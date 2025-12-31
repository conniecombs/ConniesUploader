# modules/plugin_manager.py
"""
Plugin Manager with Automatic Discovery (Phase 3).

Automatically discovers and loads all plugins from the plugins folder.
No manual registration required - just drop a plugin file and it's loaded!
"""

import importlib
import inspect
from pathlib import Path
from typing import Dict, List
from loguru import logger

from .plugins.base import ImageHostPlugin


class PluginManager:
    """
    Manages image hosting plugins with automatic discovery.

    Features:
        - Auto-discovers plugins from plugins folder
        - No manual registration needed
        - Handles load errors gracefully
        - Sorts plugins by priority/name
        - Skip files: __init__.py, base.py, schema_renderer.py, *_legacy.py
    """

    def __init__(self):
        self._plugins: Dict[str, ImageHostPlugin] = {}
        self.load_errors: List[tuple] = []  # Track failed loads
        self.load_plugins()

    def load_plugins(self) -> None:
        """
        Automatically discover and load all plugins from the plugins folder.

        Discovery process:
            1. Find all .py files in modules/plugins/
            2. Skip special files (__init__, base, schema_renderer, *_legacy)
            3. Import each module
            4. Find classes inheriting from ImageHostPlugin
            5. Instantiate and register each plugin

        Plugins are sorted by:
            - metadata.priority (if defined, lower = higher priority)
            - id (alphabetically if no priority)
        """
        plugins_dir = Path(__file__).parent / "plugins"

        # Find all .py files in plugins directory
        plugin_files = sorted(plugins_dir.glob("*.py"))

        logger.info(f"Discovering plugins in {plugins_dir}")

        for plugin_file in plugin_files:
            # Skip special files
            if plugin_file.stem in ["__init__", "base", "schema_renderer"]:
                continue

            # Skip legacy backup files
            if plugin_file.stem.endswith("_legacy") or plugin_file.stem.endswith("_v2"):
                logger.debug(f"Skipping legacy file: {plugin_file.stem}")
                continue

            try:
                # Import the module
                module_name = f"modules.plugins.{plugin_file.stem}"
                module = importlib.import_module(module_name)

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
                            self.load_errors.append((plugin_file.stem, name, str(e)))

            except Exception as e:
                error_msg = f"Failed to import {plugin_file.stem}: {e}"
                logger.error(error_msg)
                self.load_errors.append((plugin_file.stem, None, str(e)))

        # Sort plugins by priority (if defined) or alphabetically by ID
        self._plugins = dict(
            sorted(
                self._plugins.items(),
                key=lambda x: (
                    x[1].metadata.get("priority", 50),  # Default priority: 50
                    x[0],  # Fallback: sort by ID
                ),
            )
        )

        logger.info(f"Plugin discovery complete: {len(self._plugins)} plugins loaded")

        if self.load_errors:
            logger.warning(f"Plugin load errors: {len(self.load_errors)}")
            for file, cls, error in self.load_errors:
                logger.warning(f"  - {file}.{cls or '?'}: {error}")

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
