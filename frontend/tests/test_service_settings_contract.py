# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

import json
import queue
import re
import threading
from pathlib import Path

import pytest

from modules import config
from modules.credentials_manager import CredentialsManager
from modules.plugins.imgur import ImgurPlugin
from modules.plugins.turbo import TurboPlugin
from modules.settings_manager import SettingsManager
from modules.upload_manager import COVER_THUMBNAIL_OVERRIDES, UploadManager
from modules.widgets import ServiceSettingsView


@pytest.mark.unit
def test_settings_validation_accepts_imgur_service():
    manager = SettingsManager()
    settings = {**manager.defaults, "service": "imgur.com"}

    assert manager.validate_settings(settings) == []


@pytest.mark.unit
def test_settings_manager_normalizes_worker_and_thread_ranges():
    manager = SettingsManager()

    normalized = manager.normalize_numeric_ranges(
        {
            **manager.defaults,
            "global_worker_count": 99,
            "global_thread_limit": 99,
            "imx_threads": 99,
            "pix_threads": 0,
            "turbo_threads": "not-a-number",
        }
    )

    assert normalized["global_worker_count"] == 16
    assert normalized["global_thread_limit"] == 10
    assert normalized["imx_threads"] == 10
    assert normalized["pix_threads"] == 1
    assert normalized["turbo_threads"] == manager.defaults["turbo_threads"]
    assert manager.validate_settings(normalized) == []


@pytest.mark.unit
def test_settings_manager_migrates_global_thread_limit_from_old_imx_threads(tmp_path):
    manager = SettingsManager()
    manager.filepath = tmp_path / "settings.json"
    manager.filepath.write_text(json.dumps({"imx_threads": 7}), encoding="utf-8")

    loaded = manager.load()

    assert loaded["global_thread_limit"] == 7


@pytest.mark.unit
def test_settings_manager_default_path_uses_user_data_dir(tmp_path, monkeypatch):
    settings_path = tmp_path / ".conniesuploader" / "user_settings.json"
    legacy_path = tmp_path / "user_settings.json"
    monkeypatch.setattr(config, "SETTINGS_FILE", str(settings_path))
    monkeypatch.setattr(config, "LEGACY_SETTINGS_FILE", str(legacy_path))

    manager = SettingsManager()
    manager.save(manager.defaults)

    assert Path(manager.filepath) == settings_path
    assert settings_path.exists()
    assert not legacy_path.exists()


@pytest.mark.unit
def test_settings_manager_migrates_legacy_repo_local_settings(tmp_path, monkeypatch):
    settings_path = tmp_path / ".conniesuploader" / "user_settings.json"
    legacy_path = tmp_path / "user_settings.json"
    legacy_path.write_text(
        json.dumps({"service": "imx.to", "imx_gallery_id": "legacy-gallery"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "SETTINGS_FILE", str(settings_path))
    monkeypatch.setattr(config, "LEGACY_SETTINGS_FILE", str(legacy_path))

    manager = SettingsManager()
    loaded = manager.load()

    assert settings_path.exists()
    assert not legacy_path.exists()
    assert loaded["imx_gallery_id"] == "legacy-gallery"


@pytest.mark.unit
def test_settings_manager_moves_legacy_settings_to_backup_when_current_exists(
    tmp_path, monkeypatch
):
    settings_path = tmp_path / ".conniesuploader" / "user_settings.json"
    legacy_path = tmp_path / "user_settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(json.dumps({"service": "pixhost.to"}), encoding="utf-8")
    legacy_path.write_text(json.dumps({"service": "imx.to"}), encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_FILE", str(settings_path))
    monkeypatch.setattr(config, "LEGACY_SETTINGS_FILE", str(legacy_path))

    manager = SettingsManager()
    loaded = manager.load()

    assert loaded["service"] == "pixhost.to"
    assert not legacy_path.exists()
    assert list(settings_path.parent.glob("user_settings.repo-local-*.json"))


@pytest.mark.unit
def test_imgur_credentials_are_configurable():
    imgur_config = CredentialsManager.SERVICE_CONFIGS["Imgur"]
    keys = {field["key"] for field in imgur_config["fields"]}

    assert {"imgur_client_id", "imgur_access_token"} <= keys


@pytest.mark.unit
def test_upload_manager_accepts_schema_cover_count():
    cfg = {"service": "pixhost.to", "cover_count": "3"}

    assert UploadManager._cover_count_for_service(cfg) == 3


@pytest.mark.unit
def test_upload_manager_prefers_service_specific_cover_count():
    cfg = {"service": "pixhost.to", "pix_cover_count": 4, "cover_count": "1"}

    assert UploadManager._cover_count_for_service(cfg) == 4


@pytest.mark.unit
def test_upload_manager_uses_explicit_cover_files_before_legacy_count():
    class Group:
        title = "Manual Covers"
        files = ["one.jpg", "two.jpg", "three.jpg"]

        def cover_filepaths(self):
            return ["three.jpg"]

    sent_jobs = []
    manager = UploadManager.__new__(UploadManager)
    manager.cancel_event = threading.Event()
    manager.progress_queue = queue.Queue()
    manager.plugin_manager = type(
        "PluginManager",
        (),
        {"get_plugin": lambda self, service_id: None},
    )()
    manager._send_job = lambda files, cfg, creds: sent_jobs.append((list(files), dict(cfg)))

    group = Group()
    manager._dispatch_jobs(
        {group: list(group.files)},
        {"service": "pixhost.to", "pix_cover_count": 1},
        {},
    )

    assert sent_jobs[0][0] == ["three.jpg"]
    assert sent_jobs[0][1]["pix_thumb"] == "500"
    assert sent_jobs[0][1]["thumbnail_size"] == "500"
    assert sent_jobs[1][0] == ["one.jpg", "two.jpg"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("service_id", "expected"),
    [
        ("imx.to", {"thumbnail_size": "600", "imx_thumb": "600"}),
        ("pixhost.to", {"thumbnail_size": "500", "pix_thumb": "500"}),
        ("turboimagehost", {"thumbnail_size": "600", "turbo_thumb": "600"}),
        ("vipr.im", {"thumbnail_size": "800x800", "vipr_thumb": "800x800"}),
        ("imagebam.com", {"thumbnail_size": "300", "imagebam_thumb": "300"}),
        ("imgur.com", {"thumbnail_size": "h", "imgur_thumb": "h"}),
    ],
)
def test_cover_thumbnail_overrides_force_host_max_size(service_id, expected):
    cfg = {
        "service": service_id,
        "thumbnail_size": "180",
        "imx_thumb": "180",
        "pix_thumb": "200",
        "turbo_thumb": "180",
        "vipr_thumb": "170x170",
        "imagebam_thumb": "180",
        "imgur_thumb": "m",
    }

    UploadManager._apply_cover_thumbnail_overrides(cfg)

    for key, value in expected.items():
        assert cfg[key] == value
    assert COVER_THUMBNAIL_OVERRIDES[service_id] == expected


@pytest.mark.unit
def test_turbo_http_request_uses_schema_thumbnail_size():
    request = TurboPlugin().build_http_request(
        "image.jpg",
        {"thumbnail_size": "600", "turbo_thumb": "180"},
        {},
    )

    assert request["multipart_fields"]["thumb_size"]["value"] == "600"
    assert request["multipart_fields"]["qqfilename"]["value"] == "{filename}"


@pytest.mark.unit
def test_turbo_http_request_resolves_deferred_result_page_thumbnails():
    request = TurboPlugin().build_http_request(
        "image.jpg",
        {"thumbnail_size": "180"},
        {},
    )

    assert request["response_parser"]["url_path"] == "newUrl"
    assert request["response_parser"]["thumb_path"] == ""
    assert request["resolve_spec"]["result_url"] == "{url}"
    assert request["resolve_spec"]["gallery_extractor"] == "input#imgCodeGG"
    assert request["resolve_spec"]["file_match_mode"] == "filename"
    assert "img" in request["resolve_spec"]["link_extractor"].lower()
    assert "filename" in request["resolve_spec"]["link_extractor"]
    assert "thumb_url" in request["resolve_spec"]["link_extractor"]
    assert re.search(
        request["resolve_spec"]["link_extractor"],
        "[url=https://www.turboimagehost.com/p/123691283/imx api.jpg.html]"
        "[img]https://s8d9.turboimg.net/t1/123691283_imx_api.jpg[/img][/url]",
    )
    assert re.search(
        request["resolve_spec"]["link_extractor"],
        "[url=https://www.turboimagehost.com/p/123691283/imx_api.jpg.html]"
        "[img]https://s8d9.turboimg.net/t1/123691283_imx_api.jpg[/img][/url]",
    )


@pytest.mark.unit
def test_turbo_http_request_sends_gallery_checkbox_when_creating_gallery():
    request = TurboPlugin().build_http_request(
        "image.jpg",
        {
            "thumbnail_size": "180",
            "turbo_gallery_create": True,
            "turbo_gallery_name": "Batch Gallery",
            "turbo_upload_id": "shared-upload-id",
        },
        {},
    )

    fields = request["multipart_fields"]

    assert fields["galleryC"]["value"] == "1"
    assert fields["galleryN"]["value"] == "Batch Gallery"
    assert fields["upload_id"]["value"] == "shared-upload-id"
    assert "album" not in fields


@pytest.mark.unit
def test_service_aliases_store_imgur_thumbnail_code_from_readable_label():
    view = ServiceSettingsView.__new__(ServiceSettingsView)
    view.service_plugins = {"imgur.com": ImgurPlugin()}

    aliases = view.alias_config(
        "imgur.com",
        {"thumbnail_size": "Medium (320 px)", "content_type": "Safe"},
    )

    assert aliases["imgur_thumb"] == "m"
