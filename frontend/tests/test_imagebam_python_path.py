# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""ImageBam on the Python upload path (v3.2.0 milestone M4), without Go.

The plugin logs in (optional), reads the CSRF token, opens one ImageBam
upload session per job, uploads the job's files one at a time, and gives each
file the newest result-page entry after the last one the job holds
(``upload_order``). These tests run the real plugin, and the real
UploadManager where it matters, against tests/imagebam_fakes.py's fake site;
test_imagebam_e2e.py runs the same scenarios through the real sidecar on both
the Python path and the legacy Go specs.
"""

import copy
import os
import queue
import threading

import pytest

from modules import upload_manager
from modules.plugins import imagebam
from modules.plugins.base import uses_python_upload_parsing
from modules.plugins.imagebam import ImageBamPlugin
from modules.transport import TransportResponse, UploadTransport
from modules.upload_sessions import SessionState
from tests.imagebam_fakes import (
    CREDS,
    LOGIN_REFUSED,
    PASSWORD,
    SCENARIOS,
    USER,
    FakeImageBam,
    Group,
    SiteSidecar,
    outcome_matches,
    result_page,
    run_batch,
)
from tests.test_python_upload_path import FakeSidecar

SITE = "https://www.imagebam.com"
LINK_EXTRACTOR = (
    r"\[URL=(?P<image_url>https://www\.imagebam\.com/view/[^\]]+)"
    r"\]\[IMG\](?P<thumb_url>https://thumbs\d+\.imagebam\.com/[^\]]+)"
    r"\[/IMG\]\[/URL\]"
)


def legacy_spec(file_path, creds, session_fields):
    """What build_http_request returned before the migration (pinned, see below)."""
    session_request = {
        "action": "get_upload_token",
        "url": f"{SITE}/upload/session",
        "method": "POST",
        "headers": {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-TOKEN": "{csrf_token}",
            "Accept": "application/json",
            "Referer": f"{SITE}/",
        },
        "form_fields": session_fields,
        "use_cookies": True,
        "extract_fields": {"upload_token": "data", "imagebam_session": "session"},
        "response_type": "json",
    }
    pre_request = {
        "action": "get_api_csrf",
        "url": f"{SITE}/",
        "method": "GET",
        "headers": {},
        "form_fields": {},
        "use_cookies": True,
        "extract_fields": {"csrf_token": "meta[name='csrf-token']"},
        "response_type": "html",
        "follow_up_request": session_request,
    }
    if creds.get("imagebam_user") and creds.get("imagebam_pass"):
        pre_request = {
            "action": "get_login_csrf",
            "url": f"{SITE}/auth/login",
            "method": "GET",
            "headers": {},
            "form_fields": {},
            "use_cookies": True,
            "extract_fields": {"login_token": "input[name='_token']"},
            "response_type": "html",
            "follow_up_request": {
                "action": "submit_login",
                "url": f"{SITE}/auth/login",
                "method": "POST",
                "headers": {"Referer": f"{SITE}/auth/login"},
                "form_fields": {
                    "_token": "{login_token}",
                    "email": creds["imagebam_user"],
                    "password": creds["imagebam_pass"],
                    "remember": "on",
                },
                "use_cookies": True,
                "extract_fields": {"imagebam_login_marker": "form[action*='logout']"},
                "response_type": "html",
                "follow_up_request": pre_request,
            },
        }
    return {
        "url": f"{SITE}/upload",
        "method": "POST",
        "headers": {
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Referer": f"{SITE}/",
            "X-Requested-With": "XMLHttpRequest",
        },
        "pre_request": pre_request,
        "multipart_fields": {
            "files[0]": {"type": "file", "value": file_path},
            "_token": {"type": "dynamic", "value": "csrf_token"},
            "data": {"type": "dynamic", "value": "upload_token"},
        },
        "response_parser": {"type": "json", "url_path": "success", "thumb_path": ""},
        "resolve_spec": {
            "result_url": "{url}",
            "poll_delays_ms": [1000, 2000, 4000],
            "link_extractor": LINK_EXTRACTOR,
            "gallery_extractor": "a#gallery-name",
            "file_match_mode": "upload_order",
        },
    }


SESSION_FIELDS = {"thumbnail_size": "2", "content_type": "sfw", "comments_enabled": "false"}


# --- The path, and the legacy spec kept for the escape hatch --------------------------


def test_imagebam_parses_its_own_uploads_one_file_at_a_time():
    plugin = ImageBamPlugin()
    assert uses_python_upload_parsing(plugin)
    assert plugin.metadata["implementation"] == "python"
    assert plugin.upload_job_options({}) == {"sequential": True}


@pytest.mark.parametrize(
    ("config", "creds", "session_fields"),
    [
        ({}, {}, SESSION_FIELDS),
        ({}, CREDS, SESSION_FIELDS),
        (
            {"content_type": "Adult", "thumbnail_size": "300", "imagebam_gallery_title": "B {x}"},
            CREDS,
            {
                "thumbnail_size": "4",
                "content_type": "nsfw",
                "comments_enabled": "false",
                "gallery": "true",
                "gallery_token": "",
                "gallery_title": "B {x}",
            },
        ),
        (
            {"thumbnail_size": "100", "gallery_id": "490670", "imagebam_gallery_title": "B"},
            {},
            {
                "thumbnail_size": "1",
                "content_type": "sfw",
                "comments_enabled": "false",
                "gallery": "true",
                "gallery_token": "490670",
                "gallery_title": "",
            },
        ),
    ],
    ids=["anonymous", "login", "new gallery", "existing gallery"],
)
def test_the_legacy_spec_is_unchanged_for_the_escape_hatch(config, creds, session_fields):
    spec = ImageBamPlugin().build_http_request("/in/a.jpg", config, creds)
    assert spec == legacy_spec("/in/a.jpg", creds, session_fields)


def test_the_escape_hatch_sends_imagebam_through_its_legacy_spec(monkeypatch):
    bridge = FakeSidecar()
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
    um = upload_manager.UploadManager(queue.Queue(), queue.Queue(), threading.Event())
    um.current_batch_id = "b1"
    cfg = {"service": "imagebam.com", "legacy_upload_parsing": True}

    um._send_job(["/in/a.jpg", "/in/b.jpg"], cfg, CREDS)

    [job] = bridge.jobs()
    assert bridge.requests == [], "the legacy path opens no transport session"
    assert "raw_response" not in job and "session_id" not in job
    assert job["http_spec"]["pre_request"]["action"] == "get_login_csrf"
    assert job["resolve_spec"]["file_match_mode"] == "upload_order"
    assert job["creds"] == CREDS


# --- The session step ------------------------------------------------------------------


def session_on(site, session_id="s-1"):
    bridge = SiteSidecar(site)
    return UploadTransport(session_id, service="imagebam.com", bridge=bridge), bridge


def test_anonymous_session_reads_the_csrf_token_and_opens_an_upload_session():
    site = FakeImageBam()
    transport, bridge = session_on(site)

    values = ImageBamPlugin().open_upload_session(transport, {}, {})

    assert site.paths() == ["GET /", "POST /upload/session"]
    client = bridge.client("s-1")
    assert values == {
        "csrf_token": client.csrf,
        "upload_token": "780001",
        "imagebam_session": "S780001",
    }
    [opened] = site.requests_to("POST", "/upload/session")
    assert opened["form"] == SESSION_FIELDS
    assert opened["headers"] == {
        "x-requested-with": "XMLHttpRequest",
        "x-csrf-token": client.csrf,
        "accept": "application/json",
        "referer": f"{SITE}/",
    }
    assert all(r["generic_spec"]["session_id"] == "s-1" for r in bridge.requests)


def test_login_posts_the_form_token_and_credentials_before_the_session():
    site = FakeImageBam()
    transport, bridge = session_on(site)

    values = ImageBamPlugin().open_upload_session(transport, {}, CREDS)

    assert site.paths() == [
        "GET /auth/login",
        "POST /auth/login",
        "GET /",  # the redirect after the login
        "GET /",
        "POST /upload/session",
    ]
    client = bridge.client("s-1")
    assert client.logged_in
    [login] = site.requests_to("POST", "/auth/login")
    assert login["form"] == {
        "_token": client.login_token,
        "email": USER,
        "password": PASSWORD,
        "remember": "on",
    }
    assert login["headers"]["referer"] == f"{SITE}/auth/login"
    assert values["upload_token"] == "780001"


def test_a_wrong_password_fails_with_the_hosts_message():
    site = FakeImageBam()
    transport, _ = session_on(site)

    with pytest.raises(RuntimeError) as failure:
        ImageBamPlugin().open_upload_session(
            transport, {}, {"imagebam_user": USER, "imagebam_pass": "wrong-pass"}
        )

    assert str(failure.value) == f"ImageBam login failed: {LOGIN_REFUSED}"
    assert "POST /upload/session" not in site.paths()


@pytest.mark.parametrize(
    ("site", "creds", "message"),
    [
        (
            FakeImageBam(csrf_on_home=False),
            {},
            "ImageBam's page had no CSRF token (meta csrf-token)",
        ),
        (
            FakeImageBam(session_reply=(419, {"message": "CSRF token mismatch."})),
            {},
            "could not open an ImageBam upload session (HTTP 419): CSRF token mismatch.",
        ),
        (
            FakeImageBam(session_reply=(200, {"status": "error", "message": "Gallery not found"})),
            {},
            "ImageBam opened no upload session (HTTP 200): Gallery not found",
        ),
        (
            FakeImageBam(session_reply=(200, ["not", "an", "object"])),
            {},
            'ImageBam opened no upload session (HTTP 200): ["not", "an", "object"]',
        ),
    ],
    ids=["no csrf token", "session refused", "no upload token", "not an object"],
)
def test_a_session_the_host_does_not_open_fails_the_job_with_the_reason(site, creds, message):
    transport, _ = session_on(site)
    with pytest.raises(RuntimeError) as failure:
        ImageBamPlugin().open_upload_session(transport, {}, creds)
    assert str(failure.value) == message


class ScriptedTransport:
    """Answers each request with the next canned response; records what was asked."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.sent = []

    def _next(self, method, url, form=None, headers=None, retry=True):
        self.sent.append((method, url, dict(form or {}), dict(headers or {}), retry))
        return self.responses.pop(0)

    def get(self, url, *, headers=None, timeout=None, retry=True):
        return self._next("GET", url, headers=headers, retry=retry)

    def post(self, url, form_fields=None, *, headers=None, timeout=None, retry=True):
        return self._next("POST", url, form_fields, headers, retry)


def ok(body, status=200):
    return TransportResponse(True, "success", body, status, "", {}, {})


def refused(message):
    return TransportResponse(False, "failed", "", 0, "", {}, {}, message)


@pytest.mark.parametrize(
    ("responses", "message"),
    [
        (
            [refused("max retries (3) exhausted, last error: HTTP 503")],
            "could not open the ImageBam login page (HTTP 503)",
        ),
        (
            [ok("<form><input name='email'></form>")],
            "the ImageBam login page had no login form token",
        ),
        (
            [ok("<input name='_token' value='tok-1234'>"), refused("HTTP 419: Page Expired")],
            "ImageBam login failed (HTTP 419): Page Expired",
        ),
        (
            [
                ok("<input name='_token' value='tok-1234'>"),
                ok("<p class='invalid-feedback'>Too many login attempts for user@example.com.</p>"),
            ],
            "ImageBam login failed: Too many login attempts for [redacted].",
        ),
        (
            [ok("<input name='_token' value='tok-1234'>"), ok("<title>Login</title><p>Hi</p>")],
            "ImageBam login failed: the site did not log in "
            "(check the ImageBam username and password)",
        ),
    ],
    ids=["login page 503", "no form token", "login 419", "host message", "no message"],
)
def test_login_failures_name_the_hosts_answer(responses, message):
    with pytest.raises(RuntimeError) as failure:
        ImageBamPlugin().open_upload_session(ScriptedTransport(*responses), {}, CREDS)
    assert str(failure.value) == message


def test_a_cancelled_login_stops_at_once():
    cancelled = TransportResponse(False, "cancelled", "", 0, "", {}, {}, "Upload cancelled")
    transport = ScriptedTransport(cancelled)
    with pytest.raises(RuntimeError) as failure:
        ImageBamPlugin().open_upload_session(transport, {}, CREDS)
    assert str(failure.value) == "could not open the ImageBam login page: Upload cancelled"
    assert len(transport.sent) == 1


def test_a_gallery_title_with_braces_is_sent_literally():
    site = FakeImageBam()
    transport, _ = session_on(site)
    title = "{csrf_token} Beach {2024} {upload_token}"

    ImageBamPlugin().open_upload_session(transport, {"imagebam_gallery_title": title}, CREDS)

    [opened] = site.requests_to("POST", "/upload/session")
    assert opened["form"]["gallery_title"] == title
    assert site.galleries[0]["title"] == title


@pytest.mark.parametrize(
    ("config", "retry"),
    [
        ({"imagebam_gallery_title": "New"}, False),
        ({"imagebam_gallery_title": "New", "gallery_id": "490670"}, True),
        ({}, True),
    ],
    ids=["creates a gallery", "joins a gallery", "no gallery"],
)
def test_a_session_that_creates_a_gallery_is_never_sent_twice(config, retry):
    transport = ScriptedTransport(
        ok('<meta name="csrf-token" content="csrf-1234">'),
        ok('{"data": "780001", "session": "S1"}'),
    )
    ImageBamPlugin().open_upload_session(transport, config, {})
    assert transport.sent[-1][4] is retry


def test_the_login_and_the_home_page_are_retried_like_the_legacy_pre_request():
    transport = ScriptedTransport(
        ok("<input name='_token' value='tok-1234'>"),
        ok("<form action='https://www.imagebam.com/auth/logout'></form>"),
        ok('<meta name="csrf-token" content="csrf-1234">'),
        ok('{"data": "780001", "session": "S1"}'),
    )
    ImageBamPlugin().open_upload_session(transport, {}, CREDS)
    assert [(sent[0], sent[1], sent[4]) for sent in transport.sent] == [
        ("GET", f"{SITE}/auth/login", True),
        ("POST", f"{SITE}/auth/login", True),
        ("GET", f"{SITE}/", True),
        ("POST", f"{SITE}/upload/session", True),
    ]


@pytest.mark.parametrize(
    ("config", "token"),
    [
        ({"imagebam_gallery_id": "490670"}, "490670"),
        ({"gallery_id": "490671"}, "490671"),
        ({"imx_gallery_id": "IMX1", "turbo_gallery_id": "777", "pix_gallery_hash": "h"}, ""),
        ({"imagebam_gallery_id": "0"}, ""),
    ],
    ids=["its own key", "the plain field", "other hosts' galleries", "none"],
)
def test_the_gallery_comes_from_imagebams_own_settings(config, token):
    site = FakeImageBam()
    transport, _ = session_on(site)
    ImageBamPlugin().open_upload_session(transport, config, {})
    [opened] = site.requests_to("POST", "/upload/session")
    assert opened["form"].get("gallery_token", "") == token


# --- The upload request ------------------------------------------------------------------


def test_the_upload_request_is_the_legacy_one_with_the_session_values_filled_in():
    plugin = ImageBamPlugin()
    values = {"csrf_token": "csrf-1234", "upload_token": "780001", "imagebam_session": "S1"}
    legacy = plugin.build_http_request("/in/a b.jpg", {}, CREDS)

    raw = plugin.build_raw_upload_request("/in/a b.jpg", {}, values, CREDS)

    assert raw == {
        "url": legacy["url"],
        "method": legacy["method"],
        "headers": legacy["headers"],
        "multipart_fields": {
            "files[0]": {"type": "file", "value": "/in/a b.jpg"},
            "_token": {"type": "text", "value": "csrf-1234"},
            "data": {"type": "text", "value": "780001"},
        },
    }


# --- Parsing one answer ------------------------------------------------------------------


class PageTransport:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.gets = []
        self.retries = []

    def get(self, url, *, retry=True, **_):
        self.gets.append(url)
        self.retries.append(retry)
        return ok(self.pages[min(len(self.gets), len(self.pages)) - 1])

    def pause(self, seconds):
        return True


def parse(body, transport, status=200, files=("/in/a.jpg",), secrets=()):
    state = SessionState(files, secrets)
    response = TransportResponse(True, "success", body, status, f"{SITE}/upload", {}, {})
    return ImageBamPlugin().parse_upload_response(files[0], response, transport, {}, state)


def test_an_answer_is_resolved_on_its_result_page_with_the_gallery_link():
    gallery = {"url": "https://www.imagebam.com/view/GA001", "title": "Beach"}
    transport = PageTransport(result_page(["ME001"], gallery))

    result = parse('{"success": "https://www.imagebam.com/upload/complete/780001"}', transport)

    assert (result.url, result.thumb, result.gallery_url, result.error) == (
        "https://www.imagebam.com/view/ME001",
        "https://thumbs2.imagebam.com/5c/3e/ME001_t.jpeg",
        "https://www.imagebam.com/view/GA001",
        "",
    )
    assert transport.gets == ["https://www.imagebam.com/upload/complete/780001"]
    assert transport.retries == [False], "a failed look waits for the next poll, as before"


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (
            422,
            '{"message": "The given data was invalid.", "errors": {"files.0": ["bad"]}}',
            "upload rejected (HTTP 422): The given data was invalid.",
        ),
        (
            200,
            '{"success": false, "message": "Upload limit reached"}',
            "upload response had no image link (HTTP 200): Upload limit reached",
        ),
        (
            200,
            '{"success": "complete/780001"}',
            'upload response had no image link (HTTP 200): {"success": "complete/780001"}',
        ),
        (
            200,
            '{"status": "ok"}',
            'upload response had no image link (HTTP 200): {"status": "ok"}',
        ),
        (
            419,
            '{"message": "CSRF token mismatch for csrf-secret-77."}',
            "upload rejected (HTTP 419): CSRF token mismatch for [redacted].",
        ),
    ],
    ids=["422", "success false", "not a link", "no link", "redacted"],
)
def test_an_answer_without_a_result_page_fails_with_the_hosts_message(status, body, error):
    transport = PageTransport()
    result = parse(body, transport, status=status, secrets=["csrf-secret-77"])
    assert result.error == error and not result.ok
    assert transport.gets == [], "no result page to poll"


def test_a_page_without_this_upload_fails_after_the_last_look(monkeypatch):
    monkeypatch.setattr(imagebam, "RESULT_POLL_DELAYS_MS", (1, 1, 1))
    transport = PageTransport(result_page([]))
    result = parse('{"success": "https://www.imagebam.com/upload/complete/1"}', transport)
    assert result.error == "resolve upload result: result page missing 1 link(s)"
    assert len(transport.gets) == 4


# --- Whole jobs through the real UploadManager (no Go) -----------------------------------


@pytest.fixture
def imagebam_site(monkeypatch):
    """A FakeImageBam behind a SiteSidecar, with short result-page polls."""
    monkeypatch.setattr(imagebam, "RESULT_POLL_DELAYS_MS", (5, 10, 20))

    def make(**options):
        site = FakeImageBam(**options)
        bridge = SiteSidecar(site)
        monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
        return site, bridge

    return make


def paths(names):
    return [os.path.normpath(f"/set/{name}") for name in names]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_each_file_gets_its_own_upload_like_the_legacy_path(imagebam_site, scenario):
    site, bridge = imagebam_site(**scenario.site_options)
    files = paths(scenario.files)

    outcome = run_batch({Group("Set", files): files}, {"service": "imagebam.com"}, CREDS)

    got = {os.path.basename(fp): (outcome.final(fp), outcome.link(fp)) for fp in files}
    for fp, want in zip(files, scenario.want_python):
        status, link = got[os.path.basename(fp)]
        assert outcome_matches(want, status, link), (scenario.name, got)
        if status == "Done":
            assert site.image_of(link) == os.path.basename(fp), "another file's image"
            assert outcome.links[fp][1].endswith(f"/{link.rsplit('/', 1)[1]}_t.jpeg")
    # One login, one upload session; one raw job per file, in order, on it.
    assert len(site.requests_to("POST", "/auth/login")) == 1
    assert len(site.requests_to("POST", "/upload/session")) == 1
    jobs = bridge.jobs()
    assert [job["files"] for job in jobs] == [[fp] for fp in files]
    assert {job["session_id"] for job in jobs} == {"s-1"}
    assert all(job["sequential"] is True for job in jobs)
    assert [c["session_id"] for c in bridge.closes()] == ["s-1"]


def test_every_upload_carries_the_sessions_tokens(imagebam_site):
    site, bridge = imagebam_site()
    files = paths(["a.jpg", "b.jpg"])

    run_batch({Group("Set", files): files}, {"service": "imagebam.com"}, CREDS)

    csrf = bridge.client("s-1").csrf
    uploads = site.requests_to("POST", "/upload")
    assert [u["file"] for u in uploads] == ["a.jpg", "b.jpg"]
    for upload in uploads:
        assert upload["form"] == {"_token": csrf, "data": "780001"}
        assert upload["headers"] == {
            "accept": "application/json",
            "cache-control": "no-cache",
            "referer": f"{SITE}/",
            "x-requested-with": "XMLHttpRequest",
        }


def test_an_auto_gallery_with_a_cover_creates_exactly_one_gallery(imagebam_site):
    site, bridge = imagebam_site()
    files = paths(["p1.jpg", "cover.jpg", "p2.jpg"])
    group = Group("Beach {2024}", files, covers=[files[1]])

    outcome = run_batch(
        {group: files},
        {"service": "imagebam.com", "auto_gallery": True, "thumbnail_size": "180"},
        CREDS,
    )

    assert [outcome.final(fp) for fp in files] == ["Done"] * 3
    assert [r["action"] for r in bridge.requests].count("session_open") == 1
    [opened] = site.requests_to("POST", "/upload/session")
    assert opened["form"]["gallery_title"] == "Beach {2024}"
    assert opened["form"]["thumbnail_size"] == "2", "covers share the job's session"
    assert site.galleries == [
        {"id": "GA001", "title": "Beach {2024}", "url": "https://www.imagebam.com/view/GA001"}
    ]
    # Covers first, then the other files, each with its own image.
    assert site.uploaded_names() == ["cover.jpg", "p1.jpg", "p2.jpg"]
    for fp in files:
        assert site.image_of(outcome.link(fp)) == os.path.basename(fp)
        assert outcome.galleries[fp] == "https://www.imagebam.com/view/GA001"


def test_without_a_new_gallery_covers_keep_their_own_job_and_thumbnail_size(imagebam_site):
    site, bridge = imagebam_site()
    files = paths(["cover.jpg", "p1.jpg"])
    group = Group("Beach", files, covers=[files[0]])

    outcome = run_batch({group: files}, {"service": "imagebam.com", "thumbnail_size": "180"}, {})

    assert [outcome.final(fp) for fp in files] == ["Done", "Done"]
    assert [job["files"] for job in bridge.jobs()] == [[files[0]], [files[1]]]
    assert [job["session_id"] for job in bridge.jobs()] == ["s-1", "s-2"]
    opened = site.requests_to("POST", "/upload/session")
    assert [r["form"]["thumbnail_size"] for r in opened] == ["4", "2"]
    assert site.galleries == []


def test_a_wrong_password_fails_every_file_with_the_hosts_message(imagebam_site):
    site, bridge = imagebam_site()
    files = paths(["a.jpg", "b.jpg"])

    outcome = run_batch(
        {Group("Set", files): files},
        {"service": "imagebam.com"},
        {"imagebam_user": USER, "imagebam_pass": "wrong-pass"},
    )

    for fp in files:
        assert outcome.statuses[fp] == [
            f"error: upload session setup failed: ImageBam login failed: {LOGIN_REFUSED}"
        ]
    assert bridge.jobs() == [] and site.uploaded_names() == []
    assert [c["session_id"] for c in bridge.closes()] == ["s-1"]


def test_without_credentials_imagebam_uploads_anonymously(imagebam_site):
    site, _ = imagebam_site()
    files = paths(["a.jpg"])

    outcome = run_batch({Group("Set", files): files}, {"service": "imagebam.com"}, {})

    assert outcome.final(files[0]) == "Done"
    assert "GET /auth/login" not in site.paths()


def test_a_session_job_keeps_its_own_cookies(imagebam_site):
    # Two groups: two jobs, two transport sessions, two logins and CSRF tokens.
    site, bridge = imagebam_site()
    first, second = paths(["a.jpg"]), paths(["b.jpg"])

    outcome = run_batch(
        {Group("One", first): first, Group("Two", second): second},
        {"service": "imagebam.com"},
        CREDS,
    )

    assert outcome.final(first[0]) == outcome.final(second[0]) == "Done"
    assert len(site.requests_to("POST", "/auth/login")) == 2
    assert bridge.client("s-1").csrf != bridge.client("s-2").csrf
    assert [u["form"]["data"] for u in site.requests_to("POST", "/upload")] == [
        "780001",
        "780002",
    ]


def test_scenarios_name_why_the_paths_differ():
    for scenario in SCENARIOS:
        assert bool(scenario.python) == bool(scenario.why), scenario.name
        assert len(scenario.legacy) == len(scenario.want_python) == len(scenario.files)


def test_the_plugin_leaves_its_inputs_alone():
    plugin = ImageBamPlugin()
    config = {"imagebam_gallery_title": "T", "thumbnail_size": "300"}
    creds = dict(CREDS)
    before = copy.deepcopy((config, creds))
    transport = ScriptedTransport(
        ok("<input name='_token' value='tok-1234'>"),
        ok("<form action='/auth/logout'></form>"),
        ok('<meta name="csrf-token" content="csrf-1234">'),
        ok('{"data": "780001", "session": "S1"}'),
    )
    values = plugin.open_upload_session(transport, config, creds)
    plugin.build_raw_upload_request("/in/a.jpg", config, values, creds)
    assert (config, creds) == before
