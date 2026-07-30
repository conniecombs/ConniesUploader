# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""UI-neutral output generation for uploaded batches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import config
from .file_handler import sanitize_filename
from .gallery_service import gallery_url_for_service

UploadResultTuple = Tuple[str, str, str]
RenderedImageTuple = Tuple[str, str, str]


THREAD_ID_PATTERNS = (
    re.compile(r"^\d+$"),
    re.compile(r"(?:^|/)threads/(\d+)", re.IGNORECASE),
    re.compile(r"(?:^|/)showthread\.php(?:\?[^#]*)?\bt=(\d+)", re.IGNORECASE),
    re.compile(r"(?:^|[?&;])t=(\d+)", re.IGNORECASE),
)


@dataclass(frozen=True)
class GeneratedBatchOutput:
    text: str
    output_file: str
    history_file: str
    links_file: str | None
    context: Dict[str, Any]
    group_results: List[RenderedImageTuple]
    copyable: bool = True
    failed_report: bool = False


def cover_files_for_group(group: Any) -> List[str]:
    cover_filepaths = getattr(group, "cover_filepaths", None)
    if callable(cover_filepaths):
        return list(cover_filepaths())

    cover_files = getattr(group, "cover_files", [])
    cover_set = set(cover_files or [])
    return [filepath for filepath in getattr(group, "files", []) if filepath in cover_set]


def ordered_group_files_for_output(group: Any) -> List[str]:
    files = list(getattr(group, "files", []))
    covers = cover_files_for_group(group)
    if not covers:
        return files

    cover_set = set(covers)
    return [filepath for filepath in files if filepath in cover_set] + [
        filepath for filepath in files if filepath not in cover_set
    ]


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def upload_result_map(results: Iterable[Any]) -> Dict[str, Tuple[str, str]]:
    """Return successful upload URLs keyed by source path."""
    result_map: Dict[str, Tuple[str, str]] = {}
    for result in results:
        if hasattr(result, "file_path"):
            file_path = _clean_text(getattr(result, "file_path", ""))
            viewer_url = _clean_text(getattr(result, "viewer_url", ""))
            thumb_url = _clean_text(getattr(result, "thumb_url", ""))
            success = bool(getattr(result, "success", bool(viewer_url)))
            if file_path and success and viewer_url:
                result_map[file_path] = (viewer_url, thumb_url)
            continue

        try:
            file_path, viewer_url, thumb_url = result[:3]
        except (TypeError, ValueError):
            continue
        file_path = _clean_text(file_path)
        viewer_url = _clean_text(viewer_url)
        thumb_url = _clean_text(thumb_url)
        if file_path and viewer_url:
            result_map[file_path] = (viewer_url, thumb_url)
    return result_map


def upload_error_map(results: Iterable[Any]) -> Dict[str, str]:
    """Return explicit failed-upload errors from structured result objects."""
    errors: Dict[str, str] = {}
    for result in results:
        if not hasattr(result, "file_path"):
            continue
        file_path = _clean_text(getattr(result, "file_path", ""))
        if not file_path:
            continue
        success = bool(getattr(result, "success", False))
        viewer_url = _clean_text(getattr(result, "viewer_url", ""))
        if success and viewer_url:
            continue
        errors[file_path] = _clean_text(getattr(result, "error", ""))
    return errors


def thumbnail_size_for_service(service_id: str, settings: Dict[str, Any]) -> str:
    service_id = config.normalize_service_id(service_id)
    if service_id == "imx.to":
        return str(settings.get("imx_thumb", "180"))
    if service_id == config.PIXHOST_SERVICE_ID:
        return str(settings.get("pix_thumb", "200"))
    if service_id == "turboimagehost":
        return str(settings.get("turbo_thumb", "180"))
    if service_id == "vipr.im":
        thumb_size = str(settings.get("vipr_thumb", "170x170"))
        return thumb_size.split("x")[0] if "x" in thumb_size else thumb_size
    if service_id == "imagebam.com":
        return str(settings.get("imagebam_thumb", "180"))
    if service_id == "imgur.com":
        return str(settings.get("imgur_thumb", settings.get("thumbnail_size", "m")))
    return "250"


def gallery_id_from_url(service_id: str, gallery_url: str) -> str:
    service_id = config.normalize_service_id(service_id)
    gallery_url = config.normalize_pixhost_url(gallery_url)
    if service_id == "turboimagehost" and "/album/" in gallery_url:
        return gallery_url.split("/album/", 1)[1].split("/", 1)[0].strip()
    if service_id == "imagebam.com" and "/view/" in gallery_url:
        return gallery_url.split("/view/", 1)[1].split("/", 1)[0].strip()
    if service_id == config.PIXHOST_SERVICE_ID:
        for marker in ("/gallery/", "/galleries/"):
            if marker in gallery_url:
                return gallery_url.split(marker, 1)[1].split("/", 1)[0].strip()
    return ""


def gallery_id_from_settings(service_id: str, settings: Dict[str, Any]) -> str:
    service_id = config.normalize_service_id(service_id)
    if service_id == config.PIXHOST_SERVICE_ID:
        return str(settings.get("gallery_hash") or settings.get("pix_gallery_hash") or "").strip()
    if service_id == "vipr.im":
        gallery_name = str(settings.get("vipr_gallery_name") or "").strip()
        if not gallery_name or gallery_name == "None":
            return ""
        mapped_id = str(settings.get("vipr_gal_id") or "").strip()
        return "" if mapped_id == "0" else mapped_id
    if service_id == "imx.to":
        return str(settings.get("gallery_id") or settings.get("imx_gallery_id") or "").strip()
    return str(settings.get("gallery_id") or settings.get("turbo_gallery_id") or "").strip()


def selected_gallery_for_service(
    service_id: str,
    settings: Dict[str, Any],
    selected_gallery_by_service: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[Dict[str, str]]:
    service_id = config.normalize_service_id(service_id)
    record = None
    if isinstance(selected_gallery_by_service, dict):
        record = selected_gallery_by_service.get(service_id)
        if record is None and service_id == config.PIXHOST_SERVICE_ID:
            record = selected_gallery_by_service.get(config.PIXHOST_LEGACY_SERVICE_ID)
    if not isinstance(record, dict):
        selected_from_settings = settings.get("selected_gallery_by_service", {})
        if isinstance(selected_from_settings, dict):
            record = selected_from_settings.get(service_id)
            if record is None and service_id == config.PIXHOST_SERVICE_ID:
                record = selected_from_settings.get(config.PIXHOST_LEGACY_SERVICE_ID)
    if not isinstance(record, dict):
        return None

    gallery_id = str(record.get("id") or "").strip()
    if not gallery_id:
        return None
    return {
        "service": config.normalize_service_id(record.get("service") or service_id),
        "id": gallery_id,
        "name": str(record.get("name") or gallery_id),
        "url": config.normalize_pixhost_url(
            str(record.get("url") or gallery_url_for_service(service_id, gallery_id))
        ),
        "upload_hash": str(record.get("upload_hash") or ""),
    }


def gallery_for_group(
    group: Any,
    service_id: str,
    settings: Dict[str, Any],
    selected_gallery_by_service: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[Dict[str, str]]:
    service_id = config.normalize_service_id(service_id)
    group_gallery_id = str(getattr(group, "gallery_id", "") or "").strip()
    group_gallery_url = str(getattr(group, "gallery_url", "") or "").strip()
    if group_gallery_id or group_gallery_url:
        group_service = config.normalize_service_id(
            getattr(group, "gallery_service", "") or service_id
        )
        group_gallery_url = config.normalize_pixhost_url(group_gallery_url)
        if not group_gallery_id:
            group_gallery_id = gallery_id_from_url(group_service, group_gallery_url)
        return {
            "service": group_service,
            "id": group_gallery_id,
            "name": str(getattr(group, "gallery_name", "") or ""),
            "url": str(
                group_gallery_url or gallery_url_for_service(group_service, group_gallery_id)
            ),
            "upload_hash": str(getattr(group, "gallery_upload_hash", "") or ""),
        }

    selected = selected_gallery_for_service(
        service_id,
        settings,
        selected_gallery_by_service=selected_gallery_by_service,
    )
    if selected:
        return selected

    gallery_id = gallery_id_from_settings(service_id, settings)
    if not gallery_id:
        return None

    gallery_name = str(settings.get("selected_gallery_name") or "").strip()
    if service_id == "vipr.im":
        gallery_name = str(settings.get("vipr_gallery_name") or gallery_name).strip()
    return {
        "service": service_id,
        "id": gallery_id,
        "name": gallery_name,
        "url": str(settings.get("selected_gallery_url") or gallery_url_for_service(service_id, gallery_id)),
        "upload_hash": str(settings.get("selected_gallery_upload_hash") or ""),
    }


def extract_thread_id(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    for pattern in THREAD_ID_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1) if match.groups() else match.group(0)
    return ""


def thread_id_from_record(record: Any) -> str:
    if isinstance(record, dict):
        return extract_thread_id(str(record.get("thread_id") or "")) or extract_thread_id(
            str(record.get("url") or "")
        )
    return extract_thread_id(str(record or ""))


def build_rendered_results(
    group: Any,
    results: Iterable[Any],
    service_id: str,
) -> List[RenderedImageTuple]:
    service_id = config.normalize_service_id(service_id)
    result_map = upload_result_map(results)
    rendered = []
    for file_path in ordered_group_files_for_output(group):
        if file_path not in result_map:
            continue
        viewer_url, thumb_url = result_map[file_path]
        direct_url = viewer_url
        if service_id == "imx.to" and "/t/" in thumb_url:
            direct_url = thumb_url.replace("/t/", "/i/")
        rendered.append((viewer_url, thumb_url, direct_url))
    return rendered


def links_requested(settings: Dict[str, Any]) -> bool:
    service_id = config.normalize_service_id(settings.get("service", ""))
    if settings.get("save_links"):
        return True
    if service_id == "imx.to" and settings.get("imx_links"):
        return True
    if service_id == config.PIXHOST_SERVICE_ID and settings.get("pix_links"):
        return True
    if service_id == "turboimagehost" and settings.get("turbo_links"):
        return True
    if service_id == "vipr.im" and settings.get("vipr_links"):
        return True
    return False


def generate_group_output(
    group: Any,
    results: Iterable[Any],
    settings: Dict[str, Any],
    template_manager: Any,
    *,
    output_dir: str = config.OUTPUT_DIR,
    history_dir: str = config.HISTORY_DIR,
    selected_gallery_by_service: Optional[Dict[str, Dict[str, Any]]] = None,
    saved_threads_data: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Optional[GeneratedBatchOutput]:
    service_id = config.normalize_service_id(settings.get("service", ""))
    group_files = ordered_group_files_for_output(group)
    if not group_files:
        return None
    group_results = build_rendered_results(group, results, service_id)
    if len(group_results) != len(group_files):
        return None

    timestamp = now or datetime.now()
    gallery = gallery_for_group(
        group,
        service_id,
        settings,
        selected_gallery_by_service=selected_gallery_by_service,
    ) or {}
    batch_name = str(getattr(group, "title", "") or "").strip()
    gallery_id = str(gallery.get("id") or "")
    gallery_name = str(gallery.get("name") or batch_name)
    target_name = str(getattr(group, "selected_thread", "") or "").strip()
    saved_threads = saved_threads_data if isinstance(saved_threads_data, dict) else {}
    record = saved_threads.get(target_name, {})

    context = {
        "gallery_link": str(gallery.get("url") or ""),
        "gallery_name": gallery_name,
        "gallery_id": gallery_id,
        "cover_url": group_results[0][1],
        "cover_count": len(cover_files_for_group(group)),
        "thumb_size": thumbnail_size_for_service(service_id, settings),
        "batch_name": batch_name,
        "image_count": len(group_results),
        "service": service_id,
        "thread_name": target_name if target_name != "Do Not Post" else "",
        "thread_id": thread_id_from_record(record),
        "upload_date": timestamp.strftime("%Y-%m-%d"),
    }

    template_name = getattr(group, "selected_template", None) or settings.get(
        "output_format", "BBCode"
    )
    text = template_manager.apply(template_name, context, group_results)

    safe_title = sanitize_filename(batch_name)
    ts = timestamp.strftime("%Y%m%d_%H%M")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(history_dir, exist_ok=True)

    output_file = os.path.join(output_dir, f"{safe_title}_{ts}.txt")
    with open(output_file, "w", encoding="utf-8") as handle:
        handle.write(text)

    history_file = os.path.join(history_dir, f"{safe_title}_{ts}.txt")
    with open(history_file, "w", encoding="utf-8") as handle:
        handle.write(text)

    links_file = None
    if links_requested(settings):
        links_file = os.path.join(output_dir, f"{safe_title}_{ts}_links.txt")
        with open(links_file, "w", encoding="utf-8") as handle:
            handle.write("\n".join(item[0] for item in group_results))

    return GeneratedBatchOutput(
        text=text,
        output_file=output_file,
        history_file=history_file,
        links_file=links_file,
        context=context,
        group_results=group_results,
    )


def _group_file_status(
    file_path: str,
    result_map: Dict[str, Tuple[str, str]],
    error_map: Dict[str, str],
    file_states: Optional[Dict[str, Dict[str, Any]]],
) -> Tuple[str, str]:
    raw_state = {}
    if isinstance(file_states, dict):
        raw_state = file_states.get(file_path, {}) or {}
    state = _clean_text(raw_state.get("state")).lower()
    error = _clean_text(raw_state.get("error")) or error_map.get(file_path, "")

    if file_path in result_map and state != "failed":
        return "uploaded", error
    if state == "failed" or file_path in error_map:
        return "failed", error
    if state == "success":
        return "missing", error
    if state:
        return state, error
    return "missing", error


def generate_failed_group_output(
    group: Any,
    results: Iterable[Any],
    settings: Dict[str, Any],
    *,
    output_dir: str = config.OUTPUT_DIR,
    history_dir: str = config.HISTORY_DIR,
    failed_count: Optional[int] = None,
    file_states: Optional[Dict[str, Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> Optional[GeneratedBatchOutput]:
    """Write a diagnostic report for a batch that did not fully upload."""
    group_files = ordered_group_files_for_output(group)
    if not group_files:
        return None

    result_list = list(results)
    result_map = upload_result_map(result_list)
    error_map = upload_error_map(result_list)
    service_id = config.normalize_service_id(settings.get("service", ""))
    timestamp = now or datetime.now()
    batch_name = str(getattr(group, "title", "") or "Batch").strip() or "Batch"

    rows = []
    detected_failures = 0
    for file_path in group_files:
        status, error = _group_file_status(file_path, result_map, error_map, file_states)
        if status != "uploaded":
            detected_failures += 1
        name = os.path.basename(file_path)
        if status == "uploaded":
            viewer_url, thumb_url = result_map.get(file_path, ("", ""))
            rows.append(f"- {name}: Uploaded")
            if viewer_url:
                rows.append(f"  URL: {viewer_url}")
            if thumb_url:
                rows.append(f"  Thumb: {thumb_url}")
        elif status == "failed":
            rows.append(f"- {name}: FAILED")
            rows.append(f"  Reason: {error or 'Upload failed without more detail.'}")
        else:
            rows.append(f"- {name}: {status.title() or 'Missing'}")
            if error:
                rows.append(f"  Reason: {error}")
        rows.append(f"  Path: {file_path}")

    lines = [
        f"Batch: {batch_name}",
        "Status: FAILED",
        f"Service: {service_id or 'Unknown'}",
        f"Generated: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Failed uploads: {failed_count if failed_count is not None else detected_failures}",
        "",
        "Files:",
        *rows,
    ]
    text = "\n".join(lines) + "\n"

    safe_title = sanitize_filename(batch_name) or "Batch"
    ts = timestamp.strftime("%Y%m%d_%H%M")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(history_dir, exist_ok=True)

    output_file = os.path.join(output_dir, f"{safe_title}_{ts}_FAILED.txt")
    with open(output_file, "w", encoding="utf-8") as handle:
        handle.write(text)

    history_file = os.path.join(history_dir, f"{safe_title}_{ts}_FAILED.txt")
    with open(history_file, "w", encoding="utf-8") as handle:
        handle.write(text)

    return GeneratedBatchOutput(
        text=text,
        output_file=output_file,
        history_file=history_file,
        links_file=None,
        context={
            "batch_name": batch_name,
            "failed_count": failed_count if failed_count is not None else detected_failures,
            "service": service_id,
        },
        group_results=[
            (viewer_url, thumb_url, viewer_url)
            for viewer_url, thumb_url in result_map.values()
        ],
        copyable=False,
        failed_report=True,
    )
