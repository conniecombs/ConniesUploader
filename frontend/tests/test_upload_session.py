# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Upload session lifecycle: start, finish accounting, outputs and clearing."""

import queue
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from modules.ui.main_window import UploaderApp
from tests.app_factory import make_app
from tests.test_main_window_contract import (
    FakeFrame,
    FakeGroup,
    FakeLabel,
    FakeProgress,
    FakeVar,
)


def _row(group, state="pending", **extra):
    row = {
        "row": FakeFrame(),
        "state": state,
        "group": group,
        "status": FakeLabel(),
        "prog": FakeProgress(),
        "retry": FakeFrame(),
        "error_label": FakeFrame(),
        "remove": FakeFrame(),
        "image_ref": None,
        "error": "",
    }
    row.update(extra)
    return row


def _ui_app(tmp_path=None):
    """App with the widget fakes the upload/progress/output paths touch."""
    app = make_app()
    app.lock = Lock()
    app.activity = []
    app.add_activity = lambda message, level="info": app.activity.append((message, level))
    app.log = lambda _message: None
    app.lbl_eta = FakeLabel()
    app.btn_open = FakeFrame()
    app.overall_progress = FakeProgress()
    app.var_auto_copy = FakeVar(False)
    for name in ("imx", "pix", "turbo", "vipr"):
        setattr(app, f"var_{name}_links", FakeVar(False))
    app.settings = {"service": "imagebam.com"}
    app.saved_threads_data = {}
    app.auto_poster = SimpleNamespace(
        queue_post=Mock(return_value=None), skip=Mock(), begin_session=Mock()
    )
    app._set_completion_summary = Mock()
    app._set_import_checks = Mock()
    app._set_upload_checks = Mock()
    app._refresh_queue_state = Mock()
    app._refresh_start_button_state = Mock()
    app._configure_stop_button = Mock()
    app._configure_start_button = Mock()
    app._refresh_selection_actions = Mock()
    app.template_mgr = SimpleNamespace(
        apply=lambda name, context, results: "\n".join(url for url, _, _ in results)
    )
    if tmp_path is not None:
        app.output_dir = str(tmp_path / "Output")
        app.central_history_path = str(tmp_path / "history")
        Path(app.central_history_path).mkdir(parents=True, exist_ok=True)
    return app


def _start_ready_app(tmp_path, saved):
    """App whose start_upload passes preflight and records what it saves/starts."""
    app = _ui_app(tmp_path)
    app.creds = {"imx_api": "SECRET-IMX-KEY", "imx_user": "u", "imx_pass": "p"}
    app._gather_settings = lambda: {"service": "imagebam.com", "global_worker_count": 8}
    app._run_upload_preflight = lambda pending, cfg: ([], "ready")
    app._prepare_poster_session = lambda pending: []
    app._increment_firebase_counter = lambda: None
    app._register_selected_pixhost_galleries_for_finalization = lambda *args: None
    app.settings_mgr = SimpleNamespace(save=lambda cfg: saved.append(dict(cfg)))
    app.upload_manager = SimpleNamespace(start_batch=Mock(), result_queue=None)
    return app


@pytest.fixture
def no_worker_restart(monkeypatch):
    from modules.sidecar import SidecarBridge

    monkeypatch.setattr(SidecarBridge, "set_worker_count", classmethod(lambda cls, n: None))
    monkeypatch.setattr(
        "modules.ui.Main_Window.upload_checks.threading.Thread",
        lambda target=None, **kwargs: SimpleNamespace(start=lambda: None),
    )


@pytest.mark.unit
def test_start_upload_keeps_imx_api_key_out_of_saved_settings(tmp_path, no_worker_restart):
    saved = []
    app = _start_ready_app(tmp_path, saved)
    group = FakeGroup("Set", ["/s/1.jpg"])
    app.groups = [group]
    app.file_widgets = {"/s/1.jpg": _row(group)}

    UploaderApp.start_upload(app)

    assert app.is_uploading is True
    assert saved and all("api_key" not in cfg for cfg in saved)
    assert "api_key" not in app.settings
    pending, upload_cfg, creds = app.upload_manager.start_batch.call_args.args
    assert "SECRET-IMX-KEY" not in upload_cfg.values()
    assert creds["imx_api"] == "SECRET-IMX-KEY"
