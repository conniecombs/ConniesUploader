# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Tests for modules/file_handler.py"""

import pytest
import os
import tempfile
from pathlib import Path

# Add parent directory to path for imports
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.file_handler import (
    sanitize_filename,
    scan_inputs,
    get_files_from_directory,
    VALID_EXTENSIONS,
)


class TestSanitizeFilename:
    """Test suite for sanitize_filename function"""

    def test_basic_filename(self):
        """Test that basic filenames pass through unchanged"""
        assert sanitize_filename("myfile") == "myfile"
        assert sanitize_filename("my_file") == "my_file"
        assert sanitize_filename("my-file") == "my-file"
        assert sanitize_filename("my file") == "my_file"

    def test_removes_nul_bytes(self):
        """Test that NUL bytes are removed"""
        assert sanitize_filename("file\x00name") == "filename"

    def test_removes_control_characters(self):
        """Test that control characters are removed"""
        assert sanitize_filename("file\x01\x02name") == "filename"

    def test_prevents_path_traversal(self):
        """Test that path traversal is prevented"""
        assert ".." not in sanitize_filename("../etc/passwd")
        assert "./" not in sanitize_filename("./secret")
        assert "\\" not in sanitize_filename("..\\windows\\system32")

    def test_removes_invalid_characters(self):
        """Test that invalid filesystem characters are replaced"""
        result = sanitize_filename("file:name*with?<invalid>chars|")
        assert ":" not in result
        assert "*" not in result
        assert "?" not in result
        assert "<" not in result
        assert ">" not in result
        assert "|" not in result

    def test_collapses_multiple_spaces(self):
        """Test that multiple spaces/underscores are collapsed"""
        assert sanitize_filename("multiple    spaces") == "multiple_spaces"
        assert sanitize_filename("multiple____underscores") == "multiple_underscores"

    def test_windows_reserved_names(self):
        """Test that Windows reserved names are prefixed"""
        assert sanitize_filename("CON") == "file_CON"
        assert sanitize_filename("PRN") == "file_PRN"
        assert sanitize_filename("AUX") == "file_AUX"
        assert sanitize_filename("NUL") == "file_NUL"
        assert sanitize_filename("COM1") == "file_COM1"
        assert sanitize_filename("LPT1") == "file_LPT1"

    def test_empty_string_fallback(self):
        """Test that empty strings get a default name"""
        assert sanitize_filename("") == "untitled"
        assert sanitize_filename("   ") == "untitled"
        assert sanitize_filename("___") == "untitled"

    def test_max_length_truncation(self):
        """Test that long filenames are truncated"""
        long_name = "a" * 300
        result = sanitize_filename(long_name, max_length=200)
        assert len(result) == 200

    def test_strips_leading_trailing(self):
        """Test that leading/trailing underscores are removed"""
        assert sanitize_filename("__file__") == "file"
        assert sanitize_filename("  file  ") == "file"


class TestScanInputs:
    """Test suite for scan_inputs function"""

    def test_empty_input(self):
        """Test that empty input returns empty list"""
        assert scan_inputs([]) == []
        assert scan_inputs(None) == []

    def test_single_file(self):
        """Test scanning a single valid file"""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            temp_file = f.name
        try:
            result = scan_inputs(temp_file)
            assert len(result) == 1
            assert temp_file in result
        finally:
            os.unlink(temp_file)

    def test_invalid_extension(self):
        """Test that files with invalid extensions are skipped"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            temp_file = f.name
        try:
            result = scan_inputs(temp_file)
            assert len(result) == 0
        finally:
            os.unlink(temp_file)

    def test_directory_scanning(self):
        """Test scanning a directory for images"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test files
            jpg_file = Path(temp_dir) / "test1.jpg"
            png_file = Path(temp_dir) / "test2.png"
            txt_file = Path(temp_dir) / "test3.txt"

            jpg_file.touch()
            png_file.touch()
            txt_file.touch()

            result = scan_inputs(temp_dir)

            assert len(result) == 2  # Only jpg and png
            assert str(jpg_file) in result
            assert str(png_file) in result
            assert str(txt_file) not in result

    def test_multiple_inputs(self):
        """Test scanning multiple files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            file1 = Path(temp_dir) / "test1.jpg"
            file2 = Path(temp_dir) / "test2.png"
            file1.touch()
            file2.touch()

            result = scan_inputs([str(file1), str(file2)])
            assert len(result) == 2

    def test_deduplication(self):
        """Test that duplicate files are removed"""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            temp_file = f.name
        try:
            result = scan_inputs([temp_file, temp_file, temp_file])
            assert len(result) == 1
        finally:
            os.unlink(temp_file)


class TestGetFilesFromDirectory:
    """Test suite for get_files_from_directory function"""

    def test_empty_directory(self):
        """Test scanning an empty directory"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = get_files_from_directory(temp_dir)
            assert result == []

    def test_nested_directories(self):
        """Test that nested directories are scanned recursively"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create nested structure
            sub_dir = Path(temp_dir) / "subdir"
            sub_dir.mkdir()

            file1 = Path(temp_dir) / "test1.jpg"
            file2 = sub_dir / "test2.png"

            file1.touch()
            file2.touch()

            result = get_files_from_directory(temp_dir)
            assert len(result) == 2
            assert str(file1) in result
            assert str(file2) in result

    def test_mixed_files(self):
        """Test directory with valid and invalid files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            jpg_file = Path(temp_dir) / "image.jpg"
            txt_file = Path(temp_dir) / "document.txt"
            gif_file = Path(temp_dir) / "animation.gif"

            jpg_file.touch()
            txt_file.touch()
            gif_file.touch()

            result = get_files_from_directory(temp_dir)
            assert len(result) == 2  # jpg and gif only
            assert str(jpg_file) in result
            assert str(gif_file) in result
            assert str(txt_file) not in result


class TestValidExtensions:
    """Test that VALID_EXTENSIONS constant is properly defined"""

    def test_valid_extensions_exists(self):
        """Test that VALID_EXTENSIONS is defined"""
        assert VALID_EXTENSIONS is not None

    def test_common_formats(self):
        """Test that common image formats are included"""
        assert ".jpg" in VALID_EXTENSIONS
        assert ".jpeg" in VALID_EXTENSIONS
        assert ".png" in VALID_EXTENSIONS
        assert ".gif" in VALID_EXTENSIONS

    def test_extensions_lowercase(self):
        """Test that extensions are lowercase"""
        for ext in VALID_EXTENSIONS:
            assert ext == ext.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
