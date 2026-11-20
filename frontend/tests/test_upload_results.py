# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Building blocks for parse_upload_response: results, JSON paths, templates, failures."""

import pytest

from modules.transport import TransportResponse
from modules.upload_results import (
    NO_LINK_ERROR,
    UploadResult,
    apply_response_template,
    collect_secrets,
    host_message,
    html_field,
    json_value,
    redact_secrets,
    request_failure,
    split_url_extension,
)


def failed_request(message, status_code=0, body="", status="failed"):
    return TransportResponse(
        ok=False,
        status=status,
        body=body,
        status_code=status_code,
        final_url="https://host.test/x",
        data={},
        raw={},
        message=message,
    )


def test_upload_result_is_ok_only_with_a_link_and_no_error():
    assert UploadResult("https://h/v", "https://h/t").ok is True
    assert UploadResult(" ").ok is False
    assert UploadResult("https://h/v", error="boom").ok is False
    assert UploadResult.failed("why").error == "why"
    assert UploadResult().failure_reason == NO_LINK_ERROR
    assert UploadResult(error="why").failure_reason == "why"
    assert UploadResult("https://h/v").failure_reason == ""


@pytest.mark.parametrize(
    ("path", "want"),
    [
        ("data.link", "https://i/x.jpg"),
        ("files.0.sourceUrl", "https://cdn/s.jpg"),
        ("files.1.sourceUrl", ""),
        ("files.-1.sourceUrl", ""),
        ("files.x", ""),
        ("success", "true"),
        ("off", "false"),
        ("count", "3"),
        ("ratio", "0.25"),
        ("big", "1000000000000000000000"),
        ("tiny", "0.0000001"),
        ("nothing", ""),
        ("data", ""),
        ("", ""),
    ],
)
def test_json_value_reads_scalars_like_the_go_path(path, want):
    data = {
        "data": {"link": "https://i/x.jpg"},
        "files": [{"sourceUrl": "https://cdn/s.jpg"}],
        "success": True,
        "off": False,
        "count": 3,
        "ratio": 0.25,
        "big": 1e21,
        "tiny": 1e-7,
        "nothing": None,
    }
    assert json_value(data, path) == want


@pytest.mark.parametrize(
    ("link", "want"),
    [
        ("https://i.example/AbCd123.jpg", ("https://i.example/AbCd123", ".jpg")),
        ("https://i.example/a/AbCd123.png?x=1#f", ("https://i.example/a/AbCd123", ".png")),
        ("https://i.example/AbCd123", ("https://i.example/AbCd123", "")),
        ("https://i.example/a.b/c", ("https://i.example/a.b/c", "")),
        ("  ", ("", "")),
        # response_template_test.go TestURLNoExtKeepsTheLinksEscaping
        ("https://i.example/a%2Fb/AbC.jpg", ("https://i.example/a%2Fb/AbC", ".jpg")),
        ("https://i.example/a%2fb/AbC.jpg?x=1#f", ("https://i.example/a%2fb/AbC", ".jpg")),
        ("https://i.example/it's(1)!*.png", ("https://i.example/it's(1)!*", ".png")),
        ("https://i.example/a%20b.gif", ("https://i.example/a%20b", ".gif")),
        ("https://i.example/AbC", ("https://i.example/AbC", "")),
    ],
)
def test_split_url_extension(link, want):
    assert split_url_extension(link) == want


def test_response_templates_fill_file_parts_json_values_and_link_parts():
    data = {"success": True, "id": "abc123", "nested": {"slug": "s-1"}}
    assert (
        apply_response_template(
            "https://e/p/{id}/{filename}|{basename}|{ext}|{dot_ext}", data, "/in/my image.jpg"
        )
        == "https://e/p/abc123/my image.jpg|my image|jpg|.jpg"
    )
    assert apply_response_template("{slug}/{missing}", data, "/in/a") == "s-1/"
    assert (
        apply_response_template("{url_no_ext}m{url_dot_ext}", None, "/in/a.jpg", "https://i/x.png")
        == "https://i/xm.png"
    )


def test_html_field_follows_the_go_selection_rules():
    page = (
        '<meta name="csrf-token" content="tok-1">'
        '<input name="sess_id" value=" abc ">'
        '<form action="/up"><a id="gallery-name" href="https://h/g/1">My gallery</a></form>'
        "<p class=t>  plain text </p>"
        "<script>var endpoint: 'https://up.example/upload';</script>"
    )
    assert html_field(page, "meta[name='csrf-token']") == "tok-1"
    assert html_field(page, "input[name='sess_id']") == "abc"
    assert html_field(page, "form") == "/up"
    assert html_field(page, "a#gallery-name") == "https://h/g/1"
    assert html_field(page, "p.t") == "plain text"
    assert html_field(page, "div.none") == ""
    assert html_field(page, r"regex:endpoint:\s*'([^']+)'") == "https://up.example/upload"
    assert html_field(page, r"regex:csrf-token") == "csrf-token"
    assert html_field(page, "regex:nomatch") == ""
    assert html_field(page, "") == ""


def test_host_message_and_redaction():
    assert host_message('{"error":"nope"}') == "nope"
    assert host_message("x" * 300).endswith("…")
    assert len(host_message("x" * 300)) == 201
    assert redact_secrets("a token-1 b", ["token-1"]) == "a [redacted] b"


def test_collect_secrets_takes_every_long_enough_value_longest_first():
    secrets = collect_secrets(
        {"user": "bob", "pass": "hunter22"}, {"sess_id": "abcdef0123", "x": ""}
    )
    assert secrets == ["abcdef0123", "hunter22"]


def test_request_failure_quotes_the_host_with_redaction_and_a_limit():
    secret = "sess-0123456789"
    page = f"<html><body><h1>Forbidden</h1><p>session {secret} expired</p>{'z' * 400}</body></html>"
    # Go reports a non-2xx follow-up as "HTTP <code>: <whole page>".
    response = failed_request(f"HTTP 403: {page}")
    message = request_failure("login failed", response, [secret])
    assert message.startswith("login failed (HTTP 403): Forbidden session [redacted] expired")
    assert secret not in message
    assert len(message) < 260

    retried = failed_request(f"max retries (3) exhausted, last error: HTTP 503: {page}")
    assert request_failure("result page", retried, [secret]).startswith(
        "result page (HTTP 503): Forbidden session [redacted]"
    )

    with_facts = failed_request(
        "HTTP 404: ignored", status_code=404, body='{"message":"no such page"}'
    )
    assert request_failure("result page", with_facts) == "result page (HTTP 404): no such page"

    transport = failed_request(f"dial tcp: connection refused to {secret}")
    assert request_failure("login failed", transport, [secret]) == (
        "login failed: dial tcp: connection refused to [redacted]"
    )
    assert request_failure("login failed", failed_request("")) == "login failed"
