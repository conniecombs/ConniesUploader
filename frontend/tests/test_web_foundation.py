# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

import importlib

from fastapi.testclient import TestClient

from modules import config
from web.app import create_app


def test_health_endpoint_reports_web_runtime_paths():
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["app"] == "ConniesUploader"
    assert payload["version"] == config.APP_VERSION
    assert payload["paths"]["data"] == config.USER_DATA_DIR
    assert payload["paths"]["input"] == config.INPUT_DIR
    assert payload["paths"]["output"] == config.OUTPUT_DIR
    assert payload["paths"]["uploads"] == config.WEB_UPLOAD_DIR


def test_config_accepts_container_path_overrides(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"

    monkeypatch.setenv("CONNIESUPLOADER_MODE", "web")
    monkeypatch.setenv("CONNIESUPLOADER_DATA_DIR", str(data_dir))
    monkeypatch.setenv("CONNIESUPLOADER_INPUT_DIR", str(input_dir))
    monkeypatch.setenv("CONNIESUPLOADER_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("CONNIESUPLOADER_PORT", "9090")

    reloaded = importlib.reload(config)
    try:
        assert reloaded.APP_MODE == "web"
        assert reloaded.USER_DATA_DIR == str(data_dir)
        assert reloaded.INPUT_DIR == str(input_dir)
        assert reloaded.OUTPUT_DIR == str(output_dir)
        assert reloaded.WEB_UPLOAD_DIR == str(data_dir / "uploads")
        assert reloaded.HISTORY_DIR == str(data_dir / "history")
        assert reloaded.WEB_PORT == 9090
        assert reloaded.CRASH_LOG_FILE == str(data_dir / "crash_log.log")
    finally:
        monkeypatch.delenv("CONNIESUPLOADER_MODE", raising=False)
        monkeypatch.delenv("CONNIESUPLOADER_DATA_DIR", raising=False)
        monkeypatch.delenv("CONNIESUPLOADER_INPUT_DIR", raising=False)
        monkeypatch.delenv("CONNIESUPLOADER_OUTPUT_DIR", raising=False)
        monkeypatch.delenv("CONNIESUPLOADER_PORT", raising=False)
        importlib.reload(config)
