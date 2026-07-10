# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""UploadChecks behavior for the main window."""

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


class UploadChecksMixin:
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

            if upload_cfg.get(
                "confirm_before_posting"
            ) and self._selected_vipergirls_posting_targets(pending_by_group):
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
            gallery_summary = self._preflight_check_galleries(plugin, pending_by_group, cfg, issues)

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
            str(ext).lower() for ext in limits.get("allowed_formats", file_handler.VALID_EXTENSIONS)
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

    def _thread_id_from_vipergirls_record(self, record: Any) -> str:
        if isinstance(record, dict):
            thread_id = viper_api.extract_thread_id(str(record.get("thread_id") or ""))
            if thread_id:
                return thread_id
            return viper_api.extract_thread_id(str(record.get("url") or "")) or ""

        return viper_api.extract_thread_id(str(record or "")) or ""

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
            (getattr(self, "central_history_path", config.HISTORY_DIR), "History folder"),
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

    def _preflight_issues_need_credentials(self, issues: List[str]) -> bool:
        credential_words = ("credential", "client id", "access token", "password", "api key")
        return any(any(word in str(issue).lower() for word in credential_words) for issue in issues)

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
        self.add_activity(f"Upload blocked: {issue_count} {issue_label} need attention.", "error")
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
            issue
            for issue in getattr(self, "preflight_issues", [])
            if issue not in file_issue_texts
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
