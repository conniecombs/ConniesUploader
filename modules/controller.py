# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/controller.py
import threading
import queue
import time
import os
import pyperclip
import platform
import subprocess
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from loguru import logger

from . import api, config, viper_api
from .upload_manager import UploadManager
from .template_manager import TemplateManager


class RenameWorker(threading.Thread):
    def __init__(self, creds: Dict[str, Any]) -> None:
        super().__init__(daemon=True)
        self.creds = creds
        self.queue: queue.Queue = queue.Queue(maxsize=200)
        self.active: bool = True

    def add_task(self, service: str, gallery_id: str, new_name: str) -> None:
        self.queue.put((service, gallery_id, new_name))

    def run(self) -> None:
        while self.active:
            try:
                task = self.queue.get(timeout=1)
                service, gid, name = task
                if service == "imx.to":
                    logger.info(f"RenameWorker: Renaming {gid} to {name}")
                    try:
                        client = api.create_resilient_client()
                        # Add rename logic here if needed, or rely on API module
                        # (The original code had the worker but empty logic in the try block,
                        # keeping structure for future implementation)
                        client.close()
                    except Exception as e:
                        logger.error(f"Rename failed: {e}")
            except queue.Empty:
                pass
            except Exception as e:
                logger.error(f"Rename worker error: {e}")

    def stop(self) -> None:
        self.active = False


class UploadController:
    def __init__(self) -> None:
        self.progress_queue = queue.Queue(maxsize=1000)
        self.ui_queue = queue.Queue(maxsize=500)
        self.result_queue = queue.Queue(maxsize=1000)
        self.cancel_event = threading.Event()

        self.upload_manager = UploadManager(
            self.progress_queue, self.result_queue, self.cancel_event
        )
        self.template_mgr = TemplateManager()

        self.results = []
        self.clipboard_buffer = []
        self.current_output_files = []
        self.pix_galleries_to_finalize = []

        self.upload_total = 0
        self.upload_count = 0
        self.is_uploading = False

        # Auto-Post State
        self.post_holding_pen = {}
        self.next_post_index = 0
        self.post_processing_lock = threading.Lock()

        self.rename_worker = None
        self.creds = {}

    def start_workers(self, creds: Dict[str, Any]) -> None:
        """Start background workers (currently unused - RenameWorker disabled).

        RenameWorker is not currently used as there are no enqueue() calls in the codebase.
        Kept for potential future implementation of gallery renaming functionality.
        """
        self.creds = creds
        # RenameWorker initialization disabled - no active usage found
        # if not self.rename_worker or not self.rename_worker.is_alive():
        #     self.rename_worker = RenameWorker(self.creds)
        #     self.rename_worker.start()

    def start_upload(
        self,
        pending_files_map: Dict[str, List[str]],
        settings: Dict[str, Any],
        creds: Dict[str, Any],
    ) -> None:
        """Start the upload process for all pending files.

        Args:
            pending_files_map: Dict mapping group titles to lists of file paths
            settings: User settings dict containing service configs
            creds: Credentials dict for authentication
        """
        self.creds = creds
        self.settings = settings
        self.cancel_event.clear()
        self.results = []
        self.current_output_files = []
        self.clipboard_buffer = []
        self.pix_galleries_to_finalize = []

        # Reset counters
        self.upload_total = sum(len(files) for files in pending_files_map.values())
        self.upload_count = 0
        self.is_uploading = True

        # Reset Auto-Post
        self.next_post_index = 0
        self.post_holding_pen = {}

        if settings.get("auto_post_enabled"):
            threading.Thread(target=self._process_post_queue, daemon=True).start()

        self.upload_manager.start_batch(pending_files_map, settings, creds)

    def stop_upload(self) -> None:
        """Signal all upload threads to stop gracefully."""
        self.cancel_event.set()

    def handle_upload_result(self, fp: str, img: str, thumb: str) -> bool:
        self.results.append((fp, img, thumb))
        self.upload_count += 1
        return self.upload_count >= self.upload_total

    def finalize_upload(self) -> None:
        if self.pix_galleries_to_finalize:
            logger.info("Finalizing Pixhost Galleries...")
            client = api.create_resilient_client()
            for gal in self.pix_galleries_to_finalize:
                try:
                    api.finalize_pixhost_gallery(
                        gal.get("gallery_upload_hash"), gal.get("gallery_hash"), client=client
                    )
                except Exception as e:
                    logger.error(f"Pixhost finalize error: {e}")
            client.close()

        self.is_uploading = False

        # Copy to clipboard if needed
        if self.settings.get("auto_copy") and self.clipboard_buffer:
            try:
                pyperclip.copy("\n\n".join(self.clipboard_buffer))
            except (OSError, pyperclip.PyperclipException) as e:
                logger.warning(f"Could not copy to clipboard: {e}")

    def generate_group_output(
        self, group_title: str, group_files: List[str], gallery_id: Optional[str], batch_index: int
    ) -> None:
        # Map file paths to results
        res_map = {r[0]: (r[1], r[2]) for r in self.results}
        group_results = []
        svc = self.settings.get("service", "")

        for fp in group_files:
            if fp in res_map:
                viewer_url, thumb_url = res_map[fp]
                direct_url = viewer_url

                # Fix direct links for IMX
                if svc == "imx.to" and "/t/" in thumb_url:
                    direct_url = thumb_url.replace("/t/", "/i/")

                group_results.append((viewer_url, thumb_url, direct_url))

        if not group_results:
            logger.warning(f"No successful uploads for '{group_title}'.")
            return

        # Prepare Template Context
        cover_url = group_results[0][1] if group_results else ""
        gal_link = ""
        if gallery_id:
            if svc == "pixhost.to":
                gal_link = f"https://pixhost.to/gallery/{gallery_id}"
            elif svc == "imx.to":
                gal_link = f"https://imx.to/g/{gallery_id}"
            elif svc == "vipr.im":
                gal_link = f"https://vipr.im/f/{gallery_id}"

        # Get thumbnail size for BBCode formatting
        thumb_size = "250"  # Default
        if svc == "imx.to":
            thumb_size = self.settings.get("imx_thumb", "180")
        elif svc == "pixhost.to":
            thumb_size = self.settings.get("pix_thumb", "200")
        elif svc == "turboimagehost":
            thumb_size = self.settings.get("turbo_thumb", "180")
        elif svc == "imagebam.com":
            thumb_size = self.settings.get("imagebam_thumb", "180")

        ctx = {
            "gallery_link": gal_link,
            "gallery_name": group_title,
            "gallery_id": gallery_id,
            "cover_url": cover_url,
            "thumb_size": thumb_size,
        }

        # Generate Text
        text = self.template_mgr.apply(
            self.settings.get("output_format", "BBCode"), ctx, group_results
        )

        # Save to File
        try:
            safe_title = "".join(
                c for c in group_title if c.isalnum() or c in (" ", "_", "-")
            ).strip()
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            out_dir = "Output"
            os.makedirs(out_dir, exist_ok=True)

            out_name = os.path.join(out_dir, f"{safe_title}_{ts}.txt")
            with open(out_name, "w", encoding="utf-8") as f:
                f.write(text)
            self.current_output_files.append(out_name)
            logger.info(f"Saved: {out_name}")

            # Central History
            history_path = os.path.join(os.path.expanduser("~"), ".conniesuploader", "history")
            os.makedirs(history_path, exist_ok=True)
            with open(
                os.path.join(history_path, f"{safe_title}_{ts}.txt"), "w", encoding="utf-8"
            ) as f:
                f.write(text)

            # Auto-Copy Buffer
            if self.settings.get("auto_copy"):
                self.clipboard_buffer.append(text)

            # Auto-Post Handoff
            if self.settings.get("auto_post_enabled"):
                with self.post_processing_lock:
                    self.post_holding_pen[batch_index] = text

            # Links.txt generation
            need_links = False
            if svc == "imx.to" and self.settings.get("imx_links"):
                need_links = True
            elif svc == "pixhost.to" and self.settings.get("pix_links"):
                need_links = True
            elif svc == "turboimagehost" and self.settings.get("turbo_links"):
                need_links = True
            elif svc == "vipr.im" and self.settings.get("vipr_links"):
                need_links = True

            if need_links:
                links_name = os.path.join(out_dir, f"{safe_title}_{ts}_links.txt")
                raw_links = "\n".join([r[0] for r in group_results])
                with open(links_name, "w", encoding="utf-8") as f:
                    f.write(raw_links)

        except Exception as e:
            logger.error(f"Error writing output: {e}")

        return out_name

    def _process_post_queue(self) -> None:
        logger.info("Auto-Post Queue: Started.")
        user = self.creds.get("vg_user")
        pwd = self.creds.get("vg_pass")
        thread_name = self.settings.get("auto_post_thread")

        saved_threads = viper_api.load_saved_threads()
        if not user or not pwd or not thread_name or thread_name not in saved_threads:
            logger.error("Auto-Post Queue: Invalid credentials or thread. Aborting.")
            return

        thread_url = saved_threads[thread_name].get("url")
        # Extract Thread ID
        import re

        tid = None
        match = re.search(r"threads/(\d+)", thread_url) or re.search(r"t=(\d+)", thread_url)
        if match:
            tid = match.group(1)

        if not tid:
            logger.error("Auto-Post Queue: Invalid Thread ID.")
            return

        vg = viper_api.ViperGirlsAPI()
        if not vg.login(user, pwd):
            logger.error("Auto-Post Queue: Login Failed.")
            return

        while self.is_uploading or len(self.post_holding_pen) > 0:
            if self.cancel_event.is_set():
                break

            if self.next_post_index in self.post_holding_pen:
                content = self.post_holding_pen.pop(self.next_post_index)
                logger.info(f"Auto-Post Queue: Posting Batch #{self.next_post_index}...")

                if vg.post_reply(tid, content):
                    logger.info(f"Auto-Post Queue: Batch #{self.next_post_index} SUCCESS.")
                else:
                    logger.error(f"Auto-Post Queue: Batch #{self.next_post_index} FAILED.")

                self.next_post_index += 1
                time.sleep(config.POST_COOLDOWN_SECONDS)
            else:
                time.sleep(0.5)
        logger.info("Auto-Post Queue: Finished.")

    def open_output_folder(self) -> None:
        if self.current_output_files:
            folder = os.path.dirname(os.path.abspath(self.current_output_files[0]))
            if platform.system() == "Windows":
                os.startfile(folder)
            else:
                subprocess.run(["xdg-open", folder], check=False, shell=False)
