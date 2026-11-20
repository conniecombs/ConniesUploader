# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""GalleryActions behavior for the main window."""

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
    viper_client,
    viper_storage,
    viper_ui,
)

# Each host's own gallery field: (per-host settings key, plain schema key).
# Vipr's gallery comes from its dropdown and is handled separately.
_GALLERY_FIELD_KEYS = {
    "imx.to": ("imx_gallery_id", "gallery_id"),
    config.PIXHOST_SERVICE_ID: ("pix_gallery_hash", "gallery_hash"),
    "turboimagehost": ("turbo_gallery_id", "gallery_id"),
    "imagebam.com": ("imagebam_gallery_id", "gallery_id"),
    "imgur.com": ("imgur_album_id", "album_id"),
}


class GalleryActionsMixin:
    def on_gallery_created(self, service, gid=None, record=None):
        record_data = self._gallery_record_data(service, gid, record)
        service = record_data["service"]
        gid = record_data["id"]
        if not service or not gid:
            return

        self.selected_gallery_by_service[service] = record_data
        self._apply_gallery_to_service_settings(record_data)
        self.var_service.set(service)
        self._swap_service_frame(service)
        self.add_activity(
            f"Selected gallery for {service}: {record_data['name']} ({gid}).",
            "success",
        )

    def open_gallery_manager(self):
        GalleryManager(self, self.creds, callback=self.on_gallery_created)

    def _gallery_record_data(self, service, gid=None, record=None) -> Dict[str, str]:
        if isinstance(service, GalleryRecord):
            record = service
            service = record.service
            gid = record.id

        service = config.normalize_service_id(service or getattr(record, "service", ""))
        gid = str(gid or getattr(record, "id", "") or "").strip()
        name = str(getattr(record, "name", "") or gid).strip()
        url = str(getattr(record, "url", "") or gallery_url_for_service(service, gid)).strip()
        if service == config.PIXHOST_SERVICE_ID:
            url = config.normalize_pixhost_url(url)
        upload_hash = str(getattr(record, "upload_hash", "") or "").strip()
        return {
            "service": service,
            "id": gid,
            "name": name or gid,
            "url": url,
            "upload_hash": upload_hash,
        }

    def _apply_gallery_to_service_settings(self, record_data: Dict[str, str]) -> None:
        settings_view = self.__dict__.get("settings_view")
        if settings_view is None:
            return
        service = record_data["service"]
        gid = record_data["id"]
        if service == "imx.to":
            settings_view.set_value("imx.to", "gallery_id", gid)
        elif service == config.PIXHOST_SERVICE_ID:
            settings_view.set_value(config.PIXHOST_SERVICE_ID, "gallery_hash", gid)
        elif service == "vipr.im":
            self._apply_vipr_gallery_selection(record_data)
        elif service == "imagebam.com":
            settings_view.set_value("imagebam.com", "gallery_id", gid)

    def _apply_vipr_gallery_selection(self, record_data: Dict[str, str]) -> None:
        name = record_data["name"]
        gid = record_data["id"]
        vipr_galleries_map = self.vipr_galleries_map
        vipr_galleries_map[name] = gid
        plugin = self.__dict__.get("service_plugins", {}).get("vipr.im")
        if plugin:
            # Add to, not replace, the plugin's map: the dropdown's other
            # galleries must keep resolving to their ids.
            plugin.vipr_galleries_map = {**plugin.vipr_galleries_map, name: gid}
        if hasattr(self, "cb_vipr_gallery"):
            try:
                values = list(getattr(self.cb_vipr_gallery, "_values", []) or [])
                if "None" not in values:
                    values.insert(0, "None")
                if name not in values:
                    values.append(name)
                self.cb_vipr_gallery.configure(values=values)
            except (tk.TclError, AttributeError, TypeError) as exc:
                logger.debug(f"Could not update Vipr gallery dropdown: {exc}")
        settings_view = self.__dict__.get("settings_view")
        if settings_view is not None:
            settings_view.set_value("vipr.im", "vipr_gallery_name", name)

    def gallery_selected_batch_count(self) -> int:
        return len(self._selected_groups_for_gallery_assignment())

    def _selected_groups_for_gallery_assignment(self) -> List[Any]:
        selected_files = list(self.selected_files)
        if not selected_files:
            return []

        groups = []
        seen = set()
        with self.lock:
            for file_path in selected_files:
                group = self.file_widgets.get(file_path, {}).get("group")
                if group is None or id(group) in seen:
                    continue
                seen.add(id(group))
                groups.append(group)
        return groups

    def on_gallery_assign_to_selected_batches(self, service, gid=None, record=None):
        record_data = self._gallery_record_data(service, gid, record)
        groups = self._selected_groups_for_gallery_assignment()
        if not groups:
            self.on_gallery_created(record_data["service"], record_data["id"], record)
            return

        # Only the selected batches get this gallery; the host's Gallery ID
        # field (and so every other batch) is left as it is.
        self.var_service.set(record_data["service"])
        self._swap_service_frame(record_data["service"])
        for group in groups:
            self._assign_gallery_to_group(group, record_data)

        batch_label = "batch" if len(groups) == 1 else "batches"
        self.add_activity(
            f"Assigned gallery {record_data['name']} ({record_data['id']}) "
            f"to {len(groups)} selected {batch_label}.",
            "success",
        )

    def _assign_gallery_to_group(self, group: Any, record_data: Dict[str, str]) -> None:
        group.gallery_id = record_data["id"]
        group.gallery_name = record_data["name"]
        group.gallery_url = record_data["url"]
        group.gallery_service = record_data["service"]
        group.gallery_upload_hash = record_data.get("upload_hash", "")
        if record_data["service"] == config.PIXHOST_SERVICE_ID and record_data.get("upload_hash"):
            group.pix_data = {
                "gallery_hash": record_data["id"],
                "gallery_upload_hash": record_data["upload_hash"],
                "gallery_url": record_data["url"],
                "gallery_name": record_data["name"],
            }

    def refresh_vipr_galleries(self, select_id=None):
        if not self.creds["vipr_user"]:
            messagebox.showerror("Error", "Vipr credentials missing.")
            return

        def _refresh():
            try:
                self.log("Vipr: Refreshing galleries via Sidecar...")
                creds = {"vipr_user": self.creds["vipr_user"], "vipr_pass": self.creds["vipr_pass"]}
                meta = api.get_vipr_metadata(creds)
                if meta and meta.get("galleries"):
                    self.vipr_galleries_map = {g["name"]: g["id"] for g in meta["galleries"]}
                    gal_names = ["None"] + list(self.vipr_galleries_map.keys())
                    plugin = getattr(self, "service_plugins", {}).get("vipr.im")
                    if plugin:
                        plugin.vipr_galleries_map = dict(self.vipr_galleries_map)
                    selected_name = next(
                        (
                            name
                            for name, value in self.vipr_galleries_map.items()
                            if value == select_id
                        ),
                        None,
                    )

                    def _apply_galleries():
                        if hasattr(self, "cb_vipr_gallery"):
                            self.cb_vipr_gallery.configure(values=gal_names)
                        if selected_name:
                            self.settings_view.set_value(
                                "vipr.im", "vipr_gallery_name", selected_name
                            )

                    self.after(0, _apply_galleries)
                    self.log(f"Vipr: Found {len(meta['galleries'])} galleries.")
                else:
                    self.log("Vipr: No galleries found.")
            except Exception as e:
                self.log(f"Vipr Error: {e}")

        threading.Thread(target=_refresh, daemon=True).start()

    def _format_gallery_preflight_detail(self, batch_name: str, gallery: Dict[str, str]) -> str:
        gallery_id = gallery.get("id", "")
        gallery_name = gallery.get("name") or gallery_id
        url = gallery.get("url", "")
        suffix = f" ({url})" if url else ""
        return f'Selected gallery for "{batch_name}": {gallery_name} ({gallery_id}).{suffix}'

    def _register_selected_pixhost_galleries_for_finalization(
        self, pending_by_group: Dict[Any, List[str]], cfg: Dict[str, Any]
    ) -> None:
        service = config.normalize_service_id(cfg.get("service"))
        if service != config.PIXHOST_SERVICE_ID:
            return

        for group in pending_by_group.keys():
            gallery = self._gallery_for_group(group, config.PIXHOST_SERVICE_ID, cfg)
            if not gallery or not gallery.get("upload_hash"):
                continue
            self._register_pixhost_gallery_for_finalization(
                {
                    "gallery_hash": gallery["id"],
                    "gallery_upload_hash": gallery["upload_hash"],
                    "gallery_url": gallery.get("url", ""),
                    "gallery_name": gallery.get("name", ""),
                }
            )

    def _register_pixhost_gallery_for_finalization(self, gallery: Dict[str, Any]) -> bool:
        gallery_hash = str(gallery.get("gallery_hash") or "").strip()
        upload_hash = str(gallery.get("gallery_upload_hash") or "").strip()
        if not gallery_hash or not upload_hash:
            return False

        for existing in self.pix_galleries_to_finalize:
            if (
                str(existing.get("gallery_hash") or "") == gallery_hash
                and str(existing.get("gallery_upload_hash") or "") == upload_hash
            ):
                return False

        self.pix_galleries_to_finalize.append(gallery)
        return True

    def _selected_gallery_for_service(
        self, service_id: str, cfg: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, str]]:
        """Return the Gallery Manager pick for a host while its field still shows it."""
        service_id = config.normalize_service_id(service_id)
        cfg = cfg or {}
        selected = self.selected_gallery_by_service
        record = selected.get(service_id) if isinstance(selected, dict) else None
        if not isinstance(record, dict) and service_id == config.PIXHOST_SERVICE_ID:
            record = selected.get(config.PIXHOST_LEGACY_SERVICE_ID)
        if not isinstance(record, dict):
            selected_by_service = cfg.get("selected_gallery_by_service", {})
            if isinstance(selected_by_service, dict):
                record = selected_by_service.get(service_id)
                if not isinstance(record, dict) and service_id == config.PIXHOST_SERVICE_ID:
                    record = selected_by_service.get(config.PIXHOST_LEGACY_SERVICE_ID)
        if not isinstance(record, dict):
            return None

        gallery_id = str(record.get("id") or "").strip()
        if not gallery_id:
            return None
        if not self._gallery_selection_matches_field(service_id, record, cfg):
            return None
        record_service = config.normalize_service_id(record.get("service") or service_id)
        url = str(record.get("url") or gallery_url_for_service(record_service, gallery_id))
        if record_service == config.PIXHOST_SERVICE_ID:
            url = config.normalize_pixhost_url(url)
        return {
            "service": record_service,
            "id": gallery_id,
            "name": str(record.get("name") or gallery_id),
            "url": url,
            "upload_hash": str(record.get("upload_hash") or ""),
        }

    def _gallery_selection_matches_field(
        self, service_id: str, record: Dict[str, Any], cfg: Dict[str, Any]
    ) -> bool:
        """Whether a Gallery Manager pick still agrees with the host's own field.

        The field (or Vipr's dropdown) is the one source of truth: picking a
        gallery fills it in, and editing, clearing or re-choosing it replaces
        the pick. When cfg does not carry the field the pick is kept.
        """
        service_id = config.normalize_service_id(service_id)
        gallery_id = str(record.get("id") or "").strip()
        if service_id == "vipr.im":
            if "vipr_gallery_name" not in cfg:
                return True
            name = str(cfg.get("vipr_gallery_name") or "").strip()
            if name != str(record.get("name") or gallery_id).strip():
                return False
            # Until the galleries are refreshed the name maps to no id ("0").
            mapped_id = str(cfg.get("vipr_gal_id") or "").strip()
            return mapped_id in {"", "0"} or mapped_id == gallery_id
        field_value = self._gallery_field_value(service_id, cfg)
        return field_value is None or field_value == gallery_id

    def _current_gallery_selections(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Drop Gallery Manager picks whose host field no longer shows them."""
        selected = self.selected_gallery_by_service
        if not isinstance(selected, dict):
            selected = {}
        current = {
            service_id: record
            for service_id, record in selected.items()
            if isinstance(record, dict)
            and self._gallery_selection_matches_field(service_id, record, cfg)
        }
        self.selected_gallery_by_service = current
        return dict(current)

    @staticmethod
    def _gallery_field_value(service_id: str, cfg: Dict[str, Any]) -> Optional[str]:
        """Return the host's own gallery field, or None when cfg does not carry it.

        Only the host's per-host key counts, plus the plain schema key when the
        host is cfg["service"]: a gallery ID typed for one host never applies
        to another.
        """
        service_id = config.normalize_service_id(service_id)
        keys = _GALLERY_FIELD_KEYS.get(service_id)
        if not keys:
            return None
        host_key, plain_key = keys
        owner = config.normalize_service_id(cfg.get("service") or service_id)
        candidates = (plain_key, host_key) if owner == service_id else (host_key,)
        present = [key for key in candidates if key in cfg]
        if not present:
            return None
        values = (str(cfg.get(key) or "").strip() for key in present)
        return next((value for value in values if value), "")

    def _gallery_id_from_settings(self, service_id: str, cfg: Dict[str, Any]) -> str:
        service_id = config.normalize_service_id(service_id)
        if service_id == "vipr.im":
            gallery_name = str(cfg.get("vipr_gallery_name") or "").strip()
            if not gallery_name or gallery_name == "None":
                return ""
            mapped_id = str(
                cfg.get("vipr_gal_id") or self.vipr_galleries_map.get(gallery_name) or ""
            ).strip()
            return "" if mapped_id == "0" else mapped_id
        return self._gallery_field_value(service_id, cfg) or ""

    def _gallery_for_group(
        self, group: Any, service_id: str, cfg: Dict[str, Any]
    ) -> Optional[Dict[str, str]]:
        service_id = config.normalize_service_id(service_id)
        group_gallery_id = str(getattr(group, "gallery_id", "") or "").strip()
        group_gallery_url = str(getattr(group, "gallery_url", "") or "").strip()
        group_service = ""
        if group_gallery_id or group_gallery_url:
            group_service = config.normalize_service_id(
                getattr(group, "gallery_service", "") or service_id
            )
        # A gallery assigned for another host is not this upload's gallery.
        if group_service and group_service == service_id:
            if not group_gallery_id:
                group_gallery_id = self._gallery_id_from_url(group_service, group_gallery_url)
            group_gallery_url = str(
                group_gallery_url or gallery_url_for_service(group_service, group_gallery_id)
            )
            if group_service == config.PIXHOST_SERVICE_ID:
                group_gallery_url = config.normalize_pixhost_url(group_gallery_url)
            return {
                "service": group_service,
                "id": group_gallery_id,
                "name": str(getattr(group, "gallery_name", "") or ""),
                "url": group_gallery_url,
                "upload_hash": str(getattr(group, "gallery_upload_hash", "") or ""),
            }

        selected = self._selected_gallery_for_service(service_id, cfg)
        if selected:
            return selected

        gallery_id = self._gallery_id_from_settings(service_id, cfg)
        if not gallery_id:
            return None

        # selected_gallery_* describe a Gallery Manager pick; ignore them when
        # they belong to another gallery than the one the field resolves to.
        selected_id = str(cfg.get("selected_gallery_id") or "").strip()
        details = cfg if not selected_id or selected_id == gallery_id else {}
        gallery_name = str(details.get("selected_gallery_name") or "").strip()
        if service_id == "vipr.im":
            gallery_name = str(cfg.get("vipr_gallery_name") or gallery_name).strip()
        selected_gallery_url = str(
            details.get("selected_gallery_url") or gallery_url_for_service(service_id, gallery_id)
        )
        if service_id == config.PIXHOST_SERVICE_ID:
            selected_gallery_url = config.normalize_pixhost_url(selected_gallery_url)
        return {
            "service": service_id,
            "id": gallery_id,
            "name": gallery_name,
            "url": selected_gallery_url,
            "upload_hash": str(details.get("selected_gallery_upload_hash") or ""),
        }

    @staticmethod
    def _gallery_id_from_url(service_id: str, gallery_url: str) -> str:
        service_id = config.normalize_service_id(service_id)
        if service_id == "turboimagehost" and "/album/" in gallery_url:
            return gallery_url.split("/album/", 1)[1].split("/", 1)[0].strip()
        if service_id == "imagebam.com" and "/view/" in gallery_url:
            return gallery_url.split("/view/", 1)[1].split("/", 1)[0].strip()
        if service_id == config.PIXHOST_SERVICE_ID:
            for marker in ("/gallery/", "/galleries/"):
                if marker in gallery_url:
                    return gallery_url.split(marker, 1)[1].split("/", 1)[0].strip()
        return ""

    def _apply_result_gallery_url(self, filepath: str, gallery_url: Any) -> None:
        clean_url = str(gallery_url or "").strip()
        if not clean_url:
            return

        row_data = self.file_widgets.get(filepath, {})
        group = row_data.get("group") if isinstance(row_data, dict) else None
        if group is None:
            return

        service_id = str(getattr(group, "gallery_service", "") or self.settings.get("service", ""))
        if service_id not in {"turboimagehost", "imagebam.com"}:
            return

        old_url = str(getattr(group, "gallery_url", "") or "").strip()
        group.gallery_url = clean_url
        group.gallery_service = service_id
        if not str(getattr(group, "gallery_id", "") or "").strip():
            group.gallery_id = self._gallery_id_from_url(service_id, clean_url)
        if not str(getattr(group, "gallery_name", "") or "").strip():
            group.gallery_name = self._batch_display_name(group)

        if old_url != clean_url:
            label = "Turbo" if service_id == "turboimagehost" else "ImageBam"
            self.add_activity(
                f"{label} gallery URL captured for {self._batch_display_name(group)}.",
                "info",
            )

    def _gallery_name_for_group(self, group: Any, service_id: str, cfg: Dict[str, Any]) -> str:
        gallery = self._gallery_for_group(group, service_id, cfg)
        if gallery and gallery.get("name"):
            return gallery["name"]
        return self._batch_display_name(group)

    def _gallery_id_is_valid_for_service(self, service_id: str, gallery_id: str) -> bool:
        service_id = config.normalize_service_id(service_id)
        gallery_id = str(gallery_id or "").strip()
        if not gallery_id:
            return True
        if service_id == "imx.to":
            return gallery_id.replace("_", "").isalnum()
        if service_id == "vipr.im":
            return gallery_id.isdigit() or gallery_id.isalnum()
        return gallery_id.isalnum()

    def _gallery_label_for_service(self, service_id: str) -> str:
        service_id = config.normalize_service_id(service_id)
        if service_id == config.PIXHOST_SERVICE_ID:
            return "gallery hash"
        if service_id == "vipr.im":
            return "gallery ID"
        return "gallery ID"

    def _finish_pixhost_finalization(self, finalization_events: List[Tuple[str, str]]) -> None:
        for message, level in finalization_events:
            self.add_activity(message, level)
        self._on_upload_complete()
