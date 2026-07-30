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


class FailingTemplateManager:
    def apply(self, *_args, **_kwargs):
        raise AssertionError("partial output should not be rendered")


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


@pytest.mark.unit
def test_upload_controller_skips_output_for_incomplete_results(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    first = str(tmp_path / "first.jpg")
    second = str(tmp_path / "second.jpg")
    upload_controller = controller.UploadController.__new__(controller.UploadController)
    upload_controller.results = [
        (first, "https://img.test/first", "https://img.test/first-thumb"),
        (second, "", ""),
    ]
    upload_controller.settings = {"service": "pixhost.to"}
    upload_controller.template_mgr = FailingTemplateManager()
    upload_controller.current_output_files = []

    output_file = upload_controller.generate_group_output(
        "Batch Alpha",
        [first, second],
        None,
        0,
    )

    assert output_file is None
    assert upload_controller.current_output_files == []
    assert not (tmp_path / "Output").exists()
