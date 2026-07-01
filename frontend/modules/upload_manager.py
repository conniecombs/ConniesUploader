# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Upload orchestration between the UI, plugins, and Go sidecar."""

from __future__ import annotations

import os
import queue
import threading
from typing import Any, Dict, List, Tuple

from loguru import logger

from . import config
from .gallery_cache import GalleryCache
from .gallery_service import GalleryRecord, gallery_url_for_service
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


COVER_THUMBNAIL_OVERRIDES = {
    "imx.to": {"thumbnail_size": "600", "imx_thumb": "600"},
    "pixhost.to": {"thumbnail_size": "500", "pix_thumb": "500"},
    "turboimagehost": {"thumbnail_size": "600", "turbo_thumb": "600"},
    "vipr.im": {"thumbnail_size": "800x800", "vipr_thumb": "800x800"},
    "imagebam.com": {"thumbnail_size": "300", "imagebam_thumb": "300"},
    "imgur.com": {"thumbnail_size": "h", "imgur_thumb": "h"},
}


SERVICE_RATE_LIMITS = {
    "imx.to": {"requests_per_second": 2.0, "burst_size": 5},
    "pixhost.to": {"requests_per_second": 2.0, "burst_size": 5},
    "turboimagehost": {"requests_per_second": 2.0, "burst_size": 5},
    "vipr.im": {"requests_per_second": 2.0, "burst_size": 5},
    "imagebam.com": {"requests_per_second": 2.0, "burst_size": 5},
}


class UploadManager:
    def __init__(
        self,
        progress_queue: "queue.Queue[Tuple[str, str | None, Any]]",
        result_queue: "queue.Queue[Tuple[str, str, str]]",
        cancel_event: threading.Event,
    ) -> None:
        self.progress_queue = progress_queue
        self.result_queue = result_queue
        self.cancel_event = cancel_event
        self.bridge = SidecarBridge.get()
        self.plugin_manager = PluginManager()

        self.active_files: set[str] = set()
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
        failed_groups: Dict[Any, str] = {}

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
                        failed_groups[group_obj] = str(exc)

            logger.info("--- Starting Phase 2: Upload Dispatch ---")

            for group_obj, files in pending_by_group.items():
                if self.cancel_event.is_set():
                    break

                if group_obj in failed_groups:
                    err_msg = f"error: preparation failed - {failed_groups[group_obj]}"
                    for file_path in files:
                        self.result_queue.put((file_path, "", ""))
                        self.progress_queue.put(("status", file_path, err_msg))
                    continue

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
                    if getattr(group_obj, "gallery_name", ""):
                        group_cfg["selected_gallery_name"] = group_obj.gallery_name
                    if getattr(group_obj, "gallery_url", ""):
                        group_cfg["selected_gallery_url"] = group_obj.gallery_url
                    if getattr(group_obj, "gallery_upload_hash", ""):
                        group_cfg["gallery_upload_hash"] = group_obj.gallery_upload_hash
                    logger.info(f"Group '{group_obj.title}' attached to Gallery ID: {gid}")
                elif not group_cfg.get("gallery_hash"):
                    manual_hash = (
                        group_cfg.get("gallery_id", "") or group_cfg.get("pix_gallery_hash", "")
                    ).strip()
                    if manual_hash:
                        group_cfg["gallery_hash"] = manual_hash
                        logger.info(f"Group '{group_obj.title}' using manual gallery hash: {manual_hash}")

                if service_id == "turboimagehost":
                    for attr_name, config_key in (
                        ("turbo_gallery_create", "turbo_gallery_create"),
                        ("turbo_gallery_name", "turbo_gallery_name"),
                        ("turbo_upload_id", "turbo_upload_id"),
                    ):
                        value = getattr(group_obj, attr_name, None)
                        if value not in (None, ""):
                            group_cfg[config_key] = value

                if service_id == "imagebam.com":
                    gallery_title = getattr(group_obj, "imagebam_gallery_title", None)
                    if gallery_title not in (None, ""):
                        group_cfg["imagebam_gallery_title"] = gallery_title

                if service_id == "imx.to":
                    self._remember_imx_gallery_use(group_obj, group_cfg)

                explicit_covers = self._explicit_cover_files_for_group(group_obj, files)
                if explicit_covers is None:
                    cover_cnt = self._cover_count_for_service(group_cfg)
                    covers = []
                    standards = []

                    for file_path in files:
                        try:
                            idx = group_obj.files.index(file_path)
                            if idx < cover_cnt:
                                covers.append(file_path)
                            else:
                                standards.append(file_path)
                        except ValueError:
                            standards.append(file_path)
                else:
                    cover_set = set(explicit_covers)
                    covers = [file_path for file_path in files if file_path in cover_set]
                    standards = [file_path for file_path in files if file_path not in cover_set]

                if covers:
                    cover_cfg = group_cfg.copy()
                    self._apply_cover_thumbnail_overrides(cover_cfg)
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

        keys = ["cover_count", "cover_limit"]
        if key is not None:
            keys.insert(0, key)

        for candidate in keys:
            value = cfg.get(candidate)
            if value in (None, ""):
                continue
            try:
                return max(0, int(value))
            except (ValueError, TypeError) as exc:
                logger.debug(f"Could not get cover count for {service_id}: {exc}")

        return 0

    @staticmethod
    def _apply_cover_thumbnail_overrides(cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Force cover jobs to the largest exposed thumbnail size for the active host."""
        service_id = str(cfg.get("service", ""))
        overrides = COVER_THUMBNAIL_OVERRIDES.get(service_id, {})
        cfg.update(overrides)
        return cfg

    @staticmethod
    def _remember_imx_gallery_use(group_obj: Any, cfg: Dict[str, Any]) -> None:
        gallery_id = str(
            cfg.get("gallery_id") or cfg.get("selected_gallery_id") or cfg.get("imx_gallery_id") or ""
        ).strip()
        if not gallery_id:
            return

        gallery_name = str(
            cfg.get("selected_gallery_name")
            or getattr(group_obj, "gallery_name", "")
            or gallery_id
        ).strip()
        gallery_url = str(
            cfg.get("selected_gallery_url")
            or getattr(group_obj, "gallery_url", "")
            or gallery_url_for_service("imx.to", gallery_id)
        ).strip()

        record = GalleryRecord(
            service="imx.to",
            id=gallery_id,
            name=gallery_name,
            url=gallery_url,
            raw={"source": "upload"},
        )
        try:
            cache = GalleryCache()
            cache.upsert_record(record)
            cache.mark_used(record)
        except Exception as exc:
            logger.debug(f"Could not update IMX gallery cache for {gallery_id}: {exc}")

    @staticmethod
    def _explicit_cover_files_for_group(group_obj: Any, files: List[str]) -> List[str] | None:
        """Return explicit cover selections for UI groups, or None for legacy count mode."""
        cover_filepaths = getattr(group_obj, "cover_filepaths", None)
        if callable(cover_filepaths):
            cover_set = set(cover_filepaths())
            return [file_path for file_path in files if file_path in cover_set]

        cover_files = getattr(group_obj, "cover_files", None)
        if cover_files is not None:
            cover_set = set(cover_files)
            return [file_path for file_path in files if file_path in cover_set]

        return None

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
                    resolve_spec = None
                    if isinstance(http_spec, dict):
                        resolve_spec = http_spec.pop("resolve_spec", None)

                    job_data = {
                        "action": "http_upload",
                        "service": service_id,
                        "files": [os.path.normpath(f) for f in file_list],
                        "creds": creds,
                        "config": str_config,
                        "http_spec": http_spec,
                        "context_data": {},
                    }
                    if resolve_spec:
                        job_data["resolve_spec"] = resolve_spec
                    if service_id in SERVICE_RATE_LIMITS:
                        job_data["rate_limits"] = SERVICE_RATE_LIMITS[service_id]
                    logger.info(f"Using generic HTTP runner for {service_id} ({len(file_list)} files)")
                    
                    self.active_files.update(file_list)
                    if not self.bridge.send_cmd(job_data):
                        for file_path in file_list:
                            self.active_files.discard(file_path)
                            self.result_queue.put((file_path, "", ""))
                            self.progress_queue.put(("status", file_path, "error: sidecar unavailable"))
                    return

            except Exception as exc:
                logger.error(f"Failed to build HTTP request spec for {service_id}: {exc}")
                for file_path in file_list:
                    self.result_queue.put((file_path, "", ""))
                    self.progress_queue.put(("status", file_path, "error: plugin configuration failed"))
                return

        logger.error(
            f"Plugin {service_id} did not return an http_spec; "
            f"legacy Go service modules have been removed"
        )
        for file_path in file_list:
            self.result_queue.put((file_path, "", ""))
            self.progress_queue.put(
                ("status", file_path, "error: plugin missing http_spec")
            )

    @staticmethod
    def _normalize_job_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Return a sidecar-ready config with service thread controls normalized."""
        normalized = cfg.copy()
        service_id = str(normalized.get("service", ""))
        thread_value = normalized.get("global_thread_limit")

        if thread_value in (None, ""):
            thread_key = SERVICE_THREAD_KEYS.get(service_id)
            if thread_key and normalized.get(thread_key) not in (None, ""):
                thread_value = normalized[thread_key]

        try:
            threads = int(
                thread_value if thread_value not in (None, "") else normalized.get("threads", 2)
            )
        except (TypeError, ValueError):
            threads = 2

        normalized["threads"] = max(
            config.MIN_THREAD_COUNT,
            min(config.MAX_THREAD_COUNT, threads),
        )
        return normalized

    def _process_events(self) -> None:
        """Read events from the bridge and update UI-facing queues."""
        while not self.cancel_event.is_set() and not self._stop_events.is_set():
            try:
                data = self.event_queue.get(timeout=1)
                evt = data.get("type")
                fp = data.get("file") or data.get("file_path")

                if evt in ("result", "error") and fp:
                    self.active_files.discard(fp)

                if evt == "status":
                    self.progress_queue.put(("status", fp, data.get("status")))

                elif evt == "progress":
                    self.progress_queue.put(("prog", fp, data.get("data", data)))

                elif evt == "result":
                    url = data.get("url") or ""
                    thumb = data.get("thumb") or ""
                    metadata = data.get("data") if isinstance(data.get("data"), dict) else {}
                    gallery_url = str(metadata.get("gallery_url") or "").strip()
                    if gallery_url and fp:
                        self.progress_queue.put(("gallery_url", fp, gallery_url))
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

                elif evt == "sidecar_stopped":
                    logger.error(f"SIDECAR STOPPED: {data.get('msg')}")
                    for active_fp in list(self.active_files):
                        self.result_queue.put((active_fp, "", ""))
                        self.progress_queue.put(("status", active_fp, f"error: {data.get('msg')}"))
                    self.active_files.clear()

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
