# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""ViperGirls posting targets, posting history, and scheduled posts on disk.

Every load-modify-save on these JSON files runs under one process-wide lock
(the UI thread, the AutoPoster, and the scheduler all write them) and writes
through a uniquely named temp file. No network or Tk code lives here.
"""

from datetime import datetime, timezone
import functools
import json
import os
import re
import shutil
import tempfile
import threading
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from loguru import logger

# Store threads file in user's home directory.
_USER_DATA_DIR = os.path.join(os.path.expanduser("~"), ".conniesuploader")


THREADS_FILE = os.path.join(_USER_DATA_DIR, "saved_threads.json")


POSTING_HISTORY_FILE = os.path.join(_USER_DATA_DIR, "posting_history.json")


SCHEDULED_POSTS_FILE = os.path.join(_USER_DATA_DIR, "scheduled_posts.json")


POSTING_HISTORY_LIMIT = 500


TARGETS_EXPORT_VERSION = 1


VIPERGIRLS_BASE_URL = "https://vipergirls.to"


# One process-wide lock serializes every load-modify-save on the JSON files in
# the user data directory. The UI thread, the AutoPoster, and the scheduler all
# write them; without the lock a slow writer overwrote newer records.
_STORAGE_LOCK = threading.RLock()


def _locked(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _STORAGE_LOCK:
            return func(*args, **kwargs)

    return wrapper


def _atomic_write_json(path: str, payload: Any) -> None:
    """Write JSON through a uniquely named temp file, then rename over ``path``."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=directory,
        prefix=os.path.basename(path) + ".",
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
            f.write("\n")
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


THREAD_ID_PATTERNS = (
    re.compile(r"^\d+$"),
    re.compile(r"(?:^|/)threads/(\d+)", re.IGNORECASE),
    re.compile(r"(?:^|/)showthread\.php(?:\?[^#]*)?\bt=(\d+)", re.IGNORECASE),
    re.compile(r"(?:^|[?&;])t=(\d+)", re.IGNORECASE),
)


class ThreadTargetError(ValueError):
    """Raised when a ViperGirls posting target cannot be normalized."""


class ViperPostError(RuntimeError):
    """Raised when a ViperGirls page cannot be prepared for posting."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def extract_thread_id(value: str) -> Optional[str]:
    """Extract a ViperGirls thread ID from a URL, partial URL, query string, or raw ID."""
    text = (value or "").strip()
    if not text:
        return None

    for pattern in THREAD_ID_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        if match.groups():
            return match.group(1)
        return match.group(0)

    return None


def _is_supported_vipergirls_url(value: str) -> bool:
    parsed = urlparse(value)
    if not parsed.scheme:
        return True
    host = parsed.netloc.lower()
    return host == "vipergirls.to" or host.endswith(".vipergirls.to")


def _canonical_thread_url(thread_id: str) -> str:
    return f"{VIPERGIRLS_BASE_URL}/threads/{thread_id}"


def safe_target_url(url: str, thread_id: str) -> str:
    """Return ``url`` only when it points at ViperGirls; otherwise a canonical
    thread link for ``thread_id`` or an empty string.

    Saved and imported target files are user data; a foreign or non-http URL
    must never reach ``webbrowser.open``.
    """
    clean_url = str(url or "").strip()
    clean_id = extract_thread_id(str(thread_id or "")) or ""
    parsed = urlparse(clean_url)
    if (
        clean_url
        and parsed.scheme in ("http", "https")
        and parsed.netloc
        and _is_supported_vipergirls_url(clean_url)
    ):
        return clean_url
    if clean_id:
        return _canonical_thread_url(clean_id)
    return ""


def normalize_tags(tags: object) -> List[str]:
    """Normalize comma-separated or list-like target tags."""
    if tags is None:
        return []
    if isinstance(tags, str):
        raw_tags = tags.split(",")
    elif isinstance(tags, (list, tuple, set)):
        raw_tags = list(tags)
    else:
        raw_tags = [tags]

    normalized = []
    seen = set()
    for raw_tag in raw_tags:
        tag = str(raw_tag or "").strip()
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(tag)
    return normalized


def format_tags(tags: object) -> str:
    """Return a readable comma-separated tag string."""
    return ", ".join(normalize_tags(tags))


def normalize_thread_input(value: str) -> Tuple[str, str]:
    """Return normalized ``(url, thread_id)`` for accepted ViperGirls target input."""
    raw = (value or "").strip()
    thread_id = extract_thread_id(raw)
    if not thread_id:
        raise ThreadTargetError(
            "Enter a ViperGirls thread URL, threads/12345, showthread.php?t=12345, or a raw thread ID."
        )
    if not _is_supported_vipergirls_url(raw):
        raise ThreadTargetError("Only ViperGirls thread URLs are supported.")

    if urlparse(raw).scheme:
        return raw, thread_id
    return _canonical_thread_url(thread_id), thread_id


def clean_thread_title(raw_title: str) -> str:
    """Return a display-safe ViperGirls thread title."""
    title = " ".join(str(raw_title or "").split())
    if not title:
        return ""

    title = re.sub(r"^Thread:\s*", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(
        r"\s*(?:\||-)\s*ViperGirls(?:\.to)?(?:\s+Forum)?\s*$",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()

    if title.lower() in {"vipergirls", "log in", "login", "just a moment"}:
        return ""
    return title


def unique_target_name(
    base_name: str,
    thread_id: str = "",
    existing_names: Optional[Any] = None,
    exclude: Optional[str] = None,
) -> str:
    """Return a unique saved-target key while keeping the display name readable."""
    clean_name = clean_thread_title(base_name) or f"Thread {thread_id or 'Target'}"
    used = {str(name) for name in (existing_names or [])}
    if exclude:
        used.discard(exclude)

    if clean_name not in used:
        return clean_name

    if thread_id:
        candidate = f"{clean_name} ({thread_id})"
        if candidate not in used:
            return candidate

    suffix = 2
    while True:
        candidate = f"{clean_name} {suffix}"
        if candidate not in used:
            return candidate
        suffix += 1


def normalize_thread_record(
    name: str,
    target: str,
    existing: Optional[Dict[str, object]] = None,
    notes: Optional[str] = None,
    tags: Optional[object] = None,
    site_title: Optional[str] = None,
) -> Dict[str, object]:
    """Build the normalized saved record for a posting target."""
    clean_name = (name or "").strip()
    if not clean_name:
        raise ThreadTargetError("Target name is required.")

    url, thread_id = normalize_thread_input(target)
    existing = existing or {}
    now = _now_iso()
    saved_notes = existing.get("notes") if notes is None else notes
    saved_site_title = existing.get("site_title") if site_title is None else site_title
    return {
        "url": url,
        "thread_id": thread_id,
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
        "last_used_at": existing.get("last_used_at"),
        "notes": str(saved_notes or ""),
        "tags": normalize_tags(existing.get("tags") if tags is None else tags),
        "site_title": str(saved_site_title or ""),
    }


def _normalize_loaded_record(name: str, record: object) -> Tuple[Optional[Dict[str, object]], bool]:
    """Normalize one saved record from disk, tolerating older formats."""
    if not isinstance(name, str) or not name.strip():
        return None, True

    now = _now_iso()
    changed = False
    if isinstance(record, dict):
        url = str(record.get("url") or "")
        thread_id = str(record.get("thread_id") or extract_thread_id(url) or "")
        url = safe_target_url(url, thread_id)
        normalized = {
            "url": url,
            "thread_id": thread_id,
            "created_at": record.get("created_at") or now,
            "updated_at": record.get("updated_at") or now,
            "last_used_at": record.get("last_used_at"),
            "notes": str(record.get("notes") or ""),
            "tags": normalize_tags(record.get("tags")),
            "site_title": str(record.get("site_title") or ""),
        }
        expected_keys = {
            "url",
            "thread_id",
            "created_at",
            "updated_at",
            "last_used_at",
            "notes",
            "tags",
            "site_title",
        }
        changed = set(record.keys()) != expected_keys or any(
            record.get(key) != normalized.get(key) for key in expected_keys
        )
        return normalized, changed

    if isinstance(record, str):
        try:
            return normalize_thread_record(name, record), True
        except ThreadTargetError:
            legacy_id = extract_thread_id(record) or ""
            return {
                "url": safe_target_url(record, legacy_id),
                "thread_id": legacy_id,
                "created_at": now,
                "updated_at": now,
                "last_used_at": None,
                "notes": "",
                "tags": [],
                "site_title": "",
            }, True

    return None, True


def _backup_corrupt_threads_file(exc: Exception) -> None:
    if not os.path.exists(THREADS_FILE):
        return

    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = f"{THREADS_FILE}.corrupt-{stamp}.bak"
    try:
        shutil.copy2(THREADS_FILE, backup_path)
        logger.warning(f"Backed up unreadable ViperGirls targets to {backup_path}: {exc}")
    except OSError as backup_exc:
        logger.error(f"Failed to back up unreadable ViperGirls targets: {backup_exc}")


@_locked
def load_saved_threads() -> Dict[str, Dict[str, object]]:
    """Load and migrate saved ViperGirls posting targets."""
    if not os.path.exists(THREADS_FILE):
        return {}

    try:
        with open(THREADS_FILE, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except Exception as exc:
        _backup_corrupt_threads_file(exc)
        return {}

    if not isinstance(raw_data, dict):
        _backup_corrupt_threads_file(ValueError("saved thread data is not a JSON object"))
        return {}

    migrated: Dict[str, Dict[str, object]] = {}
    changed = False
    for raw_name, raw_record in raw_data.items():
        name = str(raw_name).strip()
        normalized, record_changed = _normalize_loaded_record(name, raw_record)
        if normalized is None:
            changed = True
            continue
        migrated[name] = normalized
        changed = changed or record_changed or raw_name != name

    if changed:
        try:
            save_saved_threads(migrated)
        except OSError as exc:
            logger.error(f"Failed to save migrated ViperGirls targets: {exc}")

    return migrated


@_locked
def save_saved_threads(saved_threads: Dict[str, Dict[str, object]]) -> None:
    """Atomically save normalized ViperGirls posting targets."""
    os.makedirs(_USER_DATA_DIR, exist_ok=True)
    _atomic_write_json(THREADS_FILE, saved_threads)


def validate_saved_thread_record(name: str, record: object) -> List[str]:
    """Return validation errors for a saved ViperGirls posting target."""
    errors = []
    clean_name = str(name or "").strip()
    if not clean_name:
        errors.append("Target name is required.")

    if isinstance(record, dict):
        url = str(record.get("url") or "")
        thread_id = str(record.get("thread_id") or "")
    else:
        url = str(record or "")
        thread_id = ""

    resolved_thread_id = extract_thread_id(thread_id) or extract_thread_id(url)
    if not resolved_thread_id:
        errors.append("Target needs a parseable thread ID.")
    if url and not _is_supported_vipergirls_url(url):
        errors.append("Target URL must be a ViperGirls URL.")
    return errors


def _import_record_target(record: object) -> str:
    if isinstance(record, dict):
        return str(record.get("url") or record.get("thread_id") or "")
    return str(record or "")


def _targets_from_import_payload(raw_data: object) -> Dict[str, object]:
    if isinstance(raw_data, dict) and isinstance(raw_data.get("targets"), dict):
        return raw_data["targets"]
    if isinstance(raw_data, dict):
        return raw_data
    if isinstance(raw_data, list):
        targets = {}
        for item in raw_data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("target_name") or "").strip()
            if name:
                targets[name] = item
        return targets
    raise ThreadTargetError("Import file must contain a target object or targets list.")


def import_saved_threads_file(
    filepath: str,
    existing: Optional[Dict[str, Dict[str, object]]] = None,
    overwrite: bool = True,
) -> Tuple[Dict[str, Dict[str, object]], int, int]:
    """Import saved targets from JSON and merge them with existing targets."""
    with open(filepath, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    raw_targets = _targets_from_import_payload(raw_data)
    merged = dict(existing or {})
    imported = 0
    skipped = 0

    for raw_name, raw_record in raw_targets.items():
        name = str(raw_name or "").strip()
        if not name:
            skipped += 1
            continue
        if name in merged and not overwrite:
            skipped += 1
            continue

        try:
            normalized = normalize_thread_record(
                name,
                _import_record_target(raw_record),
                existing=raw_record if isinstance(raw_record, dict) else None,
                notes=raw_record.get("notes") if isinstance(raw_record, dict) else None,
                tags=raw_record.get("tags") if isinstance(raw_record, dict) else None,
                site_title=raw_record.get("site_title") if isinstance(raw_record, dict) else None,
            )
        except ThreadTargetError:
            normalized, _changed = _normalize_loaded_record(name, raw_record)
            if normalized is None:
                skipped += 1
                continue

        merged[name] = normalized
        imported += 1

    return merged, imported, skipped


def export_saved_threads_file(
    filepath: str,
    saved_threads: Dict[str, Dict[str, object]],
    names: Optional[List[str]] = None,
) -> int:
    """Export saved targets to a portable JSON file."""
    selected_names = names if names is not None else sorted(saved_threads)
    targets = {name: saved_threads[name] for name in selected_names if name in saved_threads}
    export_data = {
        "version": TARGETS_EXPORT_VERSION,
        "exported_at": _now_iso(),
        "targets": targets,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=4, ensure_ascii=False)
        f.write("\n")
    return len(targets)


@_locked
def mark_thread_target_used(
    name: str, timestamp: Optional[str] = None
) -> Optional[Dict[str, object]]:
    """Update a saved target's last-used timestamp."""
    target_name = str(name or "").strip()
    if not target_name:
        return None

    saved_threads = load_saved_threads()
    if target_name not in saved_threads:
        return None

    used_at = timestamp or _now_iso()
    record = dict(saved_threads[target_name])
    record["last_used_at"] = used_at
    record["updated_at"] = record.get("updated_at") or used_at
    saved_threads[target_name] = record
    save_saved_threads(saved_threads)
    return record


def _backup_corrupt_json_file(filepath: str, exc: Exception) -> None:
    if not os.path.exists(filepath):
        return

    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = f"{filepath}.corrupt-{stamp}.bak"
    try:
        shutil.copy2(filepath, backup_path)
        logger.warning(f"Backed up unreadable JSON file to {backup_path}: {exc}")
    except OSError as backup_exc:
        logger.error(f"Failed to back up unreadable JSON file: {backup_exc}")


def _canonical_history_entry(entry: Dict[str, Any]) -> Dict[str, str]:
    thread_id = extract_thread_id(str(entry.get("thread_id") or "")) or ""
    target_url = str(entry.get("target_url") or "")
    if not target_url and thread_id:
        target_url = _canonical_thread_url(thread_id)

    return {
        "timestamp": str(entry.get("timestamp") or _now_iso()),
        "batch_name": str(entry.get("batch_name") or "Batch"),
        "target_name": str(entry.get("target_name") or ""),
        "thread_id": thread_id,
        "target_url": target_url,
        "status": str(entry.get("status") or "unknown"),
        "error": str(entry.get("error") or ""),
        "post_text": str(entry.get("post_text") or ""),
    }


@_locked
def load_posting_history() -> List[Dict[str, str]]:
    """Load persisted ViperGirls posting history."""
    if not os.path.exists(POSTING_HISTORY_FILE):
        return []

    try:
        with open(POSTING_HISTORY_FILE, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except Exception as exc:
        _backup_corrupt_json_file(POSTING_HISTORY_FILE, exc)
        return []

    if not isinstance(raw_data, list):
        _backup_corrupt_json_file(
            POSTING_HISTORY_FILE, ValueError("posting history is not a JSON list")
        )
        return []

    return [_canonical_history_entry(item) for item in raw_data if isinstance(item, dict)][
        -POSTING_HISTORY_LIMIT:
    ]


@_locked
def save_posting_history(history: List[Dict[str, Any]]) -> None:
    """Atomically save ViperGirls posting history."""
    os.makedirs(_USER_DATA_DIR, exist_ok=True)
    normalized = [_canonical_history_entry(item) for item in history if isinstance(item, dict)][
        -POSTING_HISTORY_LIMIT:
    ]
    _atomic_write_json(POSTING_HISTORY_FILE, normalized)


@_locked
def append_posting_history(entry: Dict[str, Any]) -> Dict[str, str]:
    """Append one ViperGirls posting attempt to history."""
    normalized = _canonical_history_entry(entry)
    history = load_posting_history()
    history.append(normalized)
    save_posting_history(history)
    return normalized


def clear_posting_history() -> None:
    """Clear persisted ViperGirls posting history."""
    save_posting_history([])


def _read_json_file(filepath: str, fallback: Any) -> Any:
    if not os.path.exists(filepath):
        return fallback
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        _backup_corrupt_json_file(filepath, exc)
        return fallback


def _parse_scheduled_time(value: str) -> Optional[datetime]:
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_scheduled_post(entry: Dict[str, Any]) -> Dict[str, str]:
    thread_id = extract_thread_id(str(entry.get("thread_id") or "")) or ""
    scheduled_time = str(entry.get("scheduled_time") or "")
    status = str(entry.get("status") or "pending").strip().lower() or "pending"
    if status not in {"pending", "posted", "failed"}:
        status = "pending"
    return {
        "id": str(entry.get("id") or ""),
        "thread_id": thread_id,
        "thread_name": str(entry.get("thread_name") or ""),
        "message": str(entry.get("message") or ""),
        "scheduled_time": scheduled_time,
        "status": status,
        "error": str(entry.get("error") or ""),
        "cover_thumbnail": str(entry.get("cover_thumbnail") or ""),
    }


@_locked
def load_scheduled_posts() -> List[Dict[str, str]]:
    """Load persisted ViperGirls scheduled posts."""
    raw_data = _read_json_file(SCHEDULED_POSTS_FILE, [])
    if not isinstance(raw_data, list):
        _backup_corrupt_json_file(
            SCHEDULED_POSTS_FILE, ValueError("scheduled posts data is not a JSON list")
        )
        return []
    return [_canonical_scheduled_post(item) for item in raw_data if isinstance(item, dict)]


@_locked
def save_scheduled_posts(posts: List[Dict[str, Any]]) -> None:
    """Atomically save ViperGirls scheduled posts."""
    os.makedirs(_USER_DATA_DIR, exist_ok=True)
    normalized = [_canonical_scheduled_post(item) for item in posts if isinstance(item, dict)]
    _atomic_write_json(SCHEDULED_POSTS_FILE, normalized)


@_locked
def add_scheduled_post(post: Dict[str, Any]) -> Dict[str, str]:
    """Persist one pending ViperGirls scheduled post."""
    normalized = _canonical_scheduled_post({**post, "status": "pending", "error": ""})
    if not normalized["id"]:
        raise ViperPostError("Scheduled post is missing an ID.")
    if not normalized["thread_id"]:
        raise ViperPostError("Scheduled post is missing a thread ID.")
    if not normalized["message"].strip():
        raise ViperPostError("Scheduled post message is empty.")
    if _parse_scheduled_time(normalized["scheduled_time"]) is None:
        raise ViperPostError("Scheduled post time is invalid.")

    posts = [item for item in load_scheduled_posts() if item.get("id") != normalized["id"]]
    posts.append(normalized)
    save_scheduled_posts(posts)
    return normalized


@_locked
def cancel_scheduled_post(post_id: str) -> bool:
    """Remove a pending scheduled post by ID."""
    clean_id = str(post_id or "").strip()
    posts = load_scheduled_posts()
    kept = [
        post
        for post in posts
        if not (post.get("id") == clean_id and post.get("status") == "pending")
    ]
    if len(kept) == len(posts):
        return False
    save_scheduled_posts(kept)
    return True


@_locked
def set_scheduled_post_status(
    post_id: str, status: str, error: str = ""
) -> Optional[Dict[str, str]]:
    """Update one scheduled post on disk and return it, or None if unknown."""
    clean_id = str(post_id or "").strip()
    posts = load_scheduled_posts()
    updated = _update_scheduled_post_status(posts, clean_id, status, error)
    match = next((item for item in updated if item.get("id") == clean_id), None)
    if match is None:
        return None
    save_scheduled_posts(updated)
    return match


def _update_scheduled_post_status(
    posts: List[Dict[str, str]],
    post_id: str,
    status: str,
    error: str = "",
) -> List[Dict[str, str]]:
    updated = []
    for post in posts:
        if post.get("id") == post_id:
            item = dict(post)
            item["status"] = status
            item["error"] = error
            updated.append(item)
        else:
            updated.append(post)
    return updated
