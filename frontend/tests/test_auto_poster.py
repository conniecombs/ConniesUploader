# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Session-based auto-poster ordering, skipping, stopping and credentials."""

import threading
import time

import pytest

from modules import auto_poster, config, viper_client


class FakeViperGirlsAPI:
    posted = []
    logins = []

    def login(self, username, password):
        FakeViperGirlsAPI.logins.append((username, password))
        return True

    def post_reply(self, thread_id, message):
        FakeViperGirlsAPI.posted.append((thread_id, message))
        return True


@pytest.fixture(autouse=True)
def fast_poster(monkeypatch):
    monkeypatch.setattr(config, "POST_COOLDOWN_SECONDS", 0.01)
    monkeypatch.setattr(viper_client, "ViperGirlsAPI", FakeViperGirlsAPI)
    FakeViperGirlsAPI.posted = []
    FakeViperGirlsAPI.logins = []


def make_poster(creds=None):
    poster = auto_poster.AutoPoster(
        creds if creds is not None else {"vg_user": "u", "vg_pass": "p"},
        {"Thread": {"url": "https://vipergirls.to/threads/123", "thread_id": "123"}},
    )
    poster.history = []
    poster._record_history_item = (
        lambda item, status, thread_id="", error="": poster.history.append(
            (item.get("batch_name"), status, error)
        )
    )
    return poster


def wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_do_not_post_group_ahead_does_not_block():
    poster = make_poster()
    uploading = [True]
    poster.begin_session([1])
    poster.start_processing(lambda: uploading[0], threading.Event())
    poster.queue_post(0, "c", "Do Not Post")
    poster.queue_post(1, "second", "Thread")
    uploading[0] = False

    assert wait_until(lambda: not poster.is_running)
    assert FakeViperGirlsAPI.posted == [("123", "second")]


def test_second_session_posts_batch_zero_again():
    poster = make_poster()
    for _ in range(2):
        uploading = [True]
        poster.begin_session([0])
        poster.start_processing(lambda: uploading[0], threading.Event())
        poster.queue_post(0, "body", "Thread")
        uploading[0] = False
        assert wait_until(lambda: not poster.is_running)

    assert FakeViperGirlsAPI.posted == [("123", "body"), ("123", "body")]


def test_skipped_index_lets_later_index_post():
    poster = make_poster()
    uploading = [True]
    poster.begin_session([0, 1])
    poster.start_processing(lambda: uploading[0], threading.Event())
    poster.skip(0, "upload failed")
    poster.queue_post(1, "later", "Thread")
    uploading[0] = False

    assert wait_until(lambda: not poster.is_running)
    assert FakeViperGirlsAPI.posted == [("123", "later")]
    assert poster.history == [("Batch 2", "success", "")]


def test_cancelled_group_skips_poster_index():
    poster = make_poster()
    poster.begin_session([0, 1])
    poster.skip(0, "cancelled")
    poster.queue_post(1, "after cancel", "Thread")
    poster.start_processing(lambda: False, threading.Event())

    assert wait_until(lambda: not poster.is_running)
    assert FakeViperGirlsAPI.posted == [("123", "after cancel")]


def test_unresolved_index_after_uploads_end_is_failed():
    poster = make_poster()
    poster.begin_session([0])
    poster.start_processing(lambda: False, threading.Event())

    assert wait_until(lambda: not poster.is_running, timeout=5.0)
    assert FakeViperGirlsAPI.posted == []
    assert poster.history == [("Batch 1", "failure", "no output generated")]


def test_stop_interrupts_waiting_worker():
    poster = make_poster()
    poster.begin_session([0])
    poster.start_processing(lambda: True, threading.Event())
    assert wait_until(lambda: poster.is_running)

    started = time.monotonic()
    poster.stop()
    assert time.monotonic() - started < 1.0
    assert not poster.is_running


def test_credentials_provider_is_read_at_session_start():
    creds = {"vg_user": "", "vg_pass": ""}
    poster = make_poster(lambda: creds)
    creds.update({"vg_user": "new-user", "vg_pass": "new-pass"})

    poster.begin_session([0])
    poster.start_processing(lambda: False, threading.Event())
    poster.queue_post(0, "body", "Thread")

    assert wait_until(lambda: not poster.is_running)
    assert FakeViperGirlsAPI.logins == [("new-user", "new-pass")]


def test_begin_session_replaces_a_live_worker():
    poster = make_poster()
    poster.begin_session([0])
    poster.start_processing(lambda: True, threading.Event())
    assert wait_until(lambda: poster.is_running)

    poster.begin_session([0])
    poster.start_processing(lambda: False, threading.Event())
    poster.queue_post(0, "fresh", "Thread")

    assert wait_until(lambda: not poster.is_running)
    assert FakeViperGirlsAPI.posted == [("123", "fresh")]


class SlowViperGirlsAPI(FakeViperGirlsAPI):
    started = threading.Event()
    delay = 0.6

    def post_reply(self, thread_id, message):
        SlowViperGirlsAPI.started.set()
        time.sleep(SlowViperGirlsAPI.delay)
        return super().post_reply(thread_id, message)


def test_begin_session_supersedes_mid_post_worker_without_zombie(monkeypatch):
    monkeypatch.setattr(viper_client, "ViperGirlsAPI", SlowViperGirlsAPI)
    SlowViperGirlsAPI.started.clear()
    poster = make_poster()
    poster.begin_session([0, 1])
    poster.start_processing(lambda: True, threading.Event())
    poster.queue_post(0, "old-0", "Thread")
    poster.queue_post(1, "old-1", "Thread")
    assert SlowViperGirlsAPI.started.wait(2)

    started = time.monotonic()
    poster.begin_session([0])
    assert time.monotonic() - started < 0.3, "begin_session must not block the Tk thread"
    poster.start_processing(lambda: False, threading.Event())
    poster.queue_post(0, "fresh", "Thread")

    assert wait_until(lambda: not poster.is_running, timeout=5.0)
    assert FakeViperGirlsAPI.posted == [("123", "old-0"), ("123", "fresh")]
    assert ("Batch 2", "failure", "superseded by a new upload") in poster.history
    assert all(entry[2] != "no output generated" for entry in poster.history)
    assert wait_until(
        lambda: not any(t.is_alive() for t in threading.enumerate() if t.name == "AutoPoster")
    )


def test_begin_session_records_queued_posts_as_superseded():
    poster = make_poster()
    poster.begin_session([0, 1, 2])
    poster.queue_post(1, "one", "Thread")
    poster.queue_post(2, "two", "Thread")

    poster.begin_session([7])

    assert sorted(poster.history) == [
        ("Batch 2", "failure", "superseded by a new upload"),
        ("Batch 3", "failure", "superseded by a new upload"),
    ]
    assert poster.post_queue == {}


def _hold_session_lock():
    """Hold the shared ViperGirls session lock on another thread until released."""
    from modules import viper_client

    acquired = threading.Event()
    release = threading.Event()

    def holder():
        with viper_client.session_lock():
            acquired.set()
            release.wait(5)

    thread = threading.Thread(target=holder, daemon=True)
    thread.start()
    assert acquired.wait(2)
    return release, thread


def test_post_waiting_on_session_lock_is_dropped_when_superseded():
    poster = make_poster()
    release, holder = _hold_session_lock()
    poster.begin_session([0])
    poster.start_processing(lambda: True, threading.Event())
    poster.queue_post(0, "old", "Thread")
    time.sleep(0.4)  # worker has popped the item and is waiting on the lock

    poster.begin_session([])  # a new upload supersedes this session
    release.set()
    holder.join(2)

    assert wait_until(
        lambda: not any(t.is_alive() for t in threading.enumerate() if t.name == "AutoPoster")
    )
    assert FakeViperGirlsAPI.posted == []
    assert ("Batch 1", "failure", "superseded by a new upload") in poster.history


def test_post_waiting_on_session_lock_is_dropped_after_stop():
    poster = make_poster()
    cancel = threading.Event()
    release, holder = _hold_session_lock()
    poster.begin_session([0])
    poster.start_processing(lambda: True, cancel)
    poster.queue_post(0, "old", "Thread")
    time.sleep(0.4)

    cancel.set()  # the user pressed Stop
    release.set()
    holder.join(2)

    assert wait_until(lambda: not poster.is_running)
    assert FakeViperGirlsAPI.posted == []
    assert ("Batch 1", "failure", "cancelled before posting") in poster.history


class FailingLoginAPI(FakeViperGirlsAPI):
    delay = 0.0

    def login(self, username, password):
        time.sleep(FailingLoginAPI.delay)
        FakeViperGirlsAPI.logins.append((username, password))
        return False


def test_posts_queued_after_a_failed_login_are_recorded_and_reported(monkeypatch):
    monkeypatch.setattr(viper_client, "ViperGirlsAPI", FailingLoginAPI)
    FailingLoginAPI.delay = 0.0
    poster = make_poster()
    poster.begin_session([0, 1])
    poster.start_processing(lambda: True, threading.Event())
    assert wait_until(lambda: not poster.is_running)

    first = poster.queue_post(0, "post 0", "Thread", batch_name="Batch A")
    second = poster.queue_post(1, "post 1", "Thread", batch_name="Batch B")

    # The caller reports the returned reason; the history records the failure.
    assert first == second == "login failed"
    assert poster.post_queue == {}
    assert poster.history == [
        ("Batch A", "failure", "login failed"),
        ("Batch B", "failure", "login failed"),
    ]
    assert FakeViperGirlsAPI.posted == []


def test_post_queued_while_login_is_failing_is_recorded_and_reported(monkeypatch):
    monkeypatch.setattr(viper_client, "ViperGirlsAPI", FailingLoginAPI)
    FailingLoginAPI.delay = 0.3
    poster = make_poster()
    notices = []
    poster.notify = lambda message, level: notices.append((message, level))
    poster.begin_session([0])
    poster.start_processing(lambda: True, threading.Event())

    assert poster.queue_post(0, "post 0", "Thread", batch_name="Batch A") == ""
    assert wait_until(lambda: not poster.is_running)

    assert poster.post_queue == {}
    assert poster.history == [("Batch A", "failure", "login failed")]
    assert notices == [('ViperGirls post for "Batch A" was not sent: login failed.', "warning")]


def test_a_new_session_after_a_failed_login_queues_posts_again(monkeypatch):
    monkeypatch.setattr(viper_client, "ViperGirlsAPI", FailingLoginAPI)
    FailingLoginAPI.delay = 0.0
    poster = make_poster()
    poster.begin_session([0])
    poster.start_processing(lambda: True, threading.Event())
    assert wait_until(lambda: not poster.is_running)
    assert poster.queue_post(0, "body", "Thread") == "login failed"

    monkeypatch.setattr(viper_client, "ViperGirlsAPI", FakeViperGirlsAPI)
    uploading = [True]
    poster.begin_session([0])
    poster.start_processing(lambda: uploading[0], threading.Event())
    assert poster.queue_post(0, "body", "Thread") == ""
    uploading[0] = False

    assert wait_until(lambda: not poster.is_running)
    assert FakeViperGirlsAPI.posted == [("123", "body")]


def test_stop_records_and_reports_posts_queued_before_and_after_it():
    poster = make_poster()
    notices = []
    poster.notify = lambda message, level: notices.append((message, level))
    cancel = threading.Event()
    poster.begin_session([0, 1])
    poster.start_processing(lambda: True, cancel)
    assert poster.queue_post(1, "post 1", "Thread", batch_name="Batch B") == ""

    cancel.set()  # Stop (or Clear List)
    assert wait_until(lambda: not poster.is_running)
    # Batch 0 finishes right after Stop; nothing will ever post it.
    refused = poster.queue_post(0, "post 0", "Thread", batch_name="Batch A")

    assert refused == "cancelled before posting"
    assert poster.post_queue == {}
    assert poster.history == [
        ("Batch B", "failure", "cancelled before posting"),
        ("Batch A", "failure", "cancelled before posting"),
    ]
    assert notices == [
        ('ViperGirls post for "Batch B" was not sent: cancelled before posting.', "warning")
    ]
    assert FakeViperGirlsAPI.posted == []


def test_a_new_session_after_stop_queues_posts_again():
    poster = make_poster()
    cancel = threading.Event()
    poster.begin_session([0])
    poster.start_processing(lambda: True, cancel)
    cancel.set()
    assert wait_until(lambda: not poster.is_running)

    uploading = [True]
    poster.begin_session([0])
    poster.start_processing(lambda: uploading[0], threading.Event())
    assert poster.queue_post(0, "body", "Thread") == ""
    uploading[0] = False

    assert wait_until(lambda: not poster.is_running)
    assert FakeViperGirlsAPI.posted == [("123", "body")]


TARGET_SET_LATE = "the ViperGirls target was chosen after the upload started"


def test_post_for_a_target_chosen_mid_upload_without_a_worker_is_recorded_and_reported():
    poster = make_poster()
    # No batch had a target at Start, so the app started no posting worker.
    poster.begin_session([])

    refused = poster.queue_post(0, "post 0", "Thread", batch_name="Batch A")

    assert refused == TARGET_SET_LATE
    assert poster.post_queue == {}
    assert poster.history == [("Batch A", "failure", TARGET_SET_LATE)]


def test_post_for_a_batch_not_registered_at_start_is_recorded_and_reported():
    poster = make_poster()
    uploading = [True]
    poster.begin_session([1])
    poster.start_processing(lambda: uploading[0], threading.Event())

    refused = poster.queue_post(0, "post 0", "Thread", batch_name="Batch A")
    uploading[0] = False

    assert refused == TARGET_SET_LATE
    assert ("Batch A", "failure", TARGET_SET_LATE) in poster.history
    assert wait_until(lambda: not poster.is_running, timeout=5.0)
    assert FakeViperGirlsAPI.posted == []
