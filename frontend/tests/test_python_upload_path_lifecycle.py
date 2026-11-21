# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""The Python upload path across Stop, Clear List and the next Start.

Session jobs follow the upload manager's per-batch cancel tokens: once a
newer batch starts after Clear List, a cleared batch's session job sends,
parses and reports nothing more (the new batch may hold rows for the same
files). Its UI puts go through _deliver, and Uploaded is a status the
sidecar bridge may drop, never one that ends or counts a row.
"""

import os
import queue
import threading
import time

import pytest

from modules import upload_manager
from modules.sidecar import SidecarBridge
from modules.ui.main_window import UploaderApp
from tests.test_main_window_contract import FakeGroup
from tests.test_python_upload_path import (
    CFG,
    CREDS,
    FakeSidecar,
    ParsingPlugin,
    file_statuses,
    raw_result,
)
from tests.test_upload_session import _row, _ui_app


class Group:
    def __init__(self, title, files):
        self.title = title
        self.files = list(files)


@pytest.fixture
def env(monkeypatch):
    bridge = FakeSidecar()
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
    progress, results, cancel = queue.Queue(), queue.Queue(), threading.Event()
    um = upload_manager.UploadManager(progress, results, cancel)
    plugin = ParsingPlugin()
    monkeypatch.setattr(um.plugin_manager, "get_plugin", lambda service_id: plugin)
    yield um, bridge, progress, results, cancel, plugin
    um.shutdown()


def clear_list_and_start(um, cancel, new_groups):
    """Clear List during an upload (Stop), then Start with new rows."""
    cancel.set()
    um.cancel_batch()
    cancel.clear()
    return um.start_batch({g: g.files for g in new_groups}, CFG, CREDS)


def statuses(q, fp):
    return file_statuses(list(q.queue), fp)


def wait_until(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def test_clear_list_during_the_login_never_sends_the_cleared_files(env):
    um, bridge, progress, _results, cancel, plugin = env
    login = threading.Event()
    opened = []

    def slow_login(transport, config, creds):
        opened.append(transport.session_id)
        login.wait(5)  # the host's login is slow
        return {"sess_id": "sess-value-123"}

    plugin.open_upload_session = slow_login
    um.start_batch({Group("Old", ["/s/a.jpg"]): ["/s/a.jpg"]}, CFG, CREDS)
    assert wait_until(lambda: opened)

    new_batch = clear_list_and_start(um, cancel, [Group("New", ["/s/a.jpg"])])
    login.set()
    assert wait_until(lambda: len(bridge.jobs()) == 1)
    um.dispatch_thread.join(3)
    time.sleep(0.1)

    [job] = bridge.jobs()
    assert job["batch_id"] == new_batch
    assert job["session_id"] == "s-2", "the new batch opens its own session"
    assert "s-1" in [close["session_id"] for close in bridge.closes()]
    assert "Cancelled" not in statuses(progress, "/s/a.jpg"), "the re-added row was ended"


def test_a_cleared_batch_never_parses_or_reports_its_raw_results(env, monkeypatch):
    um, bridge, progress, results, cancel, plugin = env
    tasks = []
    monkeypatch.setattr(um._post_pool, "submit", tasks.append)
    um._send_job(["/s/a.jpg", "/s/b.jpg"], CFG, CREDS)
    [job] = bridge.jobs()
    um._handle_event(raw_result(job["id"], "/s/a.jpg"))
    um._handle_event(raw_result(job["id"], "/s/b.jpg"))
    assert len(tasks) == 2  # both parses are waiting for a worker

    clear_list_and_start(um, cancel, [Group("New", ["/s/a.jpg"])])
    um.dispatch_thread.join(3)
    for task in list(tasks):
        task()

    assert [call for call in plugin.calls if call[0] == "parse"] == []
    assert statuses(progress, "/s/a.jpg") == [] and statuses(progress, "/s/b.jpg") == []
    assert list(results.queue) == []
    assert um._open_session_jobs == [] or all(
        job.cancel is um._batch_cancel for job in um._open_session_jobs
    )


def test_a_parse_finishing_after_clear_list_is_not_reported(env):
    um, bridge, progress, results, cancel, plugin = env
    plugin.gate = threading.Event()
    um._send_job(["/s/a.jpg"], CFG, CREDS)
    [job] = bridge.jobs()
    um._handle_event(raw_result(job["id"], "/s/a.jpg"))
    assert wait_until(lambda: any(call[0] == "parse" for call in plugin.calls))

    clear_list_and_start(um, cancel, [Group("New", ["/s/a.jpg"])])
    um.dispatch_thread.join(3)
    plugin.gate.set()
    assert wait_until(lambda: "s-1" in [c["session_id"] for c in bridge.closes()])

    assert "Done" not in statuses(progress, "/s/a.jpg")
    assert [item for item in list(results.queue) if item[1]] == []


def test_a_sequential_job_cleared_between_files_sends_nothing_more(env):
    um, bridge, progress, _results, cancel, plugin = env
    plugin.options = {"sequential": True}
    plugin.gate = threading.Event()
    um._send_job(["/s/1.jpg", "/s/2.jpg", "/s/3.jpg"], CFG, CREDS)
    [first] = bridge.jobs()
    um._handle_event(raw_result(first["id"], "/s/1.jpg"))
    um._handle_event({"id": first["id"], "type": "batch_complete", "status": "done"})

    clear_list_and_start(um, cancel, [Group("New", ["/s/2.jpg"])])
    um.dispatch_thread.join(3)
    plugin.gate.set()
    assert wait_until(lambda: "s-1" in [c["session_id"] for c in bridge.closes()])
    time.sleep(0.1)

    sent = [fp for job in bridge.jobs() if job["session_id"] == "s-1" for fp in job["files"]]
    assert sent == [os.path.normpath("/s/1.jpg")]
    for fp in ("/s/1.jpg", "/s/2.jpg", "/s/3.jpg"):
        assert statuses(progress, fp) == [], fp


def test_stop_alone_still_ends_the_batchs_files(env):
    um, bridge, progress, _results, cancel, plugin = env
    plugin.options = {"sequential": True}
    um._send_job(["/s/1.jpg", "/s/2.jpg"], CFG, CREDS)
    [first] = bridge.jobs()
    cancel.set()
    um.cancel_batch()
    um._handle_event(
        {"id": first["id"], "type": "status", "file": "/s/1.jpg", "status": "Cancelled"}
    )
    um._handle_event({"id": first["id"], "type": "batch_complete", "status": "done"})
    assert wait_until(lambda: statuses(progress, "/s/2.jpg") == ["Cancelled"])


def test_parsed_results_give_up_on_a_result_queue_a_new_upload_replaced(env):
    um, bridge, _progress, _results, _cancel, _plugin = env
    full = queue.Queue(maxsize=1)
    full.put(("other.jpg", "", ""))
    um.result_queue = full  # the Tk thread stopped reading it
    um._send_job(["/s/a.jpg"], CFG, CREDS)
    [job] = bridge.jobs()
    session_job = um._session_jobs[job["id"]]
    um._handle_event(raw_result(job["id"], "/s/a.jpg"))
    time.sleep(0.3)  # the parse is waiting to put its result
    assert session_job.post_pending == 1

    um.result_queue = queue.Queue()  # start_upload() swapped the queue
    assert wait_until(lambda: session_job.post_pending == 0), "the parse is stuck on the old queue"


def test_batch_complete_leaves_raw_results_to_their_parser(env):
    um, bridge, progress, _results, _cancel, plugin = env
    plugin.gate = threading.Event()
    um._send_job(["/s/a.jpg", "/s/b.jpg"], CFG, CREDS)
    [job] = bridge.jobs()
    um._handle_event(raw_result(job["id"], "/s/a.jpg"))
    um._handle_event({"id": job["id"], "type": "batch_complete", "status": "done"})

    assert statuses(progress, "/s/b.jpg") == ["error: no result received from sidecar"]
    assert statuses(progress, "/s/a.jpg") == []
    plugin.gate.set()
    assert wait_until(lambda: statuses(progress, "/s/a.jpg") == ["Done"])
    assert wait_until(lambda: len(bridge.closes()) == 1)


# --- Uploaded ------------------------------------------------------------------------


def test_the_bridge_may_drop_uploaded_but_never_the_raw_result():
    assert SidecarBridge._is_terminal_event({"type": "status", "status": "Uploaded"}) is False
    raw = {
        "type": "result",
        "file": "/a.jpg",
        "data": {"response_body": "{}", "status_code": "200"},
    }
    assert SidecarBridge._is_terminal_event(raw) is True

    bridge = SidecarBridge.__new__(SidecarBridge)
    bridge.listeners_lock = threading.RLock()
    bridge._shutdown_requested = threading.Event()
    full = queue.Queue(maxsize=1)
    full.put({"type": "progress"})
    bridge.listeners = [full]
    start = time.monotonic()
    bridge._dispatch_event({"type": "status", "file": "/a.jpg", "status": "Uploaded"})
    assert time.monotonic() - start < 0.5, "a full listener held up the stdout reader for Uploaded"


@pytest.mark.parametrize(
    ("state", "label", "counted"),
    [("uploading", "Processing", False), ("queued", "Processing", False)],
)
def test_uploaded_shows_processing_on_a_running_row_without_ending_it(
    tmp_path, state, label, counted
):
    app = _ui_app(tmp_path)
    app.progress_queue, app.result_queue = queue.Queue(), queue.Queue()
    group = FakeGroup("Set", ["/s/a.jpg"])
    app.groups = [group]
    app.file_widgets = {"/s/a.jpg": _row(group, state=state)}
    app.upload_count = 0
    app.progress_queue.put(("status", "/s/a.jpg", "Uploaded"))

    UploaderApp._process_progress_queue(app)

    row = app.file_widgets["/s/a.jpg"]
    assert row["state"] == state
    assert row["status"].text == label
    assert app.upload_count == 0


@pytest.mark.parametrize("state", ["success", "failed", "pending"])
def test_a_late_uploaded_leaves_a_finished_or_re_added_row_alone(tmp_path, state):
    app = _ui_app(tmp_path)
    app.progress_queue, app.result_queue = queue.Queue(), queue.Queue()
    group = FakeGroup("Set", ["/s/a.jpg"])
    app.groups = [group]
    row = _row(group, state=state)
    row["status"].configure(text="Before")
    app.file_widgets = {"/s/a.jpg": row}
    app.upload_count = 0
    app.progress_queue.put(("status", "/s/a.jpg", "Uploaded"))

    UploaderApp._process_progress_queue(app)

    assert row["state"] == state
    assert row["status"].text == "Before"
    assert app.upload_count == 0


def test_uploaded_then_done_completes_the_row_once(tmp_path):
    app = _ui_app(tmp_path)
    app.progress_queue, app.result_queue = queue.Queue(), queue.Queue()
    group = FakeGroup("Set", ["/s/a.jpg"])
    app.groups = [group]
    app.file_widgets = {"/s/a.jpg": _row(group, state="uploading")}
    app.upload_count = 0
    app.upload_total = 1
    app._update_group_progress = lambda fp: None
    app.progress_queue.put(("status", "/s/a.jpg", "Uploaded"))
    app.result_queue.put(("/s/a.jpg", "https://h/v", "https://h/t"))
    app.progress_queue.put(("status", "/s/a.jpg", "Done"))
    app.progress_queue.put(("status", "/s/a.jpg", "Uploaded"))  # arrived late

    UploaderApp._process_progress_queue(app)

    row = app.file_widgets["/s/a.jpg"]
    assert row["state"] == "success"
    assert row["status"].text == "Uploaded"
    assert app.upload_count == 1
