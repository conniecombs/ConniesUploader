"""The template recovery notice describes what actually happened."""

from modules.ui.Main_Window import menu_actions
from tests.app_factory import make_app


class _Widget:
    created = []

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        _Widget.created.append(self)

    def __getattr__(self, name):
        return lambda *a, **k: None


class _FakeCtk:
    CTkToplevel = CTkLabel = CTkFrame = CTkButton = _Widget


def _show(monkeypatch, issue):
    _Widget.created = []
    monkeypatch.setattr(menu_actions, "ctk", _FakeCtk)
    app = make_app()
    activity = []
    app.add_activity = lambda message, level="info": activity.append((message, level))
    app.template_mgr = type("Mgr", (), {"get_recovery_issue": lambda self: issue})()
    app._show_template_recovery_notice()
    texts = [w.kwargs.get("text", "") for w in _Widget.created]
    return activity, texts


def test_skipped_entries_notice_does_not_claim_defaults_were_restored(monkeypatch):
    issue = {
        "filepath": "/x/templates.json",
        "backup_path": "/x/templates.json.broken-1.bak",
        "error": "Skipped 1 saved template(s) whose content is not text: Mine.",
        "message": (
            "Some saved templates could not be loaded and were skipped. "
            "The other templates were kept and the original file was preserved."
        ),
    }
    activity, texts = _show(monkeypatch, issue)
    assert activity == [(issue["message"], "warning")]
    assert issue["message"] in texts
    assert not any("restored the built-in templates" in text for text in texts)


def test_unreadable_file_notice_keeps_its_message(monkeypatch):
    issue = {
        "filepath": "/x/templates.json",
        "backup_path": "",
        "error": "Expecting value",
        "message": "Saved templates could not be loaded. Defaults were restored and the broken file was preserved.",
    }
    activity, texts = _show(monkeypatch, issue)
    assert activity == [(issue["message"], "warning")]
    assert issue["message"] in texts
