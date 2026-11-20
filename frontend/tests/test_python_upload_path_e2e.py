# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""End to end: the real Go sidecar, the real UploadManager and the real Pixhost
plugin on the Python upload path, against a local fake host.

The sidecar is built from backend/ into a temporary directory. The test is
skipped when Go is not installed. It never contacts a real image host: the
Pixhost plugin's API base URL is pointed at the local fake host.
"""

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from modules import config, upload_manager
from modules.sidecar import PROCESS_RESTARTED_MSG, SidecarBridge
from modules.upload_results import UploadResult

BACKEND = Path(__file__).resolve().parents[2] / "backend"

pytestmark = [pytest.mark.integration, pytest.mark.requires_go]


@pytest.fixture(scope="module")
def sidecar_binary(tmp_path_factory):
    go = shutil.which("go")
    if go is None:
        pytest.skip("Go is not installed; the sidecar cannot be built")
    out = tmp_path_factory.mktemp("sidecar") / ("uploader.exe" if os.name == "nt" else "uploader")
    build = subprocess.run(
        [go, "build", "-o", str(out), "."],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if build.returncode != 0:
        pytest.fail(f"go build failed:\n{build.stdout}\n{build.stderr}")
    return out


class FakePixhost:
    """Answers Pixhost-style uploads: by file name, a link, a refusal or no link."""

    def __init__(self):
        self.uploads = []
        self.lock = threading.Lock()
        host = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def read_body(self):
                length = self.headers.get("Content-Length")
                if length:
                    return self.rfile.read(int(length))
                chunks = []
                while True:  # Go streams the multipart body in chunks
                    size = int(self.rfile.readline().strip() or b"0", 16)
                    if size == 0:
                        self.rfile.readline()
                        return b"".join(chunks)
                    chunks.append(self.rfile.read(size))
                    self.rfile.readline()

            def do_POST(self):
                body = self.read_body()
                message = BytesParser(policy=email_policy).parsebytes(
                    b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body
                )
                fields, name = {}, ""
                for part in message.iter_parts():
                    field = part.get_param("name", header="content-disposition")
                    if part.get_filename():
                        name = part.get_filename() if field == "img" else name
                    else:
                        fields[field] = part.get_content()
                with host.lock:
                    host.uploads.append(
                        {
                            "path": self.path,
                            "file": name,
                            "content_type": fields.get("content_type"),
                            "max_th_size": fields.get("max_th_size"),
                            "accept": self.headers.get("Accept"),
                        }
                    )
                status, body = 200, {
                    "name": name,
                    "show_url": f"https://pixhost.example/show/1/{name}",
                    "th_url": f"https://t1.pixhost.example/thumbs/1/{name}",
                }
                retry_after = None
                with host.lock:
                    tries = sum(1 for upload in host.uploads if upload["file"] == name)
                if name.startswith("toolarge"):
                    status, body = 400, {"error": "image too large"}
                elif name.startswith("nolink"):
                    body = {"show_url": "", "th_url": ""}
                elif name.startswith("busy") and tries == 1:
                    # Refused without taking it: the sidecar sends it again.
                    status, body, retry_after = 503, {"error": "busy"}, "0"
                payload = json.dumps(body).encode()
                self.send_response(status)
                if retry_after is not None:
                    self.send_header("Retry-After", retry_after)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def host():
    fake = FakePixhost()
    yield fake
    fake.close()


@pytest.fixture
def bridge(sidecar_binary, monkeypatch):
    class LocalBridge(SidecarBridge):
        def _resolve_executable(self):
            return sidecar_binary

    real = LocalBridge()
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: real))
    yield real
    real.shutdown()


class Group:
    def __init__(self, title, files):
        self.title = title
        self.files = list(files)
        self.cover_files = []


def run_batch(files, cfg, timeout=60):
    progress, results, cancel = queue.Queue(), queue.Queue(), threading.Event()
    um = upload_manager.UploadManager(progress, results, cancel)
    um.start_batch({Group("Set", files): list(files)}, cfg, {})
    statuses = {fp: [] for fp in files}
    links = {}
    deadline = time.monotonic() + timeout
    terminal = {}
    settle_until = None  # read a little longer: Go's Failed is followed by its reason
    while time.monotonic() < deadline and (settle_until is None or time.monotonic() < settle_until):
        if settle_until is None and len(terminal) == len(files):
            settle_until = time.monotonic() + 0.5
        try:
            kind, fp, value = progress.get(timeout=0.2)
        except queue.Empty:
            continue
        if kind != "status" or fp not in statuses:
            continue
        statuses[fp].append(value)
        text = str(value)
        if text in ("Done", "Cancelled", "Failed") or text.startswith("error"):
            terminal.setdefault(fp, text)
    while True:
        try:
            fp, url, thumb = results.get_nowait()
        except queue.Empty:
            break
        if url:
            links[fp] = (url, thumb)
    return um, statuses, terminal, links


def make_files(tmp_path, names):
    paths = []
    for name in names:
        path = tmp_path / name
        path.write_bytes(b"\xff\xd8\xff\xe0" + os.urandom(2048))
        paths.append(os.path.normpath(str(path)))
    return paths


def test_pixhost_uploads_end_to_end_on_the_python_path(tmp_path, host, bridge, monkeypatch):
    monkeypatch.setattr(config, "PIXHOST_API_BASE_URL", host.url)
    files = make_files(tmp_path, ["a.jpg", "b.jpg", "toolarge.jpg", "nolink.jpg", "busy.jpg"])

    um, statuses, terminal, links = run_batch(
        files, {"service": "pixhost.cc", "thumbnail_size": "250", "global_thread_limit": 2}
    )

    a, b, toolarge, nolink, busy = files
    assert terminal[a] == "Done" and terminal[b] == "Done", statuses
    # Refused once with 503: sent again before Python saw an answer.
    assert terminal[busy] == "Done", statuses[busy]
    assert links[busy][0] == "https://pixhost.example/show/1/busy.jpg"
    assert links[a] == (
        "https://pixhost.example/show/1/a.jpg",
        "https://t1.pixhost.example/thumbs/1/a.jpg",
    )
    assert terminal[toolarge] == "error: upload rejected (HTTP 400): image too large"
    assert terminal[nolink] == (
        'error: upload response had no image link (HTTP 200): {"show_url": "", "th_url": ""}'
    )
    # The sidecar reported each answer as Uploaded before Python decided.
    assert "Uploaded" in statuses[a] and statuses[a].index("Uploaded") < statuses[a].index("Done")
    # The request the host saw is the plugin's.
    sent = {upload["file"]: upload for upload in host.uploads}
    assert sent["a.jpg"] == {
        "path": "/images",
        "file": "a.jpg",
        "content_type": "0",
        "max_th_size": "250",
        "accept": "application/json",
    }
    uploads_by_file = [upload["file"] for upload in host.uploads]
    assert uploads_by_file.count("busy.jpg") == 2
    assert len(uploads_by_file) == 6, "only the refused upload is sent twice"
    # The job's transport session was closed once everything was parsed.
    deadline = time.monotonic() + 5
    while um._open_session_jobs and time.monotonic() < deadline:
        time.sleep(0.05)
    assert um._open_session_jobs == []
    um.shutdown()


def test_the_escape_hatch_uploads_the_same_files_through_the_legacy_go_parser(
    tmp_path, host, bridge, monkeypatch
):
    monkeypatch.setattr(config, "PIXHOST_API_BASE_URL", host.url)
    files = make_files(tmp_path, ["a.jpg", "toolarge.jpg"])

    um, statuses, terminal, links = run_batch(
        files, {"service": "pixhost.cc", "thumbnail_size": "250", "legacy_upload_parsing": True}
    )

    a, toolarge = files
    assert terminal[a] == "Done", statuses
    assert links[a][0] == "https://pixhost.example/show/1/a.jpg"
    assert "Uploaded" not in statuses[a], "the legacy path reports Done from Go"
    assert statuses[toolarge][-2:] == [
        "Failed",
        "error: upload rejected (HTTP 400): image too large",
    ]
    assert um._open_session_jobs == []
    um.shutdown()


# --- A sidecar crash in the middle of a job ------------------------------------------


class SlowHost:
    """Logs in, answers uploads (a "hang" file only when released) and result pages."""

    def __init__(self):
        self.release = threading.Event()
        self.paths = []
        host = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def answer(self, body):
                payload = body.encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                host.paths.append(self.path)
                self.answer("ok")

            def do_POST(self):
                length = self.headers.get("Content-Length")
                if length:
                    self.rfile.read(int(length))
                else:
                    while True:  # Go streams the multipart body in chunks
                        size = int(self.rfile.readline().strip() or b"0", 16)
                        if size == 0:
                            self.rfile.readline()
                            break
                        self.rfile.read(size)
                        self.rfile.readline()
                host.paths.append(self.path)
                if "hang" in self.path:
                    host.release.wait(30)
                try:
                    self.answer(json.dumps({"url": "https://h.example/v" + self.path}))
                except OSError:
                    pass  # the sidecar that sent it is gone

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


class FollowUpPlugin:
    """A Python-path host whose parser reads a result page for "a" files."""

    id = "crash.test"
    name = "Crash"
    metadata = {"credentials": []}

    def __init__(self, url):
        self.url = url
        self.parse_started = threading.Event()
        self.parse_gate = threading.Event()
        self.follow_ups = []

    def upload_job_options(self, config):
        return {}

    def open_upload_session(self, transport, config, creds):
        page = transport.get(self.url + "/login")
        if not page.ok:
            raise RuntimeError(page.message)
        return {}

    def build_raw_upload_request(self, file_path, config, session_values, creds):
        return {
            "url": f"{self.url}/upload/{os.path.basename(file_path)}",
            "method": "POST",
            "multipart_fields": {"file": {"type": "file", "value": file_path}},
        }

    def parse_upload_response(self, file_path, response, transport, session_values, session_state):
        link = json.loads(response.body)["url"]
        if os.path.basename(file_path).startswith("a"):
            self.parse_started.set()
            self.parse_gate.wait(20)
            page = transport.get(self.url + "/result")
            self.follow_ups.append(page)
            if not page.ok:
                return UploadResult.failed(f"result page: {page.message}")
        return UploadResult(url=link, thumb=link + "/t")


def _is_terminal(text):
    return text in ("Done", "Failed", "Cancelled") or text.startswith("error")


def test_after_a_crash_nothing_for_the_dead_session_reaches_the_new_process(
    tmp_path, bridge, monkeypatch
):
    host = SlowHost()
    plugin = FollowUpPlugin(host.url)
    bridge.restart_delay = 0.2
    # What the processes answer, to spot one told about a session it never had.
    answers = queue.Queue()
    bridge.add_listener(answers)
    files = make_files(tmp_path, ["a.jpg", "hang.jpg"])
    a, hang = files
    progress, results, cancel = queue.Queue(), queue.Queue(), threading.Event()
    um = upload_manager.UploadManager(progress, results, cancel)
    monkeypatch.setattr(um.plugin_manager, "get_plugin", lambda service_id: plugin)
    try:
        um.start_batch(
            {Group("Set", files): list(files)},
            {"service": "crash.test", "global_thread_limit": 2},
            {},
        )
        # a.jpg is being parsed and hang.jpg is still uploading when the
        # sidecar dies.
        assert plugin.parse_started.wait(20), "a.jpg was never parsed"
        deadline = time.monotonic() + 10
        while "/upload/hang.jpg" not in host.paths:
            assert time.monotonic() < deadline, "hang.jpg never reached the host"
            time.sleep(0.02)
        first = bridge.generation
        bridge.proc.kill()
        deadline = time.monotonic() + 10
        while not (bridge.generation > first and bridge.is_process_alive()):
            assert time.monotonic() < deadline, "the sidecar did not restart"
            time.sleep(0.02)
        # The parser's follow-up comes after the restart.
        plugin.parse_gate.set()

        terminal = {}
        deadline = time.monotonic() + 15
        settle_until = None
        while time.monotonic() < deadline and (
            settle_until is None or time.monotonic() < settle_until
        ):
            if settle_until is None and len(terminal) == len(files):
                settle_until = time.monotonic() + 1.0
            try:
                kind, fp, value = progress.get(timeout=0.2)
            except queue.Empty:
                continue
            if kind == "status" and _is_terminal(str(value)):
                terminal.setdefault(fp, []).append(str(value))

        assert terminal == {
            a: [f"error: result page: {PROCESS_RESTARTED_MSG}"],
            hang: [f"error: {PROCESS_RESTARTED_MSG}"],
        }, terminal
        assert [page.message for page in plugin.follow_ups] == [PROCESS_RESTARTED_MSG]
        assert "/result" not in host.paths, "the follow-up was sent"
        told = []
        while not answers.empty():
            event = answers.get_nowait()
            text = json.dumps(event)
            if "unknown transport session" in text or '"closed": "false"' in text:
                told.append(event)
        assert told == [], "the new process got requests for the dead process's session"
        assert um._open_session_jobs == []
    finally:
        bridge.remove_listener(answers)
        um.shutdown()
        host.close()
