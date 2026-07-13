# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Tests for modules/exceptions.py"""

import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.exceptions import (
    UploaderException,
    SidecarException,
    SidecarCrashException,
    SidecarNotFoundError,
    UploadException,
    UploadFailedException,
    ValidationException,
    InvalidFileException,
    InvalidServiceException,
    PluginException,
    PluginLoadException,
    ConfigException,
    InvalidConfigException,
    CredentialsException,
    MissingCredentialsException,
    NetworkException,
    RateLimitException,
)


class TestExceptionHierarchy:
    """Test that exception hierarchy is correctly set up"""

    def test_base_exception(self):
        """Test UploaderException is a standard Exception"""
        assert issubclass(UploaderException, Exception)

    def test_sidecar_exceptions(self):
        """Test sidecar exception hierarchy"""
        assert issubclass(SidecarException, UploaderException)
        assert issubclass(SidecarCrashException, SidecarException)
        assert issubclass(SidecarNotFoundError, SidecarException)

    def test_upload_exceptions(self):
        """Test upload exception hierarchy"""
        assert issubclass(UploadException, UploaderException)
        assert issubclass(UploadFailedException, UploadException)

    def test_validation_exceptions(self):
        """Test validation exception hierarchy"""
        assert issubclass(ValidationException, UploaderException)
        assert issubclass(InvalidFileException, ValidationException)
        assert issubclass(InvalidServiceException, ValidationException)

    def test_plugin_exceptions(self):
        """Test plugin exception hierarchy"""
        assert issubclass(PluginException, UploaderException)
        assert issubclass(PluginLoadException, PluginException)

    def test_config_exceptions(self):
        """Test config exception hierarchy"""
        assert issubclass(ConfigException, UploaderException)
        assert issubclass(InvalidConfigException, ConfigException)

    def test_credentials_exceptions(self):
        """Test credentials exception hierarchy"""
        assert issubclass(CredentialsException, UploaderException)
        assert issubclass(MissingCredentialsException, CredentialsException)

    def test_network_exceptions(self):
        """Test network exception hierarchy"""
        assert issubclass(NetworkException, UploaderException)
        assert issubclass(RateLimitException, NetworkException)


class TestUploadFailedException:
    """Test UploadFailedException functionality"""

    def test_basic_creation(self):
        """Test creating UploadFailedException"""
        exc = UploadFailedException("pixhost", "Connection timeout")
        assert exc.service == "pixhost"
        assert "pixhost" in str(exc)
        assert "Connection timeout" in str(exc)

    def test_with_original_error(self):
        """Test UploadFailedException with original error"""
        original = ValueError("Invalid response")
        exc = UploadFailedException("imx", "Upload failed", original_error=original)
        assert exc.service == "imx"
        assert exc.original_error is original

    def test_can_be_raised(self):
        """Test that exception can be raised and caught"""
        with pytest.raises(UploadFailedException) as excinfo:
            raise UploadFailedException("turbo", "Server error")
        assert excinfo.value.service == "turbo"


class TestPluginLoadException:
    """Test PluginLoadException functionality"""

    def test_basic_creation(self):
        """Test creating PluginLoadException"""
        exc = PluginLoadException("pixhost_v2", "Module not found")
        assert exc.plugin_name == "pixhost_v2"
        assert "pixhost_v2" in str(exc)
        assert "Module not found" in str(exc)

    def test_can_be_raised(self):
        """Test that exception can be raised and caught"""
        with pytest.raises(PluginLoadException) as excinfo:
            raise PluginLoadException("bad_plugin", "Syntax error")
        assert excinfo.value.plugin_name == "bad_plugin"


class TestMissingCredentialsException:
    """Test MissingCredentialsException functionality"""

    def test_basic_creation(self):
        """Test creating MissingCredentialsException"""
        exc = MissingCredentialsException("vipr")
        assert exc.service == "vipr"
        assert "vipr" in str(exc)

    def test_different_services(self):
        """Test exception for different services"""
        services = ["pixhost", "imx", "turbo", "imagebam"]
        for service in services:
            exc = MissingCredentialsException(service)
            assert exc.service == service
            assert service in str(exc)


class TestRateLimitException:
    """Test RateLimitException functionality"""

    def test_without_retry_after(self):
        """Test RateLimitException without retry_after"""
        exc = RateLimitException("pixhost")
        assert exc.service == "pixhost"
        assert exc.retry_after is None
        assert "pixhost" in str(exc)

    def test_with_retry_after(self):
        """Test RateLimitException with retry_after"""
        exc = RateLimitException("imx", retry_after=60)
        assert exc.service == "imx"
        assert exc.retry_after == 60
        assert "imx" in str(exc)
        assert "60" in str(exc)

    def test_can_be_raised(self):
        """Test that exception can be raised and caught"""
        with pytest.raises(RateLimitException) as excinfo:
            raise RateLimitException("turbo", retry_after=30)
        assert excinfo.value.service == "turbo"
        assert excinfo.value.retry_after == 30


class TestExceptionMessages:
    """Test that exception messages are helpful"""

    def test_base_exception_message(self):
        """Test base exception message"""
        exc = UploaderException("Something went wrong")
        assert str(exc) == "Something went wrong"

    def test_sidecar_crash_message(self):
        """Test sidecar crash exception message"""
        exc = SidecarCrashException("Process died unexpectedly")
        assert "unexpectedly" in str(exc).lower()

    def test_invalid_file_message(self):
        """Test invalid file exception message"""
        exc = InvalidFileException("File too large")
        assert "large" in str(exc).lower()

    def test_invalid_config_message(self):
        """Test invalid config exception message"""
        exc = InvalidConfigException("Missing required field: username")
        assert "username" in str(exc)


class TestExceptionCatching:
    """Test that exceptions can be caught correctly"""

    def test_catch_specific_exception(self):
        """Test catching specific exception"""
        with pytest.raises(InvalidFileException):
            raise InvalidFileException("Bad file")

    def test_catch_parent_exception(self):
        """Test catching by parent exception class"""
        with pytest.raises(ValidationException):
            raise InvalidFileException("Bad file")

    def test_catch_base_exception(self):
        """Test catching by base exception class"""
        with pytest.raises(UploaderException):
            raise InvalidFileException("Bad file")

    def test_multiple_exception_types(self):
        """Test catching different exception types"""
        for exc_class in [
            SidecarException,
            UploadException,
            ValidationException,
            PluginException,
        ]:
            with pytest.raises(UploaderException):
                raise exc_class("Test error")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
