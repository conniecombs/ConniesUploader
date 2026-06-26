# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Main application window for Connie's Uploader Ultimate.

Refactored from monolithic main.py for better maintainability.
This module contains the core UploaderApp class.
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
from tkinterdnd2 import DND_FILES, TkinterDnD
from PIL import Image, ImageTk
import threading
import queue
import os
import sys
import pyperclip
import subprocess
import platform
import time
from contextlib import nullcontext
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
from modules.ui.safe_scrollable_frame import SafeScrollableFrame

# Local Imports
from modules import config
from modules import api
from modules.widgets import ScrollableFrame, LogWindow, CollapsibleGroupFrame, ServiceSettingsView
from modules.gallery_manager import GalleryManager
from modules.gallery_service import GalleryRecord, gallery_url_for_service
from modules.settings_manager import SettingsManager
from modules.template_manager import TemplateManager, TemplateEditor
from modules.upload_manager import UploadManager
from modules.utils import ContextUtils
from modules import viper_api
from modules import file_handler
from modules.dnd import DragDropMixin
from modules.credentials_manager import CredentialsManager
from modules.auto_poster import AutoPoster
from modules.plugin_manager import PluginManager
from loguru import logger


class UploaderApp(ctk.CTk, TkinterDnD.DnDWrapper, DragDropMixin):
    def __init__(self) -> None:
        """Initialize the uploader application."""
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)
        self._init_window()
        self._init_variables()
        self._init_state()
        self._init_managers()
        self._init_ui()
        self._load_startup_file()

    def _init_window(self):
        """Initialize window properties (title, size, icon)."""
        self.title(f"Connie's Uploader Ultimate {config.APP_VERSION}")
        self.geometry("1250x850")
        self.minsize(1050, 720)

        # Set up graceful shutdown on window close
        # System Tray: Close button hides the window instead of quitting
        self.protocol("WM_DELETE_WINDOW", self.withdraw)

        try:
            ico_path = config.resource_path("logo.ico")
            png_path = config.resource_path("logo.png")
            if os.path.exists(ico_path):
                try:
                    self.iconbitmap(ico_path)
                except Exception:
                    pass
            elif os.path.exists(png_path):
                self.iconphoto(True, ImageTk.PhotoImage(Image.open(png_path)))
        except Exception as e:
            logger.warning(f"Icon load warning: {e}")

    def _init_variables(self):
        """Initialize UI variables and executors."""
        self.menu_thread_var = tk.IntVar(value=5)
        self._last_global_thread_limit_value = config.DEFAULT_THREAD_COUNT
        self.var_show_previews = tk.BooleanVar(value=True)
        self.var_separate_batches = tk.BooleanVar(value=False)
        self.var_appearance_mode = tk.StringVar(value="System")
        self.thumb_executor = ThreadPoolExecutor(max_workers=config.THUMBNAIL_WORKERS)

        # Queues for thread communication
        self.progress_queue = queue.Queue(maxsize=1000)
        self.ui_queue = queue.Queue(maxsize=500)
        self.result_queue = queue.Queue(maxsize=1000)
        self.cancel_event = threading.Event()
        self.lock = threading.Lock()

        # UI state
        self.file_widgets = {}
        self.groups = []
        self.results = []
        self.log_cache = []
        self.activity_events = []
        self.activity_log_file = config.ACTIVITY_LOG_FILE
        self.preflight_issues = []
        self.preflight_action_files = []
        self.preflight_action_file_issue_texts = []
        self.preflight_action_folders = []
        self.preflight_action_viper_targets = False
        self.preflight_detail_lines = []
        self.import_check_issues = []
        self.image_refs = set()  # Using set for O(1) add/remove operations
        self.log_window_ref = None
        self.clipboard_buffer = []
        self.upload_total = 0
        self.upload_count = 0
        self.is_uploading = False
        self.current_output_files = []
        self.current_completion_summary = None
        self.pix_galleries_to_finalize = []
        self.output_dir = "Output"
        self._template_recovery_notice_shown = False

    def _init_state(self):
        """Initialize application state tracking."""
        # Batch/Group tracking
        self.group_counter = 0

        # Drag & Drop state
        self.drag_data = {"item": None, "type": None, "y_start": 0, "widget_start": None}
        self.selected_files = set()
        self.selection_anchor = None
        self.highlighted_row = None
        self.context_menu = tk.Menu(self, tearoff=0)

        # Service-specific state
        self.vipr_galleries_map = {}
        self.selected_gallery_by_service = {}

    def _init_managers(self):
        """Initialize manager objects and background workers."""
        self.settings_mgr = SettingsManager()
        self.settings = self.settings_mgr.load()

        # Configure sidecar worker count before it's started
        from modules.sidecar import SidecarBridge

        worker_count = self.settings.get("global_worker_count", 8)
        SidecarBridge.set_worker_count(worker_count)

        self.template_mgr = TemplateManager()
        self.upload_manager = UploadManager(
            self.progress_queue, self.result_queue, self.cancel_event
        )

        self._load_credentials()
        # RenameWorker disabled - not currently used (no enqueue calls in codebase)
        # Kept in controller.py for future implementation if needed
        self.rename_worker = None

        # Central history directory
        self.central_history_path = os.path.join(
            os.path.expanduser("~"), ".conniesuploader", "history"
        )
        if not os.path.exists(self.central_history_path):
            os.makedirs(self.central_history_path)

        self.saved_threads_data = viper_api.load_saved_threads()

        # Initialize AutoPoster
        self.auto_poster = AutoPoster(self.creds, self.saved_threads_data)

        # System Tray Integration
        from modules.ui.system_tray import SystemTrayManager

        self.system_tray = SystemTrayManager(self)
        self.system_tray.start()

        # Initialize sidecar credentials for background scheduled posts.
        self._init_sidecar_credentials()

        # Listen for scheduler events
        self.scheduler_queue = queue.Queue()
        from modules.sidecar import SidecarBridge

        SidecarBridge.get().add_listener(self.scheduler_queue)
        self._process_scheduler_events()

    def _process_scheduler_events(self):
        try:
            while True:
                event = self.scheduler_queue.get_nowait()
                if event.get("type") == "scheduled_post_completed":
                    status = event.get("status")
                    msg = event.get("msg")
                    post_data = event.get("data", {})
                    thread_name = post_data.get("thread_name", "Unknown Thread")
                    if status == "posted":
                        self.add_activity(f"Scheduled post to '{thread_name}' succeeded.", "success")
                    else:
                        self.add_activity(f"Scheduled post to '{thread_name}' failed: {msg}", "error")
        except queue.Empty:
            pass
        self.after(1000, self._process_scheduler_events)

    def _init_sidecar_credentials(self):
        user = self.creds.get("vg_user")
        pwd = self.creds.get("vg_pass")
        if not user or not pwd:
            return

        def _login_sidecar():
            try:
                api_client = viper_api.ViperGirlsAPI()
                if api_client.login(user, pwd):
                    self.add_activity("ViperGirls scheduler session initialized.", "success")
                else:
                    self.add_activity(
                        "ViperGirls scheduler session could not be initialized.",
                        "warning",
                    )
            except Exception as exc:
                logger.warning(f"Could not initialize scheduled-post session: {exc}")

        threading.Thread(target=_login_sidecar, daemon=True).start()

    def _init_ui(self):
        """Initialize user interface (menu, layout, drag-and-drop)."""
        self._create_menu()
        self._create_layout()
        self._apply_settings()
        self.bind_all("<Delete>", self._delete_selected_from_key)
        self.bind_all("<BackSpace>", self._delete_selected_from_key)
        self.bind_all("<c>", self._toggle_selected_cover_from_key)
        self.bind_all("<C>", self._toggle_selected_cover_from_key)
        self.after(250, self._show_template_recovery_notice)

        # Register drag-and-drop on main window
        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", self.drop_files)
        self.bind("<Button-1>", self._clear_highlights, add="+")

        # CRITICAL FIX: Register drag-and-drop on scrollable containers with delay
        # CustomTkinter's scrollable frames use internal canvases that capture drop events
        # We need to register drop targets on these canvases after they're fully initialized
        # Using after() ensures the widget tree is complete before registration
        self.after(config.UI_DROP_TARGET_DELAY_MS, self._register_drop_targets)

    def _register_drop_targets(self):
        """
        Register drag-and-drop targets on scrollable frames.

        CustomTkinter scrollable frames use internal canvases that capture mouse events,
        including drag-and-drop. We need to explicitly register these canvases as drop
        targets and bind the drop handler to them.

        This method should be called with a delay (via after()) to ensure widgets are
        fully initialized before registration.
        """
        logger.info("Registering drop targets on scrollable containers...")

        # Force widget tree to update before registration
        self.update_idletasks()

        # Register drop target on the main file list container
        if hasattr(self.list_container, "_parent_canvas"):
            try:
                canvas = self.list_container._parent_canvas
                if canvas:
                    canvas.drop_target_register(DND_FILES)
                    canvas.dnd_bind("<<Drop>>", self.drop_files)
                    logger.info(f"✓ Registered drop target on list_container canvas: {canvas}")
                else:
                    logger.warning("list_container._parent_canvas is None")
            except Exception as e:
                logger.error(
                    f"✗ Could not register drop target on list_container: {e}", exc_info=True
                )
        else:
            logger.warning("list_container does not have _parent_canvas attribute")

        # Register drop target on the settings scrollable frame
        if hasattr(self.settings_frame_container, "_parent_canvas"):
            try:
                canvas = self.settings_frame_container._parent_canvas
                if canvas:
                    canvas.drop_target_register(DND_FILES)
                    canvas.dnd_bind("<<Drop>>", self.drop_files)
                    logger.info(
                        f"✓ Registered drop target on settings_frame_container canvas: {canvas}"
                    )
                else:
                    logger.warning("settings_frame_container._parent_canvas is None")
            except Exception as e:
                logger.error(
                    f"✗ Could not register drop target on settings_frame_container: {e}",
                    exc_info=True,
                )
        else:
            logger.warning("settings_frame_container does not have _parent_canvas attribute")

        logger.info("Drop target registration complete")

    def _load_startup_file(self):
        """Load file from command line argument if provided."""
        if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
            self.after(500, lambda: self._process_files([sys.argv[1]]))

        # Start UI update loop
        self.after(config.UI_UPDATE_INTERVAL_MS, self.update_ui_loop)

        # Start periodic image cleanup to prevent memory leaks
        self.after(config.UI_CLEANUP_INTERVAL_MS, self._cleanup_orphaned_images)

    def _load_credentials(self):
        """Load credentials from system keyring using CredentialsManager."""
        self.creds = CredentialsManager.load_all_credentials()
        if hasattr(self, "lbl_host_readiness"):
            self._refresh_host_readiness()

    def _create_menu(self):
        menubar = tk.Menu(self)
        self.configure(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Add Files", command=self.add_files)
        file_menu.add_command(label="Add Folder", command=self.add_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.graceful_shutdown)

        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Template Editor", command=self.open_template_editor)
        tools_menu.add_command(label="Reset Templates to Defaults", command=self.reset_templates_to_defaults)
        tools_menu.add_command(label="Set Credentials", command=self.open_creds_dialog)
        tools_menu.add_command(label="Manage Galleries", command=self.open_gallery_manager)
        tools_menu.add_separator()
        tools_menu.add_command(
            label="ViperGirls Posting Targets", command=self.open_viper_tools
        )
        tools_menu.add_command(
            label="ViperGirls Posting History", command=self.open_vipergirls_history
        )
        tools_menu.add_command(
            label="Scheduled Posts", command=self.open_scheduled_posts
        )

        tools_menu.add_separator()
        tools_menu.add_command(label="Install Context Menu", command=ContextUtils.install_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Execution Log", command=self.toggle_log)
        view_menu.add_command(label="Activity Terminal", command=self.open_activity_terminal)
        view_menu.add_separator()
        view_menu.add_checkbutton(
            label="Show Image Previews",
            onvalue=True,
            offvalue=False,
            variable=self.var_show_previews,
        )
        view_menu.add_checkbutton(
            label="Separate Batches for Files",
            onvalue=True,
            offvalue=False,
            variable=self.var_separate_batches,
        )

        view_menu.add_separator()
        appearance_menu = tk.Menu(view_menu, tearoff=0)
        view_menu.add_cascade(label="Appearance Mode", menu=appearance_menu)
        appearance_menu.add_radiobutton(
            label="System",
            variable=self.var_appearance_mode,
            value="System",
            command=self.change_appearance_mode,
        )
        appearance_menu.add_radiobutton(
            label="Light",
            variable=self.var_appearance_mode,
            value="Light",
            command=self.change_appearance_mode,
        )
        appearance_menu.add_radiobutton(
            label="Dark",
            variable=self.var_appearance_mode,
            value="Dark",
            command=self.change_appearance_mode,
        )

    def change_appearance_mode(self):
        mode = self.var_appearance_mode.get()
        ctk.set_appearance_mode(mode)

    def open_viper_tools(self):
        self.saved_threads_data = viper_api.load_saved_threads()
        from modules.ui import viper_api as ui_viper_api
        ui_viper_api.ViperToolsWindow(self, creds=self.creds, callback=self.refresh_thread_data)

    def open_scheduled_posts(self):
        from modules.ui.scheduled_posts_window import ScheduledPostsWindow
        win = ScheduledPostsWindow(self)
        win.grab_set()

    def open_vipergirls_history(self):
        from modules.ui import viper_api as ui_viper_api
        ui_viper_api.PostingHistoryWindow(self)

    def refresh_thread_data(self):
        """Refresh saved thread data from disk and update AutoPoster."""
        self.saved_threads_data = viper_api.load_saved_threads()
        self.auto_poster.saved_threads_data = self.saved_threads_data
        thread_names = list(self.saved_threads_data.keys()) if self.saved_threads_data else []
        for group in getattr(self, "groups", []):
            if hasattr(group, "update_thread_names"):
                group.update_thread_names(thread_names)

    def set_global_threads(self, n):
        n = self._bounded_int(
            n,
            config.DEFAULT_THREAD_COUNT,
            config.MIN_THREAD_COUNT,
            config.MAX_THREAD_COUNT,
        )
        self.menu_thread_var.set(n)
        self._last_global_thread_limit_value = n

    def open_template_editor(self):
        def on_update(new_key):
            pass

        TemplateEditor(
            self,
            self.template_mgr,
            current_mode="BBCode",
            data_callback=self.get_preview_data,
            update_callback=on_update,
        )

    def reset_templates_to_defaults(self):
        if not messagebox.askyesno(
            "Reset Templates",
            "Restore the built-in templates and remove saved custom templates?",
        ):
            return

        self.template_mgr.restore_defaults()
        self.add_activity("Template defaults restored.", "success")
        messagebox.showinfo("Templates Restored", "Default templates have been restored.")

    def _show_template_recovery_notice(self):
        if self._template_recovery_notice_shown:
            return

        issue = self.template_mgr.get_recovery_issue()
        if not issue:
            return

        self._template_recovery_notice_shown = True
        self.add_activity(
            "Template file could not be read. Defaults were restored and a backup was kept.",
            "warning",
        )

        dlg = ctk.CTkToplevel(self)
        dlg.title("Template Recovery")
        dlg.geometry("560x360")
        dlg.transient(self)
        dlg.focus_force()

        ctk.CTkLabel(
            dlg,
            text="Templates Restored",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w", padx=18, pady=(18, 4))
        ctk.CTkLabel(
            dlg,
            text=(
                "Your saved templates file could not be read. The app restored "
                "the built-in templates so you can keep working."
            ),
            text_color="gray",
            wraplength=510,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 12))

        details = ctk.CTkFrame(dlg, fg_color="transparent")
        details.pack(fill="x", padx=18, pady=(0, 8))
        self._add_recovery_detail(details, "Template file", issue.get("filepath", ""))
        self._add_recovery_detail(details, "Backup", issue.get("backup_path") or "Backup unavailable")
        self._add_recovery_detail(details, "Error", issue.get("error", "Unknown error"))

        feedback = ctk.CTkLabel(dlg, text="", text_color="gray", wraplength=510, justify="left")
        feedback.pack(anchor="w", padx=18, pady=(4, 0))

        actions = ctk.CTkFrame(dlg, fg_color="transparent")
        actions.pack(fill="x", padx=18, pady=(16, 18))

        def open_broken_file():
            backup_path = issue.get("backup_path")
            if backup_path:
                self._open_path(backup_path)

        def open_backup_folder():
            path = issue.get("backup_path") or issue.get("filepath")
            if path:
                self._open_path(os.path.dirname(path))

        def restore_defaults():
            self.template_mgr.restore_defaults()
            feedback.configure(text="Default templates restored.")
            self.add_activity("Template defaults restored.", "success")

        ctk.CTkButton(
            actions,
            text="Open Broken File",
            command=open_broken_file,
            state="normal" if issue.get("backup_path") else "disabled",
            width=135,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions,
            text="Open Folder",
            command=open_backup_folder,
            width=105,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            actions,
            text="Restore Defaults",
            command=restore_defaults,
            width=125,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            actions,
            text="Close",
            command=dlg.destroy,
            fg_color="gray",
            hover_color="#666666",
            width=80,
        ).pack(side="right")

    def _add_recovery_detail(self, parent, label: str, value: str) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(row, text=f"{label}:", width=100, anchor="w").pack(side="left")
        ctk.CTkLabel(
            row,
            text=value,
            anchor="w",
            text_color="gray",
            wraplength=390,
            justify="left",
        ).pack(side="left", fill="x", expand=True)

    def _open_path(self, path: str) -> None:
        if not path:
            return

        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.run(["open", path], check=False, shell=False)
            else:
                subprocess.run(["xdg-open", path], check=False, shell=False)
        except Exception as e:
            logger.error(f"Could not open path {path}: {e}")
            messagebox.showerror("Open Failed", f"Could not open:\n{path}\n\nError: {e}")

    def get_preview_data(self):
        if not self.groups:
            return None, None, None
        grp = next((g for g in self.groups if g.files), None)
        if not grp:
            return None, None, None
        current_service = self.var_service.get()
        size = "200"
        try:
            if hasattr(self, "settings_view"):
                raw = self.settings_view.get_raw_config(current_service)
                if raw.get("thumbnail_size"):
                    size = str(
                        self.settings_view.normalize_value(
                            current_service, "thumbnail_size", raw["thumbnail_size"]
                        )
                    )
            elif current_service == "imx.to":
                size = self.var_imx_thumb.get()
            elif current_service == "pixhost.to":
                size = self.var_pix_thumb.get()
            elif current_service == "turboimagehost":
                size = self.var_turbo_thumb.get()
            elif current_service == "vipr.im":
                val = self.var_vipr_thumb.get()
                size = val.split("x")[0] if "x" in val else val
            elif current_service == "imagebam.com":
                size = self.var_ib_thumb.get()
            if "x" in size:
                size = size.split("x")[0]
        except (AttributeError, tk.TclError) as e:
            logger.debug(f"Could not get thumbnail size for {current_service}: {e}")
        return (
            self._ordered_group_files_for_output(grp),
            grp.title,
            size,
            len(self._cover_files_for_group(grp)),
        )

    def on_gallery_created(self, service, gid=None, record=None):
        record_data = self._gallery_record_data(service, gid, record)
        service = record_data["service"]
        gid = record_data["id"]
        if not service or not gid:
            return

        self.selected_gallery_by_service[service] = record_data
        self._apply_gallery_to_service_settings(record_data)
        self.var_service.set(service)
        self._swap_service_frame(service)
        self.add_activity(
            f"Selected gallery for {service}: {record_data['name']} ({gid}).",
            "success",
        )

    def open_gallery_manager(self):
        GalleryManager(self, self.creds, callback=self.on_gallery_created)

    def _gallery_record_data(self, service, gid=None, record=None) -> Dict[str, str]:
        if isinstance(service, GalleryRecord):
            record = service
            service = record.service
            gid = record.id

        service = str(service or getattr(record, "service", "") or "").strip()
        gid = str(gid or getattr(record, "id", "") or "").strip()
        name = str(getattr(record, "name", "") or gid).strip()
        url = str(getattr(record, "url", "") or gallery_url_for_service(service, gid)).strip()
        upload_hash = str(getattr(record, "upload_hash", "") or "").strip()
        return {
            "service": service,
            "id": gid,
            "name": name or gid,
            "url": url,
            "upload_hash": upload_hash,
        }

    def _apply_gallery_to_service_settings(self, record_data: Dict[str, str]) -> None:
        settings_view = self.__dict__.get("settings_view")
        if settings_view is None:
            return
        service = record_data["service"]
        gid = record_data["id"]
        if service == "imx.to":
            settings_view.set_value("imx.to", "gallery_id", gid)
        elif service == "pixhost.to":
            settings_view.set_value("pixhost.to", "gallery_hash", gid)
        elif service == "vipr.im":
            self._apply_vipr_gallery_selection(record_data)
        elif service == "imagebam.com":
            settings_view.set_value("imagebam.com", "gallery_id", gid)

    def _apply_vipr_gallery_selection(self, record_data: Dict[str, str]) -> None:
        name = record_data["name"]
        gid = record_data["id"]
        vipr_galleries_map = self.__dict__.setdefault("vipr_galleries_map", {})
        vipr_galleries_map[name] = gid
        plugin = self.__dict__.get("service_plugins", {}).get("vipr.im")
        if plugin:
            plugin.vipr_galleries_map = dict(vipr_galleries_map)
        if hasattr(self, "cb_vipr_gallery"):
            try:
                values = list(getattr(self.cb_vipr_gallery, "_values", []) or [])
                if "None" not in values:
                    values.insert(0, "None")
                if name not in values:
                    values.append(name)
                self.cb_vipr_gallery.configure(values=values)
            except (tk.TclError, AttributeError, TypeError) as exc:
                logger.debug(f"Could not update Vipr gallery dropdown: {exc}")
        settings_view = self.__dict__.get("settings_view")
        if settings_view is not None:
            settings_view.set_value("vipr.im", "vipr_gallery_name", name)

    def gallery_selected_batch_count(self) -> int:
        return len(self._selected_groups_for_gallery_assignment())

    def _selected_groups_for_gallery_assignment(self) -> List[Any]:
        selected_files = list(self.__dict__.get("selected_files", set()) or [])
        if not selected_files:
            return []

        groups = []
        seen = set()
        lock = self.__dict__.get("lock")
        context = lock if lock is not None else nullcontext()
        with context:
            for file_path in selected_files:
                group = self.__dict__.get("file_widgets", {}).get(file_path, {}).get("group")
                if group is None or id(group) in seen:
                    continue
                seen.add(id(group))
                groups.append(group)
        return groups

    def on_gallery_assign_to_selected_batches(self, service, gid=None, record=None):
        record_data = self._gallery_record_data(service, gid, record)
        groups = self._selected_groups_for_gallery_assignment()
        if not groups:
            self.on_gallery_created(record_data["service"], record_data["id"], record)
            return

        self.selected_gallery_by_service[record_data["service"]] = record_data
        self.var_service.set(record_data["service"])
        self._swap_service_frame(record_data["service"])
        for group in groups:
            self._assign_gallery_to_group(group, record_data)

        batch_label = "batch" if len(groups) == 1 else "batches"
        self.add_activity(
            f"Assigned gallery {record_data['name']} ({record_data['id']}) "
            f"to {len(groups)} selected {batch_label}.",
            "success",
        )

    def _assign_gallery_to_group(self, group: Any, record_data: Dict[str, str]) -> None:
        group.gallery_id = record_data["id"]
        group.gallery_name = record_data["name"]
        group.gallery_url = record_data["url"]
        group.gallery_service = record_data["service"]
        group.gallery_upload_hash = record_data.get("upload_hash", "")
        if record_data["service"] == "pixhost.to" and record_data.get("upload_hash"):
            group.pix_data = {
                "gallery_hash": record_data["id"],
                "gallery_upload_hash": record_data["upload_hash"],
                "gallery_url": record_data["url"],
                "gallery_name": record_data["name"],
            }

    def open_creds_dialog(self):
        """Open credentials dialog using CredentialsManager."""
        CredentialsManager.create_credentials_dialog(
            parent=self, on_save_callback=self._load_credentials
        )

    def refresh_vipr_galleries(self, select_id=None):
        if not self.creds["vipr_user"]:
            messagebox.showerror("Error", "Vipr credentials missing.")
            return

        def _refresh():
            try:
                self.log("Vipr: Refreshing galleries via Sidecar...")
                creds = {"vipr_user": self.creds["vipr_user"], "vipr_pass": self.creds["vipr_pass"]}
                meta = api.get_vipr_metadata(creds)
                if meta and meta.get("galleries"):
                    self.vipr_galleries_map = {g["name"]: g["id"] for g in meta["galleries"]}
                    gal_names = ["None"] + list(self.vipr_galleries_map.keys())
                    plugin = getattr(self, "service_plugins", {}).get("vipr.im")
                    if plugin:
                        plugin.vipr_galleries_map = dict(self.vipr_galleries_map)
                    selected_name = next(
                        (name for name, value in self.vipr_galleries_map.items() if value == select_id),
                        None,
                    )

                    def _apply_galleries():
                        if hasattr(self, "cb_vipr_gallery"):
                            self.cb_vipr_gallery.configure(values=gal_names)
                        if selected_name:
                            self.settings_view.set_value(
                                "vipr.im", "vipr_gallery_name", selected_name
                            )

                    self.after(0, _apply_galleries)
                    self.log(f"Vipr: Found {len(meta['galleries'])} galleries.")
                else:
                    self.log("Vipr: No galleries found.")
            except Exception as e:
                self.log(f"Vipr Error: {e}")

        threading.Thread(target=_refresh, daemon=True).start()

    def _create_layout(self):
        main_container = ctk.CTkFrame(self)
        main_container.pack(fill="both", expand=True, padx=15, pady=15)

        self.settings_frame_container = SafeScrollableFrame(
            main_container, width=320, fg_color="transparent"
        )
        self.settings_frame_container.pack(side="left", fill="y", padx=(0, 10))
        ctk.CTkLabel(
            self.settings_frame_container, text="Settings", font=("Segoe UI", 16, "bold")
        ).pack(pady=10, padx=10, anchor="w")

        out_frame = ctk.CTkFrame(self.settings_frame_container)
        out_frame.pack(fill="x", padx=10, pady=5)
        self.var_auto_copy = ctk.BooleanVar()
        ctk.CTkCheckBox(out_frame, text="Auto-copy to clipboard", variable=self.var_auto_copy).pack(
            anchor="w", padx=5, pady=2
        )
        self.var_auto_gallery = ctk.BooleanVar()
        ctk.CTkCheckBox(
            out_frame, text="One Gallery Per Folder", variable=self.var_auto_gallery
        ).pack(anchor="w", padx=5, pady=2)
        self.var_auto_gallery.trace_add("write", lambda *_: self._refresh_host_readiness())
        self.var_confirm_before_posting = ctk.BooleanVar()
        ctk.CTkCheckBox(
            out_frame,
            text="Confirm before ViperGirls posting",
            variable=self.var_confirm_before_posting,
        ).pack(anchor="w", padx=5, pady=2)

        self.btn_open = ctk.CTkButton(
            out_frame, text="Open Output Folder", command=self.open_output_folder, state="disabled"
        )
        self.btn_open.pack(fill="x", padx=5, pady=10)
        self._create_global_advanced_section(out_frame)

        ctk.CTkLabel(
            self.settings_frame_container, text="Select Image Host", font=("Segoe UI", 13, "bold")
        ).pack(pady=(15, 2), padx=10, anchor="w")
        # Dynamically get available plugins from PluginManager
        self.plugin_manager = PluginManager()
        available_services = self.plugin_manager.get_service_names()
        default_service = (
            "pixhost.to"
            if "pixhost.to" in available_services
            else (available_services[0] if available_services else "imx.to")
        )

        self.var_service = ctk.StringVar(value=default_service)
        self.cb_service_select = ctk.CTkOptionMenu(
            self.settings_frame_container,
            variable=self.var_service,
            values=available_services,
            command=self._swap_service_frame,
        )
        self.cb_service_select.pack(fill="x", padx=10, pady=(0, 10))
        self._create_host_readiness_panel()

        self.service_settings_container = ctk.CTkFrame(
            self.settings_frame_container, fg_color="transparent"
        )
        self.service_settings_container.pack(fill="x", padx=5, pady=0)

        # --- REFACTOR: Delegate frame creation to ServiceSettingsView ---
        self.settings_view = ServiceSettingsView(
            self.service_settings_container, self, plugin_manager=self.plugin_manager
        )

        btn_frame = ctk.CTkFrame(self.settings_frame_container, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=10)
        self.btn_start = ctk.CTkButton(btn_frame, text="Start Upload", command=self.start_upload)
        self.btn_start.pack(fill="x", pady=5)
        self.btn_stop = ctk.CTkButton(
            btn_frame,
            text="Stop",
            command=self.stop_upload,
            state="disabled",
        )
        self.btn_stop.pack(fill="x", pady=5)
        self._configure_stop_button(False)

        right_panel = ctk.CTkFrame(main_container)
        right_panel.pack(side="right", fill="both", expand=True)

        queue_toolbar = ctk.CTkFrame(right_panel, fg_color="transparent")
        queue_toolbar.pack(fill="x", padx=5, pady=(5, 0))

        queue_title = ctk.CTkFrame(queue_toolbar, fg_color="transparent")
        queue_title.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(queue_title, text="Upload Queue", font=("Segoe UI", 16, "bold")).pack(
            anchor="w"
        )
        self.lbl_file_summary = ctk.CTkLabel(queue_title, text="No files added", text_color="gray")
        self.lbl_file_summary.pack(anchor="w")

        self.queue_actions = ctk.CTkFrame(queue_toolbar, fg_color="transparent")
        self.queue_actions.pack(side="right", padx=(10, 0))
        self.btn_add_files = ctk.CTkButton(
            self.queue_actions, text="Add Files", command=self.add_files, width=110
        )
        self.btn_add_files.pack(side="left", padx=(0, 6))
        self.btn_add_folder = ctk.CTkButton(
            self.queue_actions, text="Add Folder", command=self.add_folder, width=110
        )
        self.btn_add_folder.pack(side="left", padx=(0, 6))
        self.btn_retry_failed = ctk.CTkButton(
            self.queue_actions, text="Retry Failed", command=self.retry_failed, width=110
        )
        self.btn_retry_failed.pack(side="left", padx=(0, 6))
        self.btn_clear_list = ctk.CTkButton(
            self.queue_actions, text="Clear List", command=self.clear_list, width=100
        )
        self.btn_clear_list.pack(side="left")

        self.selection_actions = ctk.CTkFrame(right_panel, fg_color="transparent")
        self.lbl_selection_summary = ctk.CTkLabel(
            self.selection_actions, text="0 selected", text_color="gray"
        )
        self.lbl_selection_summary.pack(side="left", padx=(0, 10))
        self.btn_selection_mark_cover = ctk.CTkButton(
            self.selection_actions,
            text="Mark Cover",
            command=lambda: self._set_cover_for_selected(True),
            width=92,
            height=26,
            fg_color="gray",
            hover_color="#666666",
        )
        self.btn_selection_mark_cover.pack(side="left", padx=(0, 6))
        self.btn_selection_clear_cover = ctk.CTkButton(
            self.selection_actions,
            text="Clear Cover",
            command=lambda: self._set_cover_for_selected(False),
            width=92,
            height=26,
            fg_color="gray",
            hover_color="#666666",
        )
        self.btn_selection_clear_cover.pack(side="left", padx=(0, 6))
        self.btn_selection_remove = ctk.CTkButton(
            self.selection_actions,
            text="Remove",
            command=self._delete_selected_files,
            width=76,
            height=26,
            fg_color="#8E2F2F",
            hover_color="#6F2424",
        )
        self.btn_selection_remove.pack(side="left")

        self.list_container = ScrollableFrame(right_panel, width=600)
        self.list_container.pack(fill="both", expand=True, padx=5, pady=5)
        self.file_frame = self.list_container
        self._create_empty_queue_state()
        self._create_import_checks_panel(right_panel)
        self._create_upload_checks_panel(right_panel)
        self._create_completion_panel(right_panel)
        self._refresh_queue_state()

        footer = ctk.CTkFrame(right_panel, height=40, fg_color="transparent")
        self.queue_footer = footer
        footer.pack(fill="x", padx=5, pady=5)
        self.lbl_eta = ctk.CTkLabel(footer, text="Ready...", text_color="gray")
        self.lbl_eta.pack(anchor="w")
        self.overall_progress = ctk.CTkProgressBar(footer)
        self.overall_progress.set(0)
        self.overall_progress.pack(fill="x", pady=5)

    def _create_global_advanced_section(self, parent):
        self.var_global_worker_count = ctk.IntVar(value=config.DEFAULT_WORKER_COUNT)

        wrapper = ctk.CTkFrame(parent, fg_color="transparent")
        wrapper.pack(fill="x", padx=5, pady=(0, 8))

        content = ctk.CTkFrame(wrapper, fg_color="transparent")
        expanded = {"value": False}

        def toggle():
            expanded["value"] = not expanded["value"]
            if expanded["value"]:
                btn_toggle.configure(text="Advanced App Settings -")
                content.pack(fill="x", pady=(6, 0))
            else:
                content.pack_forget()
                btn_toggle.configure(text="Advanced App Settings +")

        btn_toggle = ctk.CTkButton(
            wrapper,
            text="Advanced App Settings +",
            command=toggle,
            fg_color="gray",
            hover_color="#666666",
        )
        btn_toggle.pack(fill="x")

        worker_frame = ctk.CTkFrame(content, fg_color="transparent")
        worker_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(worker_frame, text="Worker Count:", width=100).pack(side="left")
        worker_spinbox = ctk.CTkEntry(
            worker_frame, textvariable=self.var_global_worker_count, width=60
        )
        worker_spinbox.pack(side="left", padx=5)
        worker_spinbox.bind(
            "<FocusOut>",
            lambda _event: self._set_bounded_var(
                self.var_global_worker_count,
                self.var_global_worker_count.get(),
                config.DEFAULT_WORKER_COUNT,
                config.MIN_WORKER_COUNT,
                config.MAX_WORKER_COUNT,
            ),
        )
        worker_spinbox.bind(
            "<Return>",
            lambda _event: self._set_bounded_var(
                self.var_global_worker_count,
                self.var_global_worker_count.get(),
                config.DEFAULT_WORKER_COUNT,
                config.MIN_WORKER_COUNT,
                config.MAX_WORKER_COUNT,
            ),
        )
        ctk.CTkLabel(
            worker_frame,
            text=f"({config.MIN_WORKER_COUNT}-{config.MAX_WORKER_COUNT})",
            font=("Segoe UI", 10),
        ).pack(side="left")

        thread_frame = ctk.CTkFrame(content, fg_color="transparent")
        thread_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(thread_frame, text="Thread Limit:", width=100).pack(side="left")
        thread_limit_entry = ctk.CTkEntry(
            thread_frame, textvariable=self.menu_thread_var, width=60
        )
        thread_limit_entry.pack(side="left", padx=5)
        thread_limit_entry.bind(
            "<FocusOut>", lambda _event: self.set_global_threads(self.menu_thread_var.get())
        )
        thread_limit_entry.bind(
            "<Return>", lambda _event: self.set_global_threads(self.menu_thread_var.get())
        )
        ctk.CTkLabel(
            thread_frame,
            text=f"({config.MIN_THREAD_COUNT}-{config.MAX_THREAD_COUNT})",
            font=("Segoe UI", 10),
        ).pack(side="left")

    def _create_empty_queue_state(self):
        self.empty_queue_frame = ctk.CTkFrame(self.list_container, fg_color="transparent")
        self.empty_queue_frame.pack(fill="both", expand=True, padx=24, pady=90)

        ctk.CTkLabel(
            self.empty_queue_frame,
            text="Add images to begin",
            font=("Segoe UI", 18, "bold"),
        ).pack(pady=(0, 6))
        ctk.CTkLabel(
            self.empty_queue_frame,
            text="Drag files or folders here.",
            text_color="gray",
            wraplength=520,
            justify="center",
        ).pack(pady=(0, 14))

    def _set_empty_queue_visible(self, visible: bool) -> None:
        if not hasattr(self, "empty_queue_frame"):
            return

        if visible:
            if not self.empty_queue_frame.winfo_ismapped():
                self.empty_queue_frame.pack(fill="both", expand=True, padx=24, pady=90)
        else:
            if self.empty_queue_frame.winfo_ismapped():
                self.empty_queue_frame.pack_forget()

    def _set_queue_actions_visible(self, visible: bool) -> None:
        if "queue_actions" not in self.__dict__:
            return

        if visible:
            if not self.queue_actions.winfo_ismapped():
                self.queue_actions.pack(side="right", padx=(10, 0))
        elif self.queue_actions.winfo_ismapped():
            self.queue_actions.pack_forget()

    def _set_selection_actions_visible(self, visible: bool) -> None:
        if "selection_actions" not in self.__dict__:
            return

        if visible:
            if not self.selection_actions.winfo_ismapped():
                pack_kwargs = {"fill": "x", "padx": 5, "pady": (4, 0)}
                if "list_container" in self.__dict__:
                    pack_kwargs["before"] = self.list_container
                self.selection_actions.pack(**pack_kwargs)
        else:
            if self.selection_actions.winfo_ismapped():
                self.selection_actions.pack_forget()

    def _selected_queue_files(self) -> List[str]:
        selection = set(self.__dict__.get("selected_files", set()) or [])
        if not selection:
            return []

        ordered = self._ordered_filepaths()
        with self.lock:
            active_files = set(self.file_widgets)
        return [
            filepath for filepath in ordered if filepath in selection and filepath in active_files
        ]

    def _refresh_selection_actions(self) -> None:
        if "selection_actions" not in self.__dict__:
            return

        selected_files = self._selected_queue_files()
        count = len(selected_files)
        image_label = "image" if count == 1 else "images"
        self.lbl_selection_summary.configure(text=f"{count} selected {image_label}")
        self._set_selection_actions_visible(count > 0)

        button_state = "disabled" if getattr(self, "is_uploading", False) else "normal"
        for button in (
            self.btn_selection_mark_cover,
            self.btn_selection_clear_cover,
            self.btn_selection_remove,
        ):
            button.configure(state=button_state)

    def _set_cover_for_selected(self, is_cover: bool) -> None:
        self._set_cover_for_files(self._selected_queue_files(), is_cover)

    def _delete_selected_files(self) -> bool:
        return self._delete_files(self._selected_queue_files())

    def _event_targets_text_input(self, event) -> bool:
        widget = getattr(event, "widget", None)
        if widget is None:
            return False

        try:
            widget_class = str(widget.winfo_class()).lower()
        except (tk.TclError, AttributeError):
            widget_class = ""
        python_class = widget.__class__.__name__.lower()
        combined = f"{widget_class} {python_class}"
        return any(
            token in combined for token in ("entry", "text", "textbox", "spinbox", "combobox")
        )

    def _delete_selected_from_key(self, event=None):
        if self._event_targets_text_input(event):
            return None
        if self._delete_selected_files():
            return "break"
        return None

    def _toggle_selected_cover_from_key(self, event=None):
        if self._event_targets_text_input(event):
            return None
        state = int(getattr(event, "state", 0) or 0)
        if state & (self._CTRL_MASK | 0x0008):
            return None

        selected_files = self._selected_queue_files()
        if not selected_files:
            return None
        all_selected_are_covers = all(self._is_cover_file(filepath) for filepath in selected_files)
        self._set_cover_for_files(selected_files, not all_selected_are_covers)
        return "break"

    def _refresh_queue_state(self) -> None:
        if not hasattr(self, "lbl_file_summary"):
            return

        with self.lock:
            file_count = len(self.file_widgets)
        group_count = len(self.groups)

        if file_count == 0:
            if group_count == 0:
                summary = "No files added"
            else:
                batch_label = "batch" if group_count == 1 else "batches"
                summary = f"{group_count} empty {batch_label}"
        else:
            file_label = "file" if file_count == 1 else "files"
            batch_label = "batch" if group_count == 1 else "batches"
            summary = f"{file_count} {file_label} in {group_count} {batch_label}"

        self.lbl_file_summary.configure(text=summary)
        queue_is_empty = file_count == 0 and group_count == 0
        self._set_empty_queue_visible(queue_is_empty)
        self._set_queue_actions_visible(not queue_is_empty)
        self._refresh_selection_actions()
        self._refresh_start_button_state()

    def _queue_panel_pack_kwargs(self) -> Dict[str, Any]:
        pack_kwargs: Dict[str, Any] = {"fill": "x", "padx": 5, "pady": (0, 5)}
        if "queue_footer" in self.__dict__:
            pack_kwargs["before"] = self.queue_footer
        return pack_kwargs

    def _create_upload_checks_panel(self, parent) -> None:
        self.upload_checks_panel = ctk.CTkFrame(parent, border_width=1, border_color="#FFB340")

        header = ctk.CTkFrame(self.upload_checks_panel, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(8, 2))
        self.lbl_upload_checks_title = ctk.CTkLabel(
            header,
            text="Upload Checks",
            font=("Segoe UI", 13, "bold"),
            text_color="#FFB340",
        )
        self.lbl_upload_checks_title.pack(side="left")

        self.btn_upload_checks_hide = ctk.CTkButton(
            header,
            text="Hide",
            command=lambda: self._set_upload_checks([]),
            width=62,
            height=26,
            fg_color="gray",
            hover_color="#666666",
        )
        self.btn_upload_checks_hide.pack(side="right")

        self.upload_checks_body = ctk.CTkFrame(self.upload_checks_panel, fg_color="transparent")
        self.upload_checks_body.pack(fill="x", padx=10, pady=(0, 8))

        self.upload_checks_actions = ctk.CTkFrame(
            self.upload_checks_panel, fg_color="transparent"
        )
        self.btn_upload_checks_credentials = ctk.CTkButton(
            self.upload_checks_actions,
            text="Set Credentials",
            command=self.open_creds_dialog,
            width=125,
            height=28,
        )
        self.btn_upload_checks_viper_targets = ctk.CTkButton(
            self.upload_checks_actions,
            text="Manage ViperGirls Targets",
            command=self.open_viper_tools,
            width=175,
            height=28,
        )
        self.btn_upload_checks_remove_files = ctk.CTkButton(
            self.upload_checks_actions,
            text="Remove Invalid Files",
            command=self._remove_preflight_file_issues,
            width=145,
            height=28,
        )
        self.btn_upload_checks_open_folder = ctk.CTkButton(
            self.upload_checks_actions,
            text="Open Problem Folder",
            command=self._open_preflight_problem_folder,
            width=145,
            height=28,
        )
        self.btn_upload_checks_retry = ctk.CTkButton(
            self.upload_checks_actions,
            text="Try Upload Again",
            command=self.start_upload,
            width=125,
            height=28,
            fg_color="gray",
            hover_color="#666666",
        )

    def _set_upload_checks(self, issues: List[str]) -> None:
        self.preflight_issues = [str(issue) for issue in issues if str(issue).strip()]
        if not self.preflight_issues:
            self._reset_preflight_actions()
        if "upload_checks_panel" in self.__dict__:
            self._render_upload_checks()

    def _render_upload_checks(self) -> None:
        issues = getattr(self, "preflight_issues", [])
        if not issues:
            if self.upload_checks_panel.winfo_ismapped():
                self.upload_checks_panel.pack_forget()
            return

        if not self.upload_checks_panel.winfo_ismapped():
            self.upload_checks_panel.pack(**self._queue_panel_pack_kwargs())

        count = len(issues)
        issue_label = "issue" if count == 1 else "issues"
        self.lbl_upload_checks_title.configure(text=f"Upload Checks: {count} {issue_label}")
        self._refresh_upload_check_actions(issues)

        for child in self.upload_checks_body.winfo_children():
            child.destroy()

        detail_lines = getattr(self, "preflight_detail_lines", [])
        for detail in detail_lines[:5]:
            ctk.CTkLabel(
                self.upload_checks_body,
                text=f"- {detail}",
                anchor="w",
                justify="left",
                wraplength=690,
                text_color="#A8DADC",
            ).pack(anchor="w", fill="x", pady=1)

        visible_issues = issues[:6]
        for issue in visible_issues:
            ctk.CTkLabel(
                self.upload_checks_body,
                text=f"- {issue}",
                anchor="w",
                justify="left",
                wraplength=690,
                text_color="#FFB340",
            ).pack(anchor="w", fill="x", pady=1)

        remaining = len(issues) - len(visible_issues)
        if remaining > 0:
            ctk.CTkLabel(
                self.upload_checks_body,
                text=f"...and {remaining} more issue(s).",
                anchor="w",
                text_color="gray",
            ).pack(anchor="w", fill="x", pady=(2, 0))

    def _set_upload_check_action_visible(self, button, visible: bool, **pack_kwargs) -> None:
        if visible:
            button.configure(state="normal")
            if not button.winfo_ismapped():
                button.pack(**pack_kwargs)
        elif button.winfo_ismapped():
            button.pack_forget()

    def _refresh_upload_check_actions(self, issues: List[str]) -> None:
        show_credentials = self._preflight_issues_need_credentials(issues)
        show_viper_targets = bool(getattr(self, "preflight_action_viper_targets", False))
        show_remove_files = bool(self._preflight_action_files())
        show_open_folder = bool(self._preflight_action_folders())
        show_retry = bool(issues)
        show_actions = any(
            (
                show_credentials,
                show_viper_targets,
                show_remove_files,
                show_open_folder,
                show_retry,
            )
        )

        if show_actions:
            if not self.upload_checks_actions.winfo_ismapped():
                self.upload_checks_actions.pack(fill="x", padx=10, pady=(0, 8))
        elif self.upload_checks_actions.winfo_ismapped():
            self.upload_checks_actions.pack_forget()

        self._set_upload_check_action_visible(
            self.btn_upload_checks_credentials,
            show_credentials,
            side="left",
            padx=(0, 6),
        )
        self._set_upload_check_action_visible(
            self.btn_upload_checks_viper_targets,
            show_viper_targets,
            side="left",
            padx=6,
        )
        self._set_upload_check_action_visible(
            self.btn_upload_checks_remove_files,
            show_remove_files,
            side="left",
            padx=6,
        )
        self._set_upload_check_action_visible(
            self.btn_upload_checks_open_folder,
            show_open_folder,
            side="left",
            padx=6,
        )
        self._set_upload_check_action_visible(
            self.btn_upload_checks_retry,
            show_retry,
            side="right",
        )

    def _create_import_checks_panel(self, parent) -> None:
        self.import_checks_panel = ctk.CTkFrame(parent, border_width=1, border_color="#FFB340")

        header = ctk.CTkFrame(self.import_checks_panel, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(8, 2))
        self.lbl_import_checks_title = ctk.CTkLabel(
            header,
            text="Import Checks",
            font=("Segoe UI", 13, "bold"),
            text_color="#FFB340",
        )
        self.lbl_import_checks_title.pack(side="left")
        self.btn_import_checks_hide = ctk.CTkButton(
            header,
            text="Hide",
            command=lambda: self._set_import_checks([]),
            width=62,
            height=26,
            fg_color="gray",
            hover_color="#666666",
        )
        self.btn_import_checks_hide.pack(side="right")

        self.import_checks_body = ctk.CTkFrame(self.import_checks_panel, fg_color="transparent")
        self.import_checks_body.pack(fill="x", padx=10, pady=(0, 8))

    def _set_import_checks(self, issues: List[str]) -> None:
        self.import_check_issues = [str(issue) for issue in issues if str(issue).strip()]
        if "import_checks_panel" in self.__dict__:
            self._render_import_checks()

    def _render_import_checks(self) -> None:
        issues = getattr(self, "import_check_issues", [])
        if not issues:
            if self.import_checks_panel.winfo_ismapped():
                self.import_checks_panel.pack_forget()
            return

        if not self.import_checks_panel.winfo_ismapped():
            self.import_checks_panel.pack(**self._queue_panel_pack_kwargs())

        count = len(issues)
        issue_label = "issue" if count == 1 else "issues"
        self.lbl_import_checks_title.configure(text=f"Import Checks: {count} {issue_label}")

        for child in self.import_checks_body.winfo_children():
            child.destroy()

        visible_issues = issues[:6]
        for issue in visible_issues:
            ctk.CTkLabel(
                self.import_checks_body,
                text=f"- {issue}",
                anchor="w",
                justify="left",
                wraplength=690,
                text_color="#FFB340",
            ).pack(anchor="w", fill="x", pady=1)

        remaining = len(issues) - len(visible_issues)
        if remaining > 0:
            ctk.CTkLabel(
                self.import_checks_body,
                text=f"...and {remaining} more issue(s).",
                anchor="w",
                text_color="gray",
            ).pack(anchor="w", fill="x", pady=(2, 0))

    def _create_completion_panel(self, parent) -> None:
        self.completion_panel = ctk.CTkFrame(parent, border_width=1, border_color="#34C759")

        header = ctk.CTkFrame(self.completion_panel, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(8, 2))
        self.lbl_completion_title = ctk.CTkLabel(
            header,
            text="Upload Complete",
            font=("Segoe UI", 13, "bold"),
            text_color="#34C759",
        )
        self.lbl_completion_title.pack(side="left")
        self.btn_completion_hide = ctk.CTkButton(
            header,
            text="Hide",
            command=lambda: self._set_completion_summary(None),
            width=62,
            height=26,
            fg_color="gray",
            hover_color="#666666",
        )
        self.btn_completion_hide.pack(side="right")

        self.lbl_completion_status = ctk.CTkLabel(
            self.completion_panel,
            text="",
            anchor="w",
            justify="left",
            wraplength=690,
            text_color="gray",
        )
        self.lbl_completion_status.pack(fill="x", padx=10, pady=(0, 8))

        details = ctk.CTkFrame(self.completion_panel, fg_color="transparent")
        details.pack(fill="x", padx=10, pady=(0, 6))
        self.lbl_completion_uploaded = self._add_inline_completion_detail(details, "Uploaded")
        self.lbl_completion_failed = self._add_inline_completion_detail(details, "Failed")
        self.lbl_completion_generated = self._add_inline_completion_detail(
            details, "Generated files"
        )
        self.lbl_completion_clipboard = self._add_inline_completion_detail(details, "Clipboard")

        self.lbl_completion_files = ctk.CTkLabel(
            self.completion_panel,
            text="",
            anchor="w",
            justify="left",
            wraplength=690,
            text_color="gray",
        )

        self.lbl_completion_feedback = ctk.CTkLabel(
            self.completion_panel,
            text="",
            anchor="w",
            justify="left",
            text_color="gray",
        )

        self.completion_actions = ctk.CTkFrame(self.completion_panel, fg_color="transparent")
        self.btn_completion_open = ctk.CTkButton(
            self.completion_actions,
            text="Open Folder",
            command=self.open_output_folder,
            width=110,
            height=28,
        )
        self.btn_completion_copy = ctk.CTkButton(
            self.completion_actions,
            text="Copy Output",
            command=self._copy_completion_again,
            width=110,
            height=28,
        )
        self.btn_completion_schedule = ctk.CTkButton(
            self.completion_actions,
            text="Schedule for Later",
            command=self._open_schedule_modal,
            width=130,
            height=28,
        )

    def _add_inline_completion_detail(self, parent, label: str):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(side="left", padx=(0, 22))
        ctk.CTkLabel(row, text=f"{label}:", anchor="w", text_color="gray").pack(anchor="w")
        value_label = ctk.CTkLabel(row, text="0", anchor="w", font=("Segoe UI", 13, "bold"))
        value_label.pack(anchor="w")
        return value_label

    def _set_completion_summary(self, summary: Optional[Dict[str, Any]]) -> None:
        self.current_completion_summary = summary
        if "completion_panel" in self.__dict__:
            self._render_completion_summary()

    def _hide_completion_summary(self) -> None:
        if "completion_panel" in self.__dict__ and self.completion_panel.winfo_ismapped():
            self.completion_panel.pack_forget()
        for button_name in (
            "btn_completion_open",
            "btn_completion_copy",
            "btn_completion_schedule",
        ):
            button = getattr(self, button_name, None)
            if button and button.winfo_ismapped():
                button.pack_forget()
        if "completion_actions" in self.__dict__ and self.completion_actions.winfo_ismapped():
            self.completion_actions.pack_forget()

    def _render_completion_summary(self) -> None:
        summary = getattr(self, "current_completion_summary", None)
        if not summary:
            self._hide_completion_summary()
            return

        failed_count = int(summary.get("failed_count") or 0)
        accent_color = "#FFB340" if failed_count else "#34C759"
        title = "Upload Finished with Issues" if failed_count else "Upload Complete"

        if not self.completion_panel.winfo_ismapped():
            self.completion_panel.pack(**self._queue_panel_pack_kwargs())

        self.completion_panel.configure(border_color=accent_color)
        self.lbl_completion_title.configure(text=title, text_color=accent_color)
        self.lbl_completion_status.configure(text=summary.get("status_text", "Upload complete."))
        self.lbl_completion_uploaded.configure(text=str(summary.get("uploaded_count", 0)))
        self.lbl_completion_failed.configure(text=str(summary.get("failed_count", 0)))
        self.lbl_completion_generated.configure(text=str(summary.get("generated_count", 0)))
        self.lbl_completion_clipboard.configure(text=self._completion_clipboard_status(summary))

        file_text = self._completion_output_file_text(summary)
        if file_text:
            self.lbl_completion_files.configure(text=file_text)
            if not self.lbl_completion_files.winfo_ismapped():
                self.lbl_completion_files.pack(fill="x", padx=10, pady=(0, 6))
        elif self.lbl_completion_files.winfo_ismapped():
            self.lbl_completion_files.pack_forget()

        feedback = summary.get("feedback", "")
        self.lbl_completion_feedback.configure(text=feedback)
        if feedback:
            if not self.lbl_completion_feedback.winfo_ismapped():
                self.lbl_completion_feedback.pack(fill="x", padx=10, pady=(0, 6))
        elif self.lbl_completion_feedback.winfo_ismapped():
            self.lbl_completion_feedback.pack_forget()

        self._refresh_completion_actions(summary)

    def _completion_clipboard_status(self, summary: Dict[str, Any]) -> str:
        if summary.get("copied_to_clipboard"):
            return "Copied"
        if summary.get("auto_copy_requested"):
            return "Copy failed"
        return "Not copied"

    def _completion_output_file_text(self, summary: Dict[str, Any]) -> str:
        output_files = summary.get("output_files", [])
        if not output_files:
            return ""

        names = [os.path.basename(path) for path in output_files[:4]]
        if len(output_files) > 4:
            names.append(f"...and {len(output_files) - 4} more")
        return "Generated: " + ", ".join(names)

    def _set_completion_action_visible(self, button, visible: bool, **pack_kwargs) -> None:
        if visible:
            button.configure(state="normal")
            if not button.winfo_ismapped():
                button.pack(**pack_kwargs)
        elif button.winfo_ismapped():
            button.pack_forget()

    def _refresh_completion_actions(self, summary: Dict[str, Any]) -> None:
        show_open = bool(summary.get("output_files"))
        show_copy = bool(summary.get("has_copy_text"))
        show_actions = show_open or show_copy

        if show_actions:
            if not self.completion_actions.winfo_ismapped():
                self.completion_actions.pack(fill="x", padx=10, pady=(0, 8))
        elif self.completion_actions.winfo_ismapped():
            self.completion_actions.pack_forget()

        self._set_completion_action_visible(
            self.btn_completion_open,
            show_open,
            side="left",
            padx=(0, 6),
        )
        self._set_completion_action_visible(
            self.btn_completion_copy,
            show_copy,
            side="left",
            padx=(0, 6),
        )
        self._set_completion_action_visible(
            self.btn_completion_schedule,
            show_copy,  # If there is output, we can schedule it.
            side="left",
            padx=(0, 6),
        )

    def _copy_completion_again(self) -> None:
        summary = getattr(self, "current_completion_summary", None)
        if not summary:
            self.add_activity("No completed upload output is available to copy.", "warning")
            return

        if self._copy_completion_output_to_clipboard(summary):
            summary["copied_to_clipboard"] = True
            summary["feedback"] = "Copied output to clipboard."
            self.add_activity("Copied output to clipboard.", "success")
        else:
            summary["feedback"] = "No output text was available to copy."
            self.add_activity("No output text was available to copy.", "warning")
        self._set_completion_summary(summary)

    def _open_schedule_modal(self) -> None:
        summary = getattr(self, "current_completion_summary", None)
        if not summary:
            self.add_activity("No completed upload output is available to schedule.", "warning")
            return

        text = self._completion_output_text(summary)
        if not text:
            self.add_activity("No output text was available to schedule.", "warning")
            return

        # Defer import to avoid circular dependency
        from modules.ui.scheduled_posts_window import SchedulePostModal

        modal = SchedulePostModal(self, text, self.saved_threads_data)
        modal.grab_set()
        self.wait_window(modal)

        result = modal.get_result()
        if result:
            from modules.viper_api import ViperGirlsAPI
            import uuid

            post_id = str(uuid.uuid4())
            api = ViperGirlsAPI()
            from modules.sidecar import SidecarBridge

            api.bridge = SidecarBridge.get()
            success = api.schedule_post(
                post_id,
                result["thread_id"],
                result["thread_name"],
                result["message"],
                result["scheduled_time"],
            )
            if success:
                self.add_activity(f"Scheduled post for {result['scheduled_time']}", "success")
                summary["feedback"] = f"Post scheduled for {result['scheduled_time']}."
                self._set_completion_summary(summary)
            else:
                self.add_activity("Failed to schedule post.", "error")

    def _preflight_issues_need_credentials(self, issues: List[str]) -> bool:
        credential_words = ("credential", "client id", "access token", "password", "api key")
        return any(
            any(word in str(issue).lower() for word in credential_words) for issue in issues
        )

    def _preflight_action_files(self) -> List[str]:
        return list(dict.fromkeys(getattr(self, "preflight_action_files", [])))

    def _preflight_action_folders(self) -> List[Dict[str, str]]:
        folders = []
        seen = set()
        for folder in getattr(self, "preflight_action_folders", []):
            path = str(folder.get("path", "") if isinstance(folder, dict) else folder)
            if not path or path in seen:
                continue
            seen.add(path)
            label = folder.get("label", "Folder") if isinstance(folder, dict) else "Folder"
            folders.append({"label": str(label), "path": path})
        return folders

    def _reset_preflight_actions(self) -> None:
        self.preflight_action_files = []
        self.preflight_action_file_issue_texts = []
        self.preflight_action_folders = []
        self.preflight_action_viper_targets = False

    def _handle_preflight_issues(self, issues: List[str]) -> None:
        issue_count = len(issues)
        issue_label = "issue" if issue_count == 1 else "issues"
        self.lbl_eta.configure(text=f"Fix {issue_count} upload {issue_label} before uploading.")
        self._set_upload_checks(issues)
        self.add_activity(
            f"Upload blocked: {issue_count} {issue_label} need attention.", "error"
        )
        for issue in issues[:5]:
            self.add_activity(str(issue), "error")
        self._refresh_start_button_state()

    def _remove_preflight_file_issues(self) -> None:
        file_paths = self._preflight_action_files()
        removed = 0

        for file_path in file_paths:
            with self.lock:
                is_queued = file_path in self.file_widgets
            if not is_queued:
                continue
            self._delete_file(file_path)
            removed += 1

        file_issue_texts = set(getattr(self, "preflight_action_file_issue_texts", []))
        remaining_issues = [
            issue for issue in getattr(self, "preflight_issues", []) if issue not in file_issue_texts
        ]
        self.preflight_action_files = []
        self.preflight_action_file_issue_texts = []
        self._set_upload_checks(remaining_issues)

        if removed:
            file_label = "file" if removed == 1 else "files"
            self.add_activity(f"Removed {removed} invalid {file_label} from the queue.", "warning")
        else:
            self.add_activity("No invalid queued files were available to remove.", "warning")

    def _open_preflight_problem_folder(self) -> None:
        folders = self._preflight_action_folders()
        if not folders:
            self.add_activity("No problem folder is available to open.", "warning")
            return

        folder = folders[0]
        path = self._nearest_existing_folder(folder["path"])
        self._open_path(path)
        self.add_activity(f"Opened {folder['label']}: {path}.")

    def _nearest_existing_folder(self, path: str) -> str:
        current = os.path.abspath(path)
        while current and not os.path.isdir(current):
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        return current if os.path.isdir(current) else os.path.abspath(os.path.expanduser("~"))

    def add_activity(self, message: str, level: str = "info") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        event = {"time": timestamp, "message": str(message), "level": level}
        self.activity_events.append(event)
        self.activity_events = self.activity_events[-80:]
        self._append_activity_log(event)

    def _append_activity_log(self, event: Dict[str, str]) -> None:
        log_path = self.__dict__.get("activity_log_file")
        if not log_path:
            return

        try:
            log_dir = os.path.dirname(log_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            line = f"{event['time']} [{event.get('level', 'info').upper()}] {event['message']}\n"
            with open(log_path, "a", encoding="utf-8") as log_file:
                log_file.write(line)
        except OSError as exc:
            logger.debug(f"Could not write activity log: {exc}")

    def open_activity_terminal(self) -> None:
        log_path = self.__dict__.get("activity_log_file") or config.ACTIVITY_LOG_FILE
        self.activity_log_file = log_path
        try:
            log_dir = os.path.dirname(log_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            open(log_path, "a", encoding="utf-8").close()
        except OSError as exc:
            messagebox.showerror("Activity Terminal", f"Could not create activity log:\n\n{exc}")
            return

        escaped_path = log_path.replace("'", "''")
        command = (
            f"Write-Host 'Connie''s Uploader activity log'; "
            f"Write-Host '{escaped_path}'; "
            f"Get-Content -LiteralPath '{escaped_path}' -Wait"
        )
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoExit", "-Command", command],
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        except OSError as exc:
            messagebox.showerror("Activity Terminal", f"Could not open PowerShell:\n\n{exc}")

    def _create_host_readiness_panel(self) -> None:
        self.host_readiness_frame = ctk.CTkFrame(self.settings_frame_container)
        self.host_readiness_frame.pack(fill="x", padx=10, pady=(0, 8))

        self.lbl_host_readiness = ctk.CTkLabel(
            self.host_readiness_frame,
            text="Checking host readiness...",
            anchor="w",
            justify="left",
            wraplength=250,
        )
        self.lbl_host_readiness.pack(fill="x", padx=8, pady=(8, 4))

        self.btn_host_credentials = ctk.CTkButton(
            self.host_readiness_frame,
            text="Set Credentials",
            command=self.open_creds_dialog,
        )

    def _host_readiness_for(
        self, service_id: str, cfg: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        plugin = self._plugin_for_service(service_id)
        if not plugin:
            return {
                "level": "error",
                "message": f"Host unavailable: {service_id or 'None selected'}.",
                "action_required": False,
            }

        cfg = cfg or {}
        creds = getattr(self, "creds", {})
        missing_required = []
        for credential in plugin.metadata.get("credentials", []):
            if not credential.get("required"):
                continue
            key = credential.get("key", "")
            if not str(creds.get(key, "") or "").strip():
                missing_required.append(credential.get("label", key))

        if missing_required:
            missing_text = ", ".join(missing_required)
            return {
                "level": "error",
                "message": f"{plugin.name} needs {missing_text} before upload.",
                "action_required": True,
            }

        if plugin.id == "imgur.com":
            has_client_id = bool(str(creds.get("imgur_client_id", "") or "").strip())
            has_token = bool(str(creds.get("imgur_access_token", "") or "").strip())
            if not has_client_id and not has_token:
                return {
                    "level": "error",
                    "message": "Imgur needs a Client ID or Access Token before upload.",
                    "action_required": True,
                }

        auto_gallery = cfg.get("auto_gallery")
        if auto_gallery is None and hasattr(self, "var_auto_gallery"):
            auto_gallery = self.var_auto_gallery.get()
        if plugin.id == "imx.to" and auto_gallery:
            has_gallery_login = all(
                str(creds.get(key, "") or "").strip() for key in ("imx_user", "imx_pass")
            )
            if not has_gallery_login:
                return {
                    "level": "error",
                    "message": "IMX.to needs username and password for One Gallery Per Folder.",
                    "action_required": True,
                }
        if plugin.id == "imagebam.com" and auto_gallery:
            has_gallery_login = all(
                str(creds.get(key, "") or "").strip()
                for key in ("imagebam_user", "imagebam_pass")
            )
            if not has_gallery_login:
                return {
                    "level": "error",
                    "message": "ImageBam needs username and password for One Gallery Per Folder.",
                    "action_required": True,
                }

        credentials = plugin.metadata.get("credentials", [])
        optional_credentials = [item for item in credentials if not item.get("required")]
        configured_optional = [
            item
            for item in optional_credentials
            if str(creds.get(item.get("key", ""), "") or "").strip()
        ]
        auth_mode = plugin.metadata.get("features", {}).get("authentication")

        if not credentials or auth_mode == "none":
            message = f"{plugin.name} ready - no account required."
        elif optional_credentials and configured_optional:
            message = f"{plugin.name} ready with saved credentials."
        elif optional_credentials:
            message = f"{plugin.name} ready - login optional."
        else:
            message = f"{plugin.name} ready."

        return {
            "level": "ready",
            "message": message,
            "action_required": False,
        }

    def _refresh_host_readiness(self) -> None:
        if "lbl_host_readiness" not in self.__dict__:
            return

        service_id = self.var_service.get() if hasattr(self, "var_service") else ""
        readiness = self._host_readiness_for(service_id)
        colors = {
            "ready": "#34C759",
            "warning": "#FFB340",
            "error": "#FF3B30",
        }
        self.lbl_host_readiness.configure(
            text=readiness["message"],
            text_color=colors.get(readiness.get("level"), "gray"),
        )

        if readiness.get("action_required"):
            if not self.btn_host_credentials.winfo_ismapped():
                self.btn_host_credentials.pack(fill="x", padx=8, pady=(0, 8))
        elif self.btn_host_credentials.winfo_ismapped():
            self.btn_host_credentials.pack_forget()
        self._refresh_start_button_state(readiness)

    def _pending_upload_count(self) -> int:
        with self.lock:
            return sum(
                1 for data in self.file_widgets.values() if data.get("state") == "pending"
            )

    def _configure_start_button(self, text: str, state: str, active: bool = False) -> None:
        if "btn_start" not in self.__dict__:
            return

        if active:
            self.btn_start.configure(
                text=text,
                state=state,
                fg_color="#1F6AA5",
                hover_color="#144870",
                text_color="white",
            )
        else:
            self.btn_start.configure(
                text=text,
                state=state,
                fg_color="#5A5A5A",
                hover_color="#5A5A5A",
                text_color="#D0D0D0",
            )

    def _configure_stop_button(self, active: bool) -> None:
        if "btn_stop" not in self.__dict__:
            return

        if active:
            self.btn_stop.configure(
                state="normal",
                fg_color="#FF3B30",
                hover_color="#D63028",
                text_color="white",
            )
        else:
            self.btn_stop.configure(
                state="disabled",
                fg_color="#5A5A5A",
                hover_color="#5A5A5A",
                text_color="#D0D0D0",
            )

    def _refresh_start_button_state(self, readiness: Optional[Dict[str, Any]] = None) -> None:
        if "btn_start" not in self.__dict__:
            return

        if getattr(self, "is_uploading", False):
            self._configure_start_button("Uploading...", "disabled")
            self._configure_stop_button(True)
            return

        self._configure_stop_button(False)
        pending_count = self._pending_upload_count()
        if pending_count == 0:
            self._configure_start_button("Start Upload", "disabled")
            return

        if readiness is None:
            service_id = self.var_service.get() if hasattr(self, "var_service") else ""
            readiness = self._host_readiness_for(service_id)

        if readiness.get("action_required") or readiness.get("level") == "error":
            self._configure_start_button("Fix Host Settings", "disabled")
            return

        self._configure_start_button(f"Start Upload ({pending_count})", "normal", active=True)

    def _swap_service_frame(self, service_name):
        for frame in self.service_frames.values():
            frame.pack_forget()
        if service_name in self.service_frames:
            self.service_frames[service_name].pack(fill="both", expand=True, padx=5, pady=5)
        self._refresh_host_readiness()

    def _apply_settings(self):
        s = self.settings
        selected_galleries = s.get("selected_gallery_by_service", {})
        self.selected_gallery_by_service = (
            dict(selected_galleries) if isinstance(selected_galleries, dict) else {}
        )

        self._set_bounded_var(
            self.var_global_worker_count,
            s.get("global_worker_count", config.DEFAULT_WORKER_COUNT),
            config.DEFAULT_WORKER_COUNT,
            config.MIN_WORKER_COUNT,
            config.MAX_WORKER_COUNT,
        )

        self._set_bounded_var(
            self.var_imx_threads,
            s.get("imx_threads", config.DEFAULT_THREAD_COUNT),
            config.DEFAULT_THREAD_COUNT,
            config.MIN_THREAD_COUNT,
            config.MAX_THREAD_COUNT,
        )
        self._set_bounded_var(
            self.menu_thread_var,
            s.get("global_thread_limit", config.DEFAULT_THREAD_COUNT),
            config.DEFAULT_THREAD_COUNT,
            config.MIN_THREAD_COUNT,
            config.MAX_THREAD_COUNT,
        )
        self._last_global_thread_limit_value = self.menu_thread_var.get()

        self._set_bounded_var(
            self.var_pix_threads,
            s.get("pix_threads", 3),
            3,
            config.MIN_THREAD_COUNT,
            config.MAX_THREAD_COUNT,
        )

        self._set_bounded_var(
            self.var_turbo_threads,
            s.get("turbo_threads", 2),
            2,
            config.MIN_THREAD_COUNT,
            config.MAX_THREAD_COUNT,
        )

        self._set_bounded_var(
            self.var_vipr_threads,
            s.get("vipr_threads", 1),
            1,
            config.MIN_THREAD_COUNT,
            config.MAX_THREAD_COUNT,
        )

        self._set_bounded_var(
            self.var_ib_threads,
            s.get("imagebam_threads", 2),
            2,
            config.MIN_THREAD_COUNT,
            config.MAX_THREAD_COUNT,
        )
        if hasattr(self, "var_imgur_threads"):
            self._set_bounded_var(
                self.var_imgur_threads,
                s.get("imgur_threads", 2),
                2,
                config.MIN_THREAD_COUNT,
                config.MAX_THREAD_COUNT,
            )

        self.var_auto_copy.set(s.get("auto_copy", False))
        if hasattr(self, "var_confirm_before_posting"):
            self.var_confirm_before_posting.set(s.get("confirm_before_posting", False))
        self.var_auto_gallery.set(s.get("auto_gallery", False))
        self.var_show_previews.set(s.get("show_previews", True))
        self.var_separate_batches.set(s.get("separate_batches", False))

        mode = s.get("appearance_mode", "System")
        self.var_appearance_mode.set(mode)
        ctk.set_appearance_mode(mode)

        available_services = list(getattr(self, "service_frames", {}).keys())
        fallback_service = (
            "pixhost.to"
            if "pixhost.to" in available_services
            else (available_services[0] if available_services else "imx.to")
        )
        saved_service = s.get("service", fallback_service)
        if saved_service not in available_services:
            logger.warning(
                f"Saved service '{saved_service}' is not available; using '{fallback_service}'"
            )
            saved_service = fallback_service
        self.var_service.set(saved_service)
        self._swap_service_frame(saved_service)

    def _safe_int(self, value, default=2):
        try:
            return int(value)
        except (ValueError, TypeError) as e:
            logger.debug(f"Could not convert '{value}' to int, using default {default}: {e}")
            return default

    @staticmethod
    def _service_thread_var_specs():
        return (
            ("imx_threads", "var_imx_threads", config.DEFAULT_THREAD_COUNT),
            ("pix_threads", "var_pix_threads", 3),
            ("turbo_threads", "var_turbo_threads", 2),
            ("vipr_threads", "var_vipr_threads", 1),
            ("imagebam_threads", "var_ib_threads", 2),
            ("imgur_threads", "var_imgur_threads", 2),
        )

    def _bounded_int(self, value, default, minimum, maximum):
        number = self._safe_int(value, default)
        return max(minimum, min(maximum, number))

    def _set_bounded_var(self, variable, value, default, minimum, maximum):
        bounded = self._bounded_int(value, default, minimum, maximum)
        try:
            variable.set(bounded)
        except Exception as e:
            logger.debug(f"Could not set bounded UI value '{bounded}': {e}")
        return bounded

    def _gather_settings(self) -> Dict[str, Any]:
        selected_service = self.var_service.get()
        worker_count = self._set_bounded_var(
            self.var_global_worker_count,
            self.var_global_worker_count.get(),
            config.DEFAULT_WORKER_COUNT,
            config.MIN_WORKER_COUNT,
            config.MAX_WORKER_COUNT,
        )
        global_thread_limit = self._set_bounded_var(
            self.menu_thread_var,
            self.menu_thread_var.get(),
            config.DEFAULT_THREAD_COUNT,
            config.MIN_THREAD_COUNT,
            config.MAX_THREAD_COUNT,
        )
        if global_thread_limit != getattr(
            self, "_last_global_thread_limit_value", global_thread_limit
        ):
            self.set_global_threads(global_thread_limit)

        service_thread_settings = {}
        for key, var_name, default in self._service_thread_var_specs():
            variable = getattr(self, var_name, None)
            value = variable.get() if variable is not None else default
            if variable is not None:
                service_thread_settings[key] = self._set_bounded_var(
                    variable,
                    value,
                    default,
                    config.MIN_THREAD_COUNT,
                    config.MAX_THREAD_COUNT,
                )
            else:
                service_thread_settings[key] = self._bounded_int(
                    value,
                    default,
                    config.MIN_THREAD_COUNT,
                    config.MAX_THREAD_COUNT,
                )

        cfg = {
            "service": selected_service,
            "global_worker_count": worker_count,
            "global_thread_limit": global_thread_limit,
            **service_thread_settings,
            "output_format": self.settings.get("output_format", "BBCode"),
            "auto_copy": self.var_auto_copy.get(),
            "confirm_before_posting": self.var_confirm_before_posting.get(),
            "auto_gallery": self.var_auto_gallery.get(),
            "show_previews": self.var_show_previews.get(),
            "separate_batches": self.var_separate_batches.get(),
            "appearance_mode": self.var_appearance_mode.get(),
        }

        settings_view = self.__dict__.get("settings_view")
        if settings_view is None:
            cfg["selected_gallery_by_service"] = dict(
                self.__dict__.get("selected_gallery_by_service", {}) or {}
            )
            selected_gallery = self._selected_gallery_for_service(selected_service, cfg)
            if selected_gallery:
                cfg.update(
                    {
                        "selected_gallery_id": selected_gallery.get("id", ""),
                        "selected_gallery_name": selected_gallery.get("name", ""),
                        "selected_gallery_url": selected_gallery.get("url", ""),
                        "selected_gallery_upload_hash": selected_gallery.get("upload_hash", ""),
                    }
                )
            return cfg

        for service_id, raw_config in settings_view.get_all_raw_configs().items():
            cfg.update(settings_view.alias_config(service_id, raw_config))

        selected_config = settings_view.get_validated_config(selected_service)
        cfg.update(selected_config)
        cfg.update(settings_view.alias_config(selected_service, selected_config))
        cfg["selected_gallery_by_service"] = dict(
            self.__dict__.get("selected_gallery_by_service", {}) or {}
        )
        selected_gallery = self._selected_gallery_for_service(selected_service, cfg)
        if selected_gallery:
            cfg.update(
                {
                    "selected_gallery_id": selected_gallery.get("id", ""),
                    "selected_gallery_name": selected_gallery.get("name", ""),
                    "selected_gallery_url": selected_gallery.get("url", ""),
                    "selected_gallery_upload_hash": selected_gallery.get("upload_hash", ""),
                }
            )
            if selected_service == "pixhost.to" and selected_gallery.get("upload_hash"):
                cfg["gallery_upload_hash"] = selected_gallery["upload_hash"]

        return cfg

    def add_files(self):
        files = filedialog.askopenfilenames()
        if files:
            self._process_files(files)

    def add_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        has_subdirs = False
        try:
            has_subdirs = any(os.path.isdir(os.path.join(folder, d)) for d in os.listdir(folder))
        except OSError as e:
            logger.warning(f"Could not scan folder '{folder}' for subdirectories: {e}")

        if has_subdirs:
            if messagebox.askyesno(
                "Recursive Scan",
                "Do you want to scan recursively for all subfolders containing images?",
            ):
                dirs_to_add = []
                for root, dirs, files in os.walk(folder):
                    if any(f.lower().endswith(file_handler.VALID_EXTENSIONS) for f in files):
                        dirs_to_add.append(root)
                if dirs_to_add:
                    dirs_to_add.sort(key=config.natural_sort_key)
                    self._process_files(dirs_to_add)
                else:
                    messagebox.showinfo("Info", "No folders with supported images found.")
                return

            subdirs = [
                os.path.join(folder, d)
                for d in os.listdir(folder)
                if os.path.isdir(os.path.join(folder, d))
            ]
            if subdirs:
                if messagebox.askyesno(
                    "Batch Add Groups",
                    f"This folder contains {len(subdirs)} immediate subfolders.\nDo you want to add each as a separate group?",
                ):
                    self._process_files(subdirs)
                    files_in_root = [
                        f
                        for f in os.listdir(folder)
                        if os.path.isfile(os.path.join(folder, f))
                        and f.lower().endswith(file_handler.VALID_EXTENSIONS)
                    ]
                    if files_in_root:
                        self._process_files([folder])
                    return
        self._process_files([folder])

    def _process_files(self, inputs, target_group=None):
        """Process dropped or selected files/folders and add them to groups."""
        logger.info(f"📁 Processing {len(inputs)} input(s)...")
        self._set_completion_summary(None)
        self._set_import_checks([])

        # Show processing status to user
        self.lbl_eta.configure(text=f"Processing {len(inputs)} item(s)...")
        self.add_activity(f"Processing {len(inputs)} selected item(s).")
        self.update_idletasks()  # Force UI update

        misc_files = []
        show_previews = self.var_show_previews.get()
        folder_count = 0
        file_count = 0
        rejected_details = []
        empty_folders = []

        try:
            for idx, path in enumerate(inputs, 1):
                path = os.path.normpath(path)
                logger.debug(f"   Processing: {path}")

                if os.path.isdir(path):
                    folder_name = os.path.basename(path.rstrip(os.sep))
                    logger.info(f"   📂 Scanning folder: {folder_name}")

                    # Update status with current folder being scanned
                    self.lbl_eta.configure(
                        text=f"Scanning folder {idx}/{len(inputs)}: {folder_name}..."
                    )
                    self.update_idletasks()  # Force UI update

                    try:
                        files_in_folder = file_handler.get_files_from_directory(path)
                        if files_in_folder:
                            logger.info(f"      ✓ Found {len(files_in_folder)} valid image(s)")
                            files_in_folder.sort(key=config.natural_sort_key)
                            folder_count += 1
                            file_count += len(files_in_folder)

                            if target_group:
                                self.thumb_executor.submit(
                                    self._thumb_worker, files_in_folder, target_group, show_previews
                                )
                            else:
                                grp = self._create_group(folder_name)
                                self.thumb_executor.submit(
                                    self._thumb_worker, files_in_folder, grp, show_previews
                                )
                        else:
                            logger.warning(f"      ⚠ No valid images in folder: {folder_name}")
                            empty_folders.append(folder_name)
                    except Exception as e:
                        logger.error(
                            f"      ✗ Error scanning folder {folder_name}: {e}", exc_info=True
                        )
                        rejected_details.append(f"{folder_name}: could not scan folder ({e})")

                elif os.path.isfile(path):
                    if path.lower().endswith(file_handler.VALID_EXTENSIONS):
                        try:
                            # Validate file size before adding to processing queue
                            file_handler.validate_file_size(path)
                            logger.debug(f"      ✓ Valid image file: {os.path.basename(path)}")
                            misc_files.append(path)
                            file_count += 1
                        except Exception as e:
                            logger.warning(f"      ⚠ Rejected file {os.path.basename(path)}: {e}")
                            rejected_details.append(f"{os.path.basename(path)}: {e}")
                    else:
                        ext = os.path.splitext(path)[1]
                        logger.warning(
                            f"      ⚠ Rejected (invalid extension): {os.path.basename(path)} ({ext})"
                        )
                        rejected_details.append(
                            f"{os.path.basename(path)}: unsupported extension {ext or '(none)'}"
                        )
                else:
                    logger.warning(f"      ⚠ Path does not exist or is not accessible: {path}")
                    rejected_details.append(f"{os.path.basename(path) or path}: not found or inaccessible")

            if misc_files:
                logger.info(f"   📄 Processing {len(misc_files)} miscellaneous file(s)")
                misc_files.sort(key=config.natural_sort_key)
                if target_group:
                    self.thumb_executor.submit(
                        self._thumb_worker, misc_files, target_group, show_previews
                    )
                elif self.var_separate_batches.get():
                    for f in misc_files:
                        grp_name = os.path.basename(f)
                        grp = self._create_group(grp_name)
                        self.thumb_executor.submit(self._thumb_worker, [f], grp, show_previews)
                else:
                    misc_group = next((g for g in self.groups if g.title == "Miscellaneous"), None)
                    if not misc_group:
                        misc_group = self._create_group("Miscellaneous")
                    self.thumb_executor.submit(
                        self._thumb_worker, misc_files, misc_group, show_previews
                    )

            # Provide user feedback
            if file_count == 0:
                logger.warning("⚠ No valid files were processed from the drop")
                self._notify_no_valid_files(empty_folders, rejected_details)
            else:
                logger.info(
                    f"✓ Successfully processed {file_count} file(s) from {folder_count} folder(s)"
                )
                status_msg = f"Added {file_count} file(s) from {folder_count} folder(s)"
                rejected_count = len(rejected_details)
                if rejected_count > 0:
                    logger.info(f"   ({rejected_count} file(s) rejected)")
                    status_msg += f" ({rejected_count} rejected)"
                self._set_import_checks([])

                # Show loading message for large batches
                if file_count > 100:
                    status_msg += " - Loading thumbnails..."
                    logger.info(f"Loading thumbnails for {file_count} files (this may take a moment)...")

                self.lbl_eta.configure(text=status_msg)
                self.add_activity(status_msg, "success")

        except Exception as e:
            logger.error(f"✗ Error in _process_files: {e}", exc_info=True)
            self.lbl_eta.configure(text="Error processing files")
            self.add_activity(f"Error processing files: {e}", "error")
            messagebox.showerror(
                "Processing Error", f"An error occurred while processing files:\n\n{str(e)}"
            )

    def _notify_no_valid_files(self, empty_folders: List[str], rejected_details: List[str]) -> None:
        supported = ", ".join(file_handler.VALID_EXTENSIONS)
        issues = [f"No valid image files found. Supported formats: {supported}."]

        if empty_folders:
            shown_folders = empty_folders[:4]
            folder_text = ", ".join(shown_folders)
            if len(empty_folders) > len(shown_folders):
                folder_text += f", and {len(empty_folders) - len(shown_folders)} more"
            issues.append(f"Empty folders: {folder_text}")

        if rejected_details:
            issues.append(f"Rejected files: {len(rejected_details)}")
            issues.extend(rejected_details[:4])
            remaining = len(rejected_details) - 4
            if remaining > 0:
                issues.append(f"...and {remaining} more rejected file(s).")

        self.lbl_eta.configure(text="No valid image files found.")
        self._set_import_checks(issues)
        self.add_activity("No valid image files found. Check Import Checks for details.", "warning")

    def _create_group(self, title):
        t_names = list(self.saved_threads_data.keys()) if self.saved_threads_data else []
        tpl_names = self.template_mgr.get_all_keys()
        default_tpl = self.settings.get("output_format", "BBCode")
        group = CollapsibleGroupFrame(
            self.list_container,
            title=title,
            thread_names=t_names,
            template_names=tpl_names,
            default_template=default_tpl,
            post_preview_callback=self.preview_vipergirls_post,
        )
        group.pack(fill="x", pady=2, padx=2)
        group.batch_index = self.group_counter
        self.group_counter += 1
        self.groups.append(group)
        self._refresh_queue_state()

        def bind_header(w):
            w.bind("<Button-1>", lambda e, g=group: self._on_group_drag_start(e, g))
            w.bind("<B1-Motion>", self._on_group_drag_motion)
            w.bind("<ButtonRelease-1>", self._on_group_drag_end)
            w.bind("<Button-3>", lambda e, g=group: self._show_group_context(e, g))
            w.bind("<Button-2>", lambda e, g=group: self._show_group_context(e, g))

        bind_header(group.header)
        for child in group.header.winfo_children():
            if isinstance(child, (ctk.CTkLabel, tk.Label)):
                bind_header(child)
        return group

    def _thumb_worker(self, files, group_widget, show_previews):
        for idx, f in enumerate(files, 1):
            with self.lock:
                if f in self.file_widgets:
                    logger.debug(f"File already in widgets, skipping: {f}")
                    continue
            pil_image = None
            if show_previews:
                try:
                    pil_image = file_handler.generate_thumbnail(f)
                except Exception as e:
                    logger.debug(f"Thumbnail generation failed for {os.path.basename(f)}: {e}")
                    pil_image = None
            try:
                self.ui_queue.put(("add", f, pil_image, group_widget, show_previews), timeout=5.0)
            except queue.Full:
                logger.warning(f"UI queue full, skipping thumbnail for {os.path.basename(f)}")
                # Still add the file without thumbnail
                self.ui_queue.put(("add", f, None, group_widget, show_previews), timeout=5.0)
            time.sleep(0.001)

    def _increment_firebase_counter(self) -> None:
        """Increment the global upload counter on Firebase."""
        url = "https://conniesuploader-default-rtdb.firebaseio.com/upload_count.json"
        try:
            import requests
            resp = requests.get(url, timeout=5)
            count = resp.json()
            if not isinstance(count, int):
                count = 0
            count += 1
            requests.put(url, json=count, timeout=5)
        except Exception as e:
            logger.debug(f"Failed to increment Firebase counter: {e}")

    def start_upload(self) -> None:
        pending_by_group = {}
        for grp in self.groups:
            for fp in grp.files:
                with self.lock:
                    if self.file_widgets[fp]["state"] == "pending":
                        if grp not in pending_by_group:
                            pending_by_group[grp] = []
                        pending_by_group[grp].append(fp)

        if not pending_by_group:
            self._notify_no_pending_upload()
            return

        self._set_completion_summary(None)
        try:
            cfg = self._gather_settings()
            cfg["api_key"] = self.creds.get("imx_api", "")

            # Apply worker count setting (will restart sidecar if changed)
            from modules.sidecar import SidecarBridge

            SidecarBridge.set_worker_count(cfg.get("global_worker_count", 8))

            upload_cfg = cfg.copy()

            # When worker count is 1, force the runtime thread limit to 1 for true sequential uploads.
            if cfg.get("global_worker_count") == 1:
                upload_cfg["global_thread_limit"] = 1
                upload_cfg["threads"] = 1

            preflight_issues, ready_message = self._run_upload_preflight(
                pending_by_group, upload_cfg
            )
            if preflight_issues:
                self._handle_preflight_issues(preflight_issues)
                return

            if upload_cfg.get("confirm_before_posting") and self._selected_vipergirls_posting_targets(
                pending_by_group
            ):
                if not self._confirm_vipergirls_posts(pending_by_group, upload_cfg):
                    self.add_activity("Upload cancelled before ViperGirls posting.", "warning")
                    self._refresh_start_button_state()
                    return

            self._set_upload_checks([])
            self.settings = cfg
            self.settings_mgr.save(cfg)
            self.add_activity(ready_message, "success")
            for detail in getattr(self, "preflight_detail_lines", [])[:6]:
                self.add_activity(detail)

            self.cancel_event.clear()
            self.results = []
            self.result_queue = queue.Queue(maxsize=1000)
            self.upload_manager.result_queue = self.result_queue

            self.pix_galleries_to_finalize = []
            self.clipboard_buffer = []
            self._register_selected_pixhost_galleries_for_finalization(pending_by_group, upload_cfg)

            self._configure_start_button("Uploading...", "disabled")
            self._configure_stop_button(True)
            self.lbl_eta.configure(text=ready_message)

            self.overall_progress.set(0)
            try:
                self.overall_progress.configure(progress_color=["#3B8ED0", "#1F6AA5"])
            except (tk.TclError, TypeError) as e:
                logger.debug(f"Could not set gradient progress color, using solid: {e}")
                self.overall_progress.configure(progress_color="blue")

            self.upload_total = sum(len(v) for v in pending_by_group.values())
            self.upload_count = 0
            self.is_uploading = True
            self._refresh_start_button_state()

            for files in pending_by_group.values():
                for fp in files:
                    with self.lock:
                        row_data = self.file_widgets[fp]
                        row_data["state"] = "queued"
                        self._set_row_error(row_data, "")
                        row_data["status"].configure(text="Queued")
                        row_data["prog"].set(0)
                        self._set_row_progress_color(row_data, ["#3B8ED0", "#1F6AA5"])
                        self._set_row_retry_visible(row_data, False)
                        if row_data.get("remove"):
                            row_data["remove"].configure(state="disabled")
            self.add_activity(f"Queued {self.upload_total} file(s) for upload.")

            # Reset and prepare AutoPoster
            self.auto_poster.reset()
            self.saved_threads_data = viper_api.load_saved_threads()
            self.auto_poster.saved_threads_data = self.saved_threads_data

            sorted_groups = sorted(
                self.groups,
                key=lambda g: (
                    self.list_container.winfo_children().index(g)
                    if g in self.list_container.winfo_children()
                    else 999
                ),
            )
            for i, grp in enumerate(sorted_groups):
                grp.batch_index = i

            # Check if any groups have auto-posting enabled
            active_post_jobs = False
            for grp in pending_by_group.keys():
                if grp.selected_thread and grp.selected_thread != "Do Not Post":
                    active_post_jobs = True
                    break

            # Start AutoPoster if needed
            if active_post_jobs:
                self.add_activity("Auto-posting will start after output is generated.")
                self.auto_poster.start_processing(
                    is_uploading_callback=lambda: self.is_uploading, cancel_event=self.cancel_event
                )

            # Increment the global Firebase counter asynchronously
            threading.Thread(target=self._increment_firebase_counter, daemon=True).start()

            self.upload_manager.start_batch(pending_by_group, upload_cfg, self.creds)

        except Exception as e:
            if hasattr(e, "errors"):
                self._handle_preflight_issues([str(error) for error in e.errors])
            else:
                messagebox.showerror("Error starting upload", str(e))
            self._refresh_start_button_state()

    def _notify_no_pending_upload(self) -> None:
        message = "No pending files to upload. Add files or retry failed items."
        self._set_upload_checks([])
        self.lbl_eta.configure(text=message)
        self.add_activity(message, "warning")
        self._refresh_start_button_state()

    def _run_upload_preflight(
        self, pending_by_group: Dict[Any, List[str]], cfg: Dict[str, Any]
    ) -> Tuple[List[str], str]:
        """Validate upload readiness before any files are queued."""
        issues: List[str] = []
        self._reset_preflight_actions()
        self.preflight_detail_lines = []
        service_id = cfg.get("service", "")
        plugin = self._plugin_for_service(service_id)
        file_count = sum(len(files) for files in pending_by_group.values())
        gallery_summary = ""

        if not plugin:
            issues.append(f"Selected image host is not available: {service_id or 'None'}")
            plugin_name = service_id or "Image host"
        else:
            plugin_name = plugin.name
            self._preflight_check_credentials(plugin, cfg, issues)
            self._preflight_check_files(plugin, pending_by_group, issues)
            self._preflight_check_sidecar(plugin, issues)
            gallery_summary = self._preflight_check_galleries(
                plugin, pending_by_group, cfg, issues
            )

        self._preflight_check_vipergirls_posting(pending_by_group, issues)
        self._preflight_check_output_locations(issues)

        if issues:
            return issues, ""

        batch_count = len(pending_by_group)
        file_label = "file" if file_count == 1 else "files"
        batch_label = "batch" if batch_count == 1 else "batches"
        copy_status = (
            "Output will copy to clipboard."
            if cfg.get("auto_copy")
            else "Output will be saved when uploads finish."
        )
        summary = (
            f"{plugin_name} ready - {file_count} {file_label} "
            f"in {batch_count} {batch_label}. {copy_status}"
        )
        if gallery_summary:
            summary = f"{summary} {gallery_summary}"
        return [], summary

    def _plugin_for_service(self, service_id):
        plugin = getattr(self, "service_plugins", {}).get(service_id)
        if plugin:
            return plugin
        plugin_manager = getattr(self, "plugin_manager", None)
        if plugin_manager:
            return plugin_manager.get_plugin(service_id)
        return None

    def _preflight_check_credentials(self, plugin, cfg: Dict[str, Any], issues: List[str]) -> None:
        credentials = plugin.metadata.get("credentials", [])
        for credential in credentials:
            if not credential.get("required"):
                continue
            key = credential.get("key", "")
            value = str(self.creds.get(key, "") or "").strip()
            if not value:
                label = credential.get("label", key)
                issues.append(f"{plugin.name} requires {label}. Set it in Tools > Set Credentials.")

        if plugin.id == "imgur.com":
            has_client_id = bool(str(self.creds.get("imgur_client_id", "") or "").strip())
            has_token = bool(str(self.creds.get("imgur_access_token", "") or "").strip())
            if not has_client_id and not has_token:
                issues.append(
                    "Imgur requires a Client ID or Access Token. Set it in Tools > Set Credentials."
                )

        if plugin.id == "imx.to" and cfg.get("auto_gallery"):
            has_gallery_login = all(
                str(self.creds.get(key, "") or "").strip() for key in ("imx_user", "imx_pass")
            )
            if not has_gallery_login:
                issues.append(
                    "One Gallery Per Folder for IMX.to requires IMX username and password."
                )

        if plugin.id == "imagebam.com" and cfg.get("auto_gallery"):
            has_gallery_login = all(
                str(self.creds.get(key, "") or "").strip()
                for key in ("imagebam_user", "imagebam_pass")
            )
            if not has_gallery_login:
                issues.append(
                    "One Gallery Per Folder for ImageBam requires ImageBam username and password."
                )

    def _preflight_check_files(
        self,
        plugin,
        pending_by_group: Dict[Any, List[str]],
        issues: List[str],
    ) -> None:
        limits = plugin.metadata.get("limits", {})
        allowed = tuple(
            str(ext).lower()
            for ext in limits.get("allowed_formats", file_handler.VALID_EXTENSIONS)
        )
        max_size = int(limits.get("max_file_size", config.MAX_FILE_SIZE))

        invalid_files: List[str] = []
        invalid_file_paths: List[str] = []
        for files in pending_by_group.values():
            for file_path in files:
                name = os.path.basename(file_path)
                try:
                    if not os.path.isfile(file_path):
                        raise ValueError("file is missing or not accessible")
                    if allowed and not file_path.lower().endswith(allowed):
                        raise ValueError(f"not supported by {plugin.name}")
                    file_handler.validate_file_size(file_path, max_size)
                except Exception as exc:
                    invalid_files.append(f"{name}: {exc}")
                    invalid_file_paths.append(file_path)

        if invalid_files:
            file_issue_texts = ["Some queued files are not ready:"]
            file_issue_texts.extend(invalid_files[:5])
            remaining = len(invalid_files) - 5
            if remaining > 0:
                file_issue_texts.append(f"...and {remaining} more file issue(s).")
            issues.extend(file_issue_texts)
            self.preflight_action_files = invalid_file_paths
            self.preflight_action_file_issue_texts = file_issue_texts

    def _preflight_check_sidecar(self, plugin, issues: List[str]) -> None:
        if plugin.metadata.get("implementation") != "go":
            return

        bridge = getattr(getattr(self, "upload_manager", None), "bridge", None)
        if bridge is None:
            from modules.sidecar import SidecarBridge

            bridge = SidecarBridge.get()

        if bridge.is_process_alive():
            return

        started = False
        start_process = getattr(bridge, "_start_process", None)
        if callable(start_process):
            started = bool(start_process())

        if not started and not bridge.is_process_alive():
            issues.append(
                "Upload engine is not running. Run build_uploader.bat to rebuild the bundled sidecar."
            )

    def _preflight_check_galleries(
        self,
        plugin,
        pending_by_group: Dict[Any, List[str]],
        cfg: Dict[str, Any],
        issues: List[str],
    ) -> str:
        service_id = plugin.id
        if cfg.get("auto_gallery"):
            return self._preflight_check_auto_galleries(plugin, pending_by_group, issues)

        gallery_details = []
        seen = set()
        for group in pending_by_group.keys():
            batch_name = self._batch_display_name(group)
            gallery = self._gallery_for_group(group, service_id, cfg)
            if not gallery:
                continue

            gallery_service = gallery.get("service") or service_id
            gallery_id = gallery.get("id", "")
            detail = self._format_gallery_preflight_detail(batch_name, gallery)
            if detail not in seen:
                gallery_details.append(detail)
                seen.add(detail)

            if gallery_service != service_id:
                issues.append(
                    f'Gallery "{gallery.get("name", gallery_id)}" selected for "{batch_name}" '
                    f"belongs to {gallery_service}, but the current upload host is {service_id}."
                )
                continue

            if not self._gallery_id_is_valid_for_service(service_id, gallery_id):
                label = self._gallery_label_for_service(service_id)
                issues.append(
                    f'Gallery selected for "{batch_name}" has an invalid {label}: {gallery_id}.'
                )

            if service_id == "vipr.im":
                selected_name = str(cfg.get("vipr_gallery_name") or "").strip()
                if selected_name and selected_name != "None" and not gallery_id:
                    issues.append(
                        f'Vipr gallery "{selected_name}" could not be matched to an upload ID. '
                        "Refresh galleries or select it again."
                    )

        self.preflight_detail_lines.extend(gallery_details[:6])
        if len(gallery_details) > 6:
            self.preflight_detail_lines.append(
                f"...and {len(gallery_details) - 6} more gallery assignment(s)."
            )

        if len(gallery_details) == 1:
            return gallery_details[0]
        if len(gallery_details) > 1:
            return f"{len(gallery_details)} batch gallery assignments are selected."
        return ""

    def _preflight_check_auto_galleries(
        self,
        plugin,
        pending_by_group: Dict[Any, List[str]],
        issues: List[str],
    ) -> str:
        supported = {"imx.to", "pixhost.to", "turboimagehost", "vipr.im", "imagebam.com"}
        if plugin.id not in supported:
            issues.append(
                f"One Gallery Per Folder is not implemented for {plugin.name}. "
                "Turn it off or choose IMX.to/Pixhost.to/Vipr/ImageBam."
            )
            return ""

        batch_names = [self._batch_display_name(group) for group in pending_by_group.keys()]
        if not batch_names:
            return ""

        preview_names = ", ".join(batch_names[:5])
        if len(batch_names) > 5:
            preview_names = f"{preview_names}, ...and {len(batch_names) - 5} more"
        gallery_label = "gallery" if len(batch_names) == 1 else "galleries"
        detail = (
            f"One Gallery Per Folder will create {len(batch_names)} {plugin.name} {gallery_label} "
            f"before upload: {preview_names}."
        )
        self.preflight_detail_lines.append(detail)
        return detail

    def _format_gallery_preflight_detail(self, batch_name: str, gallery: Dict[str, str]) -> str:
        gallery_id = gallery.get("id", "")
        gallery_name = gallery.get("name") or gallery_id
        url = gallery.get("url", "")
        suffix = f" ({url})" if url else ""
        return f'Selected gallery for "{batch_name}": {gallery_name} ({gallery_id}).{suffix}'

    def _register_selected_pixhost_galleries_for_finalization(
        self, pending_by_group: Dict[Any, List[str]], cfg: Dict[str, Any]
    ) -> None:
        if cfg.get("service") != "pixhost.to":
            return

        for group in pending_by_group.keys():
            gallery = self._gallery_for_group(group, "pixhost.to", cfg)
            if not gallery or not gallery.get("upload_hash"):
                continue
            self._register_pixhost_gallery_for_finalization(
                {
                    "gallery_hash": gallery["id"],
                    "gallery_upload_hash": gallery["upload_hash"],
                    "gallery_url": gallery.get("url", ""),
                    "gallery_name": gallery.get("name", ""),
                }
            )

    def _register_pixhost_gallery_for_finalization(self, gallery: Dict[str, Any]) -> bool:
        gallery_hash = str(gallery.get("gallery_hash") or "").strip()
        upload_hash = str(gallery.get("gallery_upload_hash") or "").strip()
        if not gallery_hash or not upload_hash:
            return False

        for existing in self.__dict__.get("pix_galleries_to_finalize", []):
            if (
                str(existing.get("gallery_hash") or "") == gallery_hash
                and str(existing.get("gallery_upload_hash") or "") == upload_hash
            ):
                return False

        self.__dict__.setdefault("pix_galleries_to_finalize", []).append(gallery)
        return True

    def _selected_vipergirls_posting_targets(
        self, pending_by_group: Dict[Any, List[str]]
    ) -> List[Tuple[Any, str, str]]:
        selections: List[Tuple[Any, str, str]] = []
        for group in pending_by_group.keys():
            target_name = str(getattr(group, "selected_thread", "") or "").strip()
            if not target_name or target_name == "Do Not Post":
                continue
            selections.append((group, self._batch_display_name(group), target_name))
        return selections

    def _batch_display_name(self, group: Any) -> str:
        title = str(getattr(group, "title", "") or "").strip()
        if title:
            return title

        batch_index = getattr(group, "batch_index", None)
        if isinstance(batch_index, int):
            return f"Batch {batch_index + 1}"
        return "Batch"

    def _selected_gallery_for_service(
        self, service_id: str, cfg: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, str]]:
        selected = self.__dict__.get("selected_gallery_by_service", {}) or {}
        record = selected.get(service_id) if isinstance(selected, dict) else None
        if not isinstance(record, dict):
            cfg = cfg or {}
            selected_by_service = cfg.get("selected_gallery_by_service", {})
            if isinstance(selected_by_service, dict):
                record = selected_by_service.get(service_id)
        if not isinstance(record, dict):
            return None

        gallery_id = str(record.get("id") or "").strip()
        if not gallery_id:
            return None
        return {
            "service": str(record.get("service") or service_id),
            "id": gallery_id,
            "name": str(record.get("name") or gallery_id),
            "url": str(record.get("url") or gallery_url_for_service(service_id, gallery_id)),
            "upload_hash": str(record.get("upload_hash") or ""),
        }

    def _gallery_id_from_settings(self, service_id: str, cfg: Dict[str, Any]) -> str:
        if service_id == "pixhost.to":
            return str(cfg.get("gallery_hash") or cfg.get("pix_gallery_hash") or "").strip()
        if service_id == "vipr.im":
            gallery_name = str(cfg.get("vipr_gallery_name") or "").strip()
            if not gallery_name or gallery_name == "None":
                return ""
            mapped_id = str(
                cfg.get("vipr_gal_id")
                or self.__dict__.get("vipr_galleries_map", {}).get(gallery_name)
                or ""
            ).strip()
            return "" if mapped_id == "0" else mapped_id
        if service_id == "imx.to":
            return str(cfg.get("gallery_id") or cfg.get("imx_gallery_id") or "").strip()
        return str(cfg.get("gallery_id") or cfg.get("turbo_gallery_id") or "").strip()

    def _gallery_for_group(
        self, group: Any, service_id: str, cfg: Dict[str, Any]
    ) -> Optional[Dict[str, str]]:
        group_gallery_id = str(getattr(group, "gallery_id", "") or "").strip()
        group_gallery_url = str(getattr(group, "gallery_url", "") or "").strip()
        if group_gallery_id or group_gallery_url:
            group_service = str(getattr(group, "gallery_service", "") or service_id).strip()
            if not group_gallery_id:
                group_gallery_id = self._gallery_id_from_url(group_service, group_gallery_url)
            return {
                "service": group_service,
                "id": group_gallery_id,
                "name": str(getattr(group, "gallery_name", "") or ""),
                "url": str(
                    group_gallery_url or gallery_url_for_service(group_service, group_gallery_id)
                ),
                "upload_hash": str(getattr(group, "gallery_upload_hash", "") or ""),
            }

        selected = self._selected_gallery_for_service(service_id, cfg)
        if selected:
            return selected

        gallery_id = self._gallery_id_from_settings(service_id, cfg)
        if not gallery_id:
            return None

        gallery_name = str(cfg.get("selected_gallery_name") or "").strip()
        if service_id == "vipr.im":
            gallery_name = str(cfg.get("vipr_gallery_name") or gallery_name).strip()
        return {
            "service": service_id,
            "id": gallery_id,
            "name": gallery_name,
            "url": str(cfg.get("selected_gallery_url") or gallery_url_for_service(service_id, gallery_id)),
            "upload_hash": str(cfg.get("selected_gallery_upload_hash") or ""),
        }

    @staticmethod
    def _gallery_id_from_url(service_id: str, gallery_url: str) -> str:
        if service_id == "turboimagehost" and "/album/" in gallery_url:
            return gallery_url.split("/album/", 1)[1].split("/", 1)[0].strip()
        if service_id == "imagebam.com" and "/view/" in gallery_url:
            return gallery_url.split("/view/", 1)[1].split("/", 1)[0].strip()
        if service_id == "pixhost.to":
            for marker in ("/gallery/", "/galleries/"):
                if marker in gallery_url:
                    return gallery_url.split(marker, 1)[1].split("/", 1)[0].strip()
        return ""

    def _apply_result_gallery_url(self, filepath: str, gallery_url: Any) -> None:
        clean_url = str(gallery_url or "").strip()
        if not clean_url:
            return

        row_data = self.file_widgets.get(filepath, {})
        group = row_data.get("group") if isinstance(row_data, dict) else None
        if group is None:
            return

        service_id = str(getattr(group, "gallery_service", "") or self.settings.get("service", ""))
        if service_id not in {"turboimagehost", "imagebam.com"}:
            return

        old_url = str(getattr(group, "gallery_url", "") or "").strip()
        group.gallery_url = clean_url
        group.gallery_service = service_id
        if not str(getattr(group, "gallery_id", "") or "").strip():
            group.gallery_id = self._gallery_id_from_url(service_id, clean_url)
        if not str(getattr(group, "gallery_name", "") or "").strip():
            group.gallery_name = self._batch_display_name(group)

        if old_url != clean_url:
            label = "Turbo" if service_id == "turboimagehost" else "ImageBam"
            self.add_activity(
                f"{label} gallery URL captured for {self._batch_display_name(group)}.",
                "info",
            )

    def _gallery_name_for_group(self, group: Any, service_id: str, cfg: Dict[str, Any]) -> str:
        gallery = self._gallery_for_group(group, service_id, cfg)
        if gallery and gallery.get("name"):
            return gallery["name"]
        return self._batch_display_name(group)

    def _gallery_id_is_valid_for_service(self, service_id: str, gallery_id: str) -> bool:
        gallery_id = str(gallery_id or "").strip()
        if not gallery_id:
            return True
        if service_id == "imx.to":
            return gallery_id.replace("_", "").isalnum()
        if service_id == "vipr.im":
            return gallery_id.isdigit() or gallery_id.isalnum()
        return gallery_id.isalnum()

    def _gallery_label_for_service(self, service_id: str) -> str:
        if service_id == "pixhost.to":
            return "gallery hash"
        if service_id == "vipr.im":
            return "gallery ID"
        return "gallery ID"

    def _thread_id_from_vipergirls_record(self, record: Any) -> str:
        if isinstance(record, dict):
            thread_id = viper_api.extract_thread_id(str(record.get("thread_id") or ""))
            if thread_id:
                return thread_id
            return viper_api.extract_thread_id(str(record.get("url") or "")) or ""

        return viper_api.extract_thread_id(str(record or "")) or ""

    def _thumbnail_size_for_service(
        self, service_id: str, settings: Optional[Dict[str, Any]] = None
    ) -> str:
        settings = settings or self.settings
        if service_id == "imx.to":
            return str(settings.get("imx_thumb", "180"))
        if service_id == "pixhost.to":
            return str(settings.get("pix_thumb", "200"))
        if service_id == "turboimagehost":
            return str(settings.get("turbo_thumb", "180"))
        if service_id == "vipr.im":
            thumb_size = str(settings.get("vipr_thumb", "170x170"))
            return thumb_size.split("x")[0] if "x" in thumb_size else thumb_size
        if service_id == "imagebam.com":
            return str(settings.get("imagebam_thumb", "180"))
        if service_id == "imgur.com":
            return str(settings.get("imgur_thumb", settings.get("thumbnail_size", "m")))
        return "250"

    def _auto_cover_count_for_current_service(self) -> int:
        service_id = (
            self.var_service.get()
            if hasattr(self, "var_service")
            else str(getattr(self, "settings", {}).get("service", ""))
        )
        settings_view = self.__dict__.get("settings_view")
        if settings_view is not None:
            raw_config = settings_view.get_raw_config(service_id)
            if "cover_count" in raw_config:
                return max(0, min(10, self._safe_int(raw_config.get("cover_count"), 0)))

        variable_names = {
            "imx.to": "var_imx_cover_count",
            "pixhost.to": "var_pix_cover_count",
            "turboimagehost": "var_turbo_cover_count",
            "vipr.im": "var_vipr_cover_count",
        }
        variable = getattr(self, variable_names.get(service_id, ""), None)
        if variable is None:
            return 0
        try:
            value = variable.get()
        except (tk.TclError, AttributeError):
            value = 0
        return max(0, min(10, self._safe_int(value, 0)))

    def _apply_auto_covers_to_group(self, group: Any) -> None:
        auto_select = getattr(group, "auto_select_covers", None)
        if not callable(auto_select):
            return
        auto_select(self._auto_cover_count_for_current_service())
        self._refresh_cover_buttons(group)

    def _cover_files_for_group(self, group: Any) -> List[str]:
        cover_filepaths = getattr(group, "cover_filepaths", None)
        if callable(cover_filepaths):
            return list(cover_filepaths())

        cover_files = getattr(group, "cover_files", [])
        cover_set = set(cover_files or [])
        return [
            filepath
            for filepath in getattr(group, "files", [])
            if filepath in cover_set
        ]

    def _ordered_group_files_for_output(self, group: Any) -> List[str]:
        files = list(getattr(group, "files", []))
        cover_files = self._cover_files_for_group(group)
        if not cover_files:
            return files

        cover_set = set(cover_files)
        return [filepath for filepath in files if filepath in cover_set] + [
            filepath for filepath in files if filepath not in cover_set
        ]

    def _is_cover_file(self, filepath: str, group: Optional[Any] = None) -> bool:
        group = group or self.file_widgets.get(filepath, {}).get("group")
        is_cover_file = getattr(group, "is_cover_file", None)
        if callable(is_cover_file):
            return bool(is_cover_file(filepath))
        return filepath in set(getattr(group, "cover_files", []) or [])

    def _refresh_cover_button(self, filepath: str) -> None:
        with self.lock:
            row_data = self.file_widgets.get(filepath)
        if not row_data:
            return

        group = row_data.get("group")
        is_cover = self._is_cover_file(filepath, group)
        row_data["is_cover"] = is_cover

        cover_var = row_data.get("cover_var")
        if cover_var:
            try:
                cover_var.set(is_cover)
            except (tk.TclError, AttributeError):
                pass

        button = row_data.get("cover")
        if not button:
            return

        try:
            if is_cover:
                button.configure(
                    text="Cover",
                    fg_color="#1F6AA5",
                    hover_color="#144870",
                    border_color="#1F6AA5",
                    text_color="white",
                )
            else:
                button.configure(
                    text="Cover",
                    fg_color="#1F6AA5",
                    hover_color="#666666",
                    border_color="gray",
                    text_color="gray",
                )
        except (tk.TclError, AttributeError):
            return

    def _refresh_cover_buttons(self, group: Any) -> None:
        for filepath in getattr(group, "files", []):
            self._refresh_cover_button(filepath)

    def _set_cover_for_files(self, filepaths: List[str], is_cover: bool) -> None:
        if getattr(self, "is_uploading", False):
            self.add_activity("Wait for the current upload to finish before changing covers.", "warning")
            return

        changed = 0
        touched_groups = set()
        for filepath in filepaths:
            with self.lock:
                row_data = self.file_widgets.get(filepath)
            group = row_data.get("group") if row_data else None
            setter = getattr(group, "set_cover_file", None)
            if not callable(setter):
                continue
            if setter(filepath, is_cover, manual=True):
                changed += 1
            touched_groups.add(group)

        for group in touched_groups:
            self._refresh_cover_buttons(group)

        if not filepaths:
            return
        if changed or len(filepaths) == 1:
            action = "Marked" if is_cover else "Cleared cover mark for"
            count_label = (
                os.path.basename(filepaths[0])
                if len(filepaths) == 1
                else f"{len(filepaths)} images"
            )
            self.add_activity(f"{action} {count_label}.")

    def _toggle_cover_file(self, filepath: str) -> None:
        with self.lock:
            row_data = self.file_widgets.get(filepath)
        group = row_data.get("group") if row_data else None
        self._set_cover_for_files([filepath], not self._is_cover_file(filepath, group))

    def _set_cover_from_toggle(self, filepath: str) -> None:
        with self.lock:
            row_data = self.file_widgets.get(filepath)
        if not row_data:
            return

        cover_var = row_data.get("cover_var")
        is_cover = bool(cover_var.get()) if cover_var else not self._is_cover_file(filepath)
        self._set_cover_for_files([filepath], is_cover)
        self._refresh_cover_button(filepath)

    def _preview_group_results(self, group: Any) -> List[Tuple[str, str, str]]:
        results = []
        for index, file_path in enumerate(self._ordered_group_files_for_output(group), start=1):
            preview_path = str(file_path or "").replace("\\", "/").rstrip("/")
            name = os.path.basename(preview_path) or f"image-{index}"
            safe_name = file_handler.sanitize_filename(os.path.splitext(name)[0]) or f"image-{index}"
            base_url = f"https://preview.invalid/{safe_name}"
            results.append(
                (
                    f"{base_url}/viewer",
                    f"{base_url}/thumb",
                    f"{base_url}/direct",
                )
            )
        return results

    def _vipergirls_post_preview_data(
        self,
        group: Any,
        settings_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        settings = settings_override or self.settings
        target_name = str(getattr(group, "selected_thread", "") or "Do Not Post")
        try:
            saved_threads = object.__getattribute__(self, "saved_threads_data")
        except AttributeError:
            saved_threads = {}
        record = saved_threads.get(target_name, {})
        thread_id = self._thread_id_from_vipergirls_record(record)
        target_url = str(record.get("url") or "") if isinstance(record, dict) else ""
        group_results = self._preview_group_results(group)
        cover_url = group_results[0][1] if group_results else ""
        service_id = settings.get("service", "")
        gallery = self._gallery_for_group(group, service_id, settings) or {}
        gallery_id = str(gallery.get("id") or "")
        gallery_link = str(gallery.get("url") or "")
        gallery_name = str(gallery.get("name") or self._batch_display_name(group))

        ctx = {
            "gallery_link": gallery_link,
            "gallery_name": gallery_name,
            "gallery_id": gallery_id,
            "cover_url": cover_url,
            "cover_count": len(self._cover_files_for_group(group)),
            "thumb_size": self._thumbnail_size_for_service(service_id, settings),
            "batch_name": self._batch_display_name(group),
            "image_count": len(group_results),
            "service": service_id,
            "thread_name": target_name if target_name != "Do Not Post" else "",
            "thread_id": thread_id,
            "upload_date": datetime.now().strftime("%Y-%m-%d"),
        }
        content = ""
        if group_results:
            content = self.template_mgr.apply(
                getattr(group, "selected_template", "BBCode"),
                ctx,
                group_results,
            )

        issues = []
        if target_name == "Do Not Post":
            issues.append("No ViperGirls target is selected for this batch.")
        elif not record:
            issues.append(f'Target "{target_name}" is not saved.')
        elif not thread_id:
            issues.append(f'Target "{target_name}" has no usable thread ID.')
        if not group_results:
            issues.append("This batch does not contain any files to preview.")

        return {
            "batch_name": self._batch_display_name(group),
            "target_name": target_name,
            "thread_id": thread_id,
            "target_url": target_url,
            "content": content,
            "issues": issues,
        }

    def preview_vipergirls_post(self, group: Any) -> None:
        self.saved_threads_data = viper_api.load_saved_threads()
        try:
            auto_poster = object.__getattribute__(self, "auto_poster")
        except AttributeError:
            auto_poster = None
        if auto_poster:
            auto_poster.saved_threads_data = self.saved_threads_data
        preview = self._vipergirls_post_preview_data(group)
        self._show_vipergirls_post_preview_dialog(preview)

    def _show_vipergirls_post_preview_dialog(self, preview: Dict[str, Any]) -> None:
        dlg = ctk.CTkToplevel(self)
        dlg.title("ViperGirls Post Preview")
        dlg.geometry("760x640")
        dlg.minsize(640, 480)
        dlg.resizable(True, True)
        dlg.transient(self)
        dlg.focus_force()

        dlg.grid_columnconfigure(0, weight=1)
        dlg.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            dlg,
            text="ViperGirls Post Preview",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 8))

        details = ctk.CTkFrame(dlg, fg_color="transparent")
        details.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 8))
        details.grid_columnconfigure(1, weight=1)
        detail_rows = (
            ("Batch", preview.get("batch_name", "")),
            ("Target", preview.get("target_name", "")),
            ("Thread ID", preview.get("thread_id") or "Unavailable"),
        )
        for row_index, (label, value) in enumerate(detail_rows):
            ctk.CTkLabel(details, text=f"{label}:", text_color="gray").grid(
                row=row_index, column=0, sticky="w", padx=(0, 8), pady=2
            )
            ctk.CTkLabel(details, text=str(value), anchor="w").grid(
                row=row_index, column=1, sticky="ew", pady=2
            )

        body = ctk.CTkTextbox(dlg, wrap="word")
        body.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 8))
        content = preview.get("content") or "No generated content is available."
        issues = preview.get("issues") or []
        if issues:
            body.insert("end", "Checks:\n")
            for issue in issues:
                body.insert("end", f"- {issue}\n")
            body.insert("end", "\n")
        body.insert("end", content)
        body.configure(state="disabled")

        actions = ctk.CTkFrame(dlg, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", padx=18, pady=(4, 16))
        ctk.CTkButton(
            actions,
            text="Copy Post Text",
            command=lambda: self._copy_text_to_clipboard(
                preview.get("content") or "", "Copied preview post text."
            ),
            width=130,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions,
            text="Open Target",
            command=lambda: self._open_vipergirls_target(preview),
            width=110,
            state="normal" if preview.get("target_url") else "disabled",
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            actions,
            text="Close",
            command=dlg.destroy,
            fg_color="gray",
            hover_color="#666666",
            width=90,
        ).pack(side="right")

    def _open_vipergirls_target(self, preview: Dict[str, Any]) -> None:
        url = str(preview.get("target_url") or "")
        if not url:
            self.add_activity("No ViperGirls target URL is available.", "warning")
            return
        self._open_path(url)

    def _copy_text_to_clipboard(self, text: str, success_message: str) -> bool:
        if not text:
            self.add_activity("No text is available to copy.", "warning")
            return False
        try:
            pyperclip.copy(text)
            self.add_activity(success_message, "success")
            return True
        except (OSError, pyperclip.PyperclipException) as exc:
            logger.warning(f"Could not copy text to clipboard: {exc}")
            self.add_activity("Could not copy text to clipboard.", "warning")
            return False

    def _confirm_vipergirls_posts(
        self,
        pending_by_group: Dict[Any, List[str]],
        settings_override: Optional[Dict[str, Any]] = None,
    ) -> bool:
        previews = [
            self._vipergirls_post_preview_data(group, settings_override)
            for group, _batch_name, _target_name in self._selected_vipergirls_posting_targets(
                pending_by_group
            )
        ]
        if not previews:
            return True

        result = {"ok": False}
        dlg = ctk.CTkToplevel(self)
        dlg.title("Confirm ViperGirls Posting")
        dlg.geometry("820x680")
        dlg.minsize(680, 500)
        dlg.resizable(True, True)
        dlg.transient(self)
        dlg.focus_force()
        dlg.grab_set()
        dlg.grid_columnconfigure(0, weight=1)
        dlg.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            dlg,
            text="Confirm ViperGirls Posting",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 8))

        body = ctk.CTkTextbox(dlg, wrap="word")
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 8))
        for index, preview in enumerate(previews, start=1):
            if index > 1:
                body.insert("end", "\n\n" + ("=" * 72) + "\n\n")
            body.insert("end", f"Batch: {preview['batch_name']}\n")
            body.insert("end", f"Selected thread: {preview['target_name']}\n")
            body.insert("end", f"Thread ID: {preview.get('thread_id') or 'Unavailable'}\n\n")
            body.insert("end", preview.get("content") or "No generated content is available.")
        body.configure(state="disabled")

        actions = ctk.CTkFrame(dlg, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=18, pady=(4, 16))

        def approve() -> None:
            result["ok"] = True
            dlg.destroy()

        ctk.CTkButton(
            actions,
            text="Start Upload and Post",
            command=approve,
            width=155,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions,
            text="Cancel",
            command=dlg.destroy,
            fg_color="gray",
            hover_color="#666666",
            width=90,
        ).pack(side="right")
        self.wait_window(dlg)
        return result["ok"]

    def _preflight_check_vipergirls_posting(
        self,
        pending_by_group: Dict[Any, List[str]],
        issues: List[str],
    ) -> None:
        posting_targets = self._selected_vipergirls_posting_targets(pending_by_group)
        if not posting_targets:
            return

        user = str(getattr(self, "creds", {}).get("vg_user", "") or "").strip()
        password = str(getattr(self, "creds", {}).get("vg_pass", "") or "").strip()
        if not user or not password:
            issues.append(
                "ViperGirls posting needs username and password. "
                "Set them in Tools > Set Credentials."
            )

        try:
            saved_threads = viper_api.load_saved_threads()
        except Exception as exc:
            self.preflight_action_viper_targets = True
            issues.append(f"ViperGirls posting targets could not be loaded: {exc}")
            return

        self.saved_threads_data = saved_threads
        try:
            auto_poster = object.__getattribute__(self, "auto_poster")
        except AttributeError:
            auto_poster = None
        if auto_poster:
            auto_poster.saved_threads_data = saved_threads

        for _group, batch_name, target_name in posting_targets:
            record = saved_threads.get(target_name)
            if record is None:
                self.preflight_action_viper_targets = True
                issues.append(
                    f'ViperGirls target "{target_name}" selected for "{batch_name}" '
                    "no longer exists."
                )
                continue

            if not self._thread_id_from_vipergirls_record(record):
                self.preflight_action_viper_targets = True
                issues.append(
                    f'ViperGirls target "{target_name}" selected for "{batch_name}" '
                    "has no usable thread ID."
                )

    def _preflight_check_output_locations(self, issues: List[str]) -> None:
        for folder, label in [
            (getattr(self, "output_dir", "Output"), "Output folder"),
            (
                getattr(
                    self,
                    "central_history_path",
                    os.path.join(os.path.expanduser("~"), ".conniesuploader", "history"),
                ),
                "History folder",
            ),
        ]:
            try:
                self._assert_folder_writable(folder)
            except OSError as exc:
                issues.append(f"{label} is not writable: {exc}")
                self.preflight_action_folders.append({"label": label, "path": folder})

    def _assert_folder_writable(self, folder: str) -> None:
        os.makedirs(folder, exist_ok=True)
        test_path = os.path.join(folder, ".conniesuploader_write_test")
        with open(test_path, "w", encoding="utf-8") as handle:
            handle.write("ok")
        try:
            os.remove(test_path)
        except OSError as exc:
            logger.warning(f"Could not remove preflight test file {test_path}: {exc}")

    # _process_post_queue removed - now handled by AutoPoster class

    def update_ui_loop(self):
        """Main UI update loop - processes all queues and checks upload completion."""
        try:
            self._process_result_queue()
            self._process_ui_queue()
            self._process_progress_queue()

            if self.is_uploading:
                with self.lock:
                    if self.upload_count >= self.upload_total:
                        self.finish_upload()
        except Exception as e:
            logger.error(f"UI Loop Error: {e}", exc_info=True)
        finally:
            self.after(config.UI_UPDATE_INTERVAL_MS, self.update_ui_loop)

    def _process_result_queue(self):
        """Process upload results from result_queue."""
        try:
            while True:
                fp, img, thumb = self.result_queue.get_nowait()
                with self.lock:
                    self.results.append((fp, img, thumb))
        except queue.Empty:
            pass

    def _process_ui_queue(self):
        """Process UI updates from ui_queue (batch file additions)."""
        ui_limit = config.UI_QUEUE_BATCH_SIZE
        processed = 0
        try:
            while ui_limit > 0:
                item = self.ui_queue.get_nowait()
                a, f, p, g = item[:4]
                preview_requested = item[4] if len(item) > 4 else True
                if a == "add" and g.winfo_exists():
                    self._create_row(f, p, g, preview_requested=preview_requested)
                    processed += 1
                ui_limit -= 1
        except queue.Empty:
            pass
        # Log queue status for large batches to help diagnose stalling
        if processed > 0 and self.ui_queue.qsize() > 100:
            logger.debug(f"UI queue processed {processed} items, {self.ui_queue.qsize()} remaining")

    def _process_progress_queue(self):
        """Process progress updates from progress_queue (status changes, progress bars)."""
        prog_limit = config.PROGRESS_UPDATE_BATCH_SIZE
        try:
            while prog_limit > 0:
                item = self.progress_queue.get_nowait()
                k = item[0]
                if k == "register_pix_gal":
                    new_data = item[2]
                    if self._register_pixhost_gallery_for_finalization(new_data):
                        gallery_hash = str(new_data.get("gallery_hash") or "")
                        self.add_activity(
                            f"Pixhost gallery {gallery_hash} registered for finalization."
                        )
                else:
                    f = item[1]
                    v = item[2]
                    if f in self.file_widgets:
                        w = self.file_widgets[f]
                        if k == "gallery_url":
                            self._apply_result_gallery_url(f, v)
                        elif k == "status":
                            status_text = str(v or "")
                            is_success = status_text == "Done"
                            is_failure = status_text == "Failed" or status_text.lower().startswith(
                                "error"
                            )
                            if is_success or is_failure:
                                with self.lock:
                                    self.upload_count += 1
                                w["state"] = "success" if is_success else "failed"
                                w["status"].configure(text="Uploaded" if is_success else "Failed")
                                w["prog"].set(1.0)
                                self._set_row_progress_color(
                                    w, "#34C759" if is_success else "#FF3B30"
                                )
                                if w.get("remove"):
                                    w["remove"].configure(state="normal")
                                name = os.path.basename(f)
                                if is_success:
                                    self._set_row_error(w, "")
                                    self._set_row_retry_visible(w, False)
                                    self.add_activity(f"Uploaded {name}.", "success")
                                else:
                                    reason = status_text
                                    if reason.lower().startswith("error:"):
                                        reason = reason.split(":", 1)[1].strip()
                                    reason = (
                                        reason
                                        if reason != "Failed"
                                        else "Upload failed without more detail."
                                    )
                                    self._set_row_error(w, reason)
                                    self._set_row_retry_visible(w, True)
                                    self.add_activity(f"Failed {name}: {reason}.", "error")
                                self._update_group_progress(f)
                                # Update overall progress bar
                                if self.upload_total > 0:
                                    progress = self.upload_count / self.upload_total
                                    self.overall_progress.set(progress)
                            else:
                                w["status"].configure(text=self._friendly_row_status(status_text))
                        elif k == "prog":
                            progress_value = self._normalize_progress_value(v)
                            if progress_value is not None:
                                w["prog"].set(progress_value)
                prog_limit -= 1
        except queue.Empty:
            pass

    def _create_row(self, fp, pil_image, group_widget, preview_requested=True):
        """Create a UI row for a file with thumbnail, status, and progress bar.

        Args:
            fp: File path to the image
            pil_image: PIL Image object for thumbnail (or None)
            group_widget: CollapsibleGroupFrame to add the row to
        """
        group_widget.add_file(fp)
        row = ctk.CTkFrame(group_widget.content_frame)
        row.pack(fill="x", pady=1)
        drag_handle = ctk.CTkButton(
            row,
            text="::",
            width=24,
            height=24,
            fg_color="transparent",
            hover_color="#555555",
            text_color="gray",
        )
        drag_handle.pack(side="left", padx=(4, 2), pady=3)
        cover_var = tk.BooleanVar(value=False)
        cover_toggle = ctk.CTkCheckBox(
            row,
            text="Cover",
            variable=cover_var,
            command=lambda f=fp: self._set_cover_from_toggle(f),
            width=72,
            height=24,
            checkbox_width=16,
            checkbox_height=16,
            border_width=2,
            text_color="gray",
        )
        cover_toggle.pack(side="left", padx=(2, 4), pady=3)
        img_widget = None
        if pil_image:
            img_widget = ctk.CTkImage(
                light_image=pil_image, dark_image=pil_image, size=config.UI_THUMB_SIZE
            )
            image_label = ctk.CTkLabel(row, image=img_widget, text="")
            image_label.pack(side="left", padx=5)
            self.image_refs.add(img_widget)
        elif preview_requested:
            ctk.CTkLabel(row, text="No preview", width=78, text_color="gray").pack(
                side="left", padx=5
            )
        st = ctk.CTkLabel(row, text="Waiting", width=86, anchor="center")
        st.pack(side="left")
        text_frame = ctk.CTkFrame(row, fg_color="transparent")
        text_frame.pack(side="left", fill="x", expand=True, padx=5)
        filename_label = ctk.CTkLabel(
            text_frame,
            text=os.path.basename(fp),
            anchor="w",
            justify="left",
        )
        filename_label.pack(anchor="w", fill="x")
        error_label = ctk.CTkLabel(
            text_frame,
            text="",
            anchor="w",
            justify="left",
            text_color="#FF3B30",
        )

        def update_text_wrap(event):
            wraplength = max(160, event.width - 8)
            filename_label.configure(wraplength=wraplength)
            error_label.configure(wraplength=wraplength)

        text_frame.bind("<Configure>", update_text_wrap)

        row_actions = ctk.CTkFrame(row, fg_color="transparent", width=176, height=30)
        row_actions.pack(side="right", padx=(4, 5))
        row_actions.pack_propagate(False)
        retry_slot = ctk.CTkFrame(row_actions, fg_color="transparent", width=64, height=30)
        retry_slot.pack(side="right", padx=(4, 0))
        retry_slot.pack_propagate(False)
        btn_retry = ctk.CTkButton(
            retry_slot,
            text="Retry",
            width=58,
            height=24,
            command=lambda f=fp: self._retry_file(f),
            fg_color="#3B8ED0",
            hover_color="#1F6AA5",
            state="disabled",
        )
        pr = ctk.CTkProgressBar(row_actions, width=100)
        pr.set(0)
        pr.pack(side="right", padx=(0, 6), pady=8)
        with self.lock:
            self.file_widgets[fp] = {
                "row": row,
                "status": st,
                "prog": pr,
                "state": "pending",
                "group": group_widget,
                "image_ref": img_widget,  # Store reference for cleanup
                "text_frame": text_frame,
                "filename": filename_label,
                "error_label": error_label,
                "actions": row_actions,
                "retry_slot": retry_slot,
                "cover": cover_toggle,
                "cover_var": cover_var,
                "retry": btn_retry,
                "drag_handle": drag_handle,
                "error": "",
            }
            file_count = len(self.file_widgets)
        self._apply_auto_covers_to_group(group_widget)
        self.lbl_eta.configure(text=f"Files: {file_count}")
        self._refresh_queue_state()

        def bind_row(w):
            w.bind("<Button-1>", lambda e, w=row, f=fp: self._on_row_drag_start(e, w, f))
            w.bind("<B1-Motion>", self._on_row_drag_motion)
            w.bind("<ButtonRelease-1>", self._on_row_drag_end)
            w.bind("<Button-3>", lambda e, f=fp: self._show_row_context(e, f))
            w.bind("<Button-2>", lambda e, f=fp: self._show_row_context(e, f))

        interactive_widgets = (row_actions, retry_slot, cover_toggle, btn_retry, pr)

        def bind_row_tree(w):
            if w in interactive_widgets:
                return
            bind_row(w)
            for child_widget in w.winfo_children():
                bind_row_tree(child_widget)

        bind_row_tree(row)

    def _set_row_error(self, row_data: Dict[str, Any], reason: str) -> None:
        reason = str(reason or "").strip()
        row_data["error"] = reason
        error_label = row_data.get("error_label")
        if not error_label:
            return

        if reason:
            error_label.configure(text=f"Reason: {reason}")
            if not error_label.winfo_ismapped():
                error_label.pack(anchor="w", fill="x")
        else:
            error_label.configure(text="")
            if error_label.winfo_ismapped():
                error_label.pack_forget()

    def _set_row_retry_visible(self, row_data: Dict[str, Any], visible: bool) -> None:
        btn_retry = row_data.get("retry")
        if not btn_retry:
            return

        if visible:
            btn_retry.configure(state="normal")
            if not btn_retry.winfo_ismapped():
                btn_retry.pack(fill="both", expand=True, pady=3)
        else:
            btn_retry.configure(state="disabled")
            if btn_retry.winfo_ismapped():
                btn_retry.pack_forget()

    def _set_row_progress_color(self, row_data: Dict[str, Any], color: Any) -> None:
        progress = row_data.get("prog")
        if not progress:
            return

        try:
            progress.configure(progress_color=color)
        except (tk.TclError, TypeError):
            fallback = color[-1] if isinstance(color, (list, tuple)) else color
            progress.configure(progress_color=fallback)

    def _reset_row_for_retry(self, row_data: Dict[str, Any]) -> None:
        row_data["state"] = "pending"
        self._set_row_error(row_data, "")
        row_data["status"].configure(text="Retry")
        row_data["prog"].set(0)
        self._set_row_progress_color(row_data, ["#3B8ED0", "#1F6AA5"])
        self._set_row_retry_visible(row_data, False)

    def _retry_file(self, filepath: str) -> None:
        if getattr(self, "is_uploading", False):
            self.add_activity(
                "Wait for the current upload to finish before retrying one file.", "warning"
            )
            return

        with self.lock:
            row_data = self.file_widgets.get(filepath)

        if not row_data:
            self.add_activity("That file is no longer in the queue.", "warning")
            return

        if row_data.get("state") != "failed":
            self.add_activity(f"{os.path.basename(filepath)} is not failed.", "warning")
            return

        self._reset_row_for_retry(row_data)
        self.add_activity(f"Retrying {os.path.basename(filepath)}.")
        self.start_upload()

    def _copy_file_error(self, filepath: str) -> None:
        with self.lock:
            row_data = self.file_widgets.get(filepath)

        reason = str((row_data or {}).get("error", "") or "").strip()
        if not reason:
            self.add_activity(
                f"No error detail is available for {os.path.basename(filepath)}.", "warning"
            )
            return

        text = f"{os.path.basename(filepath)}: {reason}"
        try:
            pyperclip.copy(text)
            self.add_activity(f"Copied error for {os.path.basename(filepath)}.", "success")
        except (OSError, pyperclip.PyperclipException) as exc:
            logger.warning(f"Could not copy file error: {exc}")
            self.add_activity(
                f"Could not copy error for {os.path.basename(filepath)}.", "warning"
            )

    def _friendly_row_status(self, status_text: str) -> str:
        text = str(status_text or "").strip()
        if not text:
            return "Waiting"

        normalized = text.lower()
        if normalized in {"queued", "queue"}:
            return "Queued"
        if "wait" in normalized:
            return "Waiting"
        if "prepar" in normalized:
            return "Preparing"
        if "upload" in normalized:
            return "Uploading"
        if "start" in normalized:
            return "Starting"
        if normalized == "done":
            return "Uploaded"
        if normalized == "failed" or normalized.startswith("error"):
            return "Failed"
        return text

    def _normalize_progress_value(self, value: Any) -> Optional[float]:
        raw_value = value
        if isinstance(value, dict):
            raw_value = value.get("percentage")
            if raw_value is None:
                raw_value = value.get("progress")
            if raw_value is None:
                bytes_done = value.get("bytes_transferred")
                total_bytes = value.get("total_bytes")
                try:
                    raw_value = (float(bytes_done) / float(total_bytes)) * 100.0
                except (TypeError, ValueError, ZeroDivisionError):
                    return None

        try:
            progress = float(raw_value)
        except (TypeError, ValueError):
            return None

        if progress > 1.0:
            progress /= 100.0
        return max(0.0, min(1.0, progress))

    def _update_group_progress(self, fp):
        with self.lock:
            if fp not in self.file_widgets:
                return
        try:
            with self.lock:
                group = self.file_widgets[fp]["group"]
            if not group.winfo_exists():
                return
            total = len(group.files)
            if total == 0:
                return
            done = 0
            for f in group.files:
                with self.lock:
                    if f in self.file_widgets:
                        if self.file_widgets[f]["state"] in ["success", "failed"]:
                            done += 1
            group.prog.set(done / total)
            group.lbl_counts.configure(text=f"({done}/{total})")
            if done == total and not group.is_completed:
                group.mark_complete()
                self.generate_group_output(group)
        except Exception as e:
            logger.error(f"Group Update Error: {e}", exc_info=True)

    def finish_upload(self) -> None:
        if not self.is_uploading:
            return
        self.is_uploading = False  # Block re-entry before background thread starts
        self.lbl_eta.configure(text="Finalizing...")

        def _fin():
            finalization_events = []
            if self.pix_galleries_to_finalize:
                for gal in self.pix_galleries_to_finalize:
                    gallery_hash = str(gal.get("gallery_hash", "") or "")
                    gallery_name = str(gal.get("gallery_name", "") or gallery_hash)
                    try:
                        ok = api.finalize_pixhost_gallery(
                            gal.get("gallery_upload_hash", ""),
                            gal.get("gallery_hash", ""),
                        )
                        if ok:
                            finalization_events.append(
                                (
                                    f"Pixhost gallery finalized: {gallery_name} ({gallery_hash}).",
                                    "success",
                                )
                            )
                        else:
                            finalization_events.append(
                                (
                                    f"Pixhost gallery finalization failed: {gallery_name} ({gallery_hash}).",
                                    "error",
                                )
                            )
                    except Exception as e:
                        logger.error(f"Pixhost finalize error: {e}")
                        finalization_events.append(
                            (
                                f"Pixhost gallery finalization error for {gallery_name} ({gallery_hash}): {e}",
                                "error",
                            )
                        )
            self.after(0, lambda: self._finish_pixhost_finalization(finalization_events))

        threading.Thread(target=_fin, daemon=True).start()

    def _finish_pixhost_finalization(self, finalization_events: List[Tuple[str, str]]) -> None:
        for message, level in finalization_events:
            self.add_activity(message, level)
        self._on_upload_complete()

    def _on_upload_complete(self):
        self.is_uploading = False
        self._refresh_start_button_state()
        self._configure_stop_button(False)
        self.overall_progress.set(1.0)
        self.overall_progress.configure(progress_color="#34C759")
        summary = self._build_completion_summary()
        self.lbl_eta.configure(text=summary["status_text"])
        self.add_activity(summary["status_text"], "warning" if summary["failed_count"] else "success")

        if self.var_auto_copy.get() and self.clipboard_buffer:
            summary["copied_to_clipboard"] = self._copy_completion_output_to_clipboard(summary)
            if summary["copied_to_clipboard"]:
                self.add_activity("Copied output to clipboard.", "success")

        if self.current_output_files:
            self.btn_open.configure(state="normal")

        self._set_completion_summary(summary)

    def _build_completion_summary(self) -> Dict[str, Any]:
        with self.lock:
            states = [data.get("state") for data in self.file_widgets.values()]

        uploaded_count = sum(1 for state in states if state == "success")
        failed_count = sum(1 for state in states if state == "failed")
        total_count = len(states)
        output_files = list(self.current_output_files)
        generated_count = len(output_files)
        auto_copy_requested = bool(self.var_auto_copy.get())
        has_copy_text = bool(self.clipboard_buffer or output_files)

        if failed_count:
            status_text = f"Upload complete: {uploaded_count} uploaded, {failed_count} failed."
        else:
            file_label = "file" if uploaded_count == 1 else "files"
            status_text = f"Upload complete: {uploaded_count} {file_label} uploaded."

        return {
            "uploaded_count": uploaded_count,
            "failed_count": failed_count,
            "total_count": total_count,
            "generated_count": generated_count,
            "output_files": output_files,
            "auto_copy_requested": auto_copy_requested,
            "copied_to_clipboard": False,
            "has_copy_text": has_copy_text,
            "status_text": status_text,
        }

    def _completion_output_text(self, summary: Dict[str, Any]) -> str:
        if self.clipboard_buffer:
            return "\n\n".join(self.clipboard_buffer)

        chunks = []
        for output_file in summary.get("output_files", []):
            try:
                with open(output_file, "r", encoding="utf-8") as handle:
                    text = handle.read().strip()
                if text:
                    chunks.append(text)
            except OSError as exc:
                logger.warning(f"Could not read output file for clipboard copy: {exc}")
        return "\n\n".join(chunks)

    def _copy_completion_output_to_clipboard(self, summary: Dict[str, Any]) -> bool:
        text = self._completion_output_text(summary)
        if not text:
            return False

        try:
            pyperclip.copy(text)
            return True
        except (OSError, pyperclip.PyperclipException) as exc:
            logger.warning(f"Could not copy output to clipboard: {exc}")
            return False

    def stop_upload(self):
        self.cancel_event.set()
        self.lbl_eta.configure(text="Stopping...")
        self.add_activity("Stopping upload after current work finishes.", "warning")

    def generate_group_output(self, group):
        res_map = {r[0]: (r[1], r[2]) for r in self.results}
        group_results = []
        svc = self.settings.get("service", "")

        for fp in self._ordered_group_files_for_output(group):
            if fp in res_map:
                val = res_map[fp]
                viewer_url = val[0]
                thumb_url = val[1]
                direct_url = viewer_url
                if svc == "imx.to":
                    if "/t/" in thumb_url:
                        direct_url = thumb_url.replace("/t/", "/i/")
                group_results.append((viewer_url, thumb_url, direct_url))

        if not group_results:
            self.log(f"Warning: No successful uploads for '{group.title}'.")
            self.add_activity(f"No successful uploads for {group.title}.", "warning")
            return

        gallery = self._gallery_for_group(group, svc, self.settings) or {}
        gal_id = str(gallery.get("id") or "")
        cover_url = group_results[0][1] if group_results else ""

        # Get thumbnail size for BBCode formatting
        thumb_size = "250"  # Default
        if svc == "imx.to":
            thumb_size = self.settings.get("imx_thumb", "180")
        elif svc == "pixhost.to":
            thumb_size = self.settings.get("pix_thumb", "200")
        elif svc == "turboimagehost":
            thumb_size = self.settings.get("turbo_thumb", "180")
        elif svc == "vipr.im":
            thumb_size = self.settings.get("vipr_thumb", "170x170")
            if "x" in str(thumb_size):
                thumb_size = str(thumb_size).split("x")[0]
        elif svc == "imagebam.com":
            thumb_size = self.settings.get("imagebam_thumb", "180")
        elif svc == "imgur.com":
            thumb_size = self.settings.get("imgur_thumb", self.settings.get("thumbnail_size", "m"))

        gal_link = str(gallery.get("url") or "")

        target_name = str(getattr(group, "selected_thread", "") or "").strip()
        try:
            saved_threads = object.__getattribute__(self, "saved_threads_data")
        except AttributeError:
            saved_threads = {}
        record = saved_threads.get(target_name, {}) if isinstance(saved_threads, dict) else {}
        thread_id = self._thread_id_from_vipergirls_record(record)
        batch_name = self._batch_display_name(group)
        gallery_name = str(gallery.get("name") or batch_name)

        ctx = {
            "gallery_link": gal_link,
            "gallery_name": gallery_name,
            "gallery_id": gal_id,
            "cover_url": cover_url,
            "cover_count": len(self._cover_files_for_group(group)),
            "thumb_size": thumb_size,
            "batch_name": batch_name,
            "image_count": len(group_results),
            "service": svc,
            "thread_name": target_name if target_name != "Do Not Post" else "",
            "thread_id": thread_id,
            "upload_date": datetime.now().strftime("%Y-%m-%d"),
        }
        text = self.template_mgr.apply(group.selected_template, ctx, group_results)

        try:
            from modules.file_handler import sanitize_filename

            safe_title = sanitize_filename(group.title)
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            out_dir = getattr(self, "output_dir", "Output")
            os.makedirs(out_dir, exist_ok=True)
            out_name = os.path.join(out_dir, f"{safe_title}_{ts}.txt")
            with open(out_name, "w", encoding="utf-8") as f:
                f.write(text)
            self.current_output_files.append(out_name)
            self.log(f"Saved: {out_name}")
            self.add_activity(f"Saved output: {os.path.basename(out_name)}.", "success")

            # Queue for auto-posting if needed
            tgt_thread = group.selected_thread
            if tgt_thread and tgt_thread != "Do Not Post":
                self.auto_poster.queue_post(
                    group.batch_index,
                    text,
                    tgt_thread,
                    batch_name=self._batch_display_name(group),
                )
                message, level = self._vipergirls_queue_activity(group, tgt_thread)
                self.add_activity(message, level)

            central_name = os.path.join(self.central_history_path, f"{safe_title}_{ts}.txt")
            with open(central_name, "w", encoding="utf-8") as f:
                f.write(text)

            self.lbl_eta.configure(text=f"Saved: {safe_title}_{ts}.txt")
            self.btn_open.configure(state="normal")
            if self.var_auto_copy.get():
                self.clipboard_buffer.append(text)
                try:
                    pyperclip.copy("\n\n".join(self.clipboard_buffer))
                    self.add_activity("Copied output to clipboard.", "success")
                except (OSError, pyperclip.PyperclipException) as e:
                    logger.warning(f"Could not copy to clipboard: {e}")
                    self.add_activity("Could not copy output to clipboard.", "warning")

            need_links_txt = bool(self.settings.get("save_links", False))
            if svc == "imx.to" and self.var_imx_links.get():
                need_links_txt = True
            elif svc == "pixhost.to" and self.var_pix_links.get():
                need_links_txt = True
            elif svc == "turboimagehost" and self.var_turbo_links.get():
                need_links_txt = True
            elif svc == "vipr.im" and self.var_vipr_links.get():
                need_links_txt = True

            if need_links_txt:
                links_name = os.path.join(out_dir, f"{safe_title}_{ts}_links.txt")
                raw_links = "\n".join([r[0] for r in group_results])
                with open(links_name, "w", encoding="utf-8") as f:
                    f.write(raw_links)
                self.log(f"Saved Links: {links_name}")
                self.add_activity(f"Saved links file: {os.path.basename(links_name)}.", "success")

        except Exception as e:
            self.log(f"Error writing output: {e}")
            self.add_activity(f"Error writing output: {e}", "error")

    def _vipergirls_queue_activity(self, group: Any, target_name: str) -> Tuple[str, str]:
        batch_name = self._batch_display_name(group)
        try:
            saved_threads = object.__getattribute__(self, "saved_threads_data")
        except AttributeError:
            saved_threads = {}
        record = saved_threads.get(target_name)
        thread_id = self._thread_id_from_vipergirls_record(record)
        if thread_id:
            return (
                f'Queued ViperGirls post for "{batch_name}" to "{target_name}" '
                f"(thread {thread_id}).",
                "info",
            )

        return (
            f'Queued ViperGirls post for "{batch_name}" to "{target_name}" '
            "(thread ID unavailable).",
            "warning",
        )

    def open_output_folder(self):
        if self.current_output_files:
            folder = os.path.dirname(os.path.abspath(self.current_output_files[0]))
            try:
                if platform.system() == "Windows":
                    os.startfile(folder)
                else:
                    subprocess.run(["xdg-open", folder], check=False, shell=False)
                logger.info(f"Opened output folder: {folder}")
            except Exception as e:
                logger.error(f"Failed to open output folder: {e}")
                messagebox.showerror("Error", f"Could not open output folder:\n{folder}\n\nError: {str(e)}")
        else:
            logger.warning("No output files available to open folder")
            message = "No output files have been generated yet."
            self.lbl_eta.configure(text=message)
            self.add_activity(message, "warning")

    def toggle_log(self):
        if self.log_window_ref and self.log_window_ref.winfo_exists():
            self.log_window_ref.lift()
        else:
            self.log_window_ref = LogWindow(self, self.log_cache)

    def retry_failed(self) -> None:
        cnt = 0
        with self.lock:
            for w in self.file_widgets.values():
                if w["state"] == "failed":
                    self._reset_row_for_retry(w)
                    cnt += 1
        if cnt:
            self.add_activity(f"Retrying {cnt} failed file(s).")
            self.start_upload()
        else:
            self.add_activity("No failed files to retry.", "warning")

    def clear_list(self) -> None:
        self.cancel_event.set()
        self.is_uploading = False
        self.upload_count = 0
        self.upload_total = 0
        self.group_counter = 0
        self.current_output_files = []
        self.clipboard_buffer = []
        for grp in self.groups:
            grp.destroy()
        self.groups.clear()
        with self.lock:
            self.file_widgets.clear()
        self.selected_files.clear()
        self.selection_anchor = None
        self.image_refs.clear()
        self.overall_progress.set(0)
        self.lbl_eta.configure(text="Cleared.")
        self._configure_stop_button(False)
        self.btn_open.configure(state="disabled")
        self._set_import_checks([])
        self._set_upload_checks([])
        self._set_completion_summary(None)
        self._refresh_queue_state()
        self.add_activity("Cleared upload queue.")

    def _cleanup_orphaned_images(self):
        """Periodically clean up image references that are no longer in use."""
        with self.lock:
            # Keep only image refs that are still in file_widgets
            active_refs = set()
            for widget_data in self.file_widgets.values():
                img_ref = widget_data.get("image_ref")
                if img_ref:
                    active_refs.add(img_ref)

            # Remove orphaned refs using set intersection (O(n) instead of O(n²))
            self.image_refs &= active_refs

        # Schedule next cleanup in 30 seconds
        self.after(config.UI_CLEANUP_INTERVAL_MS, self._cleanup_orphaned_images)

    def log(self, msg):
        logger.info(msg)
        if self.log_window_ref and self.log_window_ref.winfo_exists():
            self.log_window_ref.append_log(msg + "\n")
        else:
            self.log_cache.append(msg + "\n")

    def graceful_shutdown(self):
        """Perform graceful shutdown of all application components."""
        logger.info("Initiating graceful shutdown...")

        # Stop any in-progress uploads
        if self.is_uploading:
            logger.info("Stopping uploads...")
            self.cancel_event.set()
            time.sleep(0.5)  # Give uploads time to detect cancellation

        # Stop AutoPoster
        if hasattr(self, "auto_poster") and self.auto_poster:
            logger.info("Stopping AutoPoster...")
            try:
                self.auto_poster.stop()
            except Exception as e:
                logger.warning(f"Error stopping AutoPoster: {e}")

        # Stop System Tray
        if hasattr(self, "system_tray") and self.system_tray:
            logger.info("Stopping System Tray...")
            try:
                self.system_tray.stop()
            except Exception as e:
                logger.warning(f"Error stopping System Tray: {e}")

        # Stop RenameWorker
        if hasattr(self, "rename_worker") and self.rename_worker:
            logger.info("Stopping RenameWorker...")
            try:
                self.rename_worker.stop()
                # Wait up to 2 seconds for rename worker to finish
                self.rename_worker.join(timeout=2.0)
            except Exception as e:
                logger.warning(f"Error stopping RenameWorker: {e}")

        # Shutdown thumbnail executor
        if hasattr(self, "thumb_executor") and self.thumb_executor:
            logger.info("Shutting down thumbnail executor...")
            try:
                # Use wait=False and manual timeout to prevent hanging
                self.thumb_executor.shutdown(wait=False, cancel_futures=True)
                # Give it a moment to finish current tasks
                time.sleep(0.3)
            except Exception as e:
                logger.warning(f"Error shutting down thumb_executor: {e}")

        # Shutdown upload manager
        if hasattr(self, "upload_manager") and self.upload_manager:
            logger.info("Shutting down upload manager...")
            try:
                self.upload_manager.shutdown()
            except Exception as e:
                logger.warning(f"Error shutting down upload_manager: {e}")

        # Terminate sidecar process
        logger.info("Terminating sidecar process...")
        try:
            from modules.sidecar import SidecarBridge

            sidecar = SidecarBridge.get()
            sidecar.shutdown()
        except Exception as e:
            logger.warning(f"Error shutting down sidecar: {e}")

        # Close log window if open
        if self.log_window_ref and self.log_window_ref.winfo_exists():
            try:
                self.log_window_ref.destroy()
            except Exception as e:
                logger.warning(f"Error closing log window: {e}")

        logger.info("Graceful shutdown complete")

        # Finally, quit the application
        self.quit()


if __name__ == "__main__":
    app = UploaderApp()
    app.mainloop()
