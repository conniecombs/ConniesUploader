# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""End to end: the real Go sidecar, the real UploadManager and the real Vipr
plugin against a local fake Vipr.

The sidecar is built from backend/ (see test_python_upload_path_e2e.py); the
test is skipped when Go is not installed. It never contacts vipr.im: the
plugin's BASE_URL points at the fake host, whose home page names itself as
the upload server.

The fake host behaves like Vipr's XFileSharing site: POST / op=login sets a
session cookie, GET / shows the upload form with the session's sess_id,
/cgi-bin/upload.cgi answers with the upload result form, and POST / with
that form shows the BBCode. Each step checks the session cookie and sess_id.
"""

import os
import queue
import re
import secrets
import threading
import time
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from modules import upload_manager
from modules.plugins import vipr
from modules.sidecar import SidecarBridge
from modules.transport import build_transport_spec, execute_transport_request
from tests.test_python_upload_path_e2e import make_files, sidecar_binary  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.requires_go]

USER, PASSWORD = "vipr-user", "Tr0ub{4dor}-3x"
CREDS = {"vipr_user": USER, "vipr_pass": PASSWORD}


def code_for(file_name):
    stem = os.path.splitext(file_name)[0]
    return re.sub(r"[^a-z0-9]", "", stem.lower()) or "file"


def bbcode(code):
    return f"[URL=https://vipr.im/{code}][IMG]https://i1.vipr.im/th/00001/{code}.jpg[/IMG][/URL]"


class FakeVipr:
    """A local Vipr: login, home page, upload endpoint and result form."""

    def __init__(self):
        self.lock = threading.Lock()
        self.sessions = {}  # cookie -> sess_id
        self.logins = []
        self.uploads = []
        self.result_forms = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.barrier = None  # set to hold uploads until N are in flight
        self.slow_arrived = threading.Event()
        self.release = threading.Event()
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

            def session(self):
                cookie = self.headers.get("Cookie") or ""
                match = re.search(r"xfss=([a-z0-9]+)", cookie)
                with host.lock:
                    return host.sessions.get(match.group(1)) if match else None

            def reply(self, body, status=200, cookie=None):
                payload = body.encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                if cookie:
                    self.send_header("Set-Cookie", f"xfss={cookie}; Path=/; HttpOnly")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                sess_id = self.session() or ""
                self.reply(
                    "<html><head><title>Vipr.im</title></head><body>"
                    '<form name="file" enctype="multipart/form-data" '
                    f'action="{host.url}/cgi-bin/upload.cgi?upload_id=" method="post">'
                    f'<input type="hidden" name="sess_id" value="{sess_id}">'
                    '<input type="file" name="file_0"></form></body></html>'
                )

            def do_POST(self):
                body = self.read_body()
                if urlsplit(self.path).path == "/cgi-bin/upload.cgi":
                    return self.upload(body)
                form = {k: v[0] for k, v in parse_qs(body.decode(), keep_blank_values=True).items()}
                if form.get("op") == "login":
                    with host.lock:
                        host.logins.append(form)
                    if form.get("login") == USER and form.get("password") == PASSWORD:
                        cookie = secrets.token_hex(8)
                        with host.lock:
                            host.sessions[cookie] = "S" + secrets.token_hex(8)
                        return self.reply("<html><body>Welcome back</body></html>", cookie=cookie)
                    return self.reply(
                        '<html><body><div class="err">Incorrect Login or Password</div>'
                        '<form method="POST"><input name="login"></form></body></html>'
                    )
                with host.lock:
                    host.result_forms.append(form)
                if form.get("op") != "upload_result" or not self.session():
                    return self.reply("<html><body><p>Session expired</p></body></html>")
                return self.reply(
                    f'<html><body><textarea id="tl3">{bbcode(form.get("fn", ""))}'
                    "</textarea></body></html>"
                )

            def upload(self, body):
                message = BytesParser(policy=email_policy).parsebytes(
                    b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body
                )
                fields, name = {}, ""
                for part in message.iter_parts():
                    field = part.get_param("name", header="content-disposition")
                    if part.get_filename():
                        name = part.get_filename() if field == "file_0" else name
                    else:
                        fields[field] = part.get_content()
                sess_id = self.session()
                query = parse_qs(urlsplit(self.path).query)
                with host.lock:
                    host.uploads.append(
                        {"file": name, "fields": fields, "query": query, "sess_ok": bool(sess_id)}
                    )
                    host.in_flight += 1
                    host.max_in_flight = max(host.max_in_flight, host.in_flight)
                try:
                    if host.barrier is not None:
                        host.barrier.wait()
                    if name.startswith("slow"):
                        host.slow_arrived.set()
                        host.release.wait(20)
                        return
                finally:
                    with host.lock:
                        host.in_flight -= 1
                code, status = code_for(name), "OK"
                if not sess_id or fields.get("sess_id") != sess_id:
                    code, status = "", "Session expired"
                self.reply(
                    "<HTML><BODY><Form name='F1' action='https://vipr.im/' method='POST'>"
                    "<textarea name='op'>upload_result</textarea>"
                    "<textarea name='per_row'>750</textarea>"
                    f"<textarea name='fn'>{code}</textarea><textarea name='st'>{status}</textarea>"
                    "</Form></BODY></HTML>"
                )

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def host(monkeypatch):
    fake = FakeVipr()
    monkeypatch.setattr(vipr, "BASE_URL", fake.url + "/")
    yield fake
    fake.close()


@pytest.fixture
def bridge(sidecar_binary, monkeypatch):  # noqa: F811
    class LocalBridge(SidecarBridge):
        sent = []

        def _resolve_executable(self):
            return sidecar_binary

        def send_job(self, payload):
            self.sent.append(payload)
            return super().send_job(payload)

        def send_job_to(self, payload, generation):  # what names a session
            self.sent.append(payload)
            return super().send_job_to(payload, generation)

    real = LocalBridge()
    real.sent = []
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: real))
    yield real
    real.shutdown()


class Group:
    def __init__(self, title, files, gallery_id=""):
        self.title = title
        self.files = list(files)
        self.cover_files = []
        self.gallery_id = gallery_id


def is_terminal(status):
    text = str(status)
    return text in ("Done", "Cancelled", "Failed") or text.startswith("error")


class Batch:
    """A started batch and what the UI queues received for it."""

    def __init__(self, files, cfg, creds=CREDS, gallery_id=""):
        self.files = files
        self.progress, self.results, self.cancel = queue.Queue(), queue.Queue(), threading.Event()
        self.um = upload_manager.UploadManager(self.progress, self.results, self.cancel)
        self.statuses = {fp: [] for fp in files}
        self.links = {}
        self.um.start_batch({Group("Set", files, gallery_id): list(files)}, cfg, dict(creds))

    def pump(self, until, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not until():
            self._read(0.1)
        self._drain_results()
        return until()

    def _read(self, wait):
        try:
            kind, fp, value = self.progress.get(timeout=wait)
        except queue.Empty:
            return
        if kind == "status" and fp in self.statuses:
            self.statuses[fp].append(value)

    def _drain_results(self):
        while True:
            try:
                fp, url, thumb = self.results.get_nowait()
            except queue.Empty:
                return
            if url:
                self.links[fp] = (url, thumb)

    def terminal(self, fp):
        return next((s for s in self.statuses[fp] if is_terminal(s)), None)

    def all_terminal(self):
        return all(self.terminal(fp) for fp in self.files)

    def settle(self, seconds=0.5):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self._read(0.05)
        self._drain_results()

    def wait_closed(self, timeout=5):
        deadline = time.monotonic() + timeout
        while self.um._open_session_jobs and time.monotonic() < deadline:
            time.sleep(0.05)
        return self.um._open_session_jobs == []


def expected_link(fp):
    code = code_for(os.path.basename(fp))
    return (f"https://vipr.im/{code}", f"https://i1.vipr.im/th/00001/{code}.jpg")


def test_vipr_logs_in_once_and_uploads_three_files_concurrently_into_a_folder(
    tmp_path, host, bridge
):
    files = make_files(tmp_path, ["a.jpg", "b.jpg", "IMG {final}.jpg"])
    host.barrier = threading.Barrier(3, timeout=15)  # answers only once all three are in flight
    cfg = {"service": "vipr.im", "thumbnail_size": "250x250", "global_thread_limit": 3}

    batch = Batch(files, cfg, gallery_id="104999")
    assert batch.pump(batch.all_terminal), batch.statuses
    batch.settle()

    for fp in files:
        assert batch.terminal(fp) == "Done", batch.statuses[fp]
        assert batch.links[fp] == expected_link(fp)
        assert "Uploaded" in batch.statuses[fp], "the sidecar handed the answer to Python"
    assert host.max_in_flight == 3
    # One login for the job; the password's braces reach the host as typed.
    assert host.logins == [{"op": "login", "login": USER, "password": PASSWORD}]
    assert len(host.sessions) == 1
    [sess_id] = host.sessions.values()
    assert sorted(upload["file"] for upload in host.uploads) == sorted(
        os.path.basename(fp) for fp in files
    )
    upload_ids = set()
    for upload in host.uploads:
        assert upload["sess_ok"], "the upload rode the login's cookie"
        assert upload["fields"] == {
            "upload_type": "file",
            "sess_id": sess_id,
            "thumb_size": "250x250",
            "per_row": "750",
            "sdomain": "vipr.im",
            "fld_id": "104999",
            "tos": "1",
            "submit_btn": "Upload",
        }
        assert upload["query"]["js_on"] == ["1"] and upload["query"]["utype"] == ["reg"]
        upload_ids.update(upload["query"]["upload_id"])
    assert len(upload_ids) == 3, "every file has its own upload slot"
    # The follow-up posted each file's result form on the same session.
    assert sorted(form["fn"] for form in host.result_forms) == sorted(
        code_for(os.path.basename(fp)) for fp in files
    )
    assert all(form["op"] == "upload_result" for form in host.result_forms)
    assert batch.wait_closed()
    batch.um.shutdown()


def test_the_legacy_escape_hatch_gives_the_same_links_from_the_same_host(tmp_path, host, bridge):
    files = make_files(tmp_path, ["a.jpg", "b.jpg", "IMG {final}.jpg"])
    cfg = {"service": "vipr.im", "thumbnail_size": "250x250", "global_thread_limit": 3}

    python = Batch(files, cfg, gallery_id="104999")
    assert python.pump(python.all_terminal), python.statuses
    python.settle()
    python_uploads = list(host.uploads)
    host.uploads.clear()

    legacy = Batch(files, dict(cfg, legacy_upload_parsing=True), gallery_id="104999")
    assert legacy.pump(legacy.all_terminal), legacy.statuses
    legacy.settle()

    assert all(legacy.terminal(fp) == "Done" for fp in files), legacy.statuses
    assert "Uploaded" not in legacy.statuses[files[0]], "the legacy path reports Done from Go"
    assert legacy.links == python.links == {fp: expected_link(fp) for fp in files}

    def sent(uploads):
        return sorted(
            (u["file"], tuple(sorted((k, v) for k, v in u["fields"].items() if k != "sess_id")))
            for u in uploads
        )

    assert sent(host.uploads) == sent(python_uploads), "both paths send the same fields"
    legacy_jobs = [p for p in bridge.sent if p.get("action") == "http_upload" and "http_spec" in p]
    assert len(legacy_jobs) == 1 and "session_id" not in legacy_jobs[0]
    for um in (python.um, legacy.um):
        um.shutdown()


def test_a_wrong_password_fails_the_batch_with_vipr_s_message(tmp_path, host, bridge):
    files = make_files(tmp_path, ["a.jpg", "b.jpg"])

    batch = Batch(files, {"service": "vipr.im"}, creds={"vipr_user": USER, "vipr_pass": "wrong"})
    assert batch.pump(batch.all_terminal, timeout=30), batch.statuses
    batch.settle()

    message = (
        "error: upload session setup failed: Vipr.im login failed: Incorrect Login or Password. "
        "Check the saved username and password."
    )
    assert [batch.terminal(fp) for fp in files] == [message, message]
    assert host.uploads == [] and batch.links == {}
    assert batch.wait_closed()
    batch.um.shutdown()


def test_stop_mid_batch_cancels_the_rest_and_closes_the_session(tmp_path, host, bridge):
    files = make_files(tmp_path, ["a.jpg", "slow.jpg", "b.jpg"])
    a, slow, b = files

    batch = Batch(files, {"service": "vipr.im", "global_thread_limit": 1})
    assert batch.pump(lambda: batch.terminal(a) and host.slow_arrived.is_set(), timeout=30)
    assert batch.terminal(a) == "Done"
    [job] = [p for p in bridge.sent if p.get("action") == "http_upload"]
    session_id = job["session_id"]

    batch.cancel.set()  # Stop
    batch.um.cancel_batch()
    assert batch.pump(batch.all_terminal, timeout=30), batch.statuses
    host.release.set()  # the host answers the cancelled upload after all
    batch.settle(1.5)

    assert batch.terminal(slow) == "Cancelled" and batch.terminal(b) == "Cancelled"
    for fp in (slow, b):
        # The sidecar follows Cancelled with its reason, which the window
        # ignores for a cancelled row; nothing else may come after it.
        after = batch.statuses[fp][batch.statuses[fp].index("Cancelled") + 1 :]
        assert set(after) <= {"Cancelled", "error: Upload cancelled"}, f"later status: {after}"
    assert set(batch.links) == {a}, "no later result arrived"
    assert [u["file"] for u in host.uploads] == ["a.jpg", "slow.jpg"], "b.jpg was never sent"
    assert [form["fn"] for form in host.result_forms] == ["a"], "no follow-up after Stop"
    assert batch.wait_closed()
    # The sidecar closed the batch's session: a request on it is refused.
    late = execute_transport_request(
        build_transport_spec(host.url + "/", literal_values=True),
        service="vipr.im",
        session_id=session_id,
        bridge=bridge,
        timeout=10,
    )
    assert not late.ok and late.message in (
        "unknown transport session",
        "transport session closed",
    ), late.message
    batch.um.shutdown()
