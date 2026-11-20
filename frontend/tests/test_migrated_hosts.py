# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""IMX, Pixhost and Imgur on the Python upload path (v3.2.0 milestone M3)."""

import os
import queue
import threading
import time
from unittest.mock import patch

import pytest

from modules import upload_manager
from modules.imx_api import ImxGalleryUpload
from modules.plugins import helpers, imx
from modules.plugins.base import uses_python_upload_parsing
from modules.plugins.imagebam import ImageBamPlugin
from modules.plugins.imgur import ImgurPlugin
from modules.plugins.imx import ImxPlugin
from modules.plugins.pixhost import PixhostPlugin
from modules.plugins.turbo import TurboPlugin
from modules.plugins.vipr import ViprPlugin
from tests.test_python_upload_path import FakeSidecar

IMX_CREDS = {"imx_api": "api-key-1", "imx_user": "user", "imx_pass": "secret-pass"}
CREDS = {**IMX_CREDS, "imgur_client_id": "client-1"}


def test_plugin_metadata_says_who_implements_the_upload():
    for plugin in (
        ImxPlugin(),
        PixhostPlugin(),
        ImgurPlugin(),
        ViprPlugin(),
        TurboPlugin(),
        ImageBamPlugin(),
    ):
        assert plugin.metadata["implementation"] == "python", plugin.id


def test_preflight_still_checks_the_sidecar_for_python_path_hosts():
    from types import SimpleNamespace

    from modules.ui.main_window import UploaderApp
    from tests.app_factory import make_app

    class DeadBridge:
        def is_process_alive(self):
            return False

        def _start_process(self):
            return False

    app = make_app()
    app.upload_manager = SimpleNamespace(bridge=DeadBridge())
    issues = []
    UploaderApp._preflight_check_sidecar(app, PixhostPlugin(), issues)
    assert issues == [
        "Upload engine is not running. Run build_uploader.bat to rebuild the bundled sidecar."
    ]

    class Standalone:
        metadata = {"implementation": "python"}

    issues = []
    UploaderApp._preflight_check_sidecar(app, Standalone(), issues)
    assert issues == [], "a plugin that uploads without the sidecar needs no engine"


def test_every_host_parses_its_own_responses():
    for plugin in (
        ImxPlugin(),
        PixhostPlugin(),
        ImgurPlugin(),
        ViprPlugin(),
        TurboPlugin(),
        ImageBamPlugin(),
    ):
        assert uses_python_upload_parsing(plugin), plugin.id


@pytest.mark.parametrize(
    ("plugin", "config"),
    [
        (ImxPlugin(), {"thumbnail_size": "600", "thumbnail_format": "Square", "gallery_id": "g1"}),
        (
            PixhostPlugin(),
            {
                "content_type": "Adult",
                "thumbnail_size": "350",
                "gallery_hash": "h1",
                "gallery_upload_hash": "u1",
            },
        ),
        (ImgurPlugin(), {"album_id": "a1", "title": "Holiday {2024}", "thumbnail_size": "l"}),
    ],
    ids=["imx", "pixhost", "imgur"],
)
def test_raw_request_is_the_legacy_request_without_parser_hooks(plugin, config):
    legacy = plugin.build_http_request("/in/a.jpg", config, CREDS)
    session_values = plugin.open_upload_session(None, config, CREDS)

    raw = plugin.build_raw_upload_request("/in/a.jpg", config, session_values, CREDS)

    assert raw == {
        "url": legacy["url"],
        "method": legacy["method"],
        "headers": legacy["headers"],
        "multipart_fields": legacy["multipart_fields"],
    }
    file_fields = [f for f in raw["multipart_fields"].values() if f["type"] == "file"]
    assert file_fields == [{"type": "file", "value": "/in/a.jpg"}]
    assert {f["type"] for f in raw["multipart_fields"].values()} == {"file", "text"}


def test_per_file_values_replace_the_sidecar_tokens(tmp_path):
    first, second = tmp_path / "Scan #1.jpg", tmp_path / "b.jpg"
    first.write_bytes(b"x" * 1234)
    second.write_bytes(b"y" * 10)

    one = helpers.per_file_upload_values(str(first))
    two = helpers.per_file_upload_values(str(second))

    assert one["filename"] == "Scan #1.jpg" and one["file_size"] == "1234"
    assert two["filename"] == "b.jpg" and two["file_size"] == "10"
    assert len(one["upload_id"]) == 12 and one["upload_id"].isalnum()
    assert one["upload_id"] != two["upload_id"]
    assert helpers.per_file_upload_values(str(tmp_path / "missing.jpg"))["file_size"] == ""


def test_imgur_job_options_carry_the_thumbnail_size_to_the_parser():
    plugin = ImgurPlugin()
    assert plugin.open_upload_session(None, {"thumbnail_size": "Huge (1024 px)"}, CREDS) == {
        "thumbnail_size": "h"
    }
    assert plugin.open_upload_session(None, {}, CREDS) == {"thumbnail_size": "m"}


@pytest.fixture
def manager(monkeypatch):
    bridge = FakeSidecar()
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
    progress, results = queue.Queue(), queue.Queue()
    um = upload_manager.UploadManager(progress, results, threading.Event())
    um.current_batch_id = "b1"
    return um, bridge, progress, results


@pytest.mark.parametrize("service", ["imx.to", "pixhost.cc", "imgur.com"])
def test_migrated_hosts_send_raw_jobs_and_the_escape_hatch_sends_legacy_ones(manager, service):
    um, bridge, _, _ = manager
    cfg = {"service": service, "thumbnail_size": "180"}

    um._send_job(["/in/a.jpg"], cfg, CREDS)
    um._send_job(["/in/b.jpg"], dict(cfg, legacy_upload_parsing=True), CREDS)

    new_path, legacy = bridge.jobs()
    assert new_path["raw_response"] is True and new_path["session_id"] == "s-1"
    assert "http_spec" not in new_path
    assert "raw_response" not in legacy and "session_id" not in legacy
    assert legacy["http_spec"]["response_parser"]["type"] == "json"
    assert [r["action"] for r in bridge.requests] == ["session_open"]


def test_imx_auto_gallery_seeds_through_the_api_and_the_rest_upload_into_it(manager):
    um, bridge, progress, results = manager

    class Group:
        title = "Beach"
        files = ["/in/1.jpg", "/in/2.jpg", "/in/3.webp"]
        gallery_id = ""
        gallery_service = ""

    seed = ImxGalleryUpload(
        "gal1", "Beach", "https://imx.to/i/one", "https://i.imx.to/t/2026/01/01/one.jpg"
    )
    with (
        patch.object(imx, "create_gallery_with_image", return_value=seed) as create,
        patch.object(upload_manager.UploadManager, "_remember_imx_gallery_use"),
    ):
        um._dispatch_jobs(
            {Group(): list(Group.files)}, {"service": "imx.to", "auto_gallery": True}, IMX_CREDS
        )

    assert create.call_args.args[2] == "/in/1.jpg"
    assert results.get_nowait() == (
        "/in/1.jpg",
        "https://imx.to/i/one",
        "https://image.imx.to/u/t/2026/01/01/one.jpg",
    )
    [job] = bridge.jobs()
    assert job["raw_response"] is True
    assert job["files"] == [os.path.normpath("/in/2.jpg"), os.path.normpath("/in/3.webp")]
    for request in job["file_requests"].values():
        assert request["multipart_fields"]["gallery_id"] == {"type": "text", "value": "gal1"}
        assert request["headers"] == {"X-API-Key": "api-key-1"}

    for fp in job["files"]:
        um._handle_event(
            {
                "id": job["id"],
                "type": "result",
                "file": fp,
                "data": {
                    "response_body": '{"status":"success","data":{"image_url":"https://imx.to/i/x",'
                    '"thumbnail_url":"https://i.imx.to/t/2026/01/01/x.jpg"}}',
                    "status_code": "200",
                    "final_url": "https://api.imx.to/v1/upload.php",
                },
            }
        )
    um._handle_event({"id": job["id"], "type": "batch_complete", "status": "done"})
    deadline = time.monotonic() + 5
    done = []
    while len(done) < 2 and time.monotonic() < deadline:
        try:
            item = progress.get(timeout=0.1)
        except queue.Empty:
            continue
        if item[0] == "status" and item[2] == "Done" and item[1] != "/in/1.jpg":
            done.append(item[1])
    assert sorted(done) == sorted(job["files"])
    assert results.get_nowait()[2] == "https://image.imx.to/u/t/2026/01/01/x.jpg"


def test_imx_without_credentials_fails_each_file_with_the_reason(manager):
    um, bridge, progress, _ = manager
    um._send_job(["/in/a.jpg"], {"service": "imx.to"}, {})
    assert bridge.jobs() == []
    statuses = [item for item in list(progress.queue) if item[0] == "status"]
    assert statuses == [
        (
            "status",
            "/in/a.jpg",
            "error: IMX uploads require username and password and API key. "
            "Set these in Credentials before uploading.",
        )
    ]
