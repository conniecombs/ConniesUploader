# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/plugins/turbo.py
"""
TurboImageHost plugin - Schema-based implementation with Go sidecar uploads.

Go-based upload plugin (upload handled by Go sidecar).
Python side manages UI, configuration validation, and optional authentication.
"""

import re
import secrets
import string
from typing import Dict, Any, List, Optional
from .base import ImageHostPlugin
from . import helpers


class TurboPlugin(ImageHostPlugin):
    """TurboImageHost image hosting plugin using schema-based UI."""

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
            "version": "BleedingEdge",
            "author": "Connie's Uploader Team",
            "description": "Upload images to TurboImageHost with optional authentication, dynamic endpoint configuration, and cover image support",
            "website": "https://www.turboimagehost.com",
            "implementation": "go",
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
                "values": ["150", "200", "250", "300", "350", "400", "500", "600"],
                "default": "180",
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
        group.turbo_gallery_create = True
        group.turbo_gallery_name = gallery_name
        group.turbo_upload_id = upload_id
        group.gallery_name = gallery_name
        group.gallery_service = self.id

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
        import os

        upload_id = config.get("turbo_upload_id") or config.get("upload_id") or self._upload_id()

        file_size = 0
        try:
            file_size = os.path.getsize(file_path)
        except OSError:
            pass

        # Map content type.
        raw_content = (config.get("content_type") or "all").lower()
        content_value = "adult" if raw_content in ("adult", "18", "true") else "all"

        # Thumbnail size.
        thumb_size = config.get("thumbnail_size") or config.get("turbo_thumb") or "150"

        # Build multipart fields.
        multipart_fields = {
            "qqfile": {"type": "file", "value": file_path},
            "upload_id": {"type": "text", "value": upload_id},
            "qquuid": {"type": "text", "value": self._upload_id()},
            "qqfilename": {"type": "text", "value": "{filename}"},
            "qqtotalfilesize": {"type": "text", "value": str(file_size)},
            "imcontent": {"type": "text", "value": content_value},
            "thumb_size": {"type": "text", "value": str(thumb_size)},
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
            gallery_id = (
                config.get("turbo_gallery_id") or config.get("gallery_id") or ""
            ).strip()
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
                "url": "https://www.turboimagehost.com/login.tu?",
                "method": "POST",
                "form_fields": {
                    "username": username,
                    "password": creds.get("turbo_pass", ""),
                    "remember": "y",
                    "login": "Login",
                },
                "use_cookies": True,
                "response_type": "html",
                "extract_fields": {},
                "follow_up_request": {
                    "action": "turbo_discover_endpoint",
                    "url": "https://www.turboimagehost.com/",
                    "method": "GET",
                    "use_cookies": True,
                    "response_type": "html",
                    "extract_fields": {
                        "endpoint": "regex:endpoint:\\s*'([^']+)'",
                    },
                },
            }
        else:
            # No login, just discover the upload endpoint.
            pre_request = {
                "action": "turbo_discover_endpoint",
                "url": "https://www.turboimagehost.com/",
                "method": "GET",
                "use_cookies": True,
                "response_type": "html",
                "extract_fields": {
                    "endpoint": "regex:endpoint:\\s*'([^']+)'",
                },
            }

        return {
            "url": "https://www.turboimagehost.com/upload_html5.tu",
            "method": "POST",
            "headers": {
                "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
                "Referer": "https://www.turboimagehost.com/",
            },
            "multipart_fields": multipart_fields,
            "pre_request": pre_request,
            "response_parser": {
                "type": "json",
                "url_path": "newUrl",
                "thumb_path": "",
                "status_path": "success",
                "success_value": "true",
                "url_template": "https://www.turboimagehost.com/p/{id}/{filename}.html",
            },
            "resolve_spec": {
                "result_url": "{url}",
                "poll_delays_ms": [500, 1000, 2000, 3000, 5000, 5000],
                "link_extractor": (
                    r"(?is)\[url=(?P<image_url>https?://[^\]]+?/p/[0-9]+/"
                    r"(?P<filename>[^/\]]+?)\.html)\]\s*"
                    r"\[img\](?P<thumb_url>https?://[^\]]+?)\[/img\]\s*\[/url\]"
                ),
                "gallery_extractor": "input#imgCodeGG",
                "file_match_mode": "filename",
            },
        }

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
