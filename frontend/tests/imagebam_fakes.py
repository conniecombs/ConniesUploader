# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""A fake ImageBam for the ImageBam tests. Nothing here contacts imagebam.com.

``FakeImageBam`` models the site the plugin talks to: the login form and its
token, the CSRF token on the home page, upload sessions (POST
/upload/session, which may create a gallery or join one), uploads into a
session, and the session's result page. That page lists every stored image of
the session in upload order, as BBCode whose view links carry no file names.
What the site does with an upload depends on the file name's prefix
(``BEHAVIOURS``).

The model serves three kinds of test:

- ``SiteSidecar``: a FakeSidecar that answers transport requests and raw
  upload jobs from the model, so the real UploadManager and plugin run
  without Go;
- ``FakeImageBamServer``: the model over HTTP with cookies, for the real
  sidecar on both the Python path and the legacy Go specs;
- ``SCENARIOS``: upload sequences in one ImageBam session, each with the
  result the legacy path gives and the one the Python path gives (the same
  unless a difference is intended, and then ``why`` says why).

Upload sequences are taken from backend/core/resolve_upload_order_test.go and
batch_resolve_test.go (the shared session, a lost answer, a 502 after
storing, a 200 without a link, a refusal, a page listing entries late, an
entry the job cannot explain), with ImageBam's own link format, plus
ImageBam variants (a 422 validation error, ``success: false``, an HTML error
page, a gallery link, a wrong password).
"""

from __future__ import annotations

import html
import itertools
import json
import os
import queue
import socket
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import parse_qsl, urljoin, urlsplit

from tests.test_python_upload_path import FakeSidecar

SITE_URL = "https://www.imagebam.com"
VIEW_URL = "https://www.imagebam.com/view/{}"
THUMB_URL = "https://thumbs2.imagebam.com/5c/3e/{}_t.jpeg"

USER = "user@example.com"
PASSWORD = "right-pass-123"
CREDS = {"imagebam_user": USER, "imagebam_pass": PASSWORD}
LOGIN_REFUSED = "These credentials do not match our records."

JSON = "application/json"

# What the site does with an upload, by the file name's prefix ("lost_a.jpg").
BEHAVIOURS = {
    "lost": "stores the image, then closes the connection without an answer",
    "gw502": "stores the image, then answers 502 (a gateway error); a retry is a normal upload",
    "nolink": 'stores the image, then answers 200 {"error": "temporarily unavailable"}',
    "refused": 'answers 403 {"error": "not allowed"} without storing the image',
    "invalid": "answers 422 with a validation error without storing the image",
    "limit": 'answers 200 {"success": false, "message": ...} without storing the image',
    "whoops": "answers 200 with an HTML error page without storing the image",
    "late": "stores the image; the next look at the result page leaves it out",
    "hold": "waits for FakeImageBam.release before it handles the upload",
}


def lost_answer(upload_url: str) -> str:
    """The real sidecar's message for a lost answer (SiteSidecar sends the same)."""
    return (
        "no response from host after upload; check the host before retrying: "
        f'Post "{upload_url}": EOF'
    )


def behaviour_of(file_name: str) -> str:
    base = os.path.basename(str(file_name))
    return next((name for name in BEHAVIOURS if base.startswith(name + "_")), "")


def bbcode(image_id: str) -> str:
    return f"[URL={VIEW_URL.format(image_id)}][IMG]{THUMB_URL.format(image_id)}[/IMG][/URL]"


def result_page(image_ids, gallery: Optional[Mapping[str, str]] = None) -> str:
    """An upload session's result page: its gallery link and every image's BBCode."""
    link = ""
    if gallery:
        link = (
            f'<p>Gallery: <a id="gallery-name" href="{gallery["url"]}">'
            f'{html.escape(gallery["title"])}</a></p>'
        )
    codes = "\n".join(bbcode(image_id) for image_id in image_ids)
    return (
        "<html><head><title>Upload complete - ImageBam</title></head><body>"
        f'{link}<textarea id="bbcode-thumbs" readonly>{codes}</textarea></body></html>'
    )


@dataclass
class Reply:
    status: int = 200
    body: str = ""
    content_type: str = "text/html; charset=UTF-8"
    location: str = ""
    lost: bool = False  # close the connection without an answer


@dataclass
class Client:
    """One browser's cookies on the site."""

    logged_in: bool = False
    login_token: str = ""
    csrf: str = ""
    flash: str = ""


@dataclass
class UploadSession:
    token: str
    images: List[str]
    gallery: Optional[Dict[str, str]] = None


def json_reply(status: int, payload: Any) -> Reply:
    return Reply(status, json.dumps(payload), JSON)


class FakeImageBam:
    """The site. ``handle`` answers one request for one client (cookie jar).

    ``page_per_upload`` answers each upload with a page of its own that lists
    only that image (batch_resolve_test.go's session_per_upload variant).
    """

    def __init__(
        self,
        base_url: str = SITE_URL,
        *,
        preexisting=(),
        page_per_upload: bool = False,
        csrf_on_home: bool = True,
        session_reply: Optional[Tuple[int, Any]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.lock = threading.RLock()
        self.preexisting = list(preexisting)
        self.page_per_upload = page_per_upload
        self.csrf_on_home = csrf_on_home
        self.session_reply = session_reply
        self.images: Dict[str, str] = {image_id: "" for image_id in self.preexisting}
        self.sessions: Dict[str, UploadSession] = {}
        self.galleries: List[Dict[str, str]] = []
        self.requests: List[Dict[str, Any]] = []
        self.tries: Counter = Counter()
        self.hidden = ""  # an image the next look at a result page leaves out
        self.held = threading.Event()  # a "hold_" upload is waiting
        self.release = threading.Event()
        self._counter = itertools.count(1)

    def new_client(self) -> Client:
        return Client()

    # What the tests look at.

    def paths(self, method: str = "") -> List[str]:
        with self.lock:
            return [
                f"{r['method']} {r['path']}"
                for r in self.requests
                if not method or r["method"] == method
            ]

    def requests_to(self, method: str, path: str) -> List[Dict[str, Any]]:
        with self.lock:
            return [r for r in self.requests if r["method"] == method and r["path"] == path]

    def uploaded_names(self) -> List[str]:
        return [r["file"] for r in self.requests_to("POST", "/upload")]

    def image_of(self, link: str) -> str:
        """The uploaded file name behind a view link."""
        with self.lock:
            return self.images.get(link.rsplit("/", 1)[-1], "")

    # Requests.

    def handle(
        self,
        client: Client,
        method: str,
        url: str,
        headers: Optional[Mapping[str, str]] = None,
        form: Optional[Mapping[str, str]] = None,
        upload: Optional[Tuple[str, bytes]] = None,
    ) -> Reply:
        path = urlsplit(url).path or "/"
        headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        form = dict(form or {})
        with self.lock:
            self.requests.append(
                {
                    "method": method,
                    "path": path,
                    "headers": headers,
                    "form": form,
                    "file": upload[0] if upload else "",
                }
            )
        if method == "POST" and path == "/upload":
            return self._upload(client, form, upload)
        with self.lock:
            if method == "GET" and path == "/auth/login":
                return self._login_page(client)
            if method == "POST" and path == "/auth/login":
                return self._log_in(client, form)
            if method == "GET" and path == "/":
                return self._home(client)
            if method == "POST" and path == "/upload/session":
                return self._open_session(client, headers, form)
            if method == "GET" and path.startswith("/upload/complete/"):
                return self._result_page(*path[len("/upload/complete/") :].split("/")[:2])
        return Reply(404, "<html><body><h1>404 | Not Found</h1></body></html>")

    def _token(self, kind: str) -> str:
        return f"{kind}-{next(self._counter):04d}-tok"

    def _login_page(self, client: Client) -> Reply:
        client.login_token = self._token("login")
        flash = ""
        if client.flash:
            flash = f'<div class="alert alert-danger" role="alert">{client.flash}</div>'
            client.flash = ""
        return Reply(
            200,
            "<html><head><title>Login - ImageBam</title></head><body>"
            '<nav><a href="/">ImageBam</a> <a href="/auth/register">Register</a></nav>'
            f'{flash}<form method="POST" action="{self.base_url}/auth/login">'
            f'<input type="hidden" name="_token" value="{client.login_token}">'
            '<input name="email"><input name="password" type="password">'
            '<input type="checkbox" name="remember"></form></body></html>',
        )

    def _log_in(self, client: Client, form: Dict[str, str]) -> Reply:
        if not client.login_token or form.get("_token") != client.login_token:
            return Reply(419, "<html><body><h1>419 | Page Expired</h1></body></html>")
        if form.get("email") == USER and form.get("password") == PASSWORD:
            client.logged_in = True
            return Reply(302, location=f"{self.base_url}/")
        client.flash = LOGIN_REFUSED
        return Reply(302, location=f"{self.base_url}/auth/login")

    def _home(self, client: Client) -> Reply:
        if not client.csrf:
            client.csrf = self._token("csrf")
        meta = f'<meta name="csrf-token" content="{client.csrf}">' if self.csrf_on_home else ""
        account = '<a href="/auth/login">Login</a>'
        if client.logged_in:
            account = (
                f'<form action="{self.base_url}/auth/logout" method="POST">'
                "<button>Logout</button></form>"
            )
        return Reply(
            200,
            f"<html><head>{meta}<title>ImageBam - Fast and free image hosting</title></head>"
            f'<body>{account}<div id="dropzone">Drop images here</div></body></html>',
        )

    def _open_session(self, client: Client, headers: Dict[str, str], form: Dict[str, str]):
        if not client.csrf or headers.get("x-csrf-token") != client.csrf:
            return json_reply(419, {"message": "CSRF token mismatch."})
        if self.session_reply is not None:
            return json_reply(*self.session_reply)
        token = str(780000 + len(self.sessions) + 1)
        gallery = None
        if form.get("gallery") == "true" and form.get("gallery_token"):
            gallery_id = f"GX{form['gallery_token']}"
            gallery = {"id": gallery_id, "title": "Existing", "url": VIEW_URL.format(gallery_id)}
        elif form.get("gallery") == "true" and form.get("gallery_title"):
            gallery_id = f"GA{len(self.galleries) + 1:03d}"
            gallery = {
                "id": gallery_id,
                "title": form["gallery_title"],
                "url": VIEW_URL.format(gallery_id),
            }
            self.galleries.append(gallery)
        self.sessions[token] = UploadSession(token, list(self.preexisting), gallery)
        return json_reply(200, {"status": "success", "data": token, "session": f"S{token}"})

    def _upload(self, client: Client, form: Dict[str, str], upload) -> Reply:
        name = upload[0] if upload else ""
        behaviour = behaviour_of(name)
        if behaviour == "hold":
            self.held.set()
            self.release.wait(15)
        with self.lock:
            if not client.csrf or form.get("_token") != client.csrf:
                return json_reply(419, {"message": "CSRF token mismatch."})
            session = self.sessions.get(form.get("data", ""))
            if session is None:
                return json_reply(422, {"message": "Invalid upload session."})
            self.tries[name] += 1
            if behaviour == "refused":
                return json_reply(403, {"error": "not allowed"})
            if behaviour == "invalid":
                return json_reply(
                    422,
                    {
                        "message": "The given data was invalid.",
                        "errors": {"files.0": ["The files.0 must be an image."]},
                    },
                )
            if behaviour == "limit":
                return json_reply(200, {"success": False, "message": "Upload limit reached"})
            if behaviour == "whoops":
                return Reply(
                    200,
                    "<html><head><title>Server Error</title></head><body>"
                    "<h1>Whoops, looks like something went wrong.</h1></body></html>",
                )
            image_id = f"ME{len(self.images) + 1:03d}"
            self.images[image_id] = name
            session.images.append(image_id)
            if behaviour == "lost":
                return Reply(lost=True)
            if behaviour == "gw502" and self.tries[name] == 1:
                return Reply(502, "bad gateway", "text/plain")
            if behaviour == "nolink":
                return json_reply(200, {"error": "temporarily unavailable"})
            if behaviour == "late":
                self.hidden = image_id
            page = f"{self.base_url}/upload/complete/{session.token}"
            if self.page_per_upload:
                page += f"/{image_id}"
            return json_reply(200, {"success": page})

    def _result_page(self, token: str, image_id: str = "") -> Reply:
        session = self.sessions.get(token)
        if session is None or (image_id and image_id not in session.images):
            return Reply(404, "<html><body><h1>404 | Not Found</h1></body></html>")
        listed = [image_id] if image_id else session.images
        image_ids = [listed_id for listed_id in listed if listed_id != self.hidden]
        self.hidden = ""
        return Reply(200, result_page(image_ids, session.gallery))


# --- The site behind a fake sidecar (no Go) --------------------------------------------


class SiteSidecar(FakeSidecar):
    """A FakeSidecar whose requests and raw uploads reach a FakeImageBam.

    A transport request on a session uses that session's own cookies and
    follows redirects, as Go's client does; a non-2xx answer fails with
    "HTTP <code>: <body>". Each raw upload job runs on a thread and reports
    the host's answer per file (result, then Uploaded), or Failed with
    body_sent for a lost answer, then batch_complete.
    """

    def __init__(self, site: FakeImageBam) -> None:
        super().__init__()
        self.site = site
        self.clients: Dict[str, Client] = {}

    def client(self, session_id: str = "") -> Client:
        return self.clients.setdefault(str(session_id or ""), self.site.new_client())

    def fetch(self, client: Client, method: str, url: str, headers=None, form=None):
        for _ in range(10):
            reply = self.site.handle(client, method, url, headers, form)
            if reply.status in (301, 302, 303) and reply.location:
                url, method, form = urljoin(url, reply.location), "GET", None
                continue
            return reply, url
        raise AssertionError("redirect loop")

    def request_with_generation(self, payload, timeout=0, cancel_event=None):
        if payload.get("action") != "http_request":
            return super().request_with_generation(payload, timeout, cancel_event)
        self.requests.append(payload)
        spec = payload["generic_spec"]
        reply, final_url = self.fetch(
            self.client(spec.get("session_id", "")),
            spec.get("method", "GET"),
            spec["url"],
            spec.get("headers"),
            spec.get("form_fields"),
        )
        if not 200 <= reply.status < 300:
            failed = {"status": "failed", "msg": f"HTTP {reply.status}: {reply.body.strip()}"}
            return failed, self.generation
        data = {
            "response_body": reply.body,
            "status_code": str(reply.status),
            "final_url": final_url,
        }
        return {"status": "success", "data": data}, self.generation

    def send_job(self, payload):
        generation = super().send_job(payload)
        if generation is not None and payload.get("raw_response"):
            threading.Thread(target=self._run_raw_job, args=(payload,), daemon=True).start()
        return generation

    def emit(self, event: Dict[str, Any]) -> None:
        for listener in list(self.listeners):
            listener.put(event)

    def _run_raw_job(self, payload: Dict[str, Any]) -> None:
        client = self.client(payload.get("session_id", ""))
        job_id = payload["id"]
        for fp in payload["files"]:
            request = payload["file_requests"][fp]
            fields = request["multipart_fields"]
            text = {name: spec["value"] for name, spec in fields.items() if spec["type"] == "text"}
            [path] = [spec["value"] for spec in fields.values() if spec["type"] == "file"]
            reply = self.site.handle(
                client,
                request["method"],
                request["url"],
                request["headers"],
                text,
                upload=(os.path.basename(path), b"\xff\xd8"),
            )
            if reply.lost:
                failed = {"id": job_id, "type": "status", "file": fp, "status": "Failed"}
                self.emit(dict(failed, data={"body_sent": "true"}))
                error = lost_answer(request["url"])
                self.emit({"id": job_id, "type": "error", "file": fp, "msg": error})
                continue
            data = {
                "response_body": reply.body,
                "status_code": str(reply.status),
                "final_url": request["url"],
            }
            self.emit({"id": job_id, "type": "result", "file": fp, "data": data})
            self.emit({"id": job_id, "type": "status", "file": fp, "status": "Uploaded"})
        self.emit({"id": job_id, "type": "batch_complete", "status": "done"})


# --- The site over HTTP (for the real sidecar) -----------------------------------------


class FakeImageBamServer:
    """``FakeImageBam`` on a local port; each ``sid`` cookie is one client."""

    def __init__(self, **site_options) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.site = FakeImageBam(self.url, **site_options)
        self.clients: Dict[str, Client] = {}
        threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()

    def close(self) -> None:
        self.site.release.set()
        self.server.shutdown()
        self.server.server_close()

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def read_body(self) -> bytes:
                length = self.headers.get("Content-Length")
                if length:
                    return self.rfile.read(int(length))
                if "chunked" not in self.headers.get("Transfer-Encoding", ""):
                    return b""
                chunks = []
                while True:  # Go streams multipart bodies in chunks
                    size = int(self.rfile.readline().strip() or b"0", 16)
                    if size == 0:
                        self.rfile.readline()
                        return b"".join(chunks)
                    chunks.append(self.rfile.read(size))
                    self.rfile.readline()

            def client(self):
                cookies = dict(
                    part.strip().split("=", 1)
                    for part in self.headers.get("Cookie", "").split(";")
                    if "=" in part
                )
                sid = cookies.get("sid", "")
                with fake.site.lock:
                    if sid not in fake.clients:
                        sid = f"sid{len(fake.clients) + 1}"
                        fake.clients[sid] = fake.site.new_client()
                        self.new_sid = sid
                    return fake.clients[sid]

            def form(self, body: bytes):
                content_type = self.headers.get("Content-Type", "")
                if content_type.startswith("multipart/form-data"):
                    message = BytesParser(policy=email_policy).parsebytes(
                        b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
                    )
                    fields, upload = {}, None
                    for part in message.iter_parts():
                        if part.get_filename():
                            upload = (part.get_filename(), part.get_content())
                        else:
                            name = part.get_param("name", header="content-disposition")
                            fields[name] = part.get_content()
                    return fields, upload
                return dict(parse_qsl(body.decode(), keep_blank_values=True)), None

            def answer(self):
                self.new_sid = ""
                client = self.client()
                body = self.read_body() if self.command == "POST" else b""
                fields, upload = self.form(body) if body else ({}, None)
                reply = fake.site.handle(
                    client, self.command, self.path, dict(self.headers), fields, upload
                )
                if reply.lost:
                    self.close_connection = True
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    return
                payload = reply.body.encode()
                try:
                    self.send_response(reply.status)
                    if self.new_sid:
                        self.send_header("Set-Cookie", f"sid={self.new_sid}; Path=/; HttpOnly")
                    if reply.location:
                        self.send_header("Location", reply.location)
                    self.send_header("Content-Type", reply.content_type)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:
                    self.close_connection = True  # the client gave up (Stop)

            do_GET = answer
            do_POST = answer

        return Handler


# --- Running a batch through the real UploadManager ------------------------------------


class Group:
    def __init__(self, title: str, files, covers=()) -> None:
        self.title = title
        self.files = list(files)
        self.cover_files = list(covers)


@dataclass
class BatchOutcome:
    statuses: Dict[str, List[str]]
    links: Dict[str, Tuple[str, str]]
    galleries: Dict[str, str]
    manager: Any

    def final(self, fp: str) -> str:
        """The file's first terminal status (the sidecar follows Cancelled with an error)."""
        return next((status for status in self.statuses[fp] if is_terminal(status)), "")

    def link(self, fp: str) -> str:
        return self.links.get(fp, ("", ""))[0]


def is_terminal(status: str) -> bool:
    return status in ("Done", "Cancelled") or status.startswith("error")


def start_batch(groups: Mapping[Any, List[str]], cfg, creds):
    from modules import upload_manager

    progress, results, cancel = queue.Queue(), queue.Queue(), threading.Event()
    um = upload_manager.UploadManager(progress, results, cancel)
    um.start_batch({group: list(files) for group, files in groups.items()}, cfg, creds)
    return um, progress, results, cancel


def collect_batch(um, progress, results, files, timeout: float = 30.0) -> BatchOutcome:
    """Read the UI queues until every file is finished and the job's session is closed."""
    statuses: Dict[str, List[str]] = {fp: [] for fp in files}
    galleries: Dict[str, str] = {}
    deadline = time.monotonic() + timeout
    settle_until = None  # read a little longer: nothing may follow a finished row
    while time.monotonic() < deadline and (settle_until is None or time.monotonic() < settle_until):
        if settle_until is None and all(
            statuses[fp] and is_terminal(statuses[fp][-1]) for fp in files
        ):
            settle_until = time.monotonic() + 0.15
        try:
            kind, fp, value = progress.get(timeout=0.05)
        except queue.Empty:
            continue
        if kind == "gallery_url":
            galleries[fp] = value
        elif kind == "status" and fp in statuses:
            statuses[fp].append(str(value))
    while um._open_session_jobs and time.monotonic() < deadline:
        time.sleep(0.02)
    links = {}
    while True:
        try:
            fp, url, thumb = results.get_nowait()
        except queue.Empty:
            break
        if url:
            links[fp] = (url, thumb)
    return BatchOutcome(statuses, links, galleries, um)


def shut_down(um) -> None:
    """``um.shutdown()`` without waiting out the listener's one-second poll."""
    um._stop_events.set()
    um.event_queue.put({"type": "log", "msg": "test finished"})
    um.shutdown()


def run_batch(groups: Mapping[Any, List[str]], cfg, creds, timeout: float = 30.0):
    um, progress, results, _cancel = start_batch(groups, cfg, creds)
    files = [fp for group_files in groups.values() for fp in group_files]
    try:
        return collect_batch(um, progress, results, files, timeout)
    finally:
        shut_down(um)


# --- Upload sequences both paths are checked against -----------------------------------


@dataclass(frozen=True)
class Scenario:
    """Files uploaded in this order into one ImageBam upload session.

    ``legacy`` and ``python`` give each file's result: an image id ("ME002"),
    or "!" and the start of its failure message ("!" alone: any failure). The
    Python result is the legacy one unless ``python`` is set, and then ``why``
    says why the paths differ.
    """

    name: str
    files: Tuple[str, ...]
    legacy: Tuple[str, ...]
    python: Tuple[str, ...] = ()
    why: str = ""
    preexisting: Tuple[str, ...] = field(default=())
    page_per_upload: bool = False

    @property
    def want_python(self) -> Tuple[str, ...]:
        return self.python or self.legacy

    @property
    def site_options(self) -> Dict[str, Any]:
        return {"preexisting": self.preexisting, "page_per_upload": self.page_per_upload}


NO_ANSWER = "!no response from host after upload"
BAD_GATEWAY = "!upload rejected (HTTP 502): bad gateway"
RESENT_AFTER_502 = (
    "the legacy path sends the file again after a 502 and it gets the second "
    "copy; the Python path never sends an upload again after a 502, since the "
    "host may have stored it (design 7.11), so that file fails and the next "
    "files still get their own entries"
)

SCENARIOS = (
    Scenario(
        "each file of a shared session gets its own entry",
        ("cover.jpg", "a.jpg", "b.jpg", "c.jpg"),
        ("ME001", "ME002", "ME003", "ME004"),
    ),
    Scenario(
        "each upload with a result page of its own, one answer lost",
        ("a.jpg", "lost_b.jpg", "c.jpg", "d.jpg"),
        ("ME001", NO_ANSWER, "ME003", "ME004"),
        page_per_upload=True,
    ),
    Scenario(
        "a lost answer in the middle; the host stored the image",
        ("a.jpg", "lost_b.jpg", "c.jpg"),
        ("ME001", NO_ANSWER, "ME003"),
    ),
    Scenario(
        "a lost answer first",
        ("lost_a.jpg", "b.jpg", "c.jpg"),
        (NO_ANSWER, "ME002", "ME003"),
    ),
    Scenario(
        "a lost answer, then a page that lists entries late",
        ("lost_a.jpg", "late_b.jpg", "late_c.jpg"),
        (NO_ANSWER, "ME002", "ME003"),
    ),
    Scenario(
        "a 502 after the host stored the image",
        ("gw502_a.jpg", "b.jpg", "c.jpg"),
        ("ME002", "ME003", "ME004"),
        python=(BAD_GATEWAY, "ME002", "ME003"),
        why=RESENT_AFTER_502,
    ),
    Scenario(
        "a 502 after storing, then a page that lists entries late",
        ("gw502_a.jpg", "late_b.jpg", "late_c.jpg"),
        ("ME002", "ME003", "ME004"),
        python=(BAD_GATEWAY, "ME002", "ME003"),
        why=RESENT_AFTER_502,
    ),
    Scenario(
        "two failures in a row after storing",
        ("a.jpg", "lost_b.jpg", "gw502_c.jpg", "d.jpg"),
        ("ME001", NO_ANSWER, "ME004", "ME005"),
        python=("ME001", NO_ANSWER, BAD_GATEWAY, "ME004"),
        why=RESENT_AFTER_502,
    ),
    Scenario(
        "a 200 without a link after storing",
        ("nolink_a.jpg", "b.jpg", "c.jpg"),
        (
            "!upload response had no image link (HTTP 200): temporarily unavailable",
            "ME002",
            "ME003",
        ),
    ),
    Scenario(
        "a 403 refusal; nothing stored",
        ("refused_a.jpg", "b.jpg", "c.jpg"),
        ("!upload rejected (HTTP 403): not allowed", "ME001", "ME002"),
    ),
    Scenario(
        "a 422 validation error; nothing stored",
        ("invalid_a.jpg", "b.jpg"),
        ("!upload rejected (HTTP 422): The given data was invalid.", "ME001"),
    ),
    Scenario(
        "success false with the host's message",
        ("limit_a.jpg", "b.jpg"),
        ("!resolve upload result", "ME001"),
        python=("!upload response had no image link (HTTP 200): Upload limit reached", "ME001"),
        why=(
            'the legacy path takes "false" for the result page and fails after polling '
            "it; the Python path fails at once with the host's message"
        ),
    ),
    Scenario(
        "an HTML error page instead of JSON",
        ("whoops_a.jpg", "b.jpg"),
        (
            "!upload response was not valid JSON (HTTP 200): "
            "Whoops, looks like something went wrong.",
            "ME001",
        ),
    ),
    Scenario(
        "an entry the job's uploads do not explain",
        ("a.jpg", "b.jpg", "c.jpg"),
        (
            "!resolve upload result: cannot tell which result-page entry is this upload's: "
            "the page lists 2 new entries, but only 1 upload(s) reached the host",
            "ME003",
            "ME004",
        ),
        preexisting=("XX001",),
    ),
)


def outcome_matches(want: str, status: str, link: str) -> bool:
    """Whether a file's final status and link fit one Scenario expectation."""
    if want.startswith("!"):
        return status.startswith("error") and status[len("error: ") :].startswith(want[1:])
    return status == "Done" and link == VIEW_URL.format(want)
