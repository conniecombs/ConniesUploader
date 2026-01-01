# modules/plugins/imx.py
import customtkinter as ctk
from .base import ImageHostPlugin
from .. import api
from ..widgets import MouseWheelComboBox

class ImxPlugin(ImageHostPlugin):
    @property
    def id(self): return "imx.to"
    @property
    def name(self): return "IMX.to"

    def render_settings(self, parent, settings):
        vars = {
            'thumb': ctk.StringVar(value=settings.get('imx_thumb', "180")),
            'format': ctk.StringVar(value=settings.get('imx_format', "Fixed Width")),
            'gallery': ctk.StringVar(value=settings.get('gallery_id', "")),
            'links': ctk.BooleanVar(value=settings.get('imx_links', False)),
            'cover_count': ctk.StringVar(value=str(settings.get('imx_cover_count', "0")))
        }

        ctk.CTkLabel(parent, text="Requires Credentials (set in Tools)", text_color="red").pack(pady=5)
        
        ctk.CTkLabel(parent, text="Thumb Size:").pack(anchor="w")
        MouseWheelComboBox(parent, variable=vars['thumb'], values=["100","180","250","300","600"]).pack(fill="x")
        
        ctk.CTkLabel(parent, text="Format:").pack(anchor="w")
        MouseWheelComboBox(parent, variable=vars['format'], values=["Fixed Width", "Fixed Height", "Proportional", "Square"]).pack(fill="x")
        
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", pady=5)
        ctk.CTkLabel(f, text="Covers:", width=60).pack(side="left")
        MouseWheelComboBox(f, variable=vars['cover_count'], values=[str(i) for i in range(11)], width=80).pack(side="left", padx=5)

        ctk.CTkCheckBox(parent, text="Links.txt", variable=vars['links']).pack(anchor="w", pady=5)
        
        ctk.CTkLabel(parent, text="Gallery ID:").pack(anchor="w", pady=(10,0))
        ctk.CTkEntry(parent, textvariable=vars['gallery']).pack(fill="x")
        
        return vars

    def get_configuration(self, ui_handle):
        return {
            'imx_thumb_id': ui_handle['thumb'].get(), # Mapped to Go config key
            'imx_format_id': ui_handle['format'].get(),
            'gallery_id': ui_handle['gallery'].get(),
            'imx_links': ui_handle['links'].get(),
            'imx_cover_count': int(ui_handle['cover_count'].get() or 0)
        }

    def prepare_group(self, group, config, context, creds):
        """
        Called before the batch upload starts.
        Always creates a gallery with the folder name if no manual gallery_id is specified.
        """
        # If user manually specified a gallery_id, use it
        manual_gid = config.get('gallery_id', '').strip()
        if manual_gid:
            return

        # Otherwise, always create a gallery with the folder name
        user = creds.get('imx_user')
        pwd = creds.get('imx_pass')

        if user and pwd:
            # Use the API wrapper which calls Sidecar action="create_gallery"
            gid = api.create_imx_gallery(user, pwd, group.title)

            if gid:
                # Store the new Gallery ID in the group object
                group.gallery_id = gid
                # Also update the config for this specific run so the uploader sees it
                config['gallery_id'] = gid

    # REMOVED: initialize_session, upload_file (Go handles this now)