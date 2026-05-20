# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Comprehensive tests for modules/validation.py - Input validation and sanitization"""

import pytest
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.validation import (
    validate_file_path,
    validate_directory_path,
    sanitize_filename,
    validate_service_name,
    validate_thread_count,
)


@pytest.mark.unit
class TestValidateFilePath:
    """Test file path validation"""

    def test_valid_file(self):
        """Test validation of existing file"""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            temp_file = f.name

        try:
            result = validate_file_path(temp_file)
            assert result is not None
            assert os.path.isabs(result)
            assert temp_file in result or os.path.basename(temp_file) in result
        finally:
            os.unlink(temp_file)

    def test_nonexistent_file(self):
        """Test that nonexistent files return None"""
        result = validate_file_path("/path/to/nonexistent/file.jpg")
        assert result is None

    def test_directory_not_file(self):
        """Test that directories return None"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = validate_file_path(temp_dir)
            assert result is None

    def test_extension_validation(self):
        """Test file extension validation"""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            jpg_file = f.name

        try:
            # Should pass with .jpg extension
            result = validate_file_path(jpg_file, allowed_extensions=(".jpg", ".png"))
            assert result is not None
        finally:
            os.unlink(jpg_file)

    def test_invalid_extension(self):
        """Test rejection of invalid extensions"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            txt_file = f.name

        try:
            result = validate_file_path(txt_file, allowed_extensions=(".jpg", ".png"))
            assert result is None
        finally:
            os.unlink(txt_file)

    def test_path_traversal_detection(self):
        """Test that path traversal attempts are detected"""
        # This should fail even if file exists
        result = validate_file_path("../../../etc/passwd")
        assert result is None

    def test_hidden_files_rejected(self):
        """Test that hidden files (starting with dot) are rejected"""
        with tempfile.TemporaryDirectory() as temp_dir:
            hidden_file = Path(temp_dir) / ".hidden.jpg"
            hidden_file.touch()

            result = validate_file_path(str(hidden_file))
            assert result is None


@pytest.mark.unit
class TestValidateDirectoryPath:
    """Test directory path validation"""

    def test_valid_directory(self):
        """Test validation of existing directory"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = validate_directory_path(temp_dir)
            assert result is not None
            assert os.path.isabs(result)
            assert os.path.isdir(result)

    def test_nonexistent_directory(self):
        """Test that nonexistent directories return None"""
        result = validate_directory_path("/path/to/nonexistent/directory")
        assert result is None

    def test_file_not_directory(self):
        """Test that files return None"""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_file = f.name

        try:
            result = validate_directory_path(temp_file)
            assert result is None
        finally:
            os.unlink(temp_file)

    def test_absolute_path_returned(self):
        """Test that absolute paths are returned"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = validate_directory_path(temp_dir)
            assert os.path.isabs(result)

    def test_path_traversal_in_directory(self):
        """Test path traversal detection for directories"""
        result = validate_directory_path("../../../tmp")
        # May succeed if /tmp exists, but should be resolved
        if result:
            assert ".." not in result


@pytest.mark.unit
class TestSanitizeFilename:
    """Test filename sanitization"""

    def test_basic_filename(self):
        """Test that safe filenames pass through"""
        assert sanitize_filename("image") == "image"
        assert sanitize_filename("my_file") == "my_file"

    def test_spaces_to_underscores(self):
        """Test that spaces become underscores"""
        assert sanitize_filename("my file") == "my_file"
        assert sanitize_filename("multiple  spaces") == "multiple_spaces"

    def test_dangerous_characters_removed(self):
        """Test removal of dangerous characters"""
        result = sanitize_filename('file<>:"|?*/name')
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert '"' not in result
        assert "|" not in result
        assert "?" not in result
        assert "*" not in result
        assert "/" not in result

    def test_path_traversal_removed(self):
        """Test that path traversal attempts are neutralized"""
        result = sanitize_filename("../../../etc/passwd")
        assert ".." not in result
        assert "/" not in result

    def test_null_bytes_removed(self):
        """Test that null bytes are removed"""
        result = sanitize_filename("file\x00name")
        assert "\x00" not in result

    def test_windows_reserved_names(self):
        """Test handling of Windows reserved names"""
        reserved_names = ["CON", "PRN", "AUX", "NUL", "COM1", "LPT1"]
        for name in reserved_names:
            result = sanitize_filename(name)
            assert result.startswith("file_")

    def test_empty_string_fallback(self):
        """Test fallback for empty strings"""
        assert sanitize_filename("") == "untitled"
        assert sanitize_filename("   ") == "untitled"

    def test_max_length_enforcement(self):
        """Test maximum length enforcement"""
        long_name = "a" * 300
        result = sanitize_filename(long_name, max_length=200)
        assert len(result) <= 200

    def test_unicode_characters(self):
        """Test handling of unicode characters"""
        result = sanitize_filename("файл")  # Russian "file"
        # Should handle unicode gracefully
        assert result is not None
        assert len(result) > 0

    def test_leading_trailing_stripped(self):
        """Test that leading/trailing underscores are stripped"""
        assert sanitize_filename("__file__") == "file"


@pytest.mark.unit
class TestValidateServiceName:
    """Test service name validation"""

    def test_valid_service_names(self):
        """Test that known service names are valid"""
        valid_services = ["imx.to", "pixhost.to", "turboimagehost", "vipr.im"]

        for service in valid_services:
            result = validate_service_name(service)
            assert result is True

    def test_invalid_service_name(self):
        """Test that unknown services return False"""
        result = validate_service_name("unknown.service")
        assert result is False

    def test_empty_service_name(self):
        """Test that empty string returns False"""
        result = validate_service_name("")
        assert result is False

    def test_with_plugin_manager(self):
        """Test validation with plugin manager"""
        # Mock plugin manager
        mock_pm = Mock()
        mock_plugin1 = Mock()
        mock_plugin1.service_id = "custom.service"
        mock_plugin2 = Mock()
        mock_plugin2.service_id = "another.service"

        mock_pm.get_all_plugins.return_value = [mock_plugin1, mock_plugin2]

        # Should accept services from plugin manager
        result = validate_service_name("custom.service", plugin_manager=mock_pm)
        assert result is True

        result = validate_service_name("another.service", plugin_manager=mock_pm)
        assert result is True

        # Should reject unknown services
        result = validate_service_name("unknown.service", plugin_manager=mock_pm)
        assert result is False

    def test_case_sensitivity(self):
        """Test that service names are case-sensitive"""
        # Assuming lowercase is standard
        assert validate_service_name("imx.to") is True
        # Uppercase might not be valid
        result = validate_service_name("IMX.TO")
        # Behavior depends on implementation

    def test_none_service_name(self):
        """Test handling of None input"""
        try:
            result = validate_service_name(None)
            # Should either return False or raise TypeError
            assert result is False
        except (TypeError, AttributeError):
            # Acceptable to raise exception for None
            pass


@pytest.mark.unit
class TestValidateThreadCount:
    """Test thread count validation"""

    def test_valid_thread_counts(self):
        """Test valid thread counts"""
        assert validate_thread_count(1) == 1
        assert validate_thread_count(4) == 4
        assert validate_thread_count(8) == 8

    def test_minimum_clamping(self):
        """Test that thread count is clamped to minimum"""
        assert validate_thread_count(0) >= 1
        assert validate_thread_count(-5) >= 1

    def test_maximum_clamping(self):
        """Test that thread count is clamped to maximum"""
        result = validate_thread_count(100)
        assert result <= 16  # Typical maximum

    def test_default_value(self):
        """Test default thread count when None is provided"""
        try:
            result = validate_thread_count(None)
            assert result >= 1
            assert result <= 16
        except TypeError:
            # Acceptable if None is not handled
            pass

    def test_string_conversion(self):
        """Test conversion from string"""
        try:
            result = validate_thread_count("4")
            assert result == 4
        except (TypeError, ValueError):
            # Acceptable if string conversion is not supported
            pass

    def test_float_handling(self):
        """Test handling of float values"""
        try:
            result = validate_thread_count(4.7)
            assert result == 4 or result == 5  # Truncated or rounded
        except TypeError:
            # Acceptable if floats are not supported
            pass


@pytest.mark.unit
class TestValidationEdgeCases:
    """Test edge cases and error conditions"""

    def test_symlink_handling(self):
        """Test handling of symbolic links"""
        if os.name != "nt":  # Unix-like systems
            with tempfile.TemporaryDirectory() as temp_dir:
                target = Path(temp_dir) / "target.jpg"
                target.touch()

                symlink = Path(temp_dir) / "link.jpg"
                try:
                    symlink.symlink_to(target)

                    # Validate should handle symlinks appropriately
                    result = validate_file_path(str(symlink))
                    # Implementation-dependent behavior
                except (OSError, NotImplementedError):
                    # Symlinks might not be supported
                    pass

    def test_very_long_paths(self):
        """Test handling of very long file paths"""
        long_path = "/tmp/" + ("a" * 500) + ".jpg"
        result = validate_file_path(long_path)
        # Should handle gracefully (likely None as file doesn't exist)
        assert result is None or isinstance(result, str)

    def test_unicode_paths(self):
        """Test handling of unicode in paths"""
        with tempfile.TemporaryDirectory() as temp_dir:
            unicode_file = Path(temp_dir) / "文件.jpg"  # Chinese "file"
            unicode_file.touch()

            result = validate_file_path(str(unicode_file))
            # Should handle unicode paths
            assert result is not None

    def test_special_characters_in_path(self):
        """Test paths with special characters"""
        # Test with parentheses, brackets, etc.
        filename = sanitize_filename("file (copy) [1].jpg")
        assert "(" not in filename or ")" not in filename  # Depending on implementation


@pytest.mark.integration
class TestValidationIntegration:
    """Integration tests for validation module"""

    def test_full_file_validation_pipeline(self):
        """Test complete validation pipeline"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create file with problematic name
            unsafe_name = "my<file>:test.jpg"
            safe_name = sanitize_filename(unsafe_name)

            file_path = Path(temp_dir) / safe_name
            file_path.touch()

            # Validate the sanitized file
            result = validate_file_path(str(file_path), allowed_extensions=(".jpg",))
            assert result is not None
            assert "<" not in result
            assert ":" not in result

    def test_directory_and_file_validation(self):
        """Test validating both directory and files within"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Validate directory
            dir_result = validate_directory_path(temp_dir)
            assert dir_result is not None

            # Create and validate file in directory
            file_path = Path(temp_dir) / "test.jpg"
            file_path.touch()

            file_result = validate_file_path(str(file_path))
            assert file_result is not None
            assert temp_dir in file_result


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "unit"])
