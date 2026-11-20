# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/plugins/turbo.py
"""
TurboImageHost plugin - Schema-based implementation.

Uploads run through the Go sidecar's transport on the Python upload path:
open_upload_session logs in (optional) and reads the upload endpoint from the
home page, build_raw_upload_request builds each file's request, and
parse_upload_response reads Turbo's JSON answer and then finds the file's
link on Turbo's result page. build_http_request keeps the legacy Go spec for
the ``legacy_upload_parsing`` fallback.
"""

import re
import secrets
import string
from typing import Dict, Any, Iterable, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from loguru import logger

from .base import ImageHostPlugin
from . import helpers
from ..result_matcher import resolve_from_result_page
from ..upload_results import (
    UploadResult,
    collapse_text,
    html_field,
    json_parser_options,
    parse_json_upload,
    redact_secrets,
    request_failure,
    truncate_text,
)

# Where TurboImageHost lives. Tests point it at a local fake host.
BASE_URL = "https://www.turboimagehost.com"

# The home page configures its uploader with the upload script: endpoint: '...'.
ENDPOINT_PATTERN = r"endpoint:\s*'([^']+)'"

# How the result page lists each image of the upload session:
# [url=https://…/p/<id>/<file name>.html][img]<thumbnail>[/img][/url].
LINK_EXTRACTOR = (
    r"(?is)\[url=(?P<image_url>https?://[^\]]+?/p/[0-9]+/"
    r"(?P<filename>[^/\]]+?)\.html)\]\s*"
    r"\[img\](?P<thumb_url>https?://[^\]]+?)\[/img\]\s*\[/url\]"
)

# The result page's gallery link box.
GALLERY_SELECTOR = "input#imgCodeGG"

# How long to wait between looks at the result page (the legacy schedule).
POLL_DELAYS_MS = (500, 1000, 2000, 3000, 5000, 5000)

# Result-page entries are matched to files by name (ResultPageMatcher).
FILE_MATCH_MODE = "filename"

# A login answer with a logout link or form is logged in.
_LOGGED_IN_SELECTOR = "a[href*='logout' i], form[action*='logout' i]"
_PASSWORD_INPUT = "input[type=password i]"

# Elements a login page shows its error in, most specific first.
_LOGIN_MESSAGE_SELECTORS = (
    ".error",
    ".errors",
    ".alert",
    ".warning",
    ".notice",
    "#error",
    "#message",
    ".message",
    "font[color]",
)


def _response_parser() -> Dict[str, str]:
    """How Turbo answers an upload; shared by the legacy spec and the Python parser."""
    return {
        "type": "json",
        "url_path": "newUrl",
        "thumb_path": "",
        "status_path": "success",
        "success_value": "true",
        "url_template": f"{BASE_URL}/p/{{id}}/{{filename}}.html",
    }


def _endpoint_discovery() -> Dict[str, Any]:
    """The legacy pre_request step that reads the upload endpoint from the home page."""
    return {
        "action": "turbo_discover_endpoint",
        "url": f"{BASE_URL}/",
        "method": "GET",
        "use_cookies": True,
        "response_type": "html",
        "extract_fields": {"endpoint": f"regex:{ENDPOINT_PATTERN}"},
    }


def _login_form(username: str, password: str) -> Dict[str, str]:
    return {"username": username, "password": password, "remember": "y", "login": "Login"}


def _upload_script_url(endpoint: str) -> str:
    """The upload URL for an endpoint read from the home page, as the legacy path resolves it.

    The endpoint may be absolute or relative to Turbo's default upload script;
    one that is not a URL leaves the default script.
    """
    default = f"{BASE_URL}/upload_html5.tu"
    try:
        return urljoin(default, endpoint.strip())
    except ValueError:
        return default


def _is_login_form(form: Any, page_url: str) -> bool:
    """Whether ``form`` is a login form: a password field, posted to the login page.

    A form without an action posts back to the page it is on.
    """
    if form.select_one(_PASSWORD_INPUT) is None:
        return False
    action = str(form.get("action") or "").strip()
    return "login" in (action or str(page_url or "")).lower()


def _login_refusal(body: str, secrets_: Iterable[str], page_url: str = "") -> Optional[str]:
    """Why the host refused a login, when its answer shows the login form again; else None.

    An answer with a logout link or form is logged in, whatever else it
    shows (a header login box, an account page's password field). Without
    one, the login is refused only if the answer shows the login form again.
    """
    soup = BeautifulSoup(str(body or ""), "html.parser")
    if soup.select_one(_LOGGED_IN_SELECTOR) is not None:
        return None
    if not any(_is_login_form(form, page_url) for form in soup.select("form")):
        return None
    for selector in _LOGIN_MESSAGE_SELECTORS:
        element = soup.select_one(selector)
        text = collapse_text(element.get_text(" ")) if element is not None else ""
        if text:
            return truncate_text(redact_secrets(text, secrets_))
    return "it showed its login form again; check the username and password"


class TurboSessionError(RuntimeError):
    """TurboImageHost refused the login, or its upload page could not be used."""


class TurboPlugin(ImageHostPlugin):
    """TurboImageHost image hosting plugin using schema-based UI."""

    THUMBNAIL_SIZES = ("150", "200", "250", "300", "350", "400", "500", "600")
    DEFAULT_THUMBNAIL_SIZE = "200"

    @classmethod
    def _offered_thumbnail_size(cls, value: Any) -> str:
        """Return ``value`` if Turbo offers it, else the nearest offered size.

        Older settings default to 180, which Turbo does not offer.
        """
        text = str(value or "").strip()
        if text in cls.THUMBNAIL_SIZES:
            return text
        try:
            wanted = float(text)
        except ValueError:
            return cls.DEFAULT_THUMBNAIL_SIZE
        return min(cls.THUMBNAIL_SIZES, key=lambda size: (abs(int(size) - wanted), -int(size)))

    @property
    def id(self) -> str:
        return "turboimagehost"

    @property
    def name(self) -> str:
        return "TurboImageHost"

    @property
    def metadata(self) -> Dict[str, Any]:
        """Plugin metadata for TurboImageHost"""
        return {
            "version": "3.2.0",
            "author": "Connie's Uploader Team",
            "description": "Upload images to TurboImageHost with optional authentication, dynamic endpoint configuration, and cover image support",
            "website": "https://www.turboimagehost.com",
            "implementation": "python",  # Python upload path; the sidecar is its transport
            "features": {
                "galleries": True,
                "covers": True,
                "authentication": "optional",
                "direct_links": True,
                "custom_thumbnails": True,
                "dynamic_endpoint": True,  # Fetches upload endpoint dynamically
            },
            "credentials": [
                {
                    "key": "turbo_user",
                    "label": "Username",
                    "required": False,
                    "description": "Optional login for enhanced features",
                },
                {
                    "key": "turbo_pass",
                    "label": "Password",
                    "required": False,
                    "secret": True,
                    "description": "Password for enhanced features",
                },
            ],
            "limits": {
                "max_file_size": 35 * 1024 * 1024,
                "allowed_formats": [".jpg", ".jpeg", ".png", ".gif"],
                "rate_limit": "Moderate (respectful use)",
                "max_resolution": (15000, 15000),
                "min_resolution": (1, 1),
            },
        }

    @property
    def settings_schema(self) -> List[Dict[str, Any]]:
        """Declarative UI schema for Turbo settings."""
        return [
            {
                "type": "dropdown",
                "key": "thumbnail_size",
                "label": "Thumbnail Size",
                "values": list(self.THUMBNAIL_SIZES),
                "default": self.DEFAULT_THUMBNAIL_SIZE,
                "required": True,
            },
            {
                "type": "inline_group",
                "fields": [
                    {"type": "label", "text": "Auto Covers:", "width": 100},
                    {
                        "type": "dropdown",
                        "key": "cover_count",
                        "values": [str(i) for i in range(11)],
                        "default": "0",
                        "width": 80,
                    },
                ],
            },
            {
                "type": "checkbox",
                "key": "save_links",
                "label": "Save Links.txt",
                "default": False,
                "advanced": True,
            },
            {
                "type": "separator",
                "advanced": True,
            },
            {
                "type": "text",
                "key": "gallery_id",
                "label": "Gallery ID (Optional)",
                "default": "",
                "placeholder": "Leave blank for auto-gallery",
                "advanced": True,
            },
        ]

    def validate_configuration(self, config: Dict[str, Any]) -> List[str]:
        """Custom validation for Turbo configuration."""
        errors = []

        # Convert cover_count to int (using helper)
        helpers.validate_cover_count(config, errors)

        # Content type - turbo uses "adult" or "all"
        # For now, default to "all" (safe)
        config["content_type"] = "all"

        return errors

    def prepare_group(
        self, group, config: Dict[str, Any], context: Dict[str, Any], creds: Dict[str, Any]
    ) -> None:
        """Attach Turbo gallery metadata for One Gallery Per Folder uploads."""
        if not config.get("auto_gallery"):
            return

        gallery_name = self._safe_gallery_name(getattr(group, "title", "") or "Gallery")
        upload_id = self._upload_id()
        helpers.claim_group_gallery(group, self.id)
        group.turbo_gallery_create = True
        group.turbo_gallery_name = gallery_name
        group.turbo_upload_id = upload_id
        group.gallery_name = gallery_name

    @staticmethod
    def _safe_gallery_name(title: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_ -]+", " ", str(title or "Gallery"))
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_")
        if len(cleaned) < 2:
            cleaned = "Gallery"
        return cleaned[:20].strip() or "Gallery"

    @staticmethod
    def _upload_id() -> str:
        alphabet = string.ascii_lowercase + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(20))

    def build_http_request(
        self, file_path: str, config: Dict[str, Any], creds: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Build HTTP request spec for TurboImageHost upload.

        Uses FineUploader-compatible multipart fields with a dynamic upload
        endpoint discovered from the homepage.
        """
        upload_id = config.get("turbo_upload_id") or config.get("upload_id") or self._upload_id()

        # Map content type.
        raw_content = (config.get("content_type") or "all").lower()
        content_value = "adult" if raw_content in ("adult", "18", "true") else "all"

        thumb_size = self._offered_thumbnail_size(
            config.get("thumbnail_size") or config.get("turbo_thumb")
        )

        # Build multipart fields. One spec serves every file of the job, so
        # per-file values are sidecar tokens it fills for each file:
        # {filename}, {file_size} (bytes) and {upload_id} (unique per file).
        multipart_fields = {
            "qqfile": {"type": "file", "value": file_path},
            "upload_id": {"type": "text", "value": upload_id},
            "qquuid": {"type": "text", "value": "{upload_id}"},
            "qqfilename": {"type": "text", "value": "{filename}"},
            "qqtotalfilesize": {"type": "text", "value": "{file_size}"},
            "imcontent": {"type": "text", "value": content_value},
            "thumb_size": {"type": "text", "value": thumb_size},
        }

        # Gallery fields.
        if config.get("turbo_gallery_create") or config.get("gallery_create"):
            gallery_name = (
                config.get("turbo_gallery_name")
                or config.get("gallery_name")
                or config.get("selected_gallery_name")
                or "Gallery"
            ).strip()
            if gallery_name:
                multipart_fields["galleryC"] = {"type": "text", "value": "1"}
                multipart_fields["galleryN"] = {
                    "type": "text",
                    "value": gallery_name,
                }
        else:
            gallery_id = (config.get("turbo_gallery_id") or config.get("gallery_id") or "").strip()
            if gallery_id:
                multipart_fields["album"] = {"type": "text", "value": gallery_id}

        # Build login pre-request chain if credentials are provided.
        username = (creds.get("turbo_user") or "").strip()
        pre_request = None
        if username:
            # Step 1: POST login
            # Step 2: GET homepage to discover upload endpoint
            pre_request = {
                "action": "turbo_login",
                "url": f"{BASE_URL}/login.tu?",
                "method": "POST",
                "form_fields": _login_form(username, creds.get("turbo_pass", "")),
                "use_cookies": True,
                "response_type": "html",
                "extract_fields": {},
                "follow_up_request": _endpoint_discovery(),
            }
        else:
            # No login, just discover the upload endpoint.
            pre_request = _endpoint_discovery()

        return {
            "url": f"{BASE_URL}/upload_html5.tu",
            "method": "POST",
            "headers": {
                "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
                "Referer": f"{BASE_URL}/",
            },
            "multipart_fields": multipart_fields,
            "pre_request": pre_request,
            "response_parser": _response_parser(),
            "resolve_spec": {
                "result_url": "{url}",
                "poll_delays_ms": list(POLL_DELAYS_MS),
                "link_extractor": LINK_EXTRACTOR,
                "gallery_extractor": GALLERY_SELECTOR,
                "file_match_mode": FILE_MATCH_MODE,
            },
        }

    # --- Python upload path ---

    def open_upload_session(
        self, transport, config: Dict[str, Any], creds: Dict[str, Any]
    ) -> Dict[str, str]:
        """Log in when a username and password are set, then read the upload endpoint.

        The steps of the legacy pre_request chain, on the job's session. A
        refused login and an upload page without an endpoint fail the job's
        files with the host's message. With only one of the two credentials
        the files upload anonymously, as they did on the legacy path (which
        posted the half login and ignored Turbo's answer). Returns the upload
        URL and the job's upload_id (the group's gallery id, else a new one,
        as the legacy spec).
        """
        username = (creds.get("turbo_user") or "").strip()
        password = str(creds.get("turbo_pass") or "")
        hidden = [password, username]
        if bool(username) != bool(password):
            missing = "password" if username else "username"
            logger.warning(
                f"TurboImageHost: no {missing} saved, so this upload goes anonymously; "
                "save both to upload to your account"
            )
        if username and password:
            login = transport.post(f"{BASE_URL}/login.tu?", _login_form(username, password))
            if not login.ok:
                raise TurboSessionError(
                    request_failure("TurboImageHost login failed", login, hidden)
                )
            refusal = _login_refusal(login.body, hidden, login.final_url)
            if refusal is not None:
                raise TurboSessionError(f"TurboImageHost refused the login: {refusal}")

        home = transport.get(f"{BASE_URL}/")
        if not home.ok:
            raise TurboSessionError(
                request_failure("could not open TurboImageHost's upload page", home, hidden)
            )
        endpoint = html_field(home.body, f"regex:{ENDPOINT_PATTERN}")
        if not endpoint:
            raise TurboSessionError(
                "TurboImageHost's upload page names no upload endpoint (the page may have changed)"
            )
        upload_id = config.get("turbo_upload_id") or config.get("upload_id") or self._upload_id()
        return {"upload_url": _upload_script_url(endpoint), "upload_id": str(upload_id)}

    def build_raw_upload_request(
        self,
        file_path: str,
        config: Dict[str, Any],
        session_values: Dict[str, str],
        creds: Dict[str, Any],
    ) -> Dict[str, Any]:
        """The legacy request, sent to the session's endpoint with this file's own values.

        The legacy spec's per-file tokens ({upload_id}, {filename},
        {file_size}) become this file's values; everything is sent literally,
        so braces in a file name stay braces.
        """
        spec = self.build_http_request(file_path, config, {})
        values = helpers.per_file_upload_values(file_path)
        fields = {name: dict(field) for name, field in spec["multipart_fields"].items()}
        fields["upload_id"]["value"] = (
            session_values.get("upload_id") or fields["upload_id"]["value"]
        )
        fields["qquuid"]["value"] = values["upload_id"]
        fields["qqfilename"]["value"] = values["filename"]
        fields["qqtotalfilesize"]["value"] = values["file_size"]
        return {
            "url": session_values.get("upload_url") or spec["url"],
            "method": spec["method"],
            "headers": dict(spec["headers"]),
            "multipart_fields": fields,
        }

    def parse_upload_response(
        self, file_path, response, transport, session_values, session_state
    ) -> UploadResult:
        """Read Turbo's JSON answer, then find this file's link on the result page it names."""
        upload = parse_json_upload(
            response,
            file_path=file_path,
            secrets=session_state.secrets,
            **json_parser_options(_response_parser()),
        )
        if not upload.ok or upload.thumb.strip():
            return upload
        return resolve_from_result_page(
            transport,
            upload.url,
            file_path,
            session_state.result_matcher(FILE_MATCH_MODE),
            link_extractor=LINK_EXTRACTOR,
            poll_delays_ms=POLL_DELAYS_MS,
            gallery_extractor=GALLERY_SELECTOR,
            secrets=session_state.secrets,
        )

    # --- Upload Implementation (Go sidecar handles uploads) ---

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
