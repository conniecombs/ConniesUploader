# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

import pytest

from modules import controller


class RaisingViperGirlsAPI:
    def login(self, user, password):
        return True

    def post_reply(self, thread_id, content):
        raise RuntimeError("network failure")


class DummyTemplateManager:
    pass


@pytest.mark.unit
def test_process_post_queue_does_not_manually_release_condition(monkeypatch):
    monkeypatch.setattr(controller, "TemplateManager", DummyTemplateManager)

    upload_controller = controller.UploadController()
    upload_controller.creds = {"vg_user": "user", "vg_pass": "password"}
    upload_controller.settings = {"auto_post_thread": "thread"}
    upload_controller.is_uploading = False
    upload_controller.post_holding_pen = {0: "post body"}

    monkeypatch.setattr(
        controller.viper_api,
        "load_saved_threads",
        lambda: {"thread": {"url": "https://vipergirls.to/threads/123-test"}},
    )
    monkeypatch.setattr(controller.viper_api, "ViperGirlsAPI", RaisingViperGirlsAPI)
    monkeypatch.setattr(controller.config, "POST_COOLDOWN_SECONDS", 0)

    upload_controller._process_post_queue()

    assert upload_controller.next_post_index == 1
    assert upload_controller.post_holding_pen == {}
