# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

import threading
from pathlib import Path

from fastapi.testclient import TestClient

from modules import config
from modules.credential_store import JsonCredentialStore
from modules.settings_manager import SettingsManager
from modules.upload_models import UploadBatch, UploadFileResult
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


class FailingUploadManager(FakeUploadManager):
    def start_batch(self, pending_by_group, settings, credentials):
        self.started = (pending_by_group, settings, credentials)
        for files in pending_by_group.values():
            for file_path in files:
                self.progress_queue.put(("status", file_path, "error: failed"))
                self.result_queue.put((file_path, "", ""))


class SlowUploadManager(FakeUploadManager):
    def start_batch(self, pending_by_group, settings, credentials):
        self.started = (pending_by_group, settings, credentials)
        for files in pending_by_group.values():
            for file_path in files:
                self.progress_queue.put(("status", file_path, "queued"))


class AtomicOnlyRegistry(UploadSessionRegistry):
    def has_active(self):
        raise AssertionError("Upload API should use create_if_idle()")


class FakeViperGirlsPoster:
    def __init__(self):
        self.calls = []

    def login(self, username, password):
        self.calls.append(("login", username, password))
        return True

    def post_reply(self, thread_id, message):
        self.calls.append(("post_reply", thread_id, message))
        return True


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
    assert payload["storage"] == "file"
    assert "file" not in payload
    imx_api = next(field for field in payload["fields"] if field["key"] == "imx_api")
    assert imx_api["present"] is True
    assert "secret-token" not in status_response.text
    assert "unknown" not in (paths["data"] / "credentials.json").read_text(encoding="utf-8")


def test_vipergirls_target_preview_schedule_history_and_delete(monkeypatch, tmp_path):
    client, _paths = make_web_client(monkeypatch, tmp_path)

    save_response = client.put(
        "/api/vipergirls/targets",
        json={
            "name": "My Target",
            "url": "https://vipergirls.to/threads/98765-sample",
            "notes": "Pinned set",
            "tags": ["sample", "web"],
        },
    )
    list_response = client.get("/api/vipergirls/targets")
    preview_response = client.post(
        "/api/vipergirls/preview",
        json={"target_name": "My Target", "message": "[url]https://img.test/view[/url]"},
    )
    schedule_response = client.post(
        "/api/vipergirls/scheduled",
        json={
            "target_name": "My Target",
            "message": "scheduled body",
            "scheduled_time": "2035-01-02T03:04:05+00:00",
        },
    )
    scheduled_id = schedule_response.json()["scheduled"]["id"]
    cancel_response = client.delete(f"/api/vipergirls/scheduled/{scheduled_id}")
    clear_history_response = client.delete("/api/vipergirls/history")
    delete_response = client.delete("/api/vipergirls/targets/My%20Target")

    assert save_response.status_code == 200
    assert save_response.json()["target"]["thread_id"] == "98765"
    assert save_response.json()["target"]["tags"] == ["sample", "web"]
    assert list_response.status_code == 200
    assert list_response.json()["targets"][0]["name"] == "My Target"
    assert preview_response.status_code == 200
    assert preview_response.json()["message"] == "[url]https://img.test/view[/url]"
    assert schedule_response.status_code == 200
    assert schedule_response.json()["scheduled"]["thread_id"] == "98765"
    assert cancel_response.status_code == 200
    assert cancel_response.json()["scheduled"] == []
    assert clear_history_response.status_code == 200
    assert clear_history_response.json()["history"] == []
    assert delete_response.status_code == 200
    assert delete_response.json()["targets"] == []


def test_vipergirls_manual_post_uses_saved_credentials_and_records_history(monkeypatch, tmp_path):
    client, _paths = make_web_client(monkeypatch, tmp_path)
    poster = FakeViperGirlsPoster()
    client.app.state.viper_api_factory = lambda: poster

    client.put(
        "/api/credentials",
        json={"credentials": {"vg_user": "poster", "vg_pass": "secret"}},
    )
    client.put(
        "/api/vipergirls/targets",
        json={"name": "My Target", "url": "https://vipergirls.to/threads/98765-sample"},
    )
    response = client.post(
        "/api/vipergirls/post",
        json={
            "target_name": "My Target",
            "message": "hello from web",
            "batch_name": "Manual Batch",
        },
    )
    history_response = client.get("/api/vipergirls/history")
    target_response = client.get("/api/vipergirls/targets")

    assert response.status_code == 200
    assert poster.calls == [
        ("login", "poster", "secret"),
        ("post_reply", "98765", "hello from web"),
    ]
    history = history_response.json()["history"]
    assert history[0]["status"] == "success"
    assert history[0]["batch_name"] == "Manual Batch"
    assert history[0]["thread_id"] == "98765"
    assert target_response.json()["targets"][0]["last_used_at"]


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
    assert upload["failed_files"] == 0
    assert upload["results"] == [
        {
            "file_path": str(image_path),
            "viewer_url": "https://img.test/view",
            "thumb_url": "https://img.test/thumb",
            "success": True,
            "error": "",
        }
    ]

    events_response = client.get(f"/api/uploads/{upload_id}/events")
    assert events_response.status_code == 200
    assert "event: result" in events_response.text
    assert "event: output" in events_response.text

    cancel_response = client.post(f"/api/uploads/{upload_id}/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["upload"]["state"] == "cancelled"


def test_upload_auto_posts_generated_output_to_vipergirls(monkeypatch, tmp_path):
    client, paths = make_web_client(monkeypatch, tmp_path)
    poster = FakeViperGirlsPoster()
    client.app.state.viper_api_factory = lambda: poster
    image_path = paths["input"] / "queued.jpg"
    image_path.write_bytes(b"fake image bytes")

    client.put(
        "/api/credentials",
        json={"credentials": {"vg_user": "poster", "vg_pass": "secret"}},
    )
    client.put(
        "/api/vipergirls/targets",
        json={"name": "My Target", "url": "https://vipergirls.to/threads/98765-sample"},
    )

    response = client.post(
        "/api/uploads",
        json={
            "settings": {
                "service": "pixhost.to",
                "global_worker_count": 1,
                "auto_post_enabled": True,
                "output_format": "BBCode",
            },
            "groups": [
                {
                    "title": "Auto Batch",
                    "files": [str(image_path)],
                    "selected_thread": "My Target",
                }
            ],
        },
    )
    history_response = client.get("/api/vipergirls/history")

    assert response.status_code == 200
    assert response.json()["upload"]["state"] == "complete"
    assert poster.calls[0] == ("login", "poster", "secret")
    assert poster.calls[1][0] == "post_reply"
    assert poster.calls[1][1] == "98765"
    assert "https://img.test/view" in poster.calls[1][2]
    history = history_response.json()["history"]
    assert history[0]["status"] == "success"
    assert history[0]["batch_name"] == "Auto Batch"


def test_upload_failures_mark_session_failed(monkeypatch, tmp_path):
    client, paths = make_web_client(monkeypatch, tmp_path)
    client.app.state.manager_factory = FailingUploadManager
    image_path = paths["input"] / "queued.jpg"
    image_path.write_bytes(b"fake image bytes")

    response = client.post(
        "/api/uploads",
        json={
            "settings": {"service": "pixhost.to", "global_worker_count": 1},
            "groups": [{"title": "Batch", "files": [str(image_path)]}],
        },
    )

    assert response.status_code == 200
    upload = response.json()["upload"]
    assert upload["state"] == "failed"
    assert upload["completed_files"] == 1
    assert upload["failed_files"] == 1
    assert upload["results"][0]["success"] is False
    assert upload["results"][0]["error"] == "Upload failed"


def test_upload_rejects_empty_groups_without_starting_session(monkeypatch, tmp_path):
    client, paths = make_web_client(monkeypatch, tmp_path)
    client.app.state.manager_factory = SlowUploadManager
    image_path = paths["input"] / "queued.jpg"
    image_path.write_bytes(b"fake image bytes")

    empty_response = client.post(
        "/api/uploads",
        json={
            "settings": {"service": "pixhost.to", "global_worker_count": 1},
            "groups": [{"title": "Empty Batch", "files": []}],
        },
    )
    valid_response = client.post(
        "/api/uploads",
        json={
            "settings": {"service": "pixhost.to", "global_worker_count": 1},
            "groups": [{"title": "Batch", "files": [str(image_path)]}],
        },
    )

    assert empty_response.status_code == 400
    assert empty_response.json()["detail"] == "At least one upload file is required"
    assert valid_response.status_code == 200
    assert valid_response.json()["upload"]["state"] == "running"


def test_registry_create_if_idle_reserves_active_slot_atomically(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "INPUT_DIR", str(tmp_path))
    image_path = tmp_path / "queued.jpg"
    image_path.write_bytes(b"fake image bytes")
    registry = UploadSessionRegistry()
    group = UploadBatch("Batch", [str(image_path)])
    settings = {"service": "pixhost.to", "global_worker_count": 1}
    barrier = threading.Barrier(6)
    results = []
    errors = []
    result_lock = threading.Lock()

    def create_session():
        try:
            barrier.wait(timeout=5)
            session = registry.create_if_idle(
                [group],
                settings,
                {},
                manager_factory=SlowUploadManager,
            )
            with result_lock:
                results.append(session)
        except Exception as exc:
            with result_lock:
                errors.append(exc)

    threads = [threading.Thread(target=create_session) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    winners = [session for session in results if session is not None]
    assert errors == []
    assert len(results) == 6
    assert len(winners) == 1
    assert registry.has_active() is True


def test_only_one_upload_can_run_at_a_time(monkeypatch, tmp_path):
    client, paths = make_web_client(monkeypatch, tmp_path)
    client.app.state.manager_factory = SlowUploadManager
    client.app.state.registry = AtomicOnlyRegistry()
    image_path = paths["input"] / "queued.jpg"
    image_path.write_bytes(b"fake image bytes")
    payload = {
        "settings": {"service": "pixhost.to", "global_worker_count": 1},
        "groups": [{"title": "Batch", "files": [str(image_path)]}],
    }

    first = client.post("/api/uploads", json=payload)
    second = client.post("/api/uploads", json=payload)

    assert first.status_code == 200
    assert first.json()["upload"]["state"] == "running"
    assert second.status_code == 409


def test_history_listing_output_download_and_delete(monkeypatch, tmp_path):
    client, paths = make_web_client(monkeypatch, tmp_path)
    history_file = paths["history"] / "result.txt"
    output_file = paths["output"] / "result.txt"
    history_file.write_text("history", encoding="utf-8")
    output_file.write_text("output", encoding="utf-8")

    history_response = client.get("/api/history")
    output_response = client.get("/api/output/result.txt")
    output_traversal = client.get("/api/output/%2e%2e/secret.txt")
    history_delete_traversal = client.delete("/api/history/%2e%2e/secret.txt")
    output_delete = client.delete("/api/output/result.txt")
    output_missing = client.delete("/api/output/result.txt")

    assert history_response.status_code == 200
    assert history_response.json()["entries"][0]["name"] == "result.txt"
    assert output_response.status_code == 200
    assert output_response.text == "output"
    assert output_traversal.status_code == 400
    assert history_delete_traversal.status_code == 400
    assert output_delete.status_code == 200
    assert output_delete.json()["deleted"]["name"] == "result.txt"
    assert not output_file.exists()
    assert history_file.exists()
    assert output_missing.status_code == 404
    history_delete = client.delete("/api/history/result.txt")
    assert history_delete.status_code == 200
    assert not history_file.exists()


def test_upload_file_result_model_remains_json_shape():
    result = UploadFileResult("file.jpg", "viewer", "thumb")

    assert result.file_path == "file.jpg"
    assert result.viewer_url == "viewer"
    assert result.thumb_url == "thumb"
