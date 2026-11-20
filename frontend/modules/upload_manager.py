# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Upload orchestration between the UI, plugins, and Go sidecar."""

from __future__ import annotations

import os
import queue
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from loguru import logger

from . import config
from .gallery_cache import GalleryCache
from .gallery_service import GalleryRecord, gallery_url_for_service
from .plugin_manager import PluginManager
from .plugins.base import uses_python_upload_parsing
from .plugins.imx import canonical_thumbnail_url as canonical_imx_thumbnail_url
from .sidecar import PROCESS_RESTARTED_MSG, SIDECAR_CRASHED_EVENT, SidecarBridge
from .transport import (
    TransportCancelled,
    TransportResponse,
    TransportSession,
    TransportSessionError,
    UploadTransport,
    close_transport_session,
    open_transport_session,
)
from .upload_results import UploadResult, collect_secrets, redact_secrets
from .upload_sessions import PostProcessingPool, SessionState

# Statuses after which the sidecar reports nothing more for a file.
TERMINAL_FILE_STATUSES = frozenset({"Done", "Failed", "Cancelled"})

# Non-terminal status of a file on the Python upload path: the host answered
# the upload and the plugin's parser is reading the answer.
UPLOADED_STATUS = "Uploaded"

# Threads that run plugin parsers (and their follow-up requests).
POST_PROCESS_WORKERS = 4

# Answers with which a host refuses an upload without taking it ("too many
# requests", "unavailable"). The sidecar re-sends such an upload; a raw result
# with one of them is the last refusal, an upload the host did not keep.
REFUSAL_STATUS_CODES = frozenset({429, 503})

SERVICE_THREAD_KEYS = {
    "imx.to": "imx_threads",
    config.PIXHOST_SERVICE_ID: "pix_threads",
    "turboimagehost": "turbo_threads",
    "vipr.im": "vipr_threads",
    "imagebam.com": "imagebam_threads",
    "imgur.com": "imgur_threads",
}


COVER_THUMBNAIL_OVERRIDES = {
    "imx.to": {"thumbnail_size": "600", "imx_thumb": "600"},
    config.PIXHOST_SERVICE_ID: {"thumbnail_size": "500", "pix_thumb": "500"},
    "turboimagehost": {"thumbnail_size": "600", "turbo_thumb": "600"},
    "vipr.im": {"thumbnail_size": "800x800", "vipr_thumb": "800x800"},
    "imagebam.com": {"thumbnail_size": "300", "imagebam_thumb": "300"},
    "imgur.com": {"thumbnail_size": "h", "imgur_thumb": "h"},
}


# Proactive sidecar rate limits for upload jobs.
# Empty / omitted = legacy-like full concurrency (Go only throttles when RPS > 0).
# Host 429 responses still use Go retry/backoff. Optional per-service overrides
# can re-enable gentle pacing without capping bulk throughput.
SERVICE_RATE_LIMITS: Dict[str, Dict[str, float | int]] = {
    # Intentionally empty defaults: do not attach rate_limits to upload jobs.
    # Callers that need throttling can pass explicit rate_limits on the job.
}


def _config_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _status_code(value: Any) -> int:
    try:
        return int(str(value or "0"))
    except (TypeError, ValueError):
        return 0


@dataclass(eq=False)
class _SessionJob:
    """One ``_send_job`` call on the Python upload path: one transport session.

    Its files go to the sidecar as one raw job, or one job per file for a
    sequential host. Guarded by UploadManager._jobs_lock.
    """

    plugin: Any
    service: str
    batch_id: str
    # The batch's own cancel token (UploadManager._batch_cancel when the batch
    # started). Stop sets it; a newer batch replaces it, which makes this job
    # superseded: it then sends, parses and reports nothing more.
    cancel: threading.Event
    id_base: str
    str_config: Dict[str, str]
    rate_limits: Optional[Dict[str, Any]]
    session: TransportSession
    transport: UploadTransport
    session_values: Dict[str, str]
    state: SessionState
    requests: Dict[str, Dict[str, Any]]
    sequential: bool
    queued: List[str]
    sidecar_jobs: Set[str] = field(default_factory=set)
    sent_jobs: int = 0
    post_pending: int = 0
    # The session's sidecar process is gone (or unreachable); end_status ends
    # the files that were never sent.
    dead: bool = False
    end_status: str = ""
    finished: bool = False


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
        # Cancel token of the current batch; each start_batch makes a new one.
        self._batch_cancel = threading.Event()
        # The token of the batch whose dispatch is running (_dispatch_jobs),
        # for the session jobs _send_job starts on its behalf.
        self._dispatch_token: threading.Event | None = None
        self._lifecycle_lock = threading.RLock()
        self._listener_registered = False
        self._stop_events = threading.Event()
        # Batch identity: every sidecar job of one Start carries ``batch_id``
        # and a per-job ``id``; events for unknown ids are ignored.
        self.current_batch_id: str | None = None
        self._job_files: Dict[str, List[str]] = {}
        self._job_counter = 0
        # Which sidecar process (generation) each sent job was written to, so a
        # crash ends exactly the jobs that died with that process. A job that
        # is registered but missing here is still being written.
        self._jobs_lock = threading.RLock()
        self._job_generation: Dict[str, int | None] = {}
        self._dead_generation = 0
        # Files whose result arrived but whose closing "Done" has not.
        self._awaiting_done: set[str] = set()
        # The Python upload path (_send_session_job): sidecar job id -> its
        # session job, every session job not finished yet, and the pool that
        # runs plugin parsers off the event listener.
        self._session_jobs: Dict[str, _SessionJob] = {}
        self._open_session_jobs: List[_SessionJob] = []
        self._post_pool = PostProcessingPool(POST_PROCESS_WORKERS)

    def _register_job(self, job_id: str, files: List[str]) -> None:
        """Remember which files a sidecar job owns so its events can be scoped."""
        self._job_files[job_id] = list(files)

    def _submit_job(
        self, job_id: str, job_data: Dict[str, Any], generation: Optional[int] = None
    ) -> bool:
        """Write a registered job to the sidecar and remember which process got it.

        With ``generation`` (a job on a transport session), the job goes only
        to that process: once it is gone, even if the crash report has not
        been handled yet, nothing is written and False is returned.
        """
        send_to = getattr(self.bridge, "send_job_to", None) if generation is not None else None
        send_job = getattr(self.bridge, "send_job", None)
        if callable(send_to):
            written = send_to(job_data, generation)
            if written is None:
                return False
            generation = written if isinstance(written, int) else None
        elif callable(send_job):
            generation = send_job(job_data)
            if generation is None:
                return False
            if not isinstance(generation, int):
                generation = None
        elif self.bridge.send_cmd(job_data):
            generation = None  # unknown: any crash report ends this job
        else:
            return False

        ended = []
        with self._jobs_lock:
            if job_id not in self._job_files:
                return True  # already ended while it was being written
            self._job_generation[job_id] = generation
            if generation is not None and generation <= self._dead_generation:
                # The process died, and was reported, while the job was written.
                ended = self._end_job(job_id, f"error: {PROCESS_RESTARTED_MSG}")
        self._deliver(ended)
        return True

    def _end_job(self, job_id: str, status_text: str) -> List[Tuple[queue.Queue, Any]]:
        """End every unfinished file of a job the sidecar will no longer report on.

        Call with ``_jobs_lock`` held, then pass the returned queue items to
        ``_deliver`` after releasing it: the UI queues are bounded and only the
        Tk thread drains them, and the Tk thread takes ``_jobs_lock`` too.
        A file whose result already arrived only lost its closing "Done";
        every other unfinished file gets ``status_text`` (a failure or
        "Cancelled").
        """
        files = self._job_files.pop(job_id, [])
        self._job_generation.pop(job_id, None)
        items: List[Tuple[queue.Queue, Any]] = []
        ended = []
        for file_path in files:
            if file_path in self._awaiting_done:
                self._awaiting_done.discard(file_path)
                items.append((self.progress_queue, ("status", file_path, "Done")))
            elif file_path in self.active_files:
                self.active_files.discard(file_path)
                items.append((self.result_queue, (file_path, "", "")))
                items.append((self.progress_queue, ("status", file_path, status_text)))
                ended.append(file_path)
        # A raw job's files whose raw result arrived are left to their parser.
        self._session_sidecar_job_done(job_id, ended)
        return items

    def _deliver(self, items: List[Tuple[queue.Queue, Any]]) -> None:
        """Put collected items on the UI queues. Never call with ``_jobs_lock`` held.

        A put waits for the Tk thread to make room, but gives up on a queue a
        new upload replaced (start_upload swaps in a new result queue), since
        nobody reads the old one any more.
        """
        for target, item in items:
            while True:
                if target is not self.result_queue and target is not self.progress_queue:
                    logger.debug("Dropping an item for a UI queue a new upload replaced")
                    break
                try:
                    target.put(item, timeout=0.5)
                    break
                except queue.Full:
                    continue

    def _next_job_id(self) -> str:
        with self._jobs_lock:
            self._job_counter += 1
            return f"{self.current_batch_id}:{self._job_counter}"

    def _listener_should_run(self) -> bool:
        """The listener stops only at shutdown, never when a batch is cancelled."""
        return not self._stop_events.is_set()

    def cancel_batch(self) -> None:
        """Ask the sidecar to abort every queued and in-flight job of this batch."""
        # The batch's own token stops its dispatch even after start_upload
        # clears the shared cancel_event for the next batch.
        self._batch_cancel.set()
        batch_id = self.current_batch_id
        if not batch_id:
            return
        logger.info(f"Cancelling sidecar batch {batch_id}")
        if self.bridge.send_cmd({"action": "cancel", "batch_id": batch_id}):
            return
        # Nothing will report these files any more: end them here so Stop
        # always finishes the batch. Off the Tk thread, which drains the
        # bounded queues these statuses go to.
        logger.warning(f"Sidecar unreachable; cancelling batch {batch_id} locally")
        threading.Thread(
            target=self._end_all_jobs,
            args=("Cancelled",),
            name="UploadManagerCancel",
            daemon=True,
        ).start()

    def _end_all_jobs(self, status_text: str) -> None:
        """End every job; the sidecar is gone or unreachable, and so are its sessions."""
        with self._jobs_lock:
            ended = self._end_all_jobs_locked(status_text)
        self._deliver(ended)

    def _end_all_jobs_locked(self, status_text: str) -> List[Tuple[queue.Queue, Any]]:
        for job in list(getattr(self, "_open_session_jobs", [])):
            self._mark_session_dead(job, status_text)
        ended: List[Tuple[queue.Queue, Any]] = []
        for job_id in list(self._job_files):
            ended += self._end_job(job_id, status_text)
        return ended

    def start_batch(
        self, pending_by_group: Dict[Any, List[str]], cfg: Dict[str, Any], creds: Dict[str, str]
    ) -> str:
        """Submit a batch of groups to the persistent Go sidecar.

        Returns the batch id attached to every job of this batch.
        """
        with self._lifecycle_lock:
            self._stop_events.clear()
            batch_id = uuid.uuid4().hex
            previous = self.dispatch_thread
            if previous is not None and previous.is_alive():
                # A cleared batch's dispatch is still running (e.g. inside a
                # host's gallery call). It must send nothing more, and this
                # batch becomes current only once it has exited, so none of
                # its files can go out under this batch's id.
                self._batch_cancel.set()
                logger.warning("Previous upload dispatch still running; the new batch waits for it")
                self._reset_jobs(None)
            else:
                previous = None
                self._reset_jobs(batch_id)
            batch_cancel = threading.Event()
            self._batch_cancel = batch_cancel

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

            self.dispatch_thread = threading.Thread(
                target=self._run_dispatch,
                args=(batch_id, batch_cancel, previous, pending_by_group, cfg, creds),
                name="UploadManagerDispatch",
                daemon=True,
            )
            self.dispatch_thread.start()
            return batch_id

    def _reset_jobs(self, batch_id: str | None) -> None:
        """Forget earlier batches' jobs, whose events are ignored from now on.

        With ``batch_id``, that batch also becomes the current one.
        """
        with self._jobs_lock:
            self._job_files = {}
            self._job_generation = {}
            self._awaiting_done = set()
            if batch_id is not None:
                self.current_batch_id = batch_id
                self._job_counter = 0
            # The earlier batches' session jobs hear nothing more from the
            # sidecar either: let them finish, silently once superseded.
            self._session_jobs = {}
            for job in list(self._open_session_jobs):
                job.sidecar_jobs.clear()
                self._post_pool.submit(lambda job=job: self._advance_session_job(job))

    def _run_dispatch(
        self,
        batch_id: str,
        batch_cancel: threading.Event,
        previous: threading.Thread | None,
        pending_by_group: Dict[Any, List[str]],
        cfg: Dict[str, Any],
        creds: Dict[str, str],
    ) -> None:
        """Dispatch a batch once the cleared batch's dispatch, if any, has exited."""
        if previous is not None:
            previous.join()
            self._reset_jobs(batch_id)
        self._dispatch_jobs(pending_by_group, cfg, creds, batch_cancel)

    def _cancel_undispatched(self, files: List[str]) -> None:
        """Give files that never reached the sidecar a terminal Cancelled state."""
        for file_path in files:
            self.result_queue.put((file_path, "", ""))
            self.progress_queue.put(("status", file_path, "Cancelled"))

    def _dispatch_jobs(
        self,
        pending_by_group: Dict[Any, List[str]],
        cfg: Dict[str, Any],
        creds: Dict[str, str],
        batch_cancel: threading.Event | None = None,
    ) -> None:
        """Send job JSON payloads to the Go process via the sidecar bridge.

        ``batch_cancel`` is this batch's own cancel token (start_batch passes
        it): start_upload clears the shared cancel_event for the next batch,
        which must not revive a cleared batch's dispatch.
        """
        logger.info("--- Starting Phase 1: Gallery Creation ---")
        failed_groups: Dict[Any, str] = {}
        completed_files: set[str] = set()
        cfg = cfg.copy()
        cfg["service"] = config.normalize_service_id(cfg.get("service", ""))
        own_token = batch_cancel
        if batch_cancel is None:
            batch_cancel = self.cancel_event

        def cancelled() -> bool:
            return batch_cancel.is_set() or self.cancel_event.is_set()

        def superseded() -> bool:
            # A newer batch started: this one was cleared and its rows are
            # gone; the new batch may hold rows for the same files.
            return own_token is not None and own_token is not self._batch_cancel

        # Session jobs started by _send_job belong to this batch's token.
        self._dispatch_token = own_token
        try:
            for group_obj, files in pending_by_group.items():
                if cancelled():
                    if superseded():
                        return
                    for remaining in pending_by_group.values():
                        self._cancel_undispatched(
                            [fp for fp in remaining if fp not in completed_files]
                        )
                    return

                service_id = cfg.get("service", "")
                plugin = self.plugin_manager.get_plugin(service_id)

                if plugin and hasattr(plugin, "prepare_group"):
                    try:
                        cover_files = self._explicit_cover_files_for_group(group_obj, files)
                        if cover_files is None:
                            cover_files = group_obj.files[: self._cover_count_for_service(cfg)]
                        context: Dict[str, Any] = {
                            "pending_files": list(files),
                            "cover_files": cover_files,
                            "cancel_event": batch_cancel,
                        }
                        temp_cfg = cfg.copy()
                        if service_id == "imx.to" and cfg.get("auto_gallery") and files:
                            self.progress_queue.put(
                                ("status", files[0], "Creating IMX gallery with first image...")
                            )
                        plugin.prepare_group(group_obj, temp_cfg, context, creds)
                        if superseded():
                            return  # cleared while the host call ran

                        for file_path, image_url, thumb_url in context.get("completed_uploads", []):
                            completed_files.add(file_path)
                            gallery_url = getattr(group_obj, "gallery_url", "")
                            if gallery_url:
                                self.progress_queue.put(("gallery_url", file_path, gallery_url))
                            self.result_queue.put(
                                (
                                    file_path,
                                    image_url,
                                    self._canonicalize_imx_thumbnail_url(thumb_url),
                                )
                            )
                            # Preparation uploads bypass the sidecar's terminal status event.
                            self.progress_queue.put(("status", file_path, "Done"))
                        if service_id == "imx.to" and getattr(group_obj, "gallery_id", ""):
                            self._remember_imx_gallery_use(
                                group_obj,
                                {
                                    "gallery_id": group_obj.gallery_id,
                                    "selected_gallery_name": group_obj.gallery_name,
                                    "selected_gallery_url": group_obj.gallery_url,
                                },
                            )

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
                files = [file_path for file_path in files if file_path not in completed_files]
                if not files:
                    continue

                if cancelled():
                    if not superseded():
                        self._cancel_undispatched(files)
                    continue

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

                if (
                    hasattr(group_obj, "gallery_id")
                    and group_obj.gallery_id
                    and self._gallery_is_for_service(group_obj, group_cfg.get("service", ""))
                ):
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
                        logger.info(
                            f"Group '{group_obj.title}' using manual gallery hash: {manual_hash}"
                        )

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

                if covers and standards and self._upload_session_creates_gallery(group_cfg):
                    # Each job opens its own upload session, and each session
                    # would create its own gallery: send one job, covers first.
                    logger.info(
                        f"Group '{group_obj.title}': {group_cfg.get('service')} creates the "
                        "gallery per upload session, so covers upload with the other files "
                        "in one job and the larger cover thumbnail size does not apply."
                    )
                    self._send_job(covers + standards, group_cfg, creds)
                    continue

                if covers:
                    cover_cfg = group_cfg.copy()
                    self._apply_cover_thumbnail_overrides(cover_cfg)
                    self._send_job(covers, cover_cfg, creds)

                if standards:
                    self._send_job(standards, group_cfg, creds)
        finally:
            self._dispatch_token = None
            logger.info("Upload dispatch finished")

    def _upload_session_creates_gallery(self, cfg: Dict[str, Any]) -> bool:
        """Whether the host plugin creates a new gallery in every upload session.

        Plugins declare this with ``upload_session_creates_gallery(config)``.
        """
        plugin = self.plugin_manager.get_plugin(cfg.get("service", ""))
        check = getattr(plugin, "upload_session_creates_gallery", None)
        if not callable(check):
            return False
        try:
            return bool(check(cfg))
        except Exception as exc:
            logger.debug(f"Could not ask {cfg.get('service')} about session galleries: {exc}")
            return False

    @staticmethod
    def _gallery_is_for_service(group_obj: Any, service_id: str) -> bool:
        """True unless the batch's gallery was chosen for a different host.

        A gallery picked in Gallery Manager records its host. After the user
        switches hosts, that host's id must not be sent to the new host.
        """
        gallery_service = config.normalize_service_id(
            str(getattr(group_obj, "gallery_service", "") or "")
        )
        if not gallery_service:
            return True
        return gallery_service == config.normalize_service_id(str(service_id or ""))

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
        service_id = config.normalize_service_id(cfg.get("service", ""))
        overrides = COVER_THUMBNAIL_OVERRIDES.get(service_id, {})
        cfg.update(overrides)
        return cfg

    @staticmethod
    def _canonicalize_imx_thumbnail_url(thumb_url: str) -> str:
        """Return IMX thumbnail URLs in the durable image.imx.to/u/t form."""
        return canonical_imx_thumbnail_url(thumb_url)

    @staticmethod
    def _remember_imx_gallery_use(group_obj: Any, cfg: Dict[str, Any]) -> None:
        gallery_id = str(
            cfg.get("gallery_id")
            or cfg.get("selected_gallery_id")
            or cfg.get("imx_gallery_id")
            or ""
        ).strip()
        if not gallery_id:
            return

        gallery_name = str(
            cfg.get("selected_gallery_name") or getattr(group_obj, "gallery_name", "") or gallery_id
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
        cfg = cfg.copy()
        cfg["service"] = config.normalize_service_id(cfg.get("service", ""))
        service_id = cfg["service"]
        job_cfg = self._normalize_job_config(cfg)
        str_config = {k: str(v) for k, v in job_cfg.items()}

        logger.info(f"_send_job for {service_id}: thumbnail_size={cfg.get('thumbnail_size')!r}")

        plugin = self.plugin_manager.get_plugin(service_id)
        if plugin is not None and self._uses_python_parsing(plugin, cfg):
            self._send_session_job(plugin, file_list, cfg, creds)
            return
        if plugin and hasattr(plugin, "build_http_request"):
            try:
                http_spec = plugin.build_http_request(
                    file_path=file_list[0] if file_list else "", config=cfg, creds=creds
                )

                if http_spec:
                    resolve_spec = None
                    if isinstance(http_spec, dict):
                        resolve_spec = http_spec.pop("resolve_spec", None)

                    job_id = self._next_job_id()
                    job_data = {
                        "id": job_id,
                        "batch_id": self.current_batch_id or "",
                        "action": "http_upload",
                        "service": service_id,
                        "files": [os.path.normpath(f) for f in file_list],
                        "creds": self._credentials_for_plugin(plugin, creds),
                        "config": str_config,
                        "http_spec": http_spec,
                        "context_data": {},
                    }
                    if resolve_spec:
                        job_data["resolve_spec"] = resolve_spec
                    rate_limits = self._rate_limits_for_job(service_id, job_cfg)
                    if rate_limits:
                        job_data["rate_limits"] = rate_limits
                    logger.info(
                        f"Using generic HTTP runner for {service_id} "
                        f"({len(file_list)} files, threads={job_cfg.get('threads')})"
                    )

                    self.active_files.update(file_list)
                    self._register_job(job_id, file_list)
                    if not self._submit_job(job_id, job_data):
                        self._job_files.pop(job_id, None)
                        for file_path in file_list:
                            self.active_files.discard(file_path)
                            self.result_queue.put((file_path, "", ""))
                            self.progress_queue.put(
                                ("status", file_path, "error: sidecar unavailable")
                            )
                    return

            except Exception as exc:
                logger.error(f"Failed to build HTTP request spec for {service_id}: {exc}")
                for file_path in file_list:
                    self.result_queue.put((file_path, "", ""))
                    self.progress_queue.put(
                        ("status", file_path, "error: plugin configuration failed")
                    )
                return

        logger.error(
            f"Plugin {service_id} did not return an http_spec; "
            f"legacy Go service modules have been removed"
        )
        for file_path in file_list:
            self.result_queue.put((file_path, "", ""))
            self.progress_queue.put(("status", file_path, "error: plugin missing http_spec"))

    # --- Python upload path ------------------------------------------------------------
    #
    # Per _send_job call: session_open (bounded by Stop), the plugin's
    # open_upload_session on this (dispatch) thread, raw upload job(s) on the
    # session, the plugin's parse_upload_response on the post-processing pool
    # for each raw result, then session_close once the sidecar has finished
    # the job(s) and every parse is done. The event listener only hands raw
    # results to the pool; it never waits for a parser or a request.

    @staticmethod
    def _uses_python_parsing(plugin: Any, cfg: Dict[str, Any]) -> bool:
        """Whether this job goes through the Python path.

        The ``legacy_upload_parsing`` setting (not shown in the window) sends
        every host through its legacy Go specs instead.
        """
        return uses_python_upload_parsing(plugin) and not _config_flag(
            cfg.get("legacy_upload_parsing")
        )

    def _finish_files(self, files: List[str], status_text: str) -> None:
        """Give files that never reached (or left) the sidecar their terminal status.

        Never call with ``_jobs_lock`` held.
        """
        items: List[Tuple[queue.Queue, Any]] = []
        for file_path in files:
            items.append((self.result_queue, (file_path, "", "")))
            items.append((self.progress_queue, ("status", file_path, status_text)))
        self._deliver(items)

    def _current_token(self) -> threading.Event:
        """The cancel token of the batch a new session job belongs to."""
        return self._dispatch_token or self._batch_cancel

    def _token_cancelled(self, token: threading.Event) -> bool:
        return token.is_set() or self.cancel_event.is_set()

    def _token_superseded(self, token: threading.Event) -> bool:
        """A newer batch started after Clear List: this batch's files are not ours any more.

        Its rows are gone, and the new batch may hold rows for the same files,
        so nothing of it may be sent or reported.
        """
        return token is not self._batch_cancel

    def _session_alive(self, session: TransportSession) -> bool:
        """False once the sidecar process that holds ``session`` is known to be dead."""
        generation = session.generation
        return generation is None or generation > self._dead_generation

    def _close_session(self, session: TransportSession) -> None:
        if not self._session_alive(session):
            return
        if not close_transport_session(self.bridge, session):
            logger.debug(f"Could not close transport session {session.session_id}")

    def _send_session_job(
        self, plugin: Any, file_list: List[str], cfg: Dict[str, Any], creds: Dict[str, str]
    ) -> None:
        service_id = cfg["service"]
        job_cfg = self._normalize_job_config(cfg)
        declared = self._credentials_for_plugin(plugin, creds)
        secrets = collect_secrets(declared)
        batch_id = self.current_batch_id or ""
        token = self._current_token()

        def stop_if_cancelled(session: Optional[TransportSession] = None) -> bool:
            """End the group if its batch was stopped or cleared meanwhile."""
            if not self._token_cancelled(token) and not self._token_superseded(token):
                return False
            if session is not None:
                self._close_session(session)
            if not self._token_superseded(token):
                self._finish_files(file_list, "Cancelled")
            return True

        if stop_if_cancelled():
            return
        try:
            session = open_transport_session(self.bridge, batch_id, cancel_event=token)
        except TransportCancelled:
            stop_if_cancelled()
            return
        except TransportSessionError as exc:
            if stop_if_cancelled():
                return
            logger.error(f"{service_id}: {exc}")
            self._finish_files(file_list, f"error: {exc}")
            return
        if stop_if_cancelled(session):
            return

        rate_limits = self._rate_limits_for_job(service_id, job_cfg)
        transport = UploadTransport(
            session.session_id,
            service=service_id,
            bridge=self.bridge,
            rate_limits=rate_limits,
            cancel_event=token,
            generation=session.generation,
        )
        try:
            # Plugins that do not subclass ImageHostPlugin get its defaults.
            open_session = getattr(plugin, "open_upload_session", None)
            opened = (open_session(transport, cfg, creds) if callable(open_session) else {}) or {}
            session_values = {str(key): str(value) for key, value in dict(opened).items()}
        except Exception as exc:
            if stop_if_cancelled(session):
                return
            logger.error(f"{service_id}: upload session setup failed: {exc}")
            self._close_session(session)
            reason = redact_secrets(f"upload session setup failed: {exc}", secrets)
            self._finish_files(file_list, f"error: {reason}")
            return
        if stop_if_cancelled(session):
            return

        secrets = collect_secrets(declared, session_values)
        requests: Dict[str, Dict[str, Any]] = {}
        for file_path in file_list:
            try:
                request = plugin.build_raw_upload_request(file_path, cfg, session_values, creds)
                requests[file_path] = self._raw_request_payload(request)
            except Exception as exc:
                logger.error(f"{service_id}: could not build the upload of {file_path}: {exc}")
                self._finish_files([file_path], f"error: {redact_secrets(str(exc), secrets)}")
        files = [file_path for file_path in file_list if file_path in requests]
        if not files:
            self._close_session(session)
            return

        try:
            job_options = getattr(plugin, "upload_job_options", None)
            options = dict((job_options(cfg) if callable(job_options) else {}) or {})
        except Exception as exc:
            logger.debug(f"{service_id}: upload_job_options failed: {exc}")
            options = {}
        job = _SessionJob(
            plugin=plugin,
            service=service_id,
            batch_id=batch_id,
            cancel=token,
            id_base=self._next_job_id(),
            str_config={key: str(value) for key, value in job_cfg.items()},
            rate_limits=rate_limits,
            session=session,
            transport=transport,
            session_values=session_values,
            state=SessionState([os.path.normpath(fp) for fp in files], secrets),
            requests=requests,
            sequential=bool(options.get("sequential")),
            queued=list(files),
        )
        logger.info(
            f"Python upload path for {service_id}: {len(files)} file(s) on session "
            f"{session.session_id} (sequential={job.sequential})"
        )
        with self._jobs_lock:
            self._open_session_jobs.append(job)
        self._advance_session_job(job)

    @staticmethod
    def _raw_request_payload(request: Any) -> Dict[str, Any]:
        """A plugin's raw upload request, as text, with its file path normalized."""
        if not isinstance(request, Mapping):
            raise TypeError("build_raw_upload_request must return a dict")
        fields = {}
        for name, spec in dict(request.get("multipart_fields") or {}).items():
            kind = str(spec.get("type") or "text")
            value = str(spec.get("value") or "")
            fields[str(name)] = {
                "type": kind,
                "value": os.path.normpath(value) if kind == "file" and value else value,
            }
        payload: Dict[str, Any] = {
            "url": str(request.get("url") or ""),
            "method": str(request.get("method") or "POST").upper(),
            "headers": {str(k): str(v) for k, v in dict(request.get("headers") or {}).items()},
            "multipart_fields": fields,
        }
        form_fields = request.get("form_fields")
        if form_fields:
            payload["form_fields"] = {str(k): str(v) for k, v in dict(form_fields).items()}
        return payload

    def _advance_session_job(self, job: _SessionJob) -> None:
        """Send the job's next files, or finish it once nothing is left to wait for.

        Called whenever a sidecar job of it completes or a parse ends; it does
        something only when neither is outstanding. Finishing ends files that
        were never sent and closes the session if its process is alive.

        Choosing the next files and reserving their sidecar job happen in one
        ``_jobs_lock`` section: two advances (a parse's and batch_complete's)
        can run at once, and the second must find the first one's job
        outstanding, or a sequential job would send two files at once, or
        finish and close its session while its last file is being sent.
        """
        send: List[str] = []
        job_id = ""
        leftovers: List[str] = []
        end_status = ""
        close = False
        with self._jobs_lock:
            if job.finished or job.sidecar_jobs or job.post_pending:
                return
            if not job.dead and not self._session_alive(job.session):
                self._mark_session_dead(job, f"error: {PROCESS_RESTARTED_MSG}")
            superseded = self._token_superseded(job.cancel)
            cancelled = self._token_cancelled(job.cancel)
            if job.queued and not (job.dead or cancelled or superseded):
                if job.sequential:
                    send = [job.queued.pop(0)]
                else:
                    send, job.queued = job.queued, []
                job_id = self._reserve_session_sidecar_job(job, send)
            else:
                leftovers, job.queued = job.queued, []
                job.finished = True
                if job in self._open_session_jobs:
                    self._open_session_jobs.remove(job)
                if superseded:
                    leftovers = []  # a cleared batch's rows are gone
                end_status = "Cancelled" if cancelled else (job.end_status or "Cancelled")
                close = not job.dead and self._session_alive(job.session)
        if job_id:
            self._send_session_sidecar_job(job, job_id, send)
            return
        self._finish_files(leftovers, end_status)
        if close:
            self._close_session(job.session)

    def _reserve_session_sidecar_job(self, job: _SessionJob, files: List[str]) -> str:
        """Register the next sidecar job of ``job`` for ``files``; call with ``_jobs_lock`` held."""
        job.sent_jobs += 1
        job_id = job.id_base if job.sent_jobs == 1 else f"{job.id_base}.{job.sent_jobs}"
        job.sidecar_jobs.add(job_id)
        self._session_jobs[job_id] = job
        self.active_files.update(files)
        self._register_job(job_id, files)
        return job_id

    def _send_session_sidecar_job(self, job: _SessionJob, job_id: str, files: List[str]) -> None:
        """Write a reserved sidecar job; never call with ``_jobs_lock`` held."""
        payload: Dict[str, Any] = {
            "id": job_id,
            "batch_id": job.batch_id,
            "action": "http_upload",
            "service": job.service,
            "files": [os.path.normpath(fp) for fp in files],
            "creds": {},
            "config": job.str_config,
            "context_data": {},
            "raw_response": True,
            "session_id": job.session.session_id,
            "sequential": job.sequential,
            "file_requests": {os.path.normpath(fp): job.requests[fp] for fp in files},
        }
        if job.rate_limits:
            payload["rate_limits"] = job.rate_limits
        if self._submit_job(job_id, payload, generation=job.session.generation):
            return
        status_text = (
            f"error: {PROCESS_RESTARTED_MSG}"
            if self._session_process_gone(job.session)
            else "error: sidecar unavailable"
        )
        with self._jobs_lock:
            # A Clear List or a crash report may have ended the job meanwhile;
            # its files are then no longer this job's to report.
            owned = self._job_files.pop(job_id, None) is not None
            self._session_jobs.pop(job_id, None)
            job.sidecar_jobs.discard(job_id)
            self._mark_session_dead(job, status_text)
            for fp in files:
                self.active_files.discard(fp)
        if owned:
            self._finish_files(files, status_text)
        self._advance_session_job(job)

    def _session_process_gone(self, session: TransportSession) -> bool:
        """Whether the bridge runs another process now, or none, than the session's."""
        current = getattr(self.bridge, "generation", None)
        if isinstance(current, int) and isinstance(session.generation, int):
            if current != session.generation:
                return True
        alive = getattr(self.bridge, "is_process_alive", None)
        return callable(alive) and alive() is False

    def _mark_session_dead(self, job: _SessionJob, status_text: str) -> None:
        """The session's sidecar process is gone; call with ``_jobs_lock`` held."""
        if not job.dead:
            job.dead = True
            job.end_status = status_text
        self._post_pool.submit(lambda: self._advance_session_job(job))

    def _session_sidecar_job_done(self, job_id: str, unfinished: List[str] = ()) -> None:
        """The sidecar reports nothing more for ``job_id``; call with ``_jobs_lock`` held."""
        session_jobs = getattr(self, "_session_jobs", None)
        job = session_jobs.pop(job_id, None) if session_jobs else None
        if job is None:
            return
        job.sidecar_jobs.discard(job_id)
        for file_path in unfinished:
            job.state.settle(os.path.normpath(file_path))
        self._post_pool.submit(lambda: self._advance_session_job(job))

    def _accept_raw_result(self, job: _SessionJob, file_path: str, data: Dict[str, Any]) -> None:
        """Hand a raw upload result to the pool. Runs on the event listener: never blocks."""
        self.active_files.discard(file_path)
        payload = data.get("data") if isinstance(data.get("data"), dict) else {}
        response = TransportResponse(
            ok=True,
            status="success",
            body=str(payload.get("response_body") or ""),
            status_code=_status_code(payload.get("status_code")),
            final_url=str(payload.get("final_url") or ""),
            data=dict(payload),
            raw=dict(data),
        )
        if response.status_code not in REFUSAL_STATUS_CODES:
            # A 429/503 here is the last refusal after the sidecar's retries ran
            # out: the host did not take the file, so it is not counted.
            job.state.record_uploaded(os.path.normpath(file_path))
        with self._jobs_lock:
            job.post_pending += 1
        self._post_pool.submit(lambda: self._post_process(job, file_path, response))

    def _post_process(self, job: _SessionJob, file_path: str, response: TransportResponse) -> None:
        """Run the plugin's parser for one file and report Done or the failure."""
        key = os.path.normpath(file_path)
        try:
            if self._token_superseded(job.cancel):
                return  # cleared: its row is gone, and the file may be queued again
            try:
                result = job.plugin.parse_upload_response(
                    key, response, job.transport, dict(job.session_values), job.state
                )
                if not isinstance(result, UploadResult):
                    result = UploadResult.failed(
                        "could not read the host's answer: the parser returned "
                        f"{type(result).__name__}, not an UploadResult"
                    )
            except Exception as exc:
                logger.exception(f"{job.service}: parsing the upload of {file_path} failed")
                result = UploadResult.failed(f"could not read the host's answer: {exc}")
            self._report_parsed_or_fail(job, file_path, result)
        finally:
            job.state.settle(key)
            with self._jobs_lock:
                job.post_pending -= 1
            self._advance_session_job(job)

    def _report_parsed_or_fail(
        self, job: _SessionJob, file_path: str, result: UploadResult
    ) -> None:
        """Report a parsed file; if reading the result fails, fail the file instead.

        Reading a result can raise (a thumbnail link the canonicalisation
        cannot split, for example). The file must still end, or the batch
        never finishes.
        """
        try:
            self._report_parsed(job, file_path, result)
            return
        except Exception as exc:
            logger.exception(f"{job.service}: reporting the upload of {file_path} failed")
            reason = f"could not read the host's answer: {exc}"
        try:
            self._report_parsed(job, file_path, UploadResult.failed(reason))
        except Exception:
            logger.exception(f"{job.service}: could not report the failure of {file_path}")
            if not self._token_superseded(job.cancel):
                self._finish_files([file_path], "error: could not read the host's answer")

    def _report_parsed(self, job: _SessionJob, file_path: str, result: UploadResult) -> None:
        """Report a parsed file. Never call with ``_jobs_lock`` held."""
        if self._token_superseded(job.cancel):
            return  # cleared while the parser ran
        items: List[Tuple[queue.Queue, Any]] = []
        if result.ok:
            gallery_url = result.gallery_url.strip()
            if gallery_url:
                items.append((self.progress_queue, ("gallery_url", file_path, gallery_url)))
            thumb = self._canonicalize_imx_thumbnail_url(result.thumb)
            items.append((self.result_queue, (file_path, result.url, thumb)))
            items.append((self.progress_queue, ("status", file_path, "Done")))
        elif self._token_cancelled(job.cancel):
            items.append((self.result_queue, (file_path, "", "")))
            items.append((self.progress_queue, ("status", file_path, "Cancelled")))
        else:
            reason = redact_secrets(result.failure_reason, job.state.secrets)
            logger.warning(f"{job.service}: {os.path.basename(file_path)} failed: {reason}")
            items.append((self.result_queue, (file_path, "", "")))
            items.append((self.progress_queue, ("status", file_path, f"error: {reason}")))
        self._deliver(items)

    @staticmethod
    def _credentials_for_plugin(plugin: Any, creds: Dict[str, str]) -> Dict[str, str]:
        """Return only the credentials the plugin declares in its metadata.

        Job credentials are serialized to the sidecar and merged into its
        template-substitution values, so every other service's passwords and
        API keys stay in Python. Plugins read their full credentials on the
        Python side (build_http_request, prepare_group) as before.
        """
        metadata = getattr(plugin, "metadata", None) or {}
        declared = [
            str(item.get("key")) for item in metadata.get("credentials", []) if item.get("key")
        ]
        return {key: creds[key] for key in declared if key in creds}

    @staticmethod
    def _normalize_job_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Return a sidecar-ready config with service thread controls normalized."""
        normalized = cfg.copy()
        service_id = config.normalize_service_id(normalized.get("service", ""))
        normalized["service"] = service_id
        # Thread Limit (global_thread_limit) is the primary concurrent-file control.
        # Fall back to per-service keys only when the global limit is unset.
        thread_value = normalized.get("global_thread_limit")

        if thread_value in (None, ""):
            thread_key = SERVICE_THREAD_KEYS.get(service_id)
            if thread_key and normalized.get(thread_key) not in (None, ""):
                thread_value = normalized[thread_key]

        try:
            threads = int(
                thread_value
                if thread_value not in (None, "")
                else normalized.get("threads", config.DEFAULT_THREAD_COUNT)
            )
        except (TypeError, ValueError):
            threads = config.DEFAULT_THREAD_COUNT

        normalized["threads"] = max(
            config.MIN_THREAD_COUNT,
            min(config.MAX_THREAD_COUNT, threads),
        )
        return normalized

    @staticmethod
    def _rate_limits_for_job(
        service_id: str, job_cfg: Dict[str, Any]
    ) -> Dict[str, float | int] | None:
        """Return optional proactive rate limits for an upload job.

        Default is no proactive limit (legacy parity). Explicit SERVICE_RATE_LIMITS
        or job_cfg rate_limit_* keys can re-enable throttling per host.
        """
        override = SERVICE_RATE_LIMITS.get(service_id)
        if not override:
            rps = job_cfg.get("rate_limit_rps")
            burst = job_cfg.get("rate_limit_burst")
            if rps in (None, "", 0, 0.0, "0"):
                return None
            try:
                return {
                    "requests_per_second": float(rps),
                    "burst_size": int(
                        burst if burst not in (None, "") else max(int(float(rps)), 1)
                    ),
                }
            except (TypeError, ValueError):
                return None

        try:
            rps = float(override.get("requests_per_second", 0))
        except (TypeError, ValueError):
            return None
        if rps <= 0:
            return None
        try:
            burst = int(override.get("burst_size", max(int(rps), 1)))
        except (TypeError, ValueError):
            burst = max(int(rps), 1)
        payload: Dict[str, float | int] = {
            "requests_per_second": rps,
            "burst_size": max(burst, 1),
        }
        if "global_limit" in override:
            try:
                payload["global_limit"] = float(override["global_limit"])
            except (TypeError, ValueError):
                pass
        return payload

    def _process_events(self) -> None:
        """Read events from the bridge and update UI-facing queues."""
        while self._listener_should_run():
            try:
                data = self.event_queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self._handle_event(data)
            except Exception as exc:
                logger.error(f"Event processing error: {exc}")

    def _fail_active_files(self, files: List[str], reason: str) -> None:
        for file_path in files:
            if file_path not in self.active_files:
                continue
            self.active_files.discard(file_path)
            self.result_queue.put((file_path, "", ""))
            self.progress_queue.put(("status", file_path, f"error: {reason}"))

    def _handle_process_crash(self, data: Dict[str, Any]) -> None:
        """End the jobs that died with a sidecar process.

        The bridge restarts the process, but whatever that process was doing
        is gone: without this its files would never get a terminal status and
        the batch would never finish.
        """
        generation = data.get("generation")
        reason = str(data.get("msg") or PROCESS_RESTARTED_MSG)
        logger.error(f"SIDECAR CRASHED (process {generation}): {reason}")
        ended: List[Tuple[queue.Queue, Any]] = []
        with self._jobs_lock:
            if isinstance(generation, int):
                self._dead_generation = max(self._dead_generation, generation)
            # Transport sessions die with their process: never close them, and
            # end the files of a session job that were not sent yet.
            for job in list(getattr(self, "_open_session_jobs", [])):
                session_generation = job.session.generation
                if (
                    not isinstance(generation, int)
                    or session_generation is None
                    or session_generation <= generation
                ):
                    self._mark_session_dead(job, f"error: {reason}")
            for job_id in list(self._job_files):
                if job_id not in self._job_generation:
                    continue  # still being written; _submit_job checks the generation
                job_generation = self._job_generation[job_id]
                if (
                    not isinstance(generation, int)
                    or job_generation is None
                    or job_generation <= generation
                ):
                    ended += self._end_job(job_id, f"error: {reason}")
        self._deliver(ended)

    def _handle_event(self, data: Dict[str, Any]) -> None:
        """Translate one sidecar event into progress/result queue items."""
        evt = data.get("type")
        fp = data.get("file") or data.get("file_path")
        job_id = data.get("id")

        if evt == SIDECAR_CRASHED_EVENT:
            self._handle_process_crash(data)
            return

        if evt == "sidecar_stopped":
            logger.error(f"SIDECAR STOPPED: {data.get('msg')}")
            reason = str(data.get("msg") or "sidecar stopped")
            with self._jobs_lock:
                ended = self._end_all_jobs_locked(f"error: {reason}")
                stragglers = list(self.active_files)
            self._deliver(ended)
            self._fail_active_files(stragglers, reason)
            return

        if job_id and job_id not in self._job_files:
            # Replies to request_sync callers or a previous batch: not ours.
            logger.debug(f"Ignoring sidecar event for unknown job {job_id}")
            return

        session_job = self._session_jobs.get(job_id) if job_id else None
        if session_job is not None and fp:
            if evt == "result":
                # A raw result: the host's answer, for the plugin to parse.
                self._accept_raw_result(session_job, fp, data)
                return
            if evt == "status" and data.get("status") in TERMINAL_FILE_STATUSES:
                details = data.get("data") if isinstance(data.get("data"), dict) else {}
                if _config_flag(details.get("body_sent")):
                    # Failed after the host received the whole file: the host
                    # may list it on its result page.
                    session_job.state.record_uploaded(os.path.normpath(fp))
                session_job.state.settle(os.path.normpath(fp))

        if evt in ("result", "error") and fp:
            self.active_files.discard(fp)
        if evt == "result" and fp:
            self._awaiting_done.add(fp)
        elif evt == "status" and fp and data.get("status") in TERMINAL_FILE_STATUSES:
            self.active_files.discard(fp)
            self._awaiting_done.discard(fp)

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
            thumb = self._canonicalize_imx_thumbnail_url(thumb)
            self.result_queue.put((fp, url, thumb))

        elif evt == "batch_complete":
            logger.debug("SIDECAR: batch complete")
            if job_id:
                # As after a crash: a file whose result arrived only lost its
                # "Done"; every other unfinished file failed. For a raw job,
                # _end_job also hands the job back to its session job; files
                # whose raw result arrived are left to their parser.
                with self._jobs_lock:
                    ended = self._end_job(job_id, "error: no result received from sidecar")
                self._deliver(ended)

        elif evt == "log":
            logger.debug(f"SIDECAR: {data.get('msg')}")

        elif evt == "error":
            msg = data.get("msg")
            if session_job is not None:
                # A raw upload's transport error can quote its request (a
                # url.Error names the upload URL), which the plugin may have
                # built from credentials or session values.
                msg = redact_secrets(str(msg or ""), session_job.state.secrets)
            logger.error(f"SIDECAR ERROR: {msg}")
            if fp:
                self.progress_queue.put(("status", fp, f"error: {msg}"))
            elif job_id and session_job is not None:
                # The sidecar rejected the whole raw job (an invalid job or a
                # recovered panic) and sends no batch_complete after it.
                with self._jobs_lock:
                    ended = self._end_job(job_id, f"error: {msg or 'sidecar error'}")
                self._deliver(ended)
            elif job_id:
                self._fail_active_files(
                    self._job_files.get(job_id, []), str(data.get("msg") or "sidecar error")
                )

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
