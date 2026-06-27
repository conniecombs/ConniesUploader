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
                    rejected_details.append(
                        f"{os.path.basename(path) or path}: not found or inaccessible"
                    )

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
                    logger.info(
                        f"Loading thumbnails for {file_count} files (this may take a moment)..."
                    )

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
