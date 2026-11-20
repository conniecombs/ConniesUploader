# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Vipr on the Python upload path (v3.2.0 milestone M4).

The plugin logs in on the job's transport session (open_upload_session),
builds each file's upload from its legacy spec with the session's values and
a per-file upload id (build_raw_upload_request), and posts the upload's
result form back to Vipr to read the BBCode links (parse_upload_response).
Parity with the legacy Go path on Vipr's pages is in test_vipr_parity.py; the
real sidecar against a fake Vipr is in test_vipr_e2e.py.
"""

import os
import queue
import re
import threading
import time
from unittest.mock import patch

import pytest

from modules import upload_manager
from modules.plugins import vipr
from modules.plugins.base import uses_python_upload_parsing
from modules.plugins.vipr import ViprPlugin, login_refusal, resolved_upload_url
from modules.sidecar import REQUEST_CANCELLED_MSG
from modules.transport import TransportResponse
from modules.upload_sessions import SessionState
from tests.test_python_upload_path import FakeSidecar

CREDS = {"vipr_user": "vipr-user", "vipr_pass": "Tr0ub{4dor}-3x", "imx_api": "other-host-key"}
SESS = "SESS7f3a9c2b1d0e"
ENDPOINT = "https://s3.vipr.im/cgi-bin/upload.cgi"
HOME = (
    '<html><body><form name="file" enctype="multipart/form-data" '
    f'action="{ENDPOINT}?upload_id=" method="post">'
    f'<input type="hidden" name="sess_id" value="{SESS}"></form></body></html>'
)
UPLOAD_FORM = (
    "<HTML><BODY><Form name='F1' action='https://vipr.im/' method='POST'>"
    "<textarea name='op'>upload_result</textarea><textarea name='per_row'>750</textarea>"
    "<textarea name='fn'>k9xq2m7v1d0a</textarea><textarea name='st'>OK</textarea>"
    "</Form></BODY></HTML>"
)
RESULT_PAGE = (
    '<textarea id="tl3">[URL=https://vipr.im/k9xq2m7v1d0a][IMG]'
    "https://i1.vipr.im/th/00512/k9xq2m7v1d0a.jpg[/IMG][/URL]</textarea>"
)


def ok(body, url=vipr.BASE_URL, status=200):
    return TransportResponse(
        ok=True,
        status="success",
        body=body,
        status_code=status,
        final_url=url,
        data={"status_code": str(status), "response_body": body},
        raw={},
    )


def refused(message, status="failed"):
    return TransportResponse(
        ok=False,
        status=status,
        body="",
        status_code=0,
        final_url="",
        data={},
        raw={},
        message=message,
    )


class Transport:
    """Answers the plugin's requests from a list of responses, in order."""

    session_id = "s-1"
    cancelled = False

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def _next(self):
        return self.responses.pop(0)

    def get(self, url, *, headers=None, timeout=None, retry=True):
        self.requests.append(("GET", url, None, retry))
        return self._next()

    def post(self, url, form_fields=None, *, headers=None, timeout=None, retry=True):
        self.requests.append(("POST", url, dict(form_fields or {}), retry))
        return self._next()


# --- Path selection and the legacy fallback -------------------------------------------


def test_vipr_is_on_the_python_path_and_says_so():
    plugin = ViprPlugin()
    assert uses_python_upload_parsing(plugin)
    assert plugin.metadata["implementation"] == "python"
    assert plugin.upload_job_options({}) == {}, "Vipr's files upload concurrently"


@pytest.fixture
def manager(monkeypatch):
    bridge = FakeSidecar()
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
    progress, results = queue.Queue(), queue.Queue()
    um = upload_manager.UploadManager(progress, results, threading.Event())
    um.current_batch_id = "b1"
    yield um, bridge, progress, results
    um.shutdown()


def test_the_escape_hatch_sends_vipr_through_its_legacy_spec(manager):
    um, bridge, _, _ = manager
    cfg = {"service": "vipr.im", "thumbnail_size": "250x250", "legacy_upload_parsing": True}

    um._send_job(["/in/a.jpg", "/in/b.jpg"], cfg, CREDS)

    [legacy] = bridge.jobs()
    assert "raw_response" not in legacy and "session_id" not in legacy
    assert bridge.requests == [], "no transport session for the legacy path"
    spec = legacy["http_spec"]
    assert spec["pre_request"]["form_fields"]["password"] == "Tr0ub{4dor}-3x"
    assert spec["multipart_fields"]["sess_id"] == {"type": "dynamic", "value": "sess_id"}
    assert spec["response_parser"]["follow_up_request"]["form_fields"]["fn"] == "{fn}"
    assert legacy["creds"] == {"vipr_user": "vipr-user", "vipr_pass": "Tr0ub{4dor}-3x"}


# --- open_upload_session: the login chain ---------------------------------------------


def test_login_posts_the_form_then_reads_the_session_and_upload_server():
    transport = Transport(ok("<html>Welcome</html>"), ok(HOME))

    values = ViprPlugin().open_upload_session(transport, {}, CREDS)

    assert values == {"sess_id": SESS, "endpoint": ENDPOINT}
    assert transport.requests == [
        (
            "POST",
            vipr.BASE_URL,
            {"op": "login", "login": "vipr-user", "password": "Tr0ub{4dor}-3x"},
            True,
        ),
        ("GET", vipr.BASE_URL, None, True),
    ]


@pytest.mark.parametrize(
    ("login_body", "message"),
    [
        (
            '<div class="err">Incorrect Login or Password</div>',
            "Vipr.im login failed: Incorrect Login or Password. "
            "Check the saved username and password.",
        ),
        (
            "<p><b>Error:</b> wrong password for vipr-user</p>",
            "Vipr.im login failed: wrong password for [redacted]. "
            "Check the saved username and password.",
        ),
        (
            "<form><input name='login'><input type='password' name='password'></form>",
            "Vipr.im login failed: no upload session after login. "
            "Check the saved username and password.",
        ),
    ],
    ids=["err-element", "plain-text", "no-message"],
)
def test_a_login_without_a_session_id_fails_the_group_with_vipr_s_message(login_body, message):
    anonymous_home = HOME.replace(SESS, "")
    transport = Transport(ok(f"<html><body>{login_body}</body></html>"), ok(anonymous_home))

    with pytest.raises(RuntimeError) as failure:
        ViprPlugin().open_upload_session(transport, {}, CREDS)

    assert str(failure.value) == message


def test_login_refusal_reads_the_usual_login_error_markup():
    assert login_refusal('<div class="alert alert-danger">Wrong username or password!</div>') == (
        "Wrong username or password!"
    )
    assert login_refusal("<span id='error'>  Your account\n was banned </span>") == (
        "Your account was banned"
    )
    assert login_refusal("<script>var e='invalid password';</script><p>Hello</p>") == ""
    assert login_refusal("<a href='/?op=forgot_pass'>Forgot your password?</a>") == ""


def test_missing_credentials_fail_before_any_request():
    transport = Transport()
    with pytest.raises(RuntimeError, match="need a username and password"):
        ViprPlugin().open_upload_session(transport, {}, {"vipr_user": "u", "vipr_pass": " "})
    assert transport.requests == []


@pytest.mark.parametrize(
    ("responses", "message"),
    [
        (
            [refused("HTTP 403: <html><body><h1>403 Forbidden</h1></body></html>")],
            "Vipr.im login failed (HTTP 403): 403 Forbidden",
        ),
        (
            [refused('Post "https://vipr.im/": dial tcp: connection refused')],
            'Vipr.im login failed: Post "https://vipr.im/": dial tcp: connection refused',
        ),
        (
            [refused(REQUEST_CANCELLED_MSG, status="cancelled")],
            f"Vipr.im login failed: {REQUEST_CANCELLED_MSG}",
        ),
        (
            [
                ok("<html>Welcome</html>"),
                refused("max retries (3) exhausted, last error: HTTP 502"),
            ],
            "could not open Vipr.im's upload page (HTTP 502)",
        ),
        (
            [
                ok("<html>Welcome</html>"),
                ok(f'<input name="sess_id" value="{SESS}"><p>Uploads are paused.</p>'),
            ],
            "Vipr.im's home page has no upload form (HTTP 200): Uploads are paused.",
        ),
    ],
    ids=["login-403", "login-unreachable", "cancelled", "home-502", "no-upload-form"],
)
def test_login_chain_failures_name_the_step_and_the_host_s_message(responses, message):
    with pytest.raises(RuntimeError) as failure:
        ViprPlugin().open_upload_session(Transport(*responses), {}, CREDS)
    assert str(failure.value) == message


def test_login_failures_never_quote_the_password():
    page = '<div class="err">Incorrect password Tr0ub{4dor}-3x for vipr-user</div>'
    transport = Transport(ok(page), ok(HOME.replace(SESS, "")))
    with pytest.raises(RuntimeError) as failure:
        ViprPlugin().open_upload_session(transport, {}, CREDS)
    assert "Tr0ub" not in str(failure.value) and "vipr-user" not in str(failure.value)
    assert "Incorrect password [redacted] for [redacted]" in str(failure.value)


# --- build_raw_upload_request ---------------------------------------------------------


def test_raw_request_is_the_legacy_request_after_the_sidecar_s_substitution(tmp_path):
    path = tmp_path / "IMG {final}.jpg"
    path.write_bytes(b"x" * 10)
    fp = str(path)
    config = {"thumbnail_size": "250x250", "vipr_gal_id": "104999", "vipr_gallery_name": "Summer"}
    session = {"sess_id": SESS, "endpoint": ENDPOINT}
    plugin = ViprPlugin()

    legacy = plugin.build_http_request(fp, config, CREDS)
    one = plugin.build_raw_upload_request(fp, config, session, CREDS)
    two = plugin.build_raw_upload_request(fp, config, session, CREDS)

    expected_fields = dict(legacy["multipart_fields"])
    expected_fields["sess_id"] = {"type": "text", "value": SESS}
    assert one["multipart_fields"] == expected_fields
    assert one["multipart_fields"]["file_0"] == {"type": "file", "value": fp}
    assert {f["type"] for f in one["multipart_fields"].values()} == {"file", "text"}
    assert (one["method"], one["headers"]) == (legacy["method"], legacy["headers"])
    # The legacy URL with {upload_id} filled in and the upload form's server.
    upload_id = one["url"].split("upload_id=")[1].split("&")[0]
    assert re.fullmatch(r"[a-z0-9]{12}", upload_id)
    legacy_url = legacy["url"].replace("https://vipr.im/cgi-bin/upload.cgi", ENDPOINT)
    assert one["url"] == legacy_url.replace("{upload_id}", upload_id)
    assert one["url"] != two["url"], "every file gets its own upload slot"
    assert "pre_request" not in one and "response_parser" not in one


@pytest.mark.parametrize(
    ("endpoint", "url"),
    [
        ("", "https://vipr.im/cgi-bin/upload.cgi?upload_id=ID&js_on=1&utype=reg&upload_type=file"),
        (
            "https://s3.vipr.im/cgi-bin/upload.cgi",
            "https://s3.vipr.im/cgi-bin/upload.cgi?upload_id=ID&js_on=1&utype=reg&upload_type=file",
        ),
        (
            "//s9.vipr.im/cgi-bin/upload.cgi",
            "https://s9.vipr.im/cgi-bin/upload.cgi?upload_id=ID&js_on=1&utype=reg&upload_type=file",
        ),
        (
            "/up/cgi-bin/upload.cgi",
            "https://vipr.im/up/cgi-bin/upload.cgi?upload_id=ID&js_on=1&utype=reg&upload_type=file",
        ),
    ],
)
def test_the_upload_goes_to_the_endpoint_with_vipr_s_query(endpoint, url):
    assert resolved_upload_url("ID", endpoint) == url


@pytest.mark.parametrize(
    ("config", "fld_id"),
    [
        # The batch's own gallery (auto-gallery or Gallery Manager assignment) first.
        (
            {"gallery_id": "batch1", "vipr_gal_id": "drop2", "selected_gallery_id": "pick3"},
            "batch1",
        ),
        # Then the gallery chosen in the dropdown.
        ({"vipr_gal_id": "drop2", "selected_gallery_id": "pick3"}, "drop2"),
        # A Gallery Manager pick fills in a dropdown gallery whose id is not known yet.
        (
            {"vipr_gal_id": "0", "vipr_gallery_name": "Summer", "selected_gallery_id": "pick3"},
            "pick3",
        ),
        ({"selected_gallery_id": "pick3"}, "pick3"),
        # "None" in the dropdown means no gallery, whatever was picked before.
        ({"vipr_gal_id": "0", "vipr_gallery_name": "None", "selected_gallery_id": "pick3"}, "0"),
        ({}, "0"),
    ],
)
def test_raw_request_uses_the_gallery_in_the_legacy_order(config, fld_id):
    request = ViprPlugin().build_raw_upload_request(
        "/in/a.jpg", config, {"sess_id": SESS, "endpoint": ENDPOINT}, CREDS
    )
    assert request["multipart_fields"]["fld_id"] == {"type": "text", "value": fld_id}


def test_a_folder_title_with_braces_is_created_as_typed():
    class Group:
        title = "[Set] Beach {HQ}"

    config = {"auto_gallery": True}
    created = {"id": "104999", "name": "Set Beach {HQ}", "url": "https://vipr.im/f/104999"}
    with patch.object(vipr.api, "create_vipr_gallery", return_value=created) as create:
        ViprPlugin().prepare_group(Group(), config, {}, CREDS)
    assert create.call_args.args[1] == "Set Beach {HQ}"
    assert config["vipr_gal_id"] == "104999"


def test_raw_request_without_a_session_fails_the_file():
    with pytest.raises(ValueError, match="no Vipr.im upload session"):
        ViprPlugin().build_raw_upload_request("/in/a.jpg", {}, {}, CREDS)


# --- parse_upload_response: the result form follow-up ---------------------------------


def state():
    return SessionState(["/in/a.jpg"], list(CREDS.values()) + [SESS, ENDPOINT])


def parse(upload, *follow_ups):
    transport = Transport(*follow_ups)
    result = ViprPlugin().parse_upload_response(
        "/in/a.jpg", upload, transport, {"sess_id": SESS, "endpoint": ENDPOINT}, state()
    )
    return result, transport


def test_the_result_form_is_posted_back_once_and_the_bbcode_read():
    result, transport = parse(ok(UPLOAD_FORM, ENDPOINT), ok(RESULT_PAGE))

    assert (result.url, result.thumb, result.gallery_url, result.error) == (
        "https://vipr.im/k9xq2m7v1d0a",
        "https://i1.vipr.im/th/00512/k9xq2m7v1d0a.jpg",
        "",
        "",
    )
    assert transport.requests == [
        (
            "POST",
            vipr.BASE_URL,
            {"fn": "k9xq2m7v1d0a", "st": "OK", "op": "upload_result", "per_row": "750"},
            False,
        )
    ]


def test_result_form_values_with_braces_are_posted_as_given():
    upload = ok(UPLOAD_FORM.replace("k9xq2m7v1d0a", "{st}{fn}"), ENDPOINT)
    _, transport = parse(upload, ok(RESULT_PAGE))
    assert transport.requests[0][2]["fn"] == "{st}{fn}"


def test_a_cancelled_follow_up_fails_without_quoting_anything():
    result, _ = parse(ok(UPLOAD_FORM, ENDPOINT), refused(REQUEST_CANCELLED_MSG, status="cancelled"))
    assert not result.ok
    assert result.error == f"response follow-up: {REQUEST_CANCELLED_MSG}"


def test_a_follow_up_that_never_answered_names_the_transport_error():
    result, _ = parse(ok(UPLOAD_FORM, ENDPOINT), refused('Post "https://vipr.im/": EOF'))
    assert result.error == 'response follow-up: Post "https://vipr.im/": EOF'


def test_a_result_page_with_a_link_but_no_thumbnail_keeps_the_link():
    page = "[URL=https://vipr.im/abc][IMG][/IMG][/URL]"
    result, _ = parse(ok(UPLOAD_FORM, ENDPOINT), ok(page))
    assert (result.url, result.thumb, result.ok) == ("https://vipr.im/abc", "", True)


def test_a_failed_raw_upload_is_reported_with_its_message():
    upload = refused("HTTP 502: <html><body>Bad Gateway</body></html>")
    result, transport = parse(upload)
    assert result.error == "upload failed (HTTP 502): Bad Gateway"
    assert transport.requests == []


# --- Through the upload manager -------------------------------------------------------


class ViprSidecar(FakeSidecar):
    """A fake sidecar whose transport requests are answered with Vipr pages."""

    def __init__(self, login_body="<html>Welcome</html>", home_body=HOME):
        super().__init__()
        self.pages = {"login": login_body, "home": home_body, "result": RESULT_PAGE}

    def request_with_generation(self, payload, timeout=0, cancel_event=None):
        if payload.get("action") != "http_request":
            return super().request_with_generation(payload, timeout, cancel_event)
        self.requests.append(payload)
        spec = payload["generic_spec"]
        if spec["method"] == "GET":
            body = self.pages["home"]
        elif spec.get("form_fields", {}).get("op") == "login":
            body = self.pages["login"]
        else:
            body = self.pages["result"]
        reply = {
            "id": payload.get("id", ""),
            "status": "success",
            "data": {"status_code": "200", "final_url": spec["url"], "response_body": body},
        }
        return reply, self.generation


@pytest.fixture
def vipr_manager(monkeypatch):
    def make(**pages):
        bridge = ViprSidecar(**pages)
        monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
        progress, results = queue.Queue(), queue.Queue()
        um = upload_manager.UploadManager(progress, results, threading.Event())
        um.current_batch_id = "b1"
        made.append(um)
        return um, bridge, progress, results

    made = []
    yield make
    for um in made:
        um.shutdown()


def is_terminal(status):
    return status in ("Done", "Cancelled") or str(status).startswith("error")


def wait_for_statuses(progress, files, timeout=5.0):
    """Each file's statuses, once every file has a terminal one."""
    seen = {fp: [] for fp in files}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(any(is_terminal(s) for s in statuses) for statuses in seen.values()):
            break
        try:
            kind, fp, value = progress.get(timeout=0.05)
        except queue.Empty:
            continue
        if kind == "status" and fp in seen:
            seen[fp].append(value)
    return seen


def test_vipr_uploads_on_a_transport_session_and_posts_the_result_form_on_it(vipr_manager):
    um, bridge, progress, results = vipr_manager()
    files = [os.path.normpath(p) for p in ("/in/a.jpg", "/in/b.jpg", "/in/c.jpg")]

    um._send_job(files, {"service": "vipr.im", "thumbnail_size": "250x250"}, CREDS)

    login, home = [r["generic_spec"] for r in bridge.requests if r["action"] == "http_request"]
    for spec in (login, home):
        assert spec["session_id"] == "s-1" and spec["literal_values"] is True
    assert login["form_fields"] == {
        "op": "login",
        "login": "vipr-user",
        "password": "Tr0ub{4dor}-3x",
    }
    [job] = bridge.jobs()
    assert job["raw_response"] is True and job["session_id"] == "s-1"
    assert job["sequential"] is False and job["creds"] == {}
    urls = {request["url"] for request in job["file_requests"].values()}
    assert len(urls) == 3 and all(url.startswith(ENDPOINT + "?upload_id=") for url in urls)
    for request in job["file_requests"].values():
        assert request["multipart_fields"]["sess_id"] == {"type": "text", "value": SESS}

    for fp in files:
        um._handle_event(
            {
                "id": job["id"],
                "type": "result",
                "file": fp,
                "data": {"response_body": UPLOAD_FORM, "status_code": "200", "final_url": ENDPOINT},
            }
        )
    um._handle_event({"id": job["id"], "type": "batch_complete", "status": "done"})
    statuses = wait_for_statuses(progress, files)

    assert all(statuses[fp][-1] == "Done" for fp in files), statuses
    links = [results.get_nowait() for _ in files]
    assert {link[1:] for link in links} == {
        ("https://vipr.im/k9xq2m7v1d0a", "https://i1.vipr.im/th/00512/k9xq2m7v1d0a.jpg")
    }
    follow_ups = [
        r["generic_spec"]
        for r in bridge.requests
        if r["action"] == "http_request" and r["generic_spec"]["method"] == "POST"
    ][1:]
    assert len(follow_ups) == 3
    for spec in follow_ups:
        assert spec["session_id"] == "s-1" and spec["url"] == vipr.BASE_URL
        assert spec["form_fields"]["op"] == "upload_result"
    deadline = time.monotonic() + 5
    while not bridge.closes() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert [close["session_id"] for close in bridge.closes()] == ["s-1"]


def test_a_wrong_password_fails_every_file_with_vipr_s_message(vipr_manager):
    um, bridge, progress, _ = vipr_manager(
        login_body='<div class="err">Incorrect Login or Password</div>',
        home_body=HOME.replace(SESS, ""),
    )
    files = ["/in/a.jpg", "/in/b.jpg"]

    um._send_job(files, {"service": "vipr.im"}, CREDS)

    assert bridge.jobs() == [], "nothing is uploaded without a login"
    statuses = [item for item in list(progress.queue) if item[0] == "status"]
    message = (
        "error: upload session setup failed: Vipr.im login failed: Incorrect Login or "
        "Password. Check the saved username and password."
    )
    assert statuses == [("status", fp, message) for fp in files]
    assert [close["session_id"] for close in bridge.closes()] == ["s-1"]


def test_a_single_file_job_redacts_the_login_session_from_its_failure(vipr_manager):
    um, bridge, progress, _ = vipr_manager()
    fp = os.path.normpath("/in/a.jpg")

    um._send_job([fp], {"service": "vipr.im"}, CREDS)
    [job] = bridge.jobs()
    um._handle_event(
        {
            "id": job["id"],
            "type": "result",
            "file": fp,
            "data": {
                "response_body": f'{{"error":"session {SESS} is not allowed to upload"}}',
                "status_code": "403",
                "final_url": ENDPOINT,
            },
        }
    )
    um._handle_event({"id": job["id"], "type": "batch_complete", "status": "done"})
    statuses = wait_for_statuses(progress, [fp])

    assert statuses[fp][-1] == (
        "error: upload rejected (HTTP 403): session [redacted] is not allowed to upload"
    )
