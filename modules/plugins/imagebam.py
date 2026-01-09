# modules/plugins/imagebam.py
"""
ImageBam.com plugin - Schema-based implementation with Go sidecar uploads.

Go-based upload plugin (upload handled by Go sidecar).
Python side manages UI and configuration validation.
"""

import os
from typing import Dict, Any, List
from .base import ImageHostPlugin
from . import helpers
from .. import api
from loguru import logger


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
            "version": "2.0.0",
            "author": "Connie's Uploader Team",
            "description": "Upload images to ImageBam.com with optional authentication and CSRF-protected uploads",
            "website": "https://imagebam.com",
            "implementation": "go",
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
        ]

    # NEW: Generic HTTP request builder with complex session management (Phase 3)
    def build_http_request(self, file_path: str, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build HTTP request specification for ImageBam upload with complex session management.
        Uses Phase 3 multi-step pre-request hooks (4 steps):
        1. GET /auth/login to get login CSRF token
        2. POST /auth/login with credentials and CSRF
        3. GET / to get API CSRF token
        4. POST /upload/session to get upload token (requires CSRF header)
        """
        # Map content type and thumbnail size
        content_type_map = {"Safe": "1", "Adult": "0"}
        thumb_size_map = {"100": "1", "180": "2", "250": "3", "300": "4"}

        content_type_id = content_type_map.get(config.get("content_type", "Safe"), "1")
        thumb_size_id = thumb_size_map.get(config.get("thumbnail_size", "180"), "2")

        # Check if credentials are provided
        has_credentials = bool(creds.get("imagebam_user") and creds.get("imagebam_pass"))

        # Build complex 4-step pre-request chain
        pre_request_spec = None

        if has_credentials:
            # Step 1: GET login page to extract CSRF token
            pre_request_spec = {
                "action": "get_login_csrf",
                "url": "https://www.imagebam.com/auth/login",
                "method": "GET",
                "headers": {},
                "form_fields": {},
                "use_cookies": True,
                "extract_fields": {
                    "login_token": "input[name='_token']"  # Extract CSRF token from login form
                },
                "response_type": "html",
                # Step 2: POST login with extracted CSRF
                "follow_up_request": {
                    "action": "submit_login",
                    "url": "https://www.imagebam.com/auth/login",
                    "method": "POST",
                    "headers": {},
                    "form_fields": {
                        "_token": "{login_token}",  # Will be substituted with extracted value
                        "email": creds.get("imagebam_user", ""),
                        "password": creds.get("imagebam_pass", ""),
                        "remember": "on"
                    },
                    "use_cookies": True,
                    "extract_fields": {},
                    "response_type": "html",
                    # Step 3: GET homepage to extract API CSRF token
                    "follow_up_request": {
                        "action": "get_api_csrf",
                        "url": "https://www.imagebam.com/",
                        "method": "GET",
                        "headers": {},
                        "form_fields": {},
                        "use_cookies": True,
                        "extract_fields": {
                            "csrf_token": "meta[name='csrf-token']"  # Extract CSRF for API
                        },
                        "response_type": "html",
                        # Step 4: POST to get upload session token
                        "follow_up_request": {
                            "action": "get_upload_token",
                            "url": "https://www.imagebam.com/upload/session",
                            "method": "POST",
                            "headers": {
                                "X-Requested-With": "XMLHttpRequest",
                                "X-CSRF-TOKEN": "{csrf_token}",  # Use extracted CSRF
                                "Content-Type": "application/x-www-form-urlencoded"
                            },
                            "form_fields": {
                                "content_type": content_type_id,
                                "thumbnail_size": thumb_size_id
                            },
                            "use_cookies": True,
                            "extract_fields": {
                                "upload_token": "data"  # Extract upload token from JSON response
                            },
                            "response_type": "json"
                        }
                    }
                }
            }

        return {
            "url": "https://www.imagebam.com/upload",
            "method": "POST",
            "headers": {},
            "pre_request": pre_request_spec,
            "multipart_fields": {
                "files[0]": {"type": "file", "value": file_path},
                "upload_session": {"type": "dynamic", "value": "upload_token"},  # Use extracted upload token
            },
            "response_parser": {
                "type": "json",
                "url_path": "files.0.sourceUrl",  # ImageBam response: {"files":[{"sourceUrl":"...","thumbUrl":"..."}]}
                "thumb_path": "files.0.thumbUrl"
            }
        }

    # --- Upload Implementation (Go sidecar handles uploads) ---

    def initialize_session(
        self, config: Dict[str, Any], creds: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Stub - Go sidecar handles session initialization."""
        return {}

    def prepare_group(
        self, group, config: Dict[str, Any], context: Dict[str, Any], creds: Dict[str, Any]
    ) -> None:
        """Stub - Go sidecar handles session via build_http_request()."""
        pass

    def upload_file(
        self, file_path: str, group, config: Dict[str, Any], context: Dict[str, Any], progress_callback
    ):
        """Stub - Go sidecar handles file uploads via build_http_request()."""
        pass
