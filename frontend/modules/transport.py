# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Python-owned transport helpers for the Go sidecar.

The Go sidecar is the fast executor. Callers in Python are responsible for
website-specific sequencing, parsing, and success/failure interpretation.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any, Dict, Mapping, Optional

from modules.sidecar import SidecarBridge

JsonDict = Dict[str, Any]


@dataclass
class TransportResponse:
    """Normalized result from a raw sidecar HTTP request."""

    ok: bool
    status: str
    body: str
    status_code: int
    final_url: str
    data: JsonDict
    raw: JsonDict
    message: str = ""

    def json(self) -> Any:
        """Decode the returned response body as JSON."""
        if self.body:
            return json.loads(self.body)
        fallback = {
            key: value
            for key, value in self.data.items()
            if key not in {"status_code", "final_url", "response_body"}
        }
        return fallback or None


def build_transport_spec(
    url: str,
    method: str = "GET",
    headers: Optional[Mapping[str, Any]] = None,
    form_fields: Optional[Mapping[str, Any]] = None,
    use_cookies: bool = True,
    include_response_body: bool = True,
    include_transport_metadata: bool = True,
    literal_values: bool = False,
    reset_cookies: bool = False,
) -> JsonDict:
    """Build a resolved sidecar transport request spec.

    ``literal_values`` tells Go to send url, headers, and form fields exactly as
    given (no ``{token}`` substitution). ``reset_cookies`` discards the shared
    cookie jar before the request runs, so a login cannot ride an old session.
    """
    spec: JsonDict = {
        "url": str(url),
        "method": str(method or "GET").upper(),
        "use_cookies": bool(use_cookies),
        "include_response_body": bool(include_response_body),
        "include_transport_metadata": bool(include_transport_metadata),
    }
    if headers:
        spec["headers"] = {str(key): str(value) for key, value in headers.items()}
    if form_fields:
        spec["form_fields"] = {str(key): str(value) for key, value in form_fields.items()}
    if literal_values:
        spec["literal_values"] = True
    if reset_cookies:
        spec["reset_cookies"] = True
    return spec


# Extra seconds Python waits beyond the deadline it hands to Go, so Go always
# gives up (and reports it) before Python does.
TRANSPORT_WAIT_MARGIN_SECONDS = 5.0


def execute_transport_request(
    spec: Mapping[str, Any],
    *,
    service: str = "",
    timeout: float = 30.0,
    bridge: Optional[Any] = None,
    rate_limits: Optional[Mapping[str, Any]] = None,
    retry: bool = True,
) -> TransportResponse:
    """Execute a resolved transport request through the Go sidecar.

    ``timeout`` becomes the request deadline Go enforces (``timeout_seconds``)
    and Python waits that long plus a small margin. ``retry=False`` disables
    Go's transport retries for requests that must not be repeated, such as a
    forum post.
    """
    generic_spec = dict(spec)
    if "timeout_seconds" not in generic_spec:
        generic_spec["timeout_seconds"] = int(math.ceil(float(timeout)))
    payload: JsonDict = {
        "action": "http_request",
        "generic_spec": generic_spec,
    }
    if service:
        payload["service"] = service
    if rate_limits:
        payload["rate_limits"] = {str(key): value for key, value in rate_limits.items()}
    if not retry:
        payload["retry_config"] = {"max_retries": 0}

    active_bridge = bridge if bridge is not None else SidecarBridge.get()
    raw = active_bridge.request_sync(
        payload, timeout=float(timeout) + TRANSPORT_WAIT_MARGIN_SECONDS
    )
    if not isinstance(raw, dict):
        return TransportResponse(
            ok=False,
            status="failed",
            body="",
            status_code=0,
            final_url="",
            data={},
            raw={"response": raw},
            message="Sidecar returned an unreadable response.",
        )

    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    body = str(data.get("response_body") or "")
    status_code = _parse_status_code(data.get("status_code"))
    final_url = str(data.get("final_url") or spec.get("url") or "")
    status = str(raw.get("status") or "")
    return TransportResponse(
        ok=status == "success",
        status=status,
        body=body,
        status_code=status_code,
        final_url=final_url,
        data=dict(data),
        raw=raw,
        message=str(raw.get("msg") or raw.get("message") or ""),
    )


def _parse_status_code(value: Any) -> int:
    try:
        return int(str(value or "0"))
    except (TypeError, ValueError):
        return 0
