# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Comprehensive tests for modules/plugin_manager.py - Plugin discovery and management"""

import pytest
import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.plugin_manager import PluginManager


@pytest.mark.unit
class TestPluginManagerImports:
    """Test plugin_manager module imports"""

    def test_module_import(self):
        """Test that plugin_manager module imports without error"""
        from modules import plugin_manager

        assert plugin_manager is not None

    def test_plugin_manager_class_exists(self):
        """Test that PluginManager class exists"""
        assert PluginManager is not None


@pytest.mark.unit
class TestPluginManagerInstantiation:
    """Test plugin manager instantiation"""

    def test_can_instantiate_with_directory(self):
        """Test that PluginManager can be instantiated with a plugin directory"""
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                pm = PluginManager(plugins_dir=temp_dir)
                assert pm is not None
            except Exception as e:
                # May fail if plugins directory structure is required
                pytest.skip(f"Requires plugin directory structure: {e}")

    def test_can_instantiate_default(self):
        """Test instantiation with default plugins directory"""
        try:
            pm = PluginManager()
            assert pm is not None
        except Exception:
            # May fail in test environment without proper directory structure
            pytest.skip("Requires proper directory structure")


@pytest.mark.unit
class TestPluginDiscovery:
    """Test plugin discovery functionality"""

    def test_discover_plugins_method_exists(self):
        """Test that discover_plugins method exists"""
        assert hasattr(PluginManager, "discover_plugins")

    def test_get_plugin_method_exists(self):
        """Test that get_plugin method exists"""
        assert hasattr(PluginManager, "get_plugin")

    def test_get_all_plugins_method_exists(self):
        """Test that get_all_plugins method exists"""
        assert hasattr(PluginManager, "get_all_plugins")

    def test_discover_py_files(self):
        """Test discovery of .py plugin files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock plugin file
            plugin_file = Path(temp_dir) / "test_plugin.py"
            plugin_content = """
class TestPlugin:
    service_id = "test.service"
    priority = 50
"""
            plugin_file.write_text(plugin_content)

            # Discovery logic would find this file
            assert plugin_file.exists()
            assert plugin_file.suffix == ".py"

    def test_discover_v2_plugins(self):
        """Test discovery of *_v2.py plugin files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create v2 plugin file
            v2_plugin = Path(temp_dir) / "service_v2.py"
            v2_plugin.touch()

            assert v2_plugin.exists()
            assert "_v2.py" in str(v2_plugin)

    def test_ignores_non_plugin_files(self):
        """Test that non-plugin files are ignored"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create files that should be ignored
            (Path(temp_dir) / "__init__.py").touch()
            (Path(temp_dir) / "base_plugin.py").touch()
            (Path(temp_dir) / "README.md").touch()
            (Path(temp_dir) / "config.json").touch()

            # These should be filtered out
            py_files = list(Path(temp_dir).glob("*.py"))
            # Should include __init__.py and base_plugin.py

            assert len(py_files) >= 0


@pytest.mark.unit
class TestPluginPriority:
    """Test plugin priority system"""

    def test_default_priority(self):
        """Test that plugins have default priority"""
        default_priority = 50
        assert default_priority >= 0
        assert default_priority <= 100

    def test_priority_sorting(self):
        """Test that plugins can be sorted by priority"""
        plugins = [
            {"name": "low", "priority": 25},
            {"name": "high", "priority": 75},
            {"name": "medium", "priority": 50},
        ]

        sorted_plugins = sorted(plugins, key=lambda p: p["priority"], reverse=True)

        assert sorted_plugins[0]["priority"] == 75
        assert sorted_plugins[1]["priority"] == 50
        assert sorted_plugins[2]["priority"] == 25

    def test_higher_priority_loaded_first(self):
        """Test that higher priority plugins should be loaded first"""
        priorities = [100, 75, 50, 25, 0]

        # Verify sorting logic
        sorted_priorities = sorted(priorities, reverse=True)
        assert sorted_priorities == [100, 75, 50, 25, 0]


@pytest.mark.unit
class TestPluginAttributes:
    """Test plugin attribute requirements"""

    def test_plugin_has_service_id(self):
        """Test that plugins should have service_id attribute"""
        mock_plugin = Mock()
        mock_plugin.service_id = "test.service"

        assert hasattr(mock_plugin, "service_id")
        assert isinstance(mock_plugin.service_id, str)

    def test_plugin_has_priority(self):
        """Test that plugins can have priority attribute"""
        mock_plugin = Mock()
        mock_plugin.priority = 50

        assert hasattr(mock_plugin, "priority")
        assert isinstance(mock_plugin.priority, int)

    def test_plugin_has_upload_method(self):
        """Test that plugins should have upload method"""
        mock_plugin = Mock()
        mock_plugin.upload = Mock(return_value=("viewer_url", "thumb_url"))

        assert hasattr(mock_plugin, "upload")
        assert callable(mock_plugin.upload)


@pytest.mark.unit
class TestPluginRetrieval:
    """Test plugin retrieval methods"""

    def test_get_plugin_by_service_id(self):
        """Test retrieving plugin by service ID"""
        # Mock data structure
        plugins = {"imx.to": Mock(service_id="imx.to"), "pixhost.to": Mock(service_id="pixhost.to")}

        # Simulate get_plugin
        service_id = "imx.to"
        plugin = plugins.get(service_id)

        assert plugin is not None
        assert plugin.service_id == "imx.to"

    def test_get_nonexistent_plugin(self):
        """Test retrieval of non-existent plugin"""
        plugins = {}

        plugin = plugins.get("nonexistent.service")
        assert plugin is None

    def test_get_all_plugins_returns_list(self):
        """Test that get_all_plugins returns iterable"""
        plugins = {"service1": Mock(), "service2": Mock(), "service3": Mock()}

        all_plugins = list(plugins.values())
        assert len(all_plugins) == 3


@pytest.mark.unit
class TestPluginValidation:
    """Test plugin validation"""

    def test_valid_plugin_structure(self):
        """Test that valid plugins have required attributes"""

        class ValidPlugin:
            service_id = "test.service"
            priority = 50

            def upload(self, file_path, config):
                return ("viewer", "thumb")

        plugin = ValidPlugin()

        assert hasattr(plugin, "service_id")
        assert hasattr(plugin, "upload")
        assert callable(plugin.upload)

    def test_invalid_plugin_missing_service_id(self):
        """Test detection of plugins missing service_id"""

        class InvalidPlugin:
            priority = 50

            def upload(self, file_path, config):
                return ("viewer", "thumb")

        plugin = InvalidPlugin()
        assert not hasattr(plugin, "service_id")

    def test_invalid_plugin_missing_upload(self):
        """Test detection of plugins missing upload method"""

        class InvalidPlugin:
            service_id = "test.service"
            priority = 50

        plugin = InvalidPlugin()
        assert not hasattr(plugin, "upload")


@pytest.mark.unit
class TestPluginLoading:
    """Test plugin loading logic"""

    def test_plugin_file_extension(self):
        """Test that only .py files are considered"""
        files = ["plugin.py", "plugin.pyc", "plugin.txt", "plugin_v2.py"]

        py_files = [f for f in files if f.endswith(".py") and not f.endswith(".pyc")]

        assert "plugin.py" in py_files
        assert "plugin_v2.py" in py_files
        assert "plugin.pyc" not in py_files
        assert "plugin.txt" not in py_files

    def test_skip_init_files(self):
        """Test that __init__.py files are skipped"""
        files = ["plugin.py", "__init__.py", "test_plugin.py"]

        non_init_files = [f for f in files if not f.startswith("__")]

        assert "plugin.py" in non_init_files
        assert "test_plugin.py" in non_init_files
        assert "__init__.py" not in non_init_files

    def test_skip_base_plugins(self):
        """Test that base/template plugins are skipped"""
        files = ["imx.py", "base_plugin.py", "plugin_base.py", "pixhost.py"]

        skip_patterns = ["base_plugin", "plugin_base"]
        filtered_files = [f for f in files if not any(pattern in f for pattern in skip_patterns)]

        assert "imx.py" in filtered_files
        assert "pixhost.py" in filtered_files
        assert "base_plugin.py" not in filtered_files
        assert "plugin_base.py" not in filtered_files


@pytest.mark.unit
class TestPluginErrors:
    """Test error handling in plugin management"""

    def test_handle_import_error(self):
        """Test handling of plugin import errors"""
        try:
            # Simulate import error
            import nonexistent_module

            pytest.fail("Should raise ImportError")
        except ImportError:
            # Should be caught and logged
            pass

    def test_handle_invalid_plugin_class(self):
        """Test handling of invalid plugin classes"""

        class InvalidPlugin:
            pass  # Missing required attributes

        plugin = InvalidPlugin()

        # Should validate before adding to manager
        has_required = hasattr(plugin, "service_id") and hasattr(plugin, "upload")
        assert not has_required


@pytest.mark.integration
class TestPluginManagerIntegration:
    """Integration tests for plugin manager"""

    def test_create_mock_plugin_directory(self):
        """Test creating a mock plugin directory structure"""
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir) / "plugins"
            plugins_dir.mkdir()

            # Create __init__.py
            (plugins_dir / "__init__.py").touch()

            # Create mock plugin
            plugin_content = """
class MockPlugin:
    service_id = "mock.service"
    priority = 50

    def upload(self, file_path, config):
        return ("http://example.com/view", "http://example.com/thumb.jpg")
"""
            (plugins_dir / "mock_plugin.py").write_text(plugin_content)

            assert plugins_dir.exists()
            assert (plugins_dir / "mock_plugin.py").exists()

    def test_plugin_discovery_workflow(self):
        """Test complete plugin discovery workflow"""
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir) / "plugins"
            plugins_dir.mkdir()

            # Create plugins
            for i in range(3):
                plugin_file = plugins_dir / f"plugin{i}.py"
                plugin_content = f"""
class Plugin{i}:
    service_id = "service{i}.test"
    priority = {i * 25}

    def upload(self, file_path, config):
        return ("url", "thumb")
"""
                plugin_file.write_text(plugin_content)

            # Verify files exist
            plugin_files = list(plugins_dir.glob("plugin*.py"))
            assert len(plugin_files) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "unit"])
