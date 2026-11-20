"""Every place that falls back to a Turbo thumbnail size uses one Turbo offers."""

from pathlib import Path

from modules.plugins.turbo import TurboPlugin
from modules.settings_manager import SettingsManager

ROOT = Path(__file__).resolve().parents[1]


def test_settings_default_is_a_turbo_size(tmp_path, monkeypatch):
    from modules import config

    monkeypatch.setattr(config, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    defaults = SettingsManager().defaults
    assert defaults["turbo_thumb"] == TurboPlugin.DEFAULT_THUMBNAIL_SIZE


def test_no_code_falls_back_to_an_unlisted_turbo_size():
    for rel in (
        "modules/widgets.py",
        "modules/ui/Main_Window/cover_helpers.py",
        "modules/ui/Main_Window/runtime.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert 'turbo_thumb", "180"' not in text, rel
        assert 'var_turbo_thumb = ctk.StringVar(value="180")' not in text, rel
