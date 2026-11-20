# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""One gallery per host: Gallery Manager picks, gallery fields and preflight agree."""

import json
from threading import Lock

import pytest

from modules.gallery_service import GalleryRecord
from modules.plugin_manager import PluginManager
from modules.plugins.vipr import ViprPlugin
from modules.widgets import ServiceSettingsView
from tests.app_factory import make_app
from tests.test_main_window_contract import FakeGroup, FakeVar

_VIPR_CREDS = {"vipr_user": "u", "vipr_pass": "p"}


class FakeCombo:
    def __init__(self, values):
        self._values = list(values)

    def configure(self, **kwargs):
        self._values = list(kwargs.get("values", self._values))


@pytest.fixture(scope="module")
def plugin_manager():
    return PluginManager()


def _gallery_app(plugin_manager, service="imx.to"):
    """An app whose settings panel is a real ServiceSettingsView over FakeVars."""
    app = make_app()
    app.lock = Lock()
    app.settings = {}
    view = ServiceSettingsView.__new__(ServiceSettingsView)
    view.app = app
    view.plugin_manager = plugin_manager
    view.service_handles = {}
    view.service_plugins = {}
    for plugin in plugin_manager.get_all_plugins():
        handle = {}
        for field in plugin.settings_schema:
            for subfield in field.get("fields", [field]):
                if "key" in subfield:
                    handle[subfield["key"]] = FakeVar(subfield.get("default", ""))
        if plugin.id == "vipr.im":
            plugin.vipr_galleries_map = {}
            plugin.vipr_gallery_urls_map = {}
            handle["vipr_gallery_name"] = FakeVar("None")
        view.service_handles[plugin.id] = handle
        view.service_plugins[plugin.id] = plugin
    app.settings_view = view
    app.service_plugins = view.service_plugins
    app.cb_vipr_gallery = FakeCombo(["None"])
    app.var_service = FakeVar(service)
    for name, value in dict(
        var_global_worker_count=8,
        menu_thread_var=5,
        var_imx_threads=5,
        var_pix_threads=3,
        var_turbo_threads=2,
        var_vipr_threads=1,
        var_ib_threads=2,
        var_imgur_threads=2,
        var_auto_copy=False,
        var_confirm_before_posting=False,
        var_auto_gallery=False,
        var_show_previews=True,
        var_separate_batches=False,
        var_appearance_mode="System",
    ).items():
        setattr(app, name, FakeVar(value))
    app.set_global_threads = lambda value: None
    app._swap_service_frame = lambda service_id: None
    app.add_activity = lambda message, level="info": None
    return app, view


def _preflight(app, plugin, group, cfg):
    issues = []
    summary = app._preflight_check_galleries(plugin, {group: ["/x/1.jpg"]}, cfg, issues)
    return issues, summary


# --- E3: gallery ids must not bleed between hosts ---------------------------


@pytest.mark.unit
@pytest.mark.parametrize("service", ["imagebam.com", "imgur.com"])
def test_turbo_gallery_id_does_not_apply_to_other_hosts(plugin_manager, service):
    app, view = _gallery_app(plugin_manager, service)
    view.set_value("turboimagehost", "gallery_id", "98765")
    group = FakeGroup("Holiday")

    cfg = app._gather_settings()

    assert app._gallery_for_group(group, service, cfg) is None
    assert _preflight(app, plugin_manager.get_plugin(service), group, cfg) == ([], "")


@pytest.mark.unit
def test_turbo_gallery_id_still_applies_to_turbo(plugin_manager):
    app, view = _gallery_app(plugin_manager, "turboimagehost")
    view.set_value("turboimagehost", "gallery_id", "98765")

    cfg = app._gather_settings()

    assert app._gallery_for_group(FakeGroup("Holiday"), "turboimagehost", cfg)["id"] == "98765"


@pytest.mark.unit
def test_imx_gallery_id_is_not_restored_into_imagebam_after_restart(plugin_manager):
    app, view = _gallery_app(plugin_manager, "imx.to")
    view.set_value("imx.to", "gallery_id", "IMXGAL1")
    saved = json.loads(json.dumps(app._gather_settings()))

    app.settings = saved

    assert view._settings_for_service("imx.to")["gallery_id"] == "IMXGAL1"
    assert view._settings_for_service("imagebam.com").get("gallery_id", "") == ""
    assert view._settings_for_service("turboimagehost").get("gallery_id", "") == ""


@pytest.mark.unit
def test_imagebam_gallery_token_is_saved_under_its_own_key(plugin_manager):
    app, view = _gallery_app(plugin_manager, "imx.to")
    view.set_value("imagebam.com", "gallery_id", "IBTOKEN")
    view.set_value("imx.to", "gallery_id", "IMXGAL1")
    saved = json.loads(json.dumps(app._gather_settings()))

    app.settings = saved

    assert saved["imagebam_gallery_id"] == "IBTOKEN"
    assert view._settings_for_service("imagebam.com")["gallery_id"] == "IBTOKEN"


@pytest.mark.unit
def test_legacy_plain_gallery_id_only_restores_into_the_saved_host(plugin_manager):
    app, view = _gallery_app(plugin_manager)
    app.settings = {"service": "imagebam.com", "gallery_id": "IBOLD", "imx_gallery_id": ""}

    assert view._settings_for_service("imagebam.com")["gallery_id"] == "IBOLD"
    assert view._settings_for_service("imx.to")["gallery_id"] == ""
    assert view._settings_for_service("turboimagehost").get("gallery_id", "") == ""


# --- E2: the gallery field is the single source of truth per host -----------


def _pick(app, service, gallery_id, name):
    app.on_gallery_created(
        GalleryRecord(service=service, id=gallery_id, name=name, url=f"https://x/{gallery_id}")
    )


@pytest.mark.unit
def test_gallery_manager_pick_is_used_while_field_still_holds_it(plugin_manager):
    app, view = _gallery_app(plugin_manager, "imx.to")
    _pick(app, "imx.to", "AAA111", "Old shoot")

    cfg = app._gather_settings()

    assert view.get_raw_config("imx.to")["gallery_id"] == "AAA111"
    assert plugin_manager.get_plugin("imx.to")._gallery_id_from_config(cfg) == "AAA111"
    gallery = app._gallery_for_group(FakeGroup("New shoot"), "imx.to", cfg)
    assert (gallery["id"], gallery["name"]) == ("AAA111", "Old shoot")


@pytest.mark.unit
def test_typing_another_gallery_id_replaces_gallery_manager_pick(plugin_manager):
    app, view = _gallery_app(plugin_manager, "imx.to")
    imx = plugin_manager.get_plugin("imx.to")
    group = FakeGroup("New shoot")
    _pick(app, "imx.to", "AAA111", "Old shoot")

    view.set_value("imx.to", "gallery_id", "BBB222")
    cfg = app._gather_settings()

    assert imx._gallery_id_from_config(cfg) == "BBB222"
    assert app._gallery_for_group(group, "imx.to", cfg)["id"] == "BBB222"
    issues, summary = _preflight(app, imx, group, cfg)
    assert issues == []
    assert "BBB222" in summary and "AAA111" not in summary
    assert "selected_gallery_id" not in cfg
    assert cfg["selected_gallery_by_service"] == {}
    assert app.selected_gallery_by_service == {}


@pytest.mark.unit
def test_clearing_gallery_field_clears_gallery_manager_pick(plugin_manager):
    app, view = _gallery_app(plugin_manager, "imx.to")
    imx = plugin_manager.get_plugin("imx.to")
    group = FakeGroup("New shoot")
    _pick(app, "imx.to", "AAA111", "Old shoot")

    view.set_value("imx.to", "gallery_id", "")
    cfg = app._gather_settings()

    assert imx._gallery_id_from_config(cfg) == ""
    assert app._gallery_for_group(group, "imx.to", cfg) is None
    assert _preflight(app, imx, group, cfg) == ([], "")
    assert app.selected_gallery_by_service == {}


@pytest.mark.unit
def test_stale_saved_pick_is_ignored_for_output(plugin_manager):
    app, _view = _gallery_app(plugin_manager, "imx.to")
    app.selected_gallery_by_service = {}
    saved = {
        "service": "imx.to",
        "gallery_id": "BBB222",
        "imx_gallery_id": "BBB222",
        "selected_gallery_by_service": {
            "imx.to": {"service": "imx.to", "id": "AAA111", "name": "Old shoot"}
        },
    }

    gallery = app._gallery_for_group(FakeGroup("New shoot"), "imx.to", saved)

    assert gallery["id"] == "BBB222"
    assert gallery["name"] != "Old shoot"


@pytest.mark.unit
def test_assigning_gallery_to_selected_batches_leaves_other_batches_alone(plugin_manager, tmp_path):
    app, _view = _gallery_app(plugin_manager, "imx.to")
    selected_path = str(tmp_path / "a.jpg")
    selected, other = FakeGroup("Selected", [selected_path]), FakeGroup("Other")
    app.file_widgets = {selected_path: {"group": selected}}
    app.selected_files = {selected_path}

    app.on_gallery_assign_to_selected_batches(
        "imx.to", "IMX_123", GalleryRecord(service="imx.to", id="IMX_123", name="Thread")
    )
    cfg = app._gather_settings()

    assert app._gallery_for_group(selected, "imx.to", cfg)["id"] == "IMX_123"
    assert app._gallery_for_group(other, "imx.to", cfg) is None
    assert plugin_manager.get_plugin("imx.to")._gallery_id_from_config(cfg) == ""


@pytest.mark.unit
def test_vipr_dropdown_choice_replaces_gallery_manager_pick(plugin_manager):
    app, view = _gallery_app(plugin_manager, "vipr.im")
    vipr = plugin_manager.get_plugin("vipr.im")
    vipr.vipr_galleries_map = {"Picked": "111", "Other": "222"}
    group = FakeGroup("Batch")
    _pick(app, "vipr.im", "111", "Picked")

    cfg = app._gather_settings()
    assert vipr._gallery_id_from_config(cfg) == "111"
    assert app._gallery_for_group(group, "vipr.im", cfg)["id"] == "111"

    view.set_value("vipr.im", "vipr_gallery_name", "Other")
    cfg = app._gather_settings()
    assert vipr._gallery_id_from_config(cfg) == "222"
    assert app._gallery_for_group(group, "vipr.im", cfg)["id"] == "222"

    view.set_value("vipr.im", "vipr_gallery_name", "None")
    cfg = app._gather_settings()
    assert vipr._gallery_id_from_config(cfg) == "0"
    assert app._gallery_for_group(group, "vipr.im", cfg) is None
    assert app.selected_gallery_by_service == {}


@pytest.mark.unit
def test_vipr_gallery_manager_pick_survives_restart_without_refresh(plugin_manager):
    app, view = _gallery_app(plugin_manager, "vipr.im")
    vipr = plugin_manager.get_plugin("vipr.im")
    app.selected_gallery_by_service = {
        "vipr.im": {"service": "vipr.im", "id": "111", "name": "Summer 2026", "url": ""}
    }
    view.set_value("vipr.im", "vipr_gallery_name", "Summer 2026")

    cfg = app._gather_settings()

    assert cfg["vipr_gal_id"] == "0"  # name -> id map is empty until a refresh
    assert vipr._gallery_id_from_config(cfg) == "111"
    assert app._gallery_for_group(FakeGroup("Batch"), "vipr.im", cfg)["id"] == "111"
    assert _preflight(app, vipr, FakeGroup("Batch"), cfg)[0] == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cfg", "expected"),
    [
        ({"selected_gallery_id": "111", "vipr_gallery_name": "Other", "vipr_gal_id": "222"}, "222"),
        ({"selected_gallery_id": "111", "vipr_gallery_name": "None", "vipr_gal_id": "0"}, "0"),
        ({"selected_gallery_id": "111", "vipr_gallery_name": "", "vipr_gal_id": "0"}, "0"),
        ({"gallery_id": "group1", "vipr_gallery_name": "Other", "vipr_gal_id": "222"}, "group1"),
    ],
)
def test_vipr_upload_gallery_follows_the_dropdown(cfg, expected):
    spec = ViprPlugin().build_http_request("/x/a.jpg", cfg, _VIPR_CREDS)

    assert spec["multipart_fields"]["fld_id"]["value"] == expected


# --- E4: unmatched Vipr gallery name must block the upload ------------------

_VIPR_UNMATCHED = (
    'Vipr gallery "Summer 2026" could not be matched to an upload ID. '
    "Refresh galleries or select it again."
)


@pytest.mark.unit
def test_vipr_saved_gallery_name_without_id_is_reported(plugin_manager):
    app, view = _gallery_app(plugin_manager, "vipr.im")
    vipr = plugin_manager.get_plugin("vipr.im")
    view.set_value("vipr.im", "vipr_gallery_name", "Summer 2026")
    cfg = app._gather_settings()
    groups = {FakeGroup("Batch A"): ["/x/1.jpg"], FakeGroup("Batch B"): ["/x/2.jpg"]}

    issues = []
    app._preflight_check_galleries(vipr, groups, cfg, issues)

    assert cfg["vipr_gal_id"] == "0"
    assert issues == [_VIPR_UNMATCHED]


@pytest.mark.unit
def test_vipr_unmatched_check_skips_batches_with_their_own_gallery():
    app = make_app()
    group = FakeGroup("Batch A")
    group.gallery_id = "555"
    group.gallery_service = "vipr.im"
    cfg = {"service": "vipr.im", "vipr_gallery_name": "Summer 2026", "vipr_gal_id": "0"}

    issues = []
    app._preflight_check_galleries(ViprPlugin(), {group: ["/x/1.jpg"]}, cfg, issues)

    assert issues == []


@pytest.mark.unit
@pytest.mark.parametrize("name", ["None", ""])
def test_vipr_no_gallery_selected_is_not_an_issue(name):
    app = make_app()
    cfg = {"service": "vipr.im", "vipr_gallery_name": name, "vipr_gal_id": "0"}

    issues = []
    app._preflight_check_galleries(ViprPlugin(), {FakeGroup("A"): ["/x/1.jpg"]}, cfg, issues)

    assert issues == []
