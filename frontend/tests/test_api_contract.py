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
