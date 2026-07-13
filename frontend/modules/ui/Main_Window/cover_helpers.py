# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""CoverHelpers behavior for the main window."""

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


class CoverHelpersMixin:
    def _thumbnail_size_for_service(
        self, service_id: str, settings: Optional[Dict[str, Any]] = None
    ) -> str:
        settings = settings or self.settings
        if service_id == "imx.to":
            return str(settings.get("imx_thumb", "180"))
        if service_id == "pixhost.to":
            return str(settings.get("pix_thumb", "200"))
        if service_id == "turboimagehost":
            return str(settings.get("turbo_thumb", "180"))
        if service_id == "vipr.im":
            thumb_size = str(settings.get("vipr_thumb", "170x170"))
            return thumb_size.split("x")[0] if "x" in thumb_size else thumb_size
        if service_id == "imagebam.com":
            return str(settings.get("imagebam_thumb", "180"))
        if service_id == "imgur.com":
            return str(settings.get("imgur_thumb", settings.get("thumbnail_size", "m")))
        return "250"

    def _auto_cover_count_for_current_service(self) -> int:
        service_id = (
            self.var_service.get()
            if hasattr(self, "var_service")
            else str(getattr(self, "settings", {}).get("service", ""))
        )
        settings_view = self.__dict__.get("settings_view")
        if settings_view is not None:
            raw_config = settings_view.get_raw_config(service_id)
            if "cover_count" in raw_config:
                return max(0, min(10, self._safe_int(raw_config.get("cover_count"), 0)))

        variable_names = {
            "imx.to": "var_imx_cover_count",
            "pixhost.to": "var_pix_cover_count",
            "turboimagehost": "var_turbo_cover_count",
            "vipr.im": "var_vipr_cover_count",
        }
        variable = getattr(self, variable_names.get(service_id, ""), None)
        if variable is None:
            return 0
        try:
            value = variable.get()
        except (tk.TclError, AttributeError):
            value = 0
        return max(0, min(10, self._safe_int(value, 0)))

    def _apply_auto_covers_to_group(self, group: Any) -> None:
        auto_select = getattr(group, "auto_select_covers", None)
        if not callable(auto_select):
            return
        auto_select(self._auto_cover_count_for_current_service())
        self._refresh_cover_buttons(group)

    def _cover_files_for_group(self, group: Any) -> List[str]:
        cover_filepaths = getattr(group, "cover_filepaths", None)
        if callable(cover_filepaths):
            return list(cover_filepaths())

        cover_files = getattr(group, "cover_files", [])
        cover_set = set(cover_files or [])
        return [filepath for filepath in getattr(group, "files", []) if filepath in cover_set]

    def _ordered_group_files_for_output(self, group: Any) -> List[str]:
        files = list(getattr(group, "files", []))
        cover_files = self._cover_files_for_group(group)
        if not cover_files:
            return files

        cover_set = set(cover_files)
        return [filepath for filepath in files if filepath in cover_set] + [
            filepath for filepath in files if filepath not in cover_set
        ]

    def _is_cover_file(self, filepath: str, group: Optional[Any] = None) -> bool:
        group = group or self.file_widgets.get(filepath, {}).get("group")
        is_cover_file = getattr(group, "is_cover_file", None)
        if callable(is_cover_file):
            return bool(is_cover_file(filepath))
        return filepath in set(getattr(group, "cover_files", []) or [])

    def _refresh_cover_button(self, filepath: str) -> None:
        with self.lock:
            row_data = self.file_widgets.get(filepath)
        if not row_data:
            return

        group = row_data.get("group")
        is_cover = self._is_cover_file(filepath, group)
        row_data["is_cover"] = is_cover

        cover_var = row_data.get("cover_var")
        if cover_var:
            try:
                cover_var.set(is_cover)
            except (tk.TclError, AttributeError):
                pass

        button = row_data.get("cover")
        if not button:
            return

        try:
            if is_cover:
                button.configure(
                    text="Cover",
                    fg_color="#1F6AA5",
                    hover_color="#144870",
                    border_color="#1F6AA5",
                    text_color="white",
                )
            else:
                button.configure(
                    text="Cover",
                    fg_color="#1F6AA5",
                    hover_color="#666666",
                    border_color="gray",
                    text_color="gray",
                )
        except (tk.TclError, AttributeError):
            return

    def _refresh_cover_buttons(self, group: Any) -> None:
        for filepath in getattr(group, "files", []):
            self._refresh_cover_button(filepath)

    def _set_cover_for_files(self, filepaths: List[str], is_cover: bool) -> None:
        if getattr(self, "is_uploading", False):
            self.add_activity(
                "Wait for the current upload to finish before changing covers.", "warning"
            )
            return

        changed = 0
        touched_groups = set()
        for filepath in filepaths:
            with self.lock:
                row_data = self.file_widgets.get(filepath)
            group = row_data.get("group") if row_data else None
            setter = getattr(group, "set_cover_file", None)
            if not callable(setter):
                continue
            if setter(filepath, is_cover, manual=True):
                changed += 1
            touched_groups.add(group)

        for group in touched_groups:
            self._refresh_cover_buttons(group)

        if not filepaths:
            return
        if changed or len(filepaths) == 1:
            action = "Marked" if is_cover else "Cleared cover mark for"
            count_label = (
                os.path.basename(filepaths[0])
                if len(filepaths) == 1
                else f"{len(filepaths)} images"
            )
            self.add_activity(f"{action} {count_label}.")

    def _toggle_cover_file(self, filepath: str) -> None:
        with self.lock:
            row_data = self.file_widgets.get(filepath)
        group = row_data.get("group") if row_data else None
        self._set_cover_for_files([filepath], not self._is_cover_file(filepath, group))

    def _set_cover_from_toggle(self, filepath: str) -> None:
        with self.lock:
            row_data = self.file_widgets.get(filepath)
        if not row_data:
            return

        cover_var = row_data.get("cover_var")
        is_cover = bool(cover_var.get()) if cover_var else not self._is_cover_file(filepath)
        self._set_cover_for_files([filepath], is_cover)
        self._refresh_cover_button(filepath)

    def _preview_group_results(self, group: Any) -> List[Tuple[str, str, str]]:
        results = []
        for index, file_path in enumerate(self._ordered_group_files_for_output(group), start=1):
            preview_path = str(file_path or "").replace("\\", "/").rstrip("/")
            name = os.path.basename(preview_path) or f"image-{index}"
            safe_name = (
                file_handler.sanitize_filename(os.path.splitext(name)[0]) or f"image-{index}"
            )
            base_url = f"https://preview.invalid/{safe_name}"
            results.append(
                (
                    f"{base_url}/viewer",
                    f"{base_url}/thumb",
                    f"{base_url}/direct",
                )
            )
        return results
