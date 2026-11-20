# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/plugins/imagebam.py
"""
ImageBam.com plugin - Schema-based implementation.

Uploads run through the Go sidecar's transport; this plugin logs in, opens
ImageBam's upload session, builds each upload request and reads ImageBam's
answer and the session's result page (the Python upload path). The legacy
Go specs in build_http_request stay as the ``legacy_upload_parsing``
fallback. The plugin also manages the UI and the per-batch gallery title.
"""

import json
from typing import Dict, Any, List
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from .base import ImageHostPlugin
from ..result_matcher import MODE_UPLOAD_ORDER, resolve_from_result_page
from ..upload_results import (
    UploadResult,
    collapse_text,
    collect_secrets,
    html_field,
    json_parser_options,
    json_value,
    parse_json_upload,
    redact_secrets,
    request_failure,
    truncate_text,
    upload_failure,
)
from loguru import logger

# Every request of both upload paths goes to this site (tests point it at a
# local fake).
IMAGEBAM_URL = "https://www.imagebam.com"

# How ImageBam answers an upload: JSON whose ``success`` is the upload
# session's result page. Shared by the legacy spec and the Python parser.
RESPONSE_PARSER = {"type": "json", "url_path": "success", "thumb_path": ""}

# The result page lists every image of the upload session, in upload order,
# as BBCode whose view links carry no file names.
LINK_EXTRACTOR = (
    r"\[URL=(?P<image_url>https://www\.imagebam\.com/view/[^\]]+)"
    r"\]\[IMG\](?P<thumb_url>https://thumbs\d+\.imagebam\.com/[^\]]+)"
    r"\[/IMG\]\[/URL\]"
)
GALLERY_EXTRACTOR = "a#gallery-name"
RESULT_POLL_DELAYS_MS = (1000, 2000, 4000)

# Pages of the session step, as the legacy pre_request chain reads them.
LOGIN_TOKEN_SELECTOR = "input[name='_token']"
LOGGED_IN_SELECTOR = "form[action*='logout']"
CSRF_SELECTOR = "meta[name='csrf-token']"

# Where a refused login page shows why, most specific first.
LOGIN_ERROR_SELECTORS = (
    ".invalid-feedback",
    ".alert-danger",
    ".alert",
    ".help-block",
    ".error",
    "[role='alert']",
)


def _site(path: str) -> str:
    return f"{IMAGEBAM_URL}{path}"


def _is_web_link(value: str) -> bool:
    parts = urlsplit(value)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


class ImageBamPlugin(ImageHostPlugin):
    """ImageBam.com image hosting plugin using schema-based UI."""

    @property
    def id(self) -> str:
        return "imagebam.com"

    @property
    def name(self) -> str:
        return "ImageBam"

    @property
    def metadata(self) -> Dict[str, Any]:
        """Plugin metadata for ImageBam.com"""
        return {
            "version": "3.2.0",
            "author": "Connie's Uploader Team",
            "description": "Upload images to ImageBam.com with optional authentication and CSRF-protected uploads",
            "website": "https://imagebam.com",
            "implementation": "python",  # Python upload path; the sidecar is its transport
            "features": {
                "galleries": True,
                "covers": False,
                "authentication": "optional",
                "direct_links": True,
                "custom_thumbnails": True,
            },
            "credentials": [
                {
                    "key": "imagebam_user",
                    "label": "Username",
                    "required": False,
                    "description": "Optional login for private galleries",
                },
                {
                    "key": "imagebam_pass",
                    "label": "Password",
                    "required": False,
                    "secret": True,
                    "description": "Password for private galleries",
                },
            ],
            "limits": {
                "max_file_size": 25 * 1024 * 1024,  # 25MB
                "allowed_formats": [".jpg", ".jpeg", ".png", ".gif"],
                "rate_limit": "Moderate (CSRF protection)",
                "max_resolution": (10000, 10000),
                "min_resolution": (1, 1),
            },
        }

    @property
    def settings_schema(self) -> List[Dict[str, Any]]:
        """Declarative UI schema for ImageBam settings."""
        return [
            {
                "type": "dropdown",
                "key": "content_type",
                "label": "Content Type",
                "values": ["Safe", "Adult"],
                "default": "Safe",
                "required": True,
            },
            {
                "type": "dropdown",
                "key": "thumbnail_size",
                "label": "Thumbnail Size",
                "values": ["100", "180", "250", "300"],
                "default": "180",
                "required": True,
            },
            {
                "type": "separator",
                "advanced": True,
            },
            {
                "type": "text",
                "key": "gallery_id",
                "label": "Gallery Token (Optional)",
                "default": "",
                "placeholder": "Numeric ImageBam gallery token",
                "advanced": True,
            },
        ]

    def prepare_group(
        self, group, config: Dict[str, Any], context: Dict[str, Any], creds: Dict[str, Any]
    ) -> None:
        """Attach a per-batch gallery title for ImageBam's upload-session flow."""
        if not config.get("auto_gallery"):
            return

        if not (creds.get("imagebam_user") and creds.get("imagebam_pass")):
            logger.warning("ImageBam credentials not set - cannot create auto-gallery")
            return

        title = str(getattr(group, "title", "") or "Gallery").strip() or "Gallery"
        group.imagebam_gallery_title = title
        group.gallery_name = title
        group.gallery_service = self.id
        config["imagebam_gallery_title"] = title
        logger.info(f"ImageBam gallery will be created during upload: {title}")

    def build_http_request(
        self, file_path: str, config: Dict[str, Any], creds: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build HTTP request specification for ImageBam's current Dropzone uploader.

        The live site first creates an upload session, then uploads the file as
        ``files[0]`` with ``_token`` and ``data=<upload token>`` multipart fields.
        """
        session_fields = self._upload_session_fields(config)

        pre_request_spec = self._build_pre_request(session_fields, creds)

        return {
            "url": _site("/upload"),
            "method": "POST",
            "headers": self._upload_headers(),
            "pre_request": pre_request_spec,
            "multipart_fields": {
                "files[0]": {"type": "file", "value": file_path},
                "_token": {
                    "type": "dynamic",
                    "value": "csrf_token",
                },
                "data": {
                    "type": "dynamic",
                    "value": "upload_token",
                },
            },
            "response_parser": dict(RESPONSE_PARSER),
            "resolve_spec": {
                "result_url": "{url}",
                "poll_delays_ms": list(RESULT_POLL_DELAYS_MS),
                "link_extractor": LINK_EXTRACTOR,
                "gallery_extractor": GALLERY_EXTRACTOR,
                # Every file of a job shares one upload session, whose result
                # page lists all of the session's images, and view links carry
                # no file names. The sidecar runs such a job's uploads one at a
                # time and gives each file the newest entry after the last one
                # the job already holds, counting attempts that failed after
                # reaching the host.
                "file_match_mode": "upload_order",
            },
        }

    @staticmethod
    def _upload_headers() -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Referer": _site("/"),
            "X-Requested-With": "XMLHttpRequest",
        }

    def _upload_session_fields(self, config: Dict[str, Any]) -> Dict[str, str]:
        """The form of POST /upload/session: thumbnail size, content type, gallery."""
        content_type_map = {"Safe": "sfw", "Adult": "nsfw"}
        thumb_size_map = {"100": "1", "180": "2", "250": "3", "300": "4"}

        content_type_id = content_type_map.get(config.get("content_type", "Safe"), "sfw")
        thumb_size_value = str(config.get("thumbnail_size", "180"))
        thumb_size_id = thumb_size_map.get(thumb_size_value, "2")
        return self._session_form_fields(config, content_type_id, thumb_size_id)

    def upload_session_creates_gallery(self, config: Dict[str, Any]) -> bool:
        """Whether each upload session built from ``config`` creates a new gallery.

        ImageBam creates the gallery when the upload session opens with a
        gallery title, so every job sent with this config makes its own.
        """
        return bool(
            self._gallery_title_from_config(config) and not self._gallery_id_from_config(config)
        )

    @staticmethod
    def _gallery_id_from_config(config: Dict[str, Any]) -> str:
        for key in ("gallery_id", "selected_gallery_id", "imagebam_gallery_id"):
            value = str(config.get(key) or "").strip()
            if value and value not in {"0", "None", "default", "-1"}:
                return value
        return ""

    @staticmethod
    def _gallery_title_from_config(config: Dict[str, Any]) -> str:
        for key in ("imagebam_gallery_title", "gallery_title", "selected_gallery_name"):
            value = str(config.get(key) or "").strip()
            if value:
                return value
        return ""

    def _session_form_fields(
        self, config: Dict[str, Any], content_type_id: str, thumb_size_id: str
    ) -> Dict[str, str]:
        fields = {
            "thumbnail_size": thumb_size_id,
            "content_type": content_type_id,
            "comments_enabled": "false",
        }

        gallery_id = self._gallery_id_from_config(config)
        gallery_title = self._gallery_title_from_config(config)
        if gallery_id:
            fields.update(
                {
                    "gallery": "true",
                    "gallery_token": gallery_id,
                    "gallery_title": "",
                }
            )
        elif gallery_title:
            fields.update(
                {
                    "gallery": "true",
                    "gallery_token": "",
                    "gallery_title": gallery_title,
                }
            )

        return fields

    @staticmethod
    def _session_headers(csrf_token: str) -> Dict[str, str]:
        return {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-TOKEN": csrf_token,
            "Accept": "application/json",
            "Referer": _site("/"),
        }

    @classmethod
    def _upload_session_request(cls, session_fields: Dict[str, str]) -> Dict[str, Any]:
        return {
            "action": "get_upload_token",
            "url": _site("/upload/session"),
            "method": "POST",
            "headers": cls._session_headers("{csrf_token}"),
            "form_fields": session_fields,
            "use_cookies": True,
            "extract_fields": {
                "upload_token": "data",
                "imagebam_session": "session",
            },
            "response_type": "json",
        }

    def _build_pre_request(
        self, session_fields: Dict[str, str], creds: Dict[str, Any]
    ) -> Dict[str, Any]:
        upload_session = self._upload_session_request(session_fields)
        get_api_csrf = {
            "action": "get_api_csrf",
            "url": _site("/"),
            "method": "GET",
            "headers": {},
            "form_fields": {},
            "use_cookies": True,
            "extract_fields": {
                "csrf_token": CSRF_SELECTOR,
            },
            "response_type": "html",
            "follow_up_request": upload_session,
        }

        if not (creds.get("imagebam_user") and creds.get("imagebam_pass")):
            return get_api_csrf

        return {
            "action": "get_login_csrf",
            "url": _site("/auth/login"),
            "method": "GET",
            "headers": {},
            "form_fields": {},
            "use_cookies": True,
            "extract_fields": {
                "login_token": LOGIN_TOKEN_SELECTOR,
            },
            "response_type": "html",
            "follow_up_request": {
                "action": "submit_login",
                "url": _site("/auth/login"),
                "method": "POST",
                "headers": {
                    "Referer": _site("/auth/login"),
                },
                "form_fields": {
                    "_token": "{login_token}",
                    "email": creds.get("imagebam_user", ""),
                    "password": creds.get("imagebam_pass", ""),
                    "remember": "on",
                },
                "use_cookies": True,
                "extract_fields": {
                    "imagebam_login_marker": LOGGED_IN_SELECTOR,
                },
                "response_type": "html",
                "follow_up_request": get_api_csrf,
            },
        }

    # --- Python upload path ---
    #
    # The steps of the legacy pre_request chain, then the legacy response
    # parser and resolve_spec, on the job's transport session:
    #   GET /auth/login (_token), POST /auth/login     only with credentials
    #   GET / (meta csrf-token)
    #   POST /upload/session (gallery fields)          -> upload token "data"
    #   POST /upload per file (files[0], _token, data) -> JSON "success"
    #   GET the "success" page; this file's entry is the newest one after
    #   the last one the job holds (upload_order); a#gallery-name -> gallery

    def upload_job_options(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """One file at a time: the result page names no files, only the upload order."""
        return {"sequential": True}

    def open_upload_session(self, transport, config: Dict[str, Any], creds: Dict[str, Any]):
        """Log in (with credentials), read the CSRF token and open ImageBam's upload session.

        One upload session per job: its gallery fields create the gallery (a
        title) or join one (a token), so the request that may create a gallery
        is never sent twice.
        """
        user, password = creds.get("imagebam_user"), creds.get("imagebam_pass")
        secrets = collect_secrets(extra=[str(user or ""), str(password or "")])
        if user and password:
            secrets.append(self._log_in(transport, str(user), str(password), secrets))

        home = transport.get(_site("/"))
        if not home.ok:
            raise RuntimeError(request_failure("could not open ImageBam", home, secrets))
        csrf_token = html_field(home.body, CSRF_SELECTOR)
        if not csrf_token:
            raise RuntimeError("ImageBam's page had no CSRF token (meta csrf-token)")
        secrets.append(csrf_token)

        opened = transport.post(
            _site("/upload/session"),
            self._upload_session_fields(config),
            headers=self._session_headers(csrf_token),
            retry=not self.upload_session_creates_gallery(config),
        )
        if not opened.ok:
            raise RuntimeError(
                request_failure("could not open an ImageBam upload session", opened, secrets)
            )
        try:
            answer = json.loads(opened.body)
        except ValueError:
            answer = None
        upload_token = json_value(answer, "data") if isinstance(answer, dict) else ""
        if not upload_token:
            raise RuntimeError(
                upload_failure(
                    "ImageBam opened no upload session", opened.status_code, opened.body, secrets
                )
            )
        values = {"csrf_token": csrf_token, "upload_token": upload_token}
        session = json_value(answer, "session")
        if session:
            values["imagebam_session"] = session
        return values

    def _log_in(self, transport, user: str, password: str, secrets: List[str]) -> str:
        """Post ImageBam's login form; return its form token. Raises with the host's reason."""
        page = transport.get(_site("/auth/login"))
        if not page.ok:
            raise RuntimeError(
                request_failure("could not open the ImageBam login page", page, secrets)
            )
        login_token = html_field(page.body, LOGIN_TOKEN_SELECTOR)
        if not login_token:
            raise RuntimeError("the ImageBam login page had no login form token")
        secrets = secrets + [login_token]
        answer = transport.post(
            _site("/auth/login"),
            {"_token": login_token, "email": user, "password": password, "remember": "on"},
            headers={"Referer": _site("/auth/login")},
        )
        if not answer.ok:
            raise RuntimeError(request_failure("ImageBam login failed", answer, secrets))
        if not html_field(answer.body, LOGGED_IN_SELECTOR):
            raise RuntimeError(
                f"ImageBam login failed: {self._login_refusal(answer.body, secrets)}"
            )
        return login_token

    @staticmethod
    def _login_refusal(body: str, secrets: List[str]) -> str:
        """The reason a refused login page shows, else a hint."""
        soup = BeautifulSoup(body or "", "html.parser")
        for selector in LOGIN_ERROR_SELECTORS:
            for element in soup.select(selector):
                text = collapse_text(element.get_text(" "))
                if text:
                    return truncate_text(redact_secrets(text, secrets))
        return "the site did not log in (check the ImageBam username and password)"

    def build_raw_upload_request(
        self,
        file_path: str,
        config: Dict[str, Any],
        session_values: Dict[str, str],
        creds: Dict[str, Any],
    ) -> Dict[str, Any]:
        """The legacy upload request with the session's CSRF and upload tokens filled in."""
        return {
            "url": _site("/upload"),
            "method": "POST",
            "headers": self._upload_headers(),
            "multipart_fields": {
                "files[0]": {"type": "file", "value": file_path},
                "_token": {"type": "text", "value": session_values["csrf_token"]},
                "data": {"type": "text", "value": session_values["upload_token"]},
            },
        }

    def parse_upload_response(
        self, file_path, response, transport, session_values, session_state
    ) -> UploadResult:
        """Read ImageBam's answer, then find this upload on the session's result page."""
        answer = parse_json_upload(
            response,
            file_path=file_path,
            secrets=session_state.secrets,
            **json_parser_options(RESPONSE_PARSER),
        )
        if not answer.ok:
            return answer
        result_url = answer.url.strip()
        if not _is_web_link(result_url):
            # {"success": false, "message": ...} and the like.
            return UploadResult.failed(
                upload_failure(
                    "upload response had no image link",
                    response.status_code,
                    response.body,
                    session_state.secrets,
                )
            )
        return resolve_from_result_page(
            transport,
            result_url,
            file_path,
            session_state.result_matcher(MODE_UPLOAD_ORDER),
            link_extractor=LINK_EXTRACTOR,
            poll_delays_ms=RESULT_POLL_DELAYS_MS,
            gallery_extractor=GALLERY_EXTRACTOR,
            secrets=session_state.secrets,
        )

    # --- Legacy stubs ---

    def initialize_session(self, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
        """Stub - Go sidecar handles session initialization."""
        return {}

    def upload_file(
        self,
        file_path: str,
        group,
        config: Dict[str, Any],
        context: Dict[str, Any],
        progress_callback,
    ):
        """Stub - Go sidecar handles file uploads via build_http_request()."""
        pass
