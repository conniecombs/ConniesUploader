# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Plugin manager with automatic discovery."""

import importlib
import inspect
import pkgutil
import re
from typing import Dict, List, Optional, Tuple

from loguru import logger

import modules.plugins
from . import config
from .plugins.base import ImageHostPlugin

PRIORITY_CRITICAL = 10
PRIORITY_HIGH = 25
PRIORITY_MEDIUM = 50
PRIORITY_LOW = 75


class PluginManager:
    """Manages image hosting plugins with automatic discovery."""

    def __init__(self):
        self._plugins: Dict[str, ImageHostPlugin] = {}
        self.load_errors: List[tuple] = []
        self.load_plugins()

    def discover_plugins(self) -> None:
        """Backward-compatible alias for older callers/tests."""
        self.load_plugins()

    def load_plugins(self) -> None:
        """Discover and load all plugins from the plugins package."""
        logger.info("Discovering plugins in modules.plugins package")
        plugin_modules = [name for _, name, _ in pkgutil.iter_modules(modules.plugins.__path__)]
        logger.debug(f"Found {len(plugin_modules)} potential plugin modules: {plugin_modules}")

        for module_name in sorted(plugin_modules):
            if module_name in ["__init__", "base", "schema_renderer", "helpers"]:
                logger.debug(f"Skipping special module: {module_name}")
                continue
            if module_name.endswith("_legacy"):
                logger.debug(f"Skipping legacy file: {module_name}")
                continue

            try:
                module = importlib.import_module(f"modules.plugins.{module_name}")
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, ImageHostPlugin) and obj != ImageHostPlugin:
                        try:
                            instance = obj()
                            plugin_id = instance.id
                            self._plugins[plugin_id] = instance
                            version = instance.metadata.get("version", "unknown")
                            impl = instance.metadata.get("implementation", "unknown")
                            logger.info(
                                f"✓ Loaded plugin: {instance.name} "
                                f"(v{version}, {impl}, id={plugin_id})"
                            )
                        except Exception as exc:
                            logger.error(f"Failed to instantiate {name}: {exc}")
                            self.load_errors.append((module_name, name, str(exc)))
            except Exception as exc:
                logger.error(f"Failed to import {module_name}: {exc}")
                self.load_errors.append((module_name, None, str(exc)))

        self._plugins = dict(
            sorted(
                self._plugins.items(),
                key=lambda item: (item[1].metadata.get("priority", PRIORITY_MEDIUM), item[0]),
            )
        )
        logger.info(f"Plugin discovery complete: {len(self._plugins)} plugins loaded")

    def _get_priority_label(self, priority: int) -> str:
        if priority < 25:
            return "CRITICAL"
        if priority < 50:
            return "HIGH"
        if priority == 50:
            return "MEDIUM"
        if priority < 75:
            return "MEDIUM-"
        if priority <= 100:
            return "LOW"
        return "CUSTOM"

    def get_plugin(self, plugin_id: str) -> Optional[ImageHostPlugin]:
        plugin_id = config.normalize_service_id(plugin_id)
        return self._plugins.get(plugin_id)

    def get_all_plugins(self) -> List[ImageHostPlugin]:
        return list(self._plugins.values())

    def get_service_names(self) -> List[str]:
        return list(self._plugins.keys())

    def get_plugin_count(self) -> int:
        return len(self._plugins)

    def get_load_errors(self) -> List[tuple]:
        return self.load_errors

    def reload_plugins(self) -> None:
        logger.info("Reloading plugins...")
        self._plugins.clear()
        self.load_errors.clear()
        self.load_plugins()

    @staticmethod
    def parse_version(version_str: str) -> Tuple[int, int, int]:
        match = re.match(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(version_str))
        if not match:
            logger.warning(f"Invalid version format: {version_str}, defaulting to 0.0.0")
            return (0, 0, 0)
        return (
            int(match.group(1)) if match.group(1) else 0,
            int(match.group(2)) if match.group(2) else 0,
            int(match.group(3)) if match.group(3) else 0,
        )

    @staticmethod
    def compare_versions(version1: str, version2: str) -> int:
        v1 = PluginManager.parse_version(version1)
        v2 = PluginManager.parse_version(version2)
        if v1 < v2:
            return -1
        if v1 > v2:
            return 1
        return 0

    def get_plugin_versions(self) -> Dict[str, str]:
        return {
            plugin_id: plugin.metadata.get("version", "unknown")
            for plugin_id, plugin in self._plugins.items()
        }

    def get_plugin_info(self, plugin_id: str) -> Optional[Dict[str, object]]:
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
        plugin = self.get_plugin(plugin_id)
        if not plugin:
            logger.warning(f"Plugin {plugin_id} not found")
            return False
        current_version = plugin.metadata.get("version", "0.0.0")
        if self.compare_versions(new_version, current_version) > 0:
            logger.info(f"Update available for {plugin_id}: {current_version} -> {new_version}")
            return True
        logger.debug(f"Version {new_version} is not newer than {current_version} for {plugin_id}")
        return False

    def get_all_plugin_info(self) -> List[Optional[Dict[str, object]]]:
        return [self.get_plugin_info(plugin_id) for plugin_id in self._plugins.keys()]
