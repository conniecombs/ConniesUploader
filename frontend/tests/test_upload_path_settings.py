# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""The legacy_upload_parsing escape hatch and how rows show the Python path's statuses."""

import json

import pytest

from modules import config
from modules.settings_manager import SettingsManager
from modules.ui.main_window import UploaderApp
from tests.app_factory import make_app
from tests.test_main_window_contract import FakeVar


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "user_settings.json"
    monkeypatch.setattr(config, "SETTINGS_FILE", str(path))
    monkeypatch.setattr(config, "LEGACY_SETTINGS_FILE", str(tmp_path / "none.json"), raising=False)
    return path


def test_legacy_upload_parsing_defaults_off(settings_file):
    manager = SettingsManager()
    assert manager.defaults["legacy_upload_parsing"] is False
    assert manager.load()["legacy_upload_parsing"] is False
    assert manager.SETTINGS_SCHEMA["properties"]["legacy_upload_parsing"] == {"type": "boolean"}


@pytest.mark.parametrize(("stored", "loaded"), [(True, True), ("true", True), ("nope", False)])
def test_legacy_upload_parsing_is_read_from_the_settings_file(settings_file, stored, loaded):
    settings_file.write_text(json.dumps({"legacy_upload_parsing": stored}), encoding="utf-8")
    assert SettingsManager().load()["legacy_upload_parsing"] is loaded


def _gather_app(settings):
    app = make_app()
    app.var_service = FakeVar("imx.to")
    app.var_global_worker_count = FakeVar(config.DEFAULT_WORKER_COUNT)
    app.menu_thread_var = FakeVar(config.DEFAULT_THREAD_COUNT)
    app._last_global_thread_limit_value = config.DEFAULT_THREAD_COUNT
    for _, var_name, default in UploaderApp._service_thread_var_specs():
        setattr(app, var_name, FakeVar(default))
    app.settings = settings
    app.var_auto_copy = FakeVar(False)
    app.var_confirm_before_posting = FakeVar(False)
    app.var_auto_gallery = FakeVar(False)
    app.var_show_previews = FakeVar(True)
    app.var_separate_batches = FakeVar(False)
    app.var_appearance_mode = FakeVar("System")
    return app


@pytest.mark.parametrize("stored", [True, False])
def test_the_hidden_setting_reaches_the_upload_and_survives_saving(stored):
    gathered = UploaderApp._gather_settings(_gather_app({"legacy_upload_parsing": stored}))
    assert gathered["legacy_upload_parsing"] is stored


def test_the_hidden_setting_defaults_off_when_missing():
    assert UploaderApp._gather_settings(_gather_app({}))["legacy_upload_parsing"] is False


def test_rows_show_uploaded_as_processing_not_as_a_finished_upload():
    app = make_app()
    assert UploaderApp._friendly_row_status(app, "Uploaded") == "Processing"
    assert UploaderApp._terminal_state_for_status("Uploaded") is None
    assert UploaderApp._friendly_row_status(app, "Uploading") == "Uploading"
    assert UploaderApp._friendly_row_status(app, "Done") == "Uploaded"
