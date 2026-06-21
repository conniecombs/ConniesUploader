from unittest.mock import patch

from modules.gallery_manager import GalleryManager
from modules.gallery_service import (
    GalleryRecord,
    GalleryService,
    GalleryStatus,
    normalize_gallery_record,
    parse_imx_gallery_html,
)


class FakeBridge:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    def request_sync(self, payload, timeout=0):
        self.calls.append((payload, timeout))
        return self.response


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def test_normalize_gallery_record_uses_standard_shape_and_service_url():
    record = normalize_gallery_record(
        "pixhost.to",
        {
            "gallery_hash": "abc123",
            "gallery_name": "Release Gallery",
            "gallery_upload_hash": "upload456",
            "extra": "kept",
        },
    )

    assert record.service == "pixhost.to"
    assert record.id == "abc123"
    assert record.name == "Release Gallery"
    assert record.url == "https://pixhost.to/gallery/abc123"
    assert record.upload_hash == "upload456"
    assert record.raw["extra"] == "kept"


def test_parse_imx_gallery_html_supports_plain_and_icon_wrapped_names():
    html = """
    <a href="/g/ABC123"><i>First Gallery</i></a>
    <a href="https://imx.to/g/DEF456">Second Gallery</a>
    """

    records, candidates = parse_imx_gallery_html(html)

    assert candidates == 2
    assert records == [
        {
            "id": "ABC123",
            "name": "First Gallery",
            "url": "https://imx.to/g/ABC123",
        },
        {
            "id": "DEF456",
            "name": "Second Gallery",
            "url": "https://imx.to/g/DEF456",
        },
    ]


def test_list_galleries_reports_unsupported_service_without_sidecar_call():
    bridge = FakeBridge()
    service = GalleryService(bridge, {})

    result = service.list_galleries("unknown.host")

    assert result.status == GalleryStatus.UNSUPPORTED
    assert bridge.calls == []


def test_list_galleries_reports_unsupported_operation_for_pixhost_listing():
    bridge = FakeBridge()
    service = GalleryService(bridge, {})

    result = service.list_galleries("pixhost.to")

    assert result.status == GalleryStatus.UNSUPPORTED
    assert "listing is not supported" in result.message
    assert bridge.calls == []


def test_list_galleries_distinguishes_empty_from_parse_failure():
    empty = GalleryService(
        FakeBridge({"type": "data", "status": "success", "data": []}),
        {"vipr_user": "user", "vipr_pass": "pass"},
    )
    parse_failed = GalleryService(
        FakeBridge({"type": "data", "status": "success", "data": [{"name": "No ID"}]}),
        {"vipr_user": "user", "vipr_pass": "pass"},
    )

    assert empty.list_galleries("vipr.im").status == GalleryStatus.EMPTY
    assert parse_failed.list_galleries("vipr.im").status == GalleryStatus.PARSE_FAILED


def test_list_galleries_requires_imx_credentials_without_vipr_fallback():
    bridge = FakeBridge()
    service = GalleryService(
        bridge,
        {
            "vipr_user": "wrong-service-user",
            "vipr_pass": "wrong-service-pass",
        },
    )

    result = service.list_galleries("imx.to")

    assert result.status == GalleryStatus.MISSING_CREDENTIALS
    assert "IMX username" in result.message
    assert bridge.calls == []


def test_create_gallery_normalizes_pixhost_success_response():
    bridge = FakeBridge(
        {
            "status": "success",
            "data": {
                "gallery_name": "Created Gallery",
                "gallery_hash": "abc123",
                "gallery_upload_hash": "upload456",
                "gallery_url": "https://pixhost.to/gallery/abc123",
            },
        }
    )
    service = GalleryService(bridge, {})

    result = service.create_gallery("pixhost.to", "Created Gallery")

    assert result.status == GalleryStatus.SUCCESS
    assert result.record.id == "abc123"
    assert result.record.upload_hash == "upload456"
    assert bridge.calls[0][0]["action"] == "create_gallery"
    assert bridge.calls[0][0]["config"] == {"gallery_name": "Created Gallery"}


def test_create_gallery_maps_login_failures_to_login_failed_status():
    bridge = FakeBridge({"status": "failed", "msg": "login failed"})
    service = GalleryService(bridge, {"vipr_user": "user", "vipr_pass": "pass"})

    result = service.create_gallery("vipr.im", "Private Folder")

    assert result.status == GalleryStatus.LOGIN_FAILED


def test_gallery_manager_stale_request_guards():
    manager = GalleryManager.__new__(GalleryManager)
    manager.service_var = FakeVar("imx.to")
    manager._refresh_request_id = 3
    manager._create_request_id = 5

    assert not GalleryManager._is_stale_refresh(manager, 3, "imx.to")
    assert GalleryManager._is_stale_refresh(manager, 2, "imx.to")
    assert GalleryManager._is_stale_refresh(manager, 3, "vipr.im")

    assert not GalleryManager._is_stale_create(manager, 5, "imx.to")
    assert GalleryManager._is_stale_create(manager, 4, "imx.to")
    assert GalleryManager._is_stale_create(manager, 5, "vipr.im")


def test_gallery_manager_filters_and_sorts_records():
    manager = GalleryManager.__new__(GalleryManager)
    manager._records = [
        GalleryRecord(
            service="imx.to",
            id="300",
            name="Gamma",
            url="https://imx.to/g/300",
            raw={},
        ),
        GalleryRecord(
            service="vipr.im",
            id="100",
            name="Beta",
            url="https://vipr.im/f/100",
            raw={"last_used_at": "2026-06-21T00:00:00+00:00"},
        ),
        GalleryRecord(
            service="pixhost.to",
            id="200",
            name="Alpha",
            url="https://pixhost.to/gallery/200",
            raw={"last_used": "2026-06-20T00:00:00+00:00"},
        ),
    ]
    manager.search_var = FakeVar("")
    manager.sort_var = FakeVar("Name")

    assert [record.name for record in GalleryManager._filtered_sorted_records(manager)] == [
        "Alpha",
        "Beta",
        "Gamma",
    ]

    manager.sort_var = FakeVar("ID/hash")
    assert [record.id for record in GalleryManager._filtered_sorted_records(manager)] == [
        "100",
        "200",
        "300",
    ]

    manager.sort_var = FakeVar("Last used")
    assert [record.name for record in GalleryManager._filtered_sorted_records(manager)] == [
        "Beta",
        "Alpha",
        "Gamma",
    ]

    manager.search_var = FakeVar("vipr.im/f/100")
    assert [record.name for record in GalleryManager._filtered_sorted_records(manager)] == ["Beta"]


def test_gallery_manager_copy_actions_update_clipboard_and_status():
    manager = GalleryManager.__new__(GalleryManager)
    copied = []
    statuses = []
    manager.clipboard_clear = lambda: copied.clear()
    manager.clipboard_append = lambda text: copied.append(text)
    manager._set_status = lambda message, is_error=False: statuses.append((message, is_error))

    GalleryManager._copy_text(manager, "abc123", "Gallery ID/hash")

    assert copied == ["abc123"]
    assert statuses[-1] == ("Copied Gallery ID/hash.", False)

    GalleryManager._copy_text(manager, "", "Gallery URL")

    assert statuses[-1] == ("No gallery url is available.", True)


def test_gallery_manager_open_gallery_uses_url_when_available():
    manager = GalleryManager.__new__(GalleryManager)
    statuses = []
    manager._set_status = lambda message, is_error=False: statuses.append((message, is_error))
    record = GalleryRecord(
        service="imx.to",
        id="abc123",
        name="Example Gallery",
        url="https://imx.to/g/abc123",
    )

    with patch("modules.gallery_manager.webbrowser.open") as open_url:
        GalleryManager._open_gallery(manager, record)

    open_url.assert_called_once_with("https://imx.to/g/abc123")
    assert statuses[-1] == ("Opened Example Gallery.", False)

    GalleryManager._open_gallery(
        manager,
        GalleryRecord(service="imx.to", id="missing", name="Missing URL"),
    )

    assert statuses[-1] == ("No gallery URL is available.", True)
