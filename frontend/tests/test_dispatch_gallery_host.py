# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""A batch's gallery is only sent to the host that gallery belongs to."""

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
    def __init__(self, title, files, gallery_id, gallery_service):
        self.title = title
        self.files = list(files)
        self.cover_files = []
        self.gallery_id = gallery_id
        self.gallery_name = "Old shoot"
        self.gallery_url = ""
        self.gallery_service = gallery_service


@pytest.fixture
def manager(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
    um = upload_manager.UploadManager(queue.Queue(), queue.Queue(), threading.Event())
    um.current_batch_id = "b1"
    return um, bridge


def _dispatch(um, group, service):
    um._dispatch_jobs(
        {group: list(group.files)},
        {"service": service, "legacy_upload_parsing": True},
        {},
    )


def test_gallery_assigned_for_another_host_is_not_sent(manager):
    um, bridge = manager
    group = Group("Set", ["/set/a.jpg"], gallery_id="IMXGAL1", gallery_service="imx.to")

    _dispatch(um, group, "turboimagehost")

    assert len(bridge.sent) == 1
    sent_config = bridge.sent[0]["config"]
    assert "IMXGAL1" not in sent_config.values()


def test_gallery_assigned_for_the_same_host_is_sent(manager):
    um, bridge = manager
    group = Group("Set", ["/set/a.jpg"], gallery_id="777", gallery_service="turboimagehost")

    _dispatch(um, group, "turboimagehost")

    assert bridge.sent[0]["config"]["gallery_id"] == "777"


def test_output_and_preflight_ignore_a_gallery_for_another_host():
    from modules.ui.main_window import UploaderApp
    from tests.app_factory import make_app

    app = make_app()
    group = Group("Set", ["/set/a.jpg"], gallery_id="IMXGAL1", gallery_service="imx.to")
    gallery = UploaderApp._gallery_for_group(app, group, "turboimagehost", {})
    assert not gallery or gallery.get("id") != "IMXGAL1"
    same = UploaderApp._gallery_for_group(app, group, "imx.to", {})
    assert same and same["id"] == "IMXGAL1"
