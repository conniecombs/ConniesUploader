# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Build an UploaderApp for contract tests without starting Tk.

Real tkinter resolves a missing attribute through ``Misc.__getattr__``, which
recurses forever on an object whose ``__init__`` never ran. Tests therefore
must not hand mixin code a bare ``UploaderApp.__new__(UploaderApp)``; this
factory gives it the same plain-Python defaults ``UploaderApp.__init__`` sets.
Tests then override only the attributes and widget fakes they care about.
"""

from modules.ui.main_window import UploaderApp


def make_app() -> UploaderApp:
    app = UploaderApp.__new__(UploaderApp)
    UploaderApp._init_runtime_state(app)
    return app
