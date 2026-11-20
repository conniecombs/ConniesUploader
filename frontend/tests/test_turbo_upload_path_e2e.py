# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""End to end: the real Go sidecar, the real UploadManager and the real Turbo
plugin, against a local fake TurboImageHost.

The sidecar is built from backend/ (see test_python_upload_path_e2e.py); the
tests are skipped when Go is not installed. They never contact the real host:
the plugin's BASE_URL is pointed at the fake host. Where both paths should
behave the same, a test runs on the Python path and on the legacy Go path
(the legacy_upload_parsing escape hatch) and checks both the same way.
"""

import json
import os
import queue
import threading
import time
import uuid
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from modules import upload_manager
from modules.plugins import turbo
from tests.test_python_upload_path_e2e import (  # noqa: F401 (pytest fixtures)
    Group,
    bridge,
    make_files,
    sidecar_binary,
)

pytestmark = [pytest.mark.integration, pytest.mark.requires_go]

USER, PASSWORD = "connie", "right-password-42"
ENDPOINT = "/upload/s8.tu"  # relative, as the plugin must resolve it


class FakeTurbo:
    """A TurboImageHost lookalike.

    GET / sets a session cookie and names the upload script; POST /login.tu
    logs the session in (302 to /) or shows the login form again with an
    error. Uploads need the session cookie; each is listed on the result page
    of its upload_id, for that session, once its listing delay has passed.
    Names are listed as Turbo sanitizes them (spaces and # become _).
    File names choose behaviour: "refused…" is answered 403, "missing…" is
    stored but never listed, and "hold…" gets no answer until release is set.
    """

    def __init__(self, listing_delay=None):
        self.lock = threading.Lock()
        self.listing_delay = dict(listing_delay or {})  # file name -> seconds
        self.sessions = {}  # session id -> logged-in user or None
        self.logins = []
        self.uploads = []
        self.images = {}  # image id -> image record
        self.galleries = {}  # upload_id -> (gallery id, name)
        self.result_reads = []
        self.release = threading.Event()
        self.next_id = 5000
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
                for part in cookie.split(";"):
                    name, _, value = part.strip().partition("=")
                    if name == "PHPSESSID" and value in host.sessions:
                        return value, False
                sid = uuid.uuid4().hex
                with host.lock:
                    host.sessions[sid] = None
                return sid, True

            def reply(self, status, body, content_type="text/html", headers=()):
                payload = body.encode()
                self.send_response(status)
                for name, value in headers:
                    self.send_header(name, value)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def cookie_headers(self, sid, new):
                return [("Set-Cookie", f"PHPSESSID={sid}; Path=/")] if new else []

            def do_GET(self):
                sid, new = self.session()
                url = urlsplit(self.path)
                if url.path == "/":
                    self.reply(200, host.home_page(sid), headers=self.cookie_headers(sid, new))
                elif url.path == "/upload_complete.tu":
                    upload_id = parse_qs(url.query).get("upload_id", [""])[0]
                    with host.lock:
                        host.result_reads.append((upload_id, sid, time.monotonic()))
                    self.reply(200, host.result_page(upload_id, sid))
                else:
                    self.reply(404, "<h1>Not Found</h1>")

            def do_POST(self):
                sid, new = self.session()
                body = self.read_body()
                path = urlsplit(self.path).path
                if path == "/login.tu":
                    form = {k: v[0] for k, v in parse_qs(body.decode()).items()}
                    good = (form.get("username"), form.get("password")) == (USER, PASSWORD)
                    with host.lock:
                        host.logins.append({"sid": sid, "form": form, "ok": good})
                        if good:
                            host.sessions[sid] = USER
                    if good:
                        headers = self.cookie_headers(sid, new) + [("Location", "/")]
                        self.reply(302, "", headers=headers)
                    else:
                        self.reply(200, host.login_page(), headers=self.cookie_headers(sid, new))
                elif path == ENDPOINT:
                    self.upload(sid, new, body)
                else:
                    self.reply(404, "<h1>Not Found</h1>")

            def upload(self, sid, new, body):
                message = BytesParser(policy=email_policy).parsebytes(
                    b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body
                )
                fields, name, data = {}, "", b""
                for part in message.iter_parts():
                    field = part.get_param("name", header="content-disposition")
                    if part.get_filename():
                        name, data = part.get_filename(), part.get_content()
                    else:
                        fields[field] = part.get_content()
                record = {
                    "file": name,
                    "fields": fields,
                    "sid": None if new else sid,
                    "user": host.sessions.get(sid),
                    "referer": self.headers.get("Referer"),
                    "accept": self.headers.get("Accept"),
                }
                with host.lock:
                    host.uploads.append(record)
                if new:
                    answer = {"success": False, "error": "Your upload session expired"}
                    return self.reply(403, json.dumps(answer), "application/json")
                if name.startswith("refused"):
                    answer = {"success": False, "error": "This file type is not allowed"}
                    return self.reply(403, json.dumps(answer), "application/json")
                if name.startswith("hold"):
                    host.release.wait(15)
                upload_id = fields.get("upload_id", "")
                with host.lock:
                    image_id = host.next_id
                    host.next_id += 1
                    host.images[image_id] = {
                        "name": name.replace(" ", "_").replace("#", "_"),
                        "data": data,
                        "upload_id": upload_id,
                        "sid": sid,
                        "listed_at": (
                            None
                            if name.startswith("missing")
                            else time.monotonic() + host.listing_delay.get(name, 0.0)
                        ),
                    }
                    if fields.get("galleryC") == "1" and upload_id not in host.galleries:
                        host.galleries[upload_id] = (
                            900 + len(host.galleries),
                            fields.get("galleryN", ""),
                        )
                answer = {
                    "success": True,
                    "newUrl": f"{host.url}/upload_complete.tu?upload_id={upload_id}",
                }
                self.reply(200, json.dumps(answer), "application/json")

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass  # a held upload answering after Stop finds its connection gone

        self.server = Server(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def home_page(self, sid):
        user = self.sessions.get(sid)
        if user:
            account = f'<a href="/logout.tu">Logout ({user})</a>'
        else:  # the anonymous page has a login box too
            account = (
                '<form action="/login.tu" method="post"><input name="username">'
                '<input type="password" name="password"></form>'
            )
        return (
            f"<html><body><div id='top'>{account}</div><div id='uploader'></div>"
            "<script>$('#uploader').fineUploader({request: {"
            f"endpoint: '{ENDPOINT}', params: {{}}}}}});</script></body></html>"
        )

    @staticmethod
    def login_page():
        return (
            "<html><body><div id='top'>TurboImageHost</div>"
            "<div class='error'>Wrong username or password.</div>"
            "<form action='login.tu' method='post'><input name='username'>"
            "<input type='password' name='password'>"
            "<input type='submit' name='login' value='Login'></form></body></html>"
        )

    def result_page(self, upload_id, sid):
        now = time.monotonic()
        with self.lock:
            listed = [
                (image_id, image["name"])
                for image_id, image in sorted(self.images.items())
                if image["upload_id"] == upload_id
                and image["sid"] == sid
                and image["listed_at"] is not None
                and image["listed_at"] <= now
            ]
            gallery = self.galleries.get(upload_id)
        codes = "\n".join(
            f"[URL={self.url}/p/{image_id}/{name}.html][IMG]{self.url}/t1/{image_id}_{name}[/IMG][/URL]"
            for image_id, name in listed
        )
        gallery_box = (
            f'<input type="text" id="imgCodeGG" value="{self.gallery_url(*gallery)}">'
            if gallery
            else ""
        )
        return (
            f'<html><body>{gallery_box}<textarea id="imgCodeURF">{codes}</textarea></body></html>'
        )

    def gallery_url(self, gallery_id, name):
        return f"{self.url}/album/{gallery_id}/{name.replace(' ', '_')}"

    def image_of(self, link):
        image_id = int(link.split("/p/")[1].split("/")[0])
        with self.lock:
            return self.images[image_id]

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def host_factory(monkeypatch):
    hosts = []

    def make(**kwargs):
        fake = FakeTurbo(**kwargs)
        hosts.append(fake)
        monkeypatch.setattr(turbo, "BASE_URL", fake.url)
        return fake

    yield make
    for fake in hosts:
        fake.close()


class Batch:
    """One Start of the upload manager, read from its queues."""

    def __init__(self, files, cfg, creds, title="Beach Set"):
        self.files = list(files)
        self.progress, self.results, self.cancel = queue.Queue(), queue.Queue(), threading.Event()
        self.um = upload_manager.UploadManager(self.progress, self.results, self.cancel)
        self.statuses = {fp: [] for fp in self.files}
        self.links, self.galleries, self.late = {}, {}, []
        self.stopped = False
        self.um.start_batch({Group(title, self.files): list(self.files)}, cfg, creds)

    def read(self, condition=lambda: False, timeout=30.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._drain()
            if condition():
                return True
            time.sleep(0.02)
        self._drain()
        return condition()

    def _drain(self):
        while True:
            try:
                kind, fp, value = self.progress.get_nowait()
            except queue.Empty:
                break
            if kind == "status" and fp in self.statuses:
                self.statuses[fp].append(value)
                if self.stopped and value == "Done":
                    self.late.append((fp, value))
            elif kind == "gallery_url":
                self.galleries[fp] = value
        while True:
            try:
                fp, url, thumb = self.results.get_nowait()
            except queue.Empty:
                break
            if url:
                self.links[fp] = (url, thumb)
                if self.stopped:
                    self.late.append((fp, url))

    def terminal(self, fp):
        for status in self.statuses[fp]:
            text = str(status)
            if text in ("Done", "Cancelled") or text.startswith("error"):
                return text
        return None

    def all_terminal(self):
        return all(self.terminal(fp) for fp in self.files)

    def stop(self):
        self.stopped = True
        self.cancel.set()
        self.um.cancel_batch()

    def finish(self):
        assert self.read(lambda: not self.um._open_session_jobs, 5), "session job left open"
        self.um.shutdown()


def path_config(path, **cfg):
    cfg = {"service": "turboimagehost", **cfg}
    if path == "legacy":
        cfg["legacy_upload_parsing"] = True
    return cfg


def assert_own_images(host, batch, files):
    """Each file's link and thumbnail show its own upload, and no two files share one."""
    for fp in files:
        url, thumb = batch.links[fp]
        image = host.image_of(url)
        with open(fp, "rb") as fh:
            assert image["data"] == fh.read(), f"{fp} got another file's image: {url}"
        image_id = url.split("/p/")[1].split("/")[0]
        assert url == f"{host.url}/p/{image_id}/{image['name']}.html"
        assert thumb == f"{host.url}/t1/{image_id}_{image['name']}"
    assert len({batch.links[fp][0] for fp in files}) == len(files)


@pytest.mark.parametrize("path", ["python", "legacy"])
def test_login_four_confusable_files_late_entries_and_the_gallery(
    tmp_path, bridge, host_factory, path
):
    names = ["cover.jpg", "back_cover.jpg", "Scan #1.jpg", "Scan #2.jpg"]
    # back_cover and Scan #2 are listed at once; cover and Scan #1 only after
    # a while, so their first looks find just the confusable names.
    host = host_factory(listing_delay={"cover.jpg": 0.8, "Scan #1.jpg": 0.3})
    files = make_files(tmp_path, names)
    cfg = path_config(path, thumbnail_size="350", auto_gallery=True, global_thread_limit=4)

    batch = Batch(files, cfg, {"turbo_user": USER, "turbo_pass": PASSWORD})
    assert batch.read(batch.all_terminal), batch.statuses

    assert {fp: batch.terminal(fp) for fp in files} == {fp: "Done" for fp in files}
    assert_own_images(host, batch, files)
    upload_id = host.uploads[0]["fields"]["upload_id"]
    gallery = host.gallery_url(*host.galleries[upload_id])
    assert gallery.endswith("/Beach_Set")
    assert batch.galleries == {fp: gallery for fp in files}
    # Entries listed late were found by polling the result page.
    assert len(host.result_reads) > len(files)

    # One login, and every upload and result page on that logged-in session.
    [login] = host.logins
    assert login["ok"] and login["form"] == {
        "username": USER,
        "password": PASSWORD,
        "remember": "y",
        "login": "Login",
    }
    assert {(upload["sid"], upload["user"]) for upload in host.uploads} == {(login["sid"], USER)}
    assert {(read[0], read[1]) for read in host.result_reads} == {(upload_id, login["sid"])}

    # The request each file sent: its own name, size and uuid; the job's upload_id.
    sent = {upload["file"]: upload for upload in host.uploads}
    assert sorted(sent) == sorted(names)
    for fp, name in zip(files, names):
        fields = sent[name]["fields"]
        assert fields["qqfilename"] == name
        assert fields["qqtotalfilesize"] == str(os.path.getsize(fp))
        assert len(fields["qquuid"]) == 12 and fields["qquuid"].isalnum()
        assert (fields["upload_id"], fields["galleryC"], fields["galleryN"]) == (
            upload_id,
            "1",
            "Beach Set",
        )
        assert (fields["imcontent"], fields["thumb_size"]) == ("all", "350")
        assert sent[name]["referer"] == f"{host.url}/"
    assert len({upload["fields"]["qquuid"] for upload in host.uploads}) == len(files)
    assert len(upload_id) == 20

    if path == "python":
        # The sidecar reported each answer before Python decided.
        for fp in files:
            assert batch.statuses[fp].index("Uploaded") < batch.statuses[fp].index("Done")
    else:
        assert all("Uploaded" not in batch.statuses[fp] for fp in files)
    batch.finish()


@pytest.mark.parametrize("path", ["python", "legacy"])
def test_same_names_in_two_folders_numbers_and_braces_anonymously(
    tmp_path, bridge, host_factory, path
):
    host = host_factory(listing_delay={"01.jpg": 0.25, "2.jpg": 0.25})
    (tmp_path / "setA").mkdir()
    (tmp_path / "setB").mkdir()
    names = ["setA/01.jpg", "setB/01.jpg", "2.jpg", "12.jpg", "Holiday {filename}.jpg"]
    files = make_files(tmp_path, names)

    batch = Batch(files, path_config(path, global_thread_limit=3), {})
    assert batch.read(batch.all_terminal), batch.statuses

    assert {fp: batch.terminal(fp) for fp in files} == {fp: "Done" for fp in files}
    a01, b01, two, twelve, braces = files
    assert_own_images(host, batch, [two, twelve, braces])
    # Same-named files take the entries in upload order: two distinct 01.jpg images.
    assert {host.image_of(batch.links[fp][0])["name"] for fp in (a01, b01)} == {"01.jpg"}
    assert len({batch.links[a01][0], batch.links[b01][0]}) == 2
    assert host.logins == [] and batch.galleries == {}
    sent = {upload["fields"]["qqfilename"] for upload in host.uploads}
    assert "Holiday {filename}.jpg" in sent, "braces are sent literally"
    assert {upload["user"] for upload in host.uploads} == {None}
    batch.finish()


def test_a_wrong_password_fails_the_batch_with_the_hosts_message(tmp_path, bridge, host_factory):
    host = host_factory()
    files = make_files(tmp_path, ["a.jpg", "b.jpg"])

    batch = Batch(files, path_config("python"), {"turbo_user": USER, "turbo_pass": "wrong-pass"})
    assert batch.read(batch.all_terminal), batch.statuses

    for fp in files:
        assert batch.terminal(fp) == (
            "error: upload session setup failed: TurboImageHost refused the login: "
            "Wrong username or password."
        )
    assert [login["ok"] for login in host.logins] == [False]
    assert host.uploads == [] and batch.links == {}
    batch.finish()


def test_stop_mid_batch_cancels_the_rest_and_nothing_arrives_later(tmp_path, bridge, host_factory):
    host = host_factory()
    names = ["a.jpg", "missing1.jpg", "hold1.jpg", "hold2.jpg", "b.jpg", "c.jpg"]
    files = make_files(tmp_path, names)
    a, missing, hold1, hold2, b, c = files

    batch = Batch(files, path_config("python", global_thread_limit=2), {})
    # a.jpg is done, missing1.jpg's link is being looked for on the result
    # page, and both upload slots wait for the host's answer to hold1/hold2.
    assert batch.read(
        lambda: batch.terminal(a) == "Done"
        and sum(1 for upload in host.uploads if upload["file"].startswith("hold")) == 2
        and len(host.result_reads) >= 3
    ), (batch.statuses, host.uploads)
    batch.stop()
    assert batch.read(batch.all_terminal, timeout=10), batch.statuses

    assert batch.terminal(a) == "Done"
    for fp in (missing, hold1, hold2, b, c):
        assert batch.terminal(fp) == "Cancelled", (fp, batch.statuses[fp])
    reads_at_stop = len(host.result_reads)
    host.release.set()  # the held uploads answer now, too late
    batch.read(timeout=1.0)
    assert batch.late == [], "a result arrived after Stop"
    assert len(host.result_reads) == reads_at_stop, "the result page was read after Stop"
    assert {upload["file"] for upload in host.uploads} == {
        "a.jpg",
        "missing1.jpg",
        "hold1.jpg",
        "hold2.jpg",
    }, "b.jpg and c.jpg were never sent"
    batch.finish()
