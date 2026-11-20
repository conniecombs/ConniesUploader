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
import threading
import uuid
from typing import Any, Dict, Mapping, Optional

from modules.sidecar import REQUEST_CANCELLED_MSG, SidecarBridge

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
    session_id: Optional[str] = None,
    cancel_event: Optional[threading.Event] = None,
) -> TransportResponse:
    """Execute a resolved transport request through the Go sidecar.

    ``timeout`` becomes the request deadline Go enforces (``timeout_seconds``)
    and Python waits that long plus a small margin. ``retry=False`` disables
    Go's transport retries for requests that must not be repeated, such as a
    forum post. ``session_id`` runs the request on that transport session's
    isolated cookie jar (see ``open_transport_session``). With
    ``cancel_event``, a request is not sent once the event is set and the
    wait for its answer ends when it is set (status ``cancelled``).
    """
    generic_spec = dict(spec)
    if "timeout_seconds" not in generic_spec:
        generic_spec["timeout_seconds"] = int(math.ceil(float(timeout)))
    if session_id:
        generic_spec["session_id"] = str(session_id)
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

    if cancel_event is not None and cancel_event.is_set():
        return _cancelled_response(spec)

    active_bridge = bridge if bridge is not None else SidecarBridge.get()
    wait = float(timeout) + TRANSPORT_WAIT_MARGIN_SECONDS
    if cancel_event is None:
        raw = active_bridge.request_sync(payload, timeout=wait)
    else:
        raw = active_bridge.request_sync(payload, timeout=wait, cancel_event=cancel_event)
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


def _cancelled_response(spec: Mapping[str, Any]) -> TransportResponse:
    return TransportResponse(
        ok=False,
        status="cancelled",
        body="",
        status_code=0,
        final_url=str(spec.get("url") or ""),
        data={},
        raw={},
        message=REQUEST_CANCELLED_MSG,
    )


# --- Transport sessions --------------------------------------------------------------
#
# A transport session is an isolated cookie jar in the sidecar. The upload
# manager opens one per upload job on the Python upload path; the plugin's
# login and follow-up requests and the job's uploads all run on it, and it is
# closed when the job and its result parsing are done. A Stop (batch cancel)
# closes it in the sidecar at once; so does the death of the sidecar process.


class TransportSessionError(RuntimeError):
    """A transport session could not be opened."""


class TransportCancelled(RuntimeError):
    """The batch was cancelled before the transport session opened."""


@dataclass(frozen=True)
class TransportSession:
    """An open transport session and the sidecar process (generation) it lives in.

    ``generation`` is None when the bridge cannot tell; such a session is
    taken to die with any sidecar crash.
    """

    session_id: str
    generation: Optional[int]
    batch_id: str


SESSION_OPEN_TIMEOUT_SECONDS = 30.0


def open_transport_session(
    bridge: Any,
    batch_id: str,
    *,
    cancel_event: Optional[threading.Event] = None,
    timeout: float = SESSION_OPEN_TIMEOUT_SECONDS,
) -> TransportSession:
    """Open a transport session for ``batch_id``.

    Raises TransportCancelled when ``cancel_event`` is set before the session
    opens, and TransportSessionError when the sidecar refuses or cannot answer.
    """
    if cancel_event is not None and cancel_event.is_set():
        raise TransportCancelled(REQUEST_CANCELLED_MSG)
    payload = {
        "action": "session_open",
        "id": f"session-open:{uuid.uuid4().hex}",
        "batch_id": str(batch_id or ""),
    }
    with_generation = getattr(bridge, "request_with_generation", None)
    if callable(with_generation):
        reply, generation = with_generation(payload, timeout=timeout, cancel_event=cancel_event)
    else:
        reply = bridge.request_sync(payload, timeout=timeout, cancel_event=cancel_event)
        generation = None
    reply = reply if isinstance(reply, dict) else {}
    if reply.get("status") == "cancelled" or (
        cancel_event is not None and cancel_event.is_set() and reply.get("status") != "success"
    ):
        raise TransportCancelled(REQUEST_CANCELLED_MSG)
    data = reply.get("data") if isinstance(reply.get("data"), dict) else {}
    session_id = str(data.get("session_id") or "")
    if reply.get("status") != "success" or not session_id:
        reason = str(reply.get("msg") or reply.get("message") or "no answer from the uploader")
        raise TransportSessionError(f"could not open an upload session: {reason}")
    return TransportSession(
        session_id=session_id,
        generation=generation if isinstance(generation, int) else None,
        batch_id=str(batch_id or ""),
    )


def close_transport_session(bridge: Any, session: TransportSession) -> bool:
    """Ask the sidecar to close ``session``; does not wait for the answer.

    The close carries its own request id: an event without one would reach
    the upload listener as an anonymous result.
    """
    return bool(
        bridge.send_cmd(
            {
                "action": "session_close",
                "id": f"session-close:{uuid.uuid4().hex}",
                "session_id": session.session_id,
            }
        )
    )


class UploadTransport:
    """The requests a host plugin makes during one upload job.

    Every request runs on the job's transport session (its own cookie jar),
    with the host's rate limits, and with literal values: Go sends the url,
    headers and form fields exactly as given, so plugin code builds each
    request completely in Python. Once the batch is cancelled, requests are
    answered with status ``cancelled`` without being sent.

    A request whose answer is not 2xx comes back with ``ok`` False and the
    status and body in ``message`` ("HTTP 403: ..."); transport failures
    likewise. Plugins read ``response.ok``, ``body``, ``status_code`` and
    ``final_url``, and ``json()``.
    """

    DEFAULT_TIMEOUT_SECONDS = 30.0

    def __init__(
        self,
        session_id: str,
        *,
        service: str = "",
        bridge: Optional[Any] = None,
        rate_limits: Optional[Mapping[str, Any]] = None,
        cancel_event: Optional[threading.Event] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._session_id = str(session_id)
        self.service = str(service or "")
        self._bridge = bridge
        self._rate_limits = dict(rate_limits) if rate_limits else None
        self._cancel_event = cancel_event
        self.timeout = float(timeout)

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def cancelled(self) -> bool:
        """Whether the batch this transport belongs to was cancelled."""
        return self._cancel_event is not None and self._cancel_event.is_set()

    def request(
        self,
        spec: Mapping[str, Any],
        *,
        timeout: Optional[float] = None,
        retry: bool = True,
    ) -> TransportResponse:
        """Send one resolved request (a ``build_transport_spec`` dict).

        ``retry=False`` for a request that must not be repeated, such as a POST
        that creates something on the host.
        """
        resolved = dict(spec)
        resolved["literal_values"] = True
        resolved.setdefault("include_response_body", True)
        resolved.setdefault("include_transport_metadata", True)
        resolved.setdefault("use_cookies", True)
        if self.cancelled:
            return _cancelled_response(resolved)
        return execute_transport_request(
            resolved,
            service=self.service,
            timeout=self.timeout if timeout is None else float(timeout),
            bridge=self._bridge,
            rate_limits=self._rate_limits,
            retry=retry,
            session_id=self._session_id,
            cancel_event=self._cancel_event,
        )

    def get(
        self,
        url: str,
        *,
        headers: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
        retry: bool = True,
    ) -> TransportResponse:
        """GET ``url`` on the session."""
        return self.request(
            build_transport_spec(url, "GET", headers=headers, literal_values=True),
            timeout=timeout,
            retry=retry,
        )

    def post(
        self,
        url: str,
        form_fields: Optional[Mapping[str, Any]] = None,
        *,
        headers: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
        retry: bool = True,
    ) -> TransportResponse:
        """POST url-encoded ``form_fields`` to ``url`` on the session."""
        return self.request(
            build_transport_spec(
                url, "POST", headers=headers, form_fields=form_fields, literal_values=True
            ),
            timeout=timeout,
            retry=retry,
        )
