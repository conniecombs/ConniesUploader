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
from modules.upload_output import generate_group_output as generate_shared_group_output


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
        try:
            output = generate_shared_group_output(
                group,
                self.results,
                self.settings,
                self.template_mgr,
                output_dir=self.__dict__.get("output_dir", config.OUTPUT_DIR),
                history_dir=self.__dict__.get("central_history_path", config.HISTORY_DIR),
                selected_gallery_by_service=self.__dict__.get("selected_gallery_by_service", {}),
                saved_threads_data=self.__dict__.get("saved_threads_data", {}),
            )
        except Exception as e:
            self.log(f"Error writing output: {e}")
            self.add_activity(f"Error writing output: {e}", "error")
            return

        if output is None:
            self.log(f"Warning: No successful uploads for '{group.title}'.")
            self.add_activity(f"No successful uploads for {group.title}.", "warning")
            return

        try:
            self.current_output_files.append(output.output_file)
            self.log(f"Saved: {output.output_file}")
            self.add_activity(
                f"Saved output: {os.path.basename(output.output_file)}.", "success"
            )

            # Queue for auto-posting if needed
            tgt_thread = group.selected_thread
            if tgt_thread and tgt_thread != "Do Not Post":
                self.auto_poster.queue_post(
                    group.batch_index,
                    output.text,
                    tgt_thread,
                    batch_name=self._batch_display_name(group),
                )
                message, level = self._vipergirls_queue_activity(group, tgt_thread)
                self.add_activity(message, level)

            self.lbl_eta.configure(text=f"Saved: {os.path.basename(output.output_file)}")
            self.btn_open.configure(state="normal")
            if self.var_auto_copy.get():
                self.clipboard_buffer.append(output.text)
                try:
                    pyperclip.copy("\n\n".join(self.clipboard_buffer))
                    self.add_activity("Copied output to clipboard.", "success")
                except (OSError, pyperclip.PyperclipException) as e:
                    logger.warning(f"Could not copy to clipboard: {e}")
                    self.add_activity("Could not copy output to clipboard.", "warning")

            if output.links_file:
                self.log(f"Saved Links: {output.links_file}")
                self.add_activity(
                    f"Saved links file: {os.path.basename(output.links_file)}.", "success"
                )

        except Exception as e:
            self.log(f"Error writing output: {e}")
            self.add_activity(f"Error writing output: {e}", "error")

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
