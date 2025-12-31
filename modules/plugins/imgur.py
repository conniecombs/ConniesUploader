# modules/plugins/imgur.py
"""
Imgur plugin - Schema-based implementation with Go sidecar uploads.

Go-based upload plugin (upload handled by Go sidecar).
Python side manages UI, configuration validation, and API key handling.
"""

import os
from typing import Dict, Any, List
from .base import ImageHostPlugin
from . import helpers
from .. import api
from loguru import logger


class ImgurPlugin(ImageHostPlugin):
    """Imgur image hosting plugin using schema-based UI."""

    @property
    def id(self) -> str:
        return "imgur.com"

    @property
    def name(self) -> str:
        return "Imgur"

    @property
    def metadata(self) -> Dict[str, Any]:
        """Plugin metadata for Imgur"""
        return {
            "version": "2.0.0",
            "author": "Connie's Uploader Team",
            "description": "Upload images to Imgur with anonymous or authenticated uploads, album support, and automatic thumbnail generation",
            "website": "https://imgur.com",
            "implementation": "go",
            "features": {
                "galleries": True,  # Imgur calls them "albums"
                "covers": False,  # Imgur doesn't have cover images
                "authentication": "optional",
                "direct_links": True,
                "custom_thumbnails": True,
                "anonymous_upload": True,  # Can upload without account
            },
            "credentials": [
                {
                    "key": "imgur_client_id",
                    "label": "Client ID",
                    "required": False,
                    "description": "Imgur API Client ID (optional for anonymous uploads)",
                },
                {
                    "key": "imgur_access_token",
                    "label": "Access Token",
                    "required": False,
                    "secret": True,
                    "description": "Imgur OAuth2 access token for authenticated uploads",
                },
            ],
            "limits": {
                "max_file_size": 20 * 1024 * 1024,  # 20MB for free accounts
                "allowed_formats": [".jpg", ".jpeg", ".png", ".gif", ".apng", ".tiff", ".mp4", ".webm"],
                "rate_limit": "1250 uploads per day (free account)",
                "max_resolution": (None, None),  # No specific limit
                "min_resolution": (1, 1),
            },
        }

    @property
    def settings_schema(self) -> List[Dict[str, Any]]:
        """Declarative UI schema for Imgur settings."""
        return [
            {
                "type": "label",
                "text": "ℹ️ Anonymous Upload Available (no credentials needed)",
                "color": "green",
            },
            {
                "type": "dropdown",
                "key": "thumbnail_size",
                "label": "Thumbnail Size",
                "values": ["s", "b", "t", "m", "l", "h"],
                "default": "m",
                "required": True,
                "help": "s=90x90, b=160x160, t=160x160, m=320x320, l=640x640, h=1024x1024",
            },
            {
                "type": "dropdown",
                "key": "content_type",
                "label": "Content Type",
                "values": ["Safe", "NSFW"],
                "default": "Safe",
                "required": True,
                "help": "Mark content as safe or NSFW (mature)",
            },
            {
                "type": "checkbox",
                "key": "save_links",
                "label": "Save Links.txt",
                "default": False,
                "help": "Save upload links to a text file",
            },
            {
                "type": "separator",
            },
            {
                "type": "text",
                "key": "album_id",
                "label": "Album ID (Optional)",
                "default": "",
                "placeholder": "Leave blank for no album",
                "help": "Imgur album ID to add images to",
            },
            {
                "type": "text",
                "key": "title",
                "label": "Image Title (Optional)",
                "default": "",
                "placeholder": "Leave blank for filename",
                "help": "Title for uploaded images",
            },
        ]

    def validate_configuration(self, config: Dict[str, Any]) -> List[str]:
        """Custom validation for Imgur configuration."""
        errors = []

        # Validate thumbnail size
        valid_sizes = ["s", "b", "t", "m", "l", "h"]
        if config.get("thumbnail_size") not in valid_sizes:
            errors.append(f"Invalid thumbnail size. Must be one of: {', '.join(valid_sizes)}")

        # Convert content type to Imgur's mature flag
        content = config.get("content_type", "Safe")
        config["mature"] = content == "NSFW"

        return errors

    # --- Upload Implementation ---

    def initialize_session(
        self, config: Dict[str, Any], creds: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Stub - Go sidecar handles session initialization."""
        return {}

    def upload_file(
        self, file_path: str, group, config: Dict[str, Any], context: Dict[str, Any], progress_callback
    ):
        """Stub - Go sidecar handles file uploads."""
        pass
