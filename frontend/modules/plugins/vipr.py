# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/plugins/vipr.py
"""
Vipr.im plugin - Schema-based implementation with custom UI elements.

Go-based upload plugin (upload handled by Go sidecar).
Includes custom gallery refresh button functionality.
"""

import threading
from typing import Dict, Any, List
import customtkinter as ctk
from .base import ImageHostPlugin
from . import helpers
from .. import api
from ..credentials_manager import CredentialsManager
from ..widgets import MouseWheelComboBox
from loguru import logger


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
            "version": "2.0.0",
            "author": "Connie's Uploader Team",
            "description": "Upload images to Vipr.im with dynamic gallery selection, cover support, and API-based uploads",
            "website": "https://vipr.im",
            "implementation": "go",
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
                    g["name"]: g.get("url", "")
                    for g in galleries
                    if g.get("name") and g.get("url")
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
            str(getattr(group, "title", "") or "Gallery")
            .replace("[", "")
            .replace("]", "")
            .strip()
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
        """
        import random
        import string

        # Generate random upload ID
        upload_id = "".join(random.choices(string.ascii_letters + string.digits, k=12))

        # Base endpoint (will be overridden if pre-request extracts custom endpoint)
        base_endpoint = "https://vipr.im/cgi-bin/upload.cgi"
        upload_url = f"{base_endpoint}?upload_id={upload_id}&js_on=1&utype=reg&upload_type=file"
        gallery_id = self._gallery_id_from_config(config)

        return {
            "url": upload_url,
            "method": "POST",
            "headers": {},
            "pre_request": {
                "action": "login_step1",
                "url": "https://vipr.im/",
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
                    "url": "https://vipr.im/",
                    "method": "GET",
                    "headers": {},
                    "form_fields": {},
                    "use_cookies": True,  # Use cookies from step 1
                    "extract_fields": {
                        "sess_id": "input[name='sess_id']",  # Extract session ID
                        "endpoint": (
                            r"regex:<form[^>]+action=[\"']"
                            r"([^\"']+/cgi-bin/upload\.cgi)\?upload_id="
                        ),
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
                "url_path": "input[name='link_url']",  # CSS selector for image URL
                "thumb_path": "input[name='thumb_url']",  # CSS selector for thumbnail URL
            },
        }

    @staticmethod
    def _gallery_id_from_config(config: Dict[str, Any]) -> str:
        for key in ("gallery_id", "selected_gallery_id", "vipr_gal_id", "vipr_gallery_id"):
            value = str(config.get(key) or "").strip()
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
