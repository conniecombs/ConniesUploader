# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Upload manager event scoping, straggler handling, and cancellation."""

import queue
import threading
import time
from types import SimpleNamespace

import pytest

from modules import upload_manager


class FakeBridge:
    def __init__(self):
        self.listeners = []
        self.sent = []
        self.generation = 1
        self.available = True

    def add_listener(self, q):
        self.listeners.append(q)

    def remove_listener(self, q):
        if q in self.listeners:
            self.listeners.remove(q)

    def send_job(self, payload):
        if not self.available:
            return None
        self.sent.append(payload)
        return self.generation

    def send_cmd(self, payload):
        return self.send_job(payload) is not None

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
    manager.um._handle_event({"id": "b1:0", "type": "status", "file": "/a.jpg", "status": "Done"})
    manager.um._handle_event({"id": "b1:0", "type": "batch_complete", "status": "done"})

    assert drain(manager.results) == [("/a.jpg", "u", "t"), ("/b.jpg", "", "")]
    assert drain(manager.progress) == [
        ("status", "/a.jpg", "Done"),
        ("status", "/b.jpg", "error: no result received from sidecar"),
    ]


def test_batch_complete_finishes_a_file_whose_done_was_lost(manager):
    manager.um._handle_event(
        {"id": "b1:0", "type": "result", "file": "/a.jpg", "url": "u", "thumb": "t"}
    )
    # ...its {"type": "status", "status": "Done"} never arrived...
    manager.um._handle_event({"id": "b1:0", "type": "batch_complete", "status": "done"})

    assert drain(manager.results) == [("/a.jpg", "u", "t"), ("/b.jpg", "", "")]
    assert drain(manager.progress) == [
        ("status", "/a.jpg", "Done"),
        ("status", "/b.jpg", "error: no result received from sidecar"),
    ]
    assert manager.um._awaiting_done == set()
    assert manager.um.active_files == set()
    assert "b1:0" not in manager.um._job_files


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


def test_jobs_send_only_the_plugins_declared_credentials(manager, monkeypatch):
    class Plugin:
        metadata = {"credentials": [{"key": "vipr_user"}, {"key": "vipr_pass"}]}

        def build_http_request(self, file_path, config, creds):
            return {"url": "https://host.test/u", "multipart_fields": {}}

    monkeypatch.setattr(manager.um.plugin_manager, "get_plugin", lambda service_id: Plugin())
    all_creds = {
        "vipr_user": "u",
        "vipr_pass": "p",
        "imx_api": "secret-api-key",
        "vg_pass": "forum-password",
    }

    manager.um._send_job(["/e.jpg"], {"service": "vipr.im"}, all_creds)

    assert manager.bridge.sent[-1]["creds"] == {"vipr_user": "u", "vipr_pass": "p"}


def test_jobs_for_plugins_without_credentials_send_none(manager, monkeypatch):
    class Plugin:
        metadata = {}

        def build_http_request(self, file_path, config, creds):
            return {"url": "https://host.test/u", "multipart_fields": {}}

    monkeypatch.setattr(manager.um.plugin_manager, "get_plugin", lambda service_id: Plugin())

    manager.um._send_job(["/e.jpg"], {"service": "pixhost.cc"}, {"imx_api": "secret"})

    assert manager.bridge.sent[-1]["creds"] == {}


INTERRUPTED = "error: Uploader process restarted; upload interrupted"


class SpecPlugin:
    metadata = {}

    def build_http_request(self, file_path, config, creds):
        return {"url": "https://host.test/u", "multipart_fields": {}}


def send_job(manager, monkeypatch, files):
    monkeypatch.setattr(manager.um.plugin_manager, "get_plugin", lambda service_id: SpecPlugin())
    manager.um._send_job(files, {"service": "pixhost.cc"}, {})
    return manager.bridge.sent[-1]["id"]


def crash(generation):
    return {
        "type": "sidecar_crashed",
        "generation": generation,
        "msg": "Uploader process restarted; upload interrupted",
    }


def test_sidecar_crash_ends_every_unfinished_file_of_the_dead_process(manager, monkeypatch):
    job = send_job(manager, monkeypatch, ["/c.jpg", "/d.jpg", "/e.jpg"])
    manager.um._handle_event({"id": job, "type": "result", "file": "/c.jpg", "url": "u"})
    manager.um._handle_event({"id": job, "type": "status", "file": "/c.jpg", "status": "Done"})
    # /d.jpg got its result, then the process died before its Done.
    manager.um._handle_event({"id": job, "type": "result", "file": "/d.jpg", "url": "u2"})
    drain(manager.results), drain(manager.progress)

    manager.um._handle_event(crash(1))

    assert drain(manager.results) == [("/e.jpg", "", "")]
    assert sorted(drain(manager.progress)) == [
        ("status", "/d.jpg", "Done"),
        ("status", "/e.jpg", INTERRUPTED),
    ]
    assert job not in manager.um._job_files


def test_sidecar_crash_leaves_jobs_of_the_restarted_process_alone(manager, monkeypatch):
    old_job = send_job(manager, monkeypatch, ["/c.jpg"])
    manager.bridge.generation = 2  # restarted; the next job reaches the new process
    new_job = send_job(manager, monkeypatch, ["/f.jpg"])

    manager.um._handle_event(crash(1))

    assert drain(manager.progress) == [("status", "/c.jpg", INTERRUPTED)]
    assert old_job not in manager.um._job_files
    assert new_job in manager.um._job_files
    assert "/f.jpg" in manager.um.active_files


def test_job_written_to_a_process_already_reported_dead_is_ended(manager, monkeypatch):
    manager.um._handle_event(crash(1))

    send_job(manager, monkeypatch, ["/c.jpg"])

    assert drain(manager.results) == [("/c.jpg", "", "")]
    assert drain(manager.progress) == [("status", "/c.jpg", INTERRUPTED)]


def test_stop_ends_unfinished_files_when_the_cancel_cannot_reach_the_sidecar(manager, monkeypatch):
    send_job(manager, monkeypatch, ["/c.jpg"])
    manager.bridge.available = False

    manager.um.cancel_batch()

    statuses = []
    deadline = time.monotonic() + 3
    while len(statuses) < 3 and time.monotonic() < deadline:
        statuses += drain(manager.progress)
        time.sleep(0.01)
    assert sorted(statuses) == [
        ("status", "/a.jpg", "Cancelled"),
        ("status", "/b.jpg", "Cancelled"),
        ("status", "/c.jpg", "Cancelled"),
    ]
    assert manager.um.active_files == set()


def test_stop_leaves_files_to_the_sidecar_when_the_cancel_is_delivered(manager):
    manager.um.cancel_batch()

    assert drain(manager.progress) == []
    assert manager.um.active_files == {"/a.jpg", "/b.jpg"}
