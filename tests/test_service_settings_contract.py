# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

import pytest

from modules.credentials_manager import CredentialsManager
from modules.plugins.imgur import ImgurPlugin
from modules.settings_manager import SettingsManager
from modules.upload_manager import UploadManager
from modules.widgets import ServiceSettingsView


@pytest.mark.unit
def test_settings_validation_accepts_imgur_service():
    manager = SettingsManager()
    settings = {**manager.defaults, "service": "imgur.com"}

    assert manager.validate_settings(settings) == []


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
def test_service_aliases_store_imgur_thumbnail_code_from_readable_label():
    view = ServiceSettingsView.__new__(ServiceSettingsView)
    view.service_plugins = {"imgur.com": ImgurPlugin()}

    aliases = view.alias_config(
        "imgur.com",
        {"thumbnail_size": "Medium (320 px)", "content_type": "Safe"},
    )

    assert aliases["imgur_thumb"] == "m"
