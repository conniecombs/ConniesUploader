# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/plugins/imagebam.py
"""
ImageBam.com plugin - Schema-based implementation with Go sidecar uploads.

Go-based upload plugin (upload handled by Go sidecar).
Python side manages UI and configuration validation.
"""

from typing import Dict, Any, List
from .base import ImageHostPlugin
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
            "version": "3.1.0",
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
        content_type_map = {"Safe": "sfw", "Adult": "nsfw"}
        thumb_size_map = {"100": "1", "180": "2", "250": "3", "300": "4"}

        content_type_id = content_type_map.get(config.get("content_type", "Safe"), "sfw")
        thumb_size_value = str(config.get("thumbnail_size", "180"))
        thumb_size_id = thumb_size_map.get(thumb_size_value, "2")
        session_fields = self._session_form_fields(config, content_type_id, thumb_size_id)

        pre_request_spec = self._build_pre_request(session_fields, creds)

        return {
            "url": "https://www.imagebam.com/upload",
            "method": "POST",
            "headers": {
                "Accept": "application/json",
                "Cache-Control": "no-cache",
                "Referer": "https://www.imagebam.com/",
                "X-Requested-With": "XMLHttpRequest",
            },
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
            "response_parser": {
                "type": "json",
                "url_path": "success",
                "thumb_path": "",
            },
            "resolve_spec": {
                "result_url": "{url}",
                "poll_delays_ms": [1000, 2000, 4000],
                "link_extractor": (
                    r"\[URL=(?P<image_url>https://www\.imagebam\.com/view/[^\]]+)"
                    r"\]\[IMG\](?P<thumb_url>https://thumbs\d+\.imagebam\.com/[^\]]+)"
                    r"\[/IMG\]\[/URL\]"
                ),
                "gallery_extractor": "a#gallery-name",
                "file_match_mode": "single",
            },
        }

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
    def _upload_session_request(session_fields: Dict[str, str]) -> Dict[str, Any]:
        return {
            "action": "get_upload_token",
            "url": "https://www.imagebam.com/upload/session",
            "method": "POST",
            "headers": {
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRF-TOKEN": "{csrf_token}",
                "Accept": "application/json",
                "Referer": "https://www.imagebam.com/",
            },
            "form_fields": session_fields,
            "use_cookies": True,
            "extract_fields": {
                "upload_token": "data",
                "imagebam_session": "session",
            },
            "response_type": "json",
        }

    def _build_pre_request(self, session_fields: Dict[str, str], creds: Dict[str, Any]) -> Dict[str, Any]:
        upload_session = self._upload_session_request(session_fields)
        get_api_csrf = {
            "action": "get_api_csrf",
            "url": "https://www.imagebam.com/",
            "method": "GET",
            "headers": {},
            "form_fields": {},
            "use_cookies": True,
            "extract_fields": {
                "csrf_token": "meta[name='csrf-token']",
            },
            "response_type": "html",
            "follow_up_request": upload_session,
        }

        if not (creds.get("imagebam_user") and creds.get("imagebam_pass")):
            return get_api_csrf

        return {
            "action": "get_login_csrf",
            "url": "https://www.imagebam.com/auth/login",
            "method": "GET",
            "headers": {},
            "form_fields": {},
            "use_cookies": True,
            "extract_fields": {
                "login_token": "input[name='_token']",
            },
            "response_type": "html",
            "follow_up_request": {
                "action": "submit_login",
                "url": "https://www.imagebam.com/auth/login",
                "method": "POST",
                "headers": {
                    "Referer": "https://www.imagebam.com/auth/login",
                },
                "form_fields": {
                    "_token": "{login_token}",
                    "email": creds.get("imagebam_user", ""),
                    "password": creds.get("imagebam_pass", ""),
                    "remember": "on",
                },
                "use_cookies": True,
                "extract_fields": {
                    "imagebam_login_marker": "form[action*='logout']",
                },
                "response_type": "html",
                "follow_up_request": get_api_csrf,
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
