# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""TurboImageHost parsing parity with the legacy Go path.

backend/core/testdata/turbo_upload_parity.json holds Turbo's upload answers
and result pages, from the Go and Python tests (the v3.2.0 matching fixes
included) plus added variants; backend/core/turbo_upload_parity_test.go
checks that the legacy Go path, with Turbo's legacy specs, reports each
expected result. These tests check that the plugin's Python parser reports
the same for the same answers and pages.
"""

import json
from pathlib import Path

import pytest

from modules.plugins import turbo
from modules.plugins.turbo import TurboPlugin
from modules.transport import TransportResponse
from modules.upload_sessions import SessionState

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "backend"
    / "core"
    / "testdata"
    / "turbo_upload_parity.json"
)
DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES = DATA["cases"]
SESSION = {"upload_url": "https://s8d8.turboimagehost.com/upload_html5.tu", "upload_id": "u" * 20}


def answer(item):
    """A fixture page or upload answer: a body (200) or {"status", "body"}."""
    return (200, item) if isinstance(item, str) else (item["status"], item["body"])


class ParityTransport:
    """Serves a case's result pages to successive requests, as UploadTransport reports them."""

    def __init__(self, pages):
        self.pages = pages
        self.fetched = []
        self.pauses = []

    def get(self, url, **_):
        self.fetched.append(url)
        status, body = answer(self.pages[min(len(self.fetched), len(self.pages)) - 1])
        if 200 <= status < 300:
            return TransportResponse(True, "success", body, status, url, {}, {})
        return TransportResponse(
            False, "failed", "", 0, url, {}, {}, f"HTTP {status}: {body.strip()}"
        )

    def pause(self, seconds):
        self.pauses.append(seconds)
        return True


def test_the_fixture_pins_turbos_real_legacy_spec():
    spec = TurboPlugin().build_http_request("/in/a.jpg", {}, {})
    assert DATA["legacy"] == {
        "response_parser": spec["response_parser"],
        "resolve_spec": spec["resolve_spec"],
    }


def test_the_fixture_covers_the_v320_fixes_and_the_added_variants():
    names = {case["name"] for case in CASES}
    for required in (
        "cover does not take back_cover",
        "2.jpg does not take 12.jpg",
        "same base name in two folders",
        "Scan #1 and Scan #2 listed as Scan__1 and Scan__2",
        "each file of a job gets its own entry as the page grows",
        "an entry is held back only for an upload that finished",
        "an entry never goes to two files",
        "NFD file names match NFC page names",
        "a host prefix matches only on the last look",
        "auth failure: the upload is refused with 403",
        "missing entry",
        "no gallery input",
    ):
        assert required in names


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_turbo_parses_like_its_legacy_spec(case):
    plugin = TurboPlugin()
    transport = ParityTransport(case["pages"])
    state = SessionState(case["files"])
    uploads = case.get("uploads") or []

    # One file after another, each resolved right after its own upload, as
    # the Go side runs them.
    for index, fp in enumerate(case["files"]):
        given = uploads[index] if index < len(uploads) and uploads[index] else case["upload"]
        status, body = answer(given)
        response = TransportResponse(True, "success", body, status, SESSION["upload_url"], {}, {})
        state.record_uploaded(fp)  # the upload manager does this on the raw result
        transport.pauses = []
        result = plugin.parse_upload_response(fp, response, transport, dict(SESSION), state)
        state.settle(fp)
        # Between its looks at the page, each file waits the legacy schedule.
        schedule = [ms / 1000 for ms in turbo.POLL_DELAYS_MS]
        assert transport.pauses == schedule[: len(transport.pauses)]

        want = case["want"][fp]
        # The Python path quotes the host's message where Go gave only the status.
        want_error = want.get("python_error", want["error"])
        assert (result.url, result.thumb, result.gallery_url, result.error) == (
            want["url"],
            want["thumb"],
            want["gallery_url"],
            want_error,
        ), fp
        assert result.ok is (want_error == "")

    assert len(transport.fetched) == case["page_requests"]
    assert set(transport.fetched) <= {case.get("result_url")}
