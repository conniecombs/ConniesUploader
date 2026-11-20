# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Upload manager behaviour across Stop / Clear List and the next Start."""

import queue
import threading
import time

from modules import upload_manager


class UnreachableBridge:
    """A sidecar that cannot be written to, so Stop cancels locally."""

    def add_listener(self, q):
        pass

    def remove_listener(self, q):
        pass

    def send_job(self, payload):
        return None

    def send_cmd(self, payload):
        return False

    def is_process_alive(self):
        return False


def _manager_cancelling_locally(monkeypatch, file_count=20, bound=5):
    """Stop pressed with the sidecar unreachable; the UI queues are small and full."""
    monkeypatch.setattr(
        upload_manager.SidecarBridge, "get", staticmethod(lambda: UnreachableBridge())
    )
    progress_q = queue.Queue(maxsize=bound)
    result_q = queue.Queue(maxsize=bound)
    um = upload_manager.UploadManager(progress_q, result_q, threading.Event())
    um.current_batch_id = "old"
    files = [f"/f{i}.jpg" for i in range(file_count)]
    um._register_job("old:1", files)
    um.active_files.update(files)

    before = set(_cancel_threads())
    um.cancel_batch()
    time.sleep(0.2)  # the local-cancel thread now waits for the Tk thread to drain
    (cancel_thread,) = set(_cancel_threads()) - before
    return um, progress_q, files, cancel_thread


def _cancel_threads():
    return [t for t in threading.enumerate() if t.name == "UploadManagerCancel" and t.is_alive()]


def _drain_until_done(progress, thread, timeout=10):
    statuses = []
    deadline = time.monotonic() + timeout
    while thread.is_alive() and time.monotonic() < deadline:
        try:
            statuses.append(progress.get(timeout=0.05))
        except queue.Empty:
            pass
    while not progress.empty():
        statuses.append(progress.get_nowait())
    return statuses


def test_start_is_not_blocked_by_a_local_cancel_waiting_for_the_ui(monkeypatch):
    um, progress, _files, cancel_thread = _manager_cancelling_locally(monkeypatch)
    # start_upload() on the Tk thread: a new result queue, then start_batch().
    um.result_queue = queue.Queue(maxsize=5)
    monkeypatch.setattr(um, "_dispatch_jobs", lambda *args, **kwargs: None)
    started = threading.Event()

    def tk_start():
        um.start_batch({}, {"service": "imx.to"}, {})
        started.set()

    threading.Thread(target=tk_start, daemon=True).start()

    # While the Tk thread is stuck it drains nothing, so the UI would freeze for good.
    assert started.wait(3.0), "start_batch() waited for _jobs_lock held by the cancel thread"
    _drain_until_done(progress, cancel_thread)  # let the cancel thread finish


def test_local_cancel_gives_up_on_a_result_queue_a_new_upload_replaced(monkeypatch):
    um, progress, files, cancel_thread = _manager_cancelling_locally(monkeypatch)
    um.result_queue = queue.Queue(maxsize=5)  # start_upload() swapped it; nobody reads the old one

    statuses = _drain_until_done(progress, cancel_thread)

    assert not cancel_thread.is_alive(), "the cancel thread is stuck on the replaced result queue"
    assert sorted(statuses) == sorted(("status", fp, "Cancelled") for fp in files)
