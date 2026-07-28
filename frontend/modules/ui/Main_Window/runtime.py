# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Runtime behavior for the main window."""

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


class RuntimeMixin:
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
        touched_files = []
        try:
            while True:
                fp, img, thumb = self.result_queue.get_nowait()
                viewer_url = str(img or "").strip()
                thumb_url = str(thumb or "").strip()
                with self.lock:
                    self.results.append((fp, viewer_url, thumb_url))
                    row_data = self.file_widgets.get(fp)
                    if row_data is not None:
                        if viewer_url:
                            row_data["upload_result"] = (viewer_url, thumb_url)
                            touched_files.append(fp)
                        else:
                            row_data.pop("upload_result", None)
        except queue.Empty:
            pass

        for fp in touched_files:
            self._update_group_progress(fp)

    def _process_ui_queue(self):
        """Process import, row, and thumbnail UI work in bounded batches."""
        row_limit = config.UI_QUEUE_BATCH_SIZE
        event_limit = config.UI_QUEUE_BATCH_SIZE * 2
        processed_rows = 0
        touched_groups = {}
        try:
            while event_limit > 0:
                item = self.ui_queue.get_nowait()
                action = item[0]
                if action == "import_complete":
                    self._handle_import_complete(*item[1:])
                elif action == "thumbnail":
                    self._apply_thumbnail_result(*item[1:])
                elif action == "add":
                    f, p, g = item[1:4]
                    preview_requested = item[4] if len(item) > 4 else True
                    if self._group_widget_exists(g):
                        self._create_row(
                            f,
                            p,
                            g,
                            preview_requested=preview_requested,
                            refresh=False,
                        )
                        self._mark_group_touched(touched_groups, g, f)
                        processed_rows += 1
                event_limit -= 1
        except queue.Empty:
            pass

        while row_limit > 0 and self.__dict__.get("pending_ui_rows"):
            epoch, f, g, preview_requested = self.pending_ui_rows.popleft()
            if not self._is_import_epoch_current(epoch) or not self._group_widget_exists(g):
                with self.lock:
                    self.pending_filepaths.discard(f)
                row_limit -= 1
                continue
            self._create_row(
                f,
                None,
                g,
                preview_requested=preview_requested,
                thumbnail_pending=preview_requested,
                refresh=False,
            )
            self._mark_group_touched(touched_groups, g, f)
            processed_rows += 1
            row_limit -= 1

        if touched_groups:
            self._finish_ui_row_batch(touched_groups)

        remaining = len(self.__dict__.get("pending_ui_rows", []) or [])
        if processed_rows > 0 and (self.ui_queue.qsize() > 100 or remaining > 100):
            logger.debug(
                f"UI queue processed {processed_rows} rows, "
                f"{self.ui_queue.qsize()} events and {remaining} rows remaining"
            )

    def _mark_group_touched(
        self, touched_groups: Dict[int, Any], group_widget: Any, filepath: str
    ) -> None:
        touched = touched_groups.setdefault(
            id(group_widget), {"group": group_widget, "files": []}
        )
        touched["files"].append(filepath)

    def _finish_ui_row_batch(self, touched_groups: Dict[int, Dict[str, Any]]) -> None:
        for touched in touched_groups.values():
            group = touched["group"]
            if self._group_widget_exists(group):
                self._apply_auto_covers_to_group(group, touched["files"])
        with self.lock:
            file_count = len(self.file_widgets)
        remaining = len(self.__dict__.get("pending_ui_rows", []) or [])
        self.lbl_eta.configure(
            text=(
                f"Loading files... {remaining} remaining"
                if remaining
                else f"Files: {file_count}"
            )
        )
        self._refresh_queue_state()

    def _apply_thumbnail_result(self, epoch: Optional[int], fp: str, pil_image: Any) -> None:
        self._ensure_import_state()
        if not self._is_import_epoch_current(epoch):
            return

        with self.lock:
            row_data = self.file_widgets.get(fp)
            if row_data is None:
                self.pending_thumbnails[fp] = (pil_image,)
                return

        label = row_data.get("thumbnail_label")
        if not label:
            row_data["thumbnail_pending"] = False
            return

        old_ref = row_data.get("image_ref")
        if pil_image:
            img_widget = ctk.CTkImage(
                light_image=pil_image, dark_image=pil_image, size=config.UI_THUMB_SIZE
            )
            try:
                label.configure(image=img_widget, text="")
            except (tk.TclError, AttributeError):
                return
            row_data["image_ref"] = img_widget
            self.image_refs.add(img_widget)
            if old_ref and old_ref in self.image_refs:
                self.image_refs.discard(old_ref)
        else:
            try:
                label.configure(image=None, text="No preview")
            except (tk.TclError, AttributeError, TypeError):
                label.configure(text="No preview")
            row_data["image_ref"] = None

        row_data["thumbnail_pending"] = False

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

    def _create_row(
        self,
        fp,
        pil_image,
        group_widget,
        preview_requested=True,
        thumbnail_pending=False,
        refresh=True,
    ):
        """Create a UI row for a file with thumbnail, status, and progress bar.

        Args:
            fp: File path to the image
            pil_image: PIL Image object for thumbnail (or None)
            group_widget: CollapsibleGroupFrame to add the row to
        """
        self._ensure_import_state()
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
            image_label = ctk.CTkLabel(
                row,
                text="Loading..." if thumbnail_pending else "No preview",
                width=78,
                text_color="gray",
            )
            image_label.pack(side="left", padx=5)
        else:
            image_label = None
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
                "thumbnail_label": image_label,
                "thumbnail_pending": thumbnail_pending,
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
            self.pending_filepaths.discard(fp)
        if refresh:
            self._apply_auto_covers_to_group(group_widget)
            self.lbl_eta.configure(text=f"Files: {file_count}")
            self._refresh_queue_state()

        pending_thumbnail = self.pending_thumbnails.pop(fp, None)
        if pending_thumbnail is not None:
            self._apply_thumbnail_result(None, fp, pending_thumbnail[0])

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
        row_data.pop("upload_result", None)
        group = row_data.get("group")
        if group is not None and hasattr(group, "is_completed"):
            group.is_completed = False
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
            self.add_activity(f"Could not copy error for {os.path.basename(filepath)}.", "warning")

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
            failed = 0
            for f in group.files:
                with self.lock:
                    if f in self.file_widgets:
                        state = self.file_widgets[f]["state"]
                        if state in ["success", "failed"]:
                            done += 1
                            if state == "failed":
                                failed += 1
            group.prog.set(done / total)
            group.lbl_counts.configure(text=f"({done}/{total})")
            if done == total and not group.is_completed:
                if failed:
                    group.mark_complete()
                    self.log(
                        f"Warning: Output skipped for '{group.title}' because "
                        f"{failed} upload(s) failed."
                    )
                    self.add_activity(
                        f"Skipped output for {group.title}: {failed} upload(s) failed.",
                        "warning",
                    )
                    self.generate_failed_group_output(group, failed)
                elif self._group_has_complete_results(group):
                    group.mark_complete()
                    self.generate_group_output(group)
                else:
                    logger.debug(
                        f"Waiting for upload result URLs before completing group '{group.title}'."
                    )
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

    def _on_upload_complete(self):
        self.is_uploading = False
        self._refresh_start_button_state()
        self._configure_stop_button(False)
        self.overall_progress.set(1.0)
        self.overall_progress.configure(progress_color="#34C759")
        summary = self._build_completion_summary()
        self.lbl_eta.configure(text=summary["status_text"])
        self.add_activity(
            summary["status_text"], "warning" if summary["failed_count"] else "success"
        )

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
        copyable_output_files = list(self.__dict__.get("copyable_output_files", output_files))
        auto_copy_requested = bool(self.var_auto_copy.get())
        has_copy_text = bool(self.clipboard_buffer or copyable_output_files)

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
            "copyable_output_files": copyable_output_files,
            "auto_copy_requested": auto_copy_requested,
            "copied_to_clipboard": False,
            "has_copy_text": has_copy_text,
            "status_text": status_text,
        }

    def _completion_output_text(self, summary: Dict[str, Any]) -> str:
        if self.clipboard_buffer:
            return "\n\n".join(self.clipboard_buffer)

        chunks = []
        output_files = summary.get("copyable_output_files")
        if output_files is None:
            output_files = summary.get("output_files", [])

        for output_file in output_files:
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

    def _upload_result_map(self) -> Dict[str, Tuple[str, str]]:
        res_map = {}
        for fp, viewer_url, thumb_url in self.__dict__.get("results", []):
            viewer_url = str(viewer_url or "").strip()
            thumb_url = str(thumb_url or "").strip()
            if viewer_url:
                res_map[fp] = (viewer_url, thumb_url)

        file_widgets = self.__dict__.get("file_widgets", {})
        lock = self.__dict__.get("lock")
        if lock is not None:
            with lock:
                stored_results = {
                    fp: data.get("upload_result")
                    for fp, data in file_widgets.items()
                    if isinstance(data, dict)
                }
        else:
            stored_results = {
                fp: data.get("upload_result")
                for fp, data in file_widgets.items()
                if isinstance(data, dict)
            }

        for fp, result in stored_results.items():
            if not result:
                continue
            try:
                viewer_url, thumb_url = result[:2]
            except (TypeError, ValueError):
                continue
            viewer_url = str(viewer_url or "").strip()
            thumb_url = str(thumb_url or "").strip()
            if viewer_url:
                res_map[fp] = (viewer_url, thumb_url)
        return res_map

    def _group_has_complete_results(self, group) -> bool:
        group_files = self._ordered_group_files_for_output(group)
        if not group_files:
            return False
        res_map = self._upload_result_map()
        return all(fp in res_map for fp in group_files)

    def stop_upload(self):
        self.cancel_event.set()
        self.lbl_eta.configure(text="Stopping...")
        self.add_activity("Stopping upload after current work finishes.", "warning")

    def generate_group_output(self, group):
        res_map = self._upload_result_map()
        group_results = []
        svc = config.normalize_service_id(self.settings.get("service", ""))
        group_files = self._ordered_group_files_for_output(group)

        if not group_files:
            self.log(f"Warning: Output skipped for '{group.title}' because the group has no files.")
            self.add_activity(f"Skipped output for {group.title}: no files in group.", "warning")
            return

        for fp in group_files:
            if fp in res_map:
                val = res_map[fp]
                viewer_url = val[0]
                thumb_url = val[1]
                direct_url = viewer_url
                if svc == "imx.to":
                    if "/t/" in thumb_url:
                        direct_url = thumb_url.replace("/t/", "/i/")
                group_results.append((viewer_url, thumb_url, direct_url))

        if len(group_results) != len(group_files):
            self.log(
                f"Warning: Output skipped for '{group.title}' because "
                f"only {len(group_results)}/{len(group_files)} upload result(s) were usable."
            )
            self.add_activity(
                f"Skipped output for {group.title}: incomplete upload results.",
                "warning",
            )
            return

        gallery = self._gallery_for_group(group, svc, self.settings) or {}
        gal_id = str(gallery.get("id") or "")
        cover_url = group_results[0][1] if group_results else ""

        # Get thumbnail size for BBCode formatting
        thumb_size = "250"  # Default
        if svc == "imx.to":
            thumb_size = self.settings.get("imx_thumb", "180")
        elif svc == config.PIXHOST_SERVICE_ID:
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
            if "copyable_output_files" not in self.__dict__:
                self.copyable_output_files = []
            self.copyable_output_files.append(out_name)
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
            elif svc == config.PIXHOST_SERVICE_ID and self.var_pix_links.get():
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

    def generate_failed_group_output(self, group, failed_count: Optional[int] = None):
        res_map = self._upload_result_map()
        group_files = self._ordered_group_files_for_output(group)
        svc = config.normalize_service_id(self.settings.get("service", ""))

        try:
            from modules.file_handler import sanitize_filename

            batch_name = self._batch_display_name(group)
            safe_title = sanitize_filename(group.title) or "Batch"
            now = datetime.now()
            ts = now.strftime("%Y%m%d_%H%M")
            out_dir = getattr(self, "output_dir", "Output")
            os.makedirs(out_dir, exist_ok=True)

            lines = [
                f"Batch: {batch_name}",
                "Status: FAILED",
                f"Service: {svc or 'Unknown'}",
                f"Generated: {now.strftime('%Y-%m-%d %H:%M:%S')}",
            ]
            if failed_count is not None:
                lines.append(f"Failed uploads: {failed_count}")
            lines.extend(["", "Files:"])

            for fp in group_files:
                with self.lock:
                    row_data = dict(self.file_widgets.get(fp, {}))
                state = str(row_data.get("state") or "pending").strip().lower()
                error = str(row_data.get("error") or "").strip()
                name = os.path.basename(fp)
                if state == "success":
                    lines.append(f"- {name}: Uploaded")
                    viewer_url, thumb_url = res_map.get(fp, ("", ""))
                    if viewer_url:
                        lines.append(f"  URL: {viewer_url}")
                    if thumb_url:
                        lines.append(f"  Thumb: {thumb_url}")
                elif state == "failed":
                    lines.append(f"- {name}: FAILED")
                    lines.append(f"  Reason: {error or 'Upload failed without more detail.'}")
                else:
                    lines.append(f"- {name}: {state.title() or 'Pending'}")
                lines.append(f"  Path: {fp}")

            text = "\n".join(lines) + "\n"
            out_name = os.path.join(out_dir, f"{safe_title}_{ts}_FAILED.txt")
            with open(out_name, "w", encoding="utf-8") as f:
                f.write(text)
            self.current_output_files.append(out_name)

            history_dir = getattr(self, "central_history_path", "")
            if history_dir:
                os.makedirs(history_dir, exist_ok=True)
                central_name = os.path.join(history_dir, f"{safe_title}_{ts}_FAILED.txt")
                with open(central_name, "w", encoding="utf-8") as f:
                    f.write(text)

            self.btn_open.configure(state="normal")
            self.log(f"Saved failed batch report: {out_name}")
            self.add_activity(
                f"Saved failed batch report: {os.path.basename(out_name)}.",
                "warning",
            )
        except Exception as e:
            self.log(f"Error writing failed batch report: {e}")
            self.add_activity(f"Error writing failed batch report: {e}", "error")

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
                messagebox.showerror(
                    "Error", f"Could not open output folder:\n{folder}\n\nError: {str(e)}"
                )
        else:
            logger.warning("No output files available to open folder")
            message = "No output files have been generated yet."
            self.lbl_eta.configure(text=message)
            self.add_activity(message, "warning")

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
        self._clear_import_work()
        self.is_uploading = False
        self.upload_count = 0
        self.upload_total = 0
        self.group_counter = 0
        self.current_output_files = []
        self.copyable_output_files = []
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

    def _clear_import_work(self) -> None:
        self._ensure_import_state()
        with self.lock:
            self.import_epoch += 1
            self.active_import_ids.clear()
            self.pending_filepaths.clear()
            self.pending_ui_rows.clear()
            self.pending_thumbnails.clear()
        try:
            while True:
                self.ui_queue.get_nowait()
        except queue.Empty:
            pass

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
