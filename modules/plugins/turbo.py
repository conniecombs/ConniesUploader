# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/plugins/turbo.py
"""
TurboImageHost plugin - Schema-based implementation with Go sidecar uploads.

Go-based upload plugin (upload handled by Go sidecar).
Python side manages UI, configuration validation, and optional authentication.
"""

import os
from typing import Dict, Any, List
from .base import ImageHostPlugin
from . import helpers
from .. import api
from loguru import logger


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
            "version": "2.0.0",
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
                "max_file_size": 50 * 1024 * 1024,  # 50MB
                "allowed_formats": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"],
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
                "type": "label",
                "text": "ℹ️ Login Optional",
                "color": "orange",
            },
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
                    {"type": "label", "text": "Cover Images:", "width": 100},
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
            },
            {
                "type": "separator",
            },
            {
                "type": "text",
                "key": "gallery_id",
                "label": "Gallery ID (Optional)",
                "default": "",
                "placeholder": "Leave blank for auto-gallery",
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

    # NEW: Generic HTTP request builder with session management (Phase 3)
    def build_http_request(
        self, file_path: str, config: Dict[str, Any], creds: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build HTTP request specification for TurboImageHost upload with session management.
        Uses Phase 3 multi-step pre-request hooks:
        1. Optional POST to /login (if credentials provided)
        2. GET / to extract upload endpoint from JavaScript
        """
        import os
        import random
        import string

        # Get file size for query parameters
        try:
            file_size = os.path.getsize(file_path)
        except OSError as e:
            logger.warning(f"Could not get file size for {file_path}: {e}")
            file_size = 0

        # Generate random upload ID
        upload_id = "".join(random.choices(string.ascii_letters + string.digits, k=12))

        # Base endpoint (will be overridden by extracted endpoint)
        base_endpoint = "https://www.turboimagehost.com/upload_html5.tu"

        # Build upload URL with query parameters
        upload_url = f"{base_endpoint}?upload_id={upload_id}&js_on=1&utype=reg&upload_type=file"

        # Check if credentials are provided
        has_credentials = bool(creds.get("turbo_user") and creds.get("turbo_pass"))

        # Build pre-request spec
        pre_request_spec = {
            "action": "get_endpoint",
            "url": "https://www.turboimagehost.com/",
            "method": "GET",
            "headers": {},
            "form_fields": {},
            "use_cookies": True,
            "extract_fields": {
                "endpoint": "regex:endpoint:\\s*'([^']+)'"  # Regex pattern to extract endpoint from JavaScript
            },
            "response_type": "html",
        }

        # If credentials provided, add login step before endpoint extraction
        if has_credentials:
            pre_request_spec = {
                "action": "login",
                "url": "https://www.turboimagehost.com/login",
                "method": "POST",
                "headers": {},
                "form_fields": {
                    "username": creds.get("turbo_user", ""),
                    "password": creds.get("turbo_pass", ""),
                    "login": "Login",
                },
                "use_cookies": True,
                "extract_fields": {},  # No extraction from login POST
                "response_type": "html",
                # Step 2: GET homepage to extract upload endpoint
                "follow_up_request": {
                    "action": "get_endpoint",
                    "url": "https://www.turboimagehost.com/",
                    "method": "GET",
                    "headers": {},
                    "form_fields": {},
                    "use_cookies": True,
                    "extract_fields": {
                        "endpoint": "regex:endpoint:\\s*'([^']+)'"  # Regex to extract endpoint
                    },
                    "response_type": "html",
                },
            }

        return {
            "url": upload_url,
            "method": "POST",
            "headers": {},
            "pre_request": pre_request_spec,
            "multipart_fields": {
                "qqfile": {"type": "file", "value": file_path},
            },
            "response_parser": {
                "type": "json",
                "status_path": "success",
                "success_value": "true",
                "url_template": "https://www.turboimagehost.com/p/{id}/{filename}.html",
                # Turbo returns {"success":true,"id":"xyz"}, construct URL from ID + filename
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
