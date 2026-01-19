# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Custom exception classes for Connie's Uploader Ultimate."""


class UploaderException(Exception):
    """Base exception for all uploader errors."""

    pass


class SidecarException(UploaderException):
    """Exceptions related to Go sidecar process."""

    pass


class SidecarCrashException(SidecarException):
    """Raised when sidecar process crashes and cannot restart."""

    pass


class SidecarNotFoundError(SidecarException):
    """Raised when sidecar binary cannot be found."""

    pass


class UploadException(UploaderException):
    """Exceptions related to upload operations."""

    pass


class UploadFailedException(UploadException):
    """Raised when an upload fails."""

    def __init__(self, service: str, message: str, original_error=None):
        self.service = service
        self.original_error = original_error
        super().__init__(f"{service}: {message}")


class ValidationException(UploaderException):
    """Exceptions related to input validation."""

    pass


class InvalidFileException(ValidationException):
    """Raised when a file is invalid (wrong type, too large, corrupted)."""

    pass


class InvalidServiceException(ValidationException):
    """Raised when an invalid service name is provided."""

    pass


class PluginException(UploaderException):
    """Exceptions related to plugin system."""

    pass


class PluginLoadException(PluginException):
    """Raised when a plugin fails to load."""

    def __init__(self, plugin_name: str, message: str):
        self.plugin_name = plugin_name
        super().__init__(f"Failed to load plugin '{plugin_name}': {message}")


class ConfigException(UploaderException):
    """Exceptions related to configuration."""

    pass


class InvalidConfigException(ConfigException):
    """Raised when configuration is invalid."""

    pass


class CredentialsException(UploaderException):
    """Exceptions related to credentials management."""

    pass


class MissingCredentialsException(CredentialsException):
    """Raised when required credentials are missing."""

    def __init__(self, service: str):
        self.service = service
        super().__init__(f"Missing credentials for service: {service}")


class NetworkException(UploaderException):
    """Exceptions related to network operations."""

    pass


class RateLimitException(NetworkException):
    """Raised when rate limit is exceeded."""

    def __init__(self, service: str, retry_after=None):
        self.service = service
        self.retry_after = retry_after
        msg = f"Rate limit exceeded for {service}"
        if retry_after:
            msg += f" (retry after {retry_after}s)"
        super().__init__(msg)
