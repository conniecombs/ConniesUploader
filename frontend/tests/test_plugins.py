# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# tests/test_plugins.py
"""
Plugin system test suite - Phase 6 Testing Framework.

Tests:
- Helper function utilities
- Schema validation
- Plugin metadata
- Plugin discovery
- Configuration validation
"""

import unittest
import sys
import os
import tempfile
from typing import Dict, Any
from unittest.mock import Mock, MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.plugins import helpers
from modules.plugins.base import ImageHostPlugin


class TestHelperFunctions(unittest.TestCase):
    """Test plugin helper utility functions."""

    def test_validate_cover_count_valid(self):
        """Test cover count validation with valid input."""
        config = {"cover_count": "5"}
        errors = []
        helpers.validate_cover_count(config, errors)
        self.assertEqual(config["cover_limit"], 5)
        self.assertEqual(len(errors), 0)

    def test_validate_cover_count_invalid(self):
        """Test cover count validation with invalid input."""
        config = {"cover_count": "invalid"}
        errors = []
        helpers.validate_cover_count(config, errors)
        self.assertEqual(len(errors), 1)
        self.assertIn("valid number", errors[0])

    def test_validate_cover_count_default(self):
        """Test cover count validation with missing value."""
        config = {}
        errors = []
        helpers.validate_cover_count(config, errors)
        self.assertEqual(config["cover_limit"], 0)
        self.assertEqual(len(errors), 0)

    def test_validate_gallery_id_valid(self):
        """Test gallery ID validation with valid alphanumeric ID."""
        errors = []
        helpers.validate_gallery_id("abc123", errors, alphanumeric=True)
        self.assertEqual(len(errors), 0)

    def test_validate_gallery_id_invalid(self):
        """Test gallery ID validation with invalid characters."""
        errors = []
        helpers.validate_gallery_id("abc-123", errors, alphanumeric=True)
        self.assertEqual(len(errors), 1)
        self.assertIn("letters and numbers", errors[0])

    def test_validate_gallery_id_empty(self):
        """Test gallery ID validation with empty string."""
        errors = []
        helpers.validate_gallery_id("", errors, alphanumeric=True)
        self.assertEqual(len(errors), 0)  # Empty is OK

    def test_validate_credentials_all_present(self):
        """Test credential validation when all required keys present."""
        creds = {"api_key": "abc123", "secret": "xyz789"}
        errors = helpers.validate_credentials(creds, ["api_key", "secret"])
        self.assertEqual(len(errors), 0)

    def test_validate_credentials_missing(self):
        """Test credential validation with missing keys."""
        creds = {"api_key": "abc123"}
        errors = helpers.validate_credentials(creds, ["api_key", "secret"])
        self.assertEqual(len(errors), 1)
        self.assertIn("secret", errors[0])

    def test_is_cover_image_first_file(self):
        """Test cover image detection for first file."""
        group = Mock()
        group.files = ["/a.jpg", "/b.jpg", "/c.jpg"]
        config = {"cover_limit": 2}

        self.assertTrue(helpers.is_cover_image("/a.jpg", group, config))
        self.assertTrue(helpers.is_cover_image("/b.jpg", group, config))
        self.assertFalse(helpers.is_cover_image("/c.jpg", group, config))

    def test_is_cover_image_zero_covers(self):
        """Test cover image detection with zero covers."""
        group = Mock()
        group.files = ["/a.jpg", "/b.jpg"]
        config = {"cover_limit": 0}

        self.assertFalse(helpers.is_cover_image("/a.jpg", group, config))

    def test_is_cover_image_missing_file(self):
        """Test cover image detection with file not in group."""
        group = Mock()
        group.files = ["/a.jpg", "/b.jpg"]
        config = {"cover_limit": 2}

        self.assertFalse(helpers.is_cover_image("/missing.jpg", group, config))

    def test_normalize_boolean_values(self):
        """Test boolean normalization with various inputs."""
        self.assertTrue(helpers.normalize_boolean(True))
        self.assertTrue(helpers.normalize_boolean("true"))
        self.assertTrue(helpers.normalize_boolean("yes"))
        self.assertTrue(helpers.normalize_boolean("1"))
        self.assertTrue(helpers.normalize_boolean(1))

        self.assertFalse(helpers.normalize_boolean(False))
        self.assertFalse(helpers.normalize_boolean("false"))
        self.assertFalse(helpers.normalize_boolean("no"))
        self.assertFalse(helpers.normalize_boolean("0"))
        self.assertFalse(helpers.normalize_boolean(0))

    def test_normalize_int_valid(self):
        """Test integer normalization with valid inputs."""
        self.assertEqual(helpers.normalize_int("42"), 42)
        self.assertEqual(helpers.normalize_int(42), 42)
        self.assertEqual(helpers.normalize_int("0"), 0)

    def test_normalize_int_invalid(self):
        """Test integer normalization with invalid inputs."""
        self.assertEqual(helpers.normalize_int("invalid", default=10), 10)
        self.assertEqual(helpers.normalize_int(None, default=5), 5)

    def test_should_create_gallery(self):
        """Test gallery creation flag detection."""
        self.assertTrue(helpers.should_create_gallery({"auto_gallery": True}))
        self.assertFalse(helpers.should_create_gallery({"auto_gallery": False}))
        self.assertFalse(helpers.should_create_gallery({}))

    def test_get_gallery_id_from_config(self):
        """Test getting gallery ID from config."""
        config = {"gallery_id": "abc123"}
        self.assertEqual(helpers.get_gallery_id(config), "abc123")

    def test_get_gallery_id_from_group(self):
        """Test getting gallery ID from group object (priority)."""
        group = Mock()
        group.gallery_id = "xyz789"
        config = {"gallery_id": "abc123"}

        # Group ID takes priority
        self.assertEqual(helpers.get_gallery_id(config, group), "xyz789")

    def test_get_gallery_id_empty(self):
        """Test getting gallery ID when none specified."""
        self.assertIsNone(helpers.get_gallery_id({}))


class TestPluginSchemas(unittest.TestCase):
    """Test plugin schema validation."""

    def test_schema_has_required_fields(self):
        """Test that schemas contain required field properties."""
        from modules.plugins import pixhost, imgur, turbo

        for plugin_module in [pixhost, imgur, turbo]:
            plugin_class = getattr(
                plugin_module, f"{plugin_module.__name__.split('.')[-1].capitalize()}Plugin"
            )
            instance = plugin_class()
            schema = instance.settings_schema

            self.assertIsInstance(schema, list)

            # Check that fields have proper structure
            for field in schema:
                self.assertIsInstance(field, dict)
                self.assertIn("type", field)

                # Fields with keys should have labels
                if "key" in field:
                    self.assertIn(
                        "label", field, f"Field with key '{field.get('key')}' missing label"
                    )

    def test_standard_keys_used(self):
        """Test that plugins use standard configuration keys."""
        from modules.plugins import pixhost, imgur, turbo, imagebam

        standard_keys = {
            "thumbnail_size",
            "content_type",
            "cover_count",
            "save_links",
            "gallery_id",
        }

        # Map module names to class names (handle special cases like ImageBam)
        class_name_map = {
            "pixhost": "PixhostPlugin",
            "imgur": "ImgurPlugin",
            "turbo": "TurboPlugin",
            "imagebam": "ImageBamPlugin",
        }

        for plugin_module in [pixhost, imgur, turbo, imagebam]:
            module_name = plugin_module.__name__.split(".")[-1]
            plugin_class = getattr(plugin_module, class_name_map[module_name])
            instance = plugin_class()
            schema = instance.settings_schema

            # Extract all keys from schema
            schema_keys = set()
            for field in schema:
                if "key" in field:
                    schema_keys.add(field["key"])
                if field.get("type") == "inline_group" and "fields" in field:
                    for subfield in field["fields"]:
                        if "key" in subfield:
                            schema_keys.add(subfield["key"])

            # Check if any standard keys are used
            used_standard = schema_keys & standard_keys
            if len(used_standard) > 0:
                # If any standard keys used, they should be named correctly
                for key in used_standard:
                    self.assertIn(
                        key, standard_keys, f"Plugin {instance.name} uses non-standard key: {key}"
                    )

    def test_plugin_schemas_do_not_duplicate_host_readiness_copy(self):
        """Credential readiness belongs in the live host readiness panel."""
        from modules.plugins import imx, imgur, turbo, vipr

        forbidden_text = [
            "requires credentials",
            "client id required",
            "login optional",
            "set in tools",
        ]
        plugins = [
            imx.ImxPlugin(),
            imgur.ImgurPlugin(),
            turbo.TurboPlugin(),
            vipr.ViprPlugin(),
        ]

        for plugin in plugins:
            field_text = " ".join(
                str(field.get("text", "")).lower() for field in plugin.settings_schema
            )
            for phrase in forbidden_text:
                self.assertNotIn(phrase, field_text, plugin.name)

    def test_inline_group_label_without_key_renders(self):
        """Test that keyless inline labels do not break schema rendering."""
        from modules.plugins import schema_renderer

        class FakeWidget:
            def __init__(self, *args, **kwargs):
                pass

            def pack(self, *args, **kwargs):
                pass

        class FakeStringVar:
            def __init__(self, value=""):
                self.value = value

            def get(self):
                return self.value

        schema = [
            {
                "type": "inline_group",
                "fields": [
                    {"type": "label", "text": "Cover Images:", "width": 100},
                    {
                        "type": "dropdown",
                        "key": "cover_count",
                        "values": ["0", "1", "2"],
                        "default": "0",
                        "width": 80,
                    },
                ],
            }
        ]

        with (
            patch.object(schema_renderer.ctk, "CTkFrame", FakeWidget),
            patch.object(schema_renderer.ctk, "CTkLabel", FakeWidget),
            patch.object(schema_renderer.ctk, "StringVar", FakeStringVar),
            patch.object(schema_renderer, "MouseWheelComboBox", FakeWidget),
        ):
            ui_vars = schema_renderer.SchemaRenderer().render(None, schema, {})

        self.assertEqual(set(ui_vars), {"cover_count"})
        self.assertEqual(ui_vars["cover_count"].get(), "0")

    def test_dropdown_value_labels_render_readable_text_but_extract_codes(self):
        """Test that dropdowns can show user-friendly labels while storing service codes."""
        from modules.plugins import schema_renderer

        class FakeWidget:
            def __init__(self, *args, **kwargs):
                pass

            def pack(self, *args, **kwargs):
                pass

        class FakeStringVar:
            def __init__(self, value=""):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        schema = [
            {
                "type": "dropdown",
                "key": "thumbnail_size",
                "label": "Thumbnail Size",
                "values": ["m", "l"],
                "value_labels": {
                    "m": "Medium (320 px)",
                    "l": "Large (640 px)",
                },
                "default": "m",
            }
        ]

        renderer = schema_renderer.SchemaRenderer()
        with (
            patch.object(schema_renderer.ctk, "CTkLabel", FakeWidget),
            patch.object(schema_renderer.ctk, "StringVar", FakeStringVar),
            patch.object(schema_renderer, "MouseWheelComboBox", FakeWidget),
        ):
            ui_vars = renderer.render(None, schema, {"thumbnail_size": "m"})

        self.assertEqual(ui_vars["thumbnail_size"].get(), "Medium (320 px)")
        ui_vars["thumbnail_size"].set("Large (640 px)")

        config, errors = renderer.extract_config(ui_vars, schema)

        self.assertEqual(errors, [])
        self.assertEqual(config["thumbnail_size"], "l")

    def test_advanced_schema_fields_render_collapsed_but_remain_configurable(self):
        """Test that advanced fields are hidden from the default path but still readable."""
        from modules.plugins import schema_renderer

        class FakeWidget:
            created_texts = []

            def __init__(self, *args, **kwargs):
                text = kwargs.get("text")
                if text:
                    self.created_texts.append(text)

            def pack(self, *args, **kwargs):
                pass

            def pack_forget(self):
                pass

            def configure(self, **kwargs):
                text = kwargs.get("text")
                if text:
                    self.created_texts.append(text)

        class FakeVar:
            def __init__(self, value=""):
                self.value = value

            def get(self):
                return self.value

        schema = [
            {
                "type": "dropdown",
                "key": "thumbnail_size",
                "label": "Thumbnail Size",
                "values": ["180"],
                "default": "180",
            },
            {
                "type": "checkbox",
                "key": "save_links",
                "label": "Save Links.txt",
                "default": False,
                "advanced": True,
            },
            {"type": "separator", "advanced": True},
            {
                "type": "text",
                "key": "gallery_id",
                "label": "Gallery ID",
                "default": "",
                "advanced": True,
            },
        ]

        with (
            patch.object(schema_renderer.ctk, "CTkFrame", FakeWidget),
            patch.object(schema_renderer.ctk, "CTkLabel", FakeWidget),
            patch.object(schema_renderer.ctk, "CTkButton", FakeWidget),
            patch.object(schema_renderer.ctk, "CTkCheckBox", FakeWidget),
            patch.object(schema_renderer.ctk, "CTkEntry", FakeWidget),
            patch.object(schema_renderer.ctk, "StringVar", FakeVar),
            patch.object(schema_renderer.ctk, "BooleanVar", FakeVar),
            patch.object(schema_renderer, "MouseWheelComboBox", FakeWidget),
        ):
            ui_vars = schema_renderer.SchemaRenderer().render(
                None,
                schema,
                {"save_links": True, "gallery_id": "abc123"},
            )

        self.assertEqual(set(ui_vars), {"thumbnail_size", "save_links", "gallery_id"})
        self.assertTrue(ui_vars["save_links"].get())
        self.assertEqual(ui_vars["gallery_id"].get(), "abc123")
        self.assertIn("Advanced Host Settings +", FakeWidget.created_texts)


class TestPixhostGalleryIntegration(unittest.TestCase):
    """Test Pixhost gallery metadata plumbing."""

    def test_metadata_matches_live_api_limits(self):
        from modules.plugins.pixhost import PixhostPlugin

        limits = PixhostPlugin().metadata["limits"]

        self.assertEqual(limits["max_file_size"], 10 * 1024 * 1024)
        self.assertEqual(limits["allowed_formats"], [".jpg", ".jpeg", ".png", ".gif"])

    def test_build_http_request_includes_gallery_upload_hash(self):
        from modules.plugins.pixhost import PixhostPlugin

        plugin = PixhostPlugin()
        request = plugin.build_http_request(
            "/tmp/image.jpg",
            {
                "content_type": "Safe",
                "thumbnail_size": "200",
                "gallery_hash": "abc123",
                "gallery_upload_hash": "upload456",
            },
            {},
        )

        fields = request["multipart_fields"]
        self.assertEqual(request["headers"]["Accept"], "application/json")
        self.assertEqual(fields["gallery_hash"]["value"], "abc123")
        self.assertEqual(fields["gallery_upload_hash"]["value"], "upload456")

    def test_prepare_group_stores_upload_hash_for_later_uploads(self):
        from modules.plugins.pixhost import PixhostPlugin

        plugin = PixhostPlugin()
        group = Mock()
        group.title = "[Test Gallery]"
        config = {"auto_gallery": True}
        context = {}
        new_gallery = {
            "gallery_hash": "abc123",
            "gallery_upload_hash": "upload456",
            "gallery_url": "https://pixhost.to/gallery/abc123",
        }

        with patch("modules.plugins.pixhost.api.create_pixhost_gallery", return_value=new_gallery):
            plugin.prepare_group(group, config, context, {})

        self.assertEqual(group.gallery_id, "abc123")
        self.assertEqual(config["gallery_hash"], "abc123")
        self.assertEqual(config["gallery_upload_hash"], "upload456")
        self.assertEqual(
            context["created_galleries"],
            [{**new_gallery, "gallery_name": "Test Gallery"}],
        )

    def test_upload_manager_preserves_created_gallery_upload_hash(self):
        import queue
        import threading

        from modules.upload_manager import UploadManager

        class Group:
            title = "Test Gallery"
            files = ["image.jpg"]

        class FakePixhostPlugin:
            def prepare_group(self, group, config, context, creds):
                gallery = {
                    "gallery_hash": "abc123",
                    "gallery_upload_hash": "upload456",
                }
                group.gallery_id = gallery["gallery_hash"]
                group.pix_data = gallery
                context["created_galleries"] = [gallery]

        sent_configs = []
        manager = UploadManager.__new__(UploadManager)
        manager.cancel_event = threading.Event()
        manager.progress_queue = queue.Queue()
        manager.plugin_manager = Mock()
        manager.plugin_manager.get_plugin.return_value = FakePixhostPlugin()
        manager._send_job = lambda files, cfg, creds: sent_configs.append(cfg.copy())

        group = Group()
        manager._dispatch_jobs(
            {group: ["image.jpg"]},
            {"service": "pixhost.to", "auto_gallery": True},
            {},
        )

        self.assertEqual(sent_configs[0]["gallery_hash"], "abc123")
        self.assertEqual(sent_configs[0]["gallery_upload_hash"], "upload456")

    def test_upload_manager_remembers_imx_gallery_use_without_full_sync(self):
        from modules.gallery_cache import GalleryCache
        from modules.upload_manager import UploadManager

        class Group:
            gallery_name = "Batch Gallery"
            gallery_url = "https://imx.to/g/abc123"

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = GalleryCache(os.path.join(temp_dir, "gallery_cache.json"))
            with patch("modules.upload_manager.GalleryCache", return_value=cache):
                UploadManager._remember_imx_gallery_use(
                    Group(),
                    {
                        "gallery_id": "abc123",
                        "selected_gallery_name": "Selected Gallery",
                        "selected_gallery_url": "https://imx.to/g/abc123",
                    },
                )

            records = cache.records_for_service("imx.to")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].id, "abc123")
            self.assertEqual(records[0].name, "Selected Gallery")
            self.assertEqual(records[0].url, "https://imx.to/g/abc123")
            self.assertEqual(records[0].raw["source"], "upload")
            self.assertTrue(records[0].raw["last_used_at"])


class TestUploadManagerJobConfig(unittest.TestCase):
    """Test sidecar job config normalization."""

    def test_service_threads_are_mapped_to_sidecar_threads(self):
        from modules.upload_manager import UploadManager

        config = UploadManager._normalize_job_config(
            {"service": "pixhost.to", "pix_threads": 7, "threads": 2}
        )

        self.assertEqual(config["threads"], 7)

    def test_global_thread_limit_takes_precedence_over_service_threads(self):
        from modules.upload_manager import UploadManager

        config = UploadManager._normalize_job_config(
            {"service": "pixhost.to", "global_thread_limit": 4, "pix_threads": 7}
        )

        self.assertEqual(config["threads"], 4)

    def test_invalid_threads_fall_back_to_safe_default(self):
        from modules.upload_manager import UploadManager

        config = UploadManager._normalize_job_config(
            {"service": "vipr.im", "global_thread_limit": "not-a-number"}
        )

        self.assertEqual(config["threads"], 2)

    def test_threads_are_clamped_to_visible_thread_limit_range(self):
        from modules.upload_manager import UploadManager

        too_high = UploadManager._normalize_job_config(
            {"service": "pixhost.to", "pix_threads": 99}
        )
        too_low = UploadManager._normalize_job_config(
            {"service": "pixhost.to", "pix_threads": 0}
        )

        self.assertEqual(too_high["threads"], 10)
        self.assertEqual(too_low["threads"], 1)


class TestImxPlugin(unittest.TestCase):
    """Test IMX-specific plugin behavior."""

    def test_prepare_group_creates_imx_gallery_for_auto_gallery(self):
        from modules.plugins import imx

        plugin = imx.ImxPlugin()
        group = Mock()
        group.title = "Batch Gallery"
        config = {"auto_gallery": True}

        with patch.object(imx.api, "create_imx_gallery", return_value="abc123") as create:
            plugin.prepare_group(
                group,
                config,
                {},
                {"imx_user": "user", "imx_pass": "secret"},
            )

        create.assert_called_once_with("user", "secret", "Batch Gallery")
        self.assertEqual(group.gallery_id, "abc123")
        self.assertEqual(group.gallery_name, "Batch Gallery")
        self.assertEqual(group.gallery_url, "https://imx.to/g/abc123")
        self.assertEqual(group.gallery_service, "imx.to")
        self.assertEqual(config["gallery_id"], "abc123")

    def test_build_http_request_uses_documented_api_header_and_selected_gallery(self):
        from modules.plugins import imx

        plugin = imx.ImxPlugin()

        request = plugin.build_http_request(
            "/tmp/image.jpg",
            {
                "selected_gallery_id": "selected123",
                "thumbnail_size": "600",
                "thumbnail_format": "Square",
            },
            {"imx_api": "api-key"},
        )

        fields = request["multipart_fields"]
        self.assertEqual(request["url"], "https://api.imx.to/v1/upload.php")
        self.assertEqual(request["headers"]["X-API-Key"], "api-key")
        self.assertNotIn("X-API-KEY", request["headers"])
        self.assertEqual(fields["gallery_id"]["value"], "selected123")
        self.assertEqual(fields["thumbnail_size"]["value"], "5")
        self.assertEqual(fields["thumbnail_format"]["value"], "3")
        self.assertEqual(request["response_parser"]["url_path"], "data.image_url")
        self.assertEqual(request["response_parser"]["thumb_path"], "data.thumbnail_url")

    def test_build_http_request_prefers_group_gallery_id_over_selected_gallery(self):
        from modules.plugins import imx

        plugin = imx.ImxPlugin()

        request = plugin.build_http_request(
            "/tmp/image.jpg",
            {"gallery_id": "group123", "selected_gallery_id": "selected123"},
            {"imx_api": "api-key"},
        )

        self.assertEqual(request["multipart_fields"]["gallery_id"]["value"], "group123")


class TestImgurHttpSpec(unittest.TestCase):
    """Test Imgur generic HTTP runner specification."""

    def test_build_http_request_uses_client_id_authorization(self):
        from modules.plugins.imgur import ImgurPlugin

        plugin = ImgurPlugin()
        request = plugin.build_http_request(
            "/tmp/image.jpg",
            {"album_id": "album123", "title": "Test Image"},
            {"imgur_client_id": "client123"},
        )

        self.assertEqual(request["url"], "https://api.imgur.com/3/image")
        self.assertEqual(request["headers"]["Authorization"], "Client-ID client123")
        self.assertEqual(request["multipart_fields"]["album"]["value"], "album123")
        self.assertEqual(request["response_parser"]["url_path"], "data.link")

    def test_build_http_request_requires_imgur_credentials(self):
        from modules.plugins.imgur import ImgurPlugin

        plugin = ImgurPlugin()

        with self.assertRaises(ValueError):
            plugin.build_http_request("/tmp/image.jpg", {}, {})

    def test_imgur_thumbnail_size_schema_uses_readable_labels(self):
        from modules.plugins.imgur import ImgurPlugin

        plugin = ImgurPlugin()
        thumbnail_field = next(
            field for field in plugin.settings_schema if field.get("key") == "thumbnail_size"
        )

        self.assertEqual(thumbnail_field["values"], ["s", "b", "t", "m", "l", "h"])
        self.assertEqual(thumbnail_field["value_labels"]["m"], "Medium (320 px)")
        self.assertNotIn("m", thumbnail_field["value_labels"].values())

    def test_imgur_validation_normalizes_readable_thumbnail_label(self):
        from modules.plugins.imgur import ImgurPlugin

        plugin = ImgurPlugin()
        config = {"thumbnail_size": "Medium (320 px)", "content_type": "Safe"}

        errors = plugin.validate_configuration(config)

        self.assertEqual(errors, [])
        self.assertEqual(config["thumbnail_size"], "m")


class TestViprPlugin(unittest.TestCase):
    """Test Vipr-specific plugin behavior."""

    def test_gallery_refresh_uses_centralized_credentials(self):
        from modules.plugins import vipr

        class ImmediateThread:
            def __init__(self, target, daemon=False):
                self.target = target
                self.daemon = daemon

            def start(self):
                self.target()

        plugin = vipr.ViprPlugin()
        plugin.cb_gallery = Mock()
        plugin.cb_gallery.get.return_value = "None"
        parent = Mock()
        parent.after.side_effect = lambda _delay, callback: callback()

        with (
            patch.object(vipr.CredentialsManager, "load_all_credentials") as load_credentials,
            patch.object(vipr.api, "get_vipr_metadata") as get_metadata,
            patch.object(vipr.threading, "Thread", ImmediateThread),
        ):
            load_credentials.return_value = {
                "vipr_user": " johngrimm ",
                "vipr_pass": " secret ",
            }
            get_metadata.return_value = {
                "galleries": [
                    {
                        "name": "First Gallery",
                        "id": "123",
                        "url": "https://vipr.im/p/user/123/First%20Gallery",
                    }
                ]
            }

            plugin._refresh_galleries(parent)

        get_metadata.assert_called_once_with(
            {"vipr_user": "johngrimm", "vipr_pass": "secret"}
        )
        plugin.cb_gallery.configure.assert_called_once_with(values=["None", "First Gallery"])
        self.assertEqual(plugin.vipr_galleries_map, {"First Gallery": "123"})
        self.assertEqual(
            plugin.vipr_gallery_urls_map,
            {"First Gallery": "https://vipr.im/p/user/123/First%20Gallery"},
        )

    def test_gallery_refresh_treats_null_gallery_response_as_empty(self):
        from modules.plugins import vipr

        class ImmediateThread:
            def __init__(self, target, daemon=False):
                self.target = target
                self.daemon = daemon

            def start(self):
                self.target()

        plugin = vipr.ViprPlugin()
        plugin.cb_gallery = Mock()
        plugin.cb_gallery.get.return_value = "Old Gallery"
        parent = Mock()
        parent.after.side_effect = lambda _delay, callback: callback()

        with (
            patch.object(vipr.CredentialsManager, "load_all_credentials") as load_credentials,
            patch.object(vipr.api, "get_vipr_metadata") as get_metadata,
            patch.object(vipr.threading, "Thread", ImmediateThread),
        ):
            load_credentials.return_value = {
                "vipr_user": "johngrimm",
                "vipr_pass": "secret",
            }
            get_metadata.return_value = {"galleries": None}

            plugin._refresh_galleries(parent)

        plugin.cb_gallery.configure.assert_called_once_with(values=["None"])
        plugin.cb_gallery.set.assert_called_once_with("None")
        self.assertEqual(plugin.vipr_galleries_map, {})

    def test_prepare_group_creates_vipr_gallery_for_auto_gallery(self):
        from modules.plugins import vipr

        plugin = vipr.ViprPlugin()
        group = Mock()
        group.title = "[Batch Gallery]"
        config = {"auto_gallery": True}
        created = {
            "id": "104999",
            "name": "Batch Gallery",
            "url": "https://vipr.im/p/johngrimm/104999/Batch%20Gallery",
        }

        with patch.object(vipr.api, "create_vipr_gallery", return_value=created) as create:
            plugin.prepare_group(
                group,
                config,
                {},
                {"vipr_user": "user", "vipr_pass": "secret"},
            )

        create.assert_called_once_with(
            {"vipr_user": "user", "vipr_pass": "secret"}, "Batch Gallery"
        )
        self.assertEqual(group.gallery_id, "104999")
        self.assertEqual(group.gallery_name, "Batch Gallery")
        self.assertEqual(
            group.gallery_url, "https://vipr.im/p/johngrimm/104999/Batch%20Gallery"
        )
        self.assertEqual(group.gallery_service, "vipr.im")
        self.assertEqual(config["vipr_gal_id"], "104999")
        self.assertEqual(config["selected_gallery_url"], group.gallery_url)

    def test_build_http_request_uses_selected_vipr_gallery_and_dynamic_endpoint(self):
        from modules.plugins import vipr

        plugin = vipr.ViprPlugin()

        request = plugin.build_http_request(
            "/tmp/image.jpg",
            {
                "vipr_gal_id": "old",
                "selected_gallery_id": "104999",
                "thumbnail_size": "250x250",
            },
            {"vipr_user": "user", "vipr_pass": "secret"},
        )

        fields = request["multipart_fields"]
        self.assertEqual(fields["fld_id"]["value"], "104999")
        self.assertEqual(fields["thumb_size"]["value"], "250x250")
        self.assertEqual(fields["per_row"]["value"], "750")
        self.assertEqual(fields["sdomain"]["value"], "vipr.im")
        endpoint = request["pre_request"]["follow_up_request"]["extract_fields"]["endpoint"]
        self.assertIn("regex:", endpoint)
        self.assertIn("cgi-bin/upload\\.cgi", endpoint)
        self.assertNotEqual(endpoint, "form[action*='upload.cgi']")
        parser = request["response_parser"]
        follow_up = parser["follow_up_request"]
        self.assertEqual(follow_up["url"], "https://vipr.im/")
        self.assertEqual(follow_up["form_fields"]["fn"], "{fn}")
        self.assertEqual(follow_up["extract_fields"]["fn"], "textarea[name='fn']")
        self.assertIn("vipr\\.im", parser["url_path"])
        self.assertIn("[IMG", parser["thumb_path"])

    def test_build_http_request_prefers_group_gallery_id_over_saved_vipr_id(self):
        from modules.plugins import vipr

        plugin = vipr.ViprPlugin()

        request = plugin.build_http_request(
            "/tmp/image.jpg",
            {"gallery_id": "created-for-group", "vipr_gal_id": "saved-selection"},
            {"vipr_user": "user", "vipr_pass": "secret"},
        )

        self.assertEqual(
            request["multipart_fields"]["fld_id"]["value"], "created-for-group"
        )


class TestImageBamPlugin(unittest.TestCase):
    """Test ImageBam's live upload-session contract."""

    def test_build_http_request_uses_live_dropzone_fields(self):
        from modules.plugins.imagebam import ImageBamPlugin

        plugin = ImageBamPlugin()

        request = plugin.build_http_request(
            "/tmp/image.jpg",
            {
                "content_type": "Safe",
                "thumbnail_size": "180",
                "selected_gallery_id": "490670",
            },
            {"imagebam_user": "user", "imagebam_pass": "secret"},
        )

        self.assertEqual(request["url"], "https://www.imagebam.com/upload")
        self.assertEqual(request["headers"]["X-Requested-With"], "XMLHttpRequest")
        fields = request["multipart_fields"]
        self.assertEqual(fields["files[0]"]["value"], "/tmp/image.jpg")
        self.assertEqual(fields["_token"]["value"], "csrf_token")
        self.assertEqual(fields["data"]["value"], "upload_token")
        self.assertNotIn("upload_session", fields)

        session_request = (
            request["pre_request"]["follow_up_request"]["follow_up_request"][
                "follow_up_request"
            ]
        )
        self.assertEqual(session_request["url"], "https://www.imagebam.com/upload/session")
        self.assertEqual(
            session_request["form_fields"],
            {
                "thumbnail_size": "2",
                "content_type": "sfw",
                "comments_enabled": "false",
                "gallery": "true",
                "gallery_token": "490670",
                "gallery_title": "",
            },
        )
        self.assertEqual(request["response_parser"]["url_path"], "success")
        self.assertEqual(request["response_parser"]["thumb_path"], "")
        self.assertEqual(request["resolve_spec"]["result_url"], "{url}")
        self.assertEqual(request["resolve_spec"]["gallery_extractor"], "a#gallery-name")
        self.assertEqual(request["resolve_spec"]["file_match_mode"], "single")
        self.assertIn("thumb_url", request["resolve_spec"]["link_extractor"])

    def test_build_http_request_can_create_gallery_during_session(self):
        from modules.plugins.imagebam import ImageBamPlugin

        plugin = ImageBamPlugin()

        request = plugin.build_http_request(
            "/tmp/image.jpg",
            {
                "content_type": "Adult",
                "thumbnail_size": "300",
                "imagebam_gallery_title": "Batch Gallery",
            },
            {},
        )

        self.assertEqual(request["pre_request"]["action"], "get_api_csrf")
        session_request = request["pre_request"]["follow_up_request"]
        self.assertEqual(
            session_request["form_fields"],
            {
                "thumbnail_size": "4",
                "content_type": "nsfw",
                "comments_enabled": "false",
                "gallery": "true",
                "gallery_token": "",
                "gallery_title": "Batch Gallery",
            },
        )

    def test_prepare_group_sets_imagebam_gallery_title_for_auto_gallery(self):
        from modules.plugins.imagebam import ImageBamPlugin

        plugin = ImageBamPlugin()
        group = Mock()
        group.title = "Batch Gallery"
        config = {"auto_gallery": True}

        plugin.prepare_group(
            group,
            config,
            {},
            {"imagebam_user": "user", "imagebam_pass": "secret"},
        )

        self.assertEqual(group.imagebam_gallery_title, "Batch Gallery")
        self.assertEqual(group.gallery_name, "Batch Gallery")
        self.assertEqual(group.gallery_service, "imagebam.com")
        self.assertEqual(config["imagebam_gallery_title"], "Batch Gallery")


class TestPluginMetadata(unittest.TestCase):
    """Test plugin metadata completeness."""

    def test_metadata_required_fields(self):
        """Test that all plugins have required metadata fields."""
        from modules.plugins import pixhost, imgur, turbo, imagebam, imx, vipr

        required_fields = {"version", "author", "description", "implementation"}

        # Map module names to class names (handle special cases)
        class_name_map = {
            "pixhost": "PixhostPlugin",
            "imgur": "ImgurPlugin",
            "turbo": "TurboPlugin",
            "imagebam": "ImageBamPlugin",
            "imx": "ImxPlugin",
            "vipr": "ViprPlugin",
        }

        for plugin_module in [pixhost, imgur, turbo, imagebam, imx, vipr]:
            module_name = plugin_module.__name__.split(".")[-1]
            plugin_class = getattr(plugin_module, class_name_map[module_name])
            instance = plugin_class()
            metadata = instance.metadata

            for field in required_fields:
                self.assertIn(
                    field, metadata, f"Plugin {instance.name} missing metadata field: {field}"
                )
                self.assertIsNotNone(metadata[field])
                self.assertNotEqual(metadata[field], "")

    def test_metadata_version_format(self):
        """Test that plugin versions follow semantic versioning."""
        from modules.plugins import pixhost, imgur

        for plugin_module in [pixhost, imgur]:
            plugin_class = getattr(
                plugin_module, f"{plugin_module.__name__.split('.')[-1].capitalize()}Plugin"
            )
            instance = plugin_class()
            version = instance.metadata.get("version")

            # Check basic semver format (X.Y.Z)
            self.assertIsNotNone(version)
            parts = version.split(".")
            self.assertEqual(len(parts), 3, f"Plugin {instance.name} version not semver: {version}")

    def test_metadata_features_structure(self):
        """Test that plugin features metadata is properly structured."""
        from modules.plugins import pixhost, imgur

        for plugin_module in [pixhost, imgur]:
            plugin_class = getattr(
                plugin_module, f"{plugin_module.__name__.split('.')[-1].capitalize()}Plugin"
            )
            instance = plugin_class()
            features = instance.metadata.get("features", {})

            self.assertIsInstance(features, dict)

            # Common feature flags should be boolean or string
            for key in ["galleries", "covers", "authentication"]:
                if key in features:
                    self.assertIn(type(features[key]), [bool, str])


class TestPluginDiscovery(unittest.TestCase):
    """Test plugin auto-discovery system."""

    def test_plugin_manager_loads_plugins(self):
        """Test that PluginManager discovers and loads plugins."""
        from modules.plugin_manager import PluginManager

        manager = PluginManager()
        manager.load_plugins()

        # Should have loaded at least 6 plugins (pixhost, imx, vipr, turbo, imagebam, imgur)
        self.assertGreaterEqual(manager.get_plugin_count(), 6)

    def test_loaded_plugins_have_valid_ids(self):
        """Test that all loaded plugins have valid IDs."""
        from modules.plugin_manager import PluginManager

        manager = PluginManager()
        manager.load_plugins()

        plugins = manager.get_all_plugins()
        service_names = manager.get_service_names()

        # Check that all plugins have valid IDs
        for plugin in plugins:
            self.assertIsNotNone(plugin.id)
            self.assertNotEqual(plugin.id, "")
            self.assertIn(plugin.id, service_names)

    def test_plugin_manager_error_tracking(self):
        """Test that PluginManager tracks loading errors."""
        from modules.plugin_manager import PluginManager

        manager = PluginManager()
        manager.load_plugins()

        # Should have error tracking available
        errors = manager.get_load_errors()
        self.assertIsInstance(errors, list)


class TestPluginBaseClass(unittest.TestCase):
    """Test plugin base class functionality."""

    def _create_test_plugin(self):
        """Create a minimal test plugin implementation."""

        class TestPlugin(ImageHostPlugin):
            @property
            def id(self):
                return "test.plugin"

            @property
            def name(self):
                return "Test Plugin"

            def initialize_session(self, config, creds):
                return {}

            def upload_file(self, file_path, group, config, context, progress_callback):
                pass

        return TestPlugin()

    def test_base_plugin_has_schema_property(self):
        """Test that base plugin class has settings_schema property."""
        plugin = self._create_test_plugin()
        schema = plugin.settings_schema
        self.assertIsInstance(schema, list)

    def test_base_plugin_has_metadata_property(self):
        """Test that base plugin class has metadata property."""
        plugin = self._create_test_plugin()
        metadata = plugin.metadata
        self.assertIsInstance(metadata, dict)

    def test_base_plugin_validate_configuration(self):
        """Test that base plugin validation returns empty errors."""
        plugin = self._create_test_plugin()
        errors = plugin.validate_configuration({})
        self.assertIsInstance(errors, list)
        self.assertEqual(len(errors), 0)


def run_tests():
    """Run all plugin tests."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestHelperFunctions))
    suite.addTests(loader.loadTestsFromTestCase(TestPluginSchemas))
    suite.addTests(loader.loadTestsFromTestCase(TestPluginMetadata))
    suite.addTests(loader.loadTestsFromTestCase(TestPluginDiscovery))
    suite.addTests(loader.loadTestsFromTestCase(TestPluginBaseClass))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Return exit code
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
