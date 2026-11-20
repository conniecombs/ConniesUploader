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


# --- Auto-gallery on a host whose prepare_group gives the group its own gallery ------
#
# ImageBam and Turbo create the batch's gallery during upload. Their
# prepare_group used to mark the group's gallery as their own while it still
# held the other host's id, so the dispatcher sent that id to them (ImageBam
# then joined "IMXGAL1" as its gallery token instead of creating a gallery).

FOREIGN = {
    "gallery_id": "IMXGAL1",
    "gallery_name": "Old IMX shoot",
    "gallery_url": "https://imx.to/g/IMXGAL1",
    "gallery_service": "imx.to",
}
IMAGEBAM_CREDS = {"imagebam_user": "user@example.com", "imagebam_pass": "right-pass-123"}


def foreign_group(**overrides):
    group = Group("Set", ["/set/a.jpg"], gallery_id="", gallery_service="")
    for name, value in dict(FOREIGN, **overrides).items():
        setattr(group, name, value)
    return group


def gallery_values(group):
    return {group.gallery_id, group.gallery_name, group.gallery_url} - {""}


def config_values(cfg):
    return {str(value) for value in cfg.values()}


@pytest.mark.parametrize(
    ("service", "creds"),
    [("imagebam.com", IMAGEBAM_CREDS), ("turboimagehost", {})],
)
def test_auto_gallery_never_sends_another_hosts_gallery(monkeypatch, manager, service, creds):
    um, _ = manager
    captured = []
    monkeypatch.setattr(um, "_send_job", lambda files, cfg, creds: captured.append(dict(cfg)))
    group = foreign_group()
    before = gallery_values(group)

    um._dispatch_jobs({group: list(group.files)}, {"service": service, "auto_gallery": True}, creds)

    [cfg] = captured
    assert "IMXGAL1" not in config_values(cfg), cfg
    # The group's gallery is now this host's own, so the gallery link the
    # upload reports is recorded for it.
    assert group.gallery_service == service
    assert not before & {group.gallery_id, group.gallery_url}


def test_imagebam_auto_gallery_creates_a_gallery_instead_of_joining_an_imx_one(
    monkeypatch, manager
):
    from modules.plugins.imagebam import ImageBamPlugin

    um, _ = manager
    captured = []
    monkeypatch.setattr(um, "_send_job", lambda files, cfg, creds: captured.append(dict(cfg)))
    group = foreign_group()

    um._dispatch_jobs(
        {group: list(group.files)},
        {"service": "imagebam.com", "auto_gallery": True},
        IMAGEBAM_CREDS,
    )

    fields = ImageBamPlugin()._upload_session_fields(captured[0])
    assert (fields["gallery"], fields["gallery_token"], fields["gallery_title"]) == (
        "true",
        "",
        "Set",
    )


def test_imagebam_auto_gallery_on_the_legacy_path_creates_a_gallery(manager):
    um, bridge = manager
    group = foreign_group()

    um._dispatch_jobs(
        {group: list(group.files)},
        {"service": "imagebam.com", "auto_gallery": True, "legacy_upload_parsing": True},
        IMAGEBAM_CREDS,
    )

    [job] = bridge.sent
    session = job["http_spec"]["pre_request"]
    while session["action"] != "get_upload_token":
        session = session["follow_up_request"]
    assert session["form_fields"]["gallery_token"] == ""
    assert session["form_fields"]["gallery_title"] == "Set"
    assert "IMXGAL1" not in config_values(job["config"])


def test_imagebam_auto_gallery_on_the_python_path_creates_a_gallery(monkeypatch):
    from tests.imagebam_fakes import FakeImageBam, SiteSidecar

    site = FakeImageBam()
    bridge = SiteSidecar(site)
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
    um = upload_manager.UploadManager(queue.Queue(), queue.Queue(), threading.Event())
    um.current_batch_id = "b1"
    group = foreign_group()
    try:
        um._dispatch_jobs(
            {group: list(group.files)},
            {"service": "imagebam.com", "auto_gallery": True},
            IMAGEBAM_CREDS,
        )
        [opened] = site.requests_to("POST", "/upload/session")
        assert opened["form"]["gallery_token"] == ""
        assert opened["form"]["gallery_title"] == "Set"
        assert [gallery["title"] for gallery in site.galleries] == ["Set"]
    finally:
        um.shutdown()


@pytest.mark.parametrize("legacy", [True, False], ids=["legacy path", "python path"])
def test_turbo_auto_gallery_sends_no_imx_gallery_on_either_path(monkeypatch, legacy):
    from tests.test_turbo_upload_path import TurboSidecar

    bridge = TurboSidecar({})
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
    um = upload_manager.UploadManager(queue.Queue(), queue.Queue(), threading.Event())
    um.current_batch_id = "b1"
    group = foreign_group()
    cfg = {"service": "turboimagehost", "auto_gallery": True, "legacy_upload_parsing": legacy}
    try:
        um._dispatch_jobs({group: list(group.files)}, cfg, {})
        [job] = bridge.jobs()
        assert "IMXGAL1" not in repr(job), job
        request = job["http_spec"] if legacy else job["file_requests"]["/set/a.jpg"]
        assert request["multipart_fields"]["galleryN"]["value"] == "Set"
    finally:
        um.shutdown()


# Every prepare_group that gives the group a gallery must not leave another
# host's gallery behind under its own name; one that gives it none must leave
# the group's host alone, so the dispatcher drops that gallery.


class _ImxGallery:
    gallery_id, gallery_name = "NEWIMX", "Set"
    image_url, thumbnail_url = "https://imx.to/i/1", "https://imx.to/t/1"


def _prepare_cases():
    from modules import api
    from modules.plugins import imagebam, imx, pixhost, turbo, vipr

    vipr_creds = {"vipr_user": "u", "vipr_pass": "p"}
    imx_creds = {"imx_user": "u", "imx_pass": "p", "imx_api": "k"}
    vipr_made = {(api, "create_vipr_gallery"): lambda creds, name: {"id": "V1", "name": name}}
    pix_made = {(api, "create_pixhost_gallery"): lambda name: {"gallery_hash": "PH1"}}
    return [
        ("imagebam", imagebam.ImageBamPlugin, IMAGEBAM_CREDS, {}, {}),
        ("imagebam without credentials", imagebam.ImageBamPlugin, {}, {}, {}),
        ("turbo", turbo.TurboPlugin, {}, {}, {}),
        ("vipr", vipr.ViprPlugin, vipr_creds, vipr_made, {}),
        (
            "vipr, creation failed",
            vipr.ViprPlugin,
            vipr_creds,
            {(api, "create_vipr_gallery"): lambda creds, name: None},
            {},
        ),
        ("pixhost", pixhost.PixhostPlugin, {}, pix_made, {}),
        (
            "pixhost, creation failed",
            pixhost.PixhostPlugin,
            {},
            {(api, "create_pixhost_gallery"): lambda name: None},
            {},
        ),
        (
            "imx",
            imx.ImxPlugin,
            imx_creds,
            {(imx, "create_gallery_with_image"): lambda *args, **kwargs: _ImxGallery()},
            {"gallery_service": "pixhost.to"},
        ),
    ]


@pytest.mark.parametrize("case", _prepare_cases(), ids=lambda case: case[0])
def test_no_prepare_group_claims_another_hosts_gallery(monkeypatch, case):
    _, plugin_class, creds, stubs, overrides = case
    for (module, name), stub in stubs.items():
        monkeypatch.setattr(module, name, stub)
    group = foreign_group(**overrides)
    before = gallery_values(group)
    other_host = group.gallery_service
    context = {"pending_files": list(group.files), "cover_files": []}

    plugin_class().prepare_group(group, {"auto_gallery": True}, context, creds)

    if group.gallery_service == other_host:
        return  # still the other host's: the dispatcher does not send it
    assert not before & gallery_values(group)
