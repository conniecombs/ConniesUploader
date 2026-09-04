# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Posting behavior for the main window."""

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


class PostingMixin:
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
            viper_client = ViperGirlsAPI()
            from modules.sidecar import SidecarBridge

            viper_client.bridge = SidecarBridge.get()
            success = viper_client.schedule_post(
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
        group_files = self._ordered_group_files_for_output(group)
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
            "folder_size": file_handler.format_file_collection_size(group_files),
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
