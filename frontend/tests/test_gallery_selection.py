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
