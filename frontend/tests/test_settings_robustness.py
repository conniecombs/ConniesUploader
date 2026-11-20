# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Settings file robustness: bad values, corrupt files, atomic saves, no secrets."""

import json
import os

import pytest

from modules import config
from modules.exceptions import InvalidConfigException
from modules.settings_manager import SettingsManager
from modules.ui.Main_Window import settings as settings_mixin_module
from tests.app_factory import make_app

_BASE = {"service": "pixhost.cc", "pix_thumb": "350", "auto_copy": True}


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", str(tmp_path / "user_settings.json"))
    monkeypatch.setattr(config, "LEGACY_SETTINGS_FILE", None)
    return SettingsManager()


def _write(manager, data=None, raw=None):
    with open(manager.filepath, "w", encoding="utf-8") as handle:
        handle.write(raw if raw is not None else json.dumps(data))


def _read(manager):
    with open(manager.filepath, encoding="utf-8") as handle:
        return json.load(handle)


# --- E5: one bad value repairs only that key --------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("key", "bad", "expected"),
    [
        ("imx_cover_count", "3", 3),
        ("imx_cover_count", None, 0),
        ("imx_cover_count", 11, 10),
        ("imx_cover_count", 2.5, 0),
        ("imx_cover_count", True, 0),
        ("auto_copy", "yes", False),
        ("auto_copy", "true", True),
        ("pix_thumb", 350, "350"),
        ("imx_thumb", "big", "180"),
        ("pix_content", "Spicy", "Safe"),
        ("service", None, "imx.to"),
    ],
)
def test_load_repairs_only_the_bad_key(manager, key, bad, expected):
    _write(manager, {**_BASE, key: bad})

    loaded = manager.load()

    assert loaded[key] == expected
    for other_key, value in _BASE.items():
        if other_key != key:
            assert loaded[other_key] == value
    assert manager.get_recovery_issue() is None
    assert any(key in note for note in manager.repairs)


@pytest.mark.unit
@pytest.mark.parametrize(("saved", "expected"), [("180", "200"), ("120", "150"), ("700", "600")])
def test_load_moves_a_turbo_size_turbo_does_not_offer_to_the_nearest_one(
    manager, saved, expected
):
    # Before v3.2.0 the Turbo default was 180, which Turbo does not offer:
    # uploads send the nearest offered size, so #thumb_size# must say the same.
    _write(manager, {"service": "turboimagehost", "turbo_thumb": saved})

    loaded = manager.load()

    assert loaded["turbo_thumb"] == expected
    assert any(note.startswith("turbo_thumb:") for note in manager.repairs)
    assert manager.get_recovery_issue() is None


@pytest.mark.unit
def test_load_keeps_a_turbo_size_turbo_offers(manager):
    _write(manager, {"service": "turboimagehost", "turbo_thumb": "350"})

    assert manager.load()["turbo_thumb"] == "350"
    assert manager.repairs == []


@pytest.mark.unit
def test_load_drops_bad_optional_key_without_default(manager):
    _write(manager, {**_BASE, "gallery_id": 123456, "auto_gallery": "maybe"})

    loaded = manager.load()

    assert loaded["gallery_id"] == "123456"
    assert "auto_gallery" not in loaded
    assert loaded["service"] == "pixhost.cc"


@pytest.mark.unit
def test_load_returns_a_copy_of_the_defaults(manager):
    loaded = manager.load()
    loaded["service"] = "vipr.im"

    assert manager.defaults["service"] == "imx.to"


# --- E5: corrupt file is backed up and replaced, not a crash ---------------


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["", "{not json", "[]", '"text"', "\x00\x01"])
def test_corrupt_settings_file_is_backed_up_and_replaced(manager, raw):
    _write(manager, raw=raw)

    loaded = manager.load()

    assert loaded == manager.defaults
    issue = manager.get_recovery_issue()
    assert issue is not None
    with open(issue["backup_path"], encoding="utf-8") as handle:
        assert handle.read() == raw
    assert _read(manager)["service"] == manager.defaults["service"]
    assert SettingsManager().load()["service"] == manager.defaults["service"]


@pytest.mark.unit
def test_settings_saved_with_a_utf8_bom_load_instead_of_being_reset(manager):
    # Notepad and some editors save UTF-8 with a byte order mark.
    with open(manager.filepath, "w", encoding="utf-8-sig") as handle:
        json.dump(_BASE, handle)

    loaded = manager.load()

    assert manager.get_recovery_issue() is None
    assert loaded["service"] == "pixhost.cc"
    assert loaded["pix_thumb"] == "350"
    assert loaded["auto_copy"] is True
    with open(manager.filepath, encoding="utf-8-sig") as handle:
        assert json.load(handle) == _BASE


@pytest.mark.unit
def test_startup_shows_notice_when_settings_were_reset(monkeypatch, tmp_path):
    app = make_app()
    activity = []
    warnings = []
    app.add_activity = lambda message, level="info": activity.append((message, level))
    monkeypatch.setattr(
        settings_mixin_module.messagebox,
        "showwarning",
        lambda title, message, **kwargs: warnings.append((title, message)),
        raising=False,
    )
    backup = str(tmp_path / "user_settings.json.broken-1.bak")
    app.settings_mgr = type(
        "Manager",
        (),
        {"get_recovery_issue": lambda self: {"backup_path": backup, "error": "bad json"}},
    )()

    app._show_settings_recovery_notice()

    assert activity and activity[0][1] == "warning"
    assert len(warnings) == 1
    assert backup in warnings[0][1]


@pytest.mark.unit
def test_startup_notice_is_silent_when_settings_loaded_fine():
    app = make_app()
    activity = []
    app.add_activity = lambda message, level="info": activity.append(message)
    app.settings_mgr = type("Manager", (), {"get_recovery_issue": lambda self: None})()

    app._show_settings_recovery_notice()

    assert activity == []


# --- E5: save validates first and writes atomically -------------------------


@pytest.mark.unit
@pytest.mark.parametrize(("bad", "expected"), [("3", 3), (None, 0)])
def test_save_repairs_bad_values_instead_of_raising_type_error(manager, bad, expected):
    manager.save({"service": "imx.to", "imx_cover_count": bad})

    assert _read(manager)["imx_cover_count"] == expected


@pytest.mark.unit
def test_failed_save_leaves_existing_file_intact(manager):
    manager.save(_BASE)
    with open(manager.filepath, encoding="utf-8") as handle:
        before = handle.read()

    with pytest.raises(InvalidConfigException):
        manager.save({**_BASE, "selected_gallery_by_service": {"imx.to": {"id": {1, 2}}}})

    with open(manager.filepath, encoding="utf-8") as handle:
        assert handle.read() == before
    assert os.listdir(os.path.dirname(manager.filepath)) == ["user_settings.json"]


# --- E5: the IMX API key never lives in the settings file -------------------


@pytest.mark.unit
def test_save_never_writes_api_key(manager):
    manager.save({**_BASE, "api_key": "SECRET"})

    assert "api_key" not in _read(manager)


@pytest.mark.unit
def test_load_scrubs_stored_api_key_from_memory_and_disk(manager):
    _write(manager, {**_BASE, "api_key": "SECRET"})

    loaded = manager.load()

    assert "api_key" not in loaded
    assert loaded["service"] == "pixhost.cc"
    with open(manager.filepath, encoding="utf-8") as handle:
        assert "SECRET" not in handle.read()
