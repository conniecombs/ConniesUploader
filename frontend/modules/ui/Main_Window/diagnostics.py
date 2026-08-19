# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Diagnostics behavior for the main window."""

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

# Session-only activity panel colors (success green / failure red).
_ACTIVITY_LEVEL_COLORS = {
    "success": "#34C759",
    "error": "#FF453A",
    "warning": "#FFB340",
    "info": "#A8B2C1",
}

_ACTIVITY_MAX_EVENTS = 200


class DiagnosticsMixin:
    def add_activity(self, message: str, level: str = "info") -> None:
        """Append a session-only activity line (no disk I/O)."""
        level_key = str(level or "info").strip().lower() or "info"
        if level_key not in _ACTIVITY_LEVEL_COLORS:
            level_key = "info"

        timestamp = datetime.now().strftime("%H:%M:%S")
        event = {
            "time": timestamp,
            "message": str(message),
            "level": level_key,
        }
        events = getattr(self, "activity_events", None)
        if events is None:
            self.activity_events = []
            events = self.activity_events
        events.append(event)
        if len(events) > _ACTIVITY_MAX_EVENTS:
            del events[: len(events) - _ACTIVITY_MAX_EVENTS]

        self._append_activity_ui(event)

    def _append_activity_ui(self, event: Dict[str, str]) -> None:
        textbox = self.__dict__.get("activity_text")
        if textbox is None:
            return

        level = event.get("level", "info")
        line = f"{event['time']}  {event['message']}\n"
        try:
            textbox.configure(state="normal")
            # Drop the empty-state placeholder on first real event.
            if getattr(self, "_activity_placeholder_active", False):
                textbox.delete("1.0", "end")
                self._activity_placeholder_active = False

            start = textbox.index("end-1c")
            textbox.insert("end", line)
            end = textbox.index("end-1c")
            tag = f"level_{level}"
            textbox.tag_add(tag, start, end)
            # Keep the visible buffer aligned with in-memory cap.
            line_count = int(float(textbox.index("end-1c").split(".")[0]))
            if line_count > _ACTIVITY_MAX_EVENTS:
                textbox.delete("1.0", f"{line_count - _ACTIVITY_MAX_EVENTS + 1}.0")
            textbox.see("end")
            textbox.configure(state="disabled")
            self._show_activity_panel()
        except Exception as exc:
            logger.debug(f"Could not update activity panel: {exc}")

    def _show_activity_panel(self) -> None:
        panel = self.__dict__.get("activity_panel")
        if panel is None:
            return
        if not panel.winfo_ismapped():
            footer = self.__dict__.get("queue_footer")
            pack_kwargs = {"fill": "x", "padx": 5, "pady": (0, 4)}
            if footer is not None:
                panel.pack(before=footer, **pack_kwargs)
            else:
                panel.pack(**pack_kwargs)

    def _hide_activity_panel(self) -> None:
        panel = self.__dict__.get("activity_panel")
        if panel is not None and panel.winfo_ismapped():
            panel.pack_forget()

    def clear_activity(self) -> None:
        """Clear the current-session activity view."""
        self.activity_events = []
        textbox = self.__dict__.get("activity_text")
        if textbox is None:
            return
        try:
            textbox.configure(state="normal")
            textbox.delete("1.0", "end")
            textbox.insert("end", "Session activity will appear here.\n")
            textbox.tag_add("level_info", "1.0", "end-1c")
            textbox.configure(state="disabled")
            self._activity_placeholder_active = True
        except Exception as exc:
            logger.debug(f"Could not clear activity panel: {exc}")

    def copy_activity(self) -> None:
        """Copy selected activity text, or the full session log if nothing is selected."""
        textbox = self.__dict__.get("activity_text")
        if textbox is None:
            return
        try:
            try:
                selected = textbox.selection_get()
            except tk.TclError:
                selected = ""
            if selected and selected.strip():
                text = selected
            else:
                # Full session buffer (skip placeholder).
                if getattr(self, "_activity_placeholder_active", False):
                    text = ""
                else:
                    textbox.configure(state="normal")
                    text = textbox.get("1.0", "end-1c")
                    textbox.configure(state="disabled")
            if not text.strip():
                self.add_activity("Nothing to copy from activity.", "warning")
                return
            pyperclip.copy(text)
            # Avoid recursion noise: use a direct UI-less path if copy was of activity.
            # Still show a short confirmation as success (green).
            events = getattr(self, "activity_events", None)
            if events is None:
                self.activity_events = []
            # Use private append to avoid infinite loop if copy fails oddly.
            timestamp = datetime.now().strftime("%H:%M:%S")
            event = {
                "time": timestamp,
                "message": "Copied activity to clipboard.",
                "level": "success",
            }
            self.activity_events.append(event)
            if len(self.activity_events) > _ACTIVITY_MAX_EVENTS:
                del self.activity_events[: len(self.activity_events) - _ACTIVITY_MAX_EVENTS]
            self._append_activity_ui(event)
        except Exception as exc:
            logger.warning(f"Could not copy activity: {exc}")
            messagebox.showerror("Copy Activity", f"Could not copy activity text:\n\n{exc}")

    def log(self, msg: str) -> None:
        """Developer/debug path — logger only (not the session activity panel)."""
        logger.info(msg)

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

        # Stop Python-owned ViperGirls scheduler
        if hasattr(self, "viper_scheduler") and self.viper_scheduler:
            logger.info("Stopping ViperGirls scheduler...")
            try:
                self.viper_scheduler.stop()
            except Exception as e:
                logger.warning(f"Error stopping ViperGirls scheduler: {e}")

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

        # Shutdown import executor
        if hasattr(self, "import_executor") and self.import_executor:
            logger.info("Shutting down import executor...")
            try:
                self.import_executor.shutdown(wait=False, cancel_futures=True)
            except Exception as e:
                logger.warning(f"Error shutting down import_executor: {e}")

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

        logger.info("Graceful shutdown complete")

        # Finally, quit the application
        self.quit()
