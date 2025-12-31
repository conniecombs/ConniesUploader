# modules/plugins/vipr.py
import customtkinter as ctk
import threading
from .base import ImageHostPlugin
from .. import api
from ..widgets import MouseWheelComboBox
from loguru import logger
import keyring

class ViprPlugin(ImageHostPlugin):
    @property
    def id(self): return "vipr.im"
    @property
    def name(self): return "Vipr.im"

    def __init__(self):
        self.vipr_galleries_map = {}
        self.cb_gallery = None

    def render_settings(self, parent, settings):
        vars = {
            'thumb': ctk.StringVar(value=settings.get('vipr_thumb', "170x170")),
            'cover_count': ctk.StringVar(value=str(settings.get('vipr_cover_count', "0"))),
            'links': ctk.BooleanVar(value=settings.get('vipr_links', False)),
            'gallery': ctk.StringVar()
        }
        
        ctk.CTkLabel(parent, text="Requires Credentials", text_color="red").pack(pady=5)
        
        ctk.CTkLabel(parent, text="Thumb Size:").pack(anchor="w")
        MouseWheelComboBox(parent, variable=vars['thumb'], values=["100x100", "170x170", "250x250", "300x300", "350x350", "500x500", "800x800"]).pack(fill="x")
        
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", pady=5)
        ctk.CTkLabel(f, text="Covers:", width=60).pack(side="left")
        MouseWheelComboBox(f, variable=vars['cover_count'], values=[str(i) for i in range(11)], width=80).pack(side="left", padx=5)
        
        ctk.CTkCheckBox(parent, text="Links.txt", variable=vars['links']).pack(anchor="w", pady=5)
        
        # Gallery Refresh Logic
        ctk.CTkButton(parent, text="Refresh Galleries / Login", command=lambda: self._refresh_galleries(parent)).pack(fill="x", pady=10)
        
        self.cb_gallery = MouseWheelComboBox(parent, variable=vars['gallery'], values=["None"])
        self.cb_gallery.pack(fill="x")
        
        return vars

    def _refresh_galleries(self, parent_widget):
        u = keyring.get_password("ImageUploader:vipr_user", "user")
        p = keyring.get_password("ImageUploader:vipr_pass", "pass")
        
        if not u: 
            return
        
        def _task():
            try:
                # Use the API wrapper which now calls the Go Sidecar
                creds = {'vipr_user': u, 'vipr_pass': p}
                meta = api.get_vipr_metadata(creds)
                
                if meta and meta.get('galleries'):
                    self.vipr_galleries_map = {g['name']: g['id'] for g in meta['galleries']}
                    names = ["None"] + list(self.vipr_galleries_map.keys())
                    self.cb_gallery.configure(values=names)
            except Exception as e:
                logger.error(f"Vipr Refresh Error: {e}")
        
        threading.Thread(target=_task, daemon=True).start()

    def get_configuration(self, ui_handle):
        gal_name = ui_handle['gallery'].get()
        gal_id = self.vipr_galleries_map.get(gal_name, "0")
        return {
            'vipr_thumb': ui_handle['thumb'].get(),
            'vipr_cover_count': int(ui_handle['cover_count'].get() or 0),
            'vipr_links': ui_handle['links'].get(),
            'vipr_gal_id': gal_id
        }
    
    # REMOVED: initialize_session, upload_file (Go handles this now)