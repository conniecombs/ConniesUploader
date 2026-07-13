# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

from unittest.mock import Mock, patch

from modules import api


def test_vipr_metadata_normalizes_null_sidecar_data():
    bridge = Mock()
    bridge.request_sync.return_value = {"status": "success", "data": None}

    with patch.object(api.SidecarBridge, "get", return_value=bridge):
        metadata = api.get_vipr_metadata(
            {"vipr_user": "johngrimm", "vipr_pass": "secret"}
        )

    assert metadata == {"galleries": []}


def test_create_imx_gallery_uses_gallery_service_live_form_flow():
    record = Mock(id="abc123")
    result = Mock(ok=True, record=record)

    with patch("modules.gallery_service.GalleryService") as service_cls:
        service_cls.return_value.create_gallery.return_value = result

        gallery_id = api.create_imx_gallery("user", "secret", "Batch Gallery")

    assert gallery_id == "abc123"
    service_cls.assert_called_once_with(
        bridge=None,
        creds={"imx_user": "user", "imx_pass": "secret"},
    )
    service_cls.return_value.create_gallery.assert_called_once_with(
        "imx.to", "Batch Gallery"
    )


def test_delete_imx_gallery_uses_gallery_service_live_edit_form_flow():
    result = Mock(ok=True)

    with patch("modules.gallery_service.GalleryService") as service_cls:
        service_cls.return_value.delete_gallery.return_value = result

        deleted = api.delete_imx_gallery("user", "secret", "abc123")

    assert deleted is True
    service_cls.assert_called_once_with(
        bridge=None,
        creds={"imx_user": "user", "imx_pass": "secret"},
    )
    service_cls.return_value.delete_gallery.assert_called_once_with(
        "imx.to", "abc123"
    )


def test_vipr_metadata_parses_file_manager_public_gallery_urls():
    bridge = Mock()
    bridge.request_sync.return_value = {
        "status": "success",
        "data": {
            "response_body": """
            <body>
              <a href="?op=my_files;fld_id=104485">0000010101</a>
              <a href="https://vipr.im/p/johngrimm/104485/0000010101" class="pub"></a>
            </body>
            """,
        },
    }

    with patch.object(api.SidecarBridge, "get", return_value=bridge):
        metadata = api.get_vipr_metadata({"vipr_user": "user", "vipr_pass": "secret"})

    assert metadata["galleries"] == [
        {
            "id": "104485",
            "name": "0000010101",
            "url": "https://vipr.im/p/johngrimm/104485/0000010101",
            "username": "johngrimm",
        }
    ]


def test_create_vipr_gallery_uses_file_manager_contract():
    bridge = Mock()
    bridge.request_sync.return_value = {
        "status": "success",
        "data": {
            "response_body": """
            <body>
              <a href="?op=my_files;fld_id=105000">Batch Gallery</a>
              <a href="https://vipr.im/p/johngrimm/105000/Batch%20Gallery" class="pub"></a>
            </body>
            """,
        },
    }

    with patch.object(api.SidecarBridge, "get", return_value=bridge):
        created = api.create_vipr_gallery(
            {"vipr_user": "user", "vipr_pass": "secret"}, "Batch Gallery"
        )

    assert created == {
        "id": "105000",
        "name": "Batch Gallery",
        "url": "https://vipr.im/p/johngrimm/105000/Batch%20Gallery",
        "gallery_id": "105000",
        "gallery_name": "Batch Gallery",
        "gallery_url": "https://vipr.im/p/johngrimm/105000/Batch%20Gallery",
    }
    payload = bridge.request_sync.call_args.args[0]
    spec = payload["generic_spec"]
    login_payload = bridge.request_sync.call_args_list[0].args[0]
    login_spec = login_payload["generic_spec"]
    assert login_spec["form_fields"]["op"] == "login"
    assert login_spec["form_fields"]["login"] == "user"
    assert payload["service"] == "vipr.im"
    assert spec["url"] == "https://vipr.im/"
    assert spec["form_fields"]["op"] == "my_files"
    assert spec["form_fields"]["create_new_folder"] == "Batch Gallery"
    assert "pre_request" not in spec
    assert "extract_fields" not in spec
    assert spec["include_response_body"] is True


def test_delete_vipr_gallery_uses_file_manager_delete_contract():
    bridge = Mock()
    bridge.request_sync.return_value = {
        "status": "success",
        "data": {
            "response_body": """
            <body>
              <a href="?op=my_files;fld_id=105001">Keep Gallery</a>
              <a href="https://vipr.im/p/johngrimm/105001/Keep%20Gallery" class="pub"></a>
            </body>
            """,
        },
    }

    with patch.object(api.SidecarBridge, "get", return_value=bridge):
        deleted = api.delete_vipr_gallery(
            {"vipr_user": "user", "vipr_pass": "secret"}, "105000"
        )

    assert deleted is True
    payload = bridge.request_sync.call_args.args[0]
    spec = payload["generic_spec"]
    login_payload = bridge.request_sync.call_args_list[0].args[0]
    login_spec = login_payload["generic_spec"]
    assert login_spec["form_fields"]["op"] == "login"
    assert login_spec["form_fields"]["login"] == "user"
    assert payload["service"] == "vipr.im"
    assert spec["url"] == "https://vipr.im/?op=my_files&fld_id=0&del_folder=105000"
    assert spec["method"] == "GET"
    assert "pre_request" not in spec
    assert "extract_fields" not in spec
    assert spec["include_response_body"] is True
