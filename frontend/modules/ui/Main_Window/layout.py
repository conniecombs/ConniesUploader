# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Layout behavior for the main window."""

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


class LayoutMixin:
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
        thread_limit_entry = ctk.CTkEntry(thread_frame, textvariable=self.menu_thread_var, width=60)
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

    def _refresh_queue_action_buttons(self, queue_is_empty: bool) -> None:
        clear_state = "disabled" if queue_is_empty else "normal"
        if "btn_clear_list" in self.__dict__:
            self.btn_clear_list.configure(state=clear_state)
        if "btn_retry_failed" in self.__dict__:
            self.btn_retry_failed.configure(state=clear_state)

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
        self._set_queue_actions_visible(True)
        self._refresh_queue_action_buttons(queue_is_empty)
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

        self.upload_checks_actions = ctk.CTkFrame(self.upload_checks_panel, fg_color="transparent")
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
                str(creds.get(key, "") or "").strip() for key in ("imagebam_user", "imagebam_pass")
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
            return sum(1 for data in self.file_widgets.values() if data.get("state") == "pending")

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
