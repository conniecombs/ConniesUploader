# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Persistent cache for image-host gallery records."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from loguru import logger

from . import config
from .gallery_service import GalleryRecord, normalize_gallery_record

_USER_DATA_DIR = config.USER_DATA_DIR
DEFAULT_GALLERY_CACHE_FILE = os.path.join(_USER_DATA_DIR, "gallery_cache.json")
# Keep gallery cache entries until the user explicitly removes/deletes them.
# Hosts like IMX can have far more than 500 galleries, and trimming breaks
# complete local search/sort after a full sync.
GALLERY_CACHE_LIMIT_PER_SERVICE = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class GalleryCache:
    """Load, save, and update cached gallery lists."""

    def __init__(self, filepath: str = DEFAULT_GALLERY_CACHE_FILE):
        self.filepath = filepath

    def load(self) -> Dict[str, Any]:
        if not os.path.exists(self.filepath):
            return self._empty_payload()

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except Exception as exc:
            self._backup_corrupt_cache(exc)
            return self._empty_payload()

        return self._normalize_payload(raw_data)

    def save(self, payload: Dict[str, Any]) -> None:
        directory = os.path.dirname(self.filepath)
        if directory:
            os.makedirs(directory, exist_ok=True)
        normalized = self._normalize_payload(payload)
        tmp_path = f"{self.filepath}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(normalized, f, indent=4, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, self.filepath)

    def records_for_service(self, service: str) -> List[GalleryRecord]:
        service = config.normalize_service_id(service)
        payload = self.load()
        records = []
        service_records = payload.get("services", {}).get(service, {})
        if not isinstance(service_records, dict):
            return []

        for raw_record in service_records.values():
            record = self._record_from_cache_item(service, raw_record)
            if record:
                records.append(record)
        return sorted(records, key=self._cached_record_sort_key)

    def upsert_records(self, service: str, records: Iterable[GalleryRecord]) -> None:
        service = config.normalize_service_id(service)
        payload = self.load()
        service_records = self._service_records(payload, service)
        cached_at = _now_iso()
        changed = False

        for record in records:
            if not record.id:
                continue
            existing = service_records.get(record.id, {})
            service_records[record.id] = self._cache_item_from_record(
                record,
                existing=existing if isinstance(existing, dict) else {},
                cached_at=cached_at,
            )
            changed = True

        if changed:
            payload["services"][service] = self._trim_service_records(service_records)
            self.save(payload)

    def upsert_record(self, record: GalleryRecord) -> None:
        self.upsert_records(record.service, [record])

    def remove_record(self, service: str, gallery_id: str) -> bool:
        service = config.normalize_service_id(service)
        gallery_id = str(gallery_id or "").strip()
        if not service or not gallery_id:
            return False

        payload = self.load()
        service_records = payload.get("services", {}).get(service)
        if not isinstance(service_records, dict) or gallery_id not in service_records:
            return False

        del service_records[gallery_id]
        if service_records:
            payload["services"][service] = service_records
        else:
            payload.get("services", {}).pop(service, None)
        self.save(payload)
        return True

    def mark_used(self, record: GalleryRecord, timestamp: Optional[str] = None) -> str:
        payload = self.load()
        service_records = self._service_records(payload, record.service)
        existing = service_records.get(record.id, {})
        item = self._cache_item_from_record(
            record,
            existing=existing if isinstance(existing, dict) else {},
        )
        used_at = timestamp or _now_iso()
        item["last_used_at"] = used_at
        item["updated_at"] = used_at
        service_records[record.id] = item
        payload["services"][record.service] = self._trim_service_records(service_records)
        self.save(payload)
        return used_at

    def toggle_pinned(self, record: GalleryRecord) -> bool:
        payload = self.load()
        service_records = self._service_records(payload, record.service)
        existing = service_records.get(record.id, {})
        item = self._cache_item_from_record(
            record,
            existing=existing if isinstance(existing, dict) else {},
        )
        item["pinned"] = not bool(item.get("pinned"))
        item["updated_at"] = _now_iso()
        service_records[record.id] = item
        payload["services"][record.service] = self._trim_service_records(service_records)
        self.save(payload)
        return bool(item["pinned"])

    def _empty_payload(self) -> Dict[str, Any]:
        return {"version": 1, "services": {}}

    def _normalize_payload(self, raw_data: Any) -> Dict[str, Any]:
        if not isinstance(raw_data, dict):
            return self._empty_payload()

        services = raw_data.get("services", {})
        if not isinstance(services, dict):
            return self._empty_payload()

        normalized = self._empty_payload()
        for service, service_records in services.items():
            service_id = config.normalize_service_id(service)
            if not service_id or not isinstance(service_records, dict):
                continue

            normalized_records = normalized["services"].get(service_id, {}).copy()
            for gallery_id, raw_record in service_records.items():
                item = self._normalize_cache_item(service_id, gallery_id, raw_record)
                if item:
                    normalized_records[item["id"]] = item
            if normalized_records:
                normalized["services"][service_id] = self._trim_service_records(
                    normalized_records
                )

        return normalized

    def _normalize_cache_item(
        self, service: str, gallery_id: Any, raw_record: Any
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(raw_record, dict):
            return None

        raw = raw_record.get("raw") if isinstance(raw_record.get("raw"), dict) else {}
        candidate = {
            **raw,
            "id": raw_record.get("id") or gallery_id,
            "name": raw_record.get("name"),
            "url": raw_record.get("url"),
            "upload_hash": raw_record.get("upload_hash"),
        }
        record = normalize_gallery_record(service, candidate)
        if not record:
            return None

        now = _now_iso()
        return {
            "service": record.service,
            "id": record.id,
            "name": record.name,
            "url": record.url,
            "upload_hash": record.upload_hash,
            "raw": dict(raw),
            "cached_at": str(raw_record.get("cached_at") or now),
            "updated_at": str(raw_record.get("updated_at") or now),
            "last_used_at": raw_record.get("last_used_at"),
            "pinned": bool(raw_record.get("pinned")),
        }

    def _cache_item_from_record(
        self,
        record: GalleryRecord,
        existing: Optional[Dict[str, Any]] = None,
        cached_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        existing = existing or {}
        now = _now_iso()
        service = config.normalize_service_id(record.service)
        return {
            "service": service,
            "id": record.id,
            "name": record.name,
            "url": config.normalize_pixhost_url(record.url),
            "upload_hash": record.upload_hash,
            "raw": {
                key: value
                for key, value in dict(record.raw or {}).items()
                if not str(key).startswith("_")
                and key
                not in {
                    "cached_at",
                    "updated_at",
                    "last_used",
                    "last_used_at",
                    "last_used_ts",
                    "pinned",
                }
            },
            "cached_at": cached_at or existing.get("cached_at") or now,
            "updated_at": now,
            "last_used_at": existing.get("last_used_at"),
            "pinned": bool(existing.get("pinned")),
        }

    def _record_from_cache_item(
        self, service: str, raw_record: Dict[str, Any]
    ) -> Optional[GalleryRecord]:
        service = config.normalize_service_id(service)
        item = self._normalize_cache_item(service, raw_record.get("id"), raw_record)
        if not item:
            return None

        raw = dict(item.get("raw") or {})
        raw.update(
            {
                "_cached": True,
                "cached_at": item.get("cached_at"),
                "updated_at": item.get("updated_at"),
                "last_used_at": item.get("last_used_at"),
                "pinned": item.get("pinned"),
            }
        )
        return GalleryRecord(
            service=service,
            id=item["id"],
            name=item["name"],
            url=item["url"],
            upload_hash=item["upload_hash"],
            raw=raw,
        )

    def _service_records(self, payload: Dict[str, Any], service: str) -> Dict[str, Any]:
        service = config.normalize_service_id(service)
        payload.setdefault("services", {})
        service_records = payload["services"].setdefault(service, {})
        if not isinstance(service_records, dict):
            service_records = {}
            payload["services"][service] = service_records
        return service_records

    def _trim_service_records(self, records: Dict[str, Any]) -> Dict[str, Any]:
        items = list(records.items())
        pinned = [(key, value) for key, value in items if bool(value.get("pinned"))]
        regular = [(key, value) for key, value in items if not bool(value.get("pinned"))]

        regular = sorted(
            regular,
            key=lambda item: str(
                item[1].get("last_used_at")
                or item[1].get("updated_at")
                or item[1].get("cached_at")
                or ""
            ),
            reverse=True,
        )
        if GALLERY_CACHE_LIMIT_PER_SERVICE is None:
            trimmed = pinned + regular
        else:
            room = max(0, GALLERY_CACHE_LIMIT_PER_SERVICE - len(pinned))
            trimmed = pinned + regular[:room]
        return dict(trimmed)

    def _cached_record_sort_key(self, record: GalleryRecord) -> tuple:
        pinned = bool(record.raw.get("pinned"))
        last_used = str(record.raw.get("last_used_at") or "")
        updated = str(record.raw.get("updated_at") or record.raw.get("cached_at") or "")
        return (not pinned, -(1 if last_used else 0), last_used or updated, record.name.lower())

    def _backup_corrupt_cache(self, exc: Exception) -> None:
        if not os.path.exists(self.filepath):
            return

        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = f"{self.filepath}.corrupt-{stamp}.bak"
        try:
            shutil.copy2(self.filepath, backup_path)
            logger.warning(f"Backed up unreadable gallery cache to {backup_path}: {exc}")
        except OSError as backup_exc:
            logger.error(f"Failed to back up unreadable gallery cache: {backup_exc}")
