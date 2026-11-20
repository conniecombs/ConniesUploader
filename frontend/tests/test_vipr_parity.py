# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Parity of Vipr's Python upload path with its legacy Go path.

backend/core/testdata/vipr_parity.json holds Vipr's pages for every step
(login, home page, upload, result form follow-up): the bodies of the Go and
Python Vipr tests plus a wrong password, markup without BBCode and a
follow-up 5xx with a secret in the page. backend/core/vipr_parity_test.go
runs each case through the legacy Go path with ``legacy_spec`` and pins the
outcome. These tests run the same pages through the plugin's Python path and
check the same ``(url, thumb, gallery_url)``, the requests the host receives,
and the Python path's failure message, and that ``legacy_spec`` is the spec
the plugin builds today.
"""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from modules.plugins import vipr
from modules.plugins.vipr import ViprPlugin
from modules.transport import TransportResponse
from modules.upload_results import collect_secrets
from modules.upload_sessions import SessionState

FIXTURE = Path(__file__).resolve().parents[2] / "backend" / "core" / "testdata" / "vipr_parity.json"
DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES = DATA["cases"]
# Where the fixture's upload form sends uploads ({{SERVER}} in its pages).
UPLOAD_SERVER = "https://s3.vipr.im"
# What the sidecar's transport retries (Go's default retry config).
RETRYABLE = {408, 429, 500, 502, 503, 504}


def page_response(page, url, *, retry=True):
    """A TransportResponse as UploadTransport returns it for ``page``."""
    status, body = int(page.get("status") or 200), page["body"].replace("{{SERVER}}", UPLOAD_SERVER)
    if 200 <= status < 300:
        return TransportResponse(
            ok=True,
            status="success",
            body=body,
            status_code=status,
            final_url=url,
            data={"status_code": str(status), "final_url": url, "response_body": body},
            raw={},
        )
    if retry and status in RETRYABLE:
        message = f"max retries (3) exhausted, last error: HTTP {status}"
    else:
        message = f"HTTP {status}: {body.strip()}"
    # A refused request carries no data, only the message (handlers.go).
    return TransportResponse(
        ok=False,
        status="failed",
        body="",
        status_code=0,
        final_url=url,
        data={},
        raw={},
        message=message,
    )


class FakeViprTransport:
    """Serves one fixture case's pages and records what the plugin sent."""

    session_id = "s-vipr"
    cancelled = False

    def __init__(self, case):
        self.case = case
        self.requests = []

    def get(self, url, *, headers=None, timeout=None, retry=True):
        self.requests.append(("GET", url, None, retry))
        assert url == vipr.BASE_URL
        return page_response(self.case["home"], url, retry=retry)

    def post(self, url, form_fields=None, *, headers=None, timeout=None, retry=True):
        form = dict(form_fields or {})
        self.requests.append(("POST", url, form, retry))
        assert url == vipr.BASE_URL
        if form.get("op") == "login":
            return page_response(self.case["login"], url, retry=retry)
        assert self.case["follow_up"] is not None, "posted a result form the host never offered"
        return page_response(self.case["follow_up"], url, retry=retry)

    def posted_result_forms(self):
        return [
            form
            for method, _, form, _ in self.requests
            if method == "POST" and form.get("op") != "login"
        ]


def run_python_path(case):
    """One case through the Python path, as the upload manager drives it.

    Returns (url, thumb, gallery_url, error, transport, request).
    """
    plugin = ViprPlugin()
    transport = FakeViprTransport(case)
    try:
        session_values = plugin.open_upload_session(transport, DATA["config"], DATA["creds"])
    except RuntimeError as exc:
        return "", "", "", str(exc), transport, None
    request = plugin.build_raw_upload_request(
        DATA["file"], DATA["config"], session_values, DATA["creds"]
    )
    upload = case["upload"]
    response = TransportResponse(
        ok=True,
        status="success",
        body=upload["body"],
        status_code=int(upload["status"]),
        final_url=request["url"],
        data={},
        raw={},
    )
    # The upload manager redacts the declared credentials and every session value.
    state = SessionState([DATA["file"]], collect_secrets(DATA["creds"], session_values))
    result = plugin.parse_upload_response(DATA["file"], response, transport, session_values, state)
    return result.url, result.thumb, result.gallery_url, result.error, transport, request


def test_the_fixture_pins_the_plugins_real_legacy_spec():
    plugin = ViprPlugin()
    assert DATA["base_url"] == vipr.BASE_URL
    assert (
        plugin.build_http_request(DATA["file"], DATA["config"], DATA["creds"])
        == DATA["legacy_spec"]
    )


def test_fixtures_cover_success_refusals_markup_and_login():
    names = " | ".join(case["name"] for case in CASES)
    for needle in (
        "BBCode",
        "wrong password",
        "without BBCode",
        "follow-up 5xx",
        "upload rejected",
        "no result form",
        "login answered with an error status",
    ):
        assert needle in names
    assert sum(1 for case in CASES if case["want"]["url"]) >= 2


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_python_path_gives_the_legacy_result(case):
    url, thumb, gallery_url, error, _, _ = run_python_path(case)

    assert (url, thumb, gallery_url) == (
        case["want"]["url"],
        case["want"]["thumb"],
        case["want"]["gallery_url"],
    )
    assert error == case["python_error"]
    # Where the legacy path fails, so does the Python path, and vice versa.
    assert bool(error) == bool(case["legacy_error"])
    if case["python_error"] and not case.get("note"):
        assert case["python_error"] == case["legacy_error"], "an unexplained wording difference"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_python_path_sends_what_the_legacy_path_sends(case):
    _, _, _, _, transport, request = run_python_path(case)
    creds = DATA["creds"]

    method, url, login, retry = transport.requests[0]
    assert (method, url) == ("POST", vipr.BASE_URL)
    # The password's braces are sent as typed.
    assert login == {"op": "login", "login": creds["vipr_user"], "password": creds["vipr_pass"]}
    if case["login"]["status"] == 200:
        assert transport.requests[1][:2] == ("GET", vipr.BASE_URL)

    if case["upload"] is None:
        assert request is None, "the Python path uploads only after a login"
        return
    fields = request["multipart_fields"]
    assert fields.pop("file_0") == {"type": "file", "value": DATA["file"]}
    assert {name: field["value"] for name, field in fields.items()} == DATA["upload_fields"]
    assert {field["type"] for field in fields.values()} == {"text"}
    parts = urlsplit(request["url"])
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{UPLOAD_SERVER}/cgi-bin/upload.cgi"
    assert re.search(DATA["upload_query"], parts.query)
    assert (request["method"], request["headers"]) == ("POST", {})

    posted = transport.posted_result_forms()
    if case.get("posted_result_form"):
        assert posted == [case["posted_result_form"]]
        # One attempt, as the legacy follow-up made.
        assert transport.requests[-1][3] is False
    elif case["follow_up"] is None:
        assert posted == []
