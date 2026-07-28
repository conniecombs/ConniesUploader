from unittest.mock import Mock, patch

from modules.gallery_cache import GalleryCache
from modules.gallery_manager import GalleryManager
from modules.gallery_service import (
    GalleryRecord,
    GalleryResult,
    GalleryService,
    GalleryStatus,
    normalize_gallery_record,
    parse_imagebam_gallery_options,
    parse_imx_gallery_html,
    parse_pixhost_gallery_import,
    parse_vipr_gallery_html,
)


class FakeBridge:
    def __init__(self, response=None, responses=None):
        self.response = response
        self.responses = list(responses or [])
        self.calls = []

    def request_sync(self, payload, timeout=0):
        self.calls.append((payload, timeout))
        if self.responses:
            return self.responses.pop(0)
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


class FakeResponse:
    def __init__(self, text="", status_code=200, url="https://imx.to/"):
        self.text = text
        self.status_code = status_code
        self.url = url


class FakeImxSession:
    def __init__(self):
        self.headers = {}
        self.cookies = Mock()
        self.get_calls = []
        self.post_calls = []

    def get(self, url, timeout=0):
        self.get_calls.append((url, timeout))
        return FakeResponse("", url=url)

    def post(self, url, data=None, timeout=0):
        self.post_calls.append((url, dict(data or {}), timeout))
        if url.endswith("/login.php"):
            return FakeResponse("Welcome johngrimm", url="https://imx.to/user/dashboard")
        return FakeResponse("", url="https://imx.to/user/gallery/edit?id=abc123")


class FakePagedImxSession(FakeImxSession):
    def __init__(self, pages):
        super().__init__()
        self.pages = pages

    def get(self, url, timeout=0):
        self.get_calls.append((url, timeout))
        if url == "https://imx.to/login.php":
            return FakeResponse("", url=url)
        page = "1"
        if "page=" in url:
            page = url.split("page=", 1)[1].split("&", 1)[0]
        return FakeResponse(self.pages.get(page, ""), url=url)


def test_normalize_gallery_record_uses_standard_shape_and_service_url():
    record = normalize_gallery_record(
        "pixhost.cc",
        {
            "gallery_hash": "abc123",
            "gallery_name": "Release Gallery",
            "gallery_upload_hash": "upload456",
            "extra": "kept",
        },
    )

    assert record.service == "pixhost.cc"
    assert record.id == "abc123"
    assert record.name == "Release Gallery"
    assert record.url == "https://pixhost.cc/gallery/abc123"
    assert record.upload_hash == "upload456"
    assert record.raw["extra"] == "kept"


def test_normalize_gallery_record_rewrites_legacy_pixhost_service_and_url():
    record = normalize_gallery_record(
        "pixhost.to",
        {
            "gallery_hash": "abc123",
            "gallery_name": "Legacy Gallery",
            "gallery_url": "https://pixhost.to/gallery/abc123",
        },
    )

    assert record.service == "pixhost.cc"
    assert record.url == "https://pixhost.cc/gallery/abc123"


def test_parse_pixhost_gallery_import_accepts_url_or_hash():
    from_url = parse_pixhost_gallery_import(
        "https://pixhost.cc/gallery/AbC123?utm=ignored",
        "Imported Gallery",
    )
    from_hash = parse_pixhost_gallery_import("xyz789")

    assert from_url == GalleryRecord(
        service="pixhost.cc",
        id="AbC123",
        name="Imported Gallery",
        url="https://pixhost.cc/gallery/AbC123",
        raw={
            "gallery_hash": "AbC123",
            "gallery_name": "Imported Gallery",
            "gallery_url": "https://pixhost.cc/gallery/AbC123",
            "source": "imported",
        },
    )
    assert from_hash.id == "xyz789"
    assert from_hash.name == "xyz789"
    assert from_hash.url == "https://pixhost.cc/gallery/xyz789"
    assert (
        parse_pixhost_gallery_import("https://pixhost.to/gallery/Legacy1").url
        == "https://pixhost.cc/gallery/Legacy1"
    )
    assert parse_pixhost_gallery_import("https://pixhost.cc/not-a-gallery/abc") is None


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


def test_parse_imx_gallery_html_supports_account_gallery_table():
    html = """
    <table>
      <tr>
        <td><a href="/g/sz0s">untitled gallery</a></td>
        <td>sz0s</td>
        <td><a href="/user/gallery/manage?id=sz0s">manage</a></td>
        <td><a href="/user/gallery/edit?id=sz0s">edit</a></td>
      </tr>
    </table>
    """

    records, candidates = parse_imx_gallery_html(html)

    assert candidates == 1
    assert records == [
        {
            "id": "sz0s",
            "name": "untitled gallery",
            "url": "https://imx.to/g/sz0s",
        }
    ]


def test_parse_imx_gallery_html_counts_unparseable_gallery_candidates():
    html = """
    <a href="/g/bad-id">Broken Gallery ID</a>
    <a href="/not-a-gallery/ABC123">Not a gallery</a>
    """

    records, candidates = parse_imx_gallery_html(html)

    assert records == []
    assert candidates == 1


def test_parse_vipr_gallery_html_pairs_folder_ids_with_public_urls():
    html = """
    <body>
      <a href="?op=my_files;fld_id=104485">0000010101</a>
      <a href="https://vipr.im/p/johngrimm/104485/0000010101" class="pub"></a>
      <a href="?op=fld_edit;fld_id=104485" class="edit"></a>
      <a href="?op=my_files&fld_id=0&del_folder=104485" class="delete"></a>
      <a href="?op=my_files;fld_id=37973">00Unsorted</a>
      <a href="https://vipr.im/p/johngrimm/37973/00Unsorted" class="pub"></a>
    </body>
    """

    records = parse_vipr_gallery_html(html)

    assert records == [
        {
            "id": "104485",
            "name": "0000010101",
            "url": "https://vipr.im/p/johngrimm/104485/0000010101",
            "username": "johngrimm",
        },
        {
            "id": "37973",
            "name": "00Unsorted",
            "url": "https://vipr.im/p/johngrimm/37973/00Unsorted",
            "username": "johngrimm",
        },
    ]


def test_parse_imagebam_gallery_options_uses_numeric_upload_tokens():
    html = """
    <select data-uploader-gallery-option-value-select name="gallery">
      <option value="default">Select Gallery or Create New</option>
      <option value="-1">Create New Gallery</option>
      <option value="787200">Existing Gallery</option>
      <option value="787201">Second Gallery</option>
    </select>
    """

    records = parse_imagebam_gallery_options(html)

    assert records == [
        {"id": "787200", "name": "Existing Gallery"},
        {"id": "787201", "name": "Second Gallery"},
    ]


def test_list_galleries_normalizes_sidecar_gallery_response_and_sends_credentials():
    bridge = FakeBridge(
        responses=[
            {"status": "success", "data": {"response_body": "logged in"}},
            {
                "status": "success",
                "data": {
                    "response_body": """
                    <body>
                      <a href="?op=my_files;fld_id=42">Vipr Folder</a>
                      <a href="https://vipr.im/p/user/42/Vipr%20Folder" class="pub"></a>
                    </body>
                    """,
                },
            },
        ]
    )
    service = GalleryService(bridge, {"vipr_user": "user", "vipr_pass": "pass"})

    result = service.list_galleries("vipr.im", page=3)

    assert result.status == GalleryStatus.SUCCESS
    assert result.page == 3
    assert result.records[0] == GalleryRecord(
        service="vipr.im",
        id="42",
        name="Vipr Folder",
        url="https://vipr.im/p/user/42/Vipr%20Folder",
        raw={
            "id": "42",
            "name": "Vipr Folder",
            "url": "https://vipr.im/p/user/42/Vipr%20Folder",
            "username": "user",
        },
    )
    payload = bridge.calls[0][0]
    assert payload["action"] == "http_request"
    assert payload["generic_spec"]["form_fields"]["op"] == "login"
    assert payload["generic_spec"]["form_fields"]["login"] == "user"
    list_payload = bridge.calls[1][0]
    assert list_payload["generic_spec"]["url"] == "https://vipr.im/?op=my_files"
    assert "pre_request" not in list_payload["generic_spec"]


def test_list_galleries_parses_vipr_generic_html_response():
    bridge = FakeBridge(
        responses=[
            {"status": "success", "data": {"response_body": "logged in"}},
            {
                "status": "success",
                "data": {
                    "response_body": """
                    <body>
                      <a href="?op=my_files;fld_id=42">Vipr Folder</a>
                      <a href="https://vipr.im/p/user/42/Vipr%20Folder" class="pub"></a>
                    </body>
                    """,
                },
            },
        ]
    )
    service = GalleryService(bridge, {"vipr_user": "user", "vipr_pass": "pass"})

    result = service.list_galleries("vipr.im")

    assert result.status == GalleryStatus.SUCCESS
    assert result.records[0].id == "42"
    assert result.records[0].name == "Vipr Folder"
    assert result.records[0].url == "https://vipr.im/p/user/42/Vipr%20Folder"


def test_list_galleries_parses_imagebam_upload_gallery_dropdown():
    bridge = FakeBridge(
        responses=[
            {
                "status": "success",
                "data": {
                    "response_body": '<input type="hidden" name="_token" value="tok">'
                },
            },
            {
                "status": "success",
                "data": {
                    "response_body": '<form action="https://www.imagebam.com/auth/logout"></form>'
                },
            },
            {
                "status": "success",
                "data": {
                    "response_body": """
                    <body>
                      <select data-uploader-gallery-option-value-select name="gallery">
                        <option value="default">Select Gallery or Create New</option>
                        <option value="490670">DL Katia 01</option>
                      </select>
                    </body>
                    """,
                },
            },
        ]
    )
    service = GalleryService(
        bridge, {"imagebam_user": "user", "imagebam_pass": "pass"}
    )

    result = service.list_galleries("imagebam.com")

    assert result.status == GalleryStatus.SUCCESS
    assert result.records[0] == GalleryRecord(
        service="imagebam.com",
        id="490670",
        name="DL Katia 01",
        raw={"id": "490670", "name": "DL Katia 01"},
    )
    login_payload = bridge.calls[1][0]
    assert login_payload["service"] == "imagebam.com"
    assert (
        login_payload["generic_spec"]["headers"]["Referer"]
        == "https://www.imagebam.com/auth/login"
    )
    assert login_payload["generic_spec"]["form_fields"]["email"] == "user"
    assert "pre_request" not in login_payload["generic_spec"]


def test_list_imagebam_galleries_rejects_login_page_after_post():
    bridge = FakeBridge(
        responses=[
            {
                "status": "success",
                "data": {
                    "response_body": '<input type="hidden" name="_token" value="tok">'
                },
            },
            {
                "status": "success",
                "data": {
                    "response_body": """
                    <html>
                      <body>
                        <form action="https://www.imagebam.com/auth/login">
                          <input name="email">
                        </form>
                      </body>
                    </html>
                    """
                },
            },
        ]
    )
    service = GalleryService(
        bridge, {"imagebam_user": "user", "imagebam_pass": "wrong"}
    )

    result = service.list_galleries("imagebam.com")

    assert result.status == GalleryStatus.LOGIN_FAILED
    assert "login failed" in result.message.lower()
    assert len(bridge.calls) == 2


def test_gallery_response_parsing_reports_unreadable_and_failed_shapes():
    service = GalleryService(
        FakeBridge("not a mapping"),
        {"vipr_user": "user", "vipr_pass": "pass"},
    )

    unreadable = service.list_galleries("vipr.im")
    assert unreadable.status == GalleryStatus.LOGIN_FAILED
    assert "login failed" in unreadable.message.lower()

    service.bridge = FakeBridge({"status": "success", "data": {"id": "42"}})
    wrong_shape = service.list_galleries("vipr.im")
    assert wrong_shape.status == GalleryStatus.EMPTY

    service.bridge = FakeBridge({"type": "error", "msg": "auth expired"})
    failed = service.list_galleries("vipr.im")
    assert failed.status == GalleryStatus.LOGIN_FAILED
    assert "login failed" in failed.message.lower()


def test_list_galleries_reports_unsupported_service_without_sidecar_call():
    bridge = FakeBridge()
    service = GalleryService(bridge, {})

    result = service.list_galleries("unknown.host")

    assert result.status == GalleryStatus.UNSUPPORTED
    assert bridge.calls == []


def test_list_galleries_reports_unsupported_operation_for_pixhost_listing():
    bridge = FakeBridge()
    service = GalleryService(bridge, {})

    result = service.list_galleries("pixhost.cc")

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
    assert parse_failed.list_galleries("vipr.im").status == GalleryStatus.EMPTY


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

    service = GalleryService(bridge, {"imagebam_user": "user"})
    result = service.list_galleries("imagebam.com")
    assert result.status == GalleryStatus.MISSING_CREDENTIALS
    assert "ImageBam password" in result.message


def test_create_gallery_normalizes_pixhost_success_response():
    bridge = FakeBridge(
        {
            "status": "success",
            "data": {
                "gallery_name": "Created Gallery",
                "gallery_hash": "abc123",
                "gallery_upload_hash": "upload456",
                "gallery_url": "https://pixhost.cc/gallery/abc123",
            },
        }
    )
    service = GalleryService(bridge, {})

    result = service.create_gallery("pixhost.cc", "Created Gallery")

    assert result.status == GalleryStatus.SUCCESS
    assert result.record.id == "abc123"
    assert result.record.upload_hash == "upload456"
    payload = bridge.calls[0][0]
    assert payload["action"] == "http_request"
    assert payload["generic_spec"]["form_fields"] == {"gallery_name": "Created Gallery"}


def test_create_imx_gallery_uses_live_login_and_add_gallery_forms(monkeypatch):
    fake_session = FakeImxSession()
    monkeypatch.setattr(
        "modules.gallery_service.requests.Session", lambda: fake_session
    )
    service = GalleryService(
        FakeBridge(), {"imx_user": "user", "imx_pass": "secret"}
    )

    result = service.create_gallery("imx.to", "Batch Gallery")

    assert result.status == GalleryStatus.SUCCESS
    assert result.record == GalleryRecord(
        service="imx.to",
        id="abc123",
        name="Batch Gallery",
        url="https://imx.to/g/abc123",
        raw={"id": "abc123", "name": "Batch Gallery"},
    )
    assert fake_session.get_calls[0][0] == "https://imx.to/login.php"
    assert fake_session.post_calls[0] == (
        "https://imx.to/login.php",
        {
            "usr_email": "user",
            "pwd": "secret",
            "doLogin": "Login",
            "remember": "1",
        },
        10,
    )
    assert fake_session.post_calls[1] == (
        "https://imx.to/user/gallery/add",
        {"gallery_name": "Batch Gallery", "submit_new_gallery": "Add"},
        15,
    )


def test_sync_all_imx_galleries_uses_one_login_and_stops_at_empty_page(monkeypatch):
    fake_session = FakePagedImxSession(
        {
            "1": "\n".join(
                f'<a href="/g/page1{index:03d}">Page One {index:03d}</a>'
                for index in range(100)
            ),
            "2": """
            <a href="/g/page2a">Page Two A</a>
            """,
            "3": "",
        }
    )
    progress = []
    monkeypatch.setattr(
        "modules.gallery_service.requests.Session", lambda: fake_session
    )
    service = GalleryService(
        FakeBridge(), {"imx_user": "user", "imx_pass": "secret"}
    )

    result = service.sync_all_galleries(
        "imx.to", progress_callback=lambda page, total: progress.append((page, total))
    )

    assert result.status == GalleryStatus.SUCCESS
    assert result.page == 2
    assert len(result.records) == 101
    assert result.records[0].id == "page1000"
    assert result.records[-1].id == "page2a"
    assert progress == [(1, 100), (2, 101)]
    assert fake_session.post_calls == [
        (
            "https://imx.to/login.php",
            {
                "usr_email": "user",
                "pwd": "secret",
                "doLogin": "Login",
                "remember": "1",
            },
            10,
        )
    ]
    assert [call[0] for call in fake_session.get_calls] == [
        "https://imx.to/login.php",
        "https://imx.to/user/galleries?page=1&limit=200",
        "https://imx.to/user/galleries?page=2&limit=200",
    ]


def test_delete_imx_gallery_posts_edit_form_and_confirms_gallery_removed(monkeypatch):
    fake_session = FakeImxSession()
    monkeypatch.setattr(
        "modules.gallery_service.requests.Session", lambda: fake_session
    )
    service = GalleryService(
        FakeBridge(), {"imx_user": "user", "imx_pass": "secret"}
    )
    record = GalleryRecord(service="imx.to", id="abc123", name="Delete Me")

    result = service.delete_gallery("imx.to", record)

    assert result.status == GalleryStatus.SUCCESS
    assert result.record.id == "abc123"
    assert result.message == "Deleted gallery 'Delete Me' (abc123)."
    assert fake_session.get_calls[0][0] == "https://imx.to/login.php"
    assert fake_session.post_calls[0] == (
        "https://imx.to/login.php",
        {
            "usr_email": "user",
            "pwd": "secret",
            "doLogin": "Login",
            "remember": "1",
        },
        10,
    )
    assert fake_session.post_calls[1] == (
        "https://imx.to/user/gallery/edit?id=abc123",
        {"delete_confirm": "on", "delete_gallery": "Remove Gallery"},
        15,
    )
    assert fake_session.get_calls[1] == (
        "https://imx.to/user/galleries?page=1&limit=200",
        10,
    )


def test_delete_imx_gallery_reports_error_when_gallery_still_listed(monkeypatch):
    class FakeStillListedSession(FakeImxSession):
        def get(self, url, timeout=0):
            self.get_calls.append((url, timeout))
            if url == "https://imx.to/user/galleries?page=1&limit=200":
                return FakeResponse(
                    '<a href="/g/abc123">Delete Me</a>',
                    url=url,
                )
            return FakeResponse("", url=url)

    fake_session = FakeStillListedSession()
    monkeypatch.setattr(
        "modules.gallery_service.requests.Session", lambda: fake_session
    )
    service = GalleryService(
        FakeBridge(), {"imx_user": "user", "imx_pass": "secret"}
    )

    result = service.delete_gallery("imx.to", "abc123")

    assert result.status == GalleryStatus.ERROR
    assert "still lists gallery" in result.message


def test_create_gallery_maps_login_failures_to_login_failed_status():
    bridge = FakeBridge({"status": "failed", "msg": "login failed"})
    service = GalleryService(bridge, {"vipr_user": "user", "vipr_pass": "pass"})

    result = service.create_gallery("vipr.im", "Private Folder")

    assert result.status == GalleryStatus.LOGIN_FAILED


def test_create_vipr_gallery_posts_file_manager_form_and_parses_created_folder():
    bridge = FakeBridge(
        {
            "status": "success",
            "data": {
                "response_body": """
                <body>
                  <a href="?op=my_files;fld_id=104999">New Folder</a>
                  <a href="https://vipr.im/p/johngrimm/104999/New%20Folder" class="pub"></a>
                </body>
                """,
            },
        }
    )
    service = GalleryService(bridge, {"vipr_user": "user", "vipr_pass": "pass"})

    result = service.create_gallery("vipr.im", "New Folder")

    assert result.status == GalleryStatus.SUCCESS
    assert result.record == GalleryRecord(
        service="vipr.im",
        id="104999",
        name="New Folder",
        url="https://vipr.im/p/johngrimm/104999/New%20Folder",
        raw={
            "id": "104999",
            "name": "New Folder",
            "url": "https://vipr.im/p/johngrimm/104999/New%20Folder",
            "username": "johngrimm",
        },
    )
    login_payload = bridge.calls[0][0]
    assert login_payload["generic_spec"]["form_fields"]["op"] == "login"
    assert login_payload["generic_spec"]["form_fields"]["login"] == "user"
    payload = bridge.calls[1][0]
    spec = payload["generic_spec"]
    assert spec["url"] == "https://vipr.im/"
    assert spec["method"] == "POST"
    assert spec["form_fields"]["op"] == "my_files"
    assert spec["form_fields"]["create_new_folder"] == "New Folder"
    assert "pre_request" not in spec
    assert "extract_fields" not in spec


def test_delete_vipr_gallery_calls_delete_endpoint_and_confirms_folder_removed():
    bridge = FakeBridge(
        {
            "status": "success",
            "data": {
                "response_body": """
                <body>
                  <a href="?op=my_files;fld_id=104998">Other Folder</a>
                  <a href="https://vipr.im/p/johngrimm/104998/Other%20Folder" class="pub"></a>
                </body>
                """,
            },
        }
    )
    service = GalleryService(bridge, {"vipr_user": "user", "vipr_pass": "pass"})
    record = GalleryRecord(service="vipr.im", id="104999", name="Delete Me")

    result = service.delete_gallery("vipr.im", record)

    assert result.status == GalleryStatus.SUCCESS
    assert result.record.id == "104999"
    assert result.message == "Deleted gallery 'Delete Me' (104999)."
    login_payload = bridge.calls[0][0]
    assert login_payload["generic_spec"]["form_fields"]["op"] == "login"
    assert login_payload["generic_spec"]["form_fields"]["login"] == "user"
    payload = bridge.calls[1][0]
    spec = payload["generic_spec"]
    assert payload["service"] == "vipr.im"
    assert spec["method"] == "GET"
    assert spec["url"] == "https://vipr.im/?op=my_files&fld_id=0&del_folder=104999"
    assert "pre_request" not in spec
    assert "extract_fields" not in spec


def test_delete_vipr_gallery_reports_error_when_folder_still_listed():
    bridge = FakeBridge(
        {
            "status": "success",
            "data": {
                "response_body": """
                <body>
                  <a href="?op=my_files;fld_id=104999">Delete Me</a>
                  <a href="https://vipr.im/p/johngrimm/104999/Delete%20Me" class="pub"></a>
                </body>
                """,
            },
        }
    )
    service = GalleryService(bridge, {"vipr_user": "user", "vipr_pass": "pass"})

    result = service.delete_gallery("vipr.im", "104999")

    assert result.status == GalleryStatus.ERROR
    assert "still lists gallery" in result.message


def test_delete_gallery_rejects_unsupported_service_without_sidecar_call():
    bridge = FakeBridge()
    service = GalleryService(bridge, {})

    result = service.delete_gallery("pixhost.cc", "abc123")

    assert result.status == GalleryStatus.UNSUPPORTED
    assert bridge.calls == []


def test_gallery_manager_stale_request_guards():
    manager = GalleryManager.__new__(GalleryManager)
    manager.service_var = FakeVar("imx.to")
    manager._refresh_request_id = 3
    manager._create_request_id = 5
    manager._delete_request_id = 7

    assert not GalleryManager._is_stale_refresh(manager, 3, "imx.to")
    assert GalleryManager._is_stale_refresh(manager, 2, "imx.to")
    assert GalleryManager._is_stale_refresh(manager, 3, "vipr.im")

    assert not GalleryManager._is_stale_create(manager, 5, "imx.to")
    assert GalleryManager._is_stale_create(manager, 4, "imx.to")
    assert GalleryManager._is_stale_create(manager, 5, "vipr.im")

    assert not GalleryManager._is_stale_delete(manager, 7, "imx.to")
    assert GalleryManager._is_stale_delete(manager, 6, "imx.to")
    assert GalleryManager._is_stale_delete(manager, 7, "vipr.im")


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


def test_gallery_cache_remove_record_deletes_only_requested_gallery(tmp_path):
    cache = GalleryCache(str(tmp_path / "gallery_cache.json"))
    keep = GalleryRecord(service="vipr.im", id="42", name="Keep")
    remove = GalleryRecord(service="vipr.im", id="43", name="Remove")
    cache.upsert_records("vipr.im", [keep, remove])

    assert cache.remove_record("vipr.im", "43") is True
    assert cache.remove_record("vipr.im", "missing") is False

    remaining = cache.records_for_service("vipr.im")
    assert [record.id for record in remaining] == ["42"]


def test_gallery_cache_keeps_large_imx_sync_until_user_deletes(tmp_path):
    cache = GalleryCache(str(tmp_path / "gallery_cache.json"))
    records = [
        GalleryRecord(
            service="imx.to",
            id=f"id{index:04d}",
            name=f"Gallery {index:04d}",
            url=f"https://imx.to/g/id{index:04d}",
        )
        for index in range(650)
    ]

    cache.upsert_records("imx.to", records)

    loaded = cache.records_for_service("imx.to")
    assert len(loaded) == 650
    assert {record.id for record in loaded} == {record.id for record in records}


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


def test_gallery_manager_imx_page_load_appends_to_cached_index(tmp_path):
    cache = GalleryCache(str(tmp_path / "gallery_cache.json"))
    cache.upsert_record(
        GalleryRecord(
            service="imx.to",
            id="page1",
            name="Page One",
            url="https://imx.to/g/page1",
        )
    )
    statuses = []
    render_calls = []
    manager = GalleryManager.__new__(GalleryManager)
    manager.gallery_cache = cache
    manager.service_var = FakeVar("imx.to")
    manager.scroll = FakeWidget()
    manager.winfo_exists = lambda: True
    manager._refresh_request_id = 2
    manager.current_page = 1
    manager._records = []
    manager._imx_all_synced = False
    manager._clear_scroll = lambda: None
    manager._set_status = lambda message, is_error=False, is_warning=False: statuses.append(
        (message, is_error, is_warning)
    )
    manager._render_current_records = lambda: render_calls.append(list(manager._records))

    GalleryManager._render_list_result(
        manager,
        2,
        "imx.to",
        GalleryResult(
            status=GalleryStatus.SUCCESS,
            message="Loaded 1 gallery record(s).",
            service="imx.to",
            records=[
                GalleryRecord(
                    service="imx.to",
                    id="page2",
                    name="Page Two",
                    url="https://imx.to/g/page2",
                )
            ],
            page=2,
        ),
    )

    assert manager.current_page == 2
    assert {record.id for record in manager._records} == {"page1", "page2"}
    assert {record.id for record in cache.records_for_service("imx.to")} == {
        "page1",
        "page2",
    }
    assert statuses[-1] == (
        "Loaded IMX.to page 2; showing 2 cached gallery record(s).",
        False,
        False,
    )
    assert render_calls and {record.id for record in render_calls[-1]} == {"page1", "page2"}


def test_gallery_manager_sync_all_result_caches_and_displays_full_index(tmp_path):
    cache = GalleryCache(str(tmp_path / "gallery_cache.json"))
    cache.upsert_record(
        GalleryRecord(
            service="imx.to",
            id="old",
            name="Old Cached",
            url="https://imx.to/g/old",
        )
    )
    statuses = []
    render_calls = []
    manager = GalleryManager.__new__(GalleryManager)
    manager.gallery_cache = cache
    manager.service_var = FakeVar("imx.to")
    manager.scroll = FakeWidget()
    manager.winfo_exists = lambda: True
    manager._sync_request_id = 5
    manager.current_page = 1
    manager._records = []
    manager._clear_scroll = lambda: None
    manager._set_status = lambda message, is_error=False, is_warning=False: statuses.append(
        (message, is_error, is_warning)
    )
    manager._render_current_records = lambda: render_calls.append(list(manager._records))

    GalleryManager._handle_sync_all_result(
        manager,
        5,
        "imx.to",
        GalleryResult(
            status=GalleryStatus.SUCCESS,
            message="Synced 2 IMX.to gallery record(s).",
            service="imx.to",
            records=[
                GalleryRecord(service="imx.to", id="new1", name="New One"),
                GalleryRecord(service="imx.to", id="new2", name="New Two"),
            ],
            page=3,
        ),
    )

    assert manager.current_page == 3
    assert manager._imx_all_synced is True
    assert {record.id for record in manager._records} == {"old", "new1", "new2"}
    assert {record.id for record in cache.records_for_service("imx.to")} == {
        "old",
        "new1",
        "new2",
    }
    assert statuses[-1] == (
        "Sync complete: fetched 2 IMX.to gallery record(s); showing 3 cached gallery record(s).",
        False,
        False,
    )
    assert render_calls and {record.id for record in render_calls[-1]} == {
        "old",
        "new1",
        "new2",
    }


def test_gallery_manager_pixhost_refresh_uses_saved_records_only(tmp_path):
    cache = GalleryCache(str(tmp_path / "gallery_cache.json"))
    cache.upsert_record(
        GalleryRecord(
            service="pixhost.cc",
            id="abc123",
            name="Saved Pixhost",
            url="https://pixhost.cc/gallery/abc123",
        )
    )
    statuses = []
    render_calls = []
    manager = GalleryManager.__new__(GalleryManager)
    manager.gallery_cache = cache
    manager.service_var = FakeVar("pixhost.cc")
    manager.scroll = FakeWidget()
    manager.winfo_exists = lambda: True
    manager._refresh_request_id = 4
    manager.current_page = 1
    manager._records = []
    manager._clear_scroll = lambda: None
    manager._set_status = lambda message, is_error=False, is_warning=False: statuses.append(
        (message, is_error, is_warning)
    )
    manager._render_current_records = lambda: render_calls.append(list(manager._records))

    GalleryManager._render_pixhost_local_result(manager, 4)

    assert manager._records[0].id == "abc123"
    assert statuses[-1] == (
        "Showing 1 saved Pixhost gallery record(s). Pixhost has no remote account gallery listing.",
        False,
        True,
    )
    assert render_calls and render_calls[-1][0].name == "Saved Pixhost"


def test_gallery_manager_toggle_pin_persists_and_rerenders(tmp_path):
    cache = GalleryCache(str(tmp_path / "gallery_cache.json"))
    record = GalleryRecord(
        service="pixhost.cc",
        id="abc123",
        name="Reusable Gallery",
        url="https://pixhost.cc/gallery/abc123",
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
    assert cache.records_for_service("pixhost.cc")[0].raw["pinned"] is True


def test_gallery_cache_merges_legacy_pixhost_service_bucket(tmp_path):
    cache_path = tmp_path / "gallery_cache.json"
    cache_path.write_text(
        """
{
  "version": 1,
  "services": {
    "pixhost.to": {
      "abc123": {
        "id": "abc123",
        "name": "Legacy Gallery",
        "url": "https://pixhost.to/gallery/abc123",
        "raw": {},
        "pinned": true
      }
    }
  }
}
""".strip(),
        encoding="utf-8",
    )
    cache = GalleryCache(str(cache_path))

    records = cache.records_for_service("pixhost.cc")

    assert len(records) == 1
    assert records[0].service == "pixhost.cc"
    assert records[0].url == "https://pixhost.cc/gallery/abc123"
    assert records[0].raw["pinned"] is True
    assert cache.records_for_service("pixhost.to")[0].id == "abc123"


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
    assert actions_seen[-1] == ["Refresh from host", "Sync All", "Create Gallery"]

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

    labels_seen.clear()
    with patch("modules.gallery_manager.ctk.CTkLabel", side_effect=fake_label):
        GalleryManager._render_result_message(
            manager,
            GalleryResult(
                status=GalleryStatus.EMPTY,
                message="No saved Pixhost galleries.",
                service="pixhost.cc",
            ),
        )

    assert statuses[-1] == ("No saved Pixhost galleries.", False)
    assert "No galleries found" in labels_seen
    assert actions_seen[-1] == ["Show saved", "Import Gallery", "Create Gallery"]


def test_gallery_manager_create_success_caches_and_renders_created_gallery(tmp_path):
    cache = GalleryCache(str(tmp_path / "gallery_cache.json"))
    record = GalleryRecord(
        service="pixhost.cc",
        id="abc123",
        name="Created Gallery",
        url="https://pixhost.cc/gallery/abc123",
    )
    statuses = []
    rendered = []
    manager = GalleryManager.__new__(GalleryManager)
    manager.gallery_cache = cache
    manager.service_var = FakeVar("pixhost.cc")
    manager._create_request_id = 7
    manager._set_status = lambda message, is_error=False: statuses.append((message, is_error))
    manager._render_created_gallery = lambda created: rendered.append(created)
    manager._render_result_message = lambda result: (_ for _ in ()).throw(
        AssertionError("success should render created gallery")
    )

    GalleryManager._handle_create_result(
        manager,
        7,
        "pixhost.cc",
        GalleryResult(
            status=GalleryStatus.SUCCESS,
            message="Created gallery 'Created Gallery' (abc123).",
            service="pixhost.cc",
            records=[record],
            record=record,
        ),
    )

    assert statuses[-1] == ("Created gallery 'Created Gallery' (abc123).", False)
    assert rendered == [record]
    assert cache.records_for_service("pixhost.cc")[0].id == "abc123"


def test_gallery_manager_import_pixhost_gallery_caches_record(tmp_path):
    cache = GalleryCache(str(tmp_path / "gallery_cache.json"))
    statuses = []
    rendered = []
    manager = GalleryManager.__new__(GalleryManager)
    manager.gallery_cache = cache
    manager.ent_pixhost_import = FakeVar("https://pixhost.cc/gallery/AbC123")
    manager.ent_name = FakeVar("Imported Pixhost")
    manager._set_status = lambda message, is_error=False: statuses.append((message, is_error))
    manager._render_created_gallery = lambda record: rendered.append(record)

    GalleryManager._import_pixhost_gallery(manager)

    assert statuses[-1] == ("Imported Pixhost gallery 'Imported Pixhost' (AbC123).", False)
    assert rendered[0].id == "AbC123"
    saved = cache.records_for_service("pixhost.cc")[0]
    assert saved.id == "AbC123"
    assert saved.name == "Imported Pixhost"
    assert saved.url == "https://pixhost.cc/gallery/AbC123"


def test_gallery_manager_import_pixhost_gallery_rejects_invalid_input(tmp_path):
    manager = GalleryManager.__new__(GalleryManager)
    manager.gallery_cache = GalleryCache(str(tmp_path / "gallery_cache.json"))
    manager.ent_pixhost_import = FakeVar("https://pixhost.cc/not-a-gallery/AbC123")
    manager.ent_name = FakeVar("")
    statuses = []
    manager._set_status = lambda message, is_error=False: statuses.append((message, is_error))
    manager._render_created_gallery = lambda record: (_ for _ in ()).throw(
        AssertionError("invalid import should not render")
    )

    GalleryManager._import_pixhost_gallery(manager)

    assert statuses[-1] == ("Enter a valid Pixhost gallery URL or hash.", True)
    assert manager.gallery_cache.records_for_service("pixhost.cc") == []


def test_gallery_manager_remove_saved_pixhost_gallery_deletes_local_cache_only(tmp_path):
    cache = GalleryCache(str(tmp_path / "gallery_cache.json"))
    remove = GalleryRecord(service="pixhost.cc", id="43", name="Remove")
    keep = GalleryRecord(service="pixhost.cc", id="42", name="Keep")
    cache.upsert_records("pixhost.cc", [keep, remove])
    statuses = []
    render_calls = []
    manager = GalleryManager.__new__(GalleryManager)
    manager.gallery_cache = cache
    manager.service_var = FakeVar("pixhost.cc")
    manager._refresh_request_id = 3
    manager._records = [keep, remove]
    manager._set_status = lambda message, is_error=False, is_warning=False: statuses.append(
        (message, is_error, is_warning)
    )
    manager._render_current_records = lambda: render_calls.append(list(manager._records))
    manager._render_pixhost_local_result = lambda request_id: render_calls.append(("empty", request_id))

    with patch("modules.gallery_manager.messagebox.askyesno", return_value=True) as confirm:
        GalleryManager._remove_saved_gallery(manager, remove)

    confirm.assert_called_once()
    assert statuses[-1] == ("Removed saved gallery 'Remove' (43).", False, False)
    assert [record.id for record in manager._records] == ["42"]
    assert [record.id for record in cache.records_for_service("pixhost.cc")] == ["42"]
    assert render_calls and render_calls[-1][0].id == "42"


def test_gallery_manager_delete_success_removes_record_from_cache_and_view(tmp_path):
    cache = GalleryCache(str(tmp_path / "gallery_cache.json"))
    remove = GalleryRecord(service="vipr.im", id="43", name="Remove")
    keep = GalleryRecord(service="vipr.im", id="42", name="Keep")
    cache.upsert_records("vipr.im", [keep, remove])
    statuses = []
    render_calls = []
    manager = GalleryManager.__new__(GalleryManager)
    manager.gallery_cache = cache
    manager.service_var = FakeVar("vipr.im")
    manager._delete_request_id = 9
    manager._records = [keep, remove]
    manager._set_status = lambda message, is_error=False: statuses.append((message, is_error))
    manager._render_current_records = lambda: render_calls.append(True)

    GalleryManager._handle_delete_result(
        manager,
        9,
        "vipr.im",
        remove,
        GalleryResult(
            status=GalleryStatus.SUCCESS,
            message="Deleted gallery 'Remove' (43).",
            service="vipr.im",
            record=remove,
        ),
    )

    assert statuses[-1] == ("Deleted gallery 'Remove' (43).", False)
    assert [record.id for record in manager._records] == ["42"]
    assert [record.id for record in cache.records_for_service("vipr.im")] == ["42"]
    assert render_calls == [True]


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
            service="pixhost.cc",
            id="200",
            name="Alpha",
            url="https://pixhost.cc/gallery/200",
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
