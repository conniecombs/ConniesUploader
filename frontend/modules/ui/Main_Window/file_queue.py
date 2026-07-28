# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""FileQueue behavior for the main window."""

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
    deque,
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


class FileQueueMixin:
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
        """Process dropped or selected files/folders without blocking the UI thread."""
        inputs = [os.path.normpath(str(path)) for path in (inputs or [])]
        if not inputs:
            return

        logger.info(f"📁 Processing {len(inputs)} input(s)...")
        self._set_completion_summary(None)
        self._set_import_checks([])

        self._ensure_import_state()
        preview_var = self.__dict__.get("var_show_previews")
        separate_var = self.__dict__.get("var_separate_batches")
        show_previews = bool(preview_var.get()) if preview_var else True
        separate_batches = bool(separate_var.get()) if separate_var else False
        import_id, epoch = self._register_import()

        self.lbl_eta.configure(text=f"Scanning {len(inputs)} item(s)...")
        self.add_activity(f"Processing {len(inputs)} selected item(s).")
        if hasattr(self, "update_idletasks"):
            self.update_idletasks()

        executor = self.__dict__.get("import_executor")
        if executor is None:
            result = self._scan_import_inputs(inputs)
            self._handle_import_complete(
                import_id, epoch, result, target_group, show_previews, separate_batches
            )
            return

        try:
            executor.submit(
                self._scan_import_worker,
                import_id,
                epoch,
                inputs,
                target_group,
                show_previews,
                separate_batches,
            )
        except Exception as e:
            self._finish_import(import_id, epoch)
            logger.error(f"✗ Error in _process_files: {e}", exc_info=True)
            self.lbl_eta.configure(text="Error processing files")
            self.add_activity(f"Error processing files: {e}", "error")
            messagebox.showerror(
                "Processing Error", f"An error occurred while processing files:\n\n{str(e)}"
            )

    def _ensure_import_state(self) -> None:
        if "import_epoch" not in self.__dict__:
            self.import_epoch = 0
        if "import_counter" not in self.__dict__:
            self.import_counter = 0
        if "active_import_ids" not in self.__dict__:
            self.active_import_ids = set()
        if "pending_filepaths" not in self.__dict__:
            self.pending_filepaths = set()
        if "pending_ui_rows" not in self.__dict__:
            self.pending_ui_rows = deque()
        if "pending_thumbnails" not in self.__dict__:
            self.pending_thumbnails = {}

    def _import_lock(self):
        return self.__dict__.get("lock") or nullcontext()

    def _register_import(self) -> Tuple[int, int]:
        self._ensure_import_state()
        with self._import_lock():
            self.import_counter += 1
            import_id = self.import_counter
            self.active_import_ids.add(import_id)
            return import_id, self.import_epoch

    def _finish_import(self, import_id: int, epoch: int) -> None:
        self._ensure_import_state()
        with self._import_lock():
            if epoch == self.import_epoch:
                self.active_import_ids.discard(import_id)

    def _is_import_epoch_current(self, epoch: Optional[int]) -> bool:
        if epoch is None:
            return True
        self._ensure_import_state()
        with self._import_lock():
            return epoch == self.import_epoch

    def _scan_import_worker(
        self,
        import_id: int,
        epoch: int,
        inputs: List[str],
        target_group: Any,
        show_previews: bool,
        separate_batches: bool,
    ) -> None:
        result = self._scan_import_inputs(inputs)
        if not self._is_import_epoch_current(epoch):
            return
        try:
            self.ui_queue.put(
                (
                    "import_complete",
                    import_id,
                    epoch,
                    result,
                    target_group,
                    show_previews,
                    separate_batches,
                ),
                timeout=5.0,
            )
        except queue.Full:
            self._finish_import(import_id, epoch)
            logger.warning("UI queue full, dropping completed import scan.")

    def _scan_import_inputs(self, inputs: List[str]) -> Dict[str, Any]:
        result = {
            "folder_batches": [],
            "misc_files": [],
            "folder_count": 0,
            "file_count": 0,
            "rejected_details": [],
            "empty_folders": [],
        }

        for path in inputs:
            logger.debug(f"   Processing: {path}")

            if os.path.isdir(path):
                folder_name = os.path.basename(path.rstrip(os.sep)) or path
                logger.info(f"   📂 Scanning folder: {folder_name}")
                try:
                    files_in_folder = file_handler.get_files_from_directory(path)
                    if files_in_folder:
                        files_in_folder.sort(key=config.natural_sort_key)
                        logger.info(f"      ✓ Found {len(files_in_folder)} valid image(s)")
                        result["folder_batches"].append((folder_name, files_in_folder))
                        result["folder_count"] += 1
                        result["file_count"] += len(files_in_folder)
                    else:
                        logger.warning(f"      ⚠ No valid images in folder: {folder_name}")
                        result["empty_folders"].append(folder_name)
                except Exception as e:
                    logger.error(
                        f"      ✗ Error scanning folder {folder_name}: {e}", exc_info=True
                    )
                    result["rejected_details"].append(
                        f"{folder_name}: could not scan folder ({e})"
                    )

            elif os.path.isfile(path):
                if path.lower().endswith(file_handler.VALID_EXTENSIONS):
                    try:
                        file_handler.validate_file_size(path)
                        logger.debug(f"      ✓ Valid image file: {os.path.basename(path)}")
                        result["misc_files"].append(path)
                        result["file_count"] += 1
                    except Exception as e:
                        logger.warning(f"      ⚠ Rejected file {os.path.basename(path)}: {e}")
                        result["rejected_details"].append(f"{os.path.basename(path)}: {e}")
                else:
                    ext = os.path.splitext(path)[1]
                    logger.warning(
                        f"      ⚠ Rejected (invalid extension): {os.path.basename(path)} ({ext})"
                    )
                    result["rejected_details"].append(
                        f"{os.path.basename(path)}: unsupported extension {ext or '(none)'}"
                    )
            else:
                logger.warning(f"      ⚠ Path does not exist or is not accessible: {path}")
                result["rejected_details"].append(
                    f"{os.path.basename(path) or path}: not found or inaccessible"
                )

        result["misc_files"].sort(key=config.natural_sort_key)
        return result

    def _handle_import_complete(
        self,
        import_id: int,
        epoch: int,
        result: Dict[str, Any],
        target_group: Any,
        show_previews: bool,
        separate_batches: bool,
    ) -> None:
        self._finish_import(import_id, epoch)
        if not self._is_import_epoch_current(epoch):
            return

        file_count = result.get("file_count", 0)
        folder_count = result.get("folder_count", 0)
        rejected_details = list(result.get("rejected_details", []))
        empty_folders = list(result.get("empty_folders", []))

        if file_count == 0:
            logger.warning("⚠ No valid files were processed from the drop")
            self._notify_no_valid_files(empty_folders, rejected_details)
            return

        queued_count = self._queue_import_rows(
            result, target_group, show_previews, separate_batches, epoch
        )
        if queued_count == 0:
            status_msg = "No new files were added."
            self.lbl_eta.configure(text=status_msg)
            self.add_activity(status_msg, "warning")
            return

        logger.info(f"✓ Queued {queued_count} file(s) from {folder_count} folder(s)")
        status_msg = f"Queued {queued_count} file(s) from {folder_count} folder(s)"
        rejected_count = len(rejected_details)
        if rejected_count > 0:
            logger.info(f"   ({rejected_count} file(s) rejected)")
            status_msg += f" ({rejected_count} rejected)"
        self._set_import_checks([])
        if queued_count > 100:
            status_msg += " - Loading rows and thumbnails..."
            logger.info(f"Loading rows and thumbnails for {queued_count} files...")

        self.lbl_eta.configure(text=status_msg)
        self.add_activity(status_msg, "success")

    def _queue_import_rows(
        self,
        result: Dict[str, Any],
        target_group: Any,
        show_previews: bool,
        separate_batches: bool,
        epoch: int,
    ) -> int:
        queued_count = 0

        for folder_name, files_in_folder in result.get("folder_batches", []):
            group = (
                target_group
                if target_group
                else self._create_group(folder_name, refresh=False)
            )
            queued_count += len(
                self._enqueue_rows_for_group(files_in_folder, group, show_previews, epoch)
            )

        misc_files = list(result.get("misc_files", []))
        if target_group:
            queued_count += len(
                self._enqueue_rows_for_group(misc_files, target_group, show_previews, epoch)
            )
        elif separate_batches:
            for filepath in misc_files:
                group = self._create_group(os.path.basename(filepath), refresh=False)
                queued_count += len(
                    self._enqueue_rows_for_group([filepath], group, show_previews, epoch)
                )
        elif misc_files:
            misc_group = next((g for g in self.groups if g.title == "Miscellaneous"), None)
            if not misc_group:
                misc_group = self._create_group("Miscellaneous", refresh=False)
            queued_count += len(
                self._enqueue_rows_for_group(misc_files, misc_group, show_previews, epoch)
            )

        if queued_count:
            self._refresh_queue_state()
        return queued_count

    def _enqueue_rows_for_group(
        self, files: List[str], group_widget: Any, show_previews: bool, epoch: int
    ) -> List[str]:
        if not files or not self._group_widget_exists(group_widget):
            return []

        queued_files = []
        self._ensure_import_state()
        with self._import_lock():
            for filepath in files:
                if filepath in self.file_widgets or filepath in self.pending_filepaths:
                    logger.debug(f"File already queued, skipping: {filepath}")
                    continue
                self.pending_filepaths.add(filepath)
                self.pending_ui_rows.append((epoch, filepath, group_widget, show_previews))
                queued_files.append(filepath)

        if show_previews and queued_files and self.__dict__.get("thumb_executor"):
            self.thumb_executor.submit(
                self._thumb_worker, queued_files, group_widget, show_previews, epoch
            )
        return queued_files

    def _group_widget_exists(self, group_widget: Any) -> bool:
        if group_widget is None:
            return False
        try:
            return bool(group_widget.winfo_exists())
        except (tk.TclError, AttributeError):
            return True

    def _notify_no_valid_files(
        self, empty_folders: List[str], rejected_details: List[str]
    ) -> None:
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

    def _create_group(self, title, refresh=True):
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
        if refresh:
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

    def _thumb_worker(self, files, group_widget, show_previews, epoch=None):
        if not show_previews:
            return

        for f in files:
            if not self._is_import_epoch_current(epoch):
                return
            with self.lock:
                known_file = f in self.file_widgets or f in self.pending_filepaths
            if not known_file:
                logger.debug(f"File no longer queued, skipping thumbnail: {f}")
                continue

            pil_image = None
            try:
                pil_image = file_handler.generate_thumbnail(f)
            except Exception as e:
                logger.debug(f"Thumbnail generation failed for {os.path.basename(f)}: {e}")
                pil_image = None
            if not self._is_import_epoch_current(epoch):
                return
            try:
                self.ui_queue.put(("thumbnail", epoch, f, pil_image), timeout=5.0)
            except queue.Full:
                logger.warning(f"UI queue full, dropping thumbnail for {os.path.basename(f)}")
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
