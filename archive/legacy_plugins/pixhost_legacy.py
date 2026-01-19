# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/plugins/pixhost.py
import customtkinter as ctk
import os
from .base import ImageHostPlugin
from .. import api
from ..widgets import MouseWheelComboBox
from loguru import logger

class PixhostPlugin(ImageHostPlugin):
    @property
    def id(self): return "pixhost.to"
    @property
    def name(self): return "Pixhost.to"

    def render_settings(self, parent, settings):
        vars = {
            'content': ctk.StringVar(value=settings.get('pix_content', "Safe")),
            'thumb': ctk.StringVar(value=settings.get('pix_thumb', "200")),
            'cover_count': ctk.StringVar(value=str(settings.get('pix_cover_count', "0"))),
            'links': ctk.BooleanVar(value=settings.get('pix_links', False)),
            'hash': ctk.StringVar(value=settings.get('pix_gallery_hash', ""))
        }
        
        ctk.CTkLabel(parent, text="Content:").pack(anchor="w")
        MouseWheelComboBox(parent, variable=vars['content'], values=["Safe", "Adult"]).pack(fill="x")
        
        ctk.CTkLabel(parent, text="Thumb Size:").pack(anchor="w")
        MouseWheelComboBox(parent, variable=vars['thumb'], values=["150","200","250","300","350","400","450","500"]).pack(fill="x")
        
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", pady=5)
        ctk.CTkLabel(f, text="Covers:", width=60).pack(side="left")
        MouseWheelComboBox(f, variable=vars['cover_count'], values=[str(i) for i in range(11)], width=80).pack(side="left", padx=5)
        
        ctk.CTkCheckBox(parent, text="Links.txt", variable=vars['links']).pack(anchor="w", pady=5)
        ctk.CTkLabel(parent, text="Gallery Hash (Optional):").pack(anchor="w", pady=(10,0))
        ctk.CTkEntry(parent, textvariable=vars['hash']).pack(fill="x")
        
        return vars

    def get_configuration(self, ui_handle):
        return {
            'content': ui_handle['content'].get(),
            'thumb_size': ui_handle['thumb'].get(),
            'cover_limit': int(ui_handle['cover_count'].get() or 0),
            'save_links': ui_handle['links'].get(),
            'gallery_hash': ui_handle['hash'].get()
        }

    def initialize_session(self, config, creds):
        return {'client': api.create_resilient_client(), 'created_galleries': []}

    def prepare_group(self, group, config, context, creds):
        if config.get('auto_gallery'):
            clean_title = group.title.replace('[', '').replace(']', '').strip()
            new_data = api.create_pixhost_gallery(clean_title, client=context['client'])
            if new_data:
                # Store gallery info on the group object
                group.pix_data = new_data
                group.gallery_id = new_data.get('gallery_hash', '')
                context['created_galleries'].append(new_data)

    def upload_file(self, file_path, group, config, context, progress_callback):
        is_cover = False
        if hasattr(group, 'files'):
            try:
                idx = group.files.index(file_path)
                if idx < config.get('cover_limit', 0): is_cover = True
            except ValueError as e:
                logger.debug(f"File {file_path} not found in group files: {e}")

        pix_data = getattr(group, 'pix_data', {})
        
        uploader = api.PixhostUploader(
            file_path,
            os.path.basename(file_path),
            lambda m: progress_callback(m.bytes_read/m.len) if m.len > 0 else None,
            config['content'],
            config['thumb_size'],
            pix_data.get('gallery_hash', config['gallery_hash']),
            pix_data.get('gallery_upload_hash'),
            is_cover
        )

        try:
            url, data, headers = uploader.get_request_params()
            if 'Content-Length' not in headers and hasattr(data, 'len'):
                headers['Content-Length'] = str(data.len)
            r = context['client'].post(url, headers=headers, data=data, timeout=300)
            return uploader.parse_response(r.json())
        finally:
            uploader.close()

    def finalize_batch(self, context):
        # Finalize any galleries created during this batch
        for gal in context.get('created_galleries', []):
            try:
                api.finalize_pixhost_gallery(
                    gal.get('gallery_upload_hash'),
                    gal.get('gallery_hash'),
                    client=context['client']
                )
            except Exception as e:
                logger.warning(f"Failed to finalize Pixhost gallery: {e}")