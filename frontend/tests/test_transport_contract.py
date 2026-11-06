from pathlib import Path

from modules.transport import build_transport_spec, execute_transport_request


class FakeBridge:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request_sync(self, payload, timeout=0):
        self.calls.append((payload, timeout))
        return self.response


def test_transport_request_prefers_raw_response_contract():
    bridge = FakeBridge(
        {
            "status": "success",
            "data": {
                "response_body": "<html>ok</html>",
                "status_code": "200",
                "final_url": "https://example.test/final",
            },
        }
    )
    spec = build_transport_spec(
        "https://example.test/start",
        method="POST",
        form_fields={"token": "literal"},
    )

    response = execute_transport_request(
        spec,
        service="example.test",
        timeout=12,
        bridge=bridge,
        rate_limits={"requests_per_second": 1.0, "burst_size": 2},
    )

    payload, timeout = bridge.calls[0]
    sent_spec = payload["generic_spec"]
    assert timeout == 17
    assert sent_spec["timeout_seconds"] == 12
    assert payload["action"] == "http_request"
    assert payload["service"] == "example.test"
    assert payload["rate_limits"] == {"requests_per_second": 1.0, "burst_size": 2}
    assert sent_spec["include_response_body"] is True
    assert sent_spec["include_transport_metadata"] is True
    assert "pre_request" not in sent_spec
    assert "extract_fields" not in sent_spec
    assert "success_check" not in sent_spec
    assert response.ok is True
    assert response.body == "<html>ok</html>"
    assert response.status_code == 200
    assert response.final_url == "https://example.test/final"


def test_production_go_stays_host_agnostic():
    repo = Path(__file__).resolve().parents[2]
    backend = repo / "backend"
    banned = {
        "vipergirls.to",
        "vipr.im",
        "pixhost.cc",
        "imx.to",
        "imagebam.com",
        "turboimagehost",
        "viper_schedule_post",
        "viper_cancel_post",
        "viper_list_posts",
    }

    violations = []
    for path in backend.rglob("*.go"):
        if path.name.endswith("_test.go"):
            continue
        text = path.read_text(encoding="utf-8").lower()
        for token in banned:
            if token in text:
                violations.append(f"{path.relative_to(repo)} contains {token}")

    assert violations == []


def test_transport_contract_documents_legacy_parser_boundary():
    repo = Path(__file__).resolve().parents[2]
    contract = (repo / "docs" / "TRANSPORT_CONTRACT.md").read_text(encoding="utf-8")

    assert "Python owns website behavior" in contract
    assert "Go owns transport mechanics" in contract
    assert "Deprecated Compatibility Hooks" in contract
    assert "response_body" in contract
    assert "status_code" in contract
    assert "final_url" in contract


def test_transport_spec_flags_are_opt_in():
    default_spec = build_transport_spec("https://example.test/")
    assert "literal_values" not in default_spec
    assert "reset_cookies" not in default_spec

    flagged = build_transport_spec("https://example.test/", literal_values=True, reset_cookies=True)
    assert flagged["literal_values"] is True
    assert flagged["reset_cookies"] is True


def test_transport_request_sends_timeout_and_margin():
    bridge = FakeBridge({"status": "success", "data": {}})
    spec = build_transport_spec("https://example.test/")

    execute_transport_request(spec, timeout=30, bridge=bridge)

    payload, timeout = bridge.calls[0]
    assert payload["generic_spec"]["timeout_seconds"] == 30
    assert timeout == 35.0


def test_transport_request_can_disable_retries():
    bridge = FakeBridge({"status": "success", "data": {}})
    spec = build_transport_spec("https://example.test/")

    execute_transport_request(spec, bridge=bridge)
    execute_transport_request(spec, bridge=bridge, retry=False)

    default_payload, _ = bridge.calls[0]
    unretried_payload, _ = bridge.calls[1]
    assert "retry_config" not in default_payload
    assert unretried_payload["retry_config"] == {"max_retries": 0}
