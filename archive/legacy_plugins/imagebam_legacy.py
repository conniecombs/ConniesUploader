# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/plugins/imagebam.py
import customtkinter as ctk
import os
from .base import ImageHostPlugin
from .. import api
from ..widgets import MouseWheelComboBox
from loguru import logger

class ImageBamPlugin(ImageHostPlugin):
    @property
    def id(self): return "imagebam.com"
    @property
    def name(self): return "ImageBam"

    def render_settings(self, parent, settings):
        vars = {
            'content': ctk.StringVar(value=settings.get('imagebam_content', "Safe")),
            'thumb': ctk.StringVar(value=settings.get('imagebam_thumb', "180"))
        }
        ctk.CTkLabel(parent, text="Content Type:").pack(anchor="w")
        MouseWheelComboBox(parent, variable=vars['content'], values=["Safe", "Adult"]).pack(fill="x")
        ctk.CTkLabel(parent, text="Thumb Size:").pack(anchor="w")
        MouseWheelComboBox(parent, variable=vars['thumb'], values=["100", "180", "250", "300"]).pack(fill="x")
        return vars

    def get_configuration(self, ui_handle):
        return {
            'content': ui_handle['content'].get(),
            'thumb_size': ui_handle['thumb'].get()
        }

    def initialize_session(self, config, creds):
        client = api.create_resilient_client()
        context = {'client': client, 'csrf': None, 'cookies': None}
        
        user = creds.get('imagebam_user')
        pwd = creds.get('imagebam_pass')
        if user and pwd:
            api.imagebam_login(user, pwd, client=client)
            
        token, cookies = api.init_imagebam_session(client)
        if token:
            context['csrf'] = token
            context['cookies'] = cookies
        else:
            logger.error("Failed to get IB CSRF token")
        return context

    def prepare_group(self, group, config, context, creds):
        # ImageBam requires a "Session Token" (upload_token) usually per batch or group
        # The original code generated it inside the loop. 
        # We can store it on the group object.
        if context.get('csrf'):
            try:
                # We need a temp client or the main client to get this token
                # Using main client from context is fine
                token_client = context['client']
                
                # Logic from old upload_manager:
                gal_title = group.title if config.get('auto_gallery') else None
                gal_id = "default" 
                
                upload_token = api.get_imagebam_upload_token(
                    token_client, context['csrf'],
                    config.get('content', 'Safe'),
                    config.get('thumb_size', '180'),
                    gal_id, gal_title
                )
                group.ib_upload_token = upload_token
            except Exception as e:
                logger.error(f"ImageBam Token Error: {e}")

    def upload_file(self, file_path, group, config, context, progress_callback):
        client = context['client']
        token = getattr(group, 'ib_upload_token', None)
        if not token: raise ValueError("Upload skipped: No ImageBam Upload Token")
        
        uploader = api.ImageBamUploader(
            file_path, os.path.basename(file_path),
            lambda m: progress_callback(m.bytes_read/m.len) if m.len > 0 else None,
            config['content'], config['thumb_size'],
            upload_token=token, csrf_token=context['csrf'],
            session_cookies=context['cookies'], client=client
        )
        
        try:
            url, data, headers = uploader.get_request_params()
            if 'Content-Length' not in headers and hasattr(data, 'len'):
                headers['Content-Length'] = str(data.len)
            r = client.post(url, headers=headers, data=data, timeout=300)
            return uploader.parse_response(r.json())
        finally:
            uploader.close()