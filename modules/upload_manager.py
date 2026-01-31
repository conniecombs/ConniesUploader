# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/upload_manager.py
import threading
import json
import os
import sys
import queue
from typing import Dict, List, Any, Tuple
from . import config
from loguru import logger
from .sidecar import SidecarBridge
from .plugin_manager import PluginManager


class UploadManager:
    def __init__(
        self,
        progress_queue: "queue.Queue[Tuple[str, str, str]]",
        result_queue: "queue.Queue[Tuple[str, str, str]]",
        cancel_event: threading.Event,
    ) -> None:
        self.progress_queue = progress_queue
        self.result_queue = result_queue
        self.cancel_event = cancel_event
        self.bridge = SidecarBridge.get()
        self.plugin_manager = PluginManager()  # For plugin-driven HTTP requests

        self.event_queue: queue.Queue = queue.Queue(maxsize=1000)
        self.listener_thread: threading.Thread = None

    def start_batch(
        self, pending_by_group: Dict[Any, List[str]], cfg: Dict[str, Any], creds: Dict[str, str]
    ) -> None:
        """
        Submits a batch of groups to the persistent Go sidecar.
        """
        # 1. Register for events
        self.bridge.add_listener(self.event_queue)

        # 2. Start listener thread to process this batch's events
        self.listener_thread = threading.Thread(target=self._process_events, daemon=True)
        self.listener_thread.start()

        # 3. Dispatch jobs asynchronously
        threading.Thread(
            target=self._dispatch_jobs, args=(pending_by_group, cfg, creds), daemon=True
        ).start()

    def _dispatch_jobs(
        self, pending_by_group: Dict[Any, List[str]], cfg: Dict[str, Any], creds: Dict[str, str]
    ) -> None:
        """Sends job JSONs to the Go process via the Bridge."""
        for group_obj, files in pending_by_group.items():
            if self.cancel_event.is_set():
                break

            # --- FIX START: Prepare Group (Create Gallery) ---
            # Create a copy of config so specific gallery IDs don't leak to other groups
            group_cfg = cfg.copy()

            service_id = group_cfg.get("service", "")
            plugin = self.plugin_manager.get_plugin(service_id)

            if plugin and hasattr(plugin, "prepare_group"):
                try:
                    # Pass a mutable context dictionary to capture created galleries
                    context = {}
                    
                    # This call creates the gallery if 'gallery_id' is empty in config
                    # and updates group_cfg['gallery_id'] with the new ID
                    plugin.prepare_group(group_obj, group_cfg, context, creds)
                    
                    # Handle created galleries for finalization (Fix for v1.2.2 regression)
                    if "created_galleries" in context:
                        for gal_data in context["created_galleries"]:
                            # Signal main thread to register this gallery for finalization
                            # Format: ('register_pix_gal', None, gal_data_dict)
                            self.progress_queue.put(('register_pix_gal', None, gal_data))
                            logger.info(f"Registered gallery for finalization: {gal_data.get('gallery_hash')}")
                            
                except Exception as e:
                    logger.error(f"Failed to prepare group {group_obj.title}: {e}")
            # --- FIX END ---

            # Determine configured cover count
            svc = group_cfg.get("service", "")
            cover_cnt = 0
            try:
                if "imx" in svc:
                    cover_cnt = int(group_cfg.get("imx_cover_count", 0))
                elif "pix" in svc:
                    cover_cnt = int(group_cfg.get("pix_cover_count", 0))
                elif "turbo" in svc:
                    cover_cnt = int(group_cfg.get("turbo_cover_count", 0))
                elif "vipr" in svc:
                    cover_cnt = int(group_cfg.get("vipr_cover_count", 0))
            except (ValueError, TypeError) as e:
                logger.debug(f"Could not get cover count for {svc}: {e}")

            covers = []
            standards = []

            for f in files:
                try:
                    idx = group_obj.files.index(f)
                    if idx < cover_cnt:
                        covers.append(f)
                    else:
                        standards.append(f)
                except ValueError:
                    standards.append(f)

            # 1. Send Cover Job (Max Thumbnail Settings)
            if covers:
                cover_cfg = group_cfg.copy()
                cover_cfg["imx_thumb"] = "600"
                cover_cfg["pix_thumb"] = "500"
                cover_cfg["turbo_thumb"] = "600"
                cover_cfg["vipr_thumb"] = "800x800"
                cover_cfg["imagebam_thumb"] = "300"
                self._send_job(covers, cover_cfg, creds)

            # 2. Send Standard Job
            if standards:
                self._send_job(standards, group_cfg, creds)

    def _send_job(self, file_list: List[str], cfg: Dict[str, Any], creds: Dict[str, str]) -> None:
        service_id = cfg["service"]

        # Ensure all config values are strings for Go compatibility
        # Go struct expects map[string]string, but Python JSON dump preserves types (int, bool)
        str_config = {k: str(v) for k, v in cfg.items()}

        # DIAGNOSTIC: Log config being sent to plugin
        logger.info(
            f"_send_job for {service_id}: thumbnail_size={repr(cfg.get('thumbnail_size'))}"
        )

        # NEW: Check if plugin supports generic HTTP runner
        plugin = self.plugin_manager.get_plugin(service_id)
        if plugin and hasattr(plugin, "build_http_request"):
            # Try to build HTTP request spec for first file (as template)
            try:
                # Note: Plugins might expect raw types (ints), so pass original cfg to them
                http_spec = plugin.build_http_request(
                    file_path=file_list[0] if file_list else "", config=cfg, creds=creds
                )

                if http_spec:
                    # Use new generic HTTP runner protocol
                    job_data = {
                        "action": "http_upload",
                        "service": service_id,
                        "files": [os.path.normpath(f) for f in file_list],
                        "creds": creds,
                        # Pass stringified config to Go
                        "config": str_config,
                        "http_spec": http_spec,
                        "context_data": {},
                    }

                    logger.info(
                        f"Using generic HTTP runner for {service_id} ({len(file_list)} files)"
                    )
                    self.bridge.send_cmd(job_data)
                    return

            except Exception as e:
                logger.error(f"Failed to build HTTP request spec for {service_id}: {e}")
                # Send error events for all files in this batch
                for file_path in file_list:
                    self.result_queue.put((file_path, "", ""))
                    self.progress_queue.put(
                        ("status", file_path, "error: plugin configuration failed")
                    )
                return

        # --- Legacy Fallback for Plugins without HTTP Spec ---
        job_data = {
            "action": "upload",
            "service": service_id,
            "files": [os.path.normpath(f) for f in file_list],
            "creds": creds,
            "config": str_config,  # Use stringified config here too
        }
        self.bridge.send_cmd(job_data)

    def _process_events(self) -> None:
        """Reads events from the bridge and updates queues."""
        while not self.cancel_event.is_set():
            try:
                # Timeout allows checking cancel_event periodically
                data = self.event_queue.get(timeout=1)

                evt = data.get("type")
                fp = data.get("file")

                if evt == "status":
                    self.progress_queue.put(("status", fp, data.get("status")))

                elif evt == "result":
                    url = data.get("url")
                    thumb = data.get("thumb")

                    # --- HOTFIX: IMX Server Issue ---
                    # Intercept broken IMX thumbnails (image.imx.to/u/t/) and fix them to i.imx.to/t/
                    if thumb and "image.imx.to/u/t/" in thumb:
                        thumb = thumb.replace("image.imx.to/u/t/", "i.imx.to/t/")

                    self.result_queue.put((fp, url, thumb))

                elif evt == "batch_complete":
                    pass
                
                elif evt == "log":
                    logger.debug(f"SIDECAR: {data.get('msg')}")
                    
                elif evt == "error":
                    logger.error(f"SIDECAR ERROR: {data.get('msg')}")

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Event processing error: {e}")

    def shutdown(self) -> None:
        """Shutdown the upload manager gracefully."""
        self.bridge.remove_listener(self.event_queue)
        if self.listener_thread and self.listener_thread.is_alive():
            self.listener_thread.join(timeout=2.0)
        logger.info("UploadManager shut down")