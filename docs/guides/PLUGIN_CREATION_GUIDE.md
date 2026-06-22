# Plugin Creation Guide

This guide explains how to add or maintain image-host plugins in Connie's Uploader Ultimate.

The current plugin model is Python-first. A plugin describes service settings and upload HTTP requests, then the bundled Go sidecar executes those requests concurrently. Most new services should not require Go changes.

## When To Use This Guide

Use this guide when you want to:

- Add a new image-host service.
- Update an existing service plugin.
- Add service-specific settings.
- Add gallery creation/finalization support.
- Debug generic HTTP runner request specs.

For the declarative UI field format only, see [Schema Plugin Guide](SCHEMA_PLUGIN_GUIDE.md).

## Current Architecture

```text
modules/plugins/<service>.py
  -> ImageHostPlugin metadata/settings_schema/validation
  -> build_http_request()
  -> UploadManager sends http_spec to Go sidecar
  -> Go sidecar executes upload and parses response
  -> Python generates output templates and optional ViperGirls posts
```

The Go sidecar supports:

- Multipart uploads.
- Pre-request and follow-up request chains.
- Cookie sessions.
- Dynamic values extracted from earlier responses.
- Header/form/body template substitution.
- JSON path extraction, including arrays such as `files.0.url`.
- HTML CSS selector extraction.
- Regex extraction with `regex:` selectors.
- URL and thumbnail templates.
- Relative/dynamic endpoint resolution through extracted `endpoint` values.
- Retry and rate limiting.
- Correlated request IDs so concurrent uploads do not consume the wrong result.

## Active Plugin Examples

Current active plugins:

- `modules/plugins/imagebam.py`
- `modules/plugins/imgur.py`
- `modules/plugins/imx.py`
- `modules/plugins/pixhost.py`
- `modules/plugins/turbo.py`
- `modules/plugins/vipr.py`

There is also a legacy Pixhost file ending in `_legacy`; the plugin manager intentionally skips `_legacy` modules.

## Plugin Discovery

Plugins are discovered automatically by `modules/plugin_manager.py` using `pkgutil.iter_modules(modules.plugins.__path__)`.

You do not need to edit `modules/plugins/__init__.py`; that file is not required for registering plugins.

The plugin manager skips:

- `base`
- `helpers`
- `schema_renderer`
- modules ending in `_legacy`

After adding a plugin file, restart the app or reload plugins in tests.

## Minimal Plugin

```python
from typing import Any, Dict, List

from .base import ImageHostPlugin


class ExamplePlugin(ImageHostPlugin):
    @property
    def id(self) -> str:
        return "example.com"

    @property
    def name(self) -> str:
        return "Example"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "version": "1.0.0",
            "author": "Your Name",
            "description": "Upload images to Example",
            "website": "https://example.com",
            "implementation": "go",
            "features": {
                "galleries": False,
                "covers": False,
                "authentication": "required",
                "direct_links": True,
                "custom_thumbnails": True,
            },
            "credentials": [
                {
                    "key": "example_api_key",
                    "label": "API Key",
                    "required": True,
                    "secret": True,
                    "description": "Example API key",
                }
            ],
            "limits": {
                "max_file_size": 10 * 1024 * 1024,
                "allowed_formats": [".jpg", ".jpeg", ".png", ".gif", ".webp"],
                "rate_limit": "Sidecar rate limited",
            },
        }

    @property
    def settings_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "dropdown",
                "key": "thumbnail_size",
                "label": "Thumbnail Size",
                "values": ["150", "250", "500"],
                "default": "250",
                "required": True,
                "help": "Host thumbnail size in pixels.",
            }
        ]

    def validate_configuration(self, config: Dict[str, Any]) -> List[str]:
        errors = []
        if config.get("thumbnail_size") not in {"150", "250", "500"}:
            errors.append("Thumbnail Size must be one of 150, 250, or 500.")
        return errors

    def build_http_request(
        self,
        file_path: str,
        config: Dict[str, Any],
        creds: Dict[str, Any],
    ) -> Dict[str, Any]:
        api_key = creds.get("example_api_key", "")
        if not api_key:
            raise ValueError("Example API Key is required.")

        return {
            "url": "https://api.example.com/upload",
            "method": "POST",
            "headers": {
                "X-API-Key": api_key,
            },
            "multipart_fields": {
                "file": {"type": "file", "value": file_path},
                "thumbnail_size": {
                    "type": "text",
                    "value": str(config.get("thumbnail_size", "250")),
                },
            },
            "response_parser": {
                "type": "json",
                "url_path": "data.viewer_url",
                "thumb_path": "data.thumb_url",
                "status_path": "status",
                "success_value": "success",
            },
        }

    def initialize_session(self, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def upload_file(self, file_path, group, config, context, progress_callback):
        raise NotImplementedError("This plugin uses build_http_request().")
```

`initialize_session()` and `upload_file()` are still abstract base-class methods. For generic-runner plugins, keep them as stubs because the upload path is `build_http_request()`.

## Metadata

Metadata is used for user guidance, validation, feature detection, and diagnostics.

Recommended fields:

```python
{
    "version": "1.0.0",
    "author": "Maintainer",
    "description": "Upload images to Service",
    "website": "https://service.example",
    "implementation": "go",
    "priority": 50,
    "features": {
        "galleries": True,
        "covers": True,
        "authentication": "required",
        "direct_links": True,
        "custom_thumbnails": True,
    },
    "credentials": [
        {
            "key": "service_user",
            "label": "Username",
            "required": True,
            "secret": False,
        },
        {
            "key": "service_pass",
            "label": "Password",
            "required": True,
            "secret": True,
        },
    ],
    "limits": {
        "max_file_size": 50 * 1024 * 1024,
        "allowed_formats": [".jpg", ".jpeg", ".png", ".gif", ".webp"],
        "rate_limit": "2 requests/second",
    },
}
```

Credential keys should be stable because they map to system keyring entries.

## Settings Schema

Use `settings_schema` for service settings instead of manually drawing widgets.

Common fields:

```python
[
    {
        "type": "dropdown",
        "key": "content_type",
        "label": "Content Type",
        "values": ["Safe", "Adult"],
        "default": "Safe",
        "required": True,
        "help": "Host-side content category.",
    },
    {
        "type": "dropdown",
        "key": "thumbnail_size",
        "label": "Thumbnail Size",
        "values": ["150", "250", "500"],
        "default": "250",
    },
    {
        "type": "number",
        "key": "cover_count",
        "label": "Auto Covers",
        "min": 0,
        "max": 10,
        "default": 0,
    },
    {
        "type": "checkbox",
        "key": "save_links",
        "label": "Save Links.txt",
        "default": False,
    },
    {
        "type": "text",
        "key": "gallery_id",
        "label": "Gallery ID",
        "default": "",
        "placeholder": "Optional",
    },
]
```

The schema renderer handles layout, defaults, extraction, validation, and tooltips from `help` text.

## HTTP Request Spec

`build_http_request()` returns a dictionary matching the Go `HttpRequestSpec` shape.

```python
{
    "url": "https://example.com/upload",
    "method": "POST",
    "headers": {},
    "pre_request": None,
    "multipart_fields": {
        "file": {"type": "file", "value": file_path},
    },
    "response_parser": {
        "type": "json",
        "url_path": "url",
        "thumb_path": "thumb",
    },
}
```

Supported top-level fields:

| Field | Purpose |
| --- | --- |
| `url` | Upload endpoint. Supports `{placeholder}` substitution. |
| `method` | Usually `POST`; defaults are handled by the sidecar when omitted. |
| `headers` | Request headers. Values support `{placeholder}` substitution. |
| `pre_request` | Optional login/session/token setup. |
| `multipart_fields` | File/text/dynamic fields for the multipart upload. |
| `response_parser` | How the sidecar extracts final image and thumbnail URLs. |

## Pre-Requests

Use pre-requests for login, cookies, CSRF tokens, upload tokens, or dynamic endpoints.

```python
"pre_request": {
    "action": "get_login_page",
    "url": "https://example.com/login",
    "method": "GET",
    "headers": {},
    "form_fields": {},
    "use_cookies": True,
    "extract_fields": {
        "csrf_token": "input[name='_token']",
    },
    "response_type": "html",
    "follow_up_request": {
        "action": "submit_login",
        "url": "https://example.com/login",
        "method": "POST",
        "headers": {},
        "form_fields": {
            "_token": "{csrf_token}",
            "username": creds.get("example_user", ""),
            "password": creds.get("example_pass", ""),
        },
        "use_cookies": True,
        "extract_fields": {
            "upload_token": "token",
        },
        "response_type": "json",
    },
}
```

Values extracted from one pre-request are available to later follow-up requests, headers, form fields, multipart fields, and the upload URL.

Use `"use_cookies": True` for every request in a login/session chain that should share cookies.

## Multipart Fields

Supported field types:

| Type | Meaning |
| --- | --- |
| `file` | Streams the upload file. |
| `text` | Sends literal text after placeholder substitution. |
| `dynamic` | Sends an extracted value by key, falling back to placeholder substitution. |

Example:

```python
"multipart_fields": {
    "file": {"type": "file", "value": file_path},
    "folder_id": {"type": "text", "value": config.get("gallery_id", "")},
    "upload_token": {"type": "dynamic", "value": "upload_token"},
}
```

## Response Parsing

JSON response:

```python
"response_parser": {
    "type": "json",
    "status_path": "status",
    "success_value": "success",
    "url_path": "data.image_url",
    "thumb_path": "data.thumbnail_url",
}
```

HTML response:

```python
"response_parser": {
    "type": "html",
    "url_path": "input[name='link_url']",
    "thumb_path": "input[name='thumb_url']",
}
```

Regex extraction:

```python
"extract_fields": {
    "endpoint": "regex:uploadEndpoint\\s*=\\s*['\"]([^'\"]+)['\"]",
}
```

Malformed regex patterns return an error from the sidecar instead of panicking.

URL templates:

```python
"response_parser": {
    "type": "json",
    "url_template": "https://example.com/i/{id}/{filename}",
    "thumb_template": "https://example.com/t/{id}_{basename}.jpg",
}
```

Template tokens can come from JSON data or file information:

- `{filename}`
- `{basename}`
- `{ext}`
- `{extension}`
- `{dot_ext}`

## Dynamic Endpoints

If a pre-request extracts a value named `endpoint`, the sidecar can resolve it against the upload URL.

```python
"pre_request": {
    "action": "discover_endpoint",
    "url": "https://example.com/",
    "method": "GET",
    "use_cookies": True,
    "extract_fields": {
        "endpoint": "form#uploadForm",
    },
    "response_type": "html",
},
"url": "https://example.com/upload?upload_id={upload_id}",
```

If `endpoint` is relative, Go resolves it against the configured upload URL and preserves the upload query string when appropriate.

You can also reference a dynamic value directly in the upload URL:

```python
"url": "{upload_url}",
```

## Gallery Hooks

Use `prepare_group()` when a plugin needs per-batch gallery setup before files upload.

Typical examples:

- Create one gallery per folder.
- Resolve a configured gallery name into an upload hash.
- Store gallery context for all files in the batch.

Use `finalize_batch()` when a service needs post-upload work. Pixhost gallery finalization is the main current example.

Gallery list/create UI should return normalized records through the gallery service layer rather than making the Gallery Manager parse host HTML directly.

## Covers

Cover behavior has two layers:

- Service settings can auto-select the first N files as covers.
- Users can manually mark one or more files as covers in the queue.

Template output can use:

- `#cover_image#` for the next selected cover each time it appears.
- `#cover_images#` for all selected covers.
- `[for cover]...[/for]` for custom per-cover output.
- `#cover_count#` for the number of selected covers.

Upload code applies host-specific maximum thumbnail settings for selected covers so generated cover BBCode can use the largest supported host thumbnail while normal images keep the user-selected thumbnail size.

## Error Handling

Do:

```python
api_key = creds.get("example_api_key", "")
if not api_key:
    raise ValueError("Example API Key is required.")
```

Do:

```python
thumb_size = str(config.get("thumbnail_size", "250"))
```

Avoid:

```python
thumb_size = config["thumbnail_size"]
```

User-facing errors should explain the action the user can take: set credentials, choose a gallery, reduce file size, retry later, or check the host response.

## Tests

Add focused tests instead of relying only on live uploads.

Useful test targets:

- Plugin discovery loads the new plugin.
- Metadata includes expected features and credentials.
- Schema renders/extracts expected keys.
- Validation reports missing credentials/config.
- `build_http_request()` returns the right URL, headers, multipart fields, pre-request chain, and response parser.
- Gallery create/list behavior normalizes records and distinguishes empty, missing credentials, login failure, parse failure, and unsupported service states.
- Cover settings and thumbnail overrides behave correctly.

Run:

```bash
pytest tests/ -v
go test ./...
go vet ./...
```

For packaging-sensitive plugin changes, also verify the build contract:

```bash
pytest tests/test_build_contract.py -v
```

## Manual Debugging

1. Run from source with a built sidecar.

```bash
go build -ldflags="-s -w" -o uploader .
python main.py
```

On Windows:

```powershell
go build -ldflags="-s -w" -o uploader.exe .
python main.py
```

2. Open `View > Execution Log`.
3. Upload one small file.
4. Verify the plugin loaded in the startup log.
5. Verify the sidecar emitted progress/result/error events.
6. If using sessions, test invalid credentials before testing valid credentials.

## Packaging Notes

The build scripts collect plugins with:

```text
--collect-submodules modules.plugins
```

and keep explicit hidden imports for the active plugin modules:

```text
modules.plugins.imx
modules.plugins.pixhost
modules.plugins.vipr
modules.plugins.turbo
modules.plugins.imagebam
modules.plugins.imgur
```

If you add a new active plugin, update the build scripts, release workflow, and build-contract tests so packaged releases include it.

## Checklist

- [ ] Plugin file added under `modules/plugins/`.
- [ ] Class inherits from `ImageHostPlugin`.
- [ ] `id` is unique and stable.
- [ ] `metadata` describes credentials, features, and limits.
- [ ] `settings_schema` uses current schema fields.
- [ ] `validate_configuration()` covers service-specific rules.
- [ ] `build_http_request()` works for one-file uploads.
- [ ] Gallery hooks are implemented if the service supports galleries.
- [ ] Cover behavior is tested if the service supports covers.
- [ ] Missing/invalid credentials produce clear errors.
- [ ] Tests cover request shape and validation.
- [ ] Build scripts/workflows include the plugin if it should ship.
- [ ] README/user docs are updated for user-visible service behavior.

## Related Docs

- [Schema Plugin Guide](SCHEMA_PLUGIN_GUIDE.md)
- [Architecture](../ARCHITECTURE.md)
- [Build Troubleshooting](BUILD_TROUBLESHOOTING.md)
- [Repository Layout](REPOSITORY_LAYOUT.md)

- **Guide Version:** 2.6.0
- **Last Updated:** 2026-06-21
