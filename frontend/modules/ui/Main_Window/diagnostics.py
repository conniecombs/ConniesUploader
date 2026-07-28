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


class DiagnosticsMixin:
    def add_activity(self, message: str, level: str = "info") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        event = {"time": timestamp, "message": str(message), "level": level}
        self.activity_events.append(event)
        self.activity_events = self.activity_events[-80:]
        self._append_activity_log(event)

    def _append_activity_log(self, event: Dict[str, str]) -> None:
        log_path = self.__dict__.get("activity_log_file")
        if not log_path:
            return

        try:
            log_dir = os.path.dirname(log_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            line = f"{event['time']} [{event.get('level', 'info').upper()}] {event['message']}\n"
            with open(log_path, "a", encoding="utf-8") as log_file:
                log_file.write(line)
        except OSError as exc:
            logger.debug(f"Could not write activity log: {exc}")

    def open_activity_terminal(self) -> None:
        log_path = self.__dict__.get("activity_log_file") or config.ACTIVITY_LOG_FILE
        self.activity_log_file = log_path
        try:
            log_dir = os.path.dirname(log_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            open(log_path, "a", encoding="utf-8").close()
        except OSError as exc:
            messagebox.showerror("Activity Terminal", f"Could not create activity log:\n\n{exc}")
            return

        escaped_path = log_path.replace("'", "''")
        command = (
            f"Write-Host 'Connie''s Uploader activity log'; "
            f"Write-Host '{escaped_path}'; "
            f"Get-Content -LiteralPath '{escaped_path}' -Wait"
        )
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoExit", "-Command", command],
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        except OSError as exc:
            messagebox.showerror("Activity Terminal", f"Could not open PowerShell:\n\n{exc}")

    def toggle_log(self):
        if self.log_window_ref and self.log_window_ref.winfo_exists():
            self.log_window_ref.lift()
        else:
            self.log_window_ref = LogWindow(self, self.log_cache)

    def log(self, msg):
        logger.info(msg)
        if self.log_window_ref and self.log_window_ref.winfo_exists():
            self.log_window_ref.append_log(msg + "\n")
        else:
            self.log_cache.append(msg + "\n")

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

        # Close log window if open
        if self.log_window_ref and self.log_window_ref.winfo_exists():
            try:
                self.log_window_ref.destroy()
            except Exception as e:
                logger.warning(f"Error closing log window: {e}")

        logger.info("Graceful shutdown complete")

        # Finally, quit the application
        self.quit()
