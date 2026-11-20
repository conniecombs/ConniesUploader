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


@pytest.mark.unit
def test_second_upload_starts_with_fresh_output_and_counts_only_its_files(
    tmp_path, no_worker_restart
):
    saved = []
    app = _start_ready_app(tmp_path, saved)
    earlier = FakeGroup("Alpha", ["/a/1.jpg"])
    later = FakeGroup("Beta", ["/b/1.jpg"])
    app.groups = [earlier, later]
    app.file_widgets = {
        "/a/1.jpg": _row(earlier, "success", upload_result=("http://v/a", "http://t/a")),
        "/b/1.jpg": _row(later),
    }
    previous_output = str(tmp_path / "Alpha.txt")
    app.current_output_files = [previous_output]
    app.copyable_output_files = [previous_output]
    app.clipboard_buffer = ["run one text"]

    UploaderApp.start_upload(app)

    assert app.current_output_files == []
    assert app.copyable_output_files == []
    assert app.clipboard_buffer == []
    assert app.upload_total == 1

    app.file_widgets["/b/1.jpg"]["state"] = "success"
    summary = UploaderApp._build_completion_summary(app)

    assert summary["uploaded_count"] == 1
    assert summary["total_count"] == 1
    assert summary["status_text"] == "Upload complete: 1 file uploaded."
    assert summary["output_files"] == []


@pytest.fixture
def frozen_minute(monkeypatch):
    from datetime import datetime

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 20, 19, 8, 30)

    monkeypatch.setattr("modules.ui.Main_Window.runtime.datetime", FrozenDatetime)


def _output_app(tmp_path, results):
    app = _ui_app(tmp_path)
    app.results = list(results)
    app.var_auto_copy = FakeVar(True)
    app.var_imagebam_links = FakeVar(False)
    app.settings = {"service": "imagebam.com", "save_links": True}
    return app


@pytest.mark.unit
@pytest.mark.parametrize("titles", [("Photos", "Photos"), ("Set (1)", "Set [1]")])
def test_batches_with_colliding_output_names_never_overwrite(
    tmp_path, frozen_minute, monkeypatch, titles
):
    monkeypatch.setattr("modules.ui.Main_Window.runtime.pyperclip.copy", lambda text: None)
    first = FakeGroup(titles[0], ["/2024/Photos/a.jpg"])
    second = FakeGroup(titles[1], ["/2025/Photos/b.jpg"])
    for group in (first, second):
        group.selected_template = "BBCode"
    app = _output_app(
        tmp_path,
        [
            ("/2024/Photos/a.jpg", "http://v/a", "http://t/a"),
            ("/2025/Photos/b.jpg", "http://v/b", "http://t/b"),
        ],
    )

    UploaderApp.generate_group_output(app, first)
    UploaderApp.generate_group_output(app, second)

    outputs = app.current_output_files
    assert len(outputs) == len(set(outputs)) == 2
    assert [Path(path).read_text(encoding="utf-8") for path in outputs] == [
        "http://v/a",
        "http://v/b",
    ]
    output_dir = Path(app.output_dir)
    assert sorted(p.name for p in output_dir.glob("*_links.txt")) == sorted(
        f"{Path(path).stem}_links.txt" for path in outputs
    )
    links = sorted(p.read_text(encoding="utf-8") for p in output_dir.glob("*_links.txt"))
    assert links == ["http://v/a", "http://v/b"]
    history = sorted(p.read_text() for p in Path(app.central_history_path).iterdir())
    assert history == ["http://v/a", "http://v/b"]
    summary = UploaderApp._build_completion_summary(app)
    assert UploaderApp._completion_output_text(app, summary) == "http://v/a\n\nhttp://v/b"


@pytest.mark.unit
def test_failed_reports_with_the_same_name_never_overwrite(tmp_path, frozen_minute):
    first = FakeGroup("Photos", ["/x/a.jpg"])
    second = FakeGroup("Photos", ["/y/b.jpg"])
    app = _output_app(tmp_path, [])
    app.file_widgets = {
        "/x/a.jpg": _row(first, "failed", error="first reason"),
        "/y/b.jpg": _row(second, "failed", error="second reason"),
    }

    UploaderApp.generate_failed_group_output(app, first, 1)
    UploaderApp.generate_failed_group_output(app, second, 1)

    reports = app.current_output_files
    assert len(set(reports)) == 2
    assert all(path.endswith("_FAILED.txt") for path in reports)
    assert "first reason" in Path(reports[0]).read_text(encoding="utf-8")
    assert "second reason" in Path(reports[1]).read_text(encoding="utf-8")
    assert len(list(Path(app.central_history_path).iterdir())) == 2


@pytest.mark.unit
@pytest.mark.parametrize(
    "service, viewer, thumb, direct",
    [
        (
            "pixhost.cc",
            "https://pixhost.to/show/42/a1.jpg",
            "https://t1.pixhost.to/thumbs/42/a1.jpg",
            "https://img1.pixhost.to/images/42/a1.jpg",
        ),
        (
            "pixhost.cc",
            "https://pixhost.cc/show/42/a1.jpg",
            "https://t17.pixhost.cc/thumbs/42/a1.jpg",
            "https://img17.pixhost.cc/images/42/a1.jpg",
        ),
        (
            "pixhost.cc",
            "https://pixhost.cc/show/42/image.html",
            "https://img.pixhost.cc/thumbs/42/image.jpg",
            "https://img.pixhost.cc/images/42/image.jpg",
        ),
        (
            "imx.to",
            "https://imx.to/i/abc",
            "https://image.imx.to/u/t/2026/11/20/abc.jpg",
            "https://image.imx.to/u/i/2026/11/20/abc.jpg",
        ),
        (
            "imgur.com",
            "https://i.imgur.com/abc.jpg",
            "https://i.imgur.com/abc.jpg",
            "https://i.imgur.com/abc.jpg",
        ),
        (
            "turboimagehost",
            "https://www.turboimagehost.com/p/1/a.jpg.html",
            "https://s1d1.turboimg.net/t1/1_a.jpg",
            "https://s1d1.turboimg.net/t1/1_a.jpg",
        ),
        ("vipr.im", "https://vipr.im/abc.html", "", ""),
    ],
)
def test_direct_url_is_an_image_never_a_viewer_page(service, viewer, thumb, direct):
    from modules.ui.Main_Window.runtime import direct_image_url

    assert direct_image_url(service, viewer, thumb) == direct


@pytest.mark.unit
def test_pixhost_full_image_post_embeds_images_not_viewer_pages(tmp_path):
    from modules.template_manager import TemplateManager

    files = ["/a/a1.jpg", "/a/a2.jpg"]
    group = FakeGroup("Alpha", files)
    group.selected_template = "ViperGirls Full Image Post"
    app = _output_app(
        tmp_path,
        [
            (fp, f"https://pixhost.to/show/42/{name}", f"https://t1.pixhost.to/thumbs/42/{name}")
            for fp, name in zip(files, ("a1.jpg", "a2.jpg"))
        ],
    )
    app.var_auto_copy = FakeVar(False)
    app.settings = {"service": "pixhost.cc"}
    app.template_mgr = TemplateManager(str(tmp_path / "templates.json"))

    UploaderApp.generate_group_output(app, group)

    text = Path(app.current_output_files[0]).read_text(encoding="utf-8")
    assert "[img]https://img1.pixhost.to/images/42/a1.jpg[/img]" in text
    assert "[img]https://img1.pixhost.to/images/42/a2.jpg[/img]" in text
    assert "/show/" not in text


def _template_app(tmp_path):
    from modules.template_manager import TemplateManager

    app = _output_app(tmp_path, [("/s/a1.jpg", "https://h/show/A1", "https://h/t/A1.jpg")])
    app.var_auto_copy = FakeVar(False)
    app.settings = {"service": "imagebam.com"}
    app.template_mgr = TemplateManager(str(tmp_path / "templates.json"))
    app.saved_threads_data = {"T": {"thread_id": "123"}}
    group = FakeGroup("Set", ["/s/a1.jpg"])
    group.selected_template = "Mine"
    group.selected_thread = "T"
    group.batch_index = 0
    app.groups = [group]
    return app, group


@pytest.mark.unit
def test_output_for_a_deleted_template_falls_back_to_the_default(tmp_path):
    app, group = _template_app(tmp_path)
    app.template_mgr.set_template("Mine", "[b]#batch_name#[/b]\n#all_images#")
    app.template_mgr.rename_template("Mine", "Mine v2")
    app.is_uploading = True

    UploaderApp.generate_group_output(app, group)

    text = Path(app.current_output_files[0]).read_text(encoding="utf-8")
    assert "https://h/t/A1.jpg" in text
    assert group.selected_template == "BBCode"
    assert any(
        level == "warning" and '"Mine"' in message and '"BBCode"' in message
        for message, level in app.activity
    )
    posted_text = app.auto_poster.queue_post.call_args.args[1]
    assert posted_text == text


@pytest.mark.unit
def test_empty_rendered_output_is_never_written_or_posted(tmp_path):
    app, group = _template_app(tmp_path)
    app.template_mgr = SimpleNamespace(
        apply=lambda name, context, results: "  \n",
        get_all_keys=lambda: ["BBCode", "Mine"],
    )

    UploaderApp.generate_group_output(app, group)

    assert app.current_output_files == []
    assert not Path(app.output_dir).exists() or list(Path(app.output_dir).iterdir()) == []
    app.auto_poster.queue_post.assert_not_called()
    app.auto_poster.skip.assert_called_once()
    assert app.auto_poster.skip.call_args.args[0] == 0
    assert any(
        level == "warning" and "produced no text" in message for message, level in app.activity
    )


@pytest.mark.unit
def test_template_changes_switch_batches_off_missing_templates(tmp_path):
    from modules.template_manager import TemplateManager

    app = _ui_app(tmp_path)
    app.template_mgr = TemplateManager(str(tmp_path / "templates.json"))
    app.template_mgr.set_template("Mine v2", "#all_images#")
    stale = SimpleNamespace(
        title="Old", selected_template="Mine", update_template_names=Mock(return_value=True)
    )
    current = SimpleNamespace(
        title="New", selected_template="Mine v2", update_template_names=Mock(return_value=False)
    )
    app.groups = [stale, current]

    UploaderApp._on_templates_changed(app, "Mine v2")

    names = app.template_mgr.get_all_keys()
    stale.update_template_names.assert_called_once_with(names, "BBCode")
    current.update_template_names.assert_called_once_with(names, "BBCode")
    assert [level for _message, level in app.activity] == ["warning"]


@pytest.mark.unit
def test_template_editor_reports_changes_to_the_main_window(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "modules.ui.Main_Window.menu_actions.TemplateEditor",
        lambda *args, **kwargs: captured.update(kwargs),
    )
    app = make_app()
    app.template_mgr = SimpleNamespace()
    app.get_preview_data = lambda: {}

    UploaderApp.open_template_editor(app)

    assert captured["update_callback"] == app._on_templates_changed


def _real_group(title, files=()):
    """A CollapsibleGroupFrame with fake child widgets (no Tk interpreter)."""
    from modules.widgets import CollapsibleGroupFrame

    group = CollapsibleGroupFrame.__new__(CollapsibleGroupFrame)
    group.title = title
    group.files = list(files)
    group.cover_files = []
    group.cover_selection_manual = False
    group.is_completed = False
    group.completed_with_failures = False
    group.selected_thread = "Do Not Post"
    group.selected_template = "BBCode"
    group.batch_index = 0
    group.gallery_id = ""
    group.gallery_url = ""
    group.template_var = None
    group.template_combo = None
    group.lbl_title = FakeFrame()
    group.lbl_counts = FakeLabel()
    group.prog = FakeProgress()
    group.winfo_exists = lambda: True
    group.destroy = lambda: None
    return group


def _upload(app, files, results):
    """Run one upload of ``files`` through the result/progress handling."""
    app.is_uploading = True
    app.upload_count = 0
    app.upload_total = len(files)
    for fp in files:
        app.file_widgets[fp]["state"] = "queued"
        viewer, thumb, status = results[fp]
        app.result_queue.put((fp, viewer, thumb))
        app.progress_queue.put(("status", fp, status))
    UploaderApp._process_result_queue(app)
    UploaderApp._process_progress_queue(app)
    app.is_uploading = False


@pytest.mark.unit
def test_files_added_to_a_completed_batch_produce_output_again(tmp_path):
    app = _ui_app(tmp_path)
    app.progress_queue, app.result_queue = queue.Queue(), queue.Queue()
    group = _real_group("Miscellaneous")
    app.groups = [group]
    group.add_file("/p/a.jpg")
    app.file_widgets["/p/a.jpg"] = _row(group)
    _upload(app, ["/p/a.jpg"], {"/p/a.jpg": ("http://v/a", "http://t/a", "Done")})
    assert group.is_completed is True
    assert len(app.current_output_files) == 1

    # Later loose files reuse the existing "Miscellaneous" batch.
    group.add_file("/p/b.jpg")
    app.file_widgets["/p/b.jpg"] = _row(group)
    assert group.is_completed is False
    _upload(app, ["/p/b.jpg"], {"/p/b.jpg": ("http://v/b", "http://t/b", "Done")})

    assert group.is_completed is True
    assert len(app.current_output_files) == 2
    assert Path(app.current_output_files[1]).read_text(encoding="utf-8") == (
        "http://v/a\nhttp://v/b"
    )


@pytest.mark.unit
def test_removing_the_failed_image_gives_the_batch_its_output(tmp_path):
    app = _ui_app(tmp_path)
    app.progress_queue, app.result_queue = queue.Queue(), queue.Queue()
    app.image_refs = set()
    app._clear_highlights = lambda *args: None
    group = _real_group("Set", ["/s/1.jpg", "/s/2.jpg", "/s/bad.jpg"])
    group.selected_thread = "T"
    app.groups = [group]
    for fp in group.files:
        app.file_widgets[fp] = _row(group)
    _upload(
        app,
        list(group.files),
        {
            "/s/1.jpg": ("http://v/1", "http://t/1", "Done"),
            "/s/2.jpg": ("http://v/2", "http://t/2", "Done"),
            "/s/bad.jpg": ("", "", "error: file rejected by host"),
        },
    )
    assert [Path(p).name.endswith("_FAILED.txt") for p in app.current_output_files] == [True]

    assert UploaderApp._delete_files(app, ["/s/bad.jpg"]) is True

    assert group.is_completed is True
    outputs = [p for p in app.current_output_files if not p.endswith("_FAILED.txt")]
    assert len(outputs) == 1
    assert Path(outputs[0]).read_text(encoding="utf-8") == "http://v/1\nhttp://v/2"
    # The upload is over, so the output is not handed to a finished poster session.
    app.auto_poster.queue_post.assert_not_called()
    assert any("not posted" in message for message, _level in app.activity)


@pytest.mark.unit
def test_removing_a_successful_image_keeps_the_existing_output(tmp_path):
    app = _ui_app(tmp_path)
    app.progress_queue, app.result_queue = queue.Queue(), queue.Queue()
    app.image_refs = set()
    app._clear_highlights = lambda *args: None
    group = _real_group("Set", ["/s/1.jpg", "/s/2.jpg"])
    app.groups = [group]
    for fp in group.files:
        app.file_widgets[fp] = _row(group)
    _upload(
        app,
        list(group.files),
        {
            "/s/1.jpg": ("http://v/1", "http://t/1", "Done"),
            "/s/2.jpg": ("http://v/2", "http://t/2", "Done"),
        },
    )

    UploaderApp._delete_files(app, ["/s/2.jpg"])

    assert len(app.current_output_files) == 1


def _finishing_app(tmp_path, monkeypatch, files, auto_copy=False):
    """Upload in progress; finalization runs inline and after() callbacks are captured."""
    monkeypatch.setattr(
        "modules.ui.Main_Window.runtime.threading.Thread",
        lambda target=None, **kwargs: SimpleNamespace(start=target),
    )
    app = _ui_app(tmp_path)
    app.progress_queue, app.result_queue = queue.Queue(), queue.Queue()
    group = FakeGroup("Batch", list(files))
    group.selected_template = "BBCode"
    app.groups = [group]
    app.file_widgets = {fp: _row(group, "queued") for fp in files}
    app.is_uploading = True
    app.upload_total = len(files)
    app.var_auto_copy = FakeVar(auto_copy)
    app.callbacks = []
    app.after = lambda delay, callback: app.callbacks.append((delay, callback))
    return app, group


def _run_after_zero(app):
    pending = [callback for delay, callback in app.callbacks if delay == 0]
    app.callbacks.clear()
    for callback in pending:
        callback()


@pytest.mark.unit
def test_result_racing_the_progress_drain_is_in_the_completion_summary(tmp_path, monkeypatch):
    app, group = _finishing_app(tmp_path, monkeypatch, ["a.jpg", "b.jpg"], auto_copy=True)
    copied = []
    monkeypatch.setattr(
        "modules.ui.Main_Window.runtime.pyperclip.copy", lambda text: copied.append(text)
    )
    app.result_queue.put(("a.jpg", "http://v/a", "http://t/a"))
    app.progress_queue.put(("status", "a.jpg", "Done"))
    app.update_ui_loop()

    def upload_thread_delivers_last_file():
        # The manager thread runs between the result drain and the progress drain.
        app.result_queue.put(("b.jpg", "http://v/b", "http://t/b"))
        app.progress_queue.put(("status", "b.jpg", "Done"))

    app._process_ui_queue = upload_thread_delivers_last_file
    app.update_ui_loop()
    _run_after_zero(app)

    summary = app._set_completion_summary.call_args.args[0]
    assert group.is_completed is True
    assert summary["generated_count"] == 1
    assert summary["copied_to_clipboard"] is True
    assert copied[-1] == "http://v/a\nhttp://v/b"


@pytest.mark.unit
def test_done_without_a_link_fails_the_row(tmp_path, monkeypatch):
    app, group = _finishing_app(tmp_path, monkeypatch, ["a.jpg"])
    app.result_queue.put(("a.jpg", "", ""))
    app.progress_queue.put(("status", "a.jpg", "Done"))

    app.update_ui_loop()

    row = app.file_widgets["a.jpg"]
    assert row["state"] == "failed"
    assert row["error"] == "Host returned no link"
    assert row["status"].text == "Failed"
    assert app.upload_count == 1
    assert ("Failed a.jpg: Host returned no link.", "error") in app.activity
    assert app.current_output_files and app.current_output_files[0].endswith("_FAILED.txt")


@pytest.mark.unit
def test_done_without_any_result_fails_the_row(tmp_path, monkeypatch):
    app, group = _finishing_app(tmp_path, monkeypatch, ["a.jpg"])
    app.progress_queue.put(("status", "a.jpg", "Done"))

    app.update_ui_loop()

    assert app.file_widgets["a.jpg"]["state"] == "failed"
    assert app.file_widgets["a.jpg"]["error"] == "Host returned no link"
