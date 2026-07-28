# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Gallery listing/creation service layer used by the Gallery Manager UI."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from loguru import logger

from modules import config
from modules.transport import build_transport_spec, execute_transport_request


class GalleryStatus:
    SUCCESS = "success"
    EMPTY = "empty"
    MISSING_CREDENTIALS = "missing_credentials"
    LOGIN_FAILED = "login_failed"
    UNSUPPORTED = "unsupported"
    PARSE_FAILED = "parse_failed"
    ERROR = "error"


@dataclass
class GalleryRecord:
    service: str
    id: str
    name: str
    url: str = ""
    upload_hash: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GalleryResult:
    status: str
    message: str
    service: str
    records: List[GalleryRecord] = field(default_factory=list)
    record: Optional[GalleryRecord] = None
    page: int = 1
    raw: Any = None
    cached: bool = False

    @property
    def ok(self) -> bool:
        return self.status == GalleryStatus.SUCCESS


SERVICE_LABELS = {
    "imx.to": "IMX.to",
    config.PIXHOST_SERVICE_ID: "Pixhost.cc",
    "vipr.im": "Vipr.im",
    "imagebam.com": "ImageBam",
}

LIST_SUPPORTED = {"imx.to", "vipr.im", "imagebam.com"}
CREATE_SUPPORTED = {"imx.to", config.PIXHOST_SERVICE_ID, "vipr.im"}
DELETE_SUPPORTED = {"imx.to", "vipr.im"}
IMX_GALLERY_PAGE_SIZE = 100
GALLERY_SYNC_MAX_PAGES = 250


def gallery_url_for_service(service: str, gallery_id: str) -> str:
    service = config.normalize_service_id(service)
    if not gallery_id:
        return ""
    if service == "imx.to":
        return f"https://imx.to/g/{gallery_id}"
    if service == config.PIXHOST_SERVICE_ID:
        return f"{config.PIXHOST_BASE_URL}/gallery/{gallery_id}"
    if service == "vipr.im":
        return ""
    if service == "imagebam.com" and gallery_id and not gallery_id.isdigit():
        return f"https://www.imagebam.com/view/{gallery_id}"
    return ""


def normalize_gallery_record(service: str, raw: Mapping[str, Any]) -> Optional[GalleryRecord]:
    service = config.normalize_service_id(service)
    gallery_id = str(
        raw.get("id")
        or raw.get("gallery_id")
        or raw.get("gallery_hash")
        or raw.get("hash")
        or ""
    ).strip()
    if not gallery_id:
        return None

    name = str(raw.get("name") or raw.get("gallery_name") or gallery_id).strip()
    url = str(raw.get("url") or raw.get("gallery_url") or "").strip()
    if service == config.PIXHOST_SERVICE_ID:
        url = config.normalize_pixhost_url(url)
    upload_hash = str(raw.get("upload_hash") or raw.get("gallery_upload_hash") or "").strip()
    if not url:
        url = gallery_url_for_service(service, gallery_id)

    return GalleryRecord(
        service=service,
        id=gallery_id,
        name=name or gallery_id,
        url=url,
        upload_hash=upload_hash,
        raw=dict(raw),
    )


def parse_pixhost_gallery_import(value: str, name: str = "") -> Optional[GalleryRecord]:
    """Build a Pixhost gallery record from a public gallery URL or hash."""
    raw_value = str(value or "").strip()
    if not raw_value:
        return None

    gallery_id = ""
    match = re.search(r"(?:^|/)gallery/([A-Za-z0-9]+)(?:[/?#]|$)", raw_value)
    if match:
        gallery_id = match.group(1)
    elif raw_value.isalnum():
        gallery_id = raw_value

    if not gallery_id:
        parsed = urlparse(raw_value if "://" in raw_value else f"https://{raw_value}")
        match = re.search(r"(?:^|/)gallery/([A-Za-z0-9]+)(?:[/?#]|$)", parsed.path)
        if match:
            gallery_id = match.group(1)

    gallery_id = gallery_id.strip()
    if not gallery_id or not gallery_id.isalnum():
        return None

    display_name = str(name or "").strip() or gallery_id
    return normalize_gallery_record(
        config.PIXHOST_SERVICE_ID,
        {
            "gallery_hash": gallery_id,
            "gallery_name": display_name,
            "gallery_url": gallery_url_for_service(config.PIXHOST_SERVICE_ID, gallery_id),
            "source": "imported",
        },
    )


def parse_imx_gallery_html(html: str) -> Tuple[List[Dict[str, Any]], int]:
    """Parse IMX gallery links from an account galleries page.

    Returns a tuple of (raw gallery records, candidate link count). Candidate
    count lets callers distinguish "empty page" from "page shape changed".
    """
    soup = BeautifulSoup(html or "", "html.parser")
    records: List[Dict[str, Any]] = []
    seen = set()
    candidates = 0

    for link in soup.find_all("a", href=True):
        href = str(link.get("href") or "")
        if "/g/" not in href:
            continue
        candidates += 1

        gallery_id = _extract_imx_gallery_id(href)
        if not gallery_id:
            continue

        if gallery_id in seen:
            continue

        name = link.get_text(" ", strip=True)
        records.append(
            {
                "id": gallery_id,
                "name": name or gallery_id,
                "url": gallery_url_for_service("imx.to", gallery_id),
            }
        )
        seen.add(gallery_id)

    return records, candidates


def _extract_imx_gallery_id(href: str) -> str:
    parsed = urlparse(href)
    path = parsed.path or href
    marker = "/g/"
    if marker not in path:
        return ""
    tail = path.split(marker, 1)[1]
    gallery_id = tail.split("/", 1)[0].split("?", 1)[0].strip()
    return gallery_id if gallery_id.replace("_", "").isalnum() else ""


def parse_vipr_gallery_html(html: str) -> List[Dict[str, Any]]:
    """Parse Vipr File Manager folder rows into gallery records.

    Vipr models galleries as account folders. The File Manager exposes a
    private folder link (``?op=my_files;fld_id=123``) and, next to it, the
    public gallery URL (``/p/<user>/<id>/<name>``).
    """
    soup = BeautifulSoup(html or "", "html.parser")
    records_by_id: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []

    for link in soup.find_all("a", href=True):
        href = str(link.get("href") or "")
        folder_id = _extract_vipr_folder_id(href)
        if folder_id:
            name = link.get_text(" ", strip=True)
            if folder_id not in records_by_id:
                records_by_id[folder_id] = {"id": folder_id, "name": name or folder_id}
                order.append(folder_id)
            elif name:
                records_by_id[folder_id]["name"] = name
            continue

        public_id, username, url_name = _extract_vipr_public_gallery(href)
        if not public_id:
            continue

        record = records_by_id.setdefault(
            public_id, {"id": public_id, "name": url_name or public_id}
        )
        if public_id not in order:
            order.append(public_id)
        record["url"] = urljoin("https://vipr.im/", href)
        if username:
            record["username"] = username
        if url_name and record.get("name") == public_id:
            record["name"] = url_name

    return [records_by_id[gallery_id] for gallery_id in order if gallery_id != "0"]


def _extract_vipr_folder_id(href: str) -> str:
    if "op=my_files" not in href or "del_folder=" in href:
        return ""
    match = re.search(r"[?;&]fld_id=(\d+)", href)
    if not match:
        return ""
    folder_id = match.group(1).strip()
    return "" if folder_id == "0" else folder_id


def _extract_vipr_public_gallery(href: str) -> Tuple[str, str, str]:
    match = re.search(r"(?:^|/)p/([^/?#]+)/(\d+)(?:/([^?#]+))?", href)
    if not match:
        return "", "", ""
    username = unquote(match.group(1).strip())
    gallery_id = match.group(2).strip()
    name = unquote((match.group(3) or "").strip())
    return gallery_id, username, name


def parse_imagebam_gallery_options(html: str) -> List[Dict[str, Any]]:
    """Parse ImageBam upload gallery options into upload-token records.

    ImageBam exposes numeric gallery tokens in the upload form. Public gallery
    pages use separate short IDs, so the numeric token is the correct value for
    assigning uploads to an existing gallery.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    select = soup.select_one("[data-uploader-gallery-option-value-select]")
    if select is None:
        select = soup.select_one("select[name='gallery']")
    if select is None:
        return []

    records: List[Dict[str, Any]] = []
    seen = set()
    for option in select.find_all("option"):
        gallery_id = str(option.get("value") or "").strip()
        if not gallery_id or gallery_id in {"default", "-1"} or gallery_id in seen:
            continue
        name = option.get_text(" ", strip=True)
        if not name:
            continue
        records.append(
            {
                "id": gallery_id,
                "name": name,
            }
        )
        seen.add(gallery_id)

    return records


class GalleryService:
    """Normalize gallery operations across sidecar-backed and direct flows."""

    def __init__(self, bridge: Any, creds: Mapping[str, Any]):
        self.bridge = bridge
        self.creds = creds
        self._imx_manual_cookies: Dict[str, str] = {}

    def set_imx_php_session(self, session_id: str) -> None:
        session_id = session_id.strip()
        self._imx_manual_cookies = (
            {"PHPSESSID": session_id, "continue": "1"} if session_id else {}
        )

    def list_galleries(self, service: str, page: int = 1) -> GalleryResult:
        service = config.normalize_service_id(service)
        if service not in SERVICE_LABELS:
            return self._result(
                GalleryStatus.UNSUPPORTED,
                f"{service or 'Selected service'} is not supported by Gallery Manager.",
                service,
                page=page,
            )
        if service not in LIST_SUPPORTED:
            return self._result(
                GalleryStatus.UNSUPPORTED,
                f"{SERVICE_LABELS[service]} gallery listing is not supported yet.",
                service,
                page=page,
            )

        missing = self._missing_credentials(service)
        if missing:
            return self._result(
                GalleryStatus.MISSING_CREDENTIALS,
                f"{SERVICE_LABELS[service]} needs {missing} before galleries can be listed.",
                service,
                page=page,
            )

        if service == "imx.to":
            return self._list_imx_galleries(page)
        if service == "imagebam.com":
            return self._list_imagebam_galleries(page)

        return self._list_sidecar_galleries(service, page)

    def sync_all_galleries(
        self,
        service: str,
        max_pages: int = GALLERY_SYNC_MAX_PAGES,
        progress_callback: Optional[Any] = None,
    ) -> GalleryResult:
        service = config.normalize_service_id(service)
        if service != "imx.to":
            return self._result(
                GalleryStatus.UNSUPPORTED,
                f"{SERVICE_LABELS.get(service, service or 'Selected service')} full sync is not supported.",
                service,
            )
        return self._sync_all_imx_galleries(max_pages, progress_callback)

    def create_gallery(self, service: str, name: str) -> GalleryResult:
        service = config.normalize_service_id(service)
        name = name.strip()
        if not name:
            return self._result(GalleryStatus.ERROR, "Enter a gallery name.", service)
        if service not in SERVICE_LABELS or service not in CREATE_SUPPORTED:
            return self._result(
                GalleryStatus.UNSUPPORTED,
                f"{service or 'Selected service'} does not support gallery creation.",
                service,
            )

        missing = self._missing_credentials(service)
        if missing:
            return self._result(
                GalleryStatus.MISSING_CREDENTIALS,
                f"{SERVICE_LABELS[service]} needs {missing} before a gallery can be created.",
                service,
            )

        if service == "imx.to":
            return self._create_imx_gallery(name)

        return self._create_sidecar_gallery(service, name)

    def delete_gallery(self, service: str, record_or_id: Any) -> GalleryResult:
        service = config.normalize_service_id(service)
        gallery_id = self._gallery_id_from_record_or_id(record_or_id)
        gallery_name = self._gallery_name_from_record_or_id(record_or_id, gallery_id)
        if not gallery_id:
            return self._result(GalleryStatus.ERROR, "Choose a gallery to delete.", service)
        if service not in SERVICE_LABELS or service not in DELETE_SUPPORTED:
            return self._result(
                GalleryStatus.UNSUPPORTED,
                f"{service or 'Selected service'} does not support gallery deletion.",
                service,
            )

        missing = self._missing_credentials(service)
        if missing:
            return self._result(
                GalleryStatus.MISSING_CREDENTIALS,
                f"{SERVICE_LABELS[service]} needs {missing} before a gallery can be deleted.",
                service,
            )

        if service == "imx.to":
            return self._delete_imx_gallery(gallery_id, gallery_name)
        if service == "vipr.im":
            return self._delete_vipr_gallery(gallery_id, gallery_name)

        return self._result(
            GalleryStatus.UNSUPPORTED,
            f"{SERVICE_LABELS.get(service, service)} gallery deletion is not supported yet.",
            service,
        )

    @staticmethod
    def _gallery_id_from_record_or_id(record_or_id: Any) -> str:
        if isinstance(record_or_id, GalleryRecord):
            return str(record_or_id.id or "").strip()
        if isinstance(record_or_id, Mapping):
            return str(record_or_id.get("id") or record_or_id.get("gallery_id") or "").strip()
        return str(record_or_id or "").strip()

    @staticmethod
    def _gallery_name_from_record_or_id(record_or_id: Any, fallback: str) -> str:
        if isinstance(record_or_id, GalleryRecord):
            return str(record_or_id.name or fallback).strip()
        if isinstance(record_or_id, Mapping):
            return str(record_or_id.get("name") or record_or_id.get("gallery_name") or fallback).strip()
        return fallback

    def _missing_credentials(self, service: str) -> str:
        if service == "imx.to" and not self._imx_manual_cookies:
            missing = []
            if not str(self.creds.get("imx_user", "") or "").strip():
                missing.append("IMX username")
            if not str(self.creds.get("imx_pass", "") or "").strip():
                missing.append("IMX password")
            return " and ".join(missing)

        if service == "vipr.im":
            missing = []
            if not str(self.creds.get("vipr_user", "") or "").strip():
                missing.append("Vipr username")
            if not str(self.creds.get("vipr_pass", "") or "").strip():
                missing.append("Vipr password")
            return " and ".join(missing)

        if service == "imagebam.com":
            missing = []
            if not str(self.creds.get("imagebam_user", "") or "").strip():
                missing.append("ImageBam username")
            if not str(self.creds.get("imagebam_pass", "") or "").strip():
                missing.append("ImageBam password")
            return " and ".join(missing)

        return ""

    def _list_sidecar_galleries(self, service: str, page: int) -> GalleryResult:
        try:
            if service == "vipr.im":
                if not self._login_vipr():
                    return self._result(
                        GalleryStatus.LOGIN_FAILED,
                        "Vipr.im login failed. Check the saved username and password.",
                        service,
                        page=page,
                    )
                response = self._transport_request(
                    service,
                    "https://vipr.im/?op=my_files",
                    timeout=20,
                )
                if not response.ok:
                    return self._failure_from_response(service, response.raw, page=page)
                raw_records = parse_vipr_gallery_html(response.body)
                return self._records_from_raw(
                    service,
                    raw_records,
                    page=page,
                    raw=response.raw,
                )
            else:
                response = self._transport_request(
                    service,
                    f"https://api.{service}/galleries",
                    headers={"Accept": "application/json"},
                    timeout=20,
                )
                if not response.ok:
                    return self._failure_from_response(service, response.raw, page=page)
                try:
                    raw_records = response.json()
                except json.JSONDecodeError as exc:
                    return self._result(
                        GalleryStatus.PARSE_FAILED,
                        f"Gallery list response was not valid JSON: {exc}",
                        service,
                        page=page,
                        raw=response.raw,
                    )
                resp = {**response.raw, "data": raw_records}
        except Exception as exc:
            logger.error(f"Failed to list galleries for {service}: {exc}")
            return self._result(GalleryStatus.ERROR, str(exc), service, page=page)

        return self._records_from_sidecar_response(service, resp, page=page)

    def _list_imagebam_galleries(self, page: int) -> GalleryResult:
        try:
            if not self._login_imagebam():
                return self._result(
                    GalleryStatus.LOGIN_FAILED,
                    "ImageBam login failed. Check the saved username and password.",
                    "imagebam.com",
                    page=page,
                )
            response = self._transport_request(
                "imagebam.com",
                "https://www.imagebam.com/",
                timeout=30,
            )
        except Exception as exc:
            logger.error(f"Failed to list ImageBam galleries: {exc}")
            return self._result(GalleryStatus.ERROR, str(exc), "imagebam.com", page=page)

        resp = {**response.raw, "data": {"response_body": response.body}}
        return self._normalize_imagebam_gallery_response(resp, page)

    def _normalize_imagebam_gallery_response(self, resp: Any, page: int) -> GalleryResult:
        if not isinstance(resp, dict):
            return self._result(
                GalleryStatus.PARSE_FAILED,
                "Gallery list returned an unreadable response.",
                "imagebam.com",
                page=page,
                raw=resp,
            )
        if resp.get("type") == "error" or resp.get("status") == "failed":
            return self._failure_from_response("imagebam.com", resp, page=page)

        data = resp.get("data")
        body = str(data.get("response_body", "") or "") if isinstance(data, dict) else ""
        if not body:
            return self._result(
                GalleryStatus.PARSE_FAILED,
                "ImageBam gallery page did not return the uploader gallery list.",
                "imagebam.com",
                page=page,
                raw=resp,
            )

        raw_records = parse_imagebam_gallery_options(body)
        if not raw_records:
            return self._result(
                GalleryStatus.EMPTY,
                "No galleries found for ImageBam.",
                "imagebam.com",
                page=page,
                raw=resp,
            )
        return self._records_from_raw("imagebam.com", raw_records, page=page, raw=resp)

    def _normalize_vipr_gallery_response(self, resp: Any) -> Any:
        if not isinstance(resp, dict):
            return resp

        data = resp.get("data")
        if isinstance(data, list):
            return resp
        if resp.get("type") == "error" or resp.get("status") == "failed":
            return resp

        if not isinstance(data, dict):
            return resp

        body = str(data.get("response_body", "") or "")
        if not body:
            return resp

        galleries = parse_vipr_gallery_html(body)
        return {**resp, "data": galleries}

    def _create_sidecar_gallery(self, service: str, name: str) -> GalleryResult:
        if service == "vipr.im":
            return self._create_vipr_gallery(name)

        try:
            if service == config.PIXHOST_SERVICE_ID:
                response = self._transport_request(
                    service,
                    f"{config.PIXHOST_API_BASE_URL}/galleries",
                    method="POST",
                    headers={"Accept": "application/json"},
                    form_fields={"gallery_name": name},
                    timeout=20,
                )
                if not response.ok:
                    return self._failure_from_response(service, response.raw)
                try:
                    raw = response.json()
                except json.JSONDecodeError as exc:
                    return self._result(
                        GalleryStatus.PARSE_FAILED,
                        f"Gallery creation response was not valid JSON: {exc}",
                        service,
                        raw=response.raw,
                    )
                resp = {**response.raw, "data": raw}
            else:
                response = self._transport_request(
                    service,
                    f"https://api.{service}/galleries",
                    method="POST",
                    headers={"Accept": "application/json"},
                    form_fields={"gallery_name": name},
                    timeout=20,
                )
                if not response.ok:
                    return self._failure_from_response(service, response.raw)
                try:
                    raw = response.json()
                except json.JSONDecodeError as exc:
                    return self._result(
                        GalleryStatus.PARSE_FAILED,
                        f"Gallery creation response was not valid JSON: {exc}",
                        service,
                        raw=response.raw,
                    )
                resp = {**response.raw, "data": raw}
        except Exception as exc:
            logger.error(f"Failed to create gallery for {service}: {exc}")
            return self._result(GalleryStatus.ERROR, str(exc), service)

        if not isinstance(resp, dict):
            return self._result(
                GalleryStatus.PARSE_FAILED,
                "Gallery creation returned an unreadable response.",
                service,
                raw=resp,
            )
        if resp.get("status") != "success":
            return self._failure_from_response(service, resp)

        data = resp.get("data")
        raw = data if isinstance(data, dict) else {}
        if not raw:
            raw = {"id": resp.get("msg") or data, "name": name}
        else:
            raw = {**raw, "name": raw.get("name") or raw.get("gallery_name") or name}

        record = normalize_gallery_record(service, raw)
        if not record:
            return self._result(
                GalleryStatus.PARSE_FAILED,
                "Gallery was created, but its ID could not be parsed.",
                service,
                raw=resp,
            )
        return self._result(
            GalleryStatus.SUCCESS,
            f"Created gallery '{record.name}' ({record.id}).",
            service,
            records=[record],
            record=record,
            raw=resp,
        )

    def _create_vipr_gallery(self, name: str) -> GalleryResult:
        try:
            if not self._login_vipr():
                return self._result(
                    GalleryStatus.LOGIN_FAILED,
                    "Vipr.im login failed. Check the saved username and password.",
                    "vipr.im",
                )
            response = self._transport_request(
                "vipr.im",
                "https://vipr.im/",
                method="POST",
                form_fields={
                    "op": "my_files",
                    "fld_id": "0",
                    "sort_field": "file_created",
                    "sort_order": "down",
                    "export_mode": "",
                    "domain": "vipr.im",
                    "create_new_folder": name,
                },
                timeout=20,
            )
        except Exception as exc:
            logger.error(f"Failed to create Vipr gallery: {exc}")
            return self._result(GalleryStatus.ERROR, str(exc), "vipr.im")

        resp = {**response.raw, "data": {"response_body": response.body}}
        if not isinstance(resp, dict):
            return self._result(
                GalleryStatus.PARSE_FAILED,
                "Gallery creation returned an unreadable response.",
                "vipr.im",
                raw=resp,
            )
        if resp.get("status") != "success":
            return self._failure_from_response("vipr.im", resp)

        data = resp.get("data")
        body = str(data.get("response_body", "") or "") if isinstance(data, dict) else ""
        raw_records = parse_vipr_gallery_html(body)
        raw = next((record for record in raw_records if record.get("name") == name), None)

        record = normalize_gallery_record("vipr.im", raw or {})
        if not record:
            return self._result(
                GalleryStatus.PARSE_FAILED,
                "Vipr.im created the gallery, but its folder ID could not be parsed.",
                "vipr.im",
                raw=resp,
            )
        return self._result(
            GalleryStatus.SUCCESS,
            f"Created gallery '{record.name}' ({record.id}).",
            "vipr.im",
            records=[record],
            record=record,
            raw=resp,
        )

    def _delete_vipr_gallery(self, gallery_id: str, gallery_name: str) -> GalleryResult:
        try:
            if not self._login_vipr():
                return self._result(
                    GalleryStatus.LOGIN_FAILED,
                    "Vipr.im login failed. Check the saved username and password.",
                    "vipr.im",
                )
            response = self._transport_request(
                "vipr.im",
                f"https://vipr.im/?op=my_files&fld_id=0&del_folder={gallery_id}",
                timeout=20,
            )
        except Exception as exc:
            logger.error(f"Failed to delete Vipr gallery {gallery_id}: {exc}")
            return self._result(GalleryStatus.ERROR, str(exc), "vipr.im")

        resp = {**response.raw, "data": {"response_body": response.body}}
        if not isinstance(resp, dict):
            return self._result(
                GalleryStatus.PARSE_FAILED,
                "Gallery deletion returned an unreadable response.",
                "vipr.im",
                raw=resp,
            )
        if resp.get("status") != "success":
            return self._failure_from_response("vipr.im", resp)

        data = resp.get("data")
        body = str(data.get("response_body", "") or "") if isinstance(data, dict) else ""
        if not body:
            return self._result(
                GalleryStatus.PARSE_FAILED,
                "Vipr.im deleted the gallery, but the file-manager page could not be read.",
                "vipr.im",
                raw=resp,
            )

        remaining = parse_vipr_gallery_html(body)
        if any(str(record.get("id") or "") == gallery_id for record in remaining):
            return self._result(
                GalleryStatus.ERROR,
                f"Vipr.im still lists gallery '{gallery_name}' ({gallery_id}) after deletion.",
                "vipr.im",
                raw=resp,
            )

        record = GalleryRecord(service="vipr.im", id=gallery_id, name=gallery_name)
        return self._result(
            GalleryStatus.SUCCESS,
            f"Deleted gallery '{gallery_name}' ({gallery_id}).",
            "vipr.im",
            record=record,
            raw=resp,
        )

    def _transport_request(
        self,
        service: str,
        url: str,
        *,
        method: str = "GET",
        headers: Optional[Mapping[str, Any]] = None,
        form_fields: Optional[Mapping[str, Any]] = None,
        timeout: float = 20,
    ):
        service = config.normalize_service_id(service)
        spec = build_transport_spec(
            url,
            method=method,
            headers=headers,
            form_fields=form_fields,
            use_cookies=True,
        )
        return execute_transport_request(
            spec,
            service=service,
            timeout=timeout,
            bridge=self.bridge,
        )

    def _login_vipr(self) -> bool:
        response = self._transport_request(
            "vipr.im",
            "https://vipr.im/",
            method="POST",
            form_fields={
                "op": "login",
                "login": self.creds.get("vipr_user", ""),
                "password": self.creds.get("vipr_pass", ""),
            },
            timeout=20,
        )
        return response.ok

    def _login_imagebam(self) -> bool:
        login_page = self._transport_request(
            "imagebam.com",
            "https://www.imagebam.com/auth/login",
            timeout=30,
        )
        if not login_page.ok:
            return False

        soup = BeautifulSoup(login_page.body or "", "html.parser")
        token_field = soup.select_one("input[name='_token']")
        token = str(token_field.get("value") or "").strip() if token_field else ""
        if not token:
            return False

        response = self._transport_request(
            "imagebam.com",
            "https://www.imagebam.com/auth/login",
            method="POST",
            headers={"Referer": "https://www.imagebam.com/auth/login"},
            form_fields={
                "_token": token,
                "email": self.creds.get("imagebam_user", ""),
                "password": self.creds.get("imagebam_pass", ""),
                "remember": "on",
            },
            timeout=30,
        )
        return response.ok and _looks_like_imagebam_logged_in(response.body)

    def _records_from_sidecar_response(
        self, service: str, resp: Any, page: int = 1
    ) -> GalleryResult:
        if not isinstance(resp, dict):
            return self._result(
                GalleryStatus.PARSE_FAILED,
                "Gallery list returned an unreadable response.",
                service,
                page=page,
                raw=resp,
            )
        if resp.get("type") == "error" or resp.get("status") == "failed":
            return self._failure_from_response(service, resp, page=page)

        data = resp.get("data")
        if data == []:
            return self._result(
                GalleryStatus.EMPTY,
                f"No galleries found for {SERVICE_LABELS.get(service, service)}.",
                service,
                page=page,
                raw=resp,
            )
        if not isinstance(data, list):
            return self._result(
                GalleryStatus.PARSE_FAILED,
                "Gallery list response did not contain a gallery list.",
                service,
                page=page,
                raw=resp,
            )
        return self._records_from_raw(service, data, page=page, raw=resp)

    def _records_from_raw(
        self, service: str, raw_records: List[Any], page: int = 1, raw: Any = None
    ) -> GalleryResult:
        records = []
        invalid_count = 0
        for raw_record in raw_records:
            if not isinstance(raw_record, Mapping):
                invalid_count += 1
                continue
            record = normalize_gallery_record(service, raw_record)
            if record:
                records.append(record)
            else:
                invalid_count += 1

        if records:
            return self._result(
                GalleryStatus.SUCCESS,
                f"Loaded {len(records)} gallery record(s).",
                service,
                records=records,
                page=page,
                raw=raw if raw is not None else raw_records,
            )
        if invalid_count:
            return self._result(
                GalleryStatus.PARSE_FAILED,
                "Gallery list was returned, but no gallery IDs could be parsed.",
                service,
                page=page,
                raw=raw if raw is not None else raw_records,
            )
        return self._result(
            GalleryStatus.EMPTY,
            f"No galleries found for {SERVICE_LABELS.get(service, service)}.",
            service,
            page=page,
            raw=raw if raw is not None else raw_records,
        )

    def _create_imx_session(self) -> Tuple[Optional[requests.Session], Optional[GalleryResult]]:
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})

        if self._imx_manual_cookies:
            for key, value in self._imx_manual_cookies.items():
                session.cookies.set(key, value, domain="imx.to")
            return session, None

        user = str(self.creds.get("imx_user", "") or "").strip()
        password = str(self.creds.get("imx_pass", "") or "").strip()
        if not user or not password:
            return session, self._result(
                GalleryStatus.MISSING_CREDENTIALS,
                "IMX.to needs IMX username and IMX password.",
                "imx.to",
            )

        try:
            login_url = "https://imx.to/login.php"
            session.get(login_url, timeout=10)
            response = session.post(
                login_url,
                data={"usr_email": user, "pwd": password, "doLogin": "Login", "remember": "1"},
                timeout=10,
            )
            if response.status_code in {401, 403}:
                return session, self._result(
                    GalleryStatus.LOGIN_FAILED,
                    "IMX.to login failed. Check the saved IMX username and password.",
                    "imx.to",
                    raw=response.text,
                )
        except requests.RequestException as exc:
            logger.error(f"IMX login request failed: {exc}")
            return session, self._result(GalleryStatus.ERROR, str(exc), "imx.to")

        return session, None

    def _list_imx_galleries(self, page: int) -> GalleryResult:
        session, problem = self._create_imx_session()
        if problem:
            problem.page = page
            return problem

        return self._fetch_imx_gallery_page(session, page)

    def _fetch_imx_gallery_page(self, session: requests.Session, page: int) -> GalleryResult:
        try:
            response = session.get(
                f"https://imx.to/user/galleries?page={page}&limit=200",
                timeout=15,
            )
        except requests.RequestException as exc:
            logger.error(f"Failed to fetch IMX galleries: {exc}")
            return self._result(GalleryStatus.ERROR, str(exc), "imx.to", page=page)

        if response.status_code in {401, 403} or _looks_like_imx_login_page(response.text):
            return self._result(
                GalleryStatus.LOGIN_FAILED,
                "IMX.to login failed. Check credentials or set a manual PHPSESSID cookie.",
                "imx.to",
                page=page,
                raw=response.text,
            )
        if response.status_code >= 400:
            return self._result(
                GalleryStatus.ERROR,
                f"IMX.to returned HTTP {response.status_code} while listing galleries.",
                "imx.to",
                page=page,
                raw=response.text,
            )

        raw_records, candidates = parse_imx_gallery_html(response.text)
        if not raw_records and candidates:
            return self._result(
                GalleryStatus.PARSE_FAILED,
                "IMX.to gallery page changed and could not be parsed.",
                "imx.to",
                page=page,
                raw=response.text,
            )
        return self._records_from_raw("imx.to", raw_records, page=page, raw=response.text)

    def _sync_all_imx_galleries(
        self, max_pages: int, progress_callback: Optional[Any] = None
    ) -> GalleryResult:
        session, problem = self._create_imx_session()
        if problem:
            return problem

        all_records: List[GalleryRecord] = []
        seen = set()
        last_page = 0

        for page in range(1, max_pages + 1):
            result = self._fetch_imx_gallery_page(session, page)
            if result.status == GalleryStatus.EMPTY:
                if all_records:
                    break
                return result
            if not result.ok:
                return result

            new_records = []
            for record in result.records:
                if record.id in seen:
                    continue
                seen.add(record.id)
                new_records.append(record)

            if not new_records and all_records:
                break

            all_records.extend(new_records)
            last_page = page
            if callable(progress_callback):
                progress_callback(page, len(all_records))

            if len(result.records) < IMX_GALLERY_PAGE_SIZE:
                break
        else:
            return self._result(
                GalleryStatus.ERROR,
                f"Stopped IMX.to sync after {max_pages} pages before reaching the end.",
                "imx.to",
                records=all_records,
                page=max_pages,
            )

        return self._result(
            GalleryStatus.SUCCESS,
            f"Synced {len(all_records)} IMX.to gallery record(s) from {last_page} page(s).",
            "imx.to",
            records=all_records,
            page=max(1, last_page),
            raw={"pages": last_page, "sync_complete": True},
        )

    def _create_imx_gallery(self, name: str) -> GalleryResult:
        session, problem = self._create_imx_session()
        if problem:
            return problem

        try:
            response = session.post(
                "https://imx.to/user/gallery/add",
                data={"gallery_name": name, "submit_new_gallery": "Add"},
                timeout=15,
            )
        except requests.RequestException as exc:
            logger.error(f"Failed to create IMX gallery: {exc}")
            return self._result(GalleryStatus.ERROR, str(exc), "imx.to")

        if response.status_code in {401, 403} or _looks_like_imx_login_page(response.text):
            return self._result(
                GalleryStatus.LOGIN_FAILED,
                "IMX.to login failed while creating the gallery.",
                "imx.to",
                raw=response.text,
            )
        if response.status_code >= 400:
            return self._result(
                GalleryStatus.ERROR,
                f"IMX.to returned HTTP {response.status_code} while creating the gallery.",
                "imx.to",
                raw=response.text,
            )

        gallery_id = _gallery_id_from_query(response.url)
        if gallery_id:
            record = normalize_gallery_record("imx.to", {"id": gallery_id, "name": name})
            return self._result(
                GalleryStatus.SUCCESS,
                f"Created gallery '{record.name}' ({record.id}).",
                "imx.to",
                records=[record],
                record=record,
                raw=response.text,
            )

        found = self._find_imx_gallery_by_name(session, name)
        if found:
            return self._result(
                GalleryStatus.SUCCESS,
                f"Created gallery '{found.name}' ({found.id}).",
                "imx.to",
                records=[found],
                record=found,
                raw=response.text,
            )

        return self._result(
            GalleryStatus.PARSE_FAILED,
            "IMX.to did not return the new gallery ID.",
            "imx.to",
            raw=response.text,
        )

    def _find_imx_gallery_by_name(
        self, session: requests.Session, name: str
    ) -> Optional[GalleryRecord]:
        try:
            response = session.get("https://imx.to/user/galleries?page=1&limit=200", timeout=10)
        except requests.RequestException as exc:
            logger.debug(f"Could not refetch IMX galleries after create: {exc}")
            return None

        raw_records, _ = parse_imx_gallery_html(response.text)
        for raw_record in raw_records:
            record = normalize_gallery_record("imx.to", raw_record)
            if record and record.name == name:
                return record
        return None

    def _delete_imx_gallery(self, gallery_id: str, gallery_name: str) -> GalleryResult:
        session, problem = self._create_imx_session()
        if problem:
            return problem

        try:
            response = session.post(
                f"https://imx.to/user/gallery/edit?id={gallery_id}",
                data={"delete_confirm": "on", "delete_gallery": "Remove Gallery"},
                timeout=15,
            )
        except requests.RequestException as exc:
            logger.error(f"Failed to delete IMX gallery {gallery_id}: {exc}")
            return self._result(GalleryStatus.ERROR, str(exc), "imx.to")

        if response.status_code in {401, 403} or _looks_like_imx_login_page(response.text):
            return self._result(
                GalleryStatus.LOGIN_FAILED,
                "IMX.to login failed while deleting the gallery.",
                "imx.to",
                raw=response.text,
            )
        if response.status_code >= 400:
            return self._result(
                GalleryStatus.ERROR,
                f"IMX.to returned HTTP {response.status_code} while deleting the gallery.",
                "imx.to",
                raw=response.text,
            )

        try:
            list_response = session.get(
                "https://imx.to/user/galleries?page=1&limit=200",
                timeout=10,
            )
        except requests.RequestException as exc:
            logger.error(f"Failed to verify IMX gallery deletion {gallery_id}: {exc}")
            return self._result(GalleryStatus.ERROR, str(exc), "imx.to")

        if list_response.status_code in {401, 403} or _looks_like_imx_login_page(
            list_response.text
        ):
            return self._result(
                GalleryStatus.LOGIN_FAILED,
                "IMX.to login failed while confirming gallery deletion.",
                "imx.to",
                raw=list_response.text,
            )
        if list_response.status_code >= 400:
            return self._result(
                GalleryStatus.ERROR,
                f"IMX.to returned HTTP {list_response.status_code} while confirming deletion.",
                "imx.to",
                raw=list_response.text,
            )

        remaining, _ = parse_imx_gallery_html(list_response.text)
        if any(str(record.get("id") or "") == gallery_id for record in remaining):
            return self._result(
                GalleryStatus.ERROR,
                f"IMX.to still lists gallery '{gallery_name}' ({gallery_id}) after deletion.",
                "imx.to",
                raw=list_response.text,
            )

        record = GalleryRecord(service="imx.to", id=gallery_id, name=gallery_name)
        return self._result(
            GalleryStatus.SUCCESS,
            f"Deleted gallery '{gallery_name}' ({gallery_id}).",
            "imx.to",
            record=record,
            raw=response.text,
        )

    def _failure_from_response(
        self, service: str, resp: Mapping[str, Any], page: int = 1
    ) -> GalleryResult:
        message = str(resp.get("msg") or resp.get("message") or "Gallery operation failed.")
        lowered = message.lower()
        if "credential" in lowered or "missing" in lowered:
            status = GalleryStatus.MISSING_CREDENTIALS
        elif "login" in lowered or "auth" in lowered:
            status = GalleryStatus.LOGIN_FAILED
        elif "support" in lowered:
            status = GalleryStatus.UNSUPPORTED
        else:
            status = GalleryStatus.ERROR
        return self._result(status, message, service, page=page, raw=dict(resp))

    def _creds_dict(self) -> Dict[str, str]:
        return {
            "imx_user": str(self.creds.get("imx_user", "") or "").strip(),
            "imx_pass": str(self.creds.get("imx_pass", "") or "").strip(),
            "vipr_user": str(self.creds.get("vipr_user", "") or "").strip(),
            "vipr_pass": str(self.creds.get("vipr_pass", "") or "").strip(),
            "imagebam_user": str(self.creds.get("imagebam_user", "") or "").strip(),
            "imagebam_pass": str(self.creds.get("imagebam_pass", "") or "").strip(),
            "api_key": str(self.creds.get("imx_api", "") or "").strip(),
        }

    def _result(
        self,
        status: str,
        message: str,
        service: str,
        records: Optional[List[GalleryRecord]] = None,
        record: Optional[GalleryRecord] = None,
        page: int = 1,
        raw: Any = None,
        cached: bool = False,
    ) -> GalleryResult:
        return GalleryResult(
            status=status,
            message=message,
            service=service,
            records=records or [],
            record=record,
            page=page,
            raw=raw,
            cached=cached,
        )


def _gallery_id_from_query(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    values = query.get("id") or query.get("gallery_id")
    return str(values[0]).strip() if values else ""


def _looks_like_imx_login_page(html: str) -> bool:
    lowered = (html or "").lower()
    login_markers = ("usr_email", "dologin", "login_form", "incorrect username")
    return any(marker in lowered for marker in login_markers)


def _looks_like_imagebam_logged_in(html: str) -> bool:
    soup = BeautifulSoup(html or "", "html.parser")
    return bool(soup.select_one("form[action*='logout'], a[href*='/logout']"))
