from unittest.mock import patch

from modules.gallery_cache import GalleryCache
from modules.gallery_manager import GalleryManager
from modules.gallery_service import (
    GalleryRecord,
    GalleryResult,
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


class FakeWidget:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def pack(self, *args, **kwargs):
        return None

    def grid(self, *args, **kwargs):
        return None

    def winfo_exists(self):
        return True

    def winfo_children(self):
        return []


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


def test_parse_imx_gallery_html_counts_unparseable_gallery_candidates():
    html = """
    <a href="/g/bad-id">Broken Gallery ID</a>
    <a href="/not-a-gallery/ABC123">Not a gallery</a>
    """

    records, candidates = parse_imx_gallery_html(html)

    assert records == []
    assert candidates == 1


def test_list_galleries_normalizes_sidecar_gallery_response_and_sends_credentials():
    bridge = FakeBridge(
        {
            "status": "success",
            "data": [
                {
                    "gallery_id": "42",
                    "gallery_name": "Vipr Folder",
                    "gallery_url": "https://vipr.im/f/42",
                }
            ],
        }
    )
    service = GalleryService(bridge, {"vipr_user": "user", "vipr_pass": "pass"})

    result = service.list_galleries("vipr.im", page=3)

    assert result.status == GalleryStatus.SUCCESS
    assert result.page == 3
    assert result.records[0] == GalleryRecord(
        service="vipr.im",
        id="42",
        name="Vipr Folder",
        url="https://vipr.im/f/42",
        raw={
            "gallery_id": "42",
            "gallery_name": "Vipr Folder",
            "gallery_url": "https://vipr.im/f/42",
        },
    )
    payload = bridge.calls[0][0]
    assert payload["action"] == "http_request"
    pre_request = payload["generic_spec"]["pre_request"]
    assert pre_request["form_fields"]["login"] == "user"


def test_list_galleries_parses_vipr_generic_html_response():
    bridge = FakeBridge(
        {
            "status": "success",
            "data": {
                "response_body": '<body><a href="?op=my_files&fld_id=42">Vipr Folder</a></body>',
            },
        }
    )
    service = GalleryService(bridge, {"vipr_user": "user", "vipr_pass": "pass"})

    result = service.list_galleries("vipr.im")

    assert result.status == GalleryStatus.SUCCESS
    assert result.records[0].id == "42"
    assert result.records[0].name == "Vipr Folder"


def test_gallery_response_parsing_reports_unreadable_and_failed_shapes():
    service = GalleryService(
        FakeBridge("not a mapping"),
        {"vipr_user": "user", "vipr_pass": "pass"},
    )

    unreadable = service.list_galleries("vipr.im")
    assert unreadable.status == GalleryStatus.PARSE_FAILED
    assert "unreadable response" in unreadable.message

    service.bridge = FakeBridge({"status": "success", "data": {"id": "42"}})
    wrong_shape = service.list_galleries("vipr.im")
    assert wrong_shape.status == GalleryStatus.PARSE_FAILED
    assert "did not contain a gallery list" in wrong_shape.message

    service.bridge = FakeBridge({"type": "error", "msg": "auth expired"})
    failed = service.list_galleries("vipr.im")
    assert failed.status == GalleryStatus.LOGIN_FAILED
    assert failed.message == "auth expired"


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


def test_gallery_credential_validation_is_service_specific():
    bridge = FakeBridge()
    service = GalleryService(bridge, {"vipr_user": "user"})

    vipr_result = service.list_galleries("vipr.im")
    assert vipr_result.status == GalleryStatus.MISSING_CREDENTIALS
    assert "Vipr password" in vipr_result.message

    create_result = service.create_gallery("vipr.im", "Folder")
    assert create_result.status == GalleryStatus.MISSING_CREDENTIALS
    assert bridge.calls == []

    service = GalleryService(bridge, {})
    assert "IMX username" in service._missing_credentials("imx.to")
    service.set_imx_php_session("manual-session")
    assert service._missing_credentials("imx.to") == ""


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
    payload = bridge.calls[0][0]
    assert payload["action"] == "http_request"
    assert payload["generic_spec"]["form_fields"] == {"gallery_name": "Created Gallery"}


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


def test_gallery_manager_stale_refresh_result_does_not_overwrite_current_view():
    old_record = GalleryRecord(service="imx.to", id="old", name="Old")
    manager = GalleryManager.__new__(GalleryManager)
    manager.service_var = FakeVar("imx.to")
    manager.scroll = FakeWidget()
    manager.winfo_exists = lambda: True
    manager._refresh_request_id = 2
    manager.current_page = 1
    manager._records = [old_record]
    manager._clear_scroll = lambda: (_ for _ in ()).throw(AssertionError("stale result rendered"))

    GalleryManager._render_list_result(
        manager,
        1,
        "imx.to",
        GalleryResult(
            status=GalleryStatus.SUCCESS,
            message="Loaded new records.",
            service="imx.to",
            records=[GalleryRecord(service="imx.to", id="new", name="New")],
            page=5,
        ),
    )

    assert manager.current_page == 1
    assert manager._records == [old_record]


def test_gallery_cache_persists_records_pins_and_last_used(tmp_path):
    cache = GalleryCache(str(tmp_path / "gallery_cache.json"))
    record = GalleryRecord(
        service="imx.to",
        id="abc123",
        name="Original Gallery",
        url="https://imx.to/g/abc123",
        raw={"extra": "kept"},
    )

    cache.upsert_record(record)
    loaded = cache.records_for_service("imx.to")[0]

    assert loaded.name == "Original Gallery"
    assert loaded.raw["_cached"] is True
    assert loaded.raw["extra"] == "kept"

    assert cache.toggle_pinned(loaded) is True
    cache.mark_used(loaded, "2026-06-21T10:00:00+00:00")
    cache.upsert_record(
        GalleryRecord(
            service="imx.to",
            id="abc123",
            name="Renamed Gallery",
            url="https://imx.to/g/abc123",
        )
    )

    reloaded = cache.records_for_service("imx.to")[0]
    assert reloaded.name == "Renamed Gallery"
    assert reloaded.raw["pinned"] is True
    assert reloaded.raw["last_used_at"] == "2026-06-21T10:00:00+00:00"
    assert not (tmp_path / "gallery_cache.json.tmp").exists()


def test_gallery_cache_backs_up_corrupt_json(tmp_path):
    cache_path = tmp_path / "gallery_cache.json"
    cache_path.write_text("{not json", encoding="utf-8")
    cache = GalleryCache(str(cache_path))

    assert cache.load() == {"version": 1, "services": {}}
    backups = list(tmp_path.glob("gallery_cache.json.corrupt-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not json"


def test_gallery_manager_falls_back_to_cached_records_when_refresh_fails(tmp_path):
    cache = GalleryCache(str(tmp_path / "gallery_cache.json"))
    cache.upsert_record(
        GalleryRecord(
            service="vipr.im",
            id="42",
            name="Cached Folder",
            url="https://vipr.im/f/42",
        )
    )
    manager = GalleryManager.__new__(GalleryManager)
    manager.gallery_cache = cache

    fallback = GalleryManager._cached_result_for_failure(
        manager,
        "vipr.im",
        GalleryResult(
            status=GalleryStatus.ERROR,
            message="Host refresh failed.",
            service="vipr.im",
        ),
    )

    assert fallback.cached is True
    assert fallback.ok
    assert fallback.records[0].name == "Cached Folder"
    assert fallback.records[0].raw["_cached"] is True
    assert fallback.message == "Host refresh failed. Showing 1 cached gallery record(s) instead."


def test_gallery_manager_empty_live_result_does_not_fall_back_to_stale_cache(tmp_path):
    cache = GalleryCache(str(tmp_path / "gallery_cache.json"))
    cache.upsert_record(
        GalleryRecord(
            service="vipr.im",
            id="42",
            name="Stale Cached Folder",
            url="https://vipr.im/f/42",
        )
    )
    rendered = []
    manager = GalleryManager.__new__(GalleryManager)
    manager.gallery_cache = cache
    manager.service_var = FakeVar("vipr.im")
    manager.scroll = FakeWidget()
    manager.winfo_exists = lambda: True
    manager._refresh_request_id = 1
    manager._clear_scroll = lambda: None
    manager._render_result_message = lambda result: rendered.append(result)

    GalleryManager._render_list_result(
        manager,
        1,
        "vipr.im",
        GalleryResult(
            status=GalleryStatus.EMPTY,
            message="No galleries found for Vipr.im.",
            service="vipr.im",
        ),
    )

    assert manager._records == []
    assert rendered[0].status == GalleryStatus.EMPTY


def test_gallery_manager_toggle_pin_persists_and_rerenders(tmp_path):
    cache = GalleryCache(str(tmp_path / "gallery_cache.json"))
    record = GalleryRecord(
        service="pixhost.to",
        id="abc123",
        name="Reusable Gallery",
        url="https://pixhost.to/gallery/abc123",
    )
    statuses = []
    render_calls = []
    manager = GalleryManager.__new__(GalleryManager)
    manager.gallery_cache = cache
    manager._set_status = lambda message, is_error=False, is_warning=False: statuses.append(
        (message, is_error, is_warning)
    )
    manager._render_current_records = lambda: render_calls.append(True)

    GalleryManager._toggle_pin(manager, record)

    assert record.raw["pinned"] is True
    assert statuses[-1] == ("Pinned Reusable Gallery.", False, False)
    assert render_calls == [True]
    assert cache.records_for_service("pixhost.to")[0].raw["pinned"] is True


def test_gallery_manager_result_messages_show_expected_empty_and_error_actions():
    statuses = []
    actions_seen = []
    labels_seen = []
    manager = GalleryManager.__new__(GalleryManager)
    manager.scroll = FakeWidget()
    manager._clear_scroll = lambda: None
    manager._set_status = lambda message, is_error=False: statuses.append((message, is_error))
    manager._render_empty_actions = lambda actions: actions_seen.append([label for label, _ in actions])

    def fake_label(*args, **kwargs):
        labels_seen.append(kwargs.get("text", ""))
        return FakeWidget(*args, **kwargs)

    with patch("modules.gallery_manager.ctk.CTkLabel", side_effect=fake_label):
        GalleryManager._render_result_message(
            manager,
            GalleryResult(
                status=GalleryStatus.EMPTY,
                message="No galleries found for IMX.to.",
                service="imx.to",
            ),
        )

    assert statuses[-1] == ("No galleries found for IMX.to.", False)
    assert "No galleries found" in labels_seen
    assert actions_seen[-1] == ["Refresh from host", "Create Gallery"]

    labels_seen.clear()
    with patch("modules.gallery_manager.ctk.CTkLabel", side_effect=fake_label):
        GalleryManager._render_result_message(
            manager,
            GalleryResult(
                status=GalleryStatus.MISSING_CREDENTIALS,
                message="Vipr.im needs Vipr password before galleries can be listed.",
                service="vipr.im",
            ),
        )

    assert statuses[-1] == (
        "Vipr.im needs Vipr password before galleries can be listed.",
        True,
    )
    assert "Missing credentials" in labels_seen
    assert actions_seen[-1] == ["Set Credentials", "Refresh from host", "Create Gallery"]


def test_gallery_manager_create_success_caches_and_renders_created_gallery(tmp_path):
    cache = GalleryCache(str(tmp_path / "gallery_cache.json"))
    record = GalleryRecord(
        service="pixhost.to",
        id="abc123",
        name="Created Gallery",
        url="https://pixhost.to/gallery/abc123",
    )
    statuses = []
    rendered = []
    manager = GalleryManager.__new__(GalleryManager)
    manager.gallery_cache = cache
    manager.service_var = FakeVar("pixhost.to")
    manager._create_request_id = 7
    manager._set_status = lambda message, is_error=False: statuses.append((message, is_error))
    manager._render_created_gallery = lambda created: rendered.append(created)
    manager._render_result_message = lambda result: (_ for _ in ()).throw(
        AssertionError("success should render created gallery")
    )

    GalleryManager._handle_create_result(
        manager,
        7,
        "pixhost.to",
        GalleryResult(
            status=GalleryStatus.SUCCESS,
            message="Created gallery 'Created Gallery' (abc123).",
            service="pixhost.to",
            records=[record],
            record=record,
        ),
    )

    assert statuses[-1] == ("Created gallery 'Created Gallery' (abc123).", False)
    assert rendered == [record]
    assert cache.records_for_service("pixhost.to")[0].id == "abc123"


def test_gallery_manager_select_marks_last_used_and_passes_full_record(tmp_path):
    cache = GalleryCache(str(tmp_path / "gallery_cache.json"))
    record = GalleryRecord(
        service="imx.to",
        id="abc123",
        name="Selected Gallery",
        url="https://imx.to/g/abc123",
        raw={"_cached": True},
    )
    calls = []
    destroyed = []
    manager = GalleryManager.__new__(GalleryManager)
    manager.gallery_cache = cache
    manager.callback = lambda service, gallery_id, selected: calls.append(
        (service, gallery_id, selected)
    )
    manager.destroy = lambda: destroyed.append(True)

    GalleryManager._select(manager, record)

    assert calls == [("imx.to", "abc123", record)]
    assert destroyed == [True]
    assert "_cached" not in record.raw
    assert record.raw["last_used_at"]
    assert cache.records_for_service("imx.to")[0].raw["last_used_at"] == record.raw["last_used_at"]


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
            raw={"last_used": "2026-06-20T00:00:00+00:00", "pinned": True},
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
        "200",
        "100",
        "300",
    ]

    manager.sort_var = FakeVar("Last used")
    assert [record.name for record in GalleryManager._filtered_sorted_records(manager)] == [
        "Alpha",
        "Beta",
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
