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
import keyring
import pyperclip
import subprocess
import platform
import time
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# Local Imports
from modules import config
from modules import api
from modules.widgets import ScrollableFrame, LogWindow, CollapsibleGroupFrame, ServiceSettingsView
from modules.gallery_manager import GalleryManager
from modules.settings_manager import SettingsManager
from modules.template_manager import TemplateManager, TemplateEditor
from modules.upload_manager import UploadManager
from modules.utils import ContextUtils
from modules import viper_api
from modules.controller import RenameWorker
from modules import file_handler
from modules.dnd import DragDropMixin
from modules.credentials_manager import CredentialsManager
from modules.auto_poster import AutoPoster
from modules.plugin_manager import PluginManager
from loguru import logger



class SafeScrollableFrame(ctk.CTkScrollableFrame):
    def check_if_master_is_canvas(self, widget):
        if widget is None:
            return False
        if isinstance(widget, str):
            try:
                widget = self.winfo_toplevel().nametowidget(widget)
            except Exception:
                return False
        try:
            if widget == self._parent_canvas:
                return True
            elif hasattr(widget, "master") and widget.master is not None:
                return self.check_if_master_is_canvas(widget.master)
            else:
                return False
        except Exception:
            return False



class UploaderApp(ctk.CTk, TkinterDnD.DnDWrapper, DragDropMixin):
    def __init__(self):
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
            print(f"Icon load warning: {e}")

    def _init_variables(self):
        """Initialize UI variables and executors."""
        self.menu_thread_var = tk.IntVar(value=5)
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
        self.image_refs = []
        self.log_window_ref = None
        self.clipboard_buffer = []
        self.upload_total = 0
        self.upload_count = 0
        self.is_uploading = False
        self.current_output_files = []
        self.pix_galleries_to_finalize = []

    def _init_state(self):
        """Initialize application state tracking."""
        # Batch/Group tracking
        self.group_counter = 0

        # Drag & Drop state
        self.drag_data = {"item": None, "type": None, "y_start": 0, "widget_start": None}
        self.highlighted_row = None
        self.context_menu = tk.Menu(self, tearoff=0)

        # Service-specific state
        self.vipr_galleries_map = {}

    def _init_managers(self):
        """Initialize manager objects and background workers."""
        self.settings_mgr = SettingsManager()
        self.settings = self.settings_mgr.load()

        # Configure sidecar worker count before it's started
        from modules.sidecar import SidecarBridge
        worker_count = self.settings.get("global_worker_count", 8)
        SidecarBridge.set_worker_count(worker_count)

        self.template_mgr = TemplateManager()
        self.upload_manager = UploadManager(self.progress_queue, self.result_queue, self.cancel_event)

        self._load_credentials()
        self.rename_worker = RenameWorker(self.creds)
        self.rename_worker.start()

        # Central history directory
        self.central_history_path = os.path.join(os.path.expanduser("~"), ".conniesuploader", "history")
        if not os.path.exists(self.central_history_path):
            os.makedirs(self.central_history_path)

        self.saved_threads_data = viper_api.load_saved_threads()

        # Initialize AutoPoster
        self.auto_poster = AutoPoster(self.creds, self.saved_threads_data)

    def _init_ui(self):
        """Initialize user interface (menu, layout, drag-and-drop)."""
        self._create_menu()
        self._create_layout()
        self._apply_settings()

        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", self.drop_files)
        self.bind("<Button-1>", self._clear_highlights, add="+")

    def _load_startup_file(self):
        """Load file from command line argument if provided."""
        if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
            self.after(500, lambda: self._process_files([sys.argv[1]]))

        # Start UI update loop
        self.after(100, self.update_ui_loop)

        # Start periodic image cleanup to prevent memory leaks
        self.after(30000, self._cleanup_orphaned_images)

    def _load_credentials(self):
        """Load credentials from system keyring using CredentialsManager."""
        self.creds = CredentialsManager.load_all_credentials()

    def _create_menu(self):
        menubar = tk.Menu(self)
        self.configure(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Add Files", command=self.add_files)
        file_menu.add_command(label="Add Folder", command=self.add_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit)

        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Template Editor", command=self.open_template_editor)
        tools_menu.add_command(label="Set Credentials", command=self.open_creds_dialog)
        tools_menu.add_command(label="Manage Galleries", command=self.open_gallery_manager)
        tools_menu.add_separator()
        tools_menu.add_command(label="Viper Tools", command=self.open_viper_tools)

        thread_menu = tk.Menu(tools_menu, tearoff=0)
        tools_menu.add_cascade(label="Set Thread Limit", menu=thread_menu)
        for i in range(1, 11):
            thread_menu.add_radiobutton(
                label=f"{i} Threads",
                value=i,
                variable=self.menu_thread_var,
                command=lambda n=i: self.set_global_threads(n),
            )

        tools_menu.add_separator()
        tools_menu.add_command(label="Install Context Menu", command=ContextUtils.install_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Execution Log", command=self.toggle_log)
        view_menu.add_separator()
        view_menu.add_checkbutton(
            label="Show Image Previews", onvalue=True, offvalue=False, variable=self.var_show_previews
        )
        view_menu.add_checkbutton(
            label="Separate Batches for Files", onvalue=True, offvalue=False, variable=self.var_separate_batches
        )

        view_menu.add_separator()
        appearance_menu = tk.Menu(view_menu, tearoff=0)
        view_menu.add_cascade(label="Appearance Mode", menu=appearance_menu)
        appearance_menu.add_radiobutton(
            label="System", variable=self.var_appearance_mode, value="System", command=self.change_appearance_mode
        )
        appearance_menu.add_radiobutton(
            label="Light", variable=self.var_appearance_mode, value="Light", command=self.change_appearance_mode
        )
        appearance_menu.add_radiobutton(
            label="Dark", variable=self.var_appearance_mode, value="Dark", command=self.change_appearance_mode
        )

    def change_appearance_mode(self):
        mode = self.var_appearance_mode.get()
        ctk.set_appearance_mode(mode)

    def open_viper_tools(self):
        self.saved_threads_data = viper_api.load_saved_threads()
        viper_api.ViperToolsWindow(self, creds=self.creds, callback=self.refresh_thread_data)

    def refresh_thread_data(self):
        """Refresh saved thread data from disk and update AutoPoster."""
        self.saved_threads_data = viper_api.load_saved_threads()
        self.auto_poster.saved_threads_data = self.saved_threads_data

    def set_global_threads(self, n):
        self.menu_thread_var.set(n)
        if hasattr(self, "var_imx_threads"):
            self.var_imx_threads.set(n)
        if hasattr(self, "var_pix_threads"):
            self.var_pix_threads.set(n)
        if hasattr(self, "var_turbo_threads"):
            self.var_turbo_threads.set(n)
        if hasattr(self, "var_vipr_threads"):
            self.var_vipr_threads.set(n)
        if hasattr(self, "var_ib_threads"):
            self.var_ib_threads.set(n)

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

    def get_preview_data(self):
        if not self.groups:
            return None, None, None
        grp = next((g for g in self.groups if g.files), None)
        if not grp:
            return None, None, None
        current_service = self.var_service.get()
        size = "200"
        try:
            if current_service == "imx.to":
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
        except (AttributeError, tk.TclError) as e:
            logger.debug(f"Could not get thumbnail size for {current_service}: {e}")
        return grp.files, grp.title, size

    def on_gallery_created(self, service, gid):
        if service == "imx.to":
            self.ent_imx_gal.delete(0, "end")
            self.ent_imx_gal.insert(0, gid)
            self.var_service.set("imx.to")
            self._swap_service_frame("imx.to")
        elif service == "pixhost.to":
            self.ent_pix_hash.delete(0, "end")
            self.ent_pix_hash.insert(0, gid)
            self.var_service.set("pixhost.to")
            self._swap_service_frame("pixhost.to")
        elif service == "vipr.im":
            self.refresh_vipr_galleries(select_id=gid)

    def open_gallery_manager(self):
        GalleryManager(self, self.creds, callback=self.on_gallery_created)

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
                    self.after(0, lambda: self.cb_vipr_gallery.configure(values=gal_names))
                    self.log(f"Vipr: Found {len(meta['galleries'])} galleries.")
                else:
                    self.log("Vipr: No galleries found.")
            except Exception as e:
                self.log(f"Vipr Error: {e}")

        threading.Thread(target=_refresh, daemon=True).start()

    def _create_layout(self):
        main_container = ctk.CTkFrame(self)
        main_container.pack(fill="both", expand=True, padx=15, pady=15)

        self.settings_frame_container = SafeScrollableFrame(main_container, width=320, fg_color="transparent")
        self.settings_frame_container.pack(side="left", fill="y", padx=(0, 10))
        ctk.CTkLabel(self.settings_frame_container, text="Settings", font=("Segoe UI", 16, "bold")).pack(
            pady=10, padx=10, anchor="w"
        )

        out_frame = ctk.CTkFrame(self.settings_frame_container)
        out_frame.pack(fill="x", padx=10, pady=5)
        self.var_auto_copy = ctk.BooleanVar()
        ctk.CTkCheckBox(out_frame, text="Auto-copy to clipboard", variable=self.var_auto_copy).pack(
            anchor="w", padx=5, pady=2
        )
        self.var_auto_gallery = ctk.BooleanVar()
        ctk.CTkCheckBox(out_frame, text="One Gallery Per Folder", variable=self.var_auto_gallery).pack(
            anchor="w", padx=5, pady=2
        )

        # Global worker count setting
        worker_frame = ctk.CTkFrame(out_frame, fg_color="transparent")
        worker_frame.pack(fill="x", padx=5, pady=5)
        ctk.CTkLabel(worker_frame, text="Worker Count:", width=100).pack(side="left")
        self.var_global_worker_count = ctk.IntVar(value=8)
        worker_spinbox = ctk.CTkEntry(worker_frame, textvariable=self.var_global_worker_count, width=60)
        worker_spinbox.pack(side="left", padx=5)
        ctk.CTkLabel(worker_frame, text="(1-16)", font=("Segoe UI", 10)).pack(side="left")

        self.btn_open = ctk.CTkButton(
            out_frame, text="Open Output Folder", command=self.open_output_folder, state="disabled"
        )
        self.btn_open.pack(fill="x", padx=5, pady=10)

        ctk.CTkLabel(self.settings_frame_container, text="Select Image Host", font=("Segoe UI", 13, "bold")).pack(
            pady=(15, 2), padx=10, anchor="w"
        )
        # Dynamically get available plugins from PluginManager
        plugin_manager = PluginManager()
        available_services = plugin_manager.get_service_names()
        default_service = available_services[0] if available_services else "imx.to"

        self.var_service = ctk.StringVar(value=default_service)
        self.cb_service_select = ctk.CTkOptionMenu(
            self.settings_frame_container,
            variable=self.var_service,
            values=available_services,
            command=self._swap_service_frame,
        )
        self.cb_service_select.pack(fill="x", padx=10, pady=(0, 10))

        self.service_settings_container = ctk.CTkFrame(self.settings_frame_container, fg_color="transparent")
        self.service_settings_container.pack(fill="x", padx=5, pady=0)

        # --- REFACTOR: Delegate frame creation to ServiceSettingsView ---
        self.settings_view = ServiceSettingsView(self.service_settings_container, self)

        btn_frame = ctk.CTkFrame(self.settings_frame_container, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=10)
        self.btn_start = ctk.CTkButton(btn_frame, text="Start Upload", command=self.start_upload)
        self.btn_start.pack(fill="x", pady=5)
        self.btn_stop = ctk.CTkButton(
            btn_frame,
            text="Stop",
            command=self.stop_upload,
            state="disabled",
            fg_color="#FF3B30",
            hover_color="#D63028",
        )
        self.btn_stop.pack(fill="x", pady=5)

        util_grid = ctk.CTkFrame(btn_frame, fg_color="transparent")
        util_grid.pack(fill="x")
        ctk.CTkButton(util_grid, text="Retry Failed", command=self.retry_failed, width=100).pack(side="left", padx=2)
        ctk.CTkButton(util_grid, text="Clear List", command=self.clear_list, width=100).pack(side="right", padx=2)

        right_panel = ctk.CTkFrame(main_container)
        right_panel.pack(side="right", fill="both", expand=True)
        self.list_container = ScrollableFrame(right_panel, width=600)
        self.list_container.pack(fill="both", expand=True, padx=5, pady=5)
        self.file_frame = self.list_container

        footer = ctk.CTkFrame(right_panel, height=40, fg_color="transparent")
        footer.pack(fill="x", padx=5, pady=5)
        self.lbl_eta = ctk.CTkLabel(footer, text="Ready...", text_color="gray")
        self.lbl_eta.pack(anchor="w")
        self.overall_progress = ctk.CTkProgressBar(footer)
        self.overall_progress.set(0)
        self.overall_progress.pack(fill="x", pady=5)

    def _swap_service_frame(self, service_name):
        for frame in self.service_frames.values():
            frame.pack_forget()
        if service_name in self.service_frames:
            self.service_frames[service_name].pack(fill="both", expand=True, padx=5, pady=5)

    def _apply_settings(self):
        s = self.settings

        def get_count(key, old_bool_key):
            val = s.get(key)
            if val is not None:
                return str(val)
            return "1" if s.get(old_bool_key, False) else "0"

        self.var_global_worker_count.set(s.get("global_worker_count", 8))

        self.var_imx_thumb.set(s.get("imx_thumb", "180"))
        self.var_imx_format.set(s.get("imx_format", "Fixed Width"))
        self.var_imx_cover_count.set(get_count("imx_cover_count", "imx_cover"))
        self.var_imx_links.set(s.get("imx_links", False))
        self.var_imx_threads.set(s.get("imx_threads", 5))
        self.menu_thread_var.set(s.get("imx_threads", 5))

        self.var_pix_content.set(s.get("pix_content", "Safe"))
        self.var_pix_thumb.set(s.get("pix_thumb", "200"))
        self.var_pix_cover_count.set(get_count("pix_cover_count", "pix_cover"))
        self.var_pix_links.set(s.get("pix_links", False))
        self.var_pix_threads.set(s.get("pix_threads", 3))

        self.var_turbo_content.set(s.get("turbo_content", "Safe"))
        self.var_turbo_thumb.set(s.get("turbo_thumb", "180"))
        self.var_turbo_cover_count.set(get_count("turbo_cover_count", "turbo_cover"))
        self.var_turbo_links.set(s.get("turbo_links", False))
        self.var_turbo_threads.set(s.get("turbo_threads", 2))

        self.var_vipr_thumb.set(s.get("vipr_thumb", "170x170"))
        self.var_vipr_cover_count.set(get_count("vipr_cover_count", "vipr_cover"))
        self.var_vipr_links.set(s.get("vipr_links", False))
        self.var_vipr_threads.set(s.get("vipr_threads", 1))

        self.var_ib_content.set(s.get("imagebam_content", "Safe"))
        self.var_ib_thumb.set(s.get("imagebam_thumb", "180"))
        self.var_ib_threads.set(s.get("imagebam_threads", 2))

        self.var_auto_copy.set(s.get("auto_copy", False))
        self.var_auto_gallery.set(s.get("auto_gallery", False))
        self.var_show_previews.set(s.get("show_previews", True))
        self.var_separate_batches.set(s.get("separate_batches", False))

        mode = s.get("appearance_mode", "System")
        self.var_appearance_mode.set(mode)
        ctk.set_appearance_mode(mode)

        saved_service = s.get("service", "imx.to")
        self.var_service.set(saved_service)
        self._swap_service_frame(saved_service)
        self.ent_imx_gal.delete(0, "end")
        self.ent_imx_gal.insert(0, s.get("gallery_id", ""))
        self.ent_pix_hash.delete(0, "end")
        self.ent_pix_hash.insert(0, s.get("pix_gallery_hash", ""))

    def _safe_int(self, value, default=2):
        try:
            return int(value)
        except (ValueError, TypeError) as e:
            logger.debug(f"Could not convert '{value}' to int, using default {default}: {e}")
            return default

    def _gather_settings(self):
        vipr_gal_name = self.cb_vipr_gallery.get()
        vipr_id = self.vipr_galleries_map.get(vipr_gal_name, "0")

        def get_c(var):
            try:
                return int(var.get())
            except (ValueError, TypeError, AttributeError) as e:
                logger.debug(f"Could not convert variable to int: {e}")
                return 0

        return {
            "service": self.var_service.get(),
            "global_worker_count": self._safe_int(self.var_global_worker_count.get(), 8),
            "imx_thumb": self.var_imx_thumb.get(),
            "imx_format": self.var_imx_format.get(),
            "imx_cover_count": get_c(self.var_imx_cover_count),
            "imx_links": self.var_imx_links.get(),
            "imx_threads": self._safe_int(self.var_imx_threads.get(), 5),
            "pix_content": self.var_pix_content.get(),
            "pix_thumb": self.var_pix_thumb.get(),
            "pix_cover_count": get_c(self.var_pix_cover_count),
            "pix_links": self.var_pix_links.get(),
            "pix_threads": self._safe_int(self.var_pix_threads.get(), 3),
            "turbo_content": self.var_turbo_content.get(),
            "turbo_thumb": self.var_turbo_thumb.get(),
            "turbo_cover_count": get_c(self.var_turbo_cover_count),
            "turbo_links": self.var_turbo_links.get(),
            "turbo_threads": self._safe_int(self.var_turbo_threads.get(), 2),
            "vipr_thumb": self.var_vipr_thumb.get(),
            "vipr_cover_count": get_c(self.var_vipr_cover_count),
            "vipr_links": self.var_vipr_links.get(),
            "vipr_threads": self._safe_int(self.var_vipr_threads.get(), 1),
            "vipr_gal_id": vipr_id,
            "imagebam_content": self.var_ib_content.get(),
            "imagebam_thumb": self.var_ib_thumb.get(),
            "imagebam_threads": self._safe_int(self.var_ib_threads.get(), 2),
            "auto_copy": self.var_auto_copy.get(),
            "auto_gallery": self.var_auto_gallery.get(),
            "show_previews": self.var_show_previews.get(),
            "gallery_id": self.ent_imx_gal.get(),
            "pix_gallery_hash": self.ent_pix_hash.get(),
            "separate_batches": self.var_separate_batches.get(),
            "appearance_mode": self.var_appearance_mode.get(),
        }

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
                "Recursive Scan", "Do you want to scan recursively for all subfolders containing images?"
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

            subdirs = [os.path.join(folder, d) for d in os.listdir(folder) if os.path.isdir(os.path.join(folder, d))]
            if subdirs:
                if messagebox.askyesno(
                    "Batch Add Groups",
                    f"This folder contains {len(subdirs)} immediate subfolders.\nDo you want to add each as a separate group?",
                ):
                    self._process_files(subdirs)
                    files_in_root = [
                        f
                        for f in os.listdir(folder)
                        if os.path.isfile(os.path.join(folder, f)) and f.lower().endswith(file_handler.VALID_EXTENSIONS)
                    ]
                    if files_in_root:
                        self._process_files([folder])
                    return
        self._process_files([folder])

    def _process_files(self, inputs, target_group=None):
        misc_files = []
        show_previews = self.var_show_previews.get()
        for path in inputs:
            path = os.path.normpath(path)
            if os.path.isdir(path):
                folder_name = os.path.basename(path.rstrip(os.sep))
                files_in_folder = file_handler.get_files_from_directory(path)
                if files_in_folder:
                    files_in_folder.sort(key=config.natural_sort_key)
                    if target_group:
                        self.thumb_executor.submit(self._thumb_worker, files_in_folder, target_group, show_previews)
                    else:
                        grp = self._create_group(folder_name)
                        self.thumb_executor.submit(self._thumb_worker, files_in_folder, grp, show_previews)
            elif os.path.isfile(path):
                if path.lower().endswith(file_handler.VALID_EXTENSIONS):
                    misc_files.append(path)

        if misc_files:
            misc_files.sort(key=config.natural_sort_key)
            if target_group:
                self.thumb_executor.submit(self._thumb_worker, misc_files, target_group, show_previews)
            elif self.var_separate_batches.get():
                for f in misc_files:
                    grp_name = os.path.basename(f)
                    grp = self._create_group(grp_name)
                    self.thumb_executor.submit(self._thumb_worker, [f], grp, show_previews)
            else:
                misc_group = next((g for g in self.groups if g.title == "Miscellaneous"), None)
                if not misc_group:
                    misc_group = self._create_group("Miscellaneous")
                self.thumb_executor.submit(self._thumb_worker, misc_files, misc_group, show_previews)

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
        )
        group.pack(fill="x", pady=2, padx=2)
        group.batch_index = self.group_counter
        self.group_counter += 1
        self.groups.append(group)

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
        for f in files:
            with self.lock:
                if f in self.file_widgets:
                    continue
            pil_image = None
            if show_previews:
                try:
                    pil_image = file_handler.generate_thumbnail(f)
                except Exception:
                    pil_image = None
            self.ui_queue.put(("add", f, pil_image, group_widget))
            time.sleep(0.001)

    def start_upload(self):
        pending_by_group = {}
        for grp in self.groups:
            for fp in grp.files:
                with self.lock:
                    if self.file_widgets[fp]["state"] == "pending":
                        if grp not in pending_by_group:
                            pending_by_group[grp] = []
                        pending_by_group[grp].append(fp)

        if not pending_by_group:
            messagebox.showinfo("Info", "No pending files found. Please add files or use 'Retry Failed'.")
            return

        try:
            cfg = self._gather_settings()
            self.settings = cfg
            self.settings_mgr.save(cfg)
            cfg["api_key"] = self.creds.get("imx_api", "")

            self.cancel_event.clear()
            self.results = []
            self.result_queue = queue.Queue(maxsize=1000)
            self.upload_manager.result_queue = self.result_queue

            self.pix_galleries_to_finalize = []
            self.clipboard_buffer = []

            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.lbl_eta.configure(text="Starting...")

            self.overall_progress.set(0)
            try:
                self.overall_progress.configure(progress_color=["#3B8ED0", "#1F6AA5"])
            except (tk.TclError, TypeError) as e:
                logger.debug(f"Could not set gradient progress color, using solid: {e}")
                self.overall_progress.configure(progress_color="blue")

            self.upload_total = sum(len(v) for v in pending_by_group.values())
            self.upload_count = 0
            self.is_uploading = True

            for files in pending_by_group.values():
                for fp in files:
                    with self.lock:
                        self.file_widgets[fp]["state"] = "queued"

            # Reset and prepare AutoPoster
            self.auto_poster.reset()
            self.saved_threads_data = viper_api.load_saved_threads()
            self.auto_poster.saved_threads_data = self.saved_threads_data

            sorted_groups = sorted(
                self.groups,
                key=lambda g: (
                    self.list_container.winfo_children().index(g) if g in self.list_container.winfo_children() else 999
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
                self.auto_poster.start_processing(
                    is_uploading_callback=lambda: self.is_uploading,
                    cancel_event=self.cancel_event
                )

            self.upload_manager.start_batch(pending_by_group, cfg, self.creds)

        except Exception as e:
            messagebox.showerror("Error starting upload", str(e))
            self.btn_start.configure(state="normal")

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
            print(f"UI Loop Error: {e}")
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
        try:
            while ui_limit > 0:
                a, f, p, g = self.ui_queue.get_nowait()
                if a == "add" and g.winfo_exists():
                    self._create_row(f, p, g)
                ui_limit -= 1
        except queue.Empty:
            pass

    def _process_progress_queue(self):
        """Process progress updates from progress_queue (status changes, progress bars)."""
        prog_limit = config.PROGRESS_UPDATE_BATCH_SIZE
        try:
            while prog_limit > 0:
                item = self.progress_queue.get_nowait()
                k = item[0]
                if k == "register_pix_gal":
                    new_data = item[2]
                    self.pix_galleries_to_finalize.append(new_data)
                else:
                    f = item[1]
                    v = item[2]
                    if f in self.file_widgets:
                        w = self.file_widgets[f]
                        if k == "status":
                            w["status"].configure(text=v)
                            if v in ["Done", "Failed"]:
                                with self.lock:
                                    self.upload_count += 1
                                w["state"] = "success" if v == "Done" else "failed"
                                w["prog"].set(1.0)
                                w["prog"].configure(progress_color="#34C759" if v == "Done" else "#FF3B30")
                                self._update_group_progress(f)
                        elif k == "prog":
                            w["prog"].set(v)
                prog_limit -= 1
        except queue.Empty:
            pass

    def _create_row(self, fp, pil_image, group_widget):
        group_widget.add_file(fp)
        row = ctk.CTkFrame(group_widget.content_frame)
        row.pack(fill="x", pady=1)
        img_widget = None
        if pil_image:
            img_widget = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=config.UI_THUMB_SIZE)
            l = ctk.CTkLabel(row, image=img_widget, text="")
            l.pack(side="left", padx=5)
            self.image_refs.append(img_widget)
        else:
            ctk.CTkLabel(row, text="[Img]", width=40).pack(side="left")
        st = ctk.CTkLabel(row, text="Wait", width=60)
        st.pack(side="left")
        ctk.CTkLabel(row, text=os.path.basename(fp)).pack(side="left", fill="x", expand=True, padx=5)
        pr = ctk.CTkProgressBar(row, width=100)
        pr.set(0)
        pr.pack(side="right", padx=5)
        with self.lock:
            self.file_widgets[fp] = {
                "row": row,
                "status": st,
                "prog": pr,
                "state": "pending",
                "group": group_widget,
                "image_ref": img_widget  # Store reference for cleanup
            }
            file_count = len(self.file_widgets)
        self.lbl_eta.configure(text=f"Files: {file_count}")

        def bind_row(w):
            w.bind("<Button-1>", lambda e, w=row, f=fp: self._on_row_drag_start(e, w, f))
            w.bind("<B1-Motion>", self._on_row_drag_motion)
            w.bind("<ButtonRelease-1>", self._on_row_drag_end)
            w.bind("<Button-3>", lambda e, f=fp: self._show_row_context(e, f))
            w.bind("<Button-2>", lambda e, f=fp: self._show_row_context(e, f))

        bind_row(row)
        for child in row.winfo_children():
            bind_row(child)

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
            print(f"Group Update Error: {e}")

    def finish_upload(self):
        if not self.is_uploading:
            return
        self.lbl_eta.configure(text="Finalizing...")

        def _fin():
            self.after(0, self._on_upload_complete)

        threading.Thread(target=_fin, daemon=True).start()

    def _on_upload_complete(self):
        self.is_uploading = False
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.overall_progress.set(1.0)
        self.overall_progress.configure(progress_color="#34C759")
        self.lbl_eta.configure(text="All batches finished.")
        if self.var_auto_copy.get() and self.clipboard_buffer:
            try:
                pyperclip.copy("\n\n".join(self.clipboard_buffer))
            except (OSError, pyperclip.PyperclipException) as e:
                logger.warning(f"Could not copy to clipboard: {e}")
        if self.current_output_files:
            self.btn_open.configure(state="normal")
            msg = "Output files created."
            if self.var_auto_copy.get():
                msg += " All output text copied to clipboard."
            messagebox.showinfo("Done", msg)

    def stop_upload(self):
        self.cancel_event.set()
        self.lbl_eta.configure(text="Stopping...")

    def generate_group_output(self, group):
        res_map = {r[0]: (r[1], r[2]) for r in self.results}
        group_results = []
        svc = self.settings.get("service", "")

        for fp in group.files:
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
            return

        gal_id = getattr(group, "gallery_id", "")
        cover_url = group_results[0][1] if group_results else ""

        # Get thumbnail size for BBCode formatting
        thumb_size = "250"  # Default
        if svc == "imx.to":
            thumb_size = self.settings.get("imx_thumb", "180")
        elif svc == "pixhost.to":
            thumb_size = self.settings.get("pix_thumb", "200")
        elif svc == "turboimagehost":
            thumb_size = self.settings.get("turbo_thumb", "180")
        elif svc == "imagebam.com":
            thumb_size = self.settings.get("imagebam_thumb", "180")

        gal_link = ""
        if gal_id:
            if svc == "pixhost.to":
                gal_link = f"https://pixhost.to/gallery/{gal_id}"
            elif svc == "imx.to":
                gal_link = f"https://imx.to/g/{gal_id}"
            elif svc == "vipr.im":
                gal_link = f"https://vipr.im/f/{gal_id}"

        ctx = {"gallery_link": gal_link, "gallery_name": group.title, "gallery_id": gal_id, "cover_url": cover_url, "thumb_size": thumb_size}
        text = self.template_mgr.apply(group.selected_template, ctx, group_results)

        try:
            from modules.file_handler import sanitize_filename
            safe_title = sanitize_filename(group.title)
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            out_dir = "Output"
            os.makedirs(out_dir, exist_ok=True)
            out_name = os.path.join(out_dir, f"{safe_title}_{ts}.txt")
            with open(out_name, "w", encoding="utf-8") as f:
                f.write(text)
            self.current_output_files.append(out_name)
            self.log(f"Saved: {out_name}")

            # Queue for auto-posting if needed
            tgt_thread = group.selected_thread
            if tgt_thread and tgt_thread != "Do Not Post":
                self.auto_poster.queue_post(group.batch_index, text, tgt_thread)

            central_name = os.path.join(self.central_history_path, f"{safe_title}_{ts}.txt")
            with open(central_name, "w", encoding="utf-8") as f:
                f.write(text)

            self.lbl_eta.configure(text=f"Saved: {safe_title}_{ts}.txt")
            self.btn_open.configure(state="normal")
            if self.var_auto_copy.get():
                self.clipboard_buffer.append(text)
                try:
                    pyperclip.copy("\n\n".join(self.clipboard_buffer))
                except (OSError, pyperclip.PyperclipException) as e:
                    logger.warning(f"Could not copy to clipboard: {e}")

            need_links_txt = False
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

        except Exception as e:
            self.log(f"Error writing output: {e}")

    def open_output_folder(self):
        if self.current_output_files:
            folder = os.path.dirname(os.path.abspath(self.current_output_files[0]))
            if platform.system() == "Windows":
                os.startfile(folder)
            else:
                subprocess.run(["xdg-open", folder], check=False, shell=False)

    def toggle_log(self):
        if self.log_window_ref and self.log_window_ref.winfo_exists():
            self.log_window_ref.lift()
        else:
            self.log_window_ref = LogWindow(self, self.log_cache)

    def retry_failed(self):
        cnt = 0
        with self.lock:
            for w in self.file_widgets.values():
                if w["state"] == "failed":
                    w["status"].configure(text="Retry")
                    w["prog"].set(0)
                    w["state"] = "pending"
                    cnt += 1
        if cnt:
            self.start_upload()

    def clear_list(self):
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
        self.image_refs.clear()
        self.overall_progress.set(0)
        self.lbl_eta.configure(text="Cleared.")
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")

    def _cleanup_orphaned_images(self):
        """Periodically clean up image references that are no longer in use."""
        with self.lock:
            # Keep only image refs that are still in file_widgets
            active_refs = set()
            for widget_data in self.file_widgets.values():
                img_ref = widget_data.get("image_ref")
                if img_ref:
                    active_refs.add(img_ref)

            # Remove orphaned refs
            self.image_refs = [ref for ref in self.image_refs if ref in active_refs]

        # Schedule next cleanup in 30 seconds
        self.after(30000, self._cleanup_orphaned_images)

    def log(self, msg):
        logger.info(msg)
        if self.log_window_ref and self.log_window_ref.winfo_exists():
            self.log_window_ref.append_log(msg + "\n")
        else:
            self.log_cache.append(msg + "\n")


if __name__ == "__main__":
    app = UploaderApp()
    app.mainloop()
