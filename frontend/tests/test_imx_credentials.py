# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Credential policy gates must run before requests, including retries."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from modules.gallery_manager import GalleryManager
from modules.gallery_service import GalleryService, GalleryStatus
from modules.imx_api import ImxApiError
from modules.plugins.imx import ImxPlugin
from modules.ui.main_window import UploaderApp


CREDS = {"imx_user": "test-user", "imx_pass": "test-password", "imx_api": "test-key"}


@pytest.mark.parametrize("missing", ["imx_user", "imx_pass", "imx_api"])
@pytest.mark.parametrize("auto_gallery", [False, True])
def test_upload_policy_blocks_ui_and_runtime_when_a_credential_is_missing(missing, auto_gallery):
    creds = {**CREDS, missing: " \t "}
    plugin = ImxPlugin()
    app = UploaderApp.__new__(UploaderApp)
    app.creds = creds
    app.service_plugins = {"imx.to": plugin}
    cfg = {"auto_gallery": auto_gallery}
    readiness = app._host_readiness_for("imx.to", cfg)
    assert readiness["level"] == "error" and readiness["action_required"]
    issues = []
    app._preflight_check_credentials(plugin, cfg, issues)
    assert len(issues) == 1
    group = SimpleNamespace(title="Test", gallery_service="imx.to", gallery_id="existing")
    with pytest.raises(ImxApiError):
        plugin.prepare_group(group, cfg, {"pending_files": ["first.png"]}, creds)
    with pytest.raises(ImxApiError):
        plugin.build_http_request("first.png", cfg, creds)


def test_complete_upload_credentials_build_request_without_transmitting_password():
    request = ImxPlugin().build_http_request("first.png", {}, CREDS)
    assert request["headers"]["X-API-Key"] == "test-key"
    assert "test-password" not in str(request)
    assert "test-user" not in str(request)


@pytest.mark.parametrize("operation", ["list", "sync", "create", "create_image", "delete"])
@pytest.mark.parametrize("manual_cookie", [False, True])
def test_every_live_gallery_operation_requires_api_key_before_network(monkeypatch, operation, manual_cookie):
    session_factory = Mock(side_effect=AssertionError("Must not contact IMX without API key"))
    monkeypatch.setattr("modules.gallery_service.requests.Session", session_factory)
    service = GalleryService(None, {**CREDS, "imx_api": ""})
    if manual_cookie:
        service.set_imx_php_session("test-session")
    operations = {
        "list": lambda: service.list_galleries("imx.to"),
        "sync": lambda: service.sync_all_galleries("imx.to"),
        "create": lambda: service.create_gallery("imx.to", "Test"),
        "create_image": lambda: service.create_gallery("imx.to", "Test", initial_image="first.png"),
        "delete": lambda: service.delete_gallery("imx.to", "abc123"),
    }
    result = operations[operation]()
    assert result.status == GalleryStatus.MISSING_CREDENTIALS
    assert "API key" in result.message
    session_factory.assert_not_called()


@pytest.mark.parametrize("missing", ["imx_user", "imx_pass"])
def test_first_image_gallery_creation_also_obeys_upload_policy(monkeypatch, missing):
    upload = Mock(side_effect=AssertionError("Must not upload without username/password"))
    monkeypatch.setattr("modules.gallery_service.create_gallery_with_image", upload)
    service = GalleryService(None, {**CREDS, missing: ""})
    result = service.create_gallery("imx.to", "Test", initial_image="first.png")
    assert result.status == GalleryStatus.MISSING_CREDENTIALS
    assert "uploads require" in result.message
    upload.assert_not_called()


def test_gallery_manager_does_not_open_cached_imx_management_without_api_key():
    manager = GalleryManager.__new__(GalleryManager)
    manager.creds = {**CREDS, "imx_api": ""}
    manager._update_service_mode = Mock()
    manager._selected_service = lambda: "imx.to"
    manager._render_result_message = Mock()
    manager.gallery_cache = Mock()
    manager._load_cached_or_refresh()
    result = manager._render_result_message.call_args.args[0]
    assert result.status == GalleryStatus.MISSING_CREDENTIALS
    manager.gallery_cache.records_for_service.assert_not_called()


def test_gallery_manager_checks_upload_credentials_before_choosing_image(monkeypatch):
    manager = GalleryManager.__new__(GalleryManager)
    manager.creds = {"imx_api": "key"}
    manager.ent_name = Mock()
    manager.ent_name.get.return_value = "Test"
    manager._selected_service = lambda: "imx.to"
    manager._set_status = Mock()
    choose = Mock()
    monkeypatch.setattr("modules.gallery_manager.filedialog.askopenfilename", choose)
    manager._create_gallery()
    choose.assert_not_called()
    assert "username and password" in manager._set_status.call_args.args[0]
