# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""TurboImageHost on the Python upload path (v3.2.0 milestone M4).

The plugin logs in (optional) and finds the upload endpoint in
open_upload_session, builds each file's request with its own size, name and
upload id, and resolves each upload's link from Turbo's result page through
the job's ResultPageMatcher. Parsing parity with the legacy Go path is in
test_turbo_upload_parity.py, the real sidecar in test_turbo_upload_path_e2e.py.
"""

import os
import queue
import threading
import time

import pytest

from modules import upload_manager
from modules.plugins import turbo
from modules.plugins.base import uses_python_upload_parsing
from modules.plugins.turbo import TurboPlugin
from modules.transport import TransportResponse
from modules.upload_sessions import SessionState
from tests.test_python_upload_path import FakeSidecar

CREDS = {"turbo_user": "connie", "turbo_pass": "hunter2-secret"}
HOME = (
    "<script>var uploader = {endpoint: 'https://s8d8.turboimagehost.com/upload_html5.tu'};</script>"
)


def page(body, status=200, url="https://www.turboimagehost.com/"):
    return TransportResponse(True, "success", body, status, url, {}, {})


# Statuses the sidecar retries for a request sent with retry=True.
RETRIED_STATUSES = (408, 429, 500, 502, 503, 504)


class refused:  # noqa: N801 (reads like the TransportResponse helpers above)
    """A non-2xx answer; FakeTransport reports it as the real sidecar does.

    With retry=True the sidecar retries a 408/429/5xx three times and then
    reports "max retries (3) exhausted, last error: HTTP 503", without the
    body; any other status, or any status with retry=False, comes back as
    "HTTP <code>: <body>".
    """

    def __init__(self, status, body, url="https://www.turboimagehost.com/"):
        self.status, self.body, self.url = status, body, url

    def response(self, retry):
        if retry and self.status in RETRIED_STATUSES:
            message = f"max retries (3) exhausted, last error: HTTP {self.status}"
        else:
            message = f"HTTP {self.status}: {self.body.strip()}"
        return TransportResponse(False, "failed", "", 0, self.url, {}, {}, message)


class FakeTransport:
    """Answers GET/POST by URL from a dict; records every call and its retry flag."""

    def __init__(self, answers=None, cancelled=False):
        self.answers = dict(answers or {})
        self.calls = []
        self.retries = []
        self.cancelled = cancelled

    def _answer(self, url, retry):
        self.retries.append(retry)
        if self.cancelled:
            return TransportResponse(False, "cancelled", "", 0, url, {}, {}, "Upload cancelled")
        answer = self.answers[url]
        answer = answer.pop(0) if isinstance(answer, list) else answer
        return answer.response(retry) if isinstance(answer, refused) else answer

    def get(self, url, *, retry=True, **_):
        self.calls.append(("GET", url, None))
        return self._answer(url, retry)

    def post(self, url, form_fields=None, *, retry=True, **_):
        self.calls.append(("POST", url, dict(form_fields or {})))
        return self._answer(url, retry)

    def pause(self, seconds):
        return not self.cancelled


# --- Which path Turbo takes ---------------------------------------------------------


def test_turbo_parses_its_own_uploads_and_says_so():
    plugin = TurboPlugin()
    assert uses_python_upload_parsing(plugin)
    assert plugin.metadata["implementation"] == "python"
    assert plugin.upload_job_options({}) == {}, "matched by file name: no need to go one by one"


LEGACY_LINK_EXTRACTOR = (
    r"(?is)\[url=(?P<image_url>https?://[^\]]+?/p/[0-9]+/"
    r"(?P<filename>[^/\]]+?)\.html)\]\s*"
    r"\[img\](?P<thumb_url>https?://[^\]]+?)\[/img\]\s*\[/url\]"
)


def test_the_legacy_spec_is_unchanged_for_the_escape_hatch():
    spec = TurboPlugin().build_http_request(
        "/in/a.jpg", {"thumbnail_size": "350", "turbo_upload_id": "u" * 20}, {}
    )
    assert spec == {
        "url": "https://www.turboimagehost.com/upload_html5.tu",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
            "Referer": "https://www.turboimagehost.com/",
        },
        "multipart_fields": {
            "qqfile": {"type": "file", "value": "/in/a.jpg"},
            "upload_id": {"type": "text", "value": "u" * 20},
            "qquuid": {"type": "text", "value": "{upload_id}"},
            "qqfilename": {"type": "text", "value": "{filename}"},
            "qqtotalfilesize": {"type": "text", "value": "{file_size}"},
            "imcontent": {"type": "text", "value": "all"},
            "thumb_size": {"type": "text", "value": "350"},
        },
        "pre_request": {
            "action": "turbo_discover_endpoint",
            "url": "https://www.turboimagehost.com/",
            "method": "GET",
            "use_cookies": True,
            "response_type": "html",
            "extract_fields": {"endpoint": "regex:endpoint:\\s*'([^']+)'"},
        },
        "response_parser": {
            "type": "json",
            "url_path": "newUrl",
            "thumb_path": "",
            "status_path": "success",
            "success_value": "true",
            "url_template": "https://www.turboimagehost.com/p/{id}/{filename}.html",
        },
        "resolve_spec": {
            "result_url": "{url}",
            "poll_delays_ms": [500, 1000, 2000, 3000, 5000, 5000],
            "link_extractor": LEGACY_LINK_EXTRACTOR,
            "gallery_extractor": "input#imgCodeGG",
            "file_match_mode": "filename",
        },
    }


def test_the_legacy_login_chain_is_unchanged():
    spec = TurboPlugin().build_http_request(
        "/in/a.jpg", {"turbo_upload_id": "u" * 20}, {"turbo_user": " connie ", "turbo_pass": "pw"}
    )
    assert spec["pre_request"] == {
        "action": "turbo_login",
        "url": "https://www.turboimagehost.com/login.tu?",
        "method": "POST",
        "form_fields": {
            "username": "connie",
            "password": "pw",
            "remember": "y",
            "login": "Login",
        },
        "use_cookies": True,
        "response_type": "html",
        "extract_fields": {},
        "follow_up_request": {
            "action": "turbo_discover_endpoint",
            "url": "https://www.turboimagehost.com/",
            "method": "GET",
            "use_cookies": True,
            "response_type": "html",
            "extract_fields": {"endpoint": "regex:endpoint:\\s*'([^']+)'"},
        },
    }


# --- open_upload_session: login and the upload endpoint -----------------------------


def test_anonymous_session_reads_the_upload_endpoint_from_the_home_page():
    transport = FakeTransport({"https://www.turboimagehost.com/": page(HOME)})

    values = TurboPlugin().open_upload_session(transport, {}, {})

    assert transport.calls == [("GET", "https://www.turboimagehost.com/", None)]
    assert values["upload_url"] == "https://s8d8.turboimagehost.com/upload_html5.tu"
    upload_id = values["upload_id"]
    assert len(upload_id) == 20 and upload_id.isalnum() and upload_id.islower()


@pytest.mark.parametrize(
    ("endpoint", "upload_url"),
    [
        (
            "https://s8d8.turboimagehost.com/upload_html5.tu",
            "https://s8d8.turboimagehost.com/upload_html5.tu",
        ),
        ("/upload_html5.tu?srv=8", "https://www.turboimagehost.com/upload_html5.tu?srv=8"),
        ("upload2.tu", "https://www.turboimagehost.com/upload2.tu"),
        ("//s9.turboimagehost.com/u.tu", "https://s9.turboimagehost.com/u.tu"),
        ("  https://s1.turboimagehost.com/u.tu  ", "https://s1.turboimagehost.com/u.tu"),
        ("http://[broken/u.tu", "https://www.turboimagehost.com/upload_html5.tu"),
    ],
)
def test_the_endpoint_resolves_against_the_upload_script_like_the_legacy_path(endpoint, upload_url):
    home = page(f"<script>new qq.FineUploader({{request: {{endpoint: '{endpoint}'}}}});</script>")
    transport = FakeTransport({"https://www.turboimagehost.com/": home})
    assert TurboPlugin().open_upload_session(transport, {}, {})["upload_url"] == upload_url


def test_one_upload_id_per_job_the_groups_gallery_id_when_it_has_one():
    transport = FakeTransport({"https://www.turboimagehost.com/": page(HOME)})
    plugin = TurboPlugin()
    cfg = {"turbo_upload_id": "shared-upload-id"}
    assert plugin.open_upload_session(transport, cfg, {})["upload_id"] == "shared-upload-id"
    assert plugin.open_upload_session(transport, {"upload_id": "x1"}, {})["upload_id"] == "x1"
    first = plugin.open_upload_session(transport, {}, {})["upload_id"]
    assert plugin.open_upload_session(transport, {}, {})["upload_id"] != first


def test_login_posts_the_credentials_then_reads_the_endpoint_on_the_same_session():
    transport = FakeTransport(
        {
            "https://www.turboimagehost.com/login.tu?": page("<a href='/logout.tu'>Logout</a>"),
            "https://www.turboimagehost.com/": page(HOME),
        }
    )

    values = TurboPlugin().open_upload_session(
        transport, {}, {"turbo_user": " connie ", "turbo_pass": "hunter2-secret"}
    )

    assert transport.calls == [
        (
            "POST",
            "https://www.turboimagehost.com/login.tu?",
            {"username": "connie", "password": "hunter2-secret", "remember": "y", "login": "Login"},
        ),
        ("GET", "https://www.turboimagehost.com/", None),
    ]
    assert values["upload_url"] == "https://s8d8.turboimagehost.com/upload_html5.tu"
    assert "hunter2-secret" not in values.values()


LOGIN_FORM_AGAIN = """<html><body><div id="top">TurboImageHost - free image hosting</div>
<div class="error">Wrong username or password hunter2-secret</div>
<form action="login.tu" method="post"><input name="username" value="connie">
<input type="password" name="password"><input type="submit" name="login" value="Login"></form>
</body></html>"""


def test_a_refused_login_fails_the_group_with_the_hosts_message():
    transport = FakeTransport({"https://www.turboimagehost.com/login.tu?": page(LOGIN_FORM_AGAIN)})

    with pytest.raises(RuntimeError) as excinfo:
        TurboPlugin().open_upload_session(transport, {}, CREDS)

    assert str(excinfo.value) == (
        "TurboImageHost refused the login: Wrong username or password [redacted]"
    )
    assert [call[0] for call in transport.calls] == ["POST"], "no upload page after a refusal"


LOGIN_URL = "https://www.turboimagehost.com/login.tu?"


@pytest.mark.parametrize(
    ("body", "url"),
    [
        (
            '<form action="/LOGIN.tu"><input name="username"><input type="PASSWORD" name="p"></form>',
            "https://www.turboimagehost.com/",
        ),
        # A form without an action posts back to the page it is on: the login page.
        ('<form><input name="username"><input type="password" name="p"></form>', LOGIN_URL),
    ],
    ids=["action names login", "no action on the login page"],
)
def test_a_refused_login_without_a_message_still_says_what_happened(body, url):
    transport = FakeTransport({LOGIN_URL: page(body, url=url)})

    with pytest.raises(RuntimeError, match="showed its login form again"):
        TurboPlugin().open_upload_session(transport, {}, CREDS)


@pytest.mark.parametrize(
    ("body", "url"),
    [
        # Logged in, with the header's login box still on the page.
        (
            '<div id="top"><form action="login.tu" method="post"><input name="username">'
            '<input type="password" name="password"></form></div>'
            '<a href="/LogOut.tu">Sign out</a><p>Welcome back, connie</p>',
            LOGIN_URL,
        ),
        # A logout form counts as well as a logout link.
        (
            '<form action="https://www.turboimagehost.com/logout.tu" method="post">'
            "<button>Logout</button></form>"
            '<form action="login.tu"><input type="password" name="password"></form>',
            LOGIN_URL,
        ),
        # An account page with a password field that is not the login form.
        (
            '<h1>My account</h1><form action="account.tu?change=pass">'
            '<input type="password" name="new_password"></form>',
            "https://www.turboimagehost.com/account.tu",
        ),
        # A password field in a form without an action, on a page that is not the login page.
        (
            '<form><input type="password" name="new_password"></form>',
            "https://www.turboimagehost.com/account.tu",
        ),
    ],
    ids=["header login box", "logout form", "account page", "account page without action"],
)
def test_a_logged_in_page_with_a_password_field_is_not_a_refusal(body, url):
    transport = FakeTransport(
        {LOGIN_URL: page(body, url=url), "https://www.turboimagehost.com/": page(HOME)}
    )

    values = TurboPlugin().open_upload_session(transport, {}, CREDS)

    assert [call[0] for call in transport.calls] == ["POST", "GET"]
    assert values["upload_url"] == "https://s8d8.turboimagehost.com/upload_html5.tu"


@pytest.mark.parametrize(
    "creds",
    [
        {"turbo_user": "connie", "turbo_pass": ""},
        {"turbo_user": "", "turbo_pass": "hunter2-secret"},
    ],
    ids=["username only", "password only"],
)
def test_half_saved_credentials_upload_anonymously_with_a_warning(monkeypatch, creds):
    # The legacy path posted the half login and ignored Turbo's answer (the
    # login form again), so the files uploaded anonymously; so does this one.
    warnings = []
    monkeypatch.setattr(turbo.logger, "warning", warnings.append)
    transport = FakeTransport(
        {
            "https://www.turboimagehost.com/login.tu?": page(LOGIN_FORM_AGAIN),
            "https://www.turboimagehost.com/": page(HOME),
        }
    )

    values = TurboPlugin().open_upload_session(transport, {}, creds)

    assert transport.calls == [("GET", "https://www.turboimagehost.com/", None)]
    assert values["upload_url"] == "https://s8d8.turboimagehost.com/upload_html5.tu"
    assert len(warnings) == 1 and "anonymously" in warnings[0]
    assert "hunter2-secret" not in warnings[0]


def test_a_login_the_host_answers_with_an_error_status_fails_the_group():
    transport = FakeTransport(
        {
            "https://www.turboimagehost.com/login.tu?": refused(
                403, "<html><body><h1>Forbidden</h1><p>Too many logins</p></body></html>"
            )
        }
    )

    with pytest.raises(RuntimeError) as excinfo:
        TurboPlugin().open_upload_session(transport, {}, CREDS)

    assert str(excinfo.value) == "TurboImageHost login failed (HTTP 403): Forbidden Too many logins"


def test_an_upload_page_without_an_endpoint_fails_the_group():
    transport = FakeTransport(
        {"https://www.turboimagehost.com/": page("<html><title>Maintenance</title></html>")}
    )
    with pytest.raises(RuntimeError, match="no upload endpoint"):
        TurboPlugin().open_upload_session(transport, {}, {})


def test_an_upload_page_the_host_keeps_refusing_fails_the_group_after_the_retries():
    # Like the legacy pre_request, the upload page is retried on a 503; the
    # sidecar then reports the status without the page.
    transport = FakeTransport(
        {"https://www.turboimagehost.com/": refused(503, "<p>Down for maintenance</p>")}
    )
    with pytest.raises(RuntimeError) as excinfo:
        TurboPlugin().open_upload_session(transport, {}, {})
    assert str(excinfo.value) == "could not open TurboImageHost's upload page (HTTP 503)"
    assert transport.retries == [True]


def test_an_upload_page_error_that_is_not_retried_quotes_the_hosts_message():
    transport = FakeTransport(
        {"https://www.turboimagehost.com/": refused(403, "<p>Your IP is banned</p>")}
    )
    with pytest.raises(RuntimeError) as excinfo:
        TurboPlugin().open_upload_session(transport, {}, {})
    assert str(excinfo.value) == (
        "could not open TurboImageHost's upload page (HTTP 403): Your IP is banned"
    )


def test_the_login_and_the_upload_page_are_retried_like_the_legacy_pre_request():
    transport = FakeTransport(
        {
            "https://www.turboimagehost.com/login.tu?": page("<a href='/logout.tu'>Logout</a>"),
            "https://www.turboimagehost.com/": page(HOME),
        }
    )
    TurboPlugin().open_upload_session(transport, {}, CREDS)
    assert transport.retries == [True, True]


def test_a_stopped_batch_ends_the_session_step():
    with pytest.raises(RuntimeError, match="cancelled"):
        TurboPlugin().open_upload_session(FakeTransport(cancelled=True), {}, CREDS)


# --- build_raw_upload_request: the legacy request with each file's own values -------


SESSION = {"upload_url": "https://s8d8.turboimagehost.com/upload_html5.tu", "upload_id": "u" * 20}


@pytest.mark.parametrize(
    "config",
    [
        {"thumbnail_size": "350"},
        {"thumbnail_size": "180", "content_type": "adult"},
        {
            "turbo_gallery_create": True,
            "turbo_gallery_name": "Beach {2024}",
            "turbo_upload_id": "g1",
        },
        {"gallery_id": " 98765 "},
    ],
    ids=["plain", "adult and an unoffered size", "new gallery", "existing gallery"],
)
def test_raw_request_is_the_legacy_request_with_each_files_own_values(tmp_path, config):
    image = tmp_path / "Holiday {filename} #1.jpg"
    image.write_bytes(b"x" * 1234)
    plugin = TurboPlugin()
    legacy = plugin.build_http_request(str(image), config, CREDS)

    raw = plugin.build_raw_upload_request(str(image), config, SESSION, CREDS)

    assert set(raw) == {"url", "method", "headers", "multipart_fields"}
    assert raw["url"] == SESSION["upload_url"]
    assert (raw["method"], raw["headers"]) == (legacy["method"], legacy["headers"])
    want = {name: dict(field) for name, field in legacy["multipart_fields"].items()}
    want["upload_id"]["value"] = SESSION["upload_id"]
    want["qqfilename"]["value"] = "Holiday {filename} #1.jpg"  # sent literally
    want["qqtotalfilesize"]["value"] = "1234"
    want["qquuid"]["value"] = raw["multipart_fields"]["qquuid"]["value"]
    assert raw["multipart_fields"] == want
    uuid = want["qquuid"]["value"]
    assert len(uuid) == 12 and uuid.isalnum()


def test_each_file_gets_its_own_size_name_and_uuid(tmp_path):
    first, second = tmp_path / "a.jpg", tmp_path / "sub" / "a.jpg"
    second.parent.mkdir()
    first.write_bytes(b"1" * 10)
    second.write_bytes(b"2" * 20)
    plugin = TurboPlugin()

    one = plugin.build_raw_upload_request(str(first), {}, SESSION, {})["multipart_fields"]
    two = plugin.build_raw_upload_request(str(second), {}, SESSION, {})["multipart_fields"]

    assert one["qqfile"] == {"type": "file", "value": str(first)}
    assert two["qqfile"] == {"type": "file", "value": str(second)}
    assert (one["qqtotalfilesize"]["value"], two["qqtotalfilesize"]["value"]) == ("10", "20")
    assert one["qqfilename"]["value"] == two["qqfilename"]["value"] == "a.jpg"
    assert one["qquuid"]["value"] != two["qquuid"]["value"]
    assert one["upload_id"] == two["upload_id"] == {"type": "text", "value": "u" * 20}


def test_the_raw_request_carries_no_credentials(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"x")
    raw = TurboPlugin().build_raw_upload_request(str(image), {}, SESSION, CREDS)
    assert "hunter2-secret" not in repr(raw) and "pre_request" not in raw


# --- parse_upload_response ---------------------------------------------------------


class PageTransport(FakeTransport):
    """Serves the result page's successive versions; the last one repeats."""

    def __init__(self, pages):
        super().__init__()
        self.pages = list(pages)
        self.pauses = []

    def get(self, url, *, retry=True, **_):
        self.calls.append(("GET", url, None))
        self.retries.append(retry)
        answer = self.pages[min(len(self.calls), len(self.pages)) - 1]
        return answer.response(retry) if isinstance(answer, refused) else page(answer, url=url)

    def pause(self, seconds):
        self.pauses.append(seconds)
        return True


def entries(*items):
    lines = "\n".join(
        f"[URL=https://www.turboimagehost.com/p/{i}/{name}.html]"
        f"[IMG]https://s8d8.turboimg.net/t1/{i}_{name}[/IMG][/URL]"
        for i, name in items
    )
    return f'<input id="imgCodeGG" value="https://www.turboimagehost.com/album/7/Beach">\n<textarea id="imgCodeURF">{lines}</textarea>'


def upload_answer(
    body='{"success":true,"newUrl":"https://www.turboimagehost.com/upload_done.tu?id=1"}',
    status=200,
):
    return page(body, status=status, url=SESSION["upload_url"])


def test_parse_polls_the_result_page_with_the_legacy_schedule_until_the_file_is_listed():
    transport = PageTransport(
        [entries(), entries((1, "other.jpg")), entries((1, "other.jpg"), (2, "a.jpg"))]
    )
    state = SessionState(["/in/a.jpg", "/in/other.jpg"])
    state.record_uploaded("/in/a.jpg")

    result = TurboPlugin().parse_upload_response(
        "/in/a.jpg", upload_answer(), transport, SESSION, state
    )

    assert (result.url, result.thumb, result.gallery_url, result.error) == (
        "https://www.turboimagehost.com/p/2/a.jpg.html",
        "https://s8d8.turboimg.net/t1/2_a.jpg",
        "https://www.turboimagehost.com/album/7/Beach",
        "",
    )
    assert {call[1] for call in transport.calls} == {
        "https://www.turboimagehost.com/upload_done.tu?id=1"
    }
    assert transport.pauses == [0.5, 1.0]


def test_a_result_page_error_waits_for_the_next_scheduled_look_not_the_sidecars_retries():
    # The legacy resolver read the page once per look: a 503 moved on to the
    # next look of the schedule, with no retry backoff of its own.
    down = refused(503, "<p>Busy</p>", url="https://www.turboimagehost.com/upload_done.tu?id=1")
    transport = PageTransport([down, entries((2, "a.jpg"))])
    state = SessionState(["/in/a.jpg"])

    result = TurboPlugin().parse_upload_response(
        "/in/a.jpg", upload_answer(), transport, SESSION, state
    )

    assert result.ok and result.url == "https://www.turboimagehost.com/p/2/a.jpg.html"
    assert transport.retries == [False, False]
    assert transport.pauses == [0.5]


def test_parse_gives_up_after_the_legacy_schedule_with_the_reason():
    transport = PageTransport([entries((1, "other.jpg"))])
    state = SessionState(["/in/a.jpg"])

    result = TurboPlugin().parse_upload_response(
        "/in/a.jpg", upload_answer(), transport, SESSION, state
    )

    assert result.error == "resolve upload result: result page missing 1 link(s)"
    assert transport.pauses == [0.5, 1.0, 2.0, 3.0, 5.0, 5.0]


def test_a_refused_upload_fails_with_the_hosts_message_and_polls_nothing():
    transport = PageTransport([entries((1, "a.jpg"))])
    state = SessionState(["/in/a.jpg"], secrets=list(CREDS.values()))
    answer = upload_answer('{"success":false,"error":"Please log in, connie"}', status=200)

    result = TurboPlugin().parse_upload_response("/in/a.jpg", answer, transport, SESSION, state)

    assert result.error == (
        "upload failed: status check did not match (HTTP 200): Please log in, [redacted]"
    )
    assert transport.calls == []


def test_a_stop_while_polling_ends_the_file_as_cancelled():
    transport = PageTransport([entries()])
    transport.pause = lambda seconds: False  # Stop pressed during the wait
    state = SessionState(["/in/a.jpg"])

    result = TurboPlugin().parse_upload_response(
        "/in/a.jpg", upload_answer(), transport, SESSION, state
    )

    assert result.error == "Upload cancelled" and len(transport.calls) == 1


# --- Through the upload manager ------------------------------------------------------


class TurboSidecar(FakeSidecar):
    """FakeSidecar that also answers Turbo's session requests and result pages."""

    def __init__(self, pages_for):
        super().__init__()
        self.pages_for = pages_for  # result page URL -> callable returning the body
        self.http = []

    def request_with_generation(self, payload, timeout=0, cancel_event=None):
        if payload["action"] != "http_request":
            return super().request_with_generation(payload, timeout, cancel_event)
        spec = payload["generic_spec"]
        self.http.append((spec["method"], spec["url"], spec.get("session_id")))
        session_pages = {
            "https://www.turboimagehost.com/login.tu?": "<a href='/logout.tu'>Logout</a>",
            "https://www.turboimagehost.com/": HOME,
        }
        body = session_pages.get(spec["url"]) or self.pages_for[spec["url"]]()
        data = {"response_body": body, "status_code": "200", "final_url": spec["url"]}
        return {"id": payload.get("id"), "status": "success", "data": data}, self.generation


def test_concurrent_parses_of_one_job_never_share_an_entry(monkeypatch):
    names = ["cover.jpg", "back_cover.jpg", "Scan #1.jpg", "Scan #2.jpg"]
    files = [os.path.normpath(f"/in/{name}") for name in names]
    listed = []  # the result page's entries, in the order the host lists them
    lock = threading.Lock()

    def result_page():
        with lock:
            return entries(*listed)

    bridge = TurboSidecar({"https://www.turboimagehost.com/done.tu?u=1": result_page})
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
    monkeypatch.setattr(turbo, "POLL_DELAYS_MS", (5, 5, 5, 5))
    progress, results = queue.Queue(), queue.Queue()
    um = upload_manager.UploadManager(progress, results, threading.Event())
    um.current_batch_id = "b1"

    um._send_job(files, {"service": "turboimagehost", "thumbnail_size": "250"}, CREDS)

    [job] = bridge.jobs()
    assert job["raw_response"] is True and job["session_id"] == "s-1"
    assert [(m, u) for m, u, _ in bridge.http] == [
        ("POST", "https://www.turboimagehost.com/login.tu?"),
        ("GET", "https://www.turboimagehost.com/"),
    ]
    assert {sid for _, _, sid in bridge.http} == {"s-1"}
    for n, name in enumerate(reversed(names)):  # Turbo sanitizes "Scan #1.jpg"
        listed.append((100 + n, name.replace(" ", "_").replace("#", "_")))
    answer = '{"success":true,"newUrl":"https://www.turboimagehost.com/done.tu?u=1"}'
    for fp in files:
        um._handle_event(
            {
                "id": job["id"],
                "type": "result",
                "file": fp,
                "data": {"response_body": answer, "status_code": "200", "final_url": "x"},
            }
        )
    um._handle_event({"id": job["id"], "type": "batch_complete", "status": "done"})

    got = {}
    deadline = time.monotonic() + 5
    while len(got) < len(files) and time.monotonic() < deadline:
        try:
            fp, url, thumb = results.get(timeout=0.1)
        except queue.Empty:
            continue
        got[fp] = (url, thumb)
    want_ids = dict(zip(reversed(files), range(100, 104)))
    assert {fp: url.split("/p/")[1].split("/")[0] for fp, (url, _) in got.items()} == {
        fp: str(image_id) for fp, image_id in want_ids.items()
    }
    deadline = time.monotonic() + 5
    while not bridge.closes() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert [close["session_id"] for close in bridge.closes()] == ["s-1"]
    galleries = [item for item in list(progress.queue) if item[0] == "gallery_url"]
    assert {item[2] for item in galleries} == {"https://www.turboimagehost.com/album/7/Beach"}
    um.shutdown()


def test_a_full_parse_pool_never_starves_a_file_of_its_entry(monkeypatch):
    # Turbo lists "Scan #N.jpg" and "Scan_N.jpg" both as Scan_N.jpg. All
    # eight uploads answer at once; the pool's four workers poll for the
    # "Scan #N.jpg" files while the "Scan_N.jpg" files wait in its queue. In
    # Go every file resolved in its own goroutine and all eight got a link.
    assert upload_manager.POST_PROCESS_WORKERS == 4
    names = [f"Scan #{n}.jpg" for n in range(1, 5)] + [f"Scan_{n}.jpg" for n in range(1, 5)]
    files = [os.path.normpath(f"/in/{name}") for name in names]
    page_entries = [(100 + n, f"Scan_{n}.jpg") for n in range(1, 5)]
    page_entries += [(200 + n, f"Scan_{n}.jpg") for n in range(1, 5)]
    bridge = TurboSidecar(
        {"https://www.turboimagehost.com/done.tu?u=1": lambda: entries(*page_entries)}
    )
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
    monkeypatch.setattr(turbo, "POLL_DELAYS_MS", (5, 5, 5, 5))
    progress, results = queue.Queue(), queue.Queue()
    um = upload_manager.UploadManager(progress, results, threading.Event())
    um.current_batch_id = "b1"
    um._send_job(files, {"service": "turboimagehost"}, {})
    [job] = bridge.jobs()
    answer = '{"success":true,"newUrl":"https://www.turboimagehost.com/done.tu?u=1"}'
    for fp in files:
        um._handle_event(
            {
                "id": job["id"],
                "type": "result",
                "file": fp,
                "data": {"response_body": answer, "status_code": "200", "final_url": "x"},
            }
        )
    um._handle_event({"id": job["id"], "type": "batch_complete", "status": "done"})

    got = {}
    deadline = time.monotonic() + 10
    while len(got) < len(files) and time.monotonic() < deadline:
        try:
            fp, url, _ = results.get(timeout=0.1)
        except queue.Empty:
            continue
        got[fp] = url
    um.shutdown()

    failed = [item for item in list(progress.queue) if str(item[2]).startswith("error")]
    assert failed == [] and all(got.get(fp) for fp in files), failed
    ids = {fp: int(url.split("/p/")[1].split("/")[0]) for fp, url in got.items()}
    assert len(set(ids.values())) == len(files)
    for n, (hashed, underscored) in enumerate(zip(files[:4], files[4:]), start=1):
        # The two names are the same on the page: each takes one of the two entries.
        assert {ids[hashed], ids[underscored]} == {100 + n, 200 + n}


def test_covers_upload_in_their_own_job_into_the_same_gallery(monkeypatch):
    class Group:
        title = "Beach: Day #1"
        files = ["/set/cover.jpg", "/set/p1.jpg"]
        cover_files = ["/set/cover.jpg"]

    bridge = TurboSidecar({})
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
    um = upload_manager.UploadManager(queue.Queue(), queue.Queue(), threading.Event())
    um.current_batch_id = "b1"

    group = Group()
    um._dispatch_jobs(
        {group: list(group.files)},
        {"service": "turboimagehost", "auto_gallery": True, "thumbnail_size": "250"},
        {},
    )

    cover_job, other_job = bridge.jobs()
    assert (cover_job["session_id"], other_job["session_id"]) == ("s-1", "s-2")
    [cover] = cover_job["file_requests"].values()
    [other] = other_job["file_requests"].values()
    assert cover["multipart_fields"]["thumb_size"]["value"] == "600"
    assert other["multipart_fields"]["thumb_size"]["value"] == "250"
    for request in (cover, other):
        fields = request["multipart_fields"]
        assert fields["galleryC"]["value"] == "1"
        assert fields["galleryN"]["value"] == "Beach Day 1"
        assert request["url"] == "https://s8d8.turboimagehost.com/upload_html5.tu"
    # One gallery: both jobs send the group's upload id.
    assert (
        cover["multipart_fields"]["upload_id"]
        == other["multipart_fields"]["upload_id"]
        == {"type": "text", "value": group.turbo_upload_id}
    )


@pytest.fixture
def manager(monkeypatch):
    bridge = FakeSidecar()
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
    um = upload_manager.UploadManager(queue.Queue(), queue.Queue(), threading.Event())
    um.current_batch_id = "b1"
    return um, bridge


def test_the_escape_hatch_sends_turbo_through_its_legacy_spec(manager):
    um, bridge = manager
    cfg = {"service": "turboimagehost", "thumbnail_size": "250", "legacy_upload_parsing": True}

    um._send_job(["/in/a.jpg", "/in/b.jpg"], cfg, CREDS)

    [legacy] = bridge.jobs()
    assert "raw_response" not in legacy and "session_id" not in legacy
    assert legacy["http_spec"]["pre_request"]["action"] == "turbo_login"
    assert legacy["http_spec"]["response_parser"]["url_path"] == "newUrl"
    assert legacy["resolve_spec"]["file_match_mode"] == "filename"
    assert bridge.requests == [], "no transport session on the legacy path"
