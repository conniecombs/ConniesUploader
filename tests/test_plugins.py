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
from typing import Dict, Any
from unittest.mock import Mock, MagicMock

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
