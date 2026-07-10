# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

from pathlib import Path

from fastapi.testclient import TestClient

from modules import config
from modules.credential_store import JsonCredentialStore
from modules.settings_manager import SettingsManager
from modules.upload_models import UploadFileResult
from modules.upload_session import UploadSessionRegistry
from web.app import create_app


class FakeUploadManager:
    def __init__(self, progress_queue, result_queue, cancel_event):
        self.progress_queue = progress_queue
        self.result_queue = result_queue
        self.cancel_event = cancel_event
        self.started = None

    def start_batch(self, pending_by_group, settings, credentials):
        self.started = (pending_by_group, settings, credentials)
        for files in pending_by_group.values():
            for file_path in files:
                self.progress_queue.put(("status", file_path, "Done"))
                self.result_queue.put(
                    (file_path, "https://img.test/view", "https://img.test/thumb")
                )


def make_web_client(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    history_dir = data_dir / "history"
    upload_dir = data_dir / "uploads"
    for directory in (data_dir, input_dir, output_dir, history_dir, upload_dir):
        directory.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "USER_DATA_DIR", str(data_dir))
    monkeypatch.setattr(config, "INPUT_DIR", str(input_dir))
    monkeypatch.setattr(config, "OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(config, "HISTORY_DIR", str(history_dir))
    monkeypatch.setattr(config, "WEB_UPLOAD_DIR", str(upload_dir))

    settings_manager = SettingsManager()
    settings_manager.filepath = str(data_dir / "user_settings.json")
    app = create_app()
    app.state.registry = UploadSessionRegistry()
    app.state.settings_manager = settings_manager
    app.state.credential_store = JsonCredentialStore(str(data_dir / "credentials.json"))
    app.state.manager_factory = FakeUploadManager
    return TestClient(app), {
        "data": data_dir,
        "input": input_dir,
        "output": output_dir,
        "history": history_dir,
        "uploads": upload_dir,
    }


def test_services_endpoint_returns_plugin_schema(monkeypatch, tmp_path):
    client, _paths = make_web_client(monkeypatch, tmp_path)

    response = client.get("/api/services")

    assert response.status_code == 200
    services = response.json()["services"]
    pixhost = next(service for service in services if service["id"] == "pixhost.to")
    assert pixhost["name"] == "Pixhost.to"
    assert pixhost["settings_schema"]


def test_settings_endpoints_load_validate_and_save(monkeypatch, tmp_path):
    client, paths = make_web_client(monkeypatch, tmp_path)

    get_response = client.get("/api/settings")
    put_response = client.put(
        "/api/settings",
        json={"settings": {"service": "pixhost.to", "global_worker_count": 99}},
    )

    assert get_response.status_code == 200
    assert put_response.status_code == 200
    assert put_response.json()["settings"]["service"] == "pixhost.to"
    assert put_response.json()["settings"]["global_worker_count"] == config.MAX_WORKER_COUNT
    assert (paths["data"] / "user_settings.json").exists()


def test_credentials_update_returns_only_status(monkeypatch, tmp_path):
    client, paths = make_web_client(monkeypatch, tmp_path)

    response = client.put(
        "/api/credentials",
        json={"credentials": {"imx_api": "secret-token", "unknown": "ignored"}},
    )
    status_response = client.get("/api/credentials/status")

    assert response.status_code == 200
    payload = status_response.json()
    imx_api = next(field for field in payload["fields"] if field["key"] == "imx_api")
    assert imx_api["present"] is True
    assert "secret-token" not in status_response.text
    assert "unknown" not in (paths["data"] / "credentials.json").read_text(encoding="utf-8")


def test_input_listing_and_path_traversal_guard(monkeypatch, tmp_path):
    client, paths = make_web_client(monkeypatch, tmp_path)
    image_path = paths["input"] / "sample.jpg"
    image_path.write_bytes(b"fake image bytes")

    response = client.get("/api/files/input")
    traversal = client.get("/api/files/input", params={"path": ".."})

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert entries[0]["name"] == "sample.jpg"
    assert entries[0]["selectable"] is True
    assert traversal.status_code == 400


def test_browser_upload_stages_file_under_data(monkeypatch, tmp_path):
    client, paths = make_web_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/files/upload",
        files=[("files", ("uploaded.jpg", b"fake image bytes", "image/jpeg"))],
    )

    assert response.status_code == 200
    saved_path = Path(response.json()["files"][0]["path"])
    assert saved_path.exists()
    assert saved_path.is_relative_to(paths["uploads"])


def test_upload_start_status_cancel_and_sse(monkeypatch, tmp_path):
    client, paths = make_web_client(monkeypatch, tmp_path)
    image_path = paths["input"] / "queued.jpg"
    image_path.write_bytes(b"fake image bytes")

    start_response = client.post(
        "/api/uploads",
        json={
            "settings": {"service": "pixhost.to", "global_worker_count": 1},
            "groups": [{"title": "Batch", "files": [str(image_path)]}],
        },
    )

    assert start_response.status_code == 200
    upload_id = start_response.json()["upload"]["id"]

    status_response = client.get(f"/api/uploads/{upload_id}")
    assert status_response.status_code == 200
    upload = status_response.json()["upload"]
    assert upload["state"] == "complete"
    assert upload["completed_files"] == 1
    assert upload["results"] == [
        {
            "file_path": str(image_path),
            "viewer_url": "https://img.test/view",
            "thumb_url": "https://img.test/thumb",
        }
    ]

    events_response = client.get(f"/api/uploads/{upload_id}/events")
    assert events_response.status_code == 200
    assert "event: snapshot" in events_response.text

    cancel_response = client.post(f"/api/uploads/{upload_id}/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["upload"]["state"] == "cancelled"


def test_history_listing_and_output_download(monkeypatch, tmp_path):
    client, paths = make_web_client(monkeypatch, tmp_path)
    history_file = paths["history"] / "old.txt"
    output_file = paths["output"] / "result.txt"
    history_file.write_text("history", encoding="utf-8")
    output_file.write_text("output", encoding="utf-8")

    history_response = client.get("/api/history")
    output_response = client.get("/api/output/result.txt")
    traversal = client.get("/api/output/%2e%2e/secret.txt")

    assert history_response.status_code == 200
    assert history_response.json()["entries"][0]["name"] == "old.txt"
    assert output_response.status_code == 200
    assert output_response.text == "output"
    assert traversal.status_code == 400


def test_upload_file_result_model_remains_json_shape():
    result = UploadFileResult("file.jpg", "viewer", "thumb")

    assert result.file_path == "file.jpg"
    assert result.viewer_url == "viewer"
    assert result.thumb_url == "thumb"
