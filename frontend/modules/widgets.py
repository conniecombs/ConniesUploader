# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

import customtkinter as ctk
from tkinter import ttk

from . import config


class ScrollableFrame(ctk.CTkScrollableFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.scrollable_frame = self

    def check_if_master_is_canvas(self, widget):
        if widget is None:
            return False
        if isinstance(widget, str):
            try:
                widget = self.winfo_toplevel().nametowidget(widget)
            except Exception:
                return False

        try:
            if widget == self._parent_canvas:
                return True
            elif hasattr(widget, "master") and widget.master is not None:
                return self.check_if_master_is_canvas(widget.master)
            else:
                return False
        except Exception:
            return False


class NativeComboBox(ttk.Combobox):
    def __init__(self, master=None, **kwargs):
        self._command = None
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        if "variable" in kwargs:
            kwargs["textvariable"] = kwargs.pop("variable")

        ctk_args = [
            "text_color",
            "fg_color",
            "border_color",
            "button_color",
            "button_hover_color",
            "dropdown_fg_color",
            "dropdown_hover_color",
            "dropdown_text_color",
            "dropdown_text_font",
            "font",
            "corner_radius",
            "border_width",
        ]
        for k in ctk_args:
            if k in kwargs:
                del kwargs[k]

        super().__init__(master, **kwargs)
        self.bind("<<ComboboxSelected>>", self._on_select)

    def _on_select(self, event):
        if self._command:
            self._command(self.get())


class MouseWheelComboBox(ctk.CTkComboBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bind("<MouseWheel>", self._on_mouse_wheel)
        self.bind("<Button-4>", lambda e: self._on_mouse_wheel(e, 120))
        self.bind("<Button-5>", lambda e: self._on_mouse_wheel(e, -120))

    def _on_mouse_wheel(self, event, linux_delta=None):
        if self._state == "disabled":
            return
        values = self._values
        if not values:
            return
        delta = linux_delta if linux_delta else event.delta
        try:
            current_val = self.get()
            current_idx = values.index(current_val)
        except ValueError:
            current_idx = 0
        step = -1 if delta > 0 else 1
        new_idx = max(0, min(len(values) - 1, current_idx + step))
        if new_idx != current_idx:
            new_val = values[new_idx]
            self.set(new_val)
            if self._command:
                self._command(new_val)


class ServiceSettingsView:
    """
    Encapsulates the creation and management of service-specific settings frames.
    Accepts the main `app` instance to attach variables to, preserving the existing data model.
    """

    SERVICE_ALIASES = {
        "imx.to": {
            "thumbnail_size": "imx_thumb",
            "thumbnail_format": "imx_format",
            "cover_count": "imx_cover_count",
            "save_links": "imx_links",
            "gallery_id": "imx_gallery_id",
        },
        config.PIXHOST_SERVICE_ID: {
            "content_type": "pix_content",
            "thumbnail_size": "pix_thumb",
            "cover_count": "pix_cover_count",
            "save_links": "pix_links",
            "gallery_hash": "pix_gallery_hash",
        },
        "turboimagehost": {
            "thumbnail_size": "turbo_thumb",
            "cover_count": "turbo_cover_count",
            "save_links": "turbo_links",
            "gallery_id": "turbo_gallery_id",
        },
        "vipr.im": {
            "thumbnail_size": "vipr_thumb",
            "cover_count": "vipr_cover_count",
            "save_links": "vipr_links",
            "vipr_gallery_name": "vipr_gallery_name",
            "vipr_gal_id": "vipr_gal_id",
        },
        "imagebam.com": {
            "content_type": "imagebam_content",
            "thumbnail_size": "imagebam_thumb",
        },
        "imgur.com": {
            "thumbnail_size": "imgur_thumb",
            "content_type": "imgur_content",
            "save_links": "imgur_links",
            "album_id": "imgur_album_id",
            "title": "imgur_title",
        },
    }

    def __init__(self, parent, app, plugin_manager=None):
        self.parent = parent
        self.app = app
        self.plugin_manager = plugin_manager
        self.service_handles = {}
        self.service_plugins = {}

        # Initialize variables on the app instance if they don't exist
        # This keeps compatibility with app._gather_settings()
        self._init_variables()
        self._build_frames()

    def _init_variables(self):
        # Global settings
        if not hasattr(self.app, "var_global_worker_count"):
            self.app.var_global_worker_count = ctk.IntVar(value=8)

        # IMX
        if not hasattr(self.app, "var_imx_thumb"):
            self.app.var_imx_thumb = ctk.StringVar(value="180")
        if not hasattr(self.app, "var_imx_format"):
            self.app.var_imx_format = ctk.StringVar(value="Fixed Width")
        if not hasattr(self.app, "var_imx_cover_count"):
            self.app.var_imx_cover_count = ctk.StringVar(value="0")
        if not hasattr(self.app, "var_imx_links"):
            self.app.var_imx_links = ctk.BooleanVar()
        if not hasattr(self.app, "var_imx_threads"):
            self.app.var_imx_threads = ctk.IntVar(value=5)

        # Pixhost
        if not hasattr(self.app, "var_pix_content"):
            self.app.var_pix_content = ctk.StringVar(value="Safe")
        if not hasattr(self.app, "var_pix_thumb"):
            self.app.var_pix_thumb = ctk.StringVar(value="200")
        if not hasattr(self.app, "var_pix_cover_count"):
            self.app.var_pix_cover_count = ctk.StringVar(value="0")
        if not hasattr(self.app, "var_pix_links"):
            self.app.var_pix_links = ctk.BooleanVar()
        if not hasattr(self.app, "var_pix_threads"):
            self.app.var_pix_threads = ctk.IntVar(value=3)

        # Turbo
        if not hasattr(self.app, "var_turbo_content"):
            self.app.var_turbo_content = ctk.StringVar(value="Safe")
        if not hasattr(self.app, "var_turbo_thumb"):
            self.app.var_turbo_thumb = ctk.StringVar(value="180")
        if not hasattr(self.app, "var_turbo_cover_count"):
            self.app.var_turbo_cover_count = ctk.StringVar(value="0")
        if not hasattr(self.app, "var_turbo_links"):
            self.app.var_turbo_links = ctk.BooleanVar()
        if not hasattr(self.app, "var_turbo_threads"):
            self.app.var_turbo_threads = ctk.IntVar(value=2)

        # Vipr
        if not hasattr(self.app, "var_vipr_thumb"):
            self.app.var_vipr_thumb = ctk.StringVar(value="170x170")
        if not hasattr(self.app, "var_vipr_gallery"):
            self.app.var_vipr_gallery = ctk.StringVar()
        if not hasattr(self.app, "var_vipr_cover_count"):
            self.app.var_vipr_cover_count = ctk.StringVar(value="0")
        if not hasattr(self.app, "var_vipr_links"):
            self.app.var_vipr_links = ctk.BooleanVar()
        if not hasattr(self.app, "var_vipr_threads"):
            self.app.var_vipr_threads = ctk.IntVar(value=1)

        # ImageBam
        if not hasattr(self.app, "var_ib_content"):
            self.app.var_ib_content = ctk.StringVar(value="Safe")
        if not hasattr(self.app, "var_ib_thumb"):
            self.app.var_ib_thumb = ctk.StringVar(value="180")
        if not hasattr(self.app, "var_ib_threads"):
            self.app.var_ib_threads = ctk.IntVar(value=2)

        # Imgur
        if not hasattr(self.app, "var_imgur_threads"):
            self.app.var_imgur_threads = ctk.IntVar(value=2)

    def _create_cover_count_combo(self, parent, variable, label_text="Auto Covers:"):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", pady=5)
        ctk.CTkLabel(f, text=label_text, width=60).pack(side="left")
        opts = [str(i) for i in range(11)]
        cb = MouseWheelComboBox(f, variable=variable, values=opts, width=80)
        cb.pack(side="left", padx=5)
        return f

    def _build_frames(self):
        self.app.service_frames = {}
        self.app.service_config_handles = self.service_handles
        self.app.service_plugins = self.service_plugins

        if not self.plugin_manager:
            self._build_imx()
            self._build_pix()
            self._build_turbo()
            self._build_vipr()
            self._build_imagebam()
            return

        for plugin in self.plugin_manager.get_all_plugins():
            p = ctk.CTkFrame(self.parent)
            service_id = plugin.id
            self.app.service_frames[service_id] = p
            self.service_plugins[service_id] = plugin

            current_settings = self._settings_for_service(service_id)
            try:
                handle = plugin.render_settings(p, current_settings)
            except Exception as exc:
                handle = {}
                ctk.CTkLabel(
                    p,
                    text=f"{plugin.name} settings could not be loaded.",
                    text_color="#FF3B30",
                ).pack(anchor="w", padx=5, pady=(5, 2))
                ctk.CTkLabel(p, text=str(exc), wraplength=260, justify="left").pack(
                    anchor="w", padx=5, pady=(0, 5)
                )

            self.service_handles[service_id] = handle
            self._install_legacy_aliases(service_id, handle)

    def _settings_for_service(self, service_id):
        service_id = config.normalize_service_id(service_id)
        settings = dict(getattr(self.app, "settings", {}) or {})
        for schema_key, legacy_key in self.SERVICE_ALIASES.get(service_id, {}).items():
            if legacy_key in settings:
                settings[schema_key] = settings[legacy_key]
        if service_id == "imx.to" and "imx_gallery_id" not in settings:
            settings["gallery_id"] = settings.get("gallery_id", "")
        return settings

    def _install_legacy_aliases(self, service_id, handle):
        service_id = config.normalize_service_id(service_id)
        aliases = self.SERVICE_ALIASES.get(service_id, {})
        for schema_key, legacy_key in aliases.items():
            if schema_key not in handle:
                continue
            var = handle[schema_key]
            if legacy_key == "imx_thumb":
                self.app.var_imx_thumb = var
            elif legacy_key == "imx_format":
                self.app.var_imx_format = var
            elif legacy_key == "imx_cover_count":
                self.app.var_imx_cover_count = var
            elif legacy_key == "imx_links":
                self.app.var_imx_links = var
            elif legacy_key == "pix_content":
                self.app.var_pix_content = var
            elif legacy_key == "pix_thumb":
                self.app.var_pix_thumb = var
            elif legacy_key == "pix_cover_count":
                self.app.var_pix_cover_count = var
            elif legacy_key == "pix_links":
                self.app.var_pix_links = var
            elif legacy_key == "turbo_thumb":
                self.app.var_turbo_thumb = var
            elif legacy_key == "turbo_cover_count":
                self.app.var_turbo_cover_count = var
            elif legacy_key == "turbo_links":
                self.app.var_turbo_links = var
            elif legacy_key == "vipr_thumb":
                self.app.var_vipr_thumb = var
            elif legacy_key == "vipr_cover_count":
                self.app.var_vipr_cover_count = var
            elif legacy_key == "vipr_links":
                self.app.var_vipr_links = var
            elif legacy_key == "imagebam_content":
                self.app.var_ib_content = var
            elif legacy_key == "imagebam_thumb":
                self.app.var_ib_thumb = var

        if service_id == "vipr.im":
            plugin = self.service_plugins.get(service_id)
            if getattr(plugin, "cb_gallery", None) is not None:
                self.app.cb_vipr_gallery = plugin.cb_gallery

    def get_raw_config(self, service_id):
        service_id = config.normalize_service_id(service_id)
        return self._read_handle(self.service_handles.get(service_id, {}))

    def get_all_raw_configs(self):
        return {
            service_id: self.get_raw_config(service_id)
            for service_id in self.service_handles
        }

    def get_validated_config(self, service_id):
        service_id = config.normalize_service_id(service_id)
        plugin = self.service_plugins.get(service_id)
        handle = self.service_handles.get(service_id)
        if not plugin or handle is None:
            return {}
        return plugin.get_configuration(handle)

    def alias_config(self, service_id, raw_config):
        service_id = config.normalize_service_id(service_id)
        aliases = {}
        plugin = self.service_plugins.get(service_id)
        for schema_key, legacy_key in self.SERVICE_ALIASES.get(service_id, {}).items():
            if schema_key not in raw_config:
                continue
            value = self.normalize_value(
                service_id, schema_key, raw_config[schema_key], plugin=plugin
            )
            if schema_key == "cover_count":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = 0
            aliases[legacy_key] = value
        return aliases

    def normalize_value(self, service_id, key, value, plugin=None):
        service_id = config.normalize_service_id(service_id)
        plugin = plugin or self.service_plugins.get(service_id)
        if not plugin:
            return value

        field = self._find_schema_field(getattr(plugin, "settings_schema", []), key)
        if not field:
            return value

        labels = field.get("value_labels", {})
        for stored_value, display_value in labels.items():
            if str(value) == str(display_value):
                return str(stored_value)
        return value

    def _find_schema_field(self, schema, key):
        for field in schema:
            if field.get("key") == key:
                return field
            for subfield in field.get("fields", []):
                if subfield.get("key") == key:
                    return subfield
        return None

    def get_value(self, service_id, key, default=""):
        service_id = config.normalize_service_id(service_id)
        return self.get_raw_config(service_id).get(key, default)

    def set_value(self, service_id, key, value):
        service_id = config.normalize_service_id(service_id)
        handle = self.service_handles.get(service_id, {})
        var = handle.get(key)
        if var is not None:
            var.set(value)

    @staticmethod
    def _read_handle(handle):
        config = {}
        for key, var in (handle or {}).items():
            if hasattr(var, "get"):
                config[key] = var.get()
        return config

    def _build_imx(self):
        p = ctk.CTkFrame(self.parent)
        self.app.service_frames["imx.to"] = p
        ctk.CTkLabel(p, text="Requires Credentials", text_color="red").pack(pady=5)
        ctk.CTkLabel(p, text="Thumb Size:").pack(anchor="w")
        MouseWheelComboBox(
            p, variable=self.app.var_imx_thumb, values=["100", "180", "250", "300", "600"]
        ).pack(fill="x")
        ctk.CTkLabel(p, text="Format:").pack(anchor="w")
        MouseWheelComboBox(
            p,
            variable=self.app.var_imx_format,
            values=["Fixed Width", "Fixed Height", "Proportional", "Square"],
        ).pack(fill="x")
        self._create_cover_count_combo(p, self.app.var_imx_cover_count)
        ctk.CTkCheckBox(p, text="Links.txt", variable=self.app.var_imx_links).pack(
            anchor="w", pady=5
        )
        ctk.CTkLabel(p, text="Gallery ID:").pack(anchor="w", pady=(10, 0))
        self.app.ent_imx_gal = ctk.CTkEntry(p)
        self.app.ent_imx_gal.pack(fill="x")

    def _build_pix(self):
        p = ctk.CTkFrame(self.parent)
        self.app.service_frames[config.PIXHOST_SERVICE_ID] = p
        ctk.CTkLabel(p, text="Content:").pack(anchor="w")
        MouseWheelComboBox(p, variable=self.app.var_pix_content, values=["Safe", "Adult"]).pack(
            fill="x"
        )
        ctk.CTkLabel(p, text="Thumb Size:").pack(anchor="w")
        MouseWheelComboBox(
            p,
            variable=self.app.var_pix_thumb,
            values=["150", "200", "250", "300", "350", "400", "450", "500"],
        ).pack(fill="x")
        self._create_cover_count_combo(p, self.app.var_pix_cover_count)
        ctk.CTkCheckBox(p, text="Links.txt", variable=self.app.var_pix_links).pack(
            anchor="w", pady=5
        )
        ctk.CTkLabel(p, text="Gallery Hash (Optional):").pack(anchor="w", pady=(10, 0))
        self.app.ent_pix_hash = ctk.CTkEntry(p)
        self.app.ent_pix_hash.pack(fill="x")

    def _build_turbo(self):
        p = ctk.CTkFrame(self.parent)
        self.app.service_frames["turboimagehost"] = p
        ctk.CTkLabel(p, text="Login Optional", text_color="red").pack(pady=5)
        ctk.CTkLabel(p, text="Thumb Size:").pack(anchor="w")
        MouseWheelComboBox(
            p,
            variable=self.app.var_turbo_thumb,
            values=["150", "200", "250", "300", "350", "400", "500", "600"],
        ).pack(fill="x")
        self._create_cover_count_combo(p, self.app.var_turbo_cover_count)
        ctk.CTkCheckBox(p, text="Links.txt", variable=self.app.var_turbo_links).pack(
            anchor="w", pady=5
        )
        ctk.CTkLabel(p, text="Gallery ID:").pack(anchor="w")
        self.app.ent_turbo_gal = ctk.CTkEntry(p)
        self.app.ent_turbo_gal.pack(fill="x")

    def _build_vipr(self):
        p = ctk.CTkFrame(self.parent)
        self.app.service_frames["vipr.im"] = p
        ctk.CTkLabel(p, text="Requires Credentials", text_color="red").pack(pady=5)
        ctk.CTkLabel(p, text="Thumb Size:").pack(anchor="w")
        MouseWheelComboBox(
            p,
            variable=self.app.var_vipr_thumb,
            values=["100x100", "170x170", "250x250", "300x300", "350x350", "500x500", "800x800"],
        ).pack(fill="x")
        self._create_cover_count_combo(p, self.app.var_vipr_cover_count)
        ctk.CTkCheckBox(p, text="Links.txt", variable=self.app.var_vipr_links).pack(
            anchor="w", pady=5
        )
        ctk.CTkButton(
            p, text="Refresh Galleries / Login", command=self.app.refresh_vipr_galleries
        ).pack(fill="x", pady=10)
        self.app.cb_vipr_gallery = MouseWheelComboBox(
            p, variable=self.app.var_vipr_gallery, values=["None"]
        )
        self.app.cb_vipr_gallery.pack(fill="x")

    def _build_imagebam(self):
        p = ctk.CTkFrame(self.parent)
        self.app.service_frames["imagebam.com"] = p
        ctk.CTkLabel(p, text="Content Type:").pack(anchor="w")
        MouseWheelComboBox(p, variable=self.app.var_ib_content, values=["Safe", "Adult"]).pack(
            fill="x"
        )
        ctk.CTkLabel(p, text="Thumb Size:").pack(anchor="w")
        MouseWheelComboBox(
            p, variable=self.app.var_ib_thumb, values=["100", "180", "250", "300"]
        ).pack(fill="x")


class CollapsibleGroupFrame(ctk.CTkFrame):
    def __init__(
        self,
        parent,
        title="Group",
        thread_names=None,
        template_names=None,
        default_template="BBCode",
        post_preview_callback=None,
    ):
        super().__init__(parent)
        self.parent = parent
        self.title = title
        self.is_collapsed = False
        self.is_completed = False
        self.files = []
        self.cover_files = []
        self.cover_selection_manual = False
        self.selected_thread = "Do Not Post"
        self.selected_template = default_template
        self.post_preview_callback = post_preview_callback

        self.header = ctk.CTkFrame(self, height=30, corner_radius=6)
        self.header.pack(fill="x", pady=(2, 0), ipadx=5, ipady=2)

        self.btn_toggle = ctk.CTkButton(
            self.header, text="-", width=20, height=20, command=self.toggle
        )
        self.btn_toggle.pack(side="left", padx=5)

        self.lbl_title = ctk.CTkLabel(self.header, text=title, font=("Segoe UI", 13, "bold"))
        self.lbl_title.pack(side="left", padx=5)

        self.lbl_counts = ctk.CTkLabel(self.header, text="(0 files)", text_color="gray")
        self.lbl_counts.pack(side="left", padx=5)

        self.prog = ctk.CTkProgressBar(self.header, width=150)
        self.prog.set(0)
        self.prog.pack(side="right", padx=10)

        vals = ["Do Not Post"]
        if thread_names:
            vals += sorted(thread_names)
        self.thread_var = ctk.StringVar(value="Do Not Post")
        self.thread_combo = NativeComboBox(
            self.header,
            width=20,
            values=vals,
            variable=self.thread_var,
            command=self._on_thread_change,
        )
        self.thread_combo.pack(side="right", padx=5)

        if post_preview_callback:
            self.btn_post_preview = ctk.CTkButton(
                self.header,
                text="Preview Post",
                width=95,
                height=24,
                command=lambda: self.post_preview_callback(self),
            )
            self.btn_post_preview.pack(side="right", padx=5)

        if template_names:
            val = (
                default_template
                if default_template in template_names
                else (template_names[0] if template_names else "")
            )
            self.selected_template = val
            self.template_var = ctk.StringVar(value=val)
            self.template_combo = NativeComboBox(
                self.header,
                width=15,
                values=template_names,
                variable=self.template_var,
                command=self._on_template_change,
            )
            self.template_combo.pack(side="right", padx=5)

        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.pack(fill="x", expand=True, padx=10, pady=5)

    def _on_thread_change(self, choice):
        self.selected_thread = choice

    def update_thread_names(self, thread_names=None):
        vals = ["Do Not Post"]
        if thread_names:
            vals += sorted(thread_names)
        self.thread_combo.configure(values=vals)
        current = self.thread_var.get()
        if current not in vals:
            current = "Do Not Post"
            self.thread_var.set(current)
        self.selected_thread = current

    def _on_template_change(self, choice):
        self.selected_template = choice

    def toggle(self):
        if self.is_collapsed:
            self.content_frame.pack(fill="x", expand=True, padx=10, pady=5)
            self.btn_toggle.configure(text="-")
        else:
            self.content_frame.pack_forget()
            self.btn_toggle.configure(text="+")
        self.is_collapsed = not self.is_collapsed

    def add_file(self, filepath):
        if filepath not in self.files:
            self.files.append(filepath)
            self.lbl_counts.configure(text=f"({len(self.files)} files)")

    def remove_file(self, filepath):
        if filepath in self.files:
            self.files.remove(filepath)
        if filepath in self.cover_files:
            self.cover_files.remove(filepath)
            self.lbl_counts.configure(text=f"({len(self.files)} files)")

    def is_cover_file(self, filepath):
        return filepath in self.cover_files

    def set_cover_file(self, filepath, is_cover=True, manual=True):
        if filepath not in self.files:
            return False

        changed = False
        if is_cover and filepath not in self.cover_files:
            self.cover_files.append(filepath)
            changed = True
        elif not is_cover and filepath in self.cover_files:
            self.cover_files.remove(filepath)
            changed = True

        if manual:
            self.cover_selection_manual = True
        return changed

    def auto_select_covers(self, count):
        if self.cover_selection_manual:
            return

        try:
            count = max(0, min(10, int(count)))
        except (TypeError, ValueError):
            count = 0
        self.cover_files = list(self.files[:count])

    def cover_filepaths(self):
        cover_set = set(self.cover_files)
        return [filepath for filepath in self.files if filepath in cover_set]

    def mark_complete(self):
        self.is_completed = True
        self.lbl_title.configure(text_color="#34C759")
        self.lbl_counts.configure(text="(Completed)", text_color="#34C759")
        self.prog.configure(progress_color="#34C759")
