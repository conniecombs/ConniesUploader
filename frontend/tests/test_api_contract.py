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
    assert payload["service"] == "vipr.im"
    assert spec["url"] == "https://vipr.im/"
    assert spec["form_fields"]["op"] == "my_files"
    assert spec["form_fields"]["create_new_folder"] == "Batch Gallery"
    assert spec["pre_request"]["form_fields"]["login"] == "user"
