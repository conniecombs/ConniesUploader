# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Upload manager event scoping, straggler handling, and cancellation."""

import queue
import threading
from types import SimpleNamespace

import pytest

from modules import upload_manager


class FakeBridge:
    def __init__(self):
        self.listeners = []
        self.sent = []

    def add_listener(self, q):
        self.listeners.append(q)

    def remove_listener(self, q):
        if q in self.listeners:
            self.listeners.remove(q)

    def send_cmd(self, payload):
        self.sent.append(payload)
        return True

    def is_process_alive(self):
        return True


def drain(q):
    items = []
    while True:
        try:
            items.append(q.get_nowait())
        except queue.Empty:
            return items


@pytest.fixture
def manager(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
    progress_q = queue.Queue()
    result_q = queue.Queue()
    cancel_event = threading.Event()
    um = upload_manager.UploadManager(progress_q, result_q, cancel_event)
    um.current_batch_id = "b1"
    um._register_job("b1:0", ["/a.jpg", "/b.jpg"])
    um.active_files.update(["/a.jpg", "/b.jpg"])
    return SimpleNamespace(
        um=um, bridge=bridge, progress=progress_q, results=result_q, cancel=cancel_event
    )


def test_events_from_other_batches_are_dropped(manager):
    manager.um._handle_event({"id": "zzz:0", "type": "result", "file": "/a.jpg", "url": "u"})

    assert drain(manager.results) == []
    assert drain(manager.progress) == []


def test_error_without_file_fails_every_active_file_of_job(manager):
    manager.um._handle_event({"id": "b1:0", "type": "error", "msg": "Invalid job: boom"})

    assert sorted(drain(manager.results)) == [("/a.jpg", "", ""), ("/b.jpg", "", "")]
    statuses = sorted(drain(manager.progress))
    assert statuses == [
        ("status", "/a.jpg", "error: Invalid job: boom"),
        ("status", "/b.jpg", "error: Invalid job: boom"),
    ]
    assert manager.um.active_files == set()


def test_batch_complete_fails_stragglers(manager):
    manager.um._handle_event(
        {"id": "b1:0", "type": "result", "file": "/a.jpg", "url": "u", "thumb": "t"}
    )
    manager.um._handle_event({"id": "b1:0", "type": "batch_complete", "status": "done"})

    assert drain(manager.results) == [("/a.jpg", "u", "t"), ("/b.jpg", "", "")]
    assert drain(manager.progress) == [
        ("status", "/b.jpg", "error: no result received from sidecar")
    ]


def test_cancelled_status_is_forwarded(manager):
    manager.um._handle_event(
        {"id": "b1:0", "type": "status", "file": "/a.jpg", "status": "Cancelled"}
    )

    assert drain(manager.progress) == [("status", "/a.jpg", "Cancelled")]


def test_cancel_batch_sends_cancel_action(manager):
    manager.um.cancel_batch()

    assert manager.bridge.sent[-1] == {"action": "cancel", "batch_id": "b1"}


def test_cancel_batch_without_active_batch_sends_nothing(manager):
    manager.um.current_batch_id = None
    manager.um.cancel_batch()

    assert manager.bridge.sent == []


def test_listener_keeps_running_after_cancel_event(manager):
    manager.cancel.set()

    assert manager.um._listener_should_run() is True
    manager.um._stop_events.set()
    assert manager.um._listener_should_run() is False


def test_dispatch_marks_undispatched_files_cancelled(manager):
    class Group:
        title = "Batch"
        files = ["/c.jpg", "/d.jpg"]

    group = Group()
    manager.cancel.set()

    manager.um._dispatch_jobs({group: ["/c.jpg", "/d.jpg"]}, {"service": "pixhost.cc"}, {})

    assert sorted(drain(manager.results)) == [("/c.jpg", "", ""), ("/d.jpg", "", "")]
    assert sorted(drain(manager.progress)) == [
        ("status", "/c.jpg", "Cancelled"),
        ("status", "/d.jpg", "Cancelled"),
    ]
    assert manager.bridge.sent == []


def test_jobs_carry_batch_and_job_ids(manager, monkeypatch):
    class Plugin:
        def build_http_request(self, file_path, config, creds):
            return {"url": "https://host.test/u", "multipart_fields": {}}

    monkeypatch.setattr(manager.um.plugin_manager, "get_plugin", lambda service_id: Plugin())
    manager.um.current_batch_id = "b9"
    manager.um._send_job(["/e.jpg"], {"service": "pixhost.cc"}, {})

    payload = manager.bridge.sent[-1]
    assert payload["batch_id"] == "b9"
    assert payload["id"].startswith("b9:")
    assert manager.um._job_files[payload["id"]] == ["/e.jpg"]
