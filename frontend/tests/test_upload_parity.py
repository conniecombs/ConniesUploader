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

from modules.transport import TransportResponse
from modules.upload_results import parse_json_upload, upload_failure

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
