# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Gallery listing/creation service layer used by the Gallery Manager UI."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup
from loguru import logger


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
    "pixhost.to": "Pixhost.to",
    "vipr.im": "Vipr.im",
}

LIST_SUPPORTED = {"imx.to", "vipr.im"}
CREATE_SUPPORTED = {"imx.to", "pixhost.to", "vipr.im"}


def gallery_url_for_service(service: str, gallery_id: str) -> str:
    if not gallery_id:
        return ""
    if service == "imx.to":
        return f"https://imx.to/g/{gallery_id}"
    if service == "pixhost.to":
        return f"https://pixhost.to/gallery/{gallery_id}"
    if service == "vipr.im":
        return f"https://vipr.im/f/{gallery_id}"
    return ""


def normalize_gallery_record(service: str, raw: Mapping[str, Any]) -> Optional[GalleryRecord]:
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
        service = service.strip()
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

        return self._list_sidecar_galleries(service, page)

    def create_gallery(self, service: str, name: str) -> GalleryResult:
        service = service.strip()
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

        return ""

    def _list_sidecar_galleries(self, service: str, page: int) -> GalleryResult:
        try:
            if service == "vipr.im":
                spec = {
                    "url": "https://vipr.im/?op=my_files",
                    "method": "GET",
                    "use_cookies": True,
                    "response_type": "html",
                    "extract_fields": {
                        "response_body": "regex:(<body[\\s\\S]*</body>)",
                    },
                    "pre_request": {
                        "action": "vipr_login",
                        "url": "https://vipr.im/",
                        "method": "POST",
                        "form_fields": {
                            "op": "login",
                            "login": self.creds.get("vipr_user", ""),
                            "password": self.creds.get("vipr_pass", ""),
                        },
                        "use_cookies": True,
                        "response_type": "html",
                        "extract_fields": {},
                    },
                }
                resp = self.bridge.request_sync(
                    {
                        "action": "http_request",
                        "service": service,
                        "generic_spec": spec,
                    },
                    timeout=20,
                )
                resp = self._normalize_vipr_gallery_response(resp)
            else:
                resp = self.bridge.request_sync(
                    {
                        "action": "http_request",
                        "service": service,
                        "generic_spec": {
                            "url": f"https://api.{service}/galleries",
                            "method": "GET",
                            "headers": {"Accept": "application/json"},
                            "response_type": "json",
                            "extract_fields": {},
                        },
                    },
                    timeout=20,
                )
        except Exception as exc:
            logger.error(f"Failed to list galleries for {service}: {exc}")
            return self._result(GalleryStatus.ERROR, str(exc), service, page=page)

        return self._records_from_sidecar_response(service, resp, page=page)

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

        galleries = []
        for match in re.finditer(r'fld_id=(\d+)[^>]*>([^<]+)', body):
            galleries.append({"id": match.group(1), "name": match.group(2).strip()})
        return {**resp, "data": galleries}

    def _create_sidecar_gallery(self, service: str, name: str) -> GalleryResult:
        try:
            if service == "pixhost.to":
                resp = self.bridge.request_sync(
                    {
                        "action": "http_request",
                        "service": service,
                        "generic_spec": {
                            "url": "https://api.pixhost.to/galleries",
                            "method": "POST",
                            "headers": {"Accept": "application/json"},
                            "form_fields": {"gallery_name": name},
                            "response_type": "json",
                            "extract_fields": {
                                "gallery_name": "gallery_name",
                                "gallery_hash": "gallery_hash",
                                "gallery_url": "gallery_url",
                                "gallery_upload_hash": "gallery_upload_hash",
                            },
                            "success_check": {
                                "field": "gallery_hash",
                                "type": "not_empty",
                            },
                        },
                    },
                    timeout=20,
                )
            else:
                resp = self.bridge.request_sync(
                    {
                        "action": "http_request",
                        "service": service,
                        "generic_spec": {
                            "url": f"https://api.{service}/galleries",
                            "method": "POST",
                            "headers": {"Accept": "application/json"},
                            "form_fields": {"gallery_name": name},
                            "response_type": "json",
                            "extract_fields": {
                                "gallery_name": "gallery_name",
                                "gallery_hash": "gallery_hash",
                                "gallery_url": "gallery_url",
                                "gallery_upload_hash": "gallery_upload_hash",
                                "id": "id",
                                "name": "name",
                            },
                        },
                    },
                    timeout=20,
                )
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
