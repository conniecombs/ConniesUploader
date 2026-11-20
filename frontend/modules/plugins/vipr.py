# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/plugins/vipr.py
"""
Vipr.im plugin - Schema-based implementation with custom UI elements.

Uploads run through the Go sidecar's transport; this plugin logs in on the
upload job's session, builds each upload request, posts Vipr's upload result
form back and reads the links from the result page (the Python upload path).
Includes custom gallery refresh button functionality.
"""

import re
import threading
from typing import Dict, Any, List

import customtkinter as ctk
from bs4 import BeautifulSoup
from .base import ImageHostPlugin
from . import helpers
from .. import api
from ..credentials_manager import CredentialsManager
from ..upload_results import (
    UploadResult,
    collapse_text,
    html_field,
    redact_secrets,
    request_failure,
    resolve_upload_url,
    truncate_text,
    upload_failure,
)
from ..widgets import MouseWheelComboBox
from loguru import logger

# Vipr's site. Login, the home page and the upload result form all live here;
# the upload itself goes to the endpoint the home page's upload form names.
BASE_URL = "https://vipr.im/"

# How Vipr's pages are read; shared by the legacy spec and the Python path.
# The home page's upload form carries the session id (filled only when
# logged in) and the upload server.
SESS_ID_SELECTOR = "input[name='sess_id']"
ENDPOINT_SELECTOR = r"regex:<form[^>]+action=[\"']([^\"']+/cgi-bin/upload\.cgi)\?upload_id="
# The upload answers with a form (XFileSharing's upload result) that is posted
# back to the site to get the result page with the BBCode.
RESULT_FORM_FIELDS = {
    "fn": "textarea[name='fn']",
    "st": "textarea[name='st']",
    "op": "textarea[name='op']",
    "per_row": "textarea[name='per_row']",
}
URL_SELECTOR = r"regex:(?is)\[URL=(https?://vipr\.im/[^\]\s]+)\]\s*\[IMG\]"
THUMB_SELECTOR = r"regex:(?is)\[IMG\](https?://[^\[]+?)\[/IMG\]"
UPLOAD_QUERY = "js_on=1&utype=reg&upload_type=file"

# Where Vipr's login page shows why a login was refused (XFileSharing
# templates), and the wording of a refusal shown anywhere else.
_LOGIN_ERROR_SELECTORS = ".err, .error, .alert-danger, .alert-error, #error, .errors"
_LOGIN_ERROR_TEXT = re.compile(
    r"\b(incorrect|invalid|wrong|failed|banned|blocked)\b.*\b(login|password|username|user|account)\b"
    r"|\b(login|password|username|account)\b.*\b(incorrect|invalid|wrong|failed|banned|blocked)\b",
    re.I,
)
LOGIN_HINT = "Check the saved username and password."


def resolved_upload_url(upload_id: str, endpoint: str = "") -> str:
    """The upload URL for one file: the home page's upload endpoint with Vipr's query.

    Resolves the endpoint against the default upload URL and keeps that
    URL's query when the endpoint has none, as the legacy sidecar did.
    """
    return resolve_upload_url(
        f"{BASE_URL}cgi-bin/upload.cgi?upload_id={upload_id}&{UPLOAD_QUERY}", endpoint
    )


def login_refusal(body: str) -> str:
    """The reason Vipr's login answer gives for refusing the login, or ""."""
    soup = BeautifulSoup(str(body or ""), "html.parser")
    for element in soup.select(_LOGIN_ERROR_SELECTORS):
        text = collapse_text(element.get_text(" "))
        if text:
            return text
    for tag in soup(["script", "style", "noscript", "template", "head"]):
        tag.decompose()
    for line in soup.stripped_strings:
        text = collapse_text(line)
        if len(text) <= 200 and _LOGIN_ERROR_TEXT.search(text):
            return text
    return ""


def _sentence(text: str) -> str:
    return text if text.endswith((".", "!", "?", "…")) else f"{text}."


class ViprPlugin(ImageHostPlugin):
    """Vipr.im image hosting plugin using schema-based UI with custom elements."""

    def __init__(self):
        self.vipr_galleries_map = {}
        self.vipr_gallery_urls_map = {}
        self.cb_gallery = None

    @property
    def id(self) -> str:
        return "vipr.im"

    @property
    def name(self) -> str:
        return "Vipr.im"

    @property
    def metadata(self) -> Dict[str, Any]:
        """Plugin metadata for Vipr.im"""
        return {
            "version": "3.2.0",
            "author": "Connie's Uploader Team",
            "description": "Upload images to Vipr.im with dynamic gallery selection, cover support, and API-based uploads",
            "website": "https://vipr.im",
            "implementation": "python",  # Python upload path; the sidecar is its transport
            "features": {
                "galleries": True,
                "covers": True,
                "authentication": "required",
                "direct_links": True,
                "custom_thumbnails": True,
                "dynamic_galleries": True,  # Fetches user galleries via API
            },
            "credentials": [
                {
                    "key": "vipr_user",
                    "label": "Username",
                    "required": True,
                    "description": "Vipr.im username for uploads and gallery access",
                },
                {
                    "key": "vipr_pass",
                    "label": "Password",
                    "required": True,
                    "secret": True,
                    "description": "Vipr.im password",
                },
            ],
            "limits": {
                "max_file_size": 50 * 1024 * 1024,  # 50MB
                "allowed_formats": [".jpg", ".jpeg", ".png", ".gif", ".webp"],
                "rate_limit": "API rate limited",
                "max_resolution": (15000, 15000),
                "min_resolution": (1, 1),
            },
        }

    @property
    def settings_schema(self) -> List[Dict[str, Any]]:
        """Declarative UI schema for Vipr settings."""
        return [
            {
                "type": "dropdown",
                "key": "thumbnail_size",
                "label": "Thumbnail Size",
                "values": [
                    "100x100",
                    "170x170",
                    "250x250",
                    "300x300",
                    "350x350",
                    "500x500",
                    "800x800",
                ],
                "default": "170x170",
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
        ]

    def validate_configuration(self, config: Dict[str, Any]) -> List[str]:
        """Custom validation for Vipr configuration."""
        errors = []

        # Convert cover_count to int (using helper)
        helpers.validate_cover_count(config, errors)

        # Get gallery ID from map
        gal_name = config.get("vipr_gallery_name", "")
        gal_id = self.vipr_galleries_map.get(gal_name, "0")
        config["vipr_gal_id"] = gal_id
        gallery_url = self.vipr_gallery_urls_map.get(gal_name, "")
        if gallery_url:
            config["vipr_gallery_url"] = gallery_url
            config["selected_gallery_url"] = gallery_url

        return errors

    def render_settings(self, parent: ctk.CTkFrame, current_settings: Dict[str, Any]):
        """
        Custom render to include gallery refresh button.

        This overrides the auto-generated render to add custom UI elements
        that can't be expressed in schema (interactive button + dynamic dropdown).
        """
        # First, render the schema-based fields
        from .schema_renderer import SchemaRenderer

        renderer = SchemaRenderer()
        ui_vars = renderer.render(parent, self.settings_schema, current_settings)

        # Add custom gallery selection UI
        ctk.CTkLabel(parent, text="─" * 40, text_color="gray").pack(pady=5)

        ctk.CTkButton(
            parent,
            text="🔄 Refresh Galleries / Login",
            command=lambda: self._refresh_galleries(parent),
        ).pack(fill="x", pady=10)

        # Gallery dropdown (dynamically populated)
        gal_name = current_settings.get("vipr_gallery_name", "None")
        ui_vars["vipr_gallery_name"] = ctk.StringVar(value=gal_name)

        self.cb_gallery = MouseWheelComboBox(
            parent, variable=ui_vars["vipr_gallery_name"], values=["None"]
        )
        self.cb_gallery.pack(fill="x")

        return ui_vars

    def get_configuration(self, ui_handle: Any) -> Dict[str, Any]:
        """
        Custom extraction to handle gallery name → ID mapping.
        """
        # Use schema renderer for standard fields
        from .schema_renderer import SchemaRenderer, ValidationError

        renderer = SchemaRenderer()
        config, errors = renderer.extract_config(ui_handle, self.settings_schema)

        # Add gallery name (custom field)
        if "vipr_gallery_name" in ui_handle:
            gal_name = ui_handle["vipr_gallery_name"].get()
            config["vipr_gallery_name"] = gal_name

            # Map gallery name to ID
            gal_id = self.vipr_galleries_map.get(gal_name, "0")
            config["vipr_gal_id"] = gal_id
            gallery_url = self.vipr_gallery_urls_map.get(gal_name, "")
            if gallery_url:
                config["vipr_gallery_url"] = gallery_url
                config["selected_gallery_url"] = gallery_url

        # Add custom validation
        custom_errors = self.validate_configuration(config)
        if custom_errors:
            errors.extend(custom_errors)

        # Raise if validation failed
        if errors:
            raise ValidationError(errors)

        return config

    def _refresh_galleries(self, parent_widget) -> None:
        """
        Fetch galleries from Vipr API and update dropdown.

        This is the custom functionality that can't be expressed in schema.
        """
        creds = self._load_vipr_credentials()
        if not creds["vipr_user"] or not creds["vipr_pass"]:
            logger.warning("Vipr credentials not found in keyring")
            return

        def _task():
            try:
                # Use the API wrapper which now calls the Go Sidecar
                meta = api.get_vipr_metadata(creds)
                galleries = (meta.get("galleries") if meta else None) or []
                self.vipr_galleries_map = {
                    g["name"]: g["id"] for g in galleries if g.get("name") and g.get("id")
                }
                self.vipr_gallery_urls_map = {
                    g["name"]: g.get("url", "") for g in galleries if g.get("name") and g.get("url")
                }
                names = ["None"] + list(self.vipr_galleries_map.keys())
                self._set_gallery_options(parent_widget, names)

                if self.vipr_galleries_map:
                    logger.info(f"Loaded {len(self.vipr_galleries_map)} Vipr galleries")
                else:
                    logger.warning("No galleries found or login failed")
            except Exception as e:
                logger.error(f"Vipr Refresh Error: {e}")

        threading.Thread(target=_task, daemon=True).start()

    @staticmethod
    def _load_vipr_credentials() -> Dict[str, str]:
        """Load Vipr credentials through the same keyring schema used by the dialog."""
        creds = CredentialsManager.load_all_credentials()
        return {
            "vipr_user": (creds.get("vipr_user") or "").strip(),
            "vipr_pass": (creds.get("vipr_pass") or "").strip(),
        }

    def _set_gallery_options(self, parent_widget, names: List[str]) -> None:
        def _apply():
            if self.cb_gallery is None:
                return
            self.cb_gallery.configure(values=names)
            try:
                if self.cb_gallery.get() not in names:
                    self.cb_gallery.set("None")
            except Exception as exc:
                logger.debug(f"Could not normalize Vipr gallery selection: {exc}")

        try:
            parent_widget.after(0, _apply)
        except Exception as exc:
            logger.debug(f"Could not schedule Vipr gallery dropdown update: {exc}")

    def prepare_group(
        self, group, config: Dict[str, Any], context: Dict[str, Any], creds: Dict[str, Any]
    ) -> None:
        """Create one Vipr folder per batch when auto-gallery is enabled."""
        if not config.get("auto_gallery"):
            return

        clean_title = (
            str(getattr(group, "title", "") or "Gallery").replace("[", "").replace("]", "").strip()
        )
        new_data = api.create_vipr_gallery(creds, clean_title)
        if not new_data:
            logger.warning(
                f"Failed to create Vipr gallery for: {getattr(group, 'title', clean_title)}"
            )
            return

        group.gallery_id = new_data.get("id") or new_data.get("gallery_id") or ""
        group.gallery_name = new_data.get("name") or new_data.get("gallery_name") or clean_title
        group.gallery_url = new_data.get("url") or new_data.get("gallery_url") or ""
        group.gallery_service = self.id
        config["vipr_gal_id"] = group.gallery_id
        config["vipr_gallery_name"] = group.gallery_name
        if group.gallery_url:
            config["vipr_gallery_url"] = group.gallery_url
            config["selected_gallery_url"] = group.gallery_url
        logger.info(f"Created Vipr gallery: {group.gallery_name} ({group.gallery_id})")

    # NEW: Generic HTTP request builder with session management (Phase 3)
    def build_http_request(
        self, file_path: str, config: Dict[str, Any], creds: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build HTTP request specification for Vipr.im upload with session management.
        Uses Phase 3 multi-step pre-request hooks:
        1. POST to / (sets cookies)
        2. GET / (extracts sess_id using cookies from step 1)

        Login runs once per multi-file job in the Go sidecar; each concurrent
        file then reuses that session with a unique {{upload_id}}.

        This is the ``legacy_upload_parsing`` fallback; the Python path
        (open_upload_session, build_raw_upload_request, parse_upload_response)
        sends the same requests and reads the answers the same way.
        """
        # Per-file upload_id is substituted by the Go sidecar ({upload_id}) so
        # concurrent workers each get a unique XFS upload slot while sharing
        # the once-per-job login session.
        base_endpoint = f"{BASE_URL}cgi-bin/upload.cgi"
        upload_url = f"{base_endpoint}?upload_id={{upload_id}}&{UPLOAD_QUERY}"
        gallery_id = self._gallery_id_from_config(config)

        return {
            "url": upload_url,
            "method": "POST",
            "headers": {},
            "pre_request": {
                "action": "login_step1",
                "url": BASE_URL,
                "method": "POST",
                "headers": {},
                "form_fields": {
                    "op": "login",
                    "login": creds.get("vipr_user", ""),
                    "password": creds.get("vipr_pass", ""),
                },
                "use_cookies": True,  # Set session cookies
                "extract_fields": {},  # No extraction from login POST
                "response_type": "html",
                # Step 2: GET homepage to extract session ID
                "follow_up_request": {
                    "action": "login_step2",
                    "url": BASE_URL,
                    "method": "GET",
                    "headers": {},
                    "form_fields": {},
                    "use_cookies": True,  # Use cookies from step 1
                    "extract_fields": {
                        "sess_id": SESS_ID_SELECTOR,  # Extract session ID
                        "endpoint": ENDPOINT_SELECTOR,
                    },
                    "response_type": "html",
                },
            },
            "multipart_fields": {
                "file_0": {"type": "file", "value": file_path},
                "upload_type": {"type": "text", "value": "file"},
                "sess_id": {"type": "dynamic", "value": "sess_id"},  # Use extracted session ID
                "thumb_size": {
                    "type": "text",
                    "value": str(config.get("thumbnail_size", "170x170")),
                },
                "per_row": {"type": "text", "value": str(config.get("per_row", "750"))},
                "sdomain": {"type": "text", "value": str(config.get("sdomain", "vipr.im"))},
                "fld_id": {"type": "text", "value": gallery_id},
                "tos": {"type": "text", "value": "1"},
                "submit_btn": {"type": "text", "value": "Upload"},
            },
            "response_parser": {
                "type": "html",
                "follow_up_request": {
                    "url": BASE_URL,
                    "method": "POST",
                    "response_type": "html",
                    "extract_fields": dict(RESULT_FORM_FIELDS),
                    "form_fields": {
                        "fn": "{fn}",
                        "st": "{st}",
                        "op": "{op}",
                        "per_row": "{per_row}",
                    },
                },
                "url_path": URL_SELECTOR,
                "thumb_path": THUMB_SELECTOR,
            },
        }

    # --- Python upload path ---

    def open_upload_session(
        self, transport, config: Dict[str, Any], creds: Dict[str, Any]
    ) -> Dict[str, str]:
        """Log in on the job's session and read the upload form's session id and server.

        The legacy pre_request chain: POST the login form to /, then GET / and
        read ``sess_id`` and the upload endpoint. Vipr answers a login with
        HTTP 200 whether or not the password is right; only a filled
        ``sess_id`` means the session is logged in. Raises with Vipr's own
        message when it refuses the login.
        """
        user = str(creds.get("vipr_user", "") or "")
        password = str(creds.get("vipr_pass", "") or "")
        secrets = [user, password]
        if not user.strip() or not password.strip():
            raise RuntimeError(
                "Vipr.im uploads need a username and password. Set them in Credentials."
            )
        login = transport.post(BASE_URL, {"op": "login", "login": user, "password": password})
        if not login.ok:
            raise RuntimeError(request_failure("Vipr.im login failed", login, secrets))
        home = transport.get(BASE_URL)
        if not home.ok:
            raise RuntimeError(
                request_failure("could not open Vipr.im's upload page", home, secrets)
            )
        sess_id = html_field(home.body, SESS_ID_SELECTOR)
        if not sess_id:
            reason = truncate_text(redact_secrets(login_refusal(login.body), secrets))
            if reason:
                raise RuntimeError(f"Vipr.im login failed: {_sentence(reason)} {LOGIN_HINT}")
            raise RuntimeError(f"Vipr.im login failed: no upload session after login. {LOGIN_HINT}")
        endpoint = html_field(home.body, ENDPOINT_SELECTOR)
        if not endpoint:
            raise RuntimeError(
                upload_failure(
                    "Vipr.im's home page has no upload form",
                    home.status_code,
                    home.body,
                    secrets + [sess_id],
                )
            )
        return {"sess_id": sess_id, "endpoint": endpoint}

    def build_raw_upload_request(
        self,
        file_path: str,
        config: Dict[str, Any],
        session_values: Dict[str, str],
        creds: Dict[str, Any],
    ) -> Dict[str, Any]:
        """The legacy spec's upload with the session's values and this file's upload id."""
        sess_id = str(session_values.get("sess_id") or "")
        if not sess_id:
            raise ValueError("no Vipr.im upload session")
        spec = self.build_http_request(file_path, config, creds)
        fields = {}
        for name, field in spec["multipart_fields"].items():
            if field["type"] == "dynamic":  # sess_id
                field = {"type": "text", "value": str(session_values.get(field["value"], ""))}
            fields[name] = dict(field)
        values = helpers.per_file_upload_values(file_path)
        return {
            "url": resolved_upload_url(values["upload_id"], session_values.get("endpoint", "")),
            "method": spec["method"],
            "headers": dict(spec["headers"]),
            "multipart_fields": fields,
        }

    def parse_upload_response(
        self, file_path, response, transport, session_values, session_state
    ) -> UploadResult:
        """Post the upload's result form back to Vipr and read the BBCode links.

        The legacy response_parser: the upload answers with a form of
        ``fn``/``st``/``op``/``per_row`` textareas, which is posted to /; the
        result page's ``[URL=…][IMG]…[/IMG]`` gives the viewer link and the
        thumbnail.
        """
        secrets = session_state.secrets
        if not getattr(response, "ok", True):
            return UploadResult.failed(request_failure("upload failed", response, secrets))
        status = int(response.status_code or 0)
        body = str(response.body or "")
        if not 200 <= status < 300:
            return UploadResult.failed(upload_failure("upload rejected", status, body, secrets))

        form = {name: html_field(body, selector) for name, selector in RESULT_FORM_FIELDS.items()}
        if not all(form.values()):
            refusal = form["st"]
            if refusal and refusal.upper() != "OK":
                # XFileSharing reports a refused file in st and leaves fn empty.
                return UploadResult.failed(
                    upload_failure("upload refused", status, refusal, secrets)
                )
            return UploadResult.failed(
                upload_failure("upload response had no result form", status, body, secrets)
            )

        # One attempt, as on the legacy path: a refusal quotes the host's message.
        result_page = transport.post(BASE_URL, form, retry=False)
        if not result_page.ok:
            return UploadResult.failed(request_failure("response follow-up", result_page, secrets))
        url = html_field(result_page.body, URL_SELECTOR)
        if not url:
            return UploadResult.failed(
                upload_failure(
                    "upload response had no image link", status, result_page.body, secrets
                )
            )
        return UploadResult(url=url, thumb=html_field(result_page.body, THUMB_SELECTOR))

    @staticmethod
    def _gallery_id_from_config(config: Dict[str, Any]) -> str:
        # A batch's own gallery first, then the gallery chosen in the dropdown.
        for key in ("gallery_id", "vipr_gal_id", "vipr_gallery_id"):
            value = str(config.get(key) or "").strip()
            if value and value not in {"0", "None"}:
                return value
        # A Gallery Manager pick only fills in a dropdown gallery whose id is
        # not known yet (before a refresh); "None" in the dropdown means none.
        gallery_name = str(config.get("vipr_gallery_name") or "").strip()
        if "vipr_gallery_name" not in config or gallery_name not in {"", "None"}:
            value = str(config.get("selected_gallery_id") or "").strip()
            if value and value not in {"0", "None"}:
                return value
        return "0"

    # Go-based upload - stubs for abstract methods (uploads handled by Go sidecar)
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
        """Stub - Go sidecar handles file uploads."""
        pass
