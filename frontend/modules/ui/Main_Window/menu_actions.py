# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""MenuActions behavior for the main window."""

from .common import (  # noqa: F401
    Any,
    AutoPoster,
    CollapsibleGroupFrame,
    ContextUtils,
    CredentialsManager,
    DND_FILES,
    Dict,
    DragDropMixin,
    GalleryManager,
    GalleryRecord,
    Image,
    ImageTk,
    List,
    LogWindow,
    Optional,
    PluginManager,
    SafeScrollableFrame,
    ScrollableFrame,
    ServiceSettingsView,
    SettingsManager,
    TemplateEditor,
    TemplateManager,
    ThreadPoolExecutor,
    TkinterDnD,
    Tuple,
    UploadManager,
    api,
    config,
    ctk,
    datetime,
    file_handler,
    filedialog,
    gallery_url_for_service,
    logger,
    messagebox,
    nullcontext,
    os,
    platform,
    pyperclip,
    queue,
    subprocess,
    sys,
    threading,
    time,
    tk,
    viper_api,
)


class MenuActionsMixin:
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
        tools_menu.add_command(
            label="Reset Templates to Defaults", command=self.reset_templates_to_defaults
        )
        tools_menu.add_command(label="Set Credentials", command=self.open_creds_dialog)
        tools_menu.add_command(label="Manage Galleries", command=self.open_gallery_manager)
        tools_menu.add_separator()
        tools_menu.add_command(label="ViperGirls Posting Targets", command=self.open_viper_tools)
        tools_menu.add_command(
            label="ViperGirls Posting History", command=self.open_vipergirls_history
        )
        tools_menu.add_command(label="Scheduled Posts", command=self.open_scheduled_posts)

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
        self._add_recovery_detail(
            details, "Backup", issue.get("backup_path") or "Backup unavailable"
        )
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

    def open_creds_dialog(self):
        """Open credentials dialog using CredentialsManager."""
        CredentialsManager.create_credentials_dialog(
            parent=self, on_save_callback=self._load_credentials
        )
