# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Parity of the Python upload parsing with the legacy Go path.

backend/core/testdata/upload_parity.json holds response bodies taken from
the Go and Python tests; backend/core/upload_parity_test.go checks that the
legacy Go path produces each expected result. These tests check that the
Python port, and each host plugin migrated to Python parsing, produce the
same results for the same responses.
"""

import json
from pathlib import Path

import pytest

from modules.plugins.imgur import ImgurPlugin
from modules.plugins.imx import ImxPlugin
from modules.plugins.pixhost import PixhostPlugin
from modules.transport import TransportResponse
from modules.upload_results import parse_json_upload, upload_failure
from modules.upload_sessions import SessionState

FIXTURE = (
    Path(__file__).resolve().parents[2] / "backend" / "core" / "testdata" / "upload_parity.json"
)
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))


def response(status, body, url="https://host.test/upload"):
    return TransportResponse(
        ok=True,
        status="success",
        body=body,
        status_code=status,
        final_url=url,
        data={},
        raw={},
    )


@pytest.mark.parametrize("case", CASES["failure_messages"], ids=lambda case: case["name"])
def test_failure_messages_match_the_go_path(case):
    got = upload_failure(case["reason"], case["status"], case["body"], case.get("secrets", ()))
    assert got == case["want"]


HOST_PLUGINS = {"imx.to": ImxPlugin, "pixhost.cc": PixhostPlugin, "imgur.com": ImgurPlugin}
HOST_CREDS = {
    "imx.to": {"imx_api": "apikey-123", "imx_user": "imx-user", "imx_pass": "imx-password"},
    "pixhost.cc": {},
    "imgur.com": {"imgur_client_id": "cid-9876"},
}
HOST_CASES = [case for case in CASES["json_uploads"] if case["host"]]


@pytest.mark.parametrize("host", sorted(HOST_PLUGINS))
def test_fixtures_cover_every_migrated_host(host):
    names = [case["name"] for case in HOST_CASES if case["host"] == host]
    assert len(names) >= 4, f"{host} needs success, refusal, rejection and no-link fixtures"


@pytest.mark.parametrize("case", HOST_CASES, ids=lambda case: case["name"])
def test_the_fixture_pins_the_hosts_real_legacy_parser(case):
    plugin = HOST_PLUGINS[case["host"]]()
    spec = plugin.build_http_request(case["file"], case["config"], HOST_CREDS[case["host"]])
    assert spec["response_parser"] == case["parser"]


@pytest.mark.parametrize("case", HOST_CASES, ids=lambda case: case["name"])
def test_migrated_host_parses_like_its_legacy_spec(case):
    plugin = HOST_PLUGINS[case["host"]]()
    creds = HOST_CREDS[case["host"]]
    session_values = plugin.open_upload_session(None, case["config"], creds)
    state = SessionState([case["file"]], secrets=list(creds.values()) + case.get("secrets", []))

    result = plugin.parse_upload_response(
        case["file"], response(case["status"], case["body"]), None, session_values, state
    )

    want = case["want"]
    # The legacy path canonicalizes IMX thumbnails after Go reports them.
    want_thumb = case.get("want_plugin_thumb", want["thumb"])
    assert (result.url, result.thumb, result.gallery_url, result.error) == (
        want["url"],
        want_thumb,
        "",
        want["error"],
    )
    assert result.ok is (want["error"] == "")


@pytest.mark.parametrize("case", CASES["json_uploads"], ids=lambda case: case["name"])
def test_json_upload_parsing_matches_the_go_path(case):
    parser = case["parser"]
    result = parse_json_upload(
        response(case["status"], case["body"]),
        file_path=case["file"],
        url_path=parser.get("url_path", ""),
        thumb_path=parser.get("thumb_path", ""),
        status_path=parser.get("status_path", ""),
        success_value=parser.get("success_value", ""),
        url_template=parser.get("url_template", ""),
        thumb_template=parser.get("thumb_template", ""),
        secrets=case.get("secrets", ()),
    )
    want = case["want"]
    assert (result.url, result.thumb, result.error) == (want["url"], want["thumb"], want["error"])
