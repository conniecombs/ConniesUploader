# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""How a group's cover files and other files are split into sidecar jobs."""

import os
import queue
import threading

import pytest

from modules import upload_manager


class FakeBridge:
    def __init__(self):
        self.sent = []

    def send_cmd(self, payload):
        self.sent.append(payload)
        return True


class Group:
    def __init__(self, title, files, covers):
        self.title = title
        self.files = list(files)
        self.cover_files = list(covers)


@pytest.fixture
def manager(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
    um = upload_manager.UploadManager(queue.Queue(), queue.Queue(), threading.Event())
    um.current_batch_id = "b1"
    return um, bridge


def _job_files(bridge):
    return [[os.path.basename(path) for path in job["files"]] for job in bridge.sent]


def test_session_created_gallery_gets_covers_and_files_in_one_job(manager):
    um, bridge = manager
    files = ["/set/p1.jpg", "/set/cover.jpg", "/set/p2.jpg"]
    group = Group("Beach", files, covers=["/set/cover.jpg"])

    um._dispatch_jobs(
        {group: list(files)},
        {"service": "imagebam.com", "auto_gallery": True, "thumbnail_size": "180"},
        {"imagebam_user": "user@example.com", "imagebam_pass": "secret"},
    )

    # One job opens one upload session, so ImageBam creates one gallery.
    assert _job_files(bridge) == [["cover.jpg", "p1.jpg", "p2.jpg"]]
    session_fields = bridge.sent[0]["http_spec"]["pre_request"]["follow_up_request"][
        "follow_up_request"
    ]["follow_up_request"]["form_fields"]
    assert session_fields["gallery_title"] == "Beach"


def test_session_gallery_host_without_a_new_gallery_keeps_separate_cover_job(manager):
    um, bridge = manager
    files = ["/set/cover.jpg", "/set/p1.jpg"]
    group = Group("Beach", files, covers=["/set/cover.jpg"])

    um._dispatch_jobs({group: list(files)}, {"service": "imagebam.com"}, {})

    assert _job_files(bridge) == [["cover.jpg"], ["p1.jpg"]]
    assert bridge.sent[0]["config"]["thumbnail_size"] == "300"


def test_other_hosts_keep_a_separate_cover_job(manager):
    um, bridge = manager
    files = ["/set/cover.jpg", "/set/p1.jpg"]
    group = Group("Beach", files, covers=["/set/cover.jpg"])

    um._dispatch_jobs({group: list(files)}, {"service": "turboimagehost", "auto_gallery": True}, {})

    assert _job_files(bridge) == [["cover.jpg"], ["p1.jpg"]]
    assert bridge.sent[0]["config"]["thumbnail_size"] == "600"
