# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Transport sessions and the UploadTransport plugins use on the new upload path."""

import threading
import time

import pytest

from modules import transport
from modules.sidecar import PROCESS_RESTARTED_MSG, SIDECAR_CRASHED_EVENT, SidecarBridge
from modules.transport import (
    TRANSPORT_WAIT_MARGIN_SECONDS,
    TransportCancelled,
    TransportSession,
    TransportSessionError,
    UploadTransport,
    close_transport_session,
    execute_transport_request,
    open_transport_session,
)


class RecordingBridge:
    """Answers every request with ``reply`` and records what was sent."""

    def __init__(self, reply=None, generation=3):
        self.reply = reply if reply is not None else {"status": "success", "data": {}}
        self.generation = generation
        self.calls = []
        self.commands = []

    def request_sync(self, payload, timeout=0, cancel_event=None):
        self.calls.append((payload, timeout, cancel_event))
        return dict(self.reply, id=payload.get("id"))

    def request_with_generation(self, payload, timeout=0, cancel_event=None):
        return self.request_sync(payload, timeout, cancel_event), self.generation

    def send_cmd(self, payload):
        self.commands.append(payload)
        return True


def test_transport_request_runs_on_the_given_session():
    bridge = RecordingBridge()
    execute_transport_request({"url": "https://h.test/"}, bridge=bridge, session_id="s-abc")

    payload, _, _ = bridge.calls[0]
    assert payload["generic_spec"]["session_id"] == "s-abc"


def test_transport_request_without_a_session_sends_none():
    bridge = RecordingBridge()
    execute_transport_request({"url": "https://h.test/"}, bridge=bridge)

    payload, _, cancel_event = bridge.calls[0]
    assert "session_id" not in payload["generic_spec"]
    assert cancel_event is None


def test_transport_request_waits_with_the_cancel_event_and_skips_a_cancelled_one():
    bridge = RecordingBridge()
    cancel = threading.Event()
    execute_transport_request({"url": "https://h.test/"}, bridge=bridge, cancel_event=cancel)
    assert bridge.calls[0][2] is cancel

    cancel.set()
    response = execute_transport_request(
        {"url": "https://h.test/"}, bridge=bridge, cancel_event=cancel
    )
    assert len(bridge.calls) == 1, "a cancelled request must not be sent"
    assert response.ok is False
    assert response.status == "cancelled"


def test_upload_transport_sends_literal_resolved_requests_on_its_session():
    bridge = RecordingBridge(
        {
            "status": "success",
            "data": {"response_body": "ok", "status_code": "200", "final_url": "https://h.test/x"},
        }
    )
    transport = UploadTransport(
        "s-1",
        service="host.test",
        bridge=bridge,
        rate_limits={"requests_per_second": 2.0, "burst_size": 1},
        timeout=12,
    )

    response = transport.post(
        "https://h.test/login", {"user": "{name}"}, headers={"Referer": "https://h.test/"}
    )
    transport.get("https://h.test/home", retry=False)
    transport.request({"url": "https://h.test/raw", "method": "PUT"}, timeout=3)

    assert response.ok and response.body == "ok" and response.status_code == 200
    first, timeout, _ = bridge.calls[0]
    spec = first["generic_spec"]
    assert spec["url"] == "https://h.test/login"
    assert spec["method"] == "POST"
    assert spec["form_fields"] == {"user": "{name}"}
    assert spec["headers"] == {"Referer": "https://h.test/"}
    assert spec["literal_values"] is True
    assert spec["session_id"] == "s-1"
    assert spec["include_response_body"] is True
    assert spec["include_transport_metadata"] is True
    assert spec["timeout_seconds"] == 12
    assert first["service"] == "host.test"
    assert first["rate_limits"] == {"requests_per_second": 2.0, "burst_size": 1}
    assert timeout == pytest.approx(17)
    second, _, _ = bridge.calls[1]
    assert second["generic_spec"]["method"] == "GET"
    assert second["retry_config"] == {"max_retries": 0}
    third, _, _ = bridge.calls[2]
    assert third["generic_spec"]["literal_values"] is True
    assert third["generic_spec"]["timeout_seconds"] == 3
    assert third["generic_spec"]["include_response_body"] is True


def test_upload_transport_answers_cancelled_without_sending_once_the_batch_stops():
    bridge = RecordingBridge()
    cancel = threading.Event()
    transport = UploadTransport("s-1", bridge=bridge, cancel_event=cancel)
    cancel.set()

    response = transport.get("https://h.test/")

    assert transport.cancelled is True
    assert bridge.calls == []
    assert response.ok is False
    assert response.status == "cancelled"


def test_open_transport_session_returns_the_session_and_its_process():
    bridge = RecordingBridge({"type": "result", "status": "success", "data": {"session_id": "s-9"}})

    session = open_transport_session(bridge, "batch-1", timeout=4)

    assert session == TransportSession(session_id="s-9", generation=3, batch_id="batch-1")
    payload, timeout, _ = bridge.calls[0]
    assert payload["action"] == "session_open"
    assert payload["batch_id"] == "batch-1"
    assert payload["id"]
    # Go gives up on an open still queued after timeout_seconds, and Python
    # waits a little longer, so Go answers first.
    assert payload["timeout_seconds"] == 4
    assert timeout == pytest.approx(4 + TRANSPORT_WAIT_MARGIN_SECONDS)


def test_open_transport_session_reports_failure_and_cancel():
    failed = RecordingBridge({"type": "result", "status": "failed", "msg": "batch cancelled"})
    with pytest.raises(TransportSessionError, match="batch cancelled"):
        open_transport_session(failed, "batch-1")

    cancel = threading.Event()
    cancel.set()
    with pytest.raises(TransportCancelled):
        open_transport_session(RecordingBridge(), "batch-1", cancel_event=cancel)


def test_open_transport_session_without_generation_support_still_works():
    class OldBridge:
        def request_sync(self, payload, timeout=0, cancel_event=None):
            return {"id": payload["id"], "status": "success", "data": {"session_id": "s-2"}}

    session = open_transport_session(OldBridge(), "b")
    assert session.session_id == "s-2"
    assert session.generation is None


def test_close_transport_session_sends_a_correlated_close():
    bridge = RecordingBridge()
    assert close_transport_session(bridge, TransportSession("s-5", 3, "b")) is True

    command = bridge.commands[0]
    assert command["action"] == "session_close"
    assert command["session_id"] == "s-5"
    assert command["id"], "a close without an id would reach listeners as an anonymous result"


# --- SidecarBridge waiting behaviour -------------------------------------------------


def _bridge_with(send):
    bridge = SidecarBridge.__new__(SidecarBridge)
    bridge.listeners = []
    bridge.listeners_lock = threading.RLock()
    bridge.send_cmd = lambda payload: send(bridge, payload) is not None
    bridge.send_job = lambda payload: send(bridge, payload)
    return bridge


def _broadcast(bridge, event):
    with bridge.listeners_lock:
        listeners = list(bridge.listeners)
    for listener in listeners:
        listener.put(event)


def test_request_sync_gives_up_promptly_when_cancelled():
    bridge = _bridge_with(lambda bridge, payload: 1)
    cancel = threading.Event()
    threading.Timer(0.2, cancel.set).start()

    start = time.monotonic()
    reply = bridge.request_sync({"action": "http_request"}, timeout=10, cancel_event=cancel)

    assert time.monotonic() - start < 3
    assert reply["status"] == "cancelled"


def test_request_with_generation_returns_the_reply_and_its_process():
    def send(bridge, payload):
        _broadcast(bridge, {"id": payload["id"], "type": "result", "status": "success"})
        return 4

    bridge = _bridge_with(send)
    reply, generation = bridge.request_with_generation({"action": "session_open"}, timeout=2)

    assert reply["status"] == "success"
    assert generation == 4


def test_request_with_generation_ends_when_its_process_dies():
    def send(bridge, payload):
        # An older process's crash report does not end this request...
        _broadcast(bridge, {"type": SIDECAR_CRASHED_EVENT, "generation": 3})
        # ...its own process's does.
        threading.Timer(
            0.1, _broadcast, args=(bridge, {"type": SIDECAR_CRASHED_EVENT, "generation": 4})
        ).start()
        return 4

    bridge = _bridge_with(send)
    start = time.monotonic()
    reply, generation = bridge.request_with_generation({"action": "http_request"}, timeout=10)

    assert time.monotonic() - start < 3
    assert reply["status"] == "error"
    assert reply["msg"] == PROCESS_RESTARTED_MSG
    assert generation == 4


def test_request_sync_still_ignores_uncorrelated_events():
    def send(bridge, payload):
        _broadcast(bridge, {"type": "result", "status": "success", "msg": "not mine"})
        _broadcast(bridge, {"type": SIDECAR_CRASHED_EVENT, "generation": 1})
        _broadcast(bridge, {"id": payload["id"], "type": "result", "status": "success"})
        return 1

    bridge = _bridge_with(send)
    reply = bridge.request_sync({"action": "x"}, timeout=2)

    assert reply["status"] == "success"
    assert "msg" not in reply


@pytest.fixture
def no_wait_margin(monkeypatch):
    monkeypatch.setattr(transport, "TRANSPORT_WAIT_MARGIN_SECONDS", 0.0)


def _silent_bridge():
    """A bridge whose sidecar never answers in time; it records what is sent."""
    sent = []

    def send(bridge, payload):
        sent.append(payload)
        return 2

    bridge = _bridge_with(send)
    bridge.sent = sent
    return bridge


def _closes(bridge, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        closes = [p for p in bridge.sent if p.get("action") == "session_close"]
        if closes:
            return closes
        time.sleep(0.01)
    return []


@pytest.mark.parametrize("ends", ["timeout", "cancel"])
def test_a_session_whose_open_reply_comes_after_python_stopped_waiting_is_closed(
    ends, no_wait_margin
):
    bridge = _silent_bridge()
    cancel = threading.Event()
    if ends == "cancel":
        threading.Timer(0.05, cancel.set).start()
    timeout = 5.0 if ends == "cancel" else 0.01
    with pytest.raises(TransportCancelled if ends == "cancel" else TransportSessionError):
        open_transport_session(bridge, "b", timeout=timeout, cancel_event=cancel)
    [opened] = bridge.sent
    assert bridge.listeners == [], "the wait's listener is gone"

    # The sidecar opened the session after all: nobody will use it, so the
    # bridge closes it.
    bridge._dispatch_event(
        {
            "id": opened["id"],
            "type": "result",
            "status": "success",
            "data": {"session_id": "s-late"},
        }
    )
    [close] = _closes(bridge)
    assert close["session_id"] == "s-late" and close["id"].startswith("session-close:")

    # One reply, one close.
    bridge._dispatch_event(
        {
            "id": opened["id"],
            "type": "result",
            "status": "success",
            "data": {"session_id": "s-late"},
        }
    )
    time.sleep(0.1)
    assert len(_closes(bridge)) == 1


def test_a_late_open_reply_that_lands_while_the_wait_ends_is_still_closed(no_wait_margin):
    bridge = _silent_bridge()
    remove = SidecarBridge.remove_listener

    def reply_then_remove(q):
        # The reply reaches the wait's own queue just after it gave up.
        [opened] = bridge.sent
        q.put(
            {
                "id": opened["id"],
                "type": "result",
                "status": "success",
                "data": {"session_id": "s-race"},
            }
        )
        remove(bridge, q)

    bridge.remove_listener = reply_then_remove
    with pytest.raises(TransportSessionError):
        open_transport_session(bridge, "b", timeout=0.01)
    [close] = _closes(bridge)
    assert close["session_id"] == "s-race"


def test_a_late_failed_open_or_a_dead_process_closes_nothing(no_wait_margin):
    bridge = _silent_bridge()
    with pytest.raises(TransportSessionError):
        open_transport_session(bridge, "b", timeout=0.01)
    [opened] = bridge.sent
    bridge._dispatch_event(
        {
            "id": opened["id"],
            "type": "result",
            "status": "failed",
            "msg": "request deadline passed while queued (waited 31s)",
        }
    )
    with pytest.raises(TransportSessionError):
        open_transport_session(bridge, "b", timeout=0.01)
    second = bridge.sent[-1]
    # The process the open went to died: it will never answer, and its
    # sessions died with it.
    bridge._forget_late_replies(2)
    bridge._dispatch_event(
        {"id": second["id"], "type": "result", "status": "success", "data": {"session_id": "s-x"}}
    )
    time.sleep(0.1)
    assert _closes(bridge, timeout=0.1) == []
    assert bridge._late_replies == {}


def test_transport_requests_wait_in_a_way_that_ends_when_the_sidecar_dies():
    class CrashAwareBridge:
        def request_sync(self, payload, timeout=0, cancel_event=None):
            raise AssertionError("a crash-aware wait must be used when the bridge has one")

        def request_with_generation(self, payload, timeout=0, cancel_event=None):
            return {"status": "error", "msg": PROCESS_RESTARTED_MSG}, 2

    response = execute_transport_request(
        {"url": "https://h.test/"}, bridge=CrashAwareBridge(), session_id="s-1"
    )
    assert response.ok is False
    assert response.message == PROCESS_RESTARTED_MSG


def test_upload_transport_pause_ends_early_when_cancelled():
    cancel = threading.Event()
    transport = UploadTransport("s-1", bridge=RecordingBridge(), cancel_event=cancel)
    assert transport.pause(0.01) is True

    threading.Timer(0.05, cancel.set).start()
    start = time.monotonic()
    assert transport.pause(10) is False
    assert time.monotonic() - start < 3
