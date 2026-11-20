# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/plugins/base.py
import abc
from typing import TYPE_CHECKING, Dict, Any, Tuple, Optional, List
import customtkinter as ctk

from ..upload_results import UploadResult

if TYPE_CHECKING:  # pragma: no cover - imports for type hints only
    from ..transport import TransportResponse, UploadTransport
    from ..upload_sessions import SessionState


def uses_python_upload_parsing(plugin: Any) -> bool:
    """Whether ``plugin`` uploads through the Python path (it parses its own responses).

    True when the plugin's class defines ``parse_upload_response`` itself;
    the base class default keeps a plugin on its legacy Go specs. The
    ``legacy_upload_parsing`` setting overrides this for every host.
    """
    method = getattr(type(plugin), "parse_upload_response", None)
    return callable(method) and method is not ImageHostPlugin.parse_upload_response


class ImageHostPlugin(abc.ABC):
    @property
    @abc.abstractmethod
    def id(self) -> str:
        """Unique identifier (e.g., 'imx.to')"""
        pass

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Display name (e.g., 'IMX.to')"""
        pass

    # --- Phase 2: Plugin Metadata ---

    @property
    def metadata(self) -> Dict[str, Any]:
        """
        Plugin metadata for documentation, validation, and feature detection.

        Returns a dictionary containing plugin information:

        Example:
            {
                "version": "3.0.0",
                "author": "Plugin Developer",
                "description": "Upload images to ServiceName with gallery support",
                "website": "https://servicenam.com",
                "implementation": "python",  # "python" or "go" (see below)
                "features": {
                    "galleries": True,
                    "covers": True,
                    "authentication": "optional",  # "required", "optional", "none"
                    "direct_links": True,
                    "custom_thumbnails": True
                },
                "credentials": [
                    {
                        "key": "service_user",
                        "label": "Username",
                        "required": False,
                        "description": "Optional login for private galleries"
                    },
                    {
                        "key": "service_pass",
                        "label": "Password",
                        "required": False,
                        "secret": True
                    }
                ],
                "limits": {
                    "max_file_size": 50 * 1024 * 1024,  # 50MB in bytes
                    "allowed_formats": [".jpg", ".jpeg", ".png", ".gif", ".webp"],
                    "rate_limit": "100/hour",
                    "max_resolution": (10000, 10000),  # (width, height)
                    "min_resolution": (100, 100)
                }
            }

        All fields are optional except version. Recommended fields:
            - version: Plugin version (semver recommended)
            - author: Plugin maintainer
            - description: One-line description
            - implementation: "python" when Python owns the host's requests and
              response parsing (the Python upload path, which still uploads
              through the sidecar's transport), or "go" when the sidecar runs
              the plugin's legacy parser specs
            - features: Dictionary of supported features
            - credentials: List of required/optional credentials
            - limits: Service limitations

        This metadata is used for:
            - Plugin documentation
            - Feature detection
            - File validation before upload
            - Credential validation
            - User guidance
        """
        return {
            "version": "1.0.0",
            "author": "Unknown",
            "description": "Image hosting plugin",
            "implementation": "python",
        }

    # --- NEW: Schema-Based Settings (Recommended) ---

    @property
    def settings_schema(self) -> List[Dict[str, Any]]:
        """
        Declarative UI schema for plugin settings.

        Returns a list of field definitions that will be auto-rendered.

        Example:
            [
                {
                    "type": "dropdown",
                    "key": "thumb_size",
                    "label": "Thumbnail Size",
                    "values": ["100", "200", "300"],
                    "default": "200",
                    "required": True,
                    "help": "Size of thumbnail images"
                },
                {
                    "type": "checkbox",
                    "key": "save_links",
                    "label": "Save Links.txt",
                    "default": False
                }
            ]

        Supported field types:
            - dropdown: Combo box with predefined values
            - checkbox: Boolean checkbox
            - number: Number input with min/max validation
            - text: Text entry field
            - label: Information label (no config output)
            - separator: Visual separator line
            - inline_group: Multiple fields in a row

        Field properties:
            - type: Widget type (required)
            - key: Configuration key (required for data fields)
            - label: Display label
            - default: Default value
            - required: Whether field is required
            - help: Tooltip text (future feature)
            - values: Available options (for dropdown)
            - min/max: Range limits (for number)
            - placeholder: Placeholder text (for text)
            - validate: Custom validation function

        If this returns an empty list, falls back to legacy render_settings().
        """
        return []

    def validate_configuration(self, config: Dict[str, Any]) -> List[str]:
        """
        Optional: Custom validation logic beyond schema validation.

        Args:
            config: Configuration dictionary extracted from UI

        Returns:
            List of error messages (empty if valid)

        Example:
            def validate_configuration(self, config):
                errors = []
                if config.get('gallery_id') and not config['gallery_id'].isalnum():
                    errors.append("Gallery ID must be alphanumeric")
                return errors
        """
        return []

    # --- LEGACY: Manual UI Methods (Backward Compatible) ---

    def render_settings(self, parent: ctk.CTkFrame, current_settings: Dict[str, Any]) -> Any:
        """
        Draws the settings widgets into 'parent'.
        Returns a 'ui_handle' (object/dict) containing the Tkinter variables
        needed to retrieve values later.

        NOTE: This method is LEGACY. New plugins should use settings_schema instead.

        If settings_schema is provided, this method is auto-generated.
        Only override this if you need custom UI logic that can't be expressed in schema.
        """
        # Check if plugin uses new schema-based approach
        if self.settings_schema:
            from .schema_renderer import SchemaRenderer

            renderer = SchemaRenderer()
            return renderer.render(parent, self.settings_schema, current_settings)
        else:
            # Legacy plugins must implement this
            raise NotImplementedError(
                f"{self.__class__.__name__} must implement either settings_schema or render_settings"
            )

    def get_configuration(self, ui_handle: Any) -> Dict[str, Any]:
        """
        Called when Start Upload is clicked.
        Extracts values from the 'ui_handle' into a plain dictionary.

        NOTE: This method is LEGACY. New plugins should use settings_schema instead.

        If settings_schema is provided, this method is auto-generated with validation.
        Only override this if you need custom extraction logic.
        """
        # Check if plugin uses new schema-based approach
        if self.settings_schema:
            from .schema_renderer import SchemaRenderer, ValidationError

            renderer = SchemaRenderer()
            config, errors = renderer.extract_config(ui_handle, self.settings_schema)

            # Add custom validation
            custom_errors = self.validate_configuration(config)
            if custom_errors:
                errors.extend(custom_errors)

            # Raise if validation failed
            if errors:
                raise ValidationError(errors)

            return config
        else:
            # Legacy plugins must implement this
            raise NotImplementedError(
                f"{self.__class__.__name__} must implement either settings_schema or get_configuration"
            )

    # --- Worker Methods (Background Thread) ---

    @abc.abstractmethod
    def initialize_session(self, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
        """
        Runs once per batch start. Performs login, fetches global tokens.
        Returns a 'context' dict passed to subsequent methods.
        """
        pass

    def prepare_group(
        self,
        group_info: Any,
        config: Dict[str, Any],
        context: Dict[str, Any],
        creds: Dict[str, Any],
    ) -> None:
        """
        Optional: Runs before processing a specific group of files.
        Used for creating galleries per folder (e.g., IMX, Pixhost).
        Modifies 'context' or 'group_info' in place.
        """
        pass

    @abc.abstractmethod
    def upload_file(
        self,
        file_path: str,
        group_info: Any,
        config: Dict[str, Any],
        context: Dict[str, Any],
        progress_callback,
    ) -> Tuple[str, str]:
        """
        Uploads a single file.
        Returns: (viewer_url, thumb_url)
        """
        pass

    def build_http_request(
        self, file_path: str, config: Dict[str, Any], creds: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        NEW: Build a generic HTTP request specification for Go sidecar execution.

        This allows plugins to define uploads declaratively without hardcoding service
        logic in Go. The Go sidecar becomes a "dumb HTTP runner" that executes
        requests based on this spec.

        Returns a dictionary with the HTTP request specification:
        {
            "url": "https://api.example.com/upload",
            "method": "POST",
            "headers": {
                "X-API-KEY": "...",
                "User-Agent": "..."
            },
            "multipart_fields": {
                "image": {"type": "file", "value": "/path/to/file.jpg"},
                "format": {"type": "text", "value": "json"},
                "thumbnail_size": {"type": "text", "value": "180"}
            },
            "response_parser": {
                "type": "json",  # or "html"
                "url_path": "data.image_url",  # JSONPath for image URL
                "thumb_path": "data.thumbnail_url",  # JSONPath for thumbnail URL
                "status_path": "status",  # JSONPath for status field
                "success_value": "success"  # Expected value for success
            }
        }

        If this method returns None, the upload falls back to legacy upload_file() method.

        Plugins on the Python upload path (they define parse_upload_response)
        keep this method as the ``legacy_upload_parsing`` fallback.
        """
        return None

    # --- Python upload path (v3.2.0) ---------------------------------------------------
    #
    # A plugin that defines parse_upload_response uploads through the Python
    # path. Per upload job the upload manager:
    #   1. opens a transport session (an isolated cookie jar in the sidecar);
    #   2. calls open_upload_session(transport, config, creds) on a worker
    #      thread: log in, fetch tokens; the returned values are session_values;
    #   3. calls build_raw_upload_request(file_path, config, session_values,
    #      creds) for each file and sends one raw upload job on the session;
    #   4. for each file the host answered, calls parse_upload_response(...) on
    #      a small worker pool; it may make follow-up requests on the transport;
    #   5. closes the session when the job and its parsing are done.
    # Stop cancels the batch, which closes its sessions in the sidecar, so
    # follow-up requests end at once with status "cancelled".
    # See docs/plans/V3_2_0_PYTHON_UPLOAD_PARSING_DESIGN.md, "How to migrate a host".

    def upload_job_options(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Options for this host's upload jobs on the Python path.

        ``{"sequential": True}`` uploads and parses a job's files one at a
        time, in order, on one session: the next file is sent only after the
        previous one was parsed. Hosts whose result page is matched by upload
        order (``ResultPageMatcher`` mode ``upload_order``) need it.
        """
        return {}

    def open_upload_session(
        self, transport: "UploadTransport", config: Dict[str, Any], creds: Dict[str, Any]
    ) -> Dict[str, str]:
        """Log in and fetch session tokens on ``transport``; return values for the uploads.

        Runs once per upload job, on a worker thread. Raise an exception with
        a readable message to fail the job's files (for example a refused
        login); the returned values are redacted from failure messages.
        """
        return {}

    def build_raw_upload_request(
        self,
        file_path: str,
        config: Dict[str, Any],
        session_values: Dict[str, str],
        creds: Dict[str, Any],
    ) -> Dict[str, Any]:
        """The fully resolved upload request for one file.

        Return ``{"url", "method", "headers", "multipart_fields"}`` (optional
        ``form_fields``: extra text fields). ``multipart_fields`` holds
        exactly one ``{"type": "file", "value": file_path}`` field; every other
        field is ``{"type": "text", "value": ...}``. Values are sent exactly
        as given: per-file values (an upload id, the file size) are made here.
        """
        raise NotImplementedError(f"{type(self).__name__} does not build raw upload requests")

    def parse_upload_response(
        self,
        file_path: str,
        response: "TransportResponse",
        transport: "UploadTransport",
        session_values: Dict[str, str],
        session_state: "SessionState",
    ) -> UploadResult:
        """Interpret the host's answer to one upload.

        ``response`` carries the answer whatever its HTTP status
        (``status_code``, ``body``, ``final_url``): decide success here. Return
        ``UploadResult(url, thumb, gallery_url)`` or ``UploadResult.failed(why)``;
        a result without a link fails the file. ``transport`` runs follow-up
        requests on the job's session; ``session_state`` is shared by the
        job's files. Called from several threads at once for one job.

        Defining this method moves the plugin to the Python upload path.
        """
        raise NotImplementedError(f"{type(self).__name__} does not parse upload responses")

    def finalize_batch(self, context: Dict[str, Any]) -> None:
        """Optional: Runs after all uploads are finished."""
        pass
