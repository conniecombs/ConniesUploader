# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

import queue
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from modules import imx_api
from modules.gallery_service import GalleryService, GalleryStatus
from modules.gallery_manager import GalleryManager
from modules.plugins.imx import ImxPlugin
from modules.upload_manager import UploadManager

CHALLENGE = '<title>Making sure you&#39;re not a bot!</title><script id="anubis_challenge">{}</script>'


@pytest.fixture
def api_session(monkeypatch):
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.post.return_value.status_code = 200
    session.post.return_value.json.return_value = {
        "status": "success",
        "data": {
            "gallery_id": "abc123",
            "gallery_name": "Test Gallery",
            "image_url": "https://imx.to/i/first",
            "thumbnail_url": "https://imx.to/t/first.jpg",
        },
    }
    monkeypatch.setattr(imx_api.requests, "Session", lambda: session)
    return session


@pytest.fixture
def first_image(tmp_path):
    path = tmp_path / "first.png"
    path.write_bytes(b"fake image bytes for mocked transport")
    return str(path)


def test_api_creation_enforces_upload_policy_and_posts_once(
    api_session, first_image
):
    result = GalleryService(None, {"imx_api": "private-key", "imx_user": "user", "imx_pass": "secret"}).create_gallery(
        "imx.to", "Test Gallery", initial_image=first_image
    )
    assert result.ok and result.record.id == "abc123"
    assert result.record.raw["first_image_url"] == "https://imx.to/i/first"
    api_session.post.assert_called_once()
    request = api_session.post.call_args.kwargs
    assert request["headers"]["X-API-Key"] == "private-key"
    assert request["data"] == {
        "format": "json",
        "create_gallery": "1",
        "gallery_name": "Test Gallery",
    }
    assert request["allow_redirects"] is False
    assert request["files"]["image"][1].closed


@pytest.mark.parametrize("name", ["", "x" * 101, "Bad:name", "Beyoncé"])
def test_invalid_gallery_names_do_not_upload(api_session, first_image, name):
    with pytest.raises(imx_api.ImxApiError, match="1–100"):
        imx_api.create_gallery_with_image("key", name, first_image)
    api_session.post.assert_not_called()


@pytest.mark.parametrize(
    "payload, message",
    [
        (
            {"status": "error", "message": "Invalid or inactive API key"},
            "Invalid or inactive API key",
        ),
        ({"status": "error", "message": "private-key denied"}, r"\[redacted\] denied"),
        (
            {"status": "success", "data": {"image_url": "https://imx.to/i/one"}},
            "did not confirm",
        ),
        ({"status": "success", "data": None}, "without gallery data"),
        ([], "invalid gallery response"),
    ],
)
def test_api_failure_never_becomes_success(api_session, first_image, payload, message):
    api_session.post.return_value.json.return_value = payload
    with pytest.raises(imx_api.ImxApiError, match=message) as problem:
        imx_api.create_gallery_with_image("private-key", "Test Gallery", first_image)
    assert "private-key" not in str(problem.value)
    api_session.post.assert_called_once()


@pytest.mark.parametrize("status", [302, 403, 429, 500])
def test_http_errors_are_clear_and_not_retried(api_session, first_image, status):
    api_session.post.return_value.status_code = status
    with pytest.raises(imx_api.ImxApiError):
        imx_api.create_gallery_with_image("key", "Test Gallery", first_image)
    api_session.post.assert_called_once()


def test_timeout_warns_about_uncertain_outcome_without_retry(api_session, first_image):
    api_session.post.side_effect = requests.Timeout("secret request details")
    with pytest.raises(
        imx_api.ImxApiError, match="may already have uploaded"
    ) as problem:
        imx_api.create_gallery_with_image("key", "Test Gallery", first_image)
    assert "secret request details" not in str(problem.value)
    api_session.post.assert_called_once()


def test_html_api_response_does_not_report_missing_gallery(api_session, first_image):
    api_session.post.return_value.json.side_effect = ValueError()
    with pytest.raises(imx_api.ImxApiError, match="unreadable"):
        imx_api.create_gallery_with_image("key", "Test Gallery", first_image)


@pytest.mark.parametrize("operation", ["list", "create", "delete", "sync"])
def test_anubis_200_blocks_website_operations_before_sending_password(
    monkeypatch, operation
):
    session = Mock()
    session.get.return_value = SimpleNamespace(
        status_code=200, text=CHALLENGE, url="https://imx.to/login.php"
    )
    monkeypatch.setattr("modules.gallery_service.requests.Session", lambda: session)
    service = GalleryService(None, {"imx_user": "user", "imx_pass": "password", "imx_api": "key"})
    operations = {
        "list": lambda: service.list_galleries("imx.to"),
        "create": lambda: service.create_gallery("imx.to", "Test"),
        "delete": lambda: service.delete_gallery("imx.to", "abc123"),
        "sync": lambda: service.sync_all_galleries("imx.to"),
    }
    result = operations[operation]()
    assert result.status == GalleryStatus.BROWSER_REQUIRED
    assert "API key" in result.message
    session.post.assert_not_called()
    session.close.assert_called_once()


def test_200_login_response_must_be_authenticated(monkeypatch):
    session = Mock()
    session.get.return_value = SimpleNamespace(
        status_code=200, text="", url="https://imx.to/user/dashboard"
    )
    session.post.return_value = session.get.return_value
    monkeypatch.setattr("modules.gallery_service.requests.Session", lambda: session)
    _, problem = GalleryService(
        None, {"imx_user": "user", "imx_pass": " password "}
    )._create_imx_session()
    assert problem.status == GalleryStatus.LOGIN_FAILED
    assert session.post.call_args.kwargs["data"]["pwd"] == " password "
    assert "remember" not in session.post.call_args.kwargs["data"]


def make_manager(monkeypatch):
    manager = UploadManager.__new__(UploadManager)
    manager.cancel_event = threading.Event()
    manager.progress_queue = queue.Queue()
    manager.result_queue = queue.Queue()
    manager.plugin_manager = Mock()
    manager.plugin_manager.get_plugin.return_value = ImxPlugin()
    manager._send_job = Mock()
    manager._remember_imx_gallery_use = Mock()
    return manager


class Group:
    title = "Test Gallery"
    files = ["first.jpg", "second.jpg"]
    gallery_id = ""
    gallery_service = ""


def test_seed_is_uploaded_once_then_remaining_files_use_gallery(monkeypatch):
    upload = imx_api.ImxGalleryUpload(
        "abc123", "Test Gallery", "https://imx.to/i/first", "https://imx.to/t/first.jpg"
    )
    create = Mock(return_value=upload)
    monkeypatch.setattr("modules.plugins.imx.create_gallery_with_image", create)
    manager = make_manager(monkeypatch)
    group = Group()
    cfg = {"service": "imx.to", "auto_gallery": True, "imx_cover_count": 1}
    manager._dispatch_jobs({group: list(group.files)}, cfg, {"imx_api": "key", "imx_user": "user", "imx_pass": "secret"})
    assert create.call_args.kwargs["fields"]["thumbnail_size"] == "5"
    assert manager.result_queue.get_nowait() == (
        "first.jpg",
        upload.image_url,
        upload.thumbnail_url,
    )
    assert manager.result_queue.empty()
    assert manager._send_job.call_args.args[0] == ["second.jpg"]
    assert manager._send_job.call_args.args[1]["gallery_id"] == "abc123"
    manager._dispatch_jobs({group: ["second.jpg"]}, cfg, {"imx_api": "key", "imx_user": "user", "imx_pass": "secret"})
    create.assert_called_once()  # Retry keeps the existing gallery.


def test_gallery_failure_stops_all_files_and_preserves_reason(monkeypatch):
    monkeypatch.setattr(
        "modules.plugins.imx.create_gallery_with_image",
        Mock(side_effect=imx_api.ImxApiError("Invalid API key")),
    )
    manager = make_manager(monkeypatch)
    group = Group()
    manager._dispatch_jobs(
        {group: list(group.files)},
        {"service": "imx.to", "auto_gallery": True},
        {"imx_api": "key", "imx_user": "user", "imx_pass": "secret"},
    )
    manager._send_job.assert_not_called()
    assert manager.result_queue.qsize() == 2
    errors = [
        event
        for event in list(manager.progress_queue.queue)
        if "error:" in str(event[2])
    ]
    assert len(errors) == 2 and all("Invalid API key" in event[2] for event in errors)


def test_single_image_gallery_has_no_second_upload(monkeypatch):
    monkeypatch.setattr(
        "modules.plugins.imx.create_gallery_with_image",
        Mock(
            return_value=imx_api.ImxGalleryUpload(
                "abc123",
                "Test Gallery",
                "https://imx.to/i/first",
                "https://imx.to/t/first.jpg",
            )
        ),
    )
    manager = make_manager(monkeypatch)
    group = Group()
    manager._dispatch_jobs(
        {group: ["first.jpg"]},
        {"service": "imx.to", "auto_gallery": True},
        {"imx_api": "key", "imx_user": "user", "imx_pass": "secret"},
    )
    manager._send_job.assert_not_called()
    assert manager.result_queue.qsize() == 1
    manager._remember_imx_gallery_use.assert_called_once()


def test_gallery_manager_chooses_first_image_and_prevents_duplicate_submission(
    monkeypatch,
):
    manager = GalleryManager.__new__(GalleryManager)
    manager.creds = {"imx_api": "key", "imx_user": "user", "imx_pass": "secret"}
    manager.ent_name = Mock()
    manager.ent_name.get.return_value = "Test Gallery"
    manager.btn_create = Mock()
    manager._selected_service = lambda: "imx.to"
    manager._create_request_id = 0
    manager._set_status = Mock()
    manager.gallery_service = Mock()
    manager.after = Mock()
    choose = Mock(return_value="first.png")
    monkeypatch.setattr("modules.gallery_manager.filedialog.askopenfilename", choose)
    worker = Mock()
    thread = Mock(return_value=worker)
    monkeypatch.setattr("modules.gallery_manager.threading.Thread", thread)
    manager._create_gallery()
    manager._create_gallery()
    choose.assert_called_once()
    worker.start.assert_called_once()
    assert manager._creating_gallery
    manager.btn_create.configure.assert_called_once_with(state="disabled")
    thread.call_args.kwargs["target"]()
    manager.gallery_service.create_gallery.assert_called_once_with(
        "imx.to", "Test Gallery", initial_image="first.png"
    )


def test_gallery_manager_cancelled_image_picker_does_not_create(monkeypatch):
    manager = GalleryManager.__new__(GalleryManager)
    manager.creds = {"imx_api": "key", "imx_user": "user", "imx_pass": "secret"}
    manager.ent_name = Mock()
    manager.ent_name.get.return_value = "Test Gallery"
    manager._selected_service = lambda: "imx.to"
    manager.gallery_service = Mock()
    monkeypatch.setattr(
        "modules.gallery_manager.filedialog.askopenfilename", lambda **kwargs: ""
    )
    manager._create_gallery()
    manager.gallery_service.create_gallery.assert_not_called()
    assert not manager.__dict__.get("_creating_gallery")


def test_missing_api_key_does_not_upload(api_session, first_image):
    with pytest.raises(imx_api.ImxApiError, match="API key"):
        imx_api.create_gallery_with_image("", "Test Gallery", first_image)
    api_session.post.assert_not_called()


def test_cancel_before_gallery_creation_does_not_upload(monkeypatch):
    create = Mock()
    monkeypatch.setattr("modules.plugins.imx.create_gallery_with_image", create)
    event = threading.Event()
    event.set()
    with pytest.raises(imx_api.ImxApiError, match="cancelled"):
        ImxPlugin().prepare_group(
            Group(),
            {"auto_gallery": True},
            {
                "pending_files": ["first.jpg"],
                "cancel_event": event,
            },
            {"imx_api": "key", "imx_user": "user", "imx_pass": "secret"},
        )
    create.assert_not_called()
