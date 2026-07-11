# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

import importlib
import base64

from fastapi.testclient import TestClient

from modules import config
from modules import viper_api
from modules.credential_store import JsonCredentialStore
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
    assert payload["security"]["auth_required"] == config.WEB_AUTH_REQUIRED


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


def test_web_auth_first_run_setup_flow(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "WEB_AUTH_REQUIRED", True)
    monkeypatch.setattr(config, "WEB_PASSWORD", "")
    monkeypatch.setattr(config, "WEB_TOKEN", "")
    monkeypatch.setattr(config, "WEB_AUTH_FILE", str(tmp_path / "web_auth.json"))
    monkeypatch.setattr(config, "WEB_DOCS_ENABLED", False)
    client = TestClient(create_app())

    health = client.get("/api/health")
    root = client.get("/", follow_redirects=False)
    setup = client.get("/setup")
    status = client.get("/api/auth/status")
    protected_api = client.get("/api/services")
    weak_password = client.post(
        "/api/auth/setup",
        json={"username": "connie", "password": "short"},
    )
    created = client.post(
        "/api/auth/setup",
        json={"username": "connie", "password": "strong-password"},
    )
    account_text = (tmp_path / "web_auth.json").read_text(encoding="utf-8")
    authenticated_root = client.get("/")
    duplicate_setup = client.post(
        "/api/auth/setup",
        json={"username": "other", "password": "another-password"},
    )
    logged_out = client.post("/api/auth/logout")
    login_redirect = client.get("/", follow_redirects=False)

    assert health.status_code == 200
    assert health.json()["security"]["setup_required"] is True
    assert root.status_code == 303
    assert root.headers["location"] == "/setup"
    assert setup.status_code == 200
    assert status.json()["setup_required"] is True
    assert protected_api.status_code == 428
    assert weak_password.status_code == 400
    assert created.status_code == 200
    assert "strong-password" not in account_text
    assert authenticated_root.status_code == 200
    assert duplicate_setup.status_code == 409
    assert logged_out.status_code == 200
    assert login_redirect.status_code == 303
    assert login_redirect.headers["location"] == "/login"


def test_web_mode_starts_and_stops_vipergirls_scheduler(monkeypatch, tmp_path):
    events = []

    class FakeScheduler:
        def __init__(self, creds, event_queue=None, credentials_provider=None, api_factory=None):
            self.credentials_provider = credentials_provider
            self.api_factory = api_factory
            events.append(("init", creds, event_queue))

        def start(self):
            events.append(("start", self.credentials_provider()))

        def stop(self):
            events.append(("stop", None))

    monkeypatch.setattr(config, "APP_MODE", "web")
    monkeypatch.setattr(config, "USER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "WEB_AUTH_REQUIRED", False)
    monkeypatch.setattr(config, "WEB_DOCS_ENABLED", False)
    monkeypatch.setattr(viper_api, "ViperGirlsPostScheduler", FakeScheduler)

    app = create_app()
    credential_store = JsonCredentialStore(str(tmp_path / "credentials.json"))
    credential_store.update({"vg_user": "poster", "vg_pass": "secret"})
    app.state.credential_store = credential_store

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200

    assert events[0][0] == "init"
    assert events[1] == ("start", {"vg_user": "poster", "vg_pass": "secret"})
    assert events[2] == ("stop", None)


def test_web_auth_accepts_basic_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "WEB_AUTH_REQUIRED", True)
    monkeypatch.setattr(config, "WEB_USERNAME", "admin")
    monkeypatch.setattr(config, "WEB_PASSWORD", "secret")
    monkeypatch.setattr(config, "WEB_TOKEN", "")
    monkeypatch.setattr(config, "WEB_AUTH_FILE", str(tmp_path / "web_auth.json"))
    monkeypatch.setattr(config, "WEB_DOCS_ENABLED", False)
    client = TestClient(create_app())
    header = base64.b64encode(b"admin:secret").decode("ascii")

    denied = client.get("/", follow_redirects=False)
    denied_api = client.get("/api/settings")
    allowed = client.get("/", headers={"Authorization": f"Basic {header}"})

    assert denied.status_code == 303
    assert denied.headers["location"] == "/login"
    assert denied_api.status_code == 401
    assert allowed.status_code == 200


def test_web_auth_accepts_setup_account_basic_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "WEB_AUTH_REQUIRED", True)
    monkeypatch.setattr(config, "WEB_PASSWORD", "")
    monkeypatch.setattr(config, "WEB_TOKEN", "")
    monkeypatch.setattr(config, "WEB_AUTH_FILE", str(tmp_path / "web_auth.json"))
    monkeypatch.setattr(config, "WEB_DOCS_ENABLED", False)
    client = TestClient(create_app())
    client.post(
        "/api/auth/setup",
        json={"username": "webuser", "password": "stored-password"},
    )
    client.post("/api/auth/logout")
    header = base64.b64encode(b"webuser:stored-password").decode("ascii")

    response = client.get("/", headers={"Authorization": f"Basic {header}"})

    assert response.status_code == 200


def test_openapi_docs_are_disabled_when_configured(monkeypatch):
    monkeypatch.setattr(config, "WEB_AUTH_REQUIRED", False)
    monkeypatch.setattr(config, "WEB_DOCS_ENABLED", False)
    client = TestClient(create_app())

    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/openapi.json").status_code == 404
