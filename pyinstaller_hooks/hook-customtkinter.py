"""PyInstaller hook for CustomTkinter plus Tcl/Tk shared libraries.

The upstream CustomTkinter hook collects package assets, but Windows builds made
from Conda-based virtual environments can miss the Tcl/Tk DLLs that _tkinter.pyd
loads from the base interpreter's Library/bin directory.
"""

import os

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks.tcl_tk import tcltk_info

datas = collect_data_files("customtkinter")
binaries = []

for library in (tcltk_info.tcl_shared_library, tcltk_info.tk_shared_library):
    if library and os.path.exists(library):
        binaries.append((library, "."))
