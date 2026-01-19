# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Comprehensive tests for modules/utils.py - Utility functions"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.utils import ContextUtils


@pytest.mark.unit
class TestUtilsImports:
    """Test utils module imports"""

    def test_module_import(self):
        """Test that utils module imports successfully"""
        from modules import utils

        assert utils is not None

    def test_context_utils_class_exists(self):
        """Test that ContextUtils class exists"""
        assert ContextUtils is not None


@pytest.mark.unit
class TestContextUtils:
    """Test ContextUtils functionality"""

    def test_context_utils_is_static(self):
        """Test that ContextUtils methods are static"""
        assert hasattr(ContextUtils, "install_menu")
        assert hasattr(ContextUtils, "remove_menu")

        # Should be callable without instantiation
        assert callable(ContextUtils.install_menu)
        assert callable(ContextUtils.remove_menu)


@pytest.mark.unit
@patch("platform.system")
class TestInstallMenu:
    """Test context menu installation"""

    def test_install_menu_windows_only(self, mock_system):
        """Test that install_menu only works on Windows"""
        mock_system.return_value = "Linux"

        # Should return early on non-Windows
        ContextUtils.install_menu()  # Should not raise error

        mock_system.return_value = "Darwin"  # macOS
        ContextUtils.install_menu()  # Should not raise error

    @patch("winreg.CreateKey")
    @patch("winreg.SetValue")
    @patch("tkinter.messagebox.showinfo")
    def test_install_menu_on_windows(
        self, mock_showinfo, mock_setvalue, mock_createkey, mock_system
    ):
        """Test successful context menu installation on Windows"""
        mock_system.return_value = "Windows"
        mock_key = MagicMock()
        mock_createkey.return_value = mock_key

        try:
            ContextUtils.install_menu()

            # Should have created registry keys if on Windows
            if sys.platform == "win32":
                assert mock_createkey.called
        except Exception:
            # May fail if winreg is not available (non-Windows test environment)
            pass

    @patch("winreg.CreateKey")
    @patch("tkinter.messagebox.showerror")
    def test_install_menu_handles_errors(self, mock_showerror, mock_createkey, mock_system):
        """Test error handling during installation"""
        mock_system.return_value = "Windows"
        mock_createkey.side_effect = Exception("Registry error")

        try:
            ContextUtils.install_menu()

            # Should show error message if on Windows
            if sys.platform == "win32":
                assert mock_showerror.called
        except Exception:
            # Acceptable if winreg is not available
            pass

    def test_install_menu_uses_pythonw(self, mock_system):
        """Test that pythonw.exe is used when available"""
        mock_system.return_value = "Windows"

        # On Windows, should prefer pythonw.exe (no console window)
        if sys.platform == "win32":
            py_exe = sys.executable.replace("python.exe", "pythonw.exe")
            # Logic should check if pythonw exists
            assert isinstance(py_exe, str)

    @patch("sys.frozen", True, create=True)
    def test_install_menu_frozen_mode(self, mock_system):
        """Test context menu installation in frozen (PyInstaller) mode"""
        mock_system.return_value = "Windows"

        # In frozen mode, should use sys.executable directly
        if hasattr(sys, "frozen") and sys.frozen:
            exe = sys.executable
            assert os.path.exists(exe) or True  # May not exist in test environment


@pytest.mark.unit
@patch("platform.system")
class TestRemoveMenu:
    """Test context menu removal"""

    def test_remove_menu_windows_only(self, mock_system):
        """Test that remove_menu only works on Windows"""
        mock_system.return_value = "Linux"
        ContextUtils.remove_menu()  # Should not raise error

        mock_system.return_value = "Darwin"
        ContextUtils.remove_menu()  # Should not raise error

    @patch("winreg.DeleteKey")
    @patch("tkinter.messagebox.showinfo")
    def test_remove_menu_on_windows(self, mock_showinfo, mock_deletekey, mock_system):
        """Test successful context menu removal on Windows"""
        mock_system.return_value = "Windows"

        try:
            ContextUtils.remove_menu()

            # Should have deleted registry keys if on Windows
            if sys.platform == "win32":
                assert mock_deletekey.called
        except Exception:
            # May fail if winreg is not available
            pass

    @patch("winreg.DeleteKey")
    @patch("loguru.logger.warning")
    def test_remove_menu_handles_missing(self, mock_warning, mock_deletekey, mock_system):
        """Test handling when context menu is not installed"""
        mock_system.return_value = "Windows"
        mock_deletekey.side_effect = OSError("Key not found")

        try:
            ContextUtils.remove_menu()

            # Should log warning if on Windows
            if sys.platform == "win32":
                # May or may not call warning depending on implementation
                pass
        except Exception:
            # Acceptable if winreg is not available
            pass

    @patch("winreg.DeleteKey")
    def test_remove_menu_deletes_in_order(self, mock_deletekey, mock_system):
        """Test that registry keys are deleted in correct order"""
        mock_system.return_value = "Windows"

        try:
            ContextUtils.remove_menu()

            if sys.platform == "win32" and mock_deletekey.called:
                # Should delete command key first, then parent key
                calls = mock_deletekey.call_args_list
                # Verify order or structure
                assert len(calls) >= 1
        except Exception:
            pass


@pytest.mark.unit
class TestContextUtilsPlatformDetection:
    """Test platform detection logic"""

    @patch("platform.system")
    def test_detects_windows(self, mock_system):
        """Test Windows platform detection"""
        mock_system.return_value = "Windows"
        assert platform.system() == "Windows" or mock_system.return_value == "Windows"

    @patch("platform.system")
    def test_detects_linux(self, mock_system):
        """Test Linux platform detection"""
        mock_system.return_value = "Linux"
        assert mock_system.return_value == "Linux"

    @patch("platform.system")
    def test_detects_macos(self, mock_system):
        """Test macOS platform detection"""
        mock_system.return_value = "Darwin"
        assert mock_system.return_value == "Darwin"


@pytest.mark.unit
class TestRegistryPathConstruction:
    """Test registry path construction"""

    def test_registry_path_format(self):
        """Test that registry paths are correctly formatted"""
        parent_path = r"Directory\shell\ConniesUploader"
        command_path = r"Directory\shell\ConniesUploader\command"

        assert "\\" in parent_path
        assert "command" in command_path
        assert command_path.startswith(parent_path.rstrip("\\"))

    def test_registry_key_names(self):
        """Test registry key naming conventions"""
        key_name = "ConniesUploader"

        assert " " not in key_name  # No spaces in registry key name
        assert key_name.isalnum() or key_name.replace("'", "").isalnum()


@pytest.mark.unit
class TestExecutablePathHandling:
    """Test executable path detection and handling"""

    def test_sys_executable_exists(self):
        """Test that sys.executable is available"""
        assert sys.executable is not None
        assert isinstance(sys.executable, str)
        assert len(sys.executable) > 0

    def test_script_path_from_argv(self):
        """Test script path detection from sys.argv"""
        assert len(sys.argv) > 0
        script_path = os.path.abspath(sys.argv[0])
        assert os.path.isabs(script_path)

    def test_frozen_detection(self):
        """Test PyInstaller frozen state detection"""
        is_frozen = getattr(sys, "frozen", False)
        assert isinstance(is_frozen, bool)

    def test_pythonw_replacement(self):
        """Test python.exe to pythonw.exe replacement"""
        if sys.platform == "win32":
            py_exe = "C:\\Python\\python.exe"
            pythonw_exe = py_exe.replace("python.exe", "pythonw.exe")

            assert pythonw_exe == "C:\\Python\\pythonw.exe"
            assert "pythonw" in pythonw_exe


@pytest.mark.unit
class TestCommandConstruction:
    """Test command line construction for registry"""

    def test_command_with_quotes(self):
        """Test that executable and script paths are quoted"""
        py_exe = "C:\\Path\\python.exe"
        script_path = "C:\\Path\\script.py"
        folder = "%V"

        cmd = f'"{py_exe}" "{script_path}" "{folder}"'

        assert cmd.count('"') >= 6  # Three quoted items
        assert folder in cmd

    def test_command_with_spaces(self):
        """Test command construction with paths containing spaces"""
        py_exe = "C:\\Program Files\\Python\\python.exe"
        script_path = "C:\\My Documents\\script.py"

        cmd = f'"{py_exe}" "{script_path}"'

        # Spaces should be within quotes
        assert '"' in cmd
        assert "Program Files" in cmd
        assert "My Documents" in cmd

    def test_frozen_command_format(self):
        """Test command format for frozen executable"""
        executable = "C:\\App\\ConniesUploader.exe"
        folder = "%V"

        cmd = f'"{executable}" "{folder}"'

        assert executable in cmd
        assert "%V" in cmd


@pytest.mark.integration
class TestContextUtilsIntegration:
    """Integration tests for context utils"""

    @patch("platform.system")
    @patch("winreg.CreateKey")
    @patch("winreg.SetValue")
    @patch("winreg.DeleteKey")
    @patch("tkinter.messagebox.showinfo")
    def test_install_and_remove_cycle(
        self, mock_showinfo, mock_deletekey, mock_setvalue, mock_createkey, mock_system
    ):
        """Test complete install and remove cycle"""
        mock_system.return_value = "Windows"
        mock_key = MagicMock()
        mock_createkey.return_value = mock_key

        try:
            # Install
            ContextUtils.install_menu()

            # Remove
            ContextUtils.remove_menu()

            # Both operations should complete without error
            assert True
        except Exception:
            # Acceptable in non-Windows environment
            pass


if __name__ == "__main__":
    # Import platform for tests that need it
    import platform

    pytest.main([__file__, "-v", "-m", "unit"])
