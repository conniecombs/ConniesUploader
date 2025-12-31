# modules/plugins/turbo.py
import customtkinter as ctk
import os
from .base import ImageHostPlugin
from .. import api
from ..widgets import MouseWheelComboBox
from loguru import logger

class TurboPlugin(ImageHostPlugin):
    @property
    def id(self): return "turboimagehost"
    @property
    def name(self): return "TurboImageHost"

    def render_settings(self, parent, settings):
        vars = {
            'content': ctk.StringVar(value=settings.get('turbo_content', "Safe")),
            'thumb': ctk.StringVar(value=settings.get('turbo_thumb', "180")),
            'cover_count': ctk.StringVar(value=str(settings.get('turbo_cover_count', "0"))),
            'links': ctk.BooleanVar(value=settings.get('turbo_links', False)),
            'gallery': ctk.StringVar(value=settings.get('turbo_gal_id', ""))
        }
        ctk.CTkLabel(parent, text="Login Optional", text_color="red").pack(pady=5)
        ctk.CTkLabel(parent, text="Thumb Size:").pack(anchor="w")
        MouseWheelComboBox(parent, variable=vars['thumb'], values=["150","200","250","300","350","400","500","600"]).pack(fill="x")
        
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", pady=5)
        ctk.CTkLabel(f, text="Covers:", width=60).pack(side="left")
        MouseWheelComboBox(f, variable=vars['cover_count'], values=[str(i) for i in range(11)], width=80).pack(side="left", padx=5)

        ctk.CTkCheckBox(parent, text="Links.txt", variable=vars['links']).pack(anchor="w", pady=5)
        ctk.CTkLabel(parent, text="Gallery ID:").pack(anchor="w")
        ctk.CTkEntry(parent, textvariable=vars['gallery']).pack(fill="x")
        
        return vars

    def get_configuration(self, ui_handle):
        return {
            'content': "Adult" if ui_handle['content'].get() == "Adult" else "Safe", # Turbo usually just safe/adult? logic in api.py is 'adult' or 'all'
            'thumb_size': ui_handle['thumb'].get(),
            'cover_limit': int(ui_handle['cover_count'].get() or 0),
            'save_links': ui_handle['links'].get(),
            'gallery_id': ui_handle['gallery'].get()
        }

    def initialize_session(self, config, creds):
        client = api.create_resilient_client()
        context = {'client': client, 'cookies': None, 'endpoint': "https://www.turboimagehost.com/upload_html5.tu"}
        
        # 1. Get Config/Endpoint
        ep = api.get_turbo_config(client=client)
        if ep: context['endpoint'] = ep
        
        # 2. Login
        user = creds.get('turbo_user')
        pwd = creds.get('turbo_pass')
        if user and pwd:
            cookies = api.turbo_login(user, pwd, client=client)
            if cookies: context['cookies'] = cookies
        
        return context

    def upload_file(self, file_path, group, config, context, progress_callback):
        client = context['client']
        # Apply cookies if present
        if context.get('cookies'):
            client.cookies.update(context['cookies'])
            
        is_cover = False
        if hasattr(group, 'files'):
            try:
                idx = group.files.index(file_path)
                if idx < config.get('cover_limit', 0): is_cover = True
            except: pass
            
        thumb = "600" if is_cover else config['thumb_size']
        
        uploader = api.TurboUploader(
            file_path,
            os.path.basename(file_path),
            lambda m: progress_callback(m.bytes_read/m.len) if m.len > 0 else None,
            context['endpoint'],
            api.generate_turbo_upload_id(),
            config['content'],
            thumb,
            config.get('gallery_id'),
            client=client
        )
        
        try:
            url, data, headers = uploader.get_request_params()
            if 'Content-Length' not in headers and hasattr(data, 'len'):
                headers['Content-Length'] = str(data.len)
            r = client.post(url, headers=headers, data=data, timeout=300)
            try: resp = r.json()
            except: resp = r.text
            return uploader.parse_response(resp)
        finally:
            uploader.close()