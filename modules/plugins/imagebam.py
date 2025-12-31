# modules/plugins/imagebam.py
"""
ImageBam.com plugin - Schema-based implementation.

Python-based upload plugin with session management and CSRF token handling.
"""

import os
from typing import Dict, Any, List
from .base import ImageHostPlugin
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
            "implementation": "python",
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

    # --- Upload Implementation (Unchanged from original) ---

    def initialize_session(
        self, config: Dict[str, Any], creds: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Initialize upload session for ImageBam.

        Handles login and CSRF token acquisition.
        """
        client = api.create_resilient_client()
        context = {"client": client, "csrf": None, "cookies": None}

        user = creds.get("imagebam_user")
        pwd = creds.get("imagebam_pass")
        if user and pwd:
            api.imagebam_login(user, pwd, client=client)

        token, cookies = api.init_imagebam_session(client)
        if token:
            context["csrf"] = token
            context["cookies"] = cookies
        else:
            logger.error("Failed to get ImageBam CSRF token")
        return context

    def prepare_group(
        self, group, config: Dict[str, Any], context: Dict[str, Any], creds: Dict[str, Any]
    ) -> None:
        """
        Prepare group for upload.

        ImageBam requires a session token (upload_token) per group.
        """
        if context.get("csrf"):
            try:
                # Using main client from context
                token_client = context["client"]

                # Logic from old upload_manager:
                gal_title = group.title if config.get("auto_gallery") else None
                gal_id = "default"

                upload_token = api.get_imagebam_upload_token(
                    token_client,
                    context["csrf"],
                    config.get("content_type", "Safe"),
                    config.get("thumbnail_size", "180"),
                    gal_id,
                    gal_title,
                )
                group.ib_upload_token = upload_token
                logger.info(f"Got ImageBam upload token for group: {group.title}")
            except Exception as e:
                logger.error(f"ImageBam Token Error: {e}")

    def upload_file(
        self, file_path: str, group, config: Dict[str, Any], context: Dict[str, Any], progress_callback
    ):
        """
        Upload a single file to ImageBam.

        Args:
            file_path: Path to image file
            group: Group object containing files
            config: Plugin configuration from UI
            context: Session context from initialize_session
            progress_callback: Function to report upload progress

        Returns:
            Tuple of (viewer_url, thumb_url)
        """
        client = context["client"]
        token = getattr(group, "ib_upload_token", None)
        if not token:
            raise ValueError("Upload skipped: No ImageBam Upload Token")

        uploader = api.ImageBamUploader(
            file_path,
            os.path.basename(file_path),
            lambda m: progress_callback(m.bytes_read / m.len) if m.len > 0 else None,
            config["content_type"],
            config["thumbnail_size"],
            upload_token=token,
            csrf_token=context["csrf"],
            session_cookies=context["cookies"],
            client=client,
        )

        try:
            url, data, headers = uploader.get_request_params()
            if "Content-Length" not in headers and hasattr(data, "len"):
                headers["Content-Length"] = str(data.len)
            r = client.post(url, headers=headers, data=data, timeout=300)
            return uploader.parse_response(r.json())
        finally:
            uploader.close()
