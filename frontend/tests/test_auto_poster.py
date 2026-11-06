# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Session-based auto-poster ordering, skipping, stopping and credentials."""

import threading
import time

import pytest

from modules import auto_poster, config, viper_api


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
    monkeypatch.setattr(viper_api, "ViperGirlsAPI", FakeViperGirlsAPI)
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
