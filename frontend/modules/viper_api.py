# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Compatibility facade for the ViperGirls modules (split in v3.1.3).

The implementation now lives in three modules:

- ``modules.viper_storage``: posting targets, history, and scheduled posts on disk
- ``modules.viper_client``: thread titles, login, replies, and the post scheduler
- ``modules.viper_ui``: the posting-target and posting-history windows

This module re-exports their names for older imports. Assigning to a
re-exported name here (for example ``monkeypatch.setattr(viper_api,
"THREADS_FILE", ...)``) would not change the owning module, so it raises with
the module to patch instead.
"""

import re as _re
import sys as _sys
import types as _types
from pathlib import Path as _Path

from modules import viper_client as _viper_client
from modules import viper_storage as _viper_storage
from modules import viper_ui as _viper_ui

_OWNERS = {}
for _module in (_viper_storage, _viper_client, _viper_ui):
    _source = _Path(_module.__file__).read_text(encoding="utf-8")
    for _name in _re.findall(r"^(?:def|class) (\w+)|^(\w+)\s*=", _source, _re.M):
        _name = _name[0] or _name[1]
        _OWNERS[_name] = _module.__name__
        globals()[_name] = getattr(_module, _name)

# Names older callers reached through this module.
SidecarBridge = _viper_client.SidecarBridge


class _ViperApiFacade(_types.ModuleType):
    def __setattr__(self, name, value):
        owner = _OWNERS.get(name)
        if owner is not None:
            raise AttributeError(
                f"modules.viper_api.{name} is re-exported from {owner}; "
                f"patch {owner}.{name} instead"
            )
        super().__setattr__(name, value)


_sys.modules[__name__].__class__ = _ViperApiFacade
