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


class RecordingBridge(UnreachableBridge):
    def __init__(self):
        self.sent = []

    def send_job(self, payload):
        self.sent.append(payload)
        return 1

    def send_cmd(self, payload):
        return self.send_job(payload) is not None

    def is_process_alive(self):
        return True


class Group:
    def __init__(self, title, files):
        self.title = title
        self.files = list(files)


class SlowGalleryPlugin:
    """An auto-gallery host whose prepare_group makes a slow network call."""

    def __init__(self):
        self.gate = threading.Event()
        self.prepared = []

    def prepare_group(self, group, config, context, creds):
        self.prepared.append(group.title)
        self.gate.wait(5)  # e.g. IMX create_gallery_with_image

    def build_http_request(self, file_path, config, creds):
        return {"url": "https://host.test/u", "multipart_fields": {}}


def _clear_list_during_prepare(monkeypatch, old_files, new_files):
    """Start, Clear List while the dispatch is inside prepare_group, re-add, Start."""
    bridge = RecordingBridge()
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
    cancel = threading.Event()
    progress = queue.Queue()
    um = upload_manager.UploadManager(progress, queue.Queue(), cancel)
    plugin = SlowGalleryPlugin()
    monkeypatch.setattr(um.plugin_manager, "get_plugin", lambda service_id: plugin)

    old = [Group(f"Old{i}", [fp]) for i, fp in enumerate(old_files)]
    um.start_batch({g: g.files for g in old}, {"service": "x"}, {})
    time.sleep(0.1)  # the dispatch thread is inside prepare_group(Old0)

    # Clear List during the upload: runtime.clear_list() -> stop_upload().
    cancel.set()
    um.cancel_batch()
    # The user re-adds files and presses Start: start_upload() clears the event.
    cancel.clear()
    new = Group("New", new_files)
    new_batch = um.start_batch({new: new.files}, {"service": "x"}, {})

    plugin.gate.set()  # the slow call returns
    deadline = time.monotonic() + 3
    while um.dispatch_thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    uploads = [job for job in bridge.sent if job.get("action") == "http_upload"]
    return um, uploads, progress, new_batch, plugin


def _drain(q):
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    return items


def test_start_after_clear_list_dispatches_the_new_batch_and_never_the_cleared_one(monkeypatch):
    um, uploads, _progress, new_batch, plugin = _clear_list_during_prepare(
        monkeypatch, ["/old/a1.jpg", "/old/b1.jpg"], ["/new/n1.jpg"]
    )

    sent_files = [fp for job in uploads for fp in job["files"]]
    assert sent_files == ["/new/n1.jpg"], f"sent={sent_files}"
    assert [job["batch_id"] for job in uploads] == [new_batch]
    assert um.current_batch_id == new_batch
    # The cleared batch made no gallery for its second folder.
    assert plugin.prepared == ["Old0", "New"]


def test_cleared_batch_does_not_cancel_the_same_files_added_again(monkeypatch):
    um, uploads, progress, new_batch, _plugin = _clear_list_during_prepare(
        monkeypatch, ["/s/a.jpg", "/s/b.jpg"], ["/s/a.jpg", "/s/b.jpg"]
    )

    assert [fp for job in uploads for fp in job["files"]] == ["/s/a.jpg", "/s/b.jpg"]
    assert [job["batch_id"] for job in uploads] == [new_batch]
    statuses = [item for item in _drain(progress) if item[0] == "status"]
    assert not any(status == "Cancelled" for _kind, _fp, status in statuses), statuses


def test_stop_before_the_cleared_dispatch_exits_cancels_the_new_batch(monkeypatch):
    bridge = RecordingBridge()
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
    cancel = threading.Event()
    progress, results = queue.Queue(), queue.Queue()
    um = upload_manager.UploadManager(progress, results, cancel)
    plugin = SlowGalleryPlugin()
    monkeypatch.setattr(um.plugin_manager, "get_plugin", lambda service_id: plugin)
    old = Group("Old", ["/old/a.jpg"])
    um.start_batch({old: old.files}, {"service": "x"}, {})
    time.sleep(0.1)
    cancel.set()
    um.cancel_batch()
    cancel.clear()
    new = Group("New", ["/new/n1.jpg"])
    um.start_batch({new: new.files}, {"service": "x"}, {})

    # Stop the new upload while the cleared one is still inside prepare_group.
    cancel.set()
    um.cancel_batch()
    plugin.gate.set()
    um.dispatch_thread.join(3)

    assert [job for job in bridge.sent if job.get("action") == "http_upload"] == []
    assert ("status", "/new/n1.jpg", "Cancelled") in _drain(progress)
    assert ("/new/n1.jpg", "", "") in _drain(results)


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
