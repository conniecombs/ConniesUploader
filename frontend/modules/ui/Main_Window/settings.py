# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Settings behavior for the main window."""

from .common import (  # noqa: F401
    Any,
    AutoPoster,
    CollapsibleGroupFrame,
    ContextUtils,
    CredentialsManager,
    DND_FILES,
    Dict,
    DragDropMixin,
    GalleryManager,
    GalleryRecord,
    Image,
    ImageTk,
    List,
    LogWindow,
    Optional,
    PluginManager,
    SafeScrollableFrame,
    ScrollableFrame,
    ServiceSettingsView,
    SettingsManager,
    TemplateEditor,
    TemplateManager,
    ThreadPoolExecutor,
    TkinterDnD,
    Tuple,
    UploadManager,
    api,
    config,
    ctk,
    datetime,
    file_handler,
    filedialog,
    gallery_url_for_service,
    logger,
    messagebox,
    nullcontext,
    os,
    platform,
    pyperclip,
    queue,
    subprocess,
    sys,
    threading,
    time,
    tk,
    viper_api,
)


class SettingsMixin:
    def get_preview_data(self):
        if not self.groups:
            return None, None, None
        grp = next((g for g in self.groups if g.files), None)
        if not grp:
            return None, None, None
        current_service = self.var_service.get()
        size = "200"
        try:
            if hasattr(self, "settings_view"):
                raw = self.settings_view.get_raw_config(current_service)
                if raw.get("thumbnail_size"):
                    size = str(
                        self.settings_view.normalize_value(
                            current_service, "thumbnail_size", raw["thumbnail_size"]
                        )
                    )
            elif current_service == "imx.to":
                size = self.var_imx_thumb.get()
            elif current_service == "pixhost.to":
                size = self.var_pix_thumb.get()
            elif current_service == "turboimagehost":
                size = self.var_turbo_thumb.get()
            elif current_service == "vipr.im":
                val = self.var_vipr_thumb.get()
                size = val.split("x")[0] if "x" in val else val
            elif current_service == "imagebam.com":
                size = self.var_ib_thumb.get()
            if "x" in size:
                size = size.split("x")[0]
        except (AttributeError, tk.TclError) as e:
            logger.debug(f"Could not get thumbnail size for {current_service}: {e}")
        return (
            self._ordered_group_files_for_output(grp),
            grp.title,
            size,
            len(self._cover_files_for_group(grp)),
        )

    def _apply_settings(self):
        s = self.settings
        selected_galleries = s.get("selected_gallery_by_service", {})
        self.selected_gallery_by_service = (
            dict(selected_galleries) if isinstance(selected_galleries, dict) else {}
        )

        self._set_bounded_var(
            self.var_global_worker_count,
            s.get("global_worker_count", config.DEFAULT_WORKER_COUNT),
            config.DEFAULT_WORKER_COUNT,
            config.MIN_WORKER_COUNT,
            config.MAX_WORKER_COUNT,
        )

        self._set_bounded_var(
            self.var_imx_threads,
            s.get("imx_threads", config.DEFAULT_THREAD_COUNT),
            config.DEFAULT_THREAD_COUNT,
            config.MIN_THREAD_COUNT,
            config.MAX_THREAD_COUNT,
        )
        self._set_bounded_var(
            self.menu_thread_var,
            s.get("global_thread_limit", config.DEFAULT_THREAD_COUNT),
            config.DEFAULT_THREAD_COUNT,
            config.MIN_THREAD_COUNT,
            config.MAX_THREAD_COUNT,
        )
        self._last_global_thread_limit_value = self.menu_thread_var.get()

        self._set_bounded_var(
            self.var_pix_threads,
            s.get("pix_threads", 3),
            3,
            config.MIN_THREAD_COUNT,
            config.MAX_THREAD_COUNT,
        )

        self._set_bounded_var(
            self.var_turbo_threads,
            s.get("turbo_threads", 2),
            2,
            config.MIN_THREAD_COUNT,
            config.MAX_THREAD_COUNT,
        )

        self._set_bounded_var(
            self.var_vipr_threads,
            s.get("vipr_threads", 1),
            1,
            config.MIN_THREAD_COUNT,
            config.MAX_THREAD_COUNT,
        )

        self._set_bounded_var(
            self.var_ib_threads,
            s.get("imagebam_threads", 2),
            2,
            config.MIN_THREAD_COUNT,
            config.MAX_THREAD_COUNT,
        )
        if hasattr(self, "var_imgur_threads"):
            self._set_bounded_var(
                self.var_imgur_threads,
                s.get("imgur_threads", 2),
                2,
                config.MIN_THREAD_COUNT,
                config.MAX_THREAD_COUNT,
            )

        self.var_auto_copy.set(s.get("auto_copy", False))
        if hasattr(self, "var_confirm_before_posting"):
            self.var_confirm_before_posting.set(s.get("confirm_before_posting", False))
        self.var_auto_gallery.set(s.get("auto_gallery", False))
        self.var_show_previews.set(s.get("show_previews", True))
        self.var_separate_batches.set(s.get("separate_batches", False))

        mode = s.get("appearance_mode", "System")
        self.var_appearance_mode.set(mode)
        ctk.set_appearance_mode(mode)

        available_services = list(getattr(self, "service_frames", {}).keys())
        fallback_service = (
            "pixhost.to"
            if "pixhost.to" in available_services
            else (available_services[0] if available_services else "imx.to")
        )
        saved_service = s.get("service", fallback_service)
        if saved_service not in available_services:
            logger.warning(
                f"Saved service '{saved_service}' is not available; using '{fallback_service}'"
            )
            saved_service = fallback_service
        self.var_service.set(saved_service)
        self._swap_service_frame(saved_service)

    def _safe_int(self, value, default=2):
        try:
            return int(value)
        except (ValueError, TypeError) as e:
            logger.debug(f"Could not convert '{value}' to int, using default {default}: {e}")
            return default

    @staticmethod
    def _service_thread_var_specs():
        return (
            ("imx_threads", "var_imx_threads", config.DEFAULT_THREAD_COUNT),
            ("pix_threads", "var_pix_threads", 3),
            ("turbo_threads", "var_turbo_threads", 2),
            ("vipr_threads", "var_vipr_threads", 1),
            ("imagebam_threads", "var_ib_threads", 2),
            ("imgur_threads", "var_imgur_threads", 2),
        )

    def _bounded_int(self, value, default, minimum, maximum):
        number = self._safe_int(value, default)
        return max(minimum, min(maximum, number))

    def _set_bounded_var(self, variable, value, default, minimum, maximum):
        bounded = self._bounded_int(value, default, minimum, maximum)
        try:
            variable.set(bounded)
        except Exception as e:
            logger.debug(f"Could not set bounded UI value '{bounded}': {e}")
        return bounded

    def _gather_settings(self) -> Dict[str, Any]:
        selected_service = self.var_service.get()
        worker_count = self._set_bounded_var(
            self.var_global_worker_count,
            self.var_global_worker_count.get(),
            config.DEFAULT_WORKER_COUNT,
            config.MIN_WORKER_COUNT,
            config.MAX_WORKER_COUNT,
        )
        global_thread_limit = self._set_bounded_var(
            self.menu_thread_var,
            self.menu_thread_var.get(),
            config.DEFAULT_THREAD_COUNT,
            config.MIN_THREAD_COUNT,
            config.MAX_THREAD_COUNT,
        )
        if global_thread_limit != getattr(
            self, "_last_global_thread_limit_value", global_thread_limit
        ):
            self.set_global_threads(global_thread_limit)

        service_thread_settings = {}
        for key, var_name, default in self._service_thread_var_specs():
            variable = getattr(self, var_name, None)
            value = variable.get() if variable is not None else default
            if variable is not None:
                service_thread_settings[key] = self._set_bounded_var(
                    variable,
                    value,
                    default,
                    config.MIN_THREAD_COUNT,
                    config.MAX_THREAD_COUNT,
                )
            else:
                service_thread_settings[key] = self._bounded_int(
                    value,
                    default,
                    config.MIN_THREAD_COUNT,
                    config.MAX_THREAD_COUNT,
                )

        cfg = {
            "service": selected_service,
            "global_worker_count": worker_count,
            "global_thread_limit": global_thread_limit,
            **service_thread_settings,
            "output_format": self.settings.get("output_format", "BBCode"),
            "auto_copy": self.var_auto_copy.get(),
            "confirm_before_posting": self.var_confirm_before_posting.get(),
            "auto_gallery": self.var_auto_gallery.get(),
            "show_previews": self.var_show_previews.get(),
            "separate_batches": self.var_separate_batches.get(),
            "appearance_mode": self.var_appearance_mode.get(),
        }

        settings_view = self.__dict__.get("settings_view")
        if settings_view is None:
            cfg["selected_gallery_by_service"] = dict(
                self.__dict__.get("selected_gallery_by_service", {}) or {}
            )
            selected_gallery = self._selected_gallery_for_service(selected_service, cfg)
            if selected_gallery:
                cfg.update(
                    {
                        "selected_gallery_id": selected_gallery.get("id", ""),
                        "selected_gallery_name": selected_gallery.get("name", ""),
                        "selected_gallery_url": selected_gallery.get("url", ""),
                        "selected_gallery_upload_hash": selected_gallery.get("upload_hash", ""),
                    }
                )
            return cfg

        for service_id, raw_config in settings_view.get_all_raw_configs().items():
            cfg.update(settings_view.alias_config(service_id, raw_config))

        selected_config = settings_view.get_validated_config(selected_service)
        cfg.update(selected_config)
        cfg.update(settings_view.alias_config(selected_service, selected_config))
        cfg["selected_gallery_by_service"] = dict(
            self.__dict__.get("selected_gallery_by_service", {}) or {}
        )
        selected_gallery = self._selected_gallery_for_service(selected_service, cfg)
        if selected_gallery:
            cfg.update(
                {
                    "selected_gallery_id": selected_gallery.get("id", ""),
                    "selected_gallery_name": selected_gallery.get("name", ""),
                    "selected_gallery_url": selected_gallery.get("url", ""),
                    "selected_gallery_upload_hash": selected_gallery.get("upload_hash", ""),
                }
            )
            if selected_service == "pixhost.to" and selected_gallery.get("upload_hash"):
                cfg["gallery_upload_hash"] = selected_gallery["upload_hash"]

        return cfg
