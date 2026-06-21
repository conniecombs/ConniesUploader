from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_windows_build_uses_local_pyinstaller_hooks_and_verifies_tkinter():
    script = (ROOT / "build_uploader.bat").read_text()

    assert '--additional-hooks-dir "pyinstaller_hooks"' in script
    assert '/C:"_tkinter.pyd"' in script
    assert '/C:"_tcl_data"' in script
    assert '/C:"_tk_data"' in script
    assert '/C:"tcl86t.dll"' in script
    assert '/C:"tk86t.dll"' in script
    assert "Tkinter runtime bundled" in script
    assert "taskkill /F /IM" in script
    assert "Closing running %APP_NAME%.exe before rebuild" in script


def test_other_build_entrypoints_use_local_pyinstaller_hooks():
    assert '--additional-hooks-dir "pyinstaller_hooks"' in (ROOT / "build.sh").read_text()
    assert '--additional-hooks-dir "pyinstaller_hooks"' in (ROOT / "Makefile").read_text()


def test_customtkinter_hook_preserves_assets_and_adds_tcl_tk_binaries():
    hook = (ROOT / "pyinstaller_hooks" / "hook-customtkinter.py").read_text()

    assert 'collect_data_files("customtkinter")' in hook
    assert "tcltk_info.tcl_shared_library" in hook
    assert "tcltk_info.tk_shared_library" in hook
    assert 'binaries.append((library, "."))' in hook
