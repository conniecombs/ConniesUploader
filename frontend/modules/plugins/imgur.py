# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/plugins/imgur.py
"""
Imgur plugin - Schema-based implementation with Go sidecar uploads.

Go-based upload plugin (upload handled by Go sidecar).
Python side manages UI, configuration validation, and API key handling.
"""

from typing import Dict, Any, List
from .base import ImageHostPlugin


class ImgurPlugin(ImageHostPlugin):
    """Imgur image hosting plugin using schema-based UI."""

    THUMBNAIL_SIZE_LABELS = {
        "s": "Small square (90x90)",
        "b": "Large square (160x160)",
        "t": "Small (160 px)",
        "m": "Medium (320 px)",
        "l": "Large (640 px)",
        "h": "Huge (1024 px)",
    }

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
            "version": "3.0.0",
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
                "allowed_formats": [
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".gif",
                    ".apng",
                    ".tiff",
                    ".mp4",
                    ".webm",
                ],
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
                "type": "dropdown",
                "key": "thumbnail_size",
                "label": "Thumbnail Size",
                "values": ["s", "b", "t", "m", "l", "h"],
                "value_labels": self.THUMBNAIL_SIZE_LABELS,
                "default": "m",
                "required": True,
                "help": "Controls the thumbnail size used in generated output.",
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
                "advanced": True,
            },
            {
                "type": "separator",
                "advanced": True,
            },
            {
                "type": "text",
                "key": "album_id",
                "label": "Album ID (Optional)",
                "default": "",
                "placeholder": "Leave blank for no album",
                "help": "Imgur album ID to add images to",
                "advanced": True,
            },
            {
                "type": "text",
                "key": "title",
                "label": "Image Title (Optional)",
                "default": "",
                "placeholder": "Leave blank for filename",
                "help": "Title for uploaded images",
                "advanced": True,
            },
        ]

    def validate_configuration(self, config: Dict[str, Any]) -> List[str]:
        """Custom validation for Imgur configuration."""
        errors = []

        # Validate thumbnail size
        valid_sizes = list(self.THUMBNAIL_SIZE_LABELS)
        selected_size = str(config.get("thumbnail_size", ""))
        if selected_size in self.THUMBNAIL_SIZE_LABELS.values():
            selected_size = next(
                code
                for code, label in self.THUMBNAIL_SIZE_LABELS.items()
                if label == selected_size
            )
            config["thumbnail_size"] = selected_size

        if selected_size not in valid_sizes:
            errors.append(f"Invalid thumbnail size. Must be one of: {', '.join(valid_sizes)}")

        # Convert content type to Imgur's mature flag
        content = config.get("content_type", "Safe")
        config["mature"] = content == "NSFW"

        return errors

    # --- Upload Implementation ---

    def build_http_request(
        self, file_path: str, config: Dict[str, Any], creds: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build an Imgur API upload request for the Go generic HTTP runner."""
        access_token = str(creds.get("imgur_access_token", "")).strip()
        client_id = str(creds.get("imgur_client_id", "")).strip()

        if access_token:
            authorization = f"Bearer {access_token}"
        elif client_id:
            authorization = f"Client-ID {client_id}"
        else:
            raise ValueError(
                "Imgur uploads require an imgur_client_id for anonymous uploads "
                "or an imgur_access_token for authenticated uploads."
            )

        multipart_fields: Dict[str, Dict[str, str]] = {
            "image": {"type": "file", "value": file_path},
            "type": {"type": "text", "value": "file"},
        }

        album_id = str(config.get("album_id", "")).strip()
        if album_id:
            multipart_fields["album"] = {"type": "text", "value": album_id}

        title = str(config.get("title", "")).strip()
        if title:
            multipart_fields["title"] = {"type": "text", "value": title}

        return {
            "url": "https://api.imgur.com/3/image",
            "method": "POST",
            "headers": {
                "Authorization": authorization,
                "Accept": "application/json",
            },
            "multipart_fields": multipart_fields,
            "response_parser": {
                "type": "json",
                "url_path": "data.link",
                "thumb_path": "data.link",
                "status_path": "success",
                "success_value": "true",
            },
        }

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
