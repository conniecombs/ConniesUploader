# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

import os
from pathlib import Path
import queue
from types import SimpleNamespace
from threading import Lock

import pytest

from modules import config
from modules.ui.main_window import UploaderApp


class FakeLabel:
    def __init__(self):
        self.text = None

    def configure(self, **kwargs):
        self.text = kwargs.get("text", self.text)


class FakeFrame:
    def __init__(self):
        self.mapped = False
        self.options = {}
        self.destroyed = False
        self.pack_args = None
        self.pack_kwargs = {}

    def winfo_ismapped(self):
        return self.mapped

    def winfo_exists(self):
        return not self.destroyed

    def winfo_children(self):
        return []

    def pack(self, *args, **kwargs):
        self.mapped = True
        self.pack_args = args
        self.pack_kwargs = kwargs

    def pack_forget(self):
        self.mapped = False

    def configure(self, **kwargs):
        self.options.update(kwargs)

    def destroy(self):
        self.destroyed = True


class FakeGroup(FakeFrame):
    def __init__(self, title, files=None):
        super().__init__()
        self.title = title
        self.files = list(files or [])
        self.cover_files = []
        self.cover_selection_manual = False

    def add_file(self, filepath):
        if filepath not in self.files:
            self.files.append(filepath)

    def remove_file(self, filepath):
        if filepath in self.files:
            self.files.remove(filepath)
        if filepath in self.cover_files:
            self.cover_files.remove(filepath)

    def is_cover_file(self, filepath):
        return filepath in self.cover_files

    def set_cover_file(self, filepath, is_cover=True, manual=True):
        if filepath not in self.files:
            return False
        changed = False
        if is_cover and filepath not in self.cover_files:
            self.cover_files.append(filepath)
            changed = True
        elif not is_cover and filepath in self.cover_files:
            self.cover_files.remove(filepath)
            changed = True
        if manual:
            self.cover_selection_manual = True
        return changed

    def auto_select_covers(self, count):
        if self.cover_selection_manual:
            return
        self.cover_files = self.files[: int(count)]

    def cover_filepaths(self):
        cover_set = set(self.cover_files)
        return [filepath for filepath in self.files if filepath in cover_set]


class FakeBridge:
    def __init__(self, alive=True, starts=False):
        self.alive = alive
        self.starts = starts

    def is_process_alive(self):
        return self.alive

    def _start_process(self):
        self.alive = self.starts
        return self.starts


class FakePlugin:
    def __init__(self, plugin_id, name, metadata):
        self.id = plugin_id
        self.name = name
        self.metadata = metadata


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeProgress:
    def __init__(self):
        self.value = None
        self.options = {}

    def set(self, value):
        self.value = value

    def configure(self, **kwargs):
        self.options.update(kwargs)


@pytest.mark.unit
def test_main_window_has_visible_add_queue_buttons():
    source = Path("modules/ui/main_window.py").read_text(encoding="utf-8")

    assert "self.btn_add_files = ctk.CTkButton" in source
    assert "text=\"Add Files\", command=self.add_files" in source
    assert "self.btn_add_folder = ctk.CTkButton" in source
    assert "text=\"Add Folder\", command=self.add_folder" in source


@pytest.mark.unit
def test_preview_data_uses_storage_thumbnail_value_for_readable_service_label():
    class FakeSettingsView:
        def get_raw_config(self, service_id):
            return {"thumbnail_size": "Medium (320 px)"}

        def normalize_value(self, service_id, key, value):
            assert service_id == "imgur.com"
            assert key == "thumbnail_size"
            assert value == "Medium (320 px)"
            return "m"

    app = UploaderApp.__new__(UploaderApp)
    app.groups = [FakeGroup("Batch", ["image.jpg"])]
    app.var_service = FakeVar("imgur.com")
    app.settings_view = FakeSettingsView()

    files, title, size, cover_count = UploaderApp.get_preview_data(app)

    assert files == ["image.jpg"]
    assert title == "Batch"
    assert size == "m"
    assert cover_count == 0


@pytest.mark.unit
def test_queue_rows_have_visible_remove_button_and_readable_fallbacks():
    source = Path("modules/ui/main_window.py").read_text(encoding="utf-8")

    assert "preview_requested=True" in source
    assert "preview_requested=preview_requested" in source
    assert "elif preview_requested:" in source
    assert 'text="No preview"' in source
    assert 'text="Waiting"' in source
    assert 'text="Set Cover"' in source
    assert 'text="Remove"' in source
    assert 'text="Retry"' in source
    assert '"remove": btn_remove' in source
    assert '"cover": btn_cover' in source
    assert '"retry": btn_retry' in source
    assert '"error_label": error_label' in source
    assert '"actions": row_actions' in source
    assert '"retry_slot": retry_slot' in source
    assert 'text="::"' in source
    assert '"drag_handle": drag_handle' in source


@pytest.mark.unit
def test_queue_rows_use_stable_action_lane_and_wrapping_text():
    source = Path("modules/ui/main_window.py").read_text(encoding="utf-8")

    assert "row_actions = ctk.CTkFrame(row, fg_color=\"transparent\", width=330, height=30)" in source
    assert "row_actions.pack_propagate(False)" in source
    assert "retry_slot = ctk.CTkFrame(row_actions, fg_color=\"transparent\", width=64, height=30)" in source
    assert "retry_slot.pack_propagate(False)" in source
    assert "def update_text_wrap(event):" in source
    assert "filename_label.configure(wraplength=wraplength)" in source
    assert "error_label.configure(wraplength=wraplength)" in source


@pytest.mark.unit
def test_worker_count_is_in_global_advanced_section():
    source = Path("modules/ui/main_window.py").read_text(encoding="utf-8")

    assert "def _create_global_advanced_section" in source
    assert "text=\"Advanced App Settings +\"" in source
    assert "text=\"Worker Count:\"" in source
    assert "text=\"Thread Limit:\"" in source
    assert "thread_limit_entry = ctk.CTkEntry" in source
    assert "set_global_threads(self.menu_thread_var.get())" in source
    assert 'upload_cfg["global_thread_limit"] = 1' in source
    assert 'cfg["imagebam_threads"] = 1' not in source
    assert "add_cascade(label=\"Set Thread Limit\"" not in source
    assert "self._create_global_advanced_section(out_frame)" in source


@pytest.mark.unit
def test_global_thread_limit_is_bounded_without_rewriting_service_thread_vars():
    app = UploaderApp.__new__(UploaderApp)
    app.menu_thread_var = FakeVar(config.DEFAULT_THREAD_COUNT)
    app._last_global_thread_limit_value = config.DEFAULT_THREAD_COUNT
    for _, var_name, default in UploaderApp._service_thread_var_specs():
        setattr(app, var_name, FakeVar(default))

    UploaderApp.set_global_threads(app, 99)

    assert app.menu_thread_var.get() == config.MAX_THREAD_COUNT
    assert app._last_global_thread_limit_value == config.MAX_THREAD_COUNT
    for _, var_name, default in UploaderApp._service_thread_var_specs():
        assert getattr(app, var_name).get() == default

    UploaderApp.set_global_threads(app, 0)

    assert app.menu_thread_var.get() == config.MIN_THREAD_COUNT
    for _, var_name, default in UploaderApp._service_thread_var_specs():
        assert getattr(app, var_name).get() == default


@pytest.mark.unit
def test_gather_settings_clamps_worker_and_changed_global_thread_limit():
    app = UploaderApp.__new__(UploaderApp)
    app.var_service = FakeVar("imx.to")
    app.var_global_worker_count = FakeVar(99)
    app.menu_thread_var = FakeVar(99)
    app._last_global_thread_limit_value = config.DEFAULT_THREAD_COUNT
    for _, var_name, default in UploaderApp._service_thread_var_specs():
        setattr(app, var_name, FakeVar(default))
    app.settings = {}
    app.var_auto_copy = FakeVar(False)
    app.var_confirm_before_posting = FakeVar(True)
    app.var_auto_gallery = FakeVar(False)
    app.var_show_previews = FakeVar(True)
    app.var_separate_batches = FakeVar(False)
    app.var_appearance_mode = FakeVar("System")

    gathered = UploaderApp._gather_settings(app)

    assert gathered["global_worker_count"] == config.MAX_WORKER_COUNT
    assert gathered["global_thread_limit"] == config.MAX_THREAD_COUNT
    assert gathered["confirm_before_posting"] is True
    assert app.var_global_worker_count.get() == config.MAX_WORKER_COUNT
    for thread_key, var_name, default in UploaderApp._service_thread_var_specs():
        assert gathered[thread_key] == default
        assert getattr(app, var_name).get() == default


@pytest.mark.unit
def test_template_recovery_actions_are_available_from_main_window():
    source = Path("modules/ui/main_window.py").read_text(encoding="utf-8")

    assert "Reset Templates to Defaults" in source
    assert "def _show_template_recovery_notice" in source
    assert 'text="Open Broken File"' in source
    assert 'text="Restore Defaults"' in source
    assert "get_recovery_issue" in source


@pytest.mark.unit
def test_host_readiness_reports_account_free_host_ready():
    app = UploaderApp.__new__(UploaderApp)
    app.creds = {}
    app.var_auto_gallery = FakeVar(False)
    app.service_plugins = {
        "pixhost.to": FakePlugin(
            "pixhost.to",
            "Pixhost.to",
            {
                "features": {"authentication": "none"},
                "credentials": [],
            },
        )
    }

    readiness = UploaderApp._host_readiness_for(app, "pixhost.to")

    assert readiness["level"] == "ready"
    assert readiness["message"] == "Pixhost.to ready - no account required."
    assert readiness["action_required"] is False


@pytest.mark.unit
def test_host_readiness_reports_missing_required_credentials():
    app = UploaderApp.__new__(UploaderApp)
    app.creds = {}
    app.var_auto_gallery = FakeVar(False)
    app.service_plugins = {
        "imx.to": FakePlugin(
            "imx.to",
            "IMX.to",
            {
                "features": {"authentication": "required"},
                "credentials": [
                    {"key": "imx_api", "label": "API Key", "required": True},
                ],
            },
        )
    }

    readiness = UploaderApp._host_readiness_for(app, "imx.to")

    assert readiness["level"] == "error"
    assert readiness["message"] == "IMX.to needs API Key before upload."
    assert readiness["action_required"] is True


@pytest.mark.unit
def test_host_readiness_reports_imgur_api_requirement():
    app = UploaderApp.__new__(UploaderApp)
    app.creds = {"imgur_client_id": "", "imgur_access_token": ""}
    app.var_auto_gallery = FakeVar(False)
    app.service_plugins = {
        "imgur.com": FakePlugin(
            "imgur.com",
            "Imgur",
            {
                "features": {"authentication": "optional"},
                "credentials": [
                    {"key": "imgur_client_id", "label": "Client ID", "required": False},
                    {
                        "key": "imgur_access_token",
                        "label": "Access Token",
                        "required": False,
                    },
                ],
            },
        )
    }

    readiness = UploaderApp._host_readiness_for(app, "imgur.com")

    assert readiness["level"] == "error"
    assert readiness["message"] == "Imgur needs a Client ID or Access Token before upload."
    assert readiness["action_required"] is True


@pytest.mark.unit
def test_host_readiness_reports_imx_auto_gallery_login_requirement():
    app = UploaderApp.__new__(UploaderApp)
    app.creds = {"imx_api": "api-key", "imx_user": "", "imx_pass": ""}
    app.var_auto_gallery = FakeVar(True)
    app.service_plugins = {
        "imx.to": FakePlugin(
            "imx.to",
            "IMX.to",
            {
                "features": {"authentication": "required"},
                "credentials": [
                    {"key": "imx_api", "label": "API Key", "required": True},
                    {"key": "imx_user", "label": "Username", "required": False},
                    {"key": "imx_pass", "label": "Password", "required": False},
                ],
            },
        )
    }

    readiness = UploaderApp._host_readiness_for(app, "imx.to")

    assert readiness["level"] == "error"
    assert readiness["message"] == "IMX.to needs username and password for One Gallery Per Folder."
    assert readiness["action_required"] is True


@pytest.mark.unit
def test_host_readiness_credentials_button_uses_full_width_layout():
    app = UploaderApp.__new__(UploaderApp)
    app.var_service = FakeVar("imgur.com")
    app.lbl_host_readiness = FakeFrame()
    app.btn_host_credentials = FakeFrame()
    app._host_readiness_for = lambda service_id: {
        "level": "error",
        "message": "Imgur needs a Client ID or Access Token before upload.",
        "action_required": True,
    }
    app._refresh_start_button_state = lambda readiness=None: None

    UploaderApp._refresh_host_readiness(app)

    assert app.lbl_host_readiness.options["text"] == (
        "Imgur needs a Client ID or Access Token before upload."
    )
    assert app.btn_host_credentials.mapped is True
    assert app.btn_host_credentials.pack_kwargs["fill"] == "x"
    assert "side" not in app.btn_host_credentials.pack_kwargs


@pytest.mark.unit
def test_start_button_disabled_until_pending_files_exist():
    app = UploaderApp.__new__(UploaderApp)
    app.lock = Lock()
    app.file_widgets = {}
    app.is_uploading = False
    app.btn_start = FakeFrame()

    UploaderApp._refresh_start_button_state(app)

    assert app.btn_start.options["text"] == "Start Upload"
    assert app.btn_start.options["state"] == "disabled"
    assert app.btn_start.options["fg_color"] == "#5A5A5A"


@pytest.mark.unit
def test_start_button_enabled_with_pending_files_and_ready_host():
    app = UploaderApp.__new__(UploaderApp)
    app.lock = Lock()
    app.file_widgets = {
        "one.jpg": {"state": "pending"},
        "two.jpg": {"state": "pending"},
        "done.jpg": {"state": "success"},
    }
    app.is_uploading = False
    app.btn_start = FakeFrame()
    app.creds = {}
    app.var_auto_gallery = FakeVar(False)
    app.var_service = FakeVar("pixhost.to")
    app.service_plugins = {
        "pixhost.to": FakePlugin(
            "pixhost.to",
            "Pixhost.to",
            {
                "features": {"authentication": "none"},
                "credentials": [],
            },
        )
    }

    UploaderApp._refresh_start_button_state(app)

    assert app.btn_start.options["text"] == "Start Upload (2)"
    assert app.btn_start.options["state"] == "normal"
    assert app.btn_start.options["fg_color"] == "#1F6AA5"


@pytest.mark.unit
def test_start_button_disabled_when_host_needs_attention():
    app = UploaderApp.__new__(UploaderApp)
    app.lock = Lock()
    app.file_widgets = {"one.jpg": {"state": "pending"}}
    app.is_uploading = False
    app.btn_start = FakeFrame()
    app.creds = {}
    app.var_auto_gallery = FakeVar(False)
    app.var_service = FakeVar("imx.to")
    app.service_plugins = {
        "imx.to": FakePlugin(
            "imx.to",
            "IMX.to",
            {
                "features": {"authentication": "required"},
                "credentials": [
                    {"key": "imx_api", "label": "API Key", "required": True},
                ],
            },
        )
    }

    UploaderApp._refresh_start_button_state(app)

    assert app.btn_start.options["text"] == "Fix Host Settings"
    assert app.btn_start.options["state"] == "disabled"
    assert app.btn_start.options["fg_color"] == "#5A5A5A"


@pytest.mark.unit
def test_start_button_disabled_while_uploading():
    app = UploaderApp.__new__(UploaderApp)
    app.lock = Lock()
    app.file_widgets = {"one.jpg": {"state": "pending"}}
    app.is_uploading = True
    app.btn_start = FakeFrame()
    app.btn_stop = FakeFrame()

    UploaderApp._refresh_start_button_state(app)

    assert app.btn_start.options["text"] == "Uploading..."
    assert app.btn_start.options["state"] == "disabled"
    assert app.btn_start.options["fg_color"] == "#5A5A5A"
    assert app.btn_stop.options["state"] == "normal"
    assert app.btn_stop.options["fg_color"] == "#FF3B30"


@pytest.mark.unit
def test_stop_button_is_gray_when_upload_is_inactive():
    app = UploaderApp.__new__(UploaderApp)
    app.btn_stop = FakeFrame()

    UploaderApp._configure_stop_button(app, False)

    assert app.btn_stop.options["state"] == "disabled"
    assert app.btn_stop.options["fg_color"] == "#5A5A5A"


@pytest.mark.unit
def test_start_upload_without_pending_files_uses_inline_feedback(monkeypatch):
    from modules.ui import main_window

    app = UploaderApp.__new__(UploaderApp)
    app.groups = []
    app.lock = Lock()
    app.lbl_eta = FakeLabel()
    checks = []
    activity = []
    refreshed = []
    app._set_upload_checks = lambda issues: checks.append(list(issues))
    app.add_activity = lambda message, level="info": activity.append((message, level))
    app._refresh_start_button_state = lambda: refreshed.append(True)

    def fail_showinfo(*_args, **_kwargs):
        raise AssertionError("No pending upload feedback should stay inline.")

    monkeypatch.setattr(main_window.messagebox, "showinfo", fail_showinfo)

    UploaderApp.start_upload(app)

    expected = "No pending files to upload. Add files or retry failed items."
    assert checks == [[]]
    assert app.lbl_eta.text == expected
    assert activity == [(expected, "warning")]
    assert refreshed == [True]


@pytest.mark.unit
def test_open_output_folder_without_files_uses_inline_feedback(monkeypatch):
    from modules.ui import main_window

    app = UploaderApp.__new__(UploaderApp)
    app.current_output_files = []
    app.lbl_eta = FakeLabel()
    activity = []
    app.add_activity = lambda message, level="info": activity.append((message, level))

    def fail_showinfo(*_args, **_kwargs):
        raise AssertionError("No-output feedback should stay inline.")

    monkeypatch.setattr(main_window.messagebox, "showinfo", fail_showinfo)

    UploaderApp.open_output_folder(app)

    expected = "No output files have been generated yet."
    assert app.lbl_eta.text == expected
    assert activity == [(expected, "warning")]


@pytest.mark.unit
def test_process_files_without_valid_images_uses_inline_import_checks(tmp_path, monkeypatch):
    from modules.ui import main_window

    bad_file = tmp_path / "notes.txt"
    bad_file.write_text("not an image", encoding="utf-8")

    app = UploaderApp.__new__(UploaderApp)
    app.lbl_eta = FakeLabel()
    app.var_show_previews = FakeVar(True)
    app.update_idletasks = lambda: None
    app._set_completion_summary = lambda summary: None
    import_checks = []
    activity = []
    app._set_import_checks = lambda issues: import_checks.append(list(issues))
    app.add_activity = lambda message, level="info": activity.append((message, level))

    def fail_showwarning(*_args, **_kwargs):
        raise AssertionError("Invalid import feedback should stay inline.")

    monkeypatch.setattr(main_window.messagebox, "showwarning", fail_showwarning)

    UploaderApp._process_files(app, [str(bad_file)])

    assert app.lbl_eta.text == "No valid image files found."
    assert import_checks[0] == []
    assert import_checks[-1][0].startswith("No valid image files found. Supported formats:")
    assert import_checks[-1][1] == "Rejected files: 1"
    assert import_checks[-1][2] == "notes.txt: unsupported extension .txt"
    assert activity[-1] == (
        "No valid image files found. Check Import Checks for details.",
        "warning",
    )


@pytest.mark.unit
def test_import_checks_panel_has_inline_retry_actions():
    source = Path("modules/ui/main_window.py").read_text(encoding="utf-8")

    assert "def _create_import_checks_panel" in source
    assert "text=\"Import Checks\"" in source
    assert "command=lambda: self._set_import_checks([])" in source
    assert "text=\"Add Files\"" in source
    assert "text=\"Add Folder\"" in source


@pytest.mark.unit
def test_refresh_queue_state_updates_summary_and_empty_state():
    app = UploaderApp.__new__(UploaderApp)
    app.lock = Lock()
    app.file_widgets = {}
    app.groups = []
    app.lbl_file_summary = FakeLabel()
    app.empty_queue_frame = FakeFrame()
    app.queue_actions = FakeFrame()

    UploaderApp._refresh_queue_state(app)

    assert app.lbl_file_summary.text == "No files added"
    assert app.empty_queue_frame.mapped is True
    assert app.queue_actions.mapped is False

    app.file_widgets = {"one.jpg": {}, "two.jpg": {}}
    app.groups = [object()]

    UploaderApp._refresh_queue_state(app)

    assert app.lbl_file_summary.text == "2 files in 1 batch"
    assert app.empty_queue_frame.mapped is False
    assert app.queue_actions.mapped is True


@pytest.mark.unit
def test_activity_panel_toggle_hides_and_restores_feed():
    app = UploaderApp.__new__(UploaderApp)
    app.activity_visible = True
    app.activity_frame = FakeFrame()
    app.activity_frame.mapped = True
    app.btn_activity_toggle = FakeFrame()

    UploaderApp.toggle_activity_panel(app)

    assert app.activity_visible is False
    assert app.activity_frame.mapped is False
    assert app.btn_activity_toggle.options["text"] == "Show"

    UploaderApp.toggle_activity_panel(app)

    assert app.activity_visible is True
    assert app.activity_frame.mapped is True
    assert app.btn_activity_toggle.options["text"] == "Hide"


@pytest.mark.unit
def test_deleting_last_image_removes_empty_batch():
    row = FakeFrame()
    image_ref = object()
    group = FakeGroup("Batch 1", ["only.jpg"])
    refreshed = []
    activity = []

    app = UploaderApp.__new__(UploaderApp)
    app.lock = Lock()
    app.groups = [group]
    app.file_widgets = {
        "only.jpg": {
            "row": row,
            "group": group,
            "image_ref": image_ref,
        }
    }
    app.image_refs = {image_ref}
    app.highlighted_row = None
    app._refresh_queue_state = lambda: refreshed.append(True)
    app.add_activity = lambda message, level="info": activity.append((message, level))

    UploaderApp._delete_file(app, "only.jpg")

    assert app.file_widgets == {}
    assert image_ref not in app.image_refs
    assert group.files == []
    assert group not in app.groups
    assert group.destroyed is True
    assert row.destroyed is True
    assert refreshed
    assert ("Removed empty batch: Batch 1.", "warning") in activity


@pytest.mark.unit
def test_moving_last_image_removes_old_batch():
    old_row = FakeFrame()
    new_row = FakeFrame()
    old_group = FakeGroup("Old Batch", ["move.jpg"])
    new_group = FakeGroup("New Batch", [])
    refreshed = []
    activity = []

    app = UploaderApp.__new__(UploaderApp)
    app.lock = Lock()
    app.groups = [old_group, new_group]
    app.file_widgets = {"move.jpg": {"row": old_row, "group": old_group, "state": "pending"}}
    app.var_show_previews = FakeVar(False)
    app._refresh_queue_state = lambda: refreshed.append(True)
    app.add_activity = lambda message, level="info": activity.append((message, level))

    def fake_create_row(fp, pil_image, group_widget, preview_requested=True):
        app.file_widgets[fp] = {
            "row": new_row,
            "group": group_widget,
            "state": "pending",
        }

    app._create_row = fake_create_row

    UploaderApp._move_file_to_group(app, "move.jpg", old_group, new_group)

    assert old_group.files == []
    assert old_group not in app.groups
    assert old_group.destroyed is True
    assert old_row.destroyed is True
    assert new_group.files == ["move.jpg"]
    assert app.file_widgets["move.jpg"]["row"] is new_row
    assert refreshed
    assert ("Removed empty batch: Old Batch.", "warning") in activity


@pytest.mark.unit
def test_move_file_relative_updates_upload_order_and_repacks_rows():
    group = FakeGroup("Batch", ["one.jpg", "two.jpg", "three.jpg"])
    rows = {filepath: FakeFrame() for filepath in group.files}
    refreshed = []
    activity = []

    app = UploaderApp.__new__(UploaderApp)
    app.lock = Lock()
    app.is_uploading = False
    app.file_widgets = {
        filepath: {"row": rows[filepath], "group": group} for filepath in group.files
    }
    app._refresh_queue_state = lambda: refreshed.append(True)
    app.add_activity = lambda message, level="info": activity.append((message, level))

    moved = UploaderApp._move_file_relative(app, "three.jpg", "top")

    assert moved is True
    assert group.files == ["three.jpg", "one.jpg", "two.jpg"]
    assert all(row.mapped for row in rows.values())
    assert refreshed
    assert activity[-1] == ("Moved image: three.jpg.", "info")


@pytest.mark.unit
def test_row_selection_supports_ctrl_shift_and_persists_after_release():
    group = FakeGroup("Batch", ["one.jpg", "two.jpg", "three.jpg", "four.jpg"])
    rows = {filepath: FakeFrame() for filepath in group.files}

    app = UploaderApp.__new__(UploaderApp)
    app.lock = Lock()
    app.groups = [group]
    app.is_uploading = False
    app.file_widgets = {
        filepath: {"row": rows[filepath], "group": group} for filepath in group.files
    }
    app.selected_files = set()
    app.selection_anchor = None
    app.drag_data = {"item": None, "type": None, "widget_start": None}
    app.configure = lambda **_kwargs: None
    app.winfo_containing = lambda *_args: None

    def event(state=0):
        return SimpleNamespace(state=state, x_root=0, y_root=0)

    UploaderApp._on_row_drag_start(app, event(), rows["one.jpg"], "one.jpg")
    UploaderApp._on_row_drag_end(app, event())
    assert app.selected_files == {"one.jpg"}

    UploaderApp._on_row_drag_start(app, event(0x0004), rows["three.jpg"], "three.jpg")
    UploaderApp._on_row_drag_end(app, event(0x0004))
    assert app.selected_files == {"one.jpg", "three.jpg"}

    UploaderApp._on_row_drag_start(app, event(0x0004), rows["one.jpg"], "one.jpg")
    UploaderApp._on_row_drag_end(app, event(0x0004))
    assert app.selected_files == {"three.jpg"}

    UploaderApp._on_row_drag_start(app, event(), rows["one.jpg"], "one.jpg")
    UploaderApp._on_row_drag_end(app, event())
    UploaderApp._on_row_drag_start(app, event(0x0001), rows["three.jpg"], "three.jpg")
    UploaderApp._on_row_drag_end(app, event(0x0001))

    assert app.selected_files == {"one.jpg", "two.jpg", "three.jpg"}
    assert app.selection_anchor == "one.jpg"
    assert rows["one.jpg"].options["fg_color"] != "transparent"
    assert rows["three.jpg"].options["fg_color"] != "transparent"


@pytest.mark.unit
def test_selected_files_move_as_one_ordered_block():
    group = FakeGroup("Batch", ["one.jpg", "two.jpg", "three.jpg", "four.jpg"])
    rows = {filepath: FakeFrame() for filepath in group.files}
    refreshed = []
    activity = []

    app = UploaderApp.__new__(UploaderApp)
    app.lock = Lock()
    app.groups = [group]
    app.is_uploading = False
    app.file_widgets = {
        filepath: {"row": rows[filepath], "group": group} for filepath in group.files
    }
    app.selected_files = {"two.jpg", "three.jpg"}
    app.selection_anchor = "two.jpg"
    app._refresh_queue_state = lambda: refreshed.append(True)
    app.add_activity = lambda message, level="info": activity.append((message, level))

    moved = UploaderApp._move_file_relative(app, "two.jpg", "bottom")

    assert moved is True
    assert group.files == ["one.jpg", "four.jpg", "two.jpg", "three.jpg"]
    assert app.selected_files == {"two.jpg", "three.jpg"}
    assert all(row.mapped for row in rows.values())
    assert refreshed
    assert activity[-1] == ("Moved 2 images.", "info")


@pytest.mark.unit
def test_sort_group_files_updates_upload_order_by_name_modified_and_reverse(tmp_path):
    img10 = tmp_path / "img10.jpg"
    img2 = tmp_path / "img2.jpg"
    img1 = tmp_path / "img1.jpg"
    for path in (img10, img2, img1):
        path.write_bytes(b"image")
    os.utime(img10, (1000, 1000))
    os.utime(img2, (2000, 2000))
    os.utime(img1, (3000, 3000))

    group = FakeGroup("Batch", [str(img10), str(img2), str(img1)])
    rows = {filepath: FakeFrame() for filepath in group.files}
    refreshed = []
    activity = []

    app = UploaderApp.__new__(UploaderApp)
    app.lock = Lock()
    app.is_uploading = False
    app.file_widgets = {
        filepath: {"row": rows[filepath], "group": group} for filepath in group.files
    }
    app._refresh_queue_state = lambda: refreshed.append(True)
    app.add_activity = lambda message, level="info": activity.append((message, level))

    assert UploaderApp._sort_group_files(app, group, "name") is True
    assert [Path(filepath).name for filepath in group.files] == [
        "img1.jpg",
        "img2.jpg",
        "img10.jpg",
    ]

    assert UploaderApp._sort_group_files(app, group, "modified") is True
    assert [Path(filepath).name for filepath in group.files] == [
        "img10.jpg",
        "img2.jpg",
        "img1.jpg",
    ]

    assert UploaderApp._sort_group_files(app, group, "reverse") is True
    assert [Path(filepath).name for filepath in group.files] == [
        "img1.jpg",
        "img2.jpg",
        "img10.jpg",
    ]
    assert len(refreshed) == 3
    assert activity[-1] == ("Reversed batch order: Batch.", "info")


@pytest.mark.unit
def test_auto_cover_count_marks_first_images_until_user_changes_selection():
    group = FakeGroup("Batch", ["one.jpg", "two.jpg", "three.jpg"])
    buttons = {filepath: FakeFrame() for filepath in group.files}

    app = UploaderApp.__new__(UploaderApp)
    app.lock = Lock()
    app.file_widgets = {
        filepath: {"group": group, "cover": buttons[filepath]} for filepath in group.files
    }
    app.var_service = FakeVar("pixhost.to")
    app.var_pix_cover_count = FakeVar("2")

    UploaderApp._apply_auto_covers_to_group(app, group)

    assert group.cover_filepaths() == ["one.jpg", "two.jpg"]
    assert buttons["one.jpg"].options["text"] == "Cover"
    assert buttons["three.jpg"].options["text"] == "Set Cover"

    group.set_cover_file("three.jpg", True, manual=True)
    app.var_pix_cover_count.set("1")
    UploaderApp._apply_auto_covers_to_group(app, group)

    assert group.cover_filepaths() == ["one.jpg", "two.jpg", "three.jpg"]


@pytest.mark.unit
def test_selected_cover_files_are_ordered_first_for_preview_output():
    group = FakeGroup("Batch", ["one.jpg", "two.jpg", "three.jpg"])
    group.set_cover_file("three.jpg", True, manual=True)

    app = UploaderApp.__new__(UploaderApp)

    preview = UploaderApp._preview_group_results(app, group)

    assert preview[0][0] == "https://preview.invalid/three/viewer"


@pytest.mark.unit
def test_upload_preflight_reports_ready_summary(tmp_path):
    image_path = tmp_path / "ready.jpg"
    image_path.write_bytes(b"fake image")

    app = UploaderApp.__new__(UploaderApp)
    app.creds = {}
    app.output_dir = str(tmp_path / "Output")
    app.central_history_path = str(tmp_path / "history")
    app.upload_manager = SimpleNamespace(bridge=FakeBridge(alive=True))
    app.service_plugins = {
        "pixhost.to": FakePlugin(
            "pixhost.to",
            "Pixhost",
            {
                "implementation": "go",
                "credentials": [],
                "limits": {
                    "allowed_formats": [".jpg"],
                    "max_file_size": 1024,
                },
            },
        )
    }

    issues, summary = UploaderApp._run_upload_preflight(
        app,
        {object(): [str(image_path)]},
        {"service": "pixhost.to", "auto_copy": True},
    )

    assert issues == []
    assert summary == "Pixhost ready - 1 file in 1 batch. Output will copy to clipboard."


@pytest.mark.unit
def test_upload_preflight_reports_specific_blockers(tmp_path):
    image_path = tmp_path / "unsupported.bmp"
    image_path.write_bytes(b"fake image")

    app = UploaderApp.__new__(UploaderApp)
    app.creds = {}
    app.output_dir = str(tmp_path / "Output")
    app.central_history_path = str(tmp_path / "history")
    app.upload_manager = SimpleNamespace(bridge=FakeBridge(alive=False, starts=False))
    app.service_plugins = {
        "imx.to": FakePlugin(
            "imx.to",
            "IMX.to",
            {
                "implementation": "go",
                "credentials": [
                    {"key": "imx_api", "label": "API Key", "required": True},
                ],
                "limits": {
                    "allowed_formats": [".jpg", ".png"],
                    "max_file_size": 1024,
                },
            },
        )
    }

    issues, summary = UploaderApp._run_upload_preflight(
        app,
        {object(): [str(image_path)]},
        {"service": "imx.to", "auto_gallery": True},
    )

    assert summary == ""
    assert "IMX.to requires API Key. Set it in Tools > Set Credentials." in issues
    assert "One Gallery Per Folder for IMX.to requires IMX username and password." in issues
    assert "Some queued files are not ready:" in issues
    assert any("unsupported.bmp: not supported by IMX.to" in issue for issue in issues)
    assert (
        "Upload engine is not running. Run build_uploader.bat to rebuild the bundled sidecar."
        in issues
    )
    assert app.preflight_action_files == [str(image_path)]
    assert "Some queued files are not ready:" in app.preflight_action_file_issue_texts


@pytest.mark.unit
def test_upload_preflight_reports_vipergirls_posting_blockers(tmp_path, monkeypatch):
    image_path = tmp_path / "ready.jpg"
    image_path.write_bytes(b"fake image")

    missing_group = FakeGroup("Missing Batch", [str(image_path)])
    missing_group.selected_thread = "Deleted Target"
    invalid_group = FakeGroup("Invalid Batch", [str(image_path)])
    invalid_group.selected_thread = "Bad Target"
    ignored_group = FakeGroup("No Post Batch", [str(image_path)])
    ignored_group.selected_thread = "Do Not Post"

    app = UploaderApp.__new__(UploaderApp)
    app.creds = {}
    app.output_dir = str(tmp_path / "Output")
    app.central_history_path = str(tmp_path / "history")
    app.upload_manager = SimpleNamespace(bridge=FakeBridge(alive=True))
    app.service_plugins = {
        "pixhost.to": FakePlugin(
            "pixhost.to",
            "Pixhost",
            {
                "implementation": "go",
                "credentials": [],
                "limits": {
                    "allowed_formats": [".jpg"],
                    "max_file_size": 1024,
                },
            },
        )
    }
    monkeypatch.setattr(
        "modules.ui.main_window.viper_api.load_saved_threads",
        lambda: {
            "Bad Target": {
                "url": "https://vipergirls.to/not-a-thread",
                "thread_id": "",
            }
        },
    )

    issues, summary = UploaderApp._run_upload_preflight(
        app,
        {
            missing_group: [str(image_path)],
            invalid_group: [str(image_path)],
            ignored_group: [str(image_path)],
        },
        {"service": "pixhost.to"},
    )

    assert summary == ""
    assert (
        "ViperGirls posting needs username and password. "
        "Set them in Tools > Set Credentials."
    ) in issues
    assert (
        'ViperGirls target "Deleted Target" selected for "Missing Batch" no longer exists.'
        in issues
    )
    assert (
        'ViperGirls target "Bad Target" selected for "Invalid Batch" has no usable thread ID.'
        in issues
    )
    assert app.preflight_action_viper_targets is True


@pytest.mark.unit
def test_upload_preflight_accepts_valid_vipergirls_posting_target(tmp_path, monkeypatch):
    image_path = tmp_path / "ready.jpg"
    image_path.write_bytes(b"fake image")

    group = FakeGroup("Ready Batch", [str(image_path)])
    group.selected_thread = "Ready Target"

    app = UploaderApp.__new__(UploaderApp)
    app.creds = {"vg_user": "user", "vg_pass": "password"}
    app.output_dir = str(tmp_path / "Output")
    app.central_history_path = str(tmp_path / "history")
    app.upload_manager = SimpleNamespace(bridge=FakeBridge(alive=True))
    app.service_plugins = {
        "pixhost.to": FakePlugin(
            "pixhost.to",
            "Pixhost",
            {
                "implementation": "go",
                "credentials": [],
                "limits": {
                    "allowed_formats": [".jpg"],
                    "max_file_size": 1024,
                },
            },
        )
    }
    monkeypatch.setattr(
        "modules.ui.main_window.viper_api.load_saved_threads",
        lambda: {
            "Ready Target": {
                "url": "https://vipergirls.to/threads/12345-title",
                "thread_id": "12345",
            }
        },
    )

    issues, summary = UploaderApp._run_upload_preflight(
        app,
        {group: [str(image_path)]},
        {"service": "pixhost.to"},
    )

    assert issues == []
    assert summary.startswith("Pixhost ready - 1 file in 1 batch.")
    assert app.preflight_action_viper_targets is False


@pytest.mark.unit
def test_upload_preflight_records_problem_folder_action(tmp_path):
    image_path = tmp_path / "ready.jpg"
    image_path.write_bytes(b"fake image")
    output_dir = tmp_path / "Output"

    app = UploaderApp.__new__(UploaderApp)
    app.creds = {}
    app.output_dir = str(output_dir)
    app.central_history_path = str(tmp_path / "history")
    app.upload_manager = SimpleNamespace(bridge=FakeBridge(alive=True))
    app.service_plugins = {
        "pixhost.to": FakePlugin(
            "pixhost.to",
            "Pixhost",
            {
                "implementation": "go",
                "credentials": [],
                "limits": {
                    "allowed_formats": [".jpg"],
                    "max_file_size": 1024,
                },
            },
        )
    }

    def fail_output_folder(folder):
        if folder == str(output_dir):
            raise OSError("permission denied")

    app._assert_folder_writable = fail_output_folder

    issues, summary = UploaderApp._run_upload_preflight(
        app,
        {object(): [str(image_path)]},
        {"service": "pixhost.to", "auto_copy": True},
    )

    assert summary == ""
    assert any("Output folder is not writable: permission denied" in issue for issue in issues)
    assert app.preflight_action_folders == [
        {"label": "Output folder", "path": str(output_dir)}
    ]


@pytest.mark.unit
def test_preflight_issue_handler_populates_in_window_checks():
    app = UploaderApp.__new__(UploaderApp)
    app.lbl_eta = FakeLabel()
    shown_checks = []
    activity = []
    refreshed = []
    app._set_upload_checks = lambda issues: shown_checks.append(list(issues))
    app.add_activity = lambda message, level="info": activity.append((message, level))
    app._refresh_start_button_state = lambda: refreshed.append(True)

    UploaderApp._handle_preflight_issues(
        app,
        ["Imgur requires a Client ID or Access Token.", "missing.jpg: file is missing"],
    )

    assert app.lbl_eta.text == "Fix 2 upload issues before uploading."
    assert shown_checks == [["Imgur requires a Client ID or Access Token.", "missing.jpg: file is missing"]]
    assert ("Upload blocked: 2 issues need attention.", "error") in activity
    assert ("Imgur requires a Client ID or Access Token.", "error") in activity
    assert refreshed == [True]


@pytest.mark.unit
def test_preflight_credentials_shortcut_only_for_credential_issues():
    app = UploaderApp.__new__(UploaderApp)

    assert UploaderApp._preflight_issues_need_credentials(
        app, ["Imgur requires a Client ID or Access Token."]
    )
    assert UploaderApp._preflight_issues_need_credentials(
        app, ["IMX.to requires API Key. Set it in Tools > Set Credentials."]
    )
    assert not UploaderApp._preflight_issues_need_credentials(
        app, ["Output folder is not writable: permission denied"]
    )


@pytest.mark.unit
def test_preflight_failures_use_in_window_checks_instead_of_modal():
    source = Path("modules/ui/main_window.py").read_text(encoding="utf-8")

    assert "_handle_preflight_issues(preflight_issues)" in source
    assert "Upload Preflight Failed" not in source


@pytest.mark.unit
def test_upload_checks_offer_action_buttons():
    source = Path("modules/ui/main_window.py").read_text(encoding="utf-8")

    assert "Set Credentials" in source
    assert "Manage ViperGirls Targets" in source
    assert "Remove Invalid Files" in source
    assert "Open Problem Folder" in source
    assert "Try Upload Again" in source


@pytest.mark.unit
def test_batch_header_offers_vipergirls_post_preview_action():
    source = Path("modules/widgets.py").read_text(encoding="utf-8")

    assert "post_preview_callback" in source
    assert 'text="Preview Post"' in source


@pytest.mark.unit
def test_upload_checks_show_only_relevant_actions():
    app = UploaderApp.__new__(UploaderApp)
    app.upload_checks_actions = FakeFrame()
    app.btn_upload_checks_credentials = FakeFrame()
    app.btn_upload_checks_viper_targets = FakeFrame()
    app.btn_upload_checks_remove_files = FakeFrame()
    app.btn_upload_checks_open_folder = FakeFrame()
    app.btn_upload_checks_retry = FakeFrame()
    app.preflight_action_files = []
    app.preflight_action_folders = []
    app.preflight_action_viper_targets = False

    UploaderApp._refresh_upload_check_actions(
        app, ["Output folder is not writable: permission denied"]
    )

    assert app.upload_checks_actions.mapped is True
    assert app.btn_upload_checks_credentials.mapped is False
    assert app.btn_upload_checks_viper_targets.mapped is False
    assert app.btn_upload_checks_remove_files.mapped is False
    assert app.btn_upload_checks_open_folder.mapped is False
    assert app.btn_upload_checks_retry.mapped is True
    assert app.btn_upload_checks_retry.options["state"] == "normal"
    assert app.btn_upload_checks_retry.pack_kwargs["side"] == "right"

    app.preflight_action_files = ["bad.bmp"]
    app.preflight_action_folders = [{"label": "Output folder", "path": "R:\\missing"}]
    app.preflight_action_viper_targets = True

    UploaderApp._refresh_upload_check_actions(
        app, ["Imgur requires a Client ID or Access Token."]
    )

    assert app.btn_upload_checks_credentials.mapped is True
    assert app.btn_upload_checks_credentials.options["state"] == "normal"
    assert app.btn_upload_checks_viper_targets.mapped is True
    assert app.btn_upload_checks_viper_targets.options["state"] == "normal"
    assert app.btn_upload_checks_remove_files.mapped is True
    assert app.btn_upload_checks_open_folder.mapped is True
    assert app.btn_upload_checks_retry.mapped is True

    app.preflight_action_files = []
    app.preflight_action_folders = []
    app.preflight_action_viper_targets = False

    UploaderApp._refresh_upload_check_actions(app, [])

    assert app.upload_checks_actions.mapped is False
    assert app.btn_upload_checks_credentials.mapped is False
    assert app.btn_upload_checks_viper_targets.mapped is False
    assert app.btn_upload_checks_remove_files.mapped is False
    assert app.btn_upload_checks_open_folder.mapped is False
    assert app.btn_upload_checks_retry.mapped is False


@pytest.mark.unit
def test_vipergirls_queue_activity_includes_batch_target_and_thread_id():
    group = FakeGroup("Batch Alpha")
    app = UploaderApp.__new__(UploaderApp)
    app.saved_threads_data = {
        "My Target": {
            "url": "https://vipergirls.to/threads/98765-title",
            "thread_id": "98765",
        }
    }

    message, level = UploaderApp._vipergirls_queue_activity(app, group, "My Target")

    assert message == 'Queued ViperGirls post for "Batch Alpha" to "My Target" (thread 98765).'
    assert level == "info"


@pytest.mark.unit
def test_vipergirls_post_preview_uses_batch_target_thread_and_template_text():
    class FakeTemplateManager:
        def apply(self, template_name, context, group_results):
            assert template_name == "BBCode"
            assert context["gallery_name"] == "Batch Alpha"
            assert context["thumb_size"] == "200"
            assert context["batch_name"] == "Batch Alpha"
            assert context["image_count"] == 1
            assert context["service"] == "pixhost.to"
            assert context["thread_name"] == "My Target"
            assert context["thread_id"] == "98765"
            assert context["upload_date"]
            return (
                f"{context['batch_name']} [{context['thread_id']}] "
                f"{context['image_count']} -> {group_results[0][0]}"
            )

    group = FakeGroup("Batch Alpha", ["R:\\Images\\first image.jpg"])
    group.selected_thread = "My Target"
    group.selected_template = "BBCode"

    app = UploaderApp.__new__(UploaderApp)
    app.settings = {"service": "pixhost.to", "pix_thumb": "200"}
    app.template_mgr = FakeTemplateManager()
    app.saved_threads_data = {
        "My Target": {
            "url": "https://vipergirls.to/threads/98765-title",
            "thread_id": "98765",
        }
    }

    preview = UploaderApp._vipergirls_post_preview_data(app, group)

    assert preview["batch_name"] == "Batch Alpha"
    assert preview["target_name"] == "My Target"
    assert preview["thread_id"] == "98765"
    assert "Batch Alpha [98765] 1 -> https://preview.invalid/first_image/viewer" in preview["content"]
    assert preview["issues"] == []


@pytest.mark.unit
def test_generate_group_output_populates_supported_template_context(tmp_path):
    captured = {}

    class FakeTemplateManager:
        def apply(self, template_name, context, group_results):
            captured["template_name"] = template_name
            captured["context"] = dict(context)
            captured["group_results"] = list(group_results)
            return (
                f"{context['batch_name']}|{context['image_count']}|"
                f"{context['service']}|{context['thread_name']}|{context['thread_id']}"
            )

    file_path = str(tmp_path / "first.jpg")
    group = FakeGroup("Batch Alpha", [file_path])
    group.selected_template = "BBCode"
    group.selected_thread = "My Target"
    group.gallery_id = "G123"
    group.batch_index = 0

    queued = []
    activity = []
    output_dir = tmp_path / "Output"
    history_dir = tmp_path / "history"
    history_dir.mkdir()

    app = UploaderApp.__new__(UploaderApp)
    app.results = [(file_path, "https://img.test/view", "https://img.test/thumb")]
    app.settings = {"service": "pixhost.to", "pix_thumb": "200"}
    app.template_mgr = FakeTemplateManager()
    app.output_dir = str(output_dir)
    app.central_history_path = str(history_dir)
    app.current_output_files = []
    app.clipboard_buffer = []
    app.saved_threads_data = {
        "My Target": {
            "url": "https://vipergirls.to/threads/98765-title",
            "thread_id": "98765",
        }
    }
    app.auto_poster = SimpleNamespace(
        queue_post=lambda *args, **kwargs: queued.append((args, kwargs))
    )
    app.lbl_eta = FakeLabel()
    app.btn_open = FakeFrame()
    app.var_auto_copy = FakeVar(False)
    app.var_imx_links = FakeVar(False)
    app.var_pix_links = FakeVar(False)
    app.var_turbo_links = FakeVar(False)
    app.var_vipr_links = FakeVar(False)
    app.log = lambda _message: None
    app.add_activity = lambda message, level="info": activity.append((message, level))

    UploaderApp.generate_group_output(app, group)

    context = captured["context"]
    assert captured["template_name"] == "BBCode"
    assert captured["group_results"] == [
        ("https://img.test/view", "https://img.test/thumb", "https://img.test/view")
    ]
    assert context["gallery_link"] == "https://pixhost.to/gallery/G123"
    assert context["gallery_name"] == "Batch Alpha"
    assert context["gallery_id"] == "G123"
    assert context["cover_url"] == "https://img.test/thumb"
    assert context["thumb_size"] == "200"
    assert context["batch_name"] == "Batch Alpha"
    assert context["image_count"] == 1
    assert context["service"] == "pixhost.to"
    assert context["thread_name"] == "My Target"
    assert context["thread_id"] == "98765"
    assert context["upload_date"]
    assert len(app.current_output_files) == 1
    assert Path(app.current_output_files[0]).read_text(encoding="utf-8") == (
        "Batch Alpha|1|pixhost.to|My Target|98765"
    )
    assert queued


@pytest.mark.unit
def test_generate_group_output_uses_selected_covers_before_standard_images(tmp_path):
    captured = {}

    class FakeTemplateManager:
        def apply(self, template_name, context, group_results):
            captured["group_results"] = list(group_results)
            captured["context"] = dict(context)
            return "ok"

    first = str(tmp_path / "first.jpg")
    second = str(tmp_path / "second.jpg")
    third = str(tmp_path / "third.jpg")
    group = FakeGroup("Batch", [first, second, third])
    group.selected_template = "BBCode"
    group.selected_thread = "Do Not Post"
    group.gallery_id = ""
    group.set_cover_file(third, True, manual=True)

    output_dir = tmp_path / "Output"
    history_dir = tmp_path / "history"
    history_dir.mkdir()

    app = UploaderApp.__new__(UploaderApp)
    app.results = [
        (first, "https://img.test/first", "https://img.test/t-first"),
        (second, "https://img.test/second", "https://img.test/t-second"),
        (third, "https://img.test/third", "https://img.test/t-third"),
    ]
    app.settings = {"service": "pixhost.to", "pix_thumb": "200"}
    app.template_mgr = FakeTemplateManager()
    app.output_dir = str(output_dir)
    app.central_history_path = str(history_dir)
    app.current_output_files = []
    app.clipboard_buffer = []
    app.saved_threads_data = {}
    app.lbl_eta = FakeLabel()
    app.btn_open = FakeFrame()
    app.var_auto_copy = FakeVar(False)
    app.var_imx_links = FakeVar(False)
    app.var_pix_links = FakeVar(False)
    app.var_turbo_links = FakeVar(False)
    app.var_vipr_links = FakeVar(False)
    app.log = lambda _message: None
    app.add_activity = lambda *args, **kwargs: None

    UploaderApp.generate_group_output(app, group)

    assert captured["group_results"][0] == (
        "https://img.test/third",
        "https://img.test/t-third",
        "https://img.test/third",
    )
    assert captured["context"]["cover_url"] == "https://img.test/t-third"


@pytest.mark.unit
def test_remove_preflight_file_issues_keeps_unrelated_upload_checks():
    row_bad = FakeFrame()
    row_good = FakeFrame()
    group = FakeGroup("Batch", ["bad.bmp", "good.jpg"])
    activity = []

    app = UploaderApp.__new__(UploaderApp)
    app.lock = Lock()
    app.groups = [group]
    app.file_widgets = {
        "bad.bmp": {"row": row_bad, "group": group, "image_ref": None},
        "good.jpg": {"row": row_good, "group": group, "image_ref": None},
    }
    app.image_refs = set()
    app.highlighted_row = None
    app.preflight_issues = [
        "IMX.to requires API Key. Set it in Tools > Set Credentials.",
        "Some queued files are not ready:",
        "bad.bmp: not supported by IMX.to",
    ]
    app.preflight_action_files = ["bad.bmp"]
    app.preflight_action_file_issue_texts = [
        "Some queued files are not ready:",
        "bad.bmp: not supported by IMX.to",
    ]
    app.preflight_action_folders = []
    app.add_activity = lambda message, level="info": activity.append((message, level))
    app._refresh_queue_state = lambda: None

    UploaderApp._remove_preflight_file_issues(app)

    assert "bad.bmp" not in app.file_widgets
    assert group.files == ["good.jpg"]
    assert row_bad.destroyed is True
    assert app.preflight_issues == [
        "IMX.to requires API Key. Set it in Tools > Set Credentials."
    ]
    assert app.preflight_action_files == []
    assert ("Removed 1 invalid file from the queue.", "warning") in activity


@pytest.mark.unit
def test_open_preflight_problem_folder_uses_nearest_existing_parent(tmp_path):
    opened = []
    activity = []

    app = UploaderApp.__new__(UploaderApp)
    app.preflight_action_folders = [
        {"label": "Output folder", "path": str(tmp_path / "missing" / "child")}
    ]
    app._open_path = lambda path: opened.append(path)
    app.add_activity = lambda message, level="info": activity.append((message, level))

    UploaderApp._open_preflight_problem_folder(app)

    assert opened == [str(tmp_path)]
    assert activity == [(f"Opened Output folder: {tmp_path}.", "info")]


@pytest.mark.unit
def test_completion_summary_counts_results_and_outputs(tmp_path):
    output_file = tmp_path / "batch.txt"
    output_file.write_text("generated output", encoding="utf-8")

    app = UploaderApp.__new__(UploaderApp)
    app.lock = Lock()
    app.file_widgets = {
        "one.jpg": {"state": "success"},
        "two.jpg": {"state": "failed"},
    }
    app.current_output_files = [str(output_file)]
    app.clipboard_buffer = []
    app.var_auto_copy = FakeVar(True)

    summary = UploaderApp._build_completion_summary(app)

    assert summary["uploaded_count"] == 1
    assert summary["failed_count"] == 1
    assert summary["generated_count"] == 1
    assert summary["has_copy_text"] is True
    assert summary["status_text"] == "Upload complete: 1 uploaded, 1 failed."


@pytest.mark.unit
def test_copy_completion_output_reads_generated_files(tmp_path, monkeypatch):
    from modules.ui import main_window

    output_file = tmp_path / "batch.txt"
    output_file.write_text("generated output", encoding="utf-8")
    copied = []

    app = UploaderApp.__new__(UploaderApp)
    app.clipboard_buffer = []
    monkeypatch.setattr(main_window.pyperclip, "copy", lambda text: copied.append(text))

    copied_ok = UploaderApp._copy_completion_output_to_clipboard(
        app,
        {"output_files": [str(output_file)]},
    )

    assert copied_ok is True
    assert copied == ["generated output"]


@pytest.mark.unit
def test_completion_summary_renders_inline_with_relevant_actions(tmp_path):
    output_file = tmp_path / "batch.txt"
    output_file.write_text("generated output", encoding="utf-8")

    app = UploaderApp.__new__(UploaderApp)
    app.completion_panel = FakeFrame()
    app.activity_panel = FakeFrame()
    app.lbl_completion_title = FakeFrame()
    app.lbl_completion_status = FakeFrame()
    app.lbl_completion_uploaded = FakeFrame()
    app.lbl_completion_failed = FakeFrame()
    app.lbl_completion_generated = FakeFrame()
    app.lbl_completion_clipboard = FakeFrame()
    app.lbl_completion_files = FakeFrame()
    app.lbl_completion_feedback = FakeFrame()
    app.completion_actions = FakeFrame()
    app.btn_completion_open = FakeFrame()
    app.btn_completion_copy = FakeFrame()
    app.btn_completion_retry = FakeFrame()
    summary = {
        "uploaded_count": 3,
        "failed_count": 1,
        "generated_count": 1,
        "output_files": [str(output_file)],
        "auto_copy_requested": True,
        "copied_to_clipboard": False,
        "has_copy_text": True,
        "status_text": "Upload complete: 3 uploaded, 1 failed.",
    }

    UploaderApp._set_completion_summary(app, summary)

    assert app.current_completion_summary == summary
    assert app.completion_panel.mapped is True
    assert app.completion_panel.pack_kwargs["before"] is app.activity_panel
    assert app.completion_panel.options["border_color"] == "#FFB340"
    assert app.lbl_completion_title.options["text"] == "Upload Finished with Issues"
    assert app.lbl_completion_status.options["text"] == "Upload complete: 3 uploaded, 1 failed."
    assert app.lbl_completion_uploaded.options["text"] == "3"
    assert app.lbl_completion_failed.options["text"] == "1"
    assert app.lbl_completion_generated.options["text"] == "1"
    assert app.lbl_completion_clipboard.options["text"] == "Copy failed"
    assert app.lbl_completion_files.mapped is True
    assert app.lbl_completion_files.options["text"] == "Generated: batch.txt"
    assert app.completion_actions.mapped is True
    assert app.btn_completion_open.mapped is True
    assert app.btn_completion_copy.mapped is True
    assert app.btn_completion_retry.mapped is True

    UploaderApp._set_completion_summary(app, None)

    assert app.completion_panel.mapped is False
    assert app.completion_actions.mapped is False
    assert app.btn_completion_open.mapped is False
    assert app.btn_completion_copy.mapped is False
    assert app.btn_completion_retry.mapped is False


@pytest.mark.unit
def test_completion_summary_success_hides_failed_only_action():
    app = UploaderApp.__new__(UploaderApp)
    app.completion_panel = FakeFrame()
    app.lbl_completion_title = FakeFrame()
    app.lbl_completion_status = FakeFrame()
    app.lbl_completion_uploaded = FakeFrame()
    app.lbl_completion_failed = FakeFrame()
    app.lbl_completion_generated = FakeFrame()
    app.lbl_completion_clipboard = FakeFrame()
    app.lbl_completion_files = FakeFrame()
    app.lbl_completion_feedback = FakeFrame()
    app.completion_actions = FakeFrame()
    app.btn_completion_open = FakeFrame()
    app.btn_completion_copy = FakeFrame()
    app.btn_completion_retry = FakeFrame()

    UploaderApp._set_completion_summary(
        app,
        {
            "uploaded_count": 1,
            "failed_count": 0,
            "generated_count": 0,
            "output_files": [],
            "auto_copy_requested": False,
            "copied_to_clipboard": False,
            "has_copy_text": False,
            "status_text": "Upload complete: 1 file uploaded.",
        },
    )

    assert app.completion_panel.options["border_color"] == "#34C759"
    assert app.lbl_completion_title.options["text"] == "Upload Complete"
    assert app.lbl_completion_clipboard.options["text"] == "Not copied"
    assert app.lbl_completion_files.mapped is False
    assert app.completion_actions.mapped is False
    assert app.btn_completion_retry.mapped is False


@pytest.mark.unit
def test_completion_copy_again_updates_inline_feedback(monkeypatch):
    from modules.ui import main_window

    copied = []
    activity = []
    app = UploaderApp.__new__(UploaderApp)
    app.current_completion_summary = {
        "output_files": [],
        "has_copy_text": True,
        "copied_to_clipboard": False,
    }
    app.clipboard_buffer = ["generated output"]
    app.add_activity = lambda message, level="info": activity.append((message, level))
    rendered = []
    app._set_completion_summary = lambda summary: rendered.append(dict(summary))
    monkeypatch.setattr(main_window.pyperclip, "copy", lambda text: copied.append(text))

    UploaderApp._copy_completion_again(app)

    assert copied == ["generated output"]
    assert activity == [("Copied output to clipboard.", "success")]
    assert rendered[-1]["copied_to_clipboard"] is True
    assert rendered[-1]["feedback"] == "Copied output to clipboard."


@pytest.mark.unit
def test_upload_completion_uses_inline_summary_instead_of_modal():
    source = Path("modules/ui/main_window.py").read_text(encoding="utf-8")
    complete_block = source[source.index("def _on_upload_complete") : source.index("def _build_completion_summary")]

    assert "self._set_completion_summary(summary)" in complete_block
    assert "self._show_completion_summary(summary)" not in complete_block


@pytest.mark.unit
def test_activity_events_are_capped_and_keep_latest():
    app = UploaderApp.__new__(UploaderApp)
    app.activity_events = []

    for index in range(85):
        UploaderApp.add_activity(app, f"event {index}")

    assert len(app.activity_events) == 80
    assert app.activity_events[0]["message"] == "event 5"
    assert app.activity_events[-1]["message"] == "event 84"


@pytest.mark.unit
def test_error_status_marks_failed_and_adds_activity_reason():
    app = UploaderApp.__new__(UploaderApp)
    app.lock = Lock()
    app.progress_queue = queue.Queue()
    app.upload_count = 0
    app.upload_total = 1
    app.activity_events = []
    app.overall_progress = FakeProgress()
    status = FakeLabel()
    prog = FakeProgress()
    remove = FakeFrame()
    retry = FakeFrame()
    error_label = FakeFrame()
    app.file_widgets = {
        "failed.jpg": {
            "state": "queued",
            "status": status,
            "prog": prog,
            "remove": remove,
            "retry": retry,
            "error_label": error_label,
        }
    }
    app._update_group_progress = lambda _filepath: None
    app.progress_queue.put(("status", "failed.jpg", "error: network timeout"))

    UploaderApp._process_progress_queue(app)

    assert app.upload_count == 1
    assert app.file_widgets["failed.jpg"]["state"] == "failed"
    assert app.file_widgets["failed.jpg"]["error"] == "network timeout"
    assert status.text == "Failed"
    assert prog.value == 1.0
    assert remove.options["state"] == "normal"
    assert retry.mapped is True
    assert retry.options["state"] == "normal"
    assert error_label.mapped is True
    assert error_label.options["text"] == "Reason: network timeout"
    assert app.activity_events[-1]["message"] == "Failed failed.jpg: network timeout."


@pytest.mark.unit
def test_retry_file_resets_only_target_failed_row_and_starts_upload():
    app = UploaderApp.__new__(UploaderApp)
    app.lock = Lock()
    app.is_uploading = False
    activity = []
    started = []
    target_status = FakeLabel()
    target_prog = FakeProgress()
    target_retry = FakeFrame()
    target_error_label = FakeFrame()
    other_status = FakeLabel()
    other_prog = FakeProgress()
    other_retry = FakeFrame()
    other_error_label = FakeFrame()
    app.file_widgets = {
        "target.jpg": {
            "state": "failed",
            "status": target_status,
            "prog": target_prog,
            "retry": target_retry,
            "error_label": target_error_label,
            "error": "timeout",
        },
        "other.jpg": {
            "state": "failed",
            "status": other_status,
            "prog": other_prog,
            "retry": other_retry,
            "error_label": other_error_label,
            "error": "server error",
        },
    }
    target_retry.mapped = True
    target_error_label.mapped = True
    app.add_activity = lambda message, level="info": activity.append((message, level))
    app.start_upload = lambda: started.append(True)

    UploaderApp._retry_file(app, "target.jpg")

    assert app.file_widgets["target.jpg"]["state"] == "pending"
    assert app.file_widgets["target.jpg"]["error"] == ""
    assert target_status.text == "Retry"
    assert target_prog.value == 0
    assert target_prog.options["progress_color"] == ["#3B8ED0", "#1F6AA5"]
    assert target_retry.mapped is False
    assert target_retry.options["state"] == "disabled"
    assert target_error_label.mapped is False
    assert target_error_label.options["text"] == ""
    assert app.file_widgets["other.jpg"]["state"] == "failed"
    assert app.file_widgets["other.jpg"]["error"] == "server error"
    assert activity == [("Retrying target.jpg.", "info")]
    assert started == [True]


@pytest.mark.unit
def test_retry_file_waits_when_upload_is_active():
    app = UploaderApp.__new__(UploaderApp)
    app.is_uploading = True
    activity = []
    app.add_activity = lambda message, level="info": activity.append((message, level))

    UploaderApp._retry_file(app, "target.jpg")

    assert activity == [
        ("Wait for the current upload to finish before retrying one file.", "warning")
    ]


@pytest.mark.unit
def test_copy_file_error_copies_failure_reason(monkeypatch):
    from modules.ui import main_window

    copied = []
    activity = []
    app = UploaderApp.__new__(UploaderApp)
    app.lock = Lock()
    app.file_widgets = {"bad.jpg": {"error": "network timeout"}}
    app.add_activity = lambda message, level="info": activity.append((message, level))
    monkeypatch.setattr(main_window.pyperclip, "copy", lambda text: copied.append(text))

    UploaderApp._copy_file_error(app, "bad.jpg")

    assert copied == ["bad.jpg: network timeout"]
    assert activity == [("Copied error for bad.jpg.", "success")]


@pytest.mark.unit
def test_friendly_row_status_labels_are_user_readable():
    app = UploaderApp.__new__(UploaderApp)

    assert UploaderApp._friendly_row_status(app, "") == "Waiting"
    assert UploaderApp._friendly_row_status(app, "queued") == "Queued"
    assert UploaderApp._friendly_row_status(app, "uploading file") == "Uploading"
    assert UploaderApp._friendly_row_status(app, "Done") == "Uploaded"
    assert UploaderApp._friendly_row_status(app, "error: timeout") == "Failed"


@pytest.mark.unit
def test_failed_row_context_menu_exposes_retry_action():
    source = Path("modules/dnd.py").read_text(encoding="utf-8")

    assert 'label="Retry Image"' in source
    assert 'label="Copy Error"' in source


@pytest.mark.unit
def test_queue_order_context_menus_expose_reorder_and_sort_actions():
    source = Path("modules/dnd.py").read_text(encoding="utf-8")
    row_motion_block = source[
        source.index("def _on_row_drag_motion") : source.index("def _on_row_drag_end")
    ]

    assert "pass" not in row_motion_block
    assert "_highlight_drag_target" in row_motion_block
    assert 'label="Move to Top"' in source
    assert 'label="Move Up"' in source
    assert 'label="Move Down"' in source
    assert 'label="Move to Bottom"' in source
    assert 'label="Sort Batch by Name"' in source
    assert 'label="Sort Batch by Modified Date"' in source
    assert 'label="Reverse Batch Order"' in source
    assert "self._retry_file(filepath)" in source
    assert "self._copy_file_error(filepath)" in source
