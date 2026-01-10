# modules/settings_manager.py
import json
import os
from . import config


class SettingsManager:
    def __init__(self):
        self.filepath = config.SETTINGS_FILE
        # UPDATED: Changed booleans (*_cover) to integers (*_cover_count)
        self.defaults = {
            "service": "imx.to",
            "global_worker_count": 8,  # Main job queue dispatcher workers
            "imx_thumb": "180",
            "imx_format": "Fixed Width",
            "imx_cover_count": 0,  # Was imx_cover
            "imx_links": False,
            "imx_threads": 5,
            "pix_content": "Safe",
            "pix_thumb": "200",
            "pix_cover_count": 0,  # Was pix_cover
            "pix_links": False,
            "pix_mk_gal": False,
            "pix_threads": 3,
            "turbo_content": "Safe",
            "turbo_thumb": "180",
            "turbo_cover_count": 0,  # Was turbo_cover
            "turbo_threads": 2,
            "output_format": "BBCode",
            "auto_copy": False,
            "separate_batches": False,
            "show_previews": True,
            # Viper/ImageBam Defaults
            "vipr_thumb": "170x170",
            "vipr_cover_count": 0,  # Was vipr_cover
            "vipr_threads": 1,
            "imagebam_content": "Safe",
            "imagebam_thumb": "180",
            # ImageBam doesn't typically have a specific "Cover" setting in API,
            # but we'll add the key for consistency if needed later.
            "imagebam_cover_count": 0,
            "imagebam_threads": 2,
        }

    def load(self):
        if not os.path.exists(self.filepath):
            return self.defaults
        try:
            with open(self.filepath, "r") as f:
                data = json.load(f)
                return {**self.defaults, **data}
        except Exception:
            return self.defaults

    def save(self, data):
        try:
            with open(self.filepath, "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Failed to save settings: {e}")
