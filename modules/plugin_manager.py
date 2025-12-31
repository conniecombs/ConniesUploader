# modules/plugin_manager.py
from .plugins.base import ImageHostPlugin
from .plugins import imx, turbo, pixhost, vipr, imagebam

class PluginManager:
    def __init__(self):
        self._plugins = {}
        self.load_plugins()

    def load_plugins(self):
        # Register available plugins here
        classes = [
            imx.ImxPlugin,
            pixhost.PixhostPlugin,
            turbo.TurboPlugin,
            vipr.ViprPlugin,
            imagebam.ImageBamPlugin
        ]
        
        for cls in classes:
            instance = cls()
            self._plugins[instance.id] = instance

    def get_plugin(self, plugin_id: str) -> ImageHostPlugin:
        return self._plugins.get(plugin_id)

    def get_all_plugins(self):
        return list(self._plugins.values())

    def get_service_names(self):
        # Return keys, but arguably you might want a specific order
        # For now, let's stick to the order they were defined or a fixed list
        order = ["imx.to", "pixhost.to", "turboimagehost", "vipr.im", "imagebam.com"]
        return [k for k in order if k in self._plugins]