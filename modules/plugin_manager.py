# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/plugin_manager.py
"""
Plugin Manager with Automatic Discovery (Phase 3).

Automatically discovers and loads all plugins from the plugins folder.
No manual registration required - just drop a plugin file and it's loaded!

Plugin Priority System:
    Plugins are sorted by their priority value (0-100 scale):
    - Lower values = Higher priority (loaded first)
    - Priority 0-24:  Critical/System plugins
    - Priority 25-49: High priority plugins
    - Priority 50:    Default priority (MEDIUM)
    - Priority 51-74: Lower priority plugins
    - Priority 75-100: Lowest priority plugins

    Use the constants defined below to set plugin priorities:
    - PRIORITY_CRITICAL = 10
    - PRIORITY_HIGH = 25
    - PRIORITY_MEDIUM = 50 (default)
    - PRIORITY_LOW = 75

    Example in plugin metadata:
        metadata = {
            "priority": PRIORITY_HIGH,  # Load before default plugins
            "version": "1.0.0",
            ...
        }
"""

import importlib
import inspect
import pkgutil
from typing import Dict, List, Tuple, Optional
from loguru import logger
import re

from .plugins.base import ImageHostPlugin
import modules.plugins


# Plugin Priority Constants (0-100 scale, lower = higher priority)
PRIORITY_CRITICAL = 10  # Critical/system plugins (highest priority)
PRIORITY_HIGH = 25  # High priority plugins
PRIORITY_MEDIUM = 50  # Default priority
PRIORITY_LOW = 75  # Low priority plugins


class PluginManager:
    """
    Manages image hosting plugins with automatic discovery.

    Features:
        - Auto-discovers plugins from plugins folder
        - No manual registration needed
        - Handles load errors gracefully
        - Sorts plugins by priority (0-100 scale, lower = higher priority)
        - Logs load order for debugging
        - Skip files: __init__.py, base.py, schema_renderer.py, *_legacy.py

    Priority System:
        Plugins are sorted by priority value (default: PRIORITY_MEDIUM = 50).
        Use priority constants: PRIORITY_CRITICAL (10), PRIORITY_HIGH (25),
        PRIORITY_MEDIUM (50), PRIORITY_LOW (75) in plugin metadata.

    Example:
        Plugin metadata with high priority:
        metadata = {
            "priority": PRIORITY_HIGH,  # Load before default plugins
            "version": "1.0.0",
            ...
        }
    """

    def __init__(self):
        self._plugins: Dict[str, ImageHostPlugin] = {}
        self.load_errors: List[tuple] = []  # Track failed loads
        self.load_plugins()

    def load_plugins(self) -> None:
        """
        Automatically discover and load all plugins from the plugins folder.

        Discovery process:
            1. Use pkgutil to discover modules in modules/plugins/ (works with PyInstaller)
            2. Skip special files (__init__, base, schema_renderer, helpers, *_legacy)
            3. Import each module
            4. Find classes inheriting from ImageHostPlugin
            5. Instantiate and register each plugin

        Plugins are sorted by:
            - metadata.priority (if defined, lower = higher priority)
            - id (alphabetically if no priority)
        """
        logger.info(f"Discovering plugins in modules.plugins package")

        # Use pkgutil.iter_modules which works in both dev and PyInstaller builds
        # This is the standard way to discover modules in a package
        plugin_modules = [name for _, name, _ in pkgutil.iter_modules(modules.plugins.__path__)]

        logger.debug(f"Found {len(plugin_modules)} potential plugin modules: {plugin_modules}")

        for module_name in sorted(plugin_modules):
            # Skip special files
            if module_name in ["__init__", "base", "schema_renderer", "helpers"]:
                logger.debug(f"Skipping special module: {module_name}")
                continue

            # Skip legacy backup files
            if module_name.endswith("_legacy"):
                logger.debug(f"Skipping legacy file: {module_name}")
                continue

            try:
                # Import the module
                full_module_name = f"modules.plugins.{module_name}"
                module = importlib.import_module(full_module_name)

                # Find all classes that inherit from ImageHostPlugin
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    # Check if it's a plugin class (not the base class itself)
                    if issubclass(obj, ImageHostPlugin) and obj != ImageHostPlugin:
                        try:
                            # Instantiate the plugin
                            instance = obj()

                            # Register by plugin ID
                            plugin_id = instance.id
                            self._plugins[plugin_id] = instance

                            # Get version from metadata
                            version = instance.metadata.get("version", "unknown")
                            impl = instance.metadata.get("implementation", "unknown")

                            logger.info(
                                f"✓ Loaded plugin: {instance.name} "
                                f"(v{version}, {impl}, id={plugin_id})"
                            )

                        except Exception as e:
                            error_msg = f"Failed to instantiate {name}: {e}"
                            logger.error(error_msg)
                            self.load_errors.append((module_name, name, str(e)))

            except Exception as e:
                error_msg = f"Failed to import {module_name}: {e}"
                logger.error(error_msg)
                self.load_errors.append((module_name, None, str(e)))

        # Sort plugins by priority (if defined) or alphabetically by ID
        self._plugins = dict(
            sorted(
                self._plugins.items(),
                key=lambda x: (
                    x[1].metadata.get("priority", PRIORITY_MEDIUM),  # Default: PRIORITY_MEDIUM (50)
                    x[0],  # Fallback: sort by ID
                ),
            )
        )

        logger.info(f"Plugin discovery complete: {len(self._plugins)} plugins loaded")

        # Log plugin load order with priorities for debugging
        logger.info("Plugin load order (by priority):")
        for plugin_id, plugin in self._plugins.items():
            priority = plugin.metadata.get("priority", PRIORITY_MEDIUM)
            priority_label = self._get_priority_label(priority)
            logger.info(f"  [{priority:3d}] {priority_label:8s} - {plugin.name} (id={plugin_id})")

        if self.load_errors:
            logger.warning(f"Plugin load errors: {len(self.load_errors)}")
            for file, cls, error in self.load_errors:
                logger.warning(f"  - {file}.{cls or '?'}: {error}")

    def _get_priority_label(self, priority: int) -> str:
        """
        Convert priority number to human-readable label.

        Args:
            priority: Priority value (0-100)

        Returns:
            Priority label (CRITICAL, HIGH, MEDIUM, LOW, or CUSTOM)
        """
        if priority < 25:
            return "CRITICAL"
        elif priority < 50:
            return "HIGH"
        elif priority == 50:
            return "MEDIUM"
        elif priority < 75:
            return "MEDIUM-"
        elif priority <= 100:
            return "LOW"
        else:
            return "CUSTOM"

    def get_plugin(self, plugin_id: str) -> ImageHostPlugin:
        """
        Get a plugin by its ID.

        Args:
            plugin_id: Plugin identifier (e.g., 'pixhost.to')

        Returns:
            Plugin instance or None if not found
        """
        return self._plugins.get(plugin_id)

    def get_all_plugins(self) -> List[ImageHostPlugin]:
        """
        Get all loaded plugins.

        Returns:
            List of plugin instances (sorted by priority/name)
        """
        return list(self._plugins.values())

    def get_service_names(self) -> List[str]:
        """
        Get list of plugin IDs (service names).

        Returns:
            List of plugin IDs in priority order

        Note: This now returns plugins in auto-discovered order
        (priority-based or alphabetical) instead of hardcoded order.
        """
        return list(self._plugins.keys())

    def get_plugin_count(self) -> int:
        """Get number of loaded plugins."""
        return len(self._plugins)

    def get_load_errors(self) -> List[tuple]:
        """
        Get list of plugin load errors.

        Returns:
            List of (filename, classname, error_message) tuples
        """
        return self.load_errors

    def reload_plugins(self) -> None:
        """
        Reload all plugins (useful for development).

        Warning: This clears all plugins and re-discovers them.
        Any state in plugin instances will be lost.
        """
        logger.info("Reloading plugins...")
        self._plugins.clear()
        self.load_errors.clear()
        self.load_plugins()

    @staticmethod
    def parse_version(version_str: str) -> Tuple[int, int, int]:
        """
        Parse a semantic version string (e.g., "2.1.3") into a tuple.

        Args:
            version_str: Version string in semver format

        Returns:
            Tuple of (major, minor, patch) as integers

        Examples:
            "2.1.3" -> (2, 1, 3)
            "1.0" -> (1, 0, 0)
            "3" -> (3, 0, 0)
        """
        # Extract numbers from version string (handles "v2.1.3" or "2.1.3")
        match = re.match(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(version_str))
        if not match:
            logger.warning(f"Invalid version format: {version_str}, defaulting to 0.0.0")
            return (0, 0, 0)

        major = int(match.group(1)) if match.group(1) else 0
        minor = int(match.group(2)) if match.group(2) else 0
        patch = int(match.group(3)) if match.group(3) else 0

        return (major, minor, patch)

    @staticmethod
    def compare_versions(version1: str, version2: str) -> int:
        """
        Compare two version strings.

        Args:
            version1: First version string
            version2: Second version string

        Returns:
            -1 if version1 < version2
            0 if version1 == version2
            1 if version1 > version2

        Examples:
            compare_versions("2.0.0", "1.9.0") -> 1
            compare_versions("1.5.0", "1.5.0") -> 0
            compare_versions("1.0.0", "2.0.0") -> -1
        """
        v1 = PluginManager.parse_version(version1)
        v2 = PluginManager.parse_version(version2)

        if v1 < v2:
            return -1
        elif v1 > v2:
            return 1
        else:
            return 0

    def get_plugin_versions(self) -> Dict[str, str]:
        """
        Get versions of all loaded plugins.

        Returns:
            Dictionary mapping plugin ID to version string
        """
        return {
            plugin_id: plugin.metadata.get("version", "unknown")
            for plugin_id, plugin in self._plugins.items()
        }

    def get_plugin_info(self, plugin_id: str) -> Optional[Dict[str, any]]:
        """
        Get detailed information about a specific plugin.

        Args:
            plugin_id: Plugin identifier

        Returns:
            Dictionary with plugin information including:
            - id: Plugin ID
            - name: Display name
            - version: Version string
            - author: Author name
            - description: Description
            - implementation: "python" or "go"
            - features: Supported features
            - credentials: Required credentials
            - limits: Service limits
        """
        plugin = self.get_plugin(plugin_id)
        if not plugin:
            return None

        metadata = plugin.metadata

        return {
            "id": plugin.id,
            "name": plugin.name,
            "version": metadata.get("version", "unknown"),
            "author": metadata.get("author", "unknown"),
            "description": metadata.get("description", ""),
            "implementation": metadata.get("implementation", "python"),
            "features": metadata.get("features", {}),
            "credentials": metadata.get("credentials", []),
            "limits": metadata.get("limits", {}),
            "website": metadata.get("website", ""),
        }

    def validate_plugin_update(self, plugin_id: str, new_version: str) -> bool:
        """
        Check if a new version is actually newer than the installed version.

        Args:
            plugin_id: Plugin identifier
            new_version: New version string to check

        Returns:
            True if new_version is newer than installed version, False otherwise
        """
        plugin = self.get_plugin(plugin_id)
        if not plugin:
            logger.warning(f"Plugin {plugin_id} not found")
            return False

        current_version = plugin.metadata.get("version", "0.0.0")

        comparison = self.compare_versions(new_version, current_version)

        if comparison > 0:
            logger.info(f"Update available for {plugin_id}: {current_version} -> {new_version}")
            return True
        else:
            logger.debug(
                f"Version {new_version} is not newer than {current_version} for {plugin_id}"
            )
            return False

    def get_all_plugin_info(self) -> List[Dict[str, any]]:
        """
        Get detailed information for all loaded plugins.

        Returns:
            List of plugin information dictionaries
        """
        return [self.get_plugin_info(plugin_id) for plugin_id in self._plugins.keys()]
