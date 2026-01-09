# modules/upload_manager.py
import threading
import json
import os
import sys
import queue
from . import config
from loguru import logger
from .sidecar import SidecarBridge
from .plugin_manager import PluginManager


class UploadManager:
    def __init__(self, progress_queue, result_queue, cancel_event):
        self.progress_queue = progress_queue
        self.result_queue = result_queue
        self.cancel_event = cancel_event
        self.bridge = SidecarBridge.get()
        self.plugin_manager = PluginManager()  # For plugin-driven HTTP requests

        self.event_queue = queue.Queue(maxsize=1000)
        self.listener_thread = None

    def start_batch(self, pending_by_group, cfg, creds):
        """
        Submits a batch of groups to the persistent Go sidecar.
        """
        # 1. Register for events
        self.bridge.add_listener(self.event_queue)

        # 2. Start listener thread to process this batch's events
        self.listener_thread = threading.Thread(target=self._process_events, daemon=True)
        self.listener_thread.start()

        # 3. Dispatch jobs asynchronously
        threading.Thread(target=self._dispatch_jobs, args=(pending_by_group, cfg, creds), daemon=True).start()

    def _dispatch_jobs(self, pending_by_group, cfg, creds):
        """Sends job JSONs to the Go process via the Bridge."""
        for group_obj, files in pending_by_group.items():
            if self.cancel_event.is_set():
                break

            # Determine configured cover count
            svc = cfg.get("service", "")
            cover_cnt = 0
            try:
                if "imx" in svc:
                    cover_cnt = int(cfg.get("imx_cover_count", 0))
                elif "pix" in svc:
                    cover_cnt = int(cfg.get("pix_cover_count", 0))
                elif "turbo" in svc:
                    cover_cnt = int(cfg.get("turbo_cover_count", 0))
                elif "vipr" in svc:
                    cover_cnt = int(cfg.get("vipr_cover_count", 0))
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
                cover_cfg = cfg.copy()
                cover_cfg["imx_thumb"] = "600"
                cover_cfg["pix_thumb"] = "500"
                cover_cfg["turbo_thumb"] = "600"
                cover_cfg["vipr_thumb"] = "800x800"
                cover_cfg["imagebam_thumb"] = "300"
                self._send_job(covers, cover_cfg, creds)

            # 2. Send Standard Job
            if standards:
                self._send_job(standards, cfg, creds)

    def _send_job(self, file_list, cfg, creds):
        service_id = cfg["service"]

        # NEW: Check if plugin supports generic HTTP runner
        plugin = self.plugin_manager.get_plugin(service_id)
        if plugin and hasattr(plugin, 'build_http_request'):
            # Try to build HTTP request spec for first file (as template)
            # Note: For file-specific fields, Go will substitute the actual file path
            try:
                http_spec = plugin.build_http_request(
                    file_path=file_list[0] if file_list else "",
                    config=cfg,
                    creds=creds
                )

                if http_spec:
                    # Use new generic HTTP runner protocol
                    job_data = {
                        "action": "http_upload",
                        "service": service_id,
                        "files": [os.path.normpath(f) for f in file_list],
                        "creds": creds,  # Pass all creds for backward compat
                        "config": {"threads": str(cfg.get(f"{service_id.split('.')[0]}_threads", 2))},
                        "http_spec": http_spec,
                        "context_data": {},
                    }

                    logger.info(f"Using generic HTTP runner for {service_id} ({len(file_list)} files)")
                    self.bridge.send_cmd(job_data)
                    return

            except Exception as e:
                logger.warning(f"Failed to build HTTP request spec for {service_id}, falling back to legacy: {e}")

        # LEGACY: Fallback to hardcoded service mappings (for backward compatibility)
        job_data = {
            "action": "upload",
            "service": service_id,
            "files": [os.path.normpath(f) for f in file_list],
            "creds": {
                "api_key": creds.get("imx_api", ""),
                "vipr_user": creds.get("vipr_user", ""),
                "vipr_pass": creds.get("vipr_pass", ""),
                "turbo_user": creds.get("turbo_user", ""),
                "turbo_pass": creds.get("turbo_pass", ""),
                "imagebam_user": creds.get("imagebam_user", ""),
                "imagebam_pass": creds.get("imagebam_pass", ""),
            },
            "config": {
                "threads": str(cfg.get(f"{service_id.split('.')[0]}_threads", 2)),
                # IMX - support both new (thumbnail_size/thumbnail_format) and legacy (imx_thumb/imx_format) keys
                "imx_thumb_id": self._map_imx_size(cfg.get("thumbnail_size") or cfg.get("imx_thumb")),
                "imx_format_id": self._map_imx_format(cfg.get("thumbnail_format") or cfg.get("imx_format")),
                "gallery_id": cfg.get("gallery_id", ""),
                # Pixhost - support both new (content_type/thumbnail_size/gallery_hash) and legacy (pix_content/pix_thumb/pix_gallery_hash) keys
                "pix_content": "1" if (cfg.get("content_type") or cfg.get("pix_content")) == "Adult" else "0",
                "pix_thumb": cfg.get("thumbnail_size") or cfg.get("pix_thumb", "200"),
                "pix_gallery_hash": cfg.get("gallery_hash") or cfg.get("pix_gallery_hash", ""),
                # Vipr - support both new (thumbnail_size) and legacy (vipr_thumb) keys
                "vipr_thumb": cfg.get("thumbnail_size") or cfg.get("vipr_thumb", "170x170"),
                "vipr_gal_id": str(cfg.get("vipr_gal_id", "0")),
                # Turbo - support both new (content_type/thumbnail_size) and legacy (turbo_content/turbo_thumb) keys
                "turbo_content": "adult" if (cfg.get("content_type") or cfg.get("turbo_content")) == "Adult" else "all",
                "turbo_thumb": cfg.get("thumbnail_size") or cfg.get("turbo_thumb", "180"),
                # ImageBam - support both new (content_type/thumbnail_size) and legacy (imagebam_content/imagebam_thumb) keys
                "ib_content": "nsfw" if (cfg.get("content_type") or cfg.get("imagebam_content")) == "Adult" else "sfw",
                "ib_thumb": self._map_ib_size(cfg.get("thumbnail_size") or cfg.get("imagebam_thumb")),
            },
            "context_data": {},
        }

        logger.info(f"Using legacy upload protocol for {service_id} ({len(file_list)} files)")
        self.bridge.send_cmd(job_data)

    def _process_events(self):
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
                        # Optional debug log
                        # logger.debug(f"Patched IMX thumbnail for {fp}")
                    # --------------------------------
                    
                    self.result_queue.put((fp, url, thumb))

                elif evt == "batch_complete":
                    # Optional: handle batch completion logic here if needed
                    pass

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Event processing error: {e}")

    # Helper Mappers
    def _map_imx_size(self, val):
        return {"100": "1", "150": "6", "180": "2", "250": "3", "300": "4"}.get(val, "2")

    def _map_imx_format(self, val):
        return {"Fixed Width": "1", "Fixed Height": "4", "Proportional": "2", "Square": "3"}.get(val, "1")

    def _map_ib_size(self, val):
        return {"100": "1", "180": "2", "250": "3", "300": "4"}.get(val, "2")