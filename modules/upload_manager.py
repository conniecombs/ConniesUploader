# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Upload orchestration between the UI, plugins, and Go sidecar."""

from __future__ import annotations

import os
import queue
import threading
from typing import Any, Dict, List, Tuple

from loguru import logger

from .plugin_manager import PluginManager
from .sidecar import SidecarBridge


SERVICE_THREAD_KEYS = {
    "imx.to": "imx_threads",
    "pixhost.to": "pix_threads",
    "turboimagehost": "turbo_threads",
    "vipr.im": "vipr_threads",
    "imagebam.com": "imagebam_threads",
    "imgur.com": "imgur_threads",
}


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
        self.plugin_manager = PluginManager()

        self.event_queue: queue.Queue = queue.Queue(maxsize=1000)
        self.listener_thread: threading.Thread | None = None
        self.dispatch_thread: threading.Thread | None = None
        self._lifecycle_lock = threading.RLock()
        self._listener_registered = False
        self._stop_events = threading.Event()

    def start_batch(
        self, pending_by_group: Dict[Any, List[str]], cfg: Dict[str, Any], creds: Dict[str, str]
    ) -> None:
        """Submit a batch of groups to the persistent Go sidecar."""
        with self._lifecycle_lock:
            self._stop_events.clear()

            if not self._listener_registered:
                self.bridge.add_listener(self.event_queue)
                self._listener_registered = True

            if not self.listener_thread or not self.listener_thread.is_alive():
                self.listener_thread = threading.Thread(
                    target=self._process_events,
                    name="UploadManagerEvents",
                    daemon=True,
                )
                self.listener_thread.start()

            if self.dispatch_thread and self.dispatch_thread.is_alive():
                logger.warning("Upload dispatch already running; ignoring duplicate start request")
                return

            self.dispatch_thread = threading.Thread(
                target=self._dispatch_jobs,
                args=(pending_by_group, cfg, creds),
                name="UploadManagerDispatch",
                daemon=True,
            )
            self.dispatch_thread.start()

    def _dispatch_jobs(
        self, pending_by_group: Dict[Any, List[str]], cfg: Dict[str, Any], creds: Dict[str, str]
    ) -> None:
        """Send job JSON payloads to the Go process via the sidecar bridge."""
        logger.info("--- Starting Phase 1: Gallery Creation ---")

        try:
            for group_obj, files in pending_by_group.items():
                if self.cancel_event.is_set():
                    return

                service_id = cfg.get("service", "")
                plugin = self.plugin_manager.get_plugin(service_id)

                if plugin and hasattr(plugin, "prepare_group"):
                    try:
                        context: Dict[str, Any] = {}
                        temp_cfg = cfg.copy()
                        plugin.prepare_group(group_obj, temp_cfg, context, creds)

                        for gal_data in context.get("created_galleries", []):
                            self.progress_queue.put(("register_pix_gal", None, gal_data))
                            logger.info(
                                f"Registered gallery for finalization: {gal_data.get('gallery_hash')}"
                            )
                    except Exception as exc:
                        logger.error(f"Failed to prepare group {group_obj.title}: {exc}")

            logger.info("--- Starting Phase 2: Upload Dispatch ---")

            for group_obj, files in pending_by_group.items():
                if self.cancel_event.is_set():
                    break

                group_cfg = cfg.copy()

                pix_data = getattr(group_obj, "pix_data", None)
                if isinstance(pix_data, dict):
                    gallery_upload_hash = pix_data.get("gallery_upload_hash")
                    if gallery_upload_hash:
                        group_cfg["gallery_upload_hash"] = gallery_upload_hash

                if hasattr(group_obj, "gallery_id") and group_obj.gallery_id:
                    gid = group_obj.gallery_id
                    group_cfg["gallery_id"] = gid
                    group_cfg["gallery_hash"] = gid
                    group_cfg["pix_gallery_hash"] = gid
                    logger.info(f"Group '{group_obj.title}' attached to Gallery ID: {gid}")
                elif not group_cfg.get("gallery_hash"):
                    manual_hash = (
                        group_cfg.get("gallery_id", "") or group_cfg.get("pix_gallery_hash", "")
                    ).strip()
                    if manual_hash:
                        group_cfg["gallery_hash"] = manual_hash
                        logger.info(f"Group '{group_obj.title}' using manual gallery hash: {manual_hash}")

                cover_cnt = self._cover_count_for_service(group_cfg)
                covers: List[str] = []
                standards: List[str] = []

                for file_path in files:
                    try:
                        idx = group_obj.files.index(file_path)
                        if idx < cover_cnt:
                            covers.append(file_path)
                        else:
                            standards.append(file_path)
                    except ValueError:
                        standards.append(file_path)

                if covers:
                    cover_cfg = group_cfg.copy()
                    cover_cfg["imx_thumb"] = "600"
                    cover_cfg["pix_thumb"] = "500"
                    cover_cfg["turbo_thumb"] = "600"
                    cover_cfg["vipr_thumb"] = "800x800"
                    cover_cfg["imagebam_thumb"] = "300"
                    if "pix" in group_cfg.get("service", ""):
                        cover_cfg["thumbnail_size"] = "500"
                    self._send_job(covers, cover_cfg, creds)

                if standards:
                    self._send_job(standards, group_cfg, creds)
        finally:
            logger.info("Upload dispatch finished")

    @staticmethod
    def _cover_count_for_service(cfg: Dict[str, Any]) -> int:
        """Return configured cover count for the selected service."""
        service_id = cfg.get("service", "")
        key = None
        if "imx" in service_id:
            key = "imx_cover_count"
        elif "pix" in service_id:
            key = "pix_cover_count"
        elif "turbo" in service_id:
            key = "turbo_cover_count"
        elif "vipr" in service_id:
            key = "vipr_cover_count"

        if key is None:
            return 0

        try:
            return max(0, int(cfg.get(key, 0)))
        except (ValueError, TypeError) as exc:
            logger.debug(f"Could not get cover count for {service_id}: {exc}")
            return 0

    def _send_job(self, file_list: List[str], cfg: Dict[str, Any], creds: Dict[str, str]) -> None:
        service_id = cfg["service"]
        job_cfg = self._normalize_job_config(cfg)
        str_config = {k: str(v) for k, v in job_cfg.items()}

        logger.info(f"_send_job for {service_id}: thumbnail_size={cfg.get('thumbnail_size')!r}")

        plugin = self.plugin_manager.get_plugin(service_id)
        if plugin and hasattr(plugin, "build_http_request"):
            try:
                http_spec = plugin.build_http_request(
                    file_path=file_list[0] if file_list else "", config=cfg, creds=creds
                )

                if http_spec:
                    job_data = {
                        "action": "http_upload",
                        "service": service_id,
                        "files": [os.path.normpath(f) for f in file_list],
                        "creds": creds,
                        "config": str_config,
                        "http_spec": http_spec,
                        "context_data": {},
                    }
                    logger.info(f"Using generic HTTP runner for {service_id} ({len(file_list)} files)")
                    self.bridge.send_cmd(job_data)
                    return

            except Exception as exc:
                logger.error(f"Failed to build HTTP request spec for {service_id}: {exc}")
                for file_path in file_list:
                    self.result_queue.put((file_path, "", ""))
                    self.progress_queue.put(("status", file_path, "error: plugin configuration failed"))
                return

        job_data = {
            "action": "upload",
            "service": service_id,
            "files": [os.path.normpath(f) for f in file_list],
            "creds": creds,
            "config": str_config,
        }
        self.bridge.send_cmd(job_data)

    @staticmethod
    def _normalize_job_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Return a sidecar-ready config with service thread controls normalized."""
        normalized = cfg.copy()
        service_id = str(normalized.get("service", ""))
        thread_key = SERVICE_THREAD_KEYS.get(service_id)

        if thread_key and normalized.get(thread_key) not in (None, ""):
            normalized["threads"] = normalized[thread_key]

        try:
            threads = int(normalized.get("threads", 2))
        except (TypeError, ValueError):
            threads = 2

        normalized["threads"] = max(1, threads)
        return normalized

    def _process_events(self) -> None:
        """Read events from the bridge and update UI-facing queues."""
        while not self.cancel_event.is_set() and not self._stop_events.is_set():
            try:
                data = self.event_queue.get(timeout=1)
                evt = data.get("type")
                fp = data.get("file") or data.get("file_path")

                if evt == "status":
                    self.progress_queue.put(("status", fp, data.get("status")))

                elif evt == "result":
                    url = data.get("url")
                    thumb = data.get("thumb")
                    if thumb and "image.imx.to/u/t/" in thumb:
                        thumb = thumb.replace("image.imx.to/u/t/", "i.imx.to/t/")
                    self.result_queue.put((fp, url, thumb))

                elif evt == "batch_complete":
                    logger.debug("SIDECAR: batch complete")

                elif evt == "log":
                    logger.debug(f"SIDECAR: {data.get('msg')}")

                elif evt == "error":
                    logger.error(f"SIDECAR ERROR: {data.get('msg')}")
                    if fp:
                        self.progress_queue.put(("status", fp, f"error: {data.get('msg')}"))

            except queue.Empty:
                continue
            except Exception as exc:
                logger.error(f"Event processing error: {exc}")

    def shutdown(self) -> None:
        """Shutdown the upload manager gracefully."""
        with self._lifecycle_lock:
            self._stop_events.set()
            if self._listener_registered:
                self.bridge.remove_listener(self.event_queue)
                self._listener_registered = False

        if self.listener_thread and self.listener_thread.is_alive():
            self.listener_thread.join(timeout=2.0)
        if self.dispatch_thread and self.dispatch_thread.is_alive():
            self.dispatch_thread.join(timeout=2.0)
        logger.info("UploadManager shut down")
