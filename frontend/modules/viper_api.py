# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""ViperGirls API helpers and saved posting target management."""

from datetime import datetime, timezone
import json
import os
import re
import shutil
import threading
import time
import webbrowser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import customtkinter as ctk
import pyperclip
import requests
from bs4 import BeautifulSoup
from tkinter import filedialog, messagebox
from loguru import logger

from modules.credentials_manager import CredentialsManager
from modules.sidecar import SidecarBridge
from modules.transport import build_transport_spec, execute_transport_request

# Store threads file in user's home directory.
_USER_DATA_DIR = os.path.join(os.path.expanduser("~"), ".conniesuploader")
THREADS_FILE = os.path.join(_USER_DATA_DIR, "saved_threads.json")
POSTING_HISTORY_FILE = os.path.join(_USER_DATA_DIR, "posting_history.json")
SCHEDULED_POSTS_FILE = os.path.join(_USER_DATA_DIR, "scheduled_posts.json")
POSTING_HISTORY_LIMIT = 500
TARGETS_EXPORT_VERSION = 1
VIPERGIRLS_BASE_URL = "https://vipergirls.to"
THREAD_TITLE_TIMEOUT_SECONDS = 8
THREAD_TITLE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
VIPERGIRLS_RATE_LIMIT = {"requests_per_second": 1.0, "burst_size": 3}

THREAD_ID_PATTERNS = (
    re.compile(r"^\d+$"),
    re.compile(r"(?:^|/)threads/(\d+)", re.IGNORECASE),
    re.compile(r"(?:^|/)showthread\.php(?:\?[^#]*)?\bt=(\d+)", re.IGNORECASE),
    re.compile(r"(?:^|[?&;])t=(\d+)", re.IGNORECASE),
)
THREAD_TITLE_SELECTORS = (
    ".threadtitle",
    "span.threadtitle",
    "#thread_title",
    "h1.threadtitle",
    "h1.p-title-value",
    ".p-title-value",
    "h1",
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


def parse_thread_title_from_html(html_text: str) -> str:
    """Parse the thread title from ViperGirls/vBulletin-style HTML."""
    soup = BeautifulSoup(html_text or "", "html.parser")

    for selector in (
        "meta[property='og:title']",
        "meta[name='twitter:title']",
    ):
        element = soup.select_one(selector)
        title = clean_thread_title(element.get("content", "") if element else "")
        if title:
            return title

    for selector in THREAD_TITLE_SELECTORS:
        element = soup.select_one(selector)
        title = clean_thread_title(element.get_text(" ", strip=True) if element else "")
        if title:
            return title

    if soup.title:
        title = clean_thread_title(soup.title.get_text(" ", strip=True))
        if title:
            return title

    return ""


def fetch_thread_title(
    url: str,
    timeout: int = THREAD_TITLE_TIMEOUT_SECONDS,
    session: Optional[Any] = None,
) -> str:
    """Fetch the current ViperGirls thread title from the live thread page."""
    if not url or not _is_supported_vipergirls_url(url):
        return ""

    client = session or requests
    try:
        response = client.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": THREAD_TITLE_USER_AGENT,
                "Referer": f"{VIPERGIRLS_BASE_URL}/forum.php",
            },
        )
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()
        return parse_thread_title_from_html(getattr(response, "text", "") or "")
    except (requests.RequestException, AttributeError, ValueError) as exc:
        logger.warning(f"Could not fetch ViperGirls thread title for {url}: {exc}")
        return ""


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


def build_site_named_thread_record(
    fallback_name: str,
    target: str,
    existing: Optional[Dict[str, object]] = None,
    notes: Optional[str] = None,
    tags: Optional[object] = None,
    existing_names: Optional[Any] = None,
    exclude: Optional[str] = None,
    fetch_title: bool = True,
) -> Tuple[str, Dict[str, object], bool]:
    """Normalize a target and choose a saved name from the live thread title when possible."""
    url, thread_id = normalize_thread_input(target)
    existing = existing or {}
    site_title = fetch_thread_title(url) if fetch_title else ""
    previous_site_title = str(existing.get("site_title") or "").strip()
    display_name = site_title or previous_site_title or fallback_name or f"Thread {thread_id}"
    key_name = unique_target_name(display_name, thread_id, existing_names, exclude=exclude)
    record = normalize_thread_record(
        display_name,
        target,
        existing=existing,
        notes=notes,
        tags=tags,
        site_title=site_title or previous_site_title,
    )
    return key_name, record, bool(site_title)


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
        if not url and thread_id:
            url = _canonical_thread_url(thread_id)
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
            return {
                "url": record,
                "thread_id": extract_thread_id(record) or "",
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


def save_saved_threads(saved_threads: Dict[str, Dict[str, object]]) -> None:
    """Atomically save normalized ViperGirls posting targets."""
    os.makedirs(_USER_DATA_DIR, exist_ok=True)
    tmp_path = f"{THREADS_FILE}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(saved_threads, f, indent=4, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_path, THREADS_FILE)


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
    targets = {
        name: saved_threads[name]
        for name in selected_names
        if name in saved_threads
    }
    export_data = {
        "version": TARGETS_EXPORT_VERSION,
        "exported_at": _now_iso(),
        "targets": targets,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=4, ensure_ascii=False)
        f.write("\n")
    return len(targets)


def mark_thread_target_used(name: str, timestamp: Optional[str] = None) -> Optional[Dict[str, object]]:
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

    return [
        _canonical_history_entry(item)
        for item in raw_data
        if isinstance(item, dict)
    ][-POSTING_HISTORY_LIMIT:]


def save_posting_history(history: List[Dict[str, Any]]) -> None:
    """Atomically save ViperGirls posting history."""
    os.makedirs(_USER_DATA_DIR, exist_ok=True)
    normalized = [
        _canonical_history_entry(item)
        for item in history
        if isinstance(item, dict)
    ][-POSTING_HISTORY_LIMIT:]
    tmp_path = f"{POSTING_HISTORY_FILE}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=4, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_path, POSTING_HISTORY_FILE)


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


def load_scheduled_posts() -> List[Dict[str, str]]:
    """Load persisted ViperGirls scheduled posts."""
    raw_data = _read_json_file(SCHEDULED_POSTS_FILE, [])
    if not isinstance(raw_data, list):
        _backup_corrupt_json_file(
            SCHEDULED_POSTS_FILE, ValueError("scheduled posts data is not a JSON list")
        )
        return []
    return [
        _canonical_scheduled_post(item)
        for item in raw_data
        if isinstance(item, dict)
    ]


def save_scheduled_posts(posts: List[Dict[str, Any]]) -> None:
    """Atomically save ViperGirls scheduled posts."""
    os.makedirs(_USER_DATA_DIR, exist_ok=True)
    normalized = [
        _canonical_scheduled_post(item)
        for item in posts
        if isinstance(item, dict)
    ]
    tmp_path = f"{SCHEDULED_POSTS_FILE}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=4, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_path, SCHEDULED_POSTS_FILE)


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


def cancel_scheduled_post(post_id: str) -> bool:
    """Remove a pending scheduled post by ID."""
    clean_id = str(post_id or "").strip()
    posts = load_scheduled_posts()
    kept = [
        post for post in posts
        if not (post.get("id") == clean_id and post.get("status") == "pending")
    ]
    if len(kept) == len(posts):
        return False
    save_scheduled_posts(kept)
    return True


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


def _vipergirls_login_succeeded(body: str, final_url: str = "") -> bool:
    lowered = (body or "").lower()
    if "thank you for logging in" in lowered or "logout.php" in lowered:
        return True
    token_match = re.search(r"SECURITYTOKEN\s*=\s*\"([^\"]+)\"", body or "")
    if token_match and token_match.group(1).strip().lower() != "guest":
        return True
    return bool(re.search(r"(?i)(?:forum\.php|/forums?|/threads?)", final_url or ""))


def _vipergirls_post_succeeded(body: str, final_url: str = "") -> bool:
    if re.search(r"(?i)thank you for posting|redirecting", body or ""):
        return True
    return bool(re.search(r"(?i)(?:/threads/\d+|showthread\.php\?t=\d+)", final_url or ""))


def _extract_form_value(element: Any) -> str:
    if element.name == "textarea":
        return element.get_text() or ""
    if element.name == "select":
        selected = element.select_one("option[selected]")
        if selected is None:
            selected = element.select_one("option")
        return str(selected.get("value", selected.get_text(strip=True)) if selected else "")
    return str(element.get("value", ""))


def _copy_reply_form_fields(form: Any) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for element in form.select("input, textarea, select"):
        name = str(element.get("name") or "").strip()
        if not name:
            continue
        tag_name = str(element.name or "").lower()
        field_type = str(element.get("type") or "").lower()
        if tag_name == "input" and field_type in {"submit", "button", "image", "file"}:
            continue
        if field_type in {"checkbox", "radio"} and not element.has_attr("checked"):
            continue
        fields[name] = _extract_form_value(element)
    return fields


def _summarize_vipergirls_page(soup: BeautifulSoup) -> str:
    title = clean_thread_title(soup.title.get_text(" ", strip=True) if soup.title else "")
    page_text = " ".join((soup.get_text(" ", strip=True) or "").split())
    lowered = page_text.lower()
    if "you are not logged in" in lowered or "log in" == title.lower():
        return "ViperGirls returned a login page."
    if "no permission" in lowered or "do not have permission" in lowered:
        return "ViperGirls reported that this account cannot reply to the thread."
    if "thread is closed" in lowered or "closed thread" in lowered:
        return "ViperGirls reported that the thread is closed."
    if "just a moment" in lowered:
        return "ViperGirls returned an interstitial page."
    if title:
        return f"Reply form was not found on page '{title}'."
    return "Reply form was not found on the ViperGirls page."


def build_vipergirls_reply_spec(thread_id: str, message: str, html_text: str) -> Dict[str, Any]:
    """Parse a live ViperGirls reply page and build a resolved POST spec."""
    clean_thread_id = extract_thread_id(str(thread_id or "")) or ""
    if not clean_thread_id:
        raise ViperPostError("Thread ID is missing or invalid.")
    if not str(message or "").strip():
        raise ViperPostError("Post message is empty.")

    reply_url = f"{VIPERGIRLS_BASE_URL}/newreply.php?do=newreply&t={clean_thread_id}"
    soup = BeautifulSoup(html_text or "", "html.parser")
    form = None
    for candidate in soup.select("form"):
        action = str(candidate.get("action") or "")
        input_names = {
            str(element.get("name") or "")
            for element in candidate.select("input, textarea, select")
        }
        if (
            "newreply.php" in action
            and "do=postreply" in action
        ) or {"message", "securitytoken", "do"}.issubset(input_names):
            form = candidate
            break

    if form is None:
        raise ViperPostError(_summarize_vipergirls_page(soup))

    form_fields = _copy_reply_form_fields(form)
    required_fields = {"securitytoken", "do", "t", "loggedinuser"}
    missing = sorted(name for name in required_fields if name not in form_fields)
    if missing:
        raise ViperPostError(
            "ViperGirls reply form is missing required field(s): "
            + ", ".join(missing)
        )

    form_fields["message"] = str(message)
    form_fields["message_backup"] = ""
    form_fields["wysiwyg"] = form_fields.get("wysiwyg", "0") or "0"
    form_fields["iconid"] = form_fields.get("iconid", "0") or "0"
    form_fields["do"] = "postreply"
    form_fields["t"] = clean_thread_id
    form_fields["sbutton"] = "Submit Reply"
    form_fields.setdefault("signature", "1")
    form_fields.setdefault("parseurl", "1")
    form_fields.setdefault("emailupdate", "0")
    form_fields.setdefault("folderid", "0")
    form_fields.pop("preview", None)

    action = str(form.get("action") or f"newreply.php?do=postreply&t={clean_thread_id}")
    post_url = urljoin(VIPERGIRLS_BASE_URL + "/", action)
    return {
        "url": post_url,
        "method": "POST",
        "use_cookies": True,
        "form_fields": form_fields,
        "headers": {
            "Referer": reply_url,
        },
        "include_response_body": True,
        "include_transport_metadata": True,
    }


class ViperGirlsPostScheduler:
    """Python-owned scheduled-post runner for ViperGirls."""

    def __init__(self, creds: Dict[str, str], event_queue: Optional[Any] = None):
        self.creds = creds
        self.event_queue = event_queue
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="ViperGirlsPostScheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def _emit(self, post: Dict[str, str], status: str, msg: str) -> None:
        if self.event_queue is None:
            return
        try:
            self.event_queue.put_nowait({
                "type": "scheduled_post_completed",
                "id": post.get("id"),
                "status": status,
                "msg": msg,
                "data": post,
            })
        except Exception:
            logger.debug("Could not emit scheduled post event.", exc_info=True)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.process_due_posts()
            except Exception as exc:
                logger.warning(f"Scheduled ViperGirls post check failed: {exc}")
            self._stop_event.wait(60.0)

    def process_due_posts(self, now: Optional[datetime] = None) -> List[Dict[str, str]]:
        now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        posts = load_scheduled_posts()
        due_posts = [
            post for post in posts
            if post.get("status") == "pending"
            and (scheduled_at := _parse_scheduled_time(post.get("scheduled_time", "")))
            and scheduled_at <= now_utc
        ]
        if not due_posts:
            return []

        user = str(self.creds.get("vg_user") or "")
        pwd = str(self.creds.get("vg_pass") or "")
        if not user or not pwd:
            error = "Missing ViperGirls credentials."
            for post in due_posts:
                posts = _update_scheduled_post_status(posts, post["id"], "failed", error)
                failed_post = next(item for item in posts if item.get("id") == post["id"])
                self._emit(failed_post, "failed", error)
            save_scheduled_posts(posts)
            return due_posts

        api = ViperGirlsAPI()
        if not api.login(user, pwd):
            error = "ViperGirls login failed."
            for post in due_posts:
                posts = _update_scheduled_post_status(posts, post["id"], "failed", error)
                failed_post = next(item for item in posts if item.get("id") == post["id"])
                self._emit(failed_post, "failed", error)
            save_scheduled_posts(posts)
            return due_posts

        for post in due_posts:
            try:
                ok = api.post_reply(post["thread_id"], post["message"])
                status = "posted" if ok else "failed"
                error = "" if ok else "ViperGirls post failed."
            except Exception as exc:
                status = "failed"
                error = str(exc)
            posts = _update_scheduled_post_status(posts, post["id"], status, error)
            updated_post = next(item for item in posts if item.get("id") == post["id"])
            self._emit(updated_post, status, error or "Post successful")
            save_scheduled_posts(posts)

        return due_posts


class ViperGirlsAPI:
    def __init__(self):
        self.bridge = SidecarBridge.get()
        self.is_logged_in = False

    def login(self, username, password):
        logger.info("ViperAPI: Logging in...")
        import hashlib
        md5_pass = hashlib.md5(password.encode()).hexdigest()

        seed_spec = build_transport_spec(
            f"{VIPERGIRLS_BASE_URL}/login.php?do=login",
            method="GET",
            use_cookies=True,
        )
        seed_resp = execute_transport_request(
            seed_spec,
            service="vipergirls.to",
            timeout=30,
            bridge=self.bridge,
            rate_limits=VIPERGIRLS_RATE_LIMIT,
        )
        if not seed_resp.ok:
            logger.error(f"ViperAPI: Login seed failed: {seed_resp.message}")
            return False

        spec = build_transport_spec(
            f"{VIPERGIRLS_BASE_URL}/login.php?do=login",
            method="POST",
            use_cookies=True,
            form_fields={
                "vb_login_username": username,
                "vb_login_md5password": md5_pass,
                "vb_login_md5password_utf": md5_pass,
                "cookieuser": "1",
                "do": "login",
                "securitytoken": "guest",
            },
            headers={"Referer": f"{VIPERGIRLS_BASE_URL}/forum.php"},
        )
        resp = execute_transport_request(
            spec,
            service="vipergirls.to",
            timeout=30,
            bridge=self.bridge,
            rate_limits=VIPERGIRLS_RATE_LIMIT,
        )

        if resp.ok and _vipergirls_login_succeeded(resp.body, resp.final_url):
            self.is_logged_in = True
            logger.info("ViperAPI: Login Successful")
            return True

        logger.error(f"ViperAPI: Login Failed: {resp.message or 'unexpected page'}")
        return False

    def post_reply(self, thread_id, message):
        logger.info(f"ViperAPI: Posting to thread {thread_id}...")
        clean_thread_id = extract_thread_id(str(thread_id or "")) or ""
        if not clean_thread_id:
            logger.error("ViperAPI: Post Failed: invalid thread ID")
            return False

        reply_url = f"{VIPERGIRLS_BASE_URL}/newreply.php?do=newreply&t={clean_thread_id}"
        fetch_spec = build_transport_spec(
            reply_url,
            method="GET",
            headers={"Referer": f"{VIPERGIRLS_BASE_URL}/forum.php"},
            use_cookies=True,
        )
        fetch_resp = execute_transport_request(
            fetch_spec,
            service="vipergirls.to",
            timeout=30,
            bridge=self.bridge,
            rate_limits=VIPERGIRLS_RATE_LIMIT,
        )
        if not fetch_resp.ok:
            logger.error(f"ViperAPI: Reply form fetch failed: {fetch_resp.message}")
            return False

        try:
            post_spec = build_vipergirls_reply_spec(clean_thread_id, message, fetch_resp.body)
        except ViperPostError as exc:
            logger.error(f"ViperAPI: Post Failed: {exc}")
            return False

        resp = execute_transport_request(
            post_spec,
            service="vipergirls.to",
            timeout=60,
            bridge=self.bridge,
            rate_limits=VIPERGIRLS_RATE_LIMIT,
        )

        if resp.ok and _vipergirls_post_succeeded(resp.body, resp.final_url):
            logger.info("ViperAPI: Post Successful")
            return True

        logger.error(f"ViperAPI: Post Failed: {resp.message or 'unexpected page'}")
        return False

    def schedule_post(self, post_id, thread_id, thread_name, message, scheduled_time, cover_thumbnail=""):
        logger.info(f"ViperAPI: Scheduling post to thread {thread_id} for {scheduled_time}...")
        try:
            add_scheduled_post(
                {
                    "id": post_id,
                    "thread_id": str(thread_id),
                    "thread_name": thread_name,
                    "message": message,
                    "scheduled_time": scheduled_time,
                    "cover_thumbnail": cover_thumbnail,
                }
            )
            return True
        except ViperPostError as exc:
            logger.error(f"ViperAPI: Schedule failed: {exc}")
            return False

    def cancel_scheduled_post(self, post_id):
        logger.info(f"ViperAPI: Cancelling scheduled post {post_id}...")
        return cancel_scheduled_post(post_id)

    def list_scheduled_posts(self):
        return load_scheduled_posts()

    def close(self):
        pass


class ViperToolsWindow(ctk.CTkToplevel):
    """Manage saved ViperGirls posting targets."""

    def __init__(self, parent, creds=None, callback=None):
        super().__init__(parent)
        self.parent = parent
        self.creds = creds or {}
        self.callback = callback
        self.saved_threads = load_saved_threads()
        self.editing_name: Optional[str] = None
        self.search_var = ctk.StringVar(value="")
        self.sort_var = ctk.StringVar(value="Name")
        self.selected_targets: Dict[str, Any] = {}
        self.expanded_targets: Dict[str, bool] = {}

        self.title("ViperGirls Posting Targets")
        self.geometry("1180x700")
        self.minsize(960, 560)
        self.resizable(True, True)
        self.transient(parent)
        self.lift()
        self.focus_force()

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(1, weight=1)

        self._build_health_bar()
        self._build_target_list()
        self._build_controls()
        self.refresh_list()

    def _build_health_bar(self) -> None:
        self.health_bar = ctk.CTkFrame(self)
        self.health_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 6))
        self.health_bar.grid_columnconfigure(2, weight=1)

        self.credentials_label = ctk.CTkLabel(self.health_bar, text="")
        self.credentials_label.grid(row=0, column=0, padx=(10, 12), pady=8, sticky="w")

        self.target_count_label = ctk.CTkLabel(self.health_bar, text="")
        self.target_count_label.grid(row=0, column=1, padx=(0, 12), pady=8, sticky="w")

        self.path_label = ctk.CTkLabel(
            self.health_bar,
            text=THREADS_FILE,
            text_color="gray",
            anchor="w",
        )
        self.path_label.grid(row=0, column=2, padx=(0, 12), pady=8, sticky="ew")

        ctk.CTkButton(
            self.health_bar,
            text="Set Credentials",
            width=120,
            command=self.open_credentials,
        ).grid(row=0, column=3, padx=4, pady=8)

        self.test_login_button = ctk.CTkButton(
            self.health_bar,
            text="Test Login",
            width=95,
            command=self.test_login,
        )
        self.test_login_button.grid(row=0, column=4, padx=4, pady=8)

        ctk.CTkButton(
            self.health_bar,
            text="Open Data Folder",
            width=130,
            command=self.open_data_folder,
        ).grid(row=0, column=5, padx=(4, 10), pady=8)

        ctk.CTkButton(
            self.health_bar,
            text="History",
            width=85,
            command=self.open_history,
        ).grid(row=0, column=6, padx=(0, 10), pady=8)

    def _build_target_list(self) -> None:
        self.list_panel = ctk.CTkFrame(self, fg_color="transparent")
        self.list_panel.grid(row=1, column=0, sticky="nsew", padx=(10, 8), pady=(0, 10))
        self.list_panel.grid_columnconfigure(0, weight=1)
        self.list_panel.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(self.list_panel)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        toolbar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(toolbar, text="Search").grid(row=0, column=0, sticky="w", padx=(10, 6), pady=8)
        search_entry = ctk.CTkEntry(toolbar, textvariable=self.search_var)
        search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=8)
        self.search_var.trace_add("write", lambda *_: self.refresh_list())

        ctk.CTkLabel(toolbar, text="Sort").grid(row=0, column=2, sticky="w", padx=(0, 6), pady=8)
        self.sort_menu = ctk.CTkOptionMenu(
            toolbar,
            variable=self.sort_var,
            values=["Name", "Last Used", "Thread ID"],
            command=lambda _choice: self.refresh_list(),
            width=115,
        )
        self.sort_menu.grid(row=0, column=3, padx=(0, 8), pady=8)

        ctk.CTkButton(toolbar, text="Import", width=76, command=self.import_targets).grid(
            row=0, column=4, padx=3, pady=8
        )
        ctk.CTkButton(toolbar, text="Export All", width=92, command=self.export_all_targets).grid(
            row=0, column=5, padx=3, pady=8
        )
        ctk.CTkButton(
            toolbar,
            text="Refresh Names",
            width=115,
            command=self.refresh_target_names,
        ).grid(row=0, column=6, padx=3, pady=8)
        ctk.CTkButton(
            toolbar,
            text="Export Selected",
            width=120,
            command=self.export_selected_targets,
        ).grid(row=0, column=7, padx=3, pady=8)
        ctk.CTkButton(
            toolbar,
            text="Delete Selected",
            width=120,
            fg_color="#B23B3B",
            hover_color="#8F2D2D",
            command=self.bulk_delete_selected,
        ).grid(row=0, column=8, padx=(3, 10), pady=8)

        self.scroll = ctk.CTkScrollableFrame(self.list_panel, label_text="Saved Posting Targets")
        self.scroll.grid(row=1, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)

    def _build_controls(self) -> None:
        self.controls = ctk.CTkFrame(self, width=310)
        self.controls.grid(row=1, column=1, sticky="nsew", padx=(0, 10), pady=(0, 10))
        self.controls.grid_propagate(False)
        self.controls.grid_columnconfigure(0, weight=1)

        self.form_title_label = ctk.CTkLabel(
            self.controls,
            text="Add Posting Target",
            font=("Segoe UI", 15, "bold"),
        )
        self.form_title_label.grid(row=0, column=0, sticky="w", padx=14, pady=(14, 8))

        ctk.CTkLabel(self.controls, text="Fallback Name").grid(row=1, column=0, sticky="w", padx=14)
        self.ent_name = ctk.CTkEntry(
            self.controls,
            placeholder_text="Optional if title fetch fails",
        )
        self.ent_name.grid(row=2, column=0, sticky="ew", padx=14, pady=(2, 10))

        ctk.CTkLabel(self.controls, text="Thread URL or ID").grid(row=3, column=0, sticky="w", padx=14)
        self.ent_url = ctk.CTkEntry(
            self.controls,
            placeholder_text="URL, threads/12345, or 12345",
        )
        self.ent_url.grid(row=4, column=0, sticky="ew", padx=14, pady=(2, 10))

        ctk.CTkLabel(self.controls, text="Tags").grid(row=5, column=0, sticky="w", padx=14)
        self.ent_tags = ctk.CTkEntry(
            self.controls,
            placeholder_text="comma, separated, labels",
        )
        self.ent_tags.grid(row=6, column=0, sticky="ew", padx=14, pady=(2, 10))

        ctk.CTkLabel(self.controls, text="Notes").grid(row=7, column=0, sticky="w", padx=14)
        self.ent_notes = ctk.CTkEntry(
            self.controls,
            placeholder_text="Optional reminder or workflow note",
        )
        self.ent_notes.grid(row=8, column=0, sticky="ew", padx=14, pady=(2, 10))

        self.save_button = ctk.CTkButton(
            self.controls,
            text="Save Target",
            command=self.save_target,
        )
        self.save_button.grid(row=9, column=0, sticky="ew", padx=14, pady=(4, 6))

        self.cancel_edit_button = ctk.CTkButton(
            self.controls,
            text="Cancel Edit",
            command=self.cancel_edit,
            fg_color="gray",
            hover_color="#666666",
        )
        self.cancel_edit_button.grid(row=10, column=0, sticky="ew", padx=14, pady=(0, 6))
        self.cancel_edit_button.configure(state="disabled")

        ctk.CTkButton(
            self.controls,
            text="Refresh List",
            command=self.refresh_list,
        ).grid(row=11, column=0, sticky="ew", padx=14, pady=(12, 6))

    def _update_health(self) -> None:
        self.creds = CredentialsManager.load_all_credentials()
        has_credentials = bool(self.creds.get("vg_user") and self.creds.get("vg_pass"))
        self.credentials_label.configure(
            text=f"Credentials: {'Set' if has_credentials else 'Missing'}",
            text_color="#2FA572" if has_credentials else "#D9534F",
        )
        self.target_count_label.configure(text=f"Targets: {len(self.saved_threads)}")

    def _filtered_sorted_targets(self) -> List[Tuple[str, Dict[str, object]]]:
        query = self.search_var.get().strip().lower()
        items = []
        for name, data in self.saved_threads.items():
            haystack = " ".join(
                [
                    name,
                    str(data.get("thread_id") or ""),
                    str(data.get("url") or ""),
                    str(data.get("notes") or ""),
                    str(data.get("site_title") or ""),
                    format_tags(data.get("tags")),
                ]
            ).lower()
            if query and query not in haystack:
                continue
            items.append((name, data))

        sort_by = self.sort_var.get()
        if sort_by == "Last Used":
            return sorted(
                items,
                key=lambda item: (
                    str(item[1].get("last_used_at") or ""),
                    item[0].lower(),
                ),
                reverse=True,
            )
        if sort_by == "Thread ID":
            return sorted(
                items,
                key=lambda item: (
                    str(item[1].get("thread_id") or ""),
                    item[0].lower(),
                ),
            )
        return sorted(items, key=lambda item: item[0].lower())

    def refresh_list(self) -> None:
        for widget in self.scroll.winfo_children():
            widget.destroy()

        selected_names = set(self._selected_target_names())
        self.saved_threads = load_saved_threads()
        self.expanded_targets = {
            name: is_expanded
            for name, is_expanded in getattr(self, "expanded_targets", {}).items()
            if name in self.saved_threads
        }
        self.selected_targets = {}
        self._update_health()
        visible_targets = self._filtered_sorted_targets()

        header = ctk.CTkFrame(self.scroll, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=4, pady=(0, 4))
        header.grid_columnconfigure(0, weight=0)
        header.grid_columnconfigure(1, weight=0)
        header.grid_columnconfigure(2, weight=3)
        header.grid_columnconfigure(3, weight=1)
        header.grid_columnconfigure(4, weight=3)
        header.grid_columnconfigure(5, weight=0)
        headers = ("", "Sel", "Name / Tags", "Thread / Last Used", "Notes", "Actions")
        for column, text in enumerate(headers):
            ctk.CTkLabel(header, text=text, font=("Segoe UI", 12, "bold")).grid(
                row=0, column=column, sticky="w", padx=6
            )

        if not self.saved_threads:
            ctk.CTkLabel(
                self.scroll,
                text=(
                    "No saved posting targets yet. Add a target with a ViperGirls thread "
                    "URL or raw thread ID, or import a saved targets JSON file."
                ),
                text_color="gray",
                wraplength=760,
                justify="left",
            ).grid(row=1, column=0, sticky="w", padx=12, pady=18)
            return

        if not visible_targets:
            ctk.CTkLabel(
                self.scroll,
                text="No saved posting targets match the current search.",
                text_color="gray",
            ).grid(row=1, column=0, sticky="w", padx=12, pady=18)
            return

        for row_index, (name, data) in enumerate(visible_targets, start=1):
            self._add_target_row(row_index, name, data, selected=name in selected_names)

    def _add_target_row(
        self,
        row_index: int,
        name: str,
        data: Dict[str, object],
        selected: bool = False,
    ) -> None:
        row = ctk.CTkFrame(self.scroll)
        row.grid(row=row_index, column=0, sticky="ew", padx=4, pady=3)
        row.grid_columnconfigure(0, weight=0)
        row.grid_columnconfigure(1, weight=0)
        row.grid_columnconfigure(2, weight=3)
        row.grid_columnconfigure(3, weight=1)
        row.grid_columnconfigure(4, weight=3)
        row.grid_columnconfigure(5, weight=0)

        thread_id = str(data.get("thread_id") or "")
        url = str(data.get("url") or "")
        tags = format_tags(data.get("tags"))
        notes = str(data.get("notes") or "")
        last_used = str(data.get("last_used_at") or "Never")
        expanded = bool(getattr(self, "expanded_targets", {}).get(name))

        ctk.CTkButton(
            row,
            text="-" if expanded else "+",
            width=28,
            height=24,
            command=lambda n=name: self.toggle_target_expanded(n),
        ).grid(row=0, column=0, rowspan=3, sticky="nw", padx=(6, 0), pady=8)

        var = ctk.BooleanVar(value=selected)
        self.selected_targets[name] = var
        ctk.CTkCheckBox(row, text="", variable=var, width=24).grid(
            row=0, column=1, rowspan=3, sticky="nw", padx=(6, 0), pady=8
        )

        name_frame = ctk.CTkFrame(row, fg_color="transparent")
        name_frame.grid(row=0, column=2, sticky="nsew", padx=6, pady=(6, 6))
        name_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            name_frame,
            text=self._display_target_name(name, data),
            anchor="w",
            font=("Segoe UI", 12, "bold"),
        ).pack(fill="x", anchor="w")
        if expanded:
            self._add_target_url_link(name_frame, url)
        ctk.CTkLabel(
            name_frame,
            text=tags or "No tags",
            anchor="w",
            text_color="gray",
        ).pack(fill="x", anchor="w", pady=(2, 0))

        ctk.CTkLabel(row, text=thread_id or "Missing", anchor="w", text_color="gray").grid(
            row=0, column=3, sticky="ew", padx=6, pady=(6, 0)
        )
        ctk.CTkLabel(row, text=f"Last used: {last_used}", anchor="w", text_color="gray").grid(
            row=1, column=3, sticky="ew", padx=6, pady=(0, 6)
        )
        ctk.CTkLabel(
            row,
            text=self._shorten(notes, 72) if notes else "No notes",
            anchor="w",
            text_color="gray",
            wraplength=360,
        ).grid(row=0, column=4, rowspan=2, sticky="ew", padx=6, pady=(6, 6))

        validation_errors = validate_saved_thread_record(name, data)
        if validation_errors:
            ctk.CTkLabel(
                row,
                text="; ".join(validation_errors),
                anchor="w",
                text_color="#D9534F",
            ).grid(row=2, column=2, columnspan=3, sticky="ew", padx=6, pady=(0, 6))

        actions = ctk.CTkFrame(row, fg_color="transparent")
        actions.grid(row=0, column=5, rowspan=2, sticky="e", padx=6, pady=4)
        ctk.CTkButton(actions, text="Edit", width=52, command=lambda n=name: self.edit_thread(n)).pack(
            side="left", padx=2
        )
        ctk.CTkButton(actions, text="Open", width=55, command=lambda n=name: self.open_thread(n)).pack(
            side="left", padx=2
        )
        ctk.CTkButton(
            actions,
            text="Validate",
            width=70,
            command=lambda n=name: self.validate_thread(n),
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            actions,
            text="Delete",
            width=60,
            fg_color="#B23B3B",
            hover_color="#8F2D2D",
            command=lambda n=name: self.delete_thread(n),
        ).pack(side="left", padx=2)

    @staticmethod
    def _display_target_name(name: str, data: Optional[Dict[str, object]] = None) -> str:
        if isinstance(data, dict):
            site_title = clean_thread_title(str(data.get("site_title") or ""))
            if site_title:
                return site_title
        return str(name or "").strip() or "Untitled target"

    def _add_target_url_link(self, parent: Any, url: str) -> None:
        if not url:
            ctk.CTkLabel(
                parent,
                text="No URL saved",
                anchor="w",
                text_color="gray",
            ).pack(fill="x", anchor="w", pady=(2, 0))
            return

        link_label = ctk.CTkLabel(
            parent,
            text=url,
            anchor="w",
            text_color="#2B78D6",
            wraplength=500,
            cursor="hand2",
        )
        link_label.pack(fill="x", anchor="w", pady=(2, 0))
        link_label.bind("<Button-1>", lambda _event, link=url: self.open_url(link))

    def toggle_target_expanded(self, name: str) -> None:
        expanded_targets = getattr(self, "expanded_targets", {})
        expanded_targets[name] = not expanded_targets.get(name, False)
        self.expanded_targets = expanded_targets
        self.refresh_list()

    @staticmethod
    def open_url(url: str) -> None:
        webbrowser.open(url)

    @staticmethod
    def _shorten(value: str, max_len: int) -> str:
        if len(value) <= max_len:
            return value
        return f"{value[: max_len - 3]}..."

    def _selected_target_names(self) -> List[str]:
        selected = []
        for name, variable in self.selected_targets.items():
            try:
                if variable.get():
                    selected.append(name)
            except Exception:
                continue
        return selected

    def save_target(self) -> None:
        fallback_name = self.ent_name.get().strip()
        target = self.ent_url.get().strip()
        tags = self.ent_tags.get().strip()
        notes = self.ent_notes.get().strip()
        old_name = self.editing_name
        existing = self.saved_threads.get(old_name or fallback_name, {})

        try:
            name, record, fetched_title = build_site_named_thread_record(
                fallback_name,
                target,
                existing=existing,
                notes=notes,
                tags=tags,
                existing_names=self.saved_threads.keys(),
                exclude=old_name,
            )
        except ThreadTargetError as exc:
            messagebox.showerror("Invalid Target", str(exc))
            return

        if not fetched_title:
            logger.warning(
                f"Saved ViperGirls target '{name}' without a live site title; using fallback name."
            )

        duplicate_thread = self._find_duplicate_thread_id(str(record["thread_id"]), exclude=old_name)
        if duplicate_thread and not messagebox.askyesno(
            "Duplicate Thread ID",
            (
                f"'{duplicate_thread}' already uses thread ID {record['thread_id']}.\n\n"
                "Save this target anyway?"
            ),
        ):
            return

        updated = dict(self.saved_threads)
        if old_name and old_name != name:
            updated.pop(old_name, None)
        updated[name] = record

        try:
            save_saved_threads(updated)
        except OSError as exc:
            messagebox.showerror("Save Failed", f"Failed to save posting targets:\n{exc}")
            return

        self.saved_threads = updated
        self.cancel_edit(clear_fields=True)
        self.refresh_list()
        self._notify_changed()

    def refresh_target_names(self) -> None:
        names = self._selected_target_names() or list(self.saved_threads)
        if not names:
            messagebox.showwarning("Refresh Names", "No saved targets are available to refresh.")
            return

        updated = dict(self.saved_threads)
        renamed = 0
        failed = 0
        editing_name = self.editing_name
        expanded_targets = dict(getattr(self, "expanded_targets", {}))

        for current_name in names:
            record = updated.get(current_name)
            if not isinstance(record, dict):
                failed += 1
                continue

            target = _import_record_target(record)
            try:
                new_name, new_record, fetched_title = build_site_named_thread_record(
                    current_name,
                    target,
                    existing=record,
                    notes=record.get("notes"),
                    tags=record.get("tags"),
                    existing_names=updated.keys(),
                    exclude=current_name,
                    fetch_title=True,
                )
            except ThreadTargetError:
                failed += 1
                continue

            if not fetched_title:
                failed += 1
                continue

            if new_name != current_name:
                updated.pop(current_name, None)
                if editing_name == current_name:
                    editing_name = new_name
                if current_name in expanded_targets:
                    expanded_targets[new_name] = expanded_targets.pop(current_name)
            updated[new_name] = new_record
            renamed += 1

        if renamed:
            try:
                save_saved_threads(updated)
            except OSError as exc:
                messagebox.showerror("Refresh Names Failed", f"Failed to save refreshed targets:\n{exc}")
                return
            self.saved_threads = updated
            self.editing_name = editing_name
            self.expanded_targets = expanded_targets
            self.refresh_list()
            self._notify_changed()

        messagebox.showinfo(
            "Refresh Names",
            f"Updated {renamed} target name(s). Failed to fetch {failed} title(s).",
        )

    def _find_duplicate_thread_id(self, thread_id: str, exclude: Optional[str] = None) -> Optional[str]:
        for name, data in self.saved_threads.items():
            if name == exclude:
                continue
            if str(data.get("thread_id") or "") == thread_id:
                return name
        return None

    def edit_thread(self, name: str) -> None:
        data = self.saved_threads.get(name)
        if not data:
            return
        self.editing_name = name
        self.form_title_label.configure(text="Edit Posting Target")
        self.save_button.configure(text="Update Target")
        self.cancel_edit_button.configure(state="normal")
        self.ent_name.delete(0, "end")
        self.ent_name.insert(0, name)
        self.ent_url.delete(0, "end")
        self.ent_url.insert(0, str(data.get("url") or ""))
        self.ent_tags.delete(0, "end")
        self.ent_tags.insert(0, format_tags(data.get("tags")))
        self.ent_notes.delete(0, "end")
        self.ent_notes.insert(0, str(data.get("notes") or ""))

    def cancel_edit(self, clear_fields: bool = True) -> None:
        self.editing_name = None
        self.form_title_label.configure(text="Add Posting Target")
        self.save_button.configure(text="Save Target")
        self.cancel_edit_button.configure(state="disabled")
        if clear_fields:
            self.ent_name.delete(0, "end")
            self.ent_url.delete(0, "end")
            self.ent_tags.delete(0, "end")
            self.ent_notes.delete(0, "end")

    def open_thread(self, name: str) -> None:
        data = self.saved_threads.get(name, {})
        url = str(data.get("url") or "")
        if not url:
            messagebox.showerror("Open Target", "This target does not have a URL.")
            return
        self.open_url(url)

    def validate_thread(self, name: str) -> None:
        data = self.saved_threads.get(name, {})
        errors = validate_saved_thread_record(name, data)
        if errors:
            messagebox.showerror("Invalid Target", f"'{name}' is invalid:\n\n" + "\n".join(errors))
            return
        thread_id = str(data.get("thread_id") or extract_thread_id(str(data.get("url") or "")) or "")
        messagebox.showinfo("Target Valid", f"'{name}' resolves to thread ID {thread_id}.")

    def delete_thread(self, name: str) -> None:
        if name not in self.saved_threads:
            return
        if not messagebox.askyesno("Delete Target", f"Delete '{name}'?"):
            return

        updated = dict(self.saved_threads)
        updated.pop(name, None)
        try:
            save_saved_threads(updated)
        except OSError as exc:
            messagebox.showerror("Delete Failed", f"Failed to save posting targets:\n{exc}")
            return

        self.saved_threads = updated
        if self.editing_name == name:
            self.cancel_edit(clear_fields=True)
        self.refresh_list()
        self._notify_changed()

    def bulk_delete_selected(self) -> None:
        names = self._selected_target_names()
        if not names:
            messagebox.showwarning("Delete Selected", "Select one or more targets to delete.")
            return
        if not messagebox.askyesno("Delete Selected", f"Delete {len(names)} selected target(s)?"):
            return

        updated = dict(self.saved_threads)
        for name in names:
            updated.pop(name, None)
        try:
            save_saved_threads(updated)
        except OSError as exc:
            messagebox.showerror("Delete Failed", f"Failed to save posting targets:\n{exc}")
            return

        self.saved_threads = updated
        if self.editing_name in names:
            self.cancel_edit(clear_fields=True)
        self.refresh_list()
        self._notify_changed()

    def import_targets(self) -> None:
        filepath = filedialog.askopenfilename(
            title="Import ViperGirls Targets",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not filepath:
            return

        overwrite = True
        duplicates = self._duplicate_names_in_import(filepath)
        if duplicates:
            overwrite = messagebox.askyesno(
                "Import Targets",
                (
                    f"{len(duplicates)} imported target name(s) already exist.\n\n"
                    "Overwrite matching saved targets?"
                ),
            )

        try:
            merged, imported, skipped = import_saved_threads_file(
                filepath,
                existing=self.saved_threads,
                overwrite=overwrite,
            )
            save_saved_threads(merged)
        except Exception as exc:
            messagebox.showerror("Import Failed", f"Could not import targets:\n{exc}")
            return

        self.saved_threads = merged
        self.refresh_list()
        self._notify_changed()
        messagebox.showinfo(
            "Import Complete",
            f"Imported {imported} target(s). Skipped {skipped} target(s).",
        )

    def _duplicate_names_in_import(self, filepath: str) -> List[str]:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            raw_targets = _targets_from_import_payload(raw_data)
        except Exception:
            return []
        return [str(name).strip() for name in raw_targets if str(name).strip() in self.saved_threads]

    def export_all_targets(self) -> None:
        self._export_targets(sorted(self.saved_threads))

    def export_selected_targets(self) -> None:
        names = self._selected_target_names()
        if not names:
            messagebox.showwarning("Export Selected", "Select one or more targets to export.")
            return
        self._export_targets(names)

    def _export_targets(self, names: List[str]) -> None:
        if not names:
            messagebox.showwarning("Export Targets", "No saved targets are available to export.")
            return
        filepath = filedialog.asksaveasfilename(
            title="Export ViperGirls Targets",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not filepath:
            return
        try:
            exported = export_saved_threads_file(filepath, self.saved_threads, names=names)
        except OSError as exc:
            messagebox.showerror("Export Failed", f"Could not export targets:\n{exc}")
            return
        messagebox.showinfo("Export Complete", f"Exported {exported} target(s).")

    def open_credentials(self) -> None:
        def _after_save():
            if hasattr(self.parent, "_load_credentials"):
                self.parent._load_credentials()
            self._update_health()

        CredentialsManager.create_credentials_dialog(parent=self, on_save_callback=_after_save)

    def test_login(self) -> None:
        creds = CredentialsManager.load_all_credentials()
        user = creds.get("vg_user", "")
        pwd = creds.get("vg_pass", "")
        if not user or not pwd:
            messagebox.showerror("Missing Credentials", "Set ViperGirls credentials before testing login.")
            self._update_health()
            return

        self.test_login_button.configure(state="disabled", text="Testing...")

        def _task():
            ok = ViperGirlsAPI().login(user, pwd)

            def _finish():
                self.test_login_button.configure(state="normal", text="Test Login")
                if ok:
                    messagebox.showinfo("Login Successful", "ViperGirls login succeeded.")
                else:
                    messagebox.showerror("Login Failed", "ViperGirls login failed.")

            try:
                self.after(0, _finish)
            except Exception:
                logger.debug("ViperGirls target window closed before login test completed.")

        threading.Thread(target=_task, daemon=True).start()

    def open_data_folder(self) -> None:
        os.makedirs(_USER_DATA_DIR, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(_USER_DATA_DIR)
            else:
                webbrowser.open(_USER_DATA_DIR)
        except Exception as exc:
            messagebox.showerror("Open Folder Failed", f"Could not open:\n{_USER_DATA_DIR}\n\n{exc}")

    def open_history(self) -> None:
        PostingHistoryWindow(self)

    def _notify_changed(self) -> None:
        if self.callback:
            self.callback()


class PostingHistoryWindow(ctk.CTkToplevel):
    """View and manage ViperGirls posting history."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.history: List[Dict[str, str]] = []

        self.title("ViperGirls Posting History")
        self.geometry("1040x640")
        self.minsize(880, 480)
        self.resizable(True, True)
        self.transient(parent)
        self.lift()
        self.focus_force()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_history_list()
        self.refresh_history()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self)
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="Posting History",
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=10, pady=8)

        self.history_count_label = ctk.CTkLabel(header, text="", text_color="gray")
        self.history_count_label.grid(row=0, column=1, sticky="w", padx=(4, 10), pady=8)

        ctk.CTkButton(
            header,
            text="Refresh",
            width=90,
            command=self.refresh_history,
        ).grid(row=0, column=2, padx=4, pady=8)
        ctk.CTkButton(
            header,
            text="Clear History",
            width=120,
            fg_color="#B23B3B",
            hover_color="#8F2D2D",
            command=self.clear_history,
        ).grid(row=0, column=3, padx=(4, 10), pady=8)

    def _build_history_list(self) -> None:
        self.scroll = ctk.CTkScrollableFrame(self, label_text="Recent Posting Attempts")
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.scroll.grid_columnconfigure(0, weight=1)

    def refresh_history(self) -> None:
        for widget in self.scroll.winfo_children():
            widget.destroy()

        self.history = list(reversed(load_posting_history()))
        self.history_count_label.configure(
            text=f"{len(self.history)} saved attempt(s) - {POSTING_HISTORY_FILE}"
        )

        if not self.history:
            ctk.CTkLabel(
                self.scroll,
                text="No ViperGirls posting history yet.",
                text_color="gray",
            ).grid(row=0, column=0, sticky="w", padx=12, pady=18)
            return

        for row_index, entry in enumerate(self.history):
            self._add_history_row(row_index, entry)

    def _add_history_row(self, row_index: int, entry: Dict[str, str]) -> None:
        row = ctk.CTkFrame(self.scroll)
        row.grid(row=row_index, column=0, sticky="ew", padx=4, pady=3)
        row.grid_columnconfigure(1, weight=1)

        status = str(entry.get("status") or "unknown").lower()
        status_color = "#2FA572" if status == "success" else "#D9534F"
        ctk.CTkLabel(
            row,
            text=status.upper(),
            text_color=status_color,
            width=70,
            anchor="w",
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, rowspan=2, sticky="nw", padx=8, pady=8)

        title = (
            f"{entry.get('batch_name', 'Batch')} -> "
            f"{entry.get('target_name', 'Unknown target')} "
            f"(thread {entry.get('thread_id') or 'unknown'})"
        )
        ctk.CTkLabel(row, text=title, anchor="w", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=1, sticky="ew", padx=6, pady=(7, 1)
        )

        detail = entry.get("timestamp", "")
        error = str(entry.get("error") or "")
        if error:
            detail = f"{detail} - {error}"
        ctk.CTkLabel(
            row,
            text=detail,
            anchor="w",
            text_color="gray",
        ).grid(row=1, column=1, sticky="ew", padx=6, pady=(0, 7))

        actions = ctk.CTkFrame(row, fg_color="transparent")
        actions.grid(row=0, column=2, rowspan=2, sticky="e", padx=8, pady=6)
        ctk.CTkButton(
            actions,
            text="Copy Post",
            width=82,
            command=lambda e=entry: self.copy_post_text(e),
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            actions,
            text="Copy Error",
            width=84,
            command=lambda e=entry: self.copy_error(e),
            state="normal" if error else "disabled",
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            actions,
            text="Open",
            width=58,
            command=lambda e=entry: self.open_target(e),
            state="normal" if entry.get("target_url") else "disabled",
        ).pack(side="left", padx=2)

    def copy_post_text(self, entry: Dict[str, str]) -> None:
        self._copy_text(entry.get("post_text", ""), "Post text copied.")

    def copy_error(self, entry: Dict[str, str]) -> None:
        self._copy_text(entry.get("error", ""), "Error copied.")

    def _copy_text(self, text: str, success_message: str) -> None:
        if not text:
            messagebox.showwarning("Copy", "No text is available to copy.")
            return
        try:
            pyperclip.copy(text)
            messagebox.showinfo("Copy", success_message)
        except (OSError, pyperclip.PyperclipException) as exc:
            messagebox.showerror("Copy Failed", f"Could not copy text:\n{exc}")

    def open_target(self, entry: Dict[str, str]) -> None:
        url = str(entry.get("target_url") or "")
        if not url:
            messagebox.showerror("Open Target", "No target URL is available.")
            return
        webbrowser.open(url)

    def clear_history(self) -> None:
        if not self.history:
            return
        if not messagebox.askyesno("Clear Posting History", "Clear all posting history?"):
            return
        try:
            clear_posting_history()
        except OSError as exc:
            messagebox.showerror("Clear Failed", f"Could not clear posting history:\n{exc}")
            return
        self.refresh_history()
