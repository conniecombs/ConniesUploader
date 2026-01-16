# Plugin Creation Guide

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Protocol Specification](#protocol-specification)
4. [Step-by-Step Guide](#step-by-step-guide)
5. [Examples](#examples)
6. [Best Practices](#best-practices)
7. [Troubleshooting](#troubleshooting)
8. [Testing](#testing)

---

## Overview

Connie's Uploader Ultimate uses a **plugin-driven architecture** where Python plugins define HTTP request specifications and the Go sidecar executes them. This eliminates the need to modify or recompile Go code when adding new image hosting services.

### Key Benefits

- ✅ **Zero Go Changes**: Add services by creating Python plugins only
- ✅ **No Recompilation**: Drop in plugin files and restart
- ✅ **Full Flexibility**: Support any HTTP-based upload API
- ✅ **Session Management**: Multi-step logins, cookies, CSRF tokens
- ✅ **Dynamic Behavior**: Extract values at runtime and use in subsequent requests

### Supported Service Types

| Service Type | Examples | Features |
|--------------|----------|----------|
| **Stateless API** | IMX.to, Pixhost | Simple POST with API keys/headers |
| **Session-Based (Simple)** | Vipr.im | Multi-step login, cookie persistence |
| **Session-Based (Complex)** | ImageBam, TurboImageHost | CSRF tokens, dynamic endpoints, template substitution |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Python Plugin                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  build_http_request(file_path, config, creds)        │   │
│  │  Returns: HttpRequestSpec dict                       │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────┬───────────────────────────────────────┘
                      │ JSON Protocol
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                         Go Sidecar                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  1. Execute pre-request (if specified)               │   │
│  │     - Login to service                               │   │
│  │     - Extract tokens/session IDs/endpoints           │   │
│  │     - Store cookies                                  │   │
│  │                                                      │   │
│  │  2. Build main upload request                        │   │
│  │     - Substitute dynamic fields from extracted values│   │
│  │     - Use session cookies if available               │   │
│  │                                                      │   │
│  │  3. Execute upload                                   │   │
│  │     - Stream file via multipart/form-data            │   │
│  │     - Apply rate limiting                            │   │
│  │                                                      │   │
│  │  4. Parse response                                   │   │
│  │     - Extract image URL and thumbnail URL            │   │
│  │     - Support JSON or HTML responses                 │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Protocol Specification

### HttpRequestSpec (Main Structure)

```python
{
    "url": str,                          # Upload endpoint URL
    "method": str,                       # HTTP method ("POST" or "GET")
    "headers": Dict[str, str],           # HTTP headers
    "pre_request": PreRequestSpec,       # Optional: Login/session setup
    "multipart_fields": Dict[str, MultipartField],  # Upload form fields
    "response_parser": ResponseParserSpec           # How to parse response
}
```

### PreRequestSpec (Session Management)

```python
{
    "action": str,                       # Description (e.g., "login", "get_token")
    "url": str,                          # Request URL
    "method": str,                       # HTTP method
    "headers": Dict[str, str],           # HTTP headers (supports templates)
    "form_fields": Dict[str, str],       # POST body fields (supports templates)
    "use_cookies": bool,                 # Persist cookies for main request
    "extract_fields": Dict[str, str],    # Values to extract (name -> selector/JSONPath)
    "response_type": str,                # "json" or "html"
    "follow_up_request": PreRequestSpec  # Optional: Next request in chain
}
```

**Template Substitution**: Use `{field_name}` in `form_fields` or `headers` to reference values extracted from previous requests.

Example:
```python
"headers": {
    "X-CSRF-TOKEN": "{csrf_token}"  # Substituted with extracted value
}
```

### MultipartField

```python
{
    "type": str,    # "file", "text", or "dynamic"
    "value": str    # For "file": ignored (uses job file)
                    # For "text": the literal value
                    # For "dynamic": reference to extracted field name
}
```

**Field Types**:
- `"file"`: Streams the uploaded file (always use `"type": "file"` for the image field)
- `"text"`: Static value (e.g., API key, configuration option)
- `"dynamic"`: Runtime value extracted from pre-request (e.g., session ID, upload token)

Example:
```python
"multipart_fields": {
    "image": {"type": "file", "value": file_path},
    "api_key": {"type": "text", "value": "your-api-key"},
    "session_id": {"type": "dynamic", "value": "sess_id"}  # From pre-request
}
```

### ResponseParserSpec

```python
{
    "type": str,                  # "json" or "html"
    "url_path": str,              # JSONPath or CSS selector for image URL
    "thumb_path": str,            # JSONPath or CSS selector for thumbnail URL
    "status_path": str,           # Optional: JSONPath for status field
    "success_value": str,         # Optional: Expected success value
    "url_template": str,          # Optional: Template to construct URL (e.g., "https://example.com/p/{id}/{filename}.html")
    "thumb_template": str         # Optional: Template to construct thumbnail URL
}
```

**Extraction Methods**:

1. **JSON (JSONPath)**: Dot notation to navigate nested JSON
   ```python
   "url_path": "data.image_url"      # Extracts data["image_url"]
   "url_path": "files.0.sourceUrl"   # Extracts files[0]["sourceUrl"]
   ```

2. **HTML (CSS Selectors)**: Standard CSS selectors
   ```python
   "url_path": "input[name='link_url']"  # Extracts value attribute
   "thumb_path": "img.thumbnail"          # Extracts src attribute or text
   ```

3. **HTML (Regex)**: For extracting from JavaScript or complex HTML
   ```python
   "extract_fields": {
       "endpoint": "regex:endpoint:\\s*'([^']+)'"  # First capture group
   }
   ```

4. **URL Templates**: Construct URLs from response data
   ```python
   "url_template": "https://example.com/p/{id}/{filename}.html"
   # Substitutes {id} from JSON response, {filename} from uploaded file
   ```

---

## Step-by-Step Guide

### Step 1: Create Plugin File

Create a new file in `modules/plugins/` named after your service:

```bash
touch modules/plugins/yourservice.py
```

### Step 2: Basic Plugin Structure

```python
from typing import Dict, Any, List
from .base import ImageHostPlugin

class YourServicePlugin(ImageHostPlugin):
    """Your Service image hosting plugin."""

    @property
    def id(self) -> str:
        return "yourservice.com"

    @property
    def name(self) -> str:
        return "Your Service"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "version": "1.0.0",
            "author": "Your Name",
            "description": "Upload images to Your Service",
            "website": "https://yourservice.com",
            "implementation": "go",  # Uses Go sidecar
            "features": {
                "galleries": False,
                "covers": False,
                "authentication": "required",  # or "optional", "none"
                "direct_links": True,
                "custom_thumbnails": True,
            },
            "credentials": [
                {
                    "key": "yourservice_api_key",
                    "label": "API Key",
                    "required": True,
                    "secret": True,
                    "description": "Your Service API key"
                }
            ],
            "limits": {
                "max_file_size": 10 * 1024 * 1024,  # 10MB
                "allowed_formats": [".jpg", ".jpeg", ".png"],
                "rate_limit": "API rate limited",
            }
        }

    @property
    def settings_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "dropdown",
                "key": "quality",
                "label": "Quality",
                "values": ["low", "medium", "high"],
                "default": "high",
                "required": True
            }
        ]

    def build_http_request(self, file_path: str, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
        """Build HTTP request specification for Your Service upload."""
        # Implementation goes here (see examples below)
        pass

    # Stub methods (required by base class)
    def initialize_session(self, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def upload_file(self, file_path: str, group, config: Dict[str, Any], context: Dict[str, Any], progress_callback):
        pass
```

### Step 3: Implement build_http_request()

This is the core method. See examples below for different service types.

### Step 4: Register Plugin

Add your plugin to `modules/plugins/__init__.py`:

```python
from .yourservice import YourServicePlugin

# Add to the imports and ensure it's registered in the plugin manager
```

### Step 5: Test

1. Restart the application
2. Configure credentials (if needed)
3. Select your service and upload a test image
4. Check logs for any errors

---

## Examples

### Example 1: Simple Stateless API (IMX-style)

**Service**: Simple POST to API endpoint with API key in header.

```python
def build_http_request(self, file_path: str, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
    """Simple stateless API with API key authentication."""
    return {
        "url": "https://api.example.com/v1/upload",
        "method": "POST",
        "headers": {
            "X-API-KEY": creds.get("example_api_key", "")
        },
        "multipart_fields": {
            "image": {"type": "file", "value": file_path},
            "quality": {"type": "text", "value": config.get("quality", "high")},
            "public": {"type": "text", "value": "1"}
        },
        "response_parser": {
            "type": "json",
            "url_path": "data.url",
            "thumb_path": "data.thumbnail",
            "status_path": "status",
            "success_value": "success"
        }
    }
```

**Response Example**:
```json
{
    "status": "success",
    "data": {
        "url": "https://example.com/i/abc123.jpg",
        "thumbnail": "https://example.com/t/abc123_thumb.jpg"
    }
}
```

---

### Example 2: Two-Step Login (Vipr-style)

**Service**: POST credentials → GET homepage to extract session ID → Upload with session

```python
def build_http_request(self, file_path: str, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
    """Two-step login with cookie persistence."""
    import random, string
    upload_id = ''.join(random.choices(string.ascii_letters + string.digits, k=12))

    return {
        "url": f"https://example.com/upload.cgi?upload_id={upload_id}",
        "method": "POST",
        "headers": {},
        "pre_request": {
            "action": "login_step1",
            "url": "https://example.com/login",
            "method": "POST",
            "headers": {},
            "form_fields": {
                "username": creds.get("example_user", ""),
                "password": creds.get("example_pass", "")
            },
            "use_cookies": True,  # Persist cookies
            "extract_fields": {},  # No extraction from POST
            "response_type": "html",
            # Step 2: GET homepage to extract session ID
            "follow_up_request": {
                "action": "login_step2",
                "url": "https://example.com/",
                "method": "GET",
                "headers": {},
                "form_fields": {},
                "use_cookies": True,  # Use cookies from step 1
                "extract_fields": {
                    "session_id": "input[name='session_id']"  # CSS selector
                },
                "response_type": "html"
            }
        },
        "multipart_fields": {
            "file": {"type": "file", "value": file_path},
            "session_id": {"type": "dynamic", "value": "session_id"}  # From pre-request
        },
        "response_parser": {
            "type": "html",
            "url_path": "input[name='image_url']",
            "thumb_path": "input[name='thumb_url']"
        }
    }
```

---

### Example 3: Complex CSRF Login (ImageBam-style)

**Service**: 4-step login with CSRF tokens and template substitution

```python
def build_http_request(self, file_path: str, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
    """Complex 4-step login with CSRF and template substitution."""

    return {
        "url": "https://example.com/upload",
        "method": "POST",
        "headers": {},
        "pre_request": {
            # Step 1: GET login page to extract CSRF token
            "action": "get_login_csrf",
            "url": "https://example.com/login",
            "method": "GET",
            "headers": {},
            "form_fields": {},
            "use_cookies": True,
            "extract_fields": {
                "login_token": "input[name='_token']"
            },
            "response_type": "html",
            # Step 2: POST login with CSRF
            "follow_up_request": {
                "action": "submit_login",
                "url": "https://example.com/login",
                "method": "POST",
                "headers": {},
                "form_fields": {
                    "_token": "{login_token}",  # Template substitution
                    "email": creds.get("example_user", ""),
                    "password": creds.get("example_pass", "")
                },
                "use_cookies": True,
                "extract_fields": {},
                "response_type": "html",
                # Step 3: GET API CSRF token
                "follow_up_request": {
                    "action": "get_api_csrf",
                    "url": "https://example.com/",
                    "method": "GET",
                    "headers": {},
                    "form_fields": {},
                    "use_cookies": True,
                    "extract_fields": {
                        "csrf_token": "meta[name='csrf-token']"
                    },
                    "response_type": "html",
                    # Step 4: POST to get upload token
                    "follow_up_request": {
                        "action": "get_upload_token",
                        "url": "https://example.com/upload/session",
                        "method": "POST",
                        "headers": {
                            "X-CSRF-TOKEN": "{csrf_token}",  # Template in header
                            "X-Requested-With": "XMLHttpRequest"
                        },
                        "form_fields": {
                            "quality": config.get("quality", "high")
                        },
                        "use_cookies": True,
                        "extract_fields": {
                            "upload_token": "token"  # Extract from JSON
                        },
                        "response_type": "json"
                    }
                }
            }
        },
        "multipart_fields": {
            "file": {"type": "file", "value": file_path},
            "upload_session": {"type": "dynamic", "value": "upload_token"}
        },
        "response_parser": {
            "type": "json",
            "url_path": "data.url",
            "thumb_path": "data.thumb"
        }
    }
```

---

### Example 4: Regex Extraction + URL Templates (Turbo-style)

**Service**: Extract endpoint from JavaScript, construct URL from response

```python
def build_http_request(self, file_path: str, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
    """Regex extraction and URL template construction."""
    import random, string
    upload_id = ''.join(random.choices(string.ascii_letters + string.digits, k=12))

    return {
        "url": f"https://example.com/upload.php?id={upload_id}",
        "method": "POST",
        "headers": {},
        "pre_request": {
            "action": "get_endpoint",
            "url": "https://example.com/",
            "method": "GET",
            "headers": {},
            "form_fields": {},
            "use_cookies": True,
            "extract_fields": {
                # Regex extraction from JavaScript
                "endpoint": "regex:uploadEndpoint\\s*=\\s*['\"]([^'\"]+)['\"]"
            },
            "response_type": "html"
        },
        "multipart_fields": {
            "file": {"type": "file", "value": file_path}
        },
        "response_parser": {
            "type": "json",
            "status_path": "success",
            "success_value": "true",
            # Construct URL from response fields
            "url_template": "https://example.com/i/{id}/{filename}",
            "thumb_template": "https://example.com/t/{id}_thumb.jpg"
        }
    }
```

**Response Example**:
```json
{
    "success": true,
    "id": "abc123"
}
```

**Constructed URLs**:
- Image: `https://example.com/i/abc123/photo.jpg`
- Thumb: `https://example.com/t/abc123_thumb.jpg`

---

### Example 5: Optional Authentication

**Service**: Support both anonymous and authenticated uploads

```python
def build_http_request(self, file_path: str, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
    """Support optional authentication."""
    has_credentials = bool(creds.get("example_user") and creds.get("example_pass"))

    # Build pre-request only if credentials provided
    pre_request_spec = None
    if has_credentials:
        pre_request_spec = {
            "action": "login",
            "url": "https://example.com/login",
            "method": "POST",
            "headers": {},
            "form_fields": {
                "username": creds.get("example_user", ""),
                "password": creds.get("example_pass", "")
            },
            "use_cookies": True,
            "extract_fields": {
                "auth_token": "token"
            },
            "response_type": "json"
        }

    # Build multipart fields
    multipart_fields = {
        "file": {"type": "file", "value": file_path}
    }

    # Add auth token if authenticated
    if has_credentials:
        multipart_fields["auth_token"] = {"type": "dynamic", "value": "auth_token"}

    return {
        "url": "https://example.com/upload",
        "method": "POST",
        "headers": {},
        "pre_request": pre_request_spec,  # None for anonymous
        "multipart_fields": multipart_fields,
        "response_parser": {
            "type": "json",
            "url_path": "url",
            "thumb_path": "thumb"
        }
    }
```

---

## Best Practices

### 1. Error Handling

The Go sidecar provides automatic error handling, but ensure your plugin returns valid data:

```python
# ✅ Good: Provide defaults for missing config
thumb_size = config.get("thumbnail_size", "180")

# ✅ Good: Validate credentials before building spec
if not creds.get("api_key"):
    # Plugin manager will catch this and show error to user
    raise ValueError("API key is required")

# ❌ Bad: Assuming keys exist
thumb_size = config["thumbnail_size"]  # KeyError if missing
```

### 2. Cookie Persistence

Use `"use_cookies": True` in pre-requests to maintain session:

```python
"pre_request": {
    "use_cookies": True,  # ✅ Cookies persist to main upload
    # ...
}
```

Without this, each request uses a fresh session.

### 3. Template Substitution

Always use `{placeholder}` syntax for dynamic values:

```python
# ✅ Good: Template substitution
"form_fields": {
    "_token": "{csrf_token}"  # Substituted from extracted value
}

# ❌ Bad: Manual concatenation (won't work)
"form_fields": {
    "_token": extracted_values["csrf_token"]  # Not available in plugin
}
```

### 4. Regex Extraction

Use `regex:` prefix for regex patterns in HTML extraction:

```python
"extract_fields": {
    "endpoint": "regex:endpoint:\\s*'([^']+)'"  # ✅ Regex pattern
}

# Not:
"extract_fields": {
    "endpoint": "endpoint:\\s*'([^']+)'"  # ❌ Won't work (treated as CSS selector)
}
```

### 5. Dynamic Fields

Reference extracted field names, not paths:

```python
"extract_fields": {
    "my_token": "data.token"  # Extracts from JSON path
},
"multipart_fields": {
    "token": {"type": "dynamic", "value": "my_token"}  # ✅ References field name
}

# Not:
"multipart_fields": {
    "token": {"type": "dynamic", "value": "data.token"}  # ❌ Won't work
}
```

### 6. Response Parser Selection

Choose the right parser type:

```python
# JSON Response: {"url": "...", "thumb": "..."}
"response_parser": {
    "type": "json",
    "url_path": "url",
    "thumb_path": "thumb"
}

# HTML Response: <input name="url" value="...">
"response_parser": {
    "type": "html",
    "url_path": "input[name='url']",
    "thumb_path": "input[name='thumb']"
}
```

### 7. Rate Limiting

Rate limiting is handled automatically by the Go sidecar. Configure in `uploader.go`:

```go
var rateLimiters = map[string]*rate.Limiter{
    "yourservice.com": rate.NewLimiter(rate.Limit(2.0), 5),  // 2 req/s
}
```

---

## Troubleshooting

### Issue: "pre-request failed: no URL found"

**Cause**: CSS selector or JSONPath didn't match response.

**Solution**:
1. Check the actual HTML/JSON response from the service
2. Test your selector/path with a browser console or JSON viewer
3. Use regex extraction if CSS selectors are unreliable

```python
# Instead of:
"extract_fields": {
    "token": "input[name='token']"  # Might not match
}

# Try:
"extract_fields": {
    "token": "regex:token['\"]\\s*:\\s*['\"]([^'\"]+)['\"]"
}
```

### Issue: "dynamic field references unknown extracted value"

**Cause**: Referenced field wasn't extracted in pre-request.

**Solution**: Verify field name matches exactly:

```python
# Pre-request
"extract_fields": {
    "session_id": "input[name='sess_id']"  # Field name: session_id
}

# Main request
"multipart_fields": {
    "sess_id": {"type": "dynamic", "value": "session_id"}  # ✅ Matches
}
```

### Issue: "upload failed with status: error"

**Cause**: Service returned error status.

**Solution**: Check response parser configuration:

```python
"response_parser": {
    "type": "json",
    "status_path": "status",        # Path to status field
    "success_value": "success",     # Expected value
    "url_path": "data.url"
}
```

If status != success_value, Go sidecar returns the error message.

### Issue: URLs contain {placeholders}

**Cause**: Template substitution failed (field not in response).

**Solution**: Verify response contains the fields referenced in template:

```python
# Response: {"id": "abc123", "name": "photo"}
"url_template": "https://example.com/i/{id}/{filename}"  # ✅ {id} exists
"url_template": "https://example.com/i/{photo_id}/{filename}"  # ❌ {photo_id} doesn't exist
```

### Issue: "Cookies not persisting"

**Cause**: `"use_cookies": false` or missing.

**Solution**: Set to `true` in all pre-request steps:

```python
"pre_request": {
    "use_cookies": True,  # ✅ Essential for session
    # ...
}
```

### Issue: "Connection reset" or "Rate limit exceeded"

**Cause**: Service is blocking or rate limiting.

**Solution**:
1. Add longer delays between requests (configure rate limiter in Go)
2. Verify User-Agent is set (done automatically by Go)
3. Check if service requires additional headers

---

## Testing

### Manual Testing

1. **Enable Debug Logging**: Check Go sidecar logs for detailed request/response info
   ```
   tail -f uploader.log
   ```

2. **Test with Single File**: Upload one file first to verify plugin works

3. **Check Response**: Verify service returns expected format

4. **Test Edge Cases**:
   - Missing credentials
   - Invalid credentials
   - Large files
   - Special characters in filename

### Automated Testing

Create a test script:

```python
# test_plugin.py
import sys
sys.path.insert(0, '/path/to/GolangVersion')

from modules.plugins.yourservice import YourServicePlugin

plugin = YourServicePlugin()
config = {"quality": "high"}
creds = {"yourservice_api_key": "test-key"}

# Test plugin
try:
    spec = plugin.build_http_request("/tmp/test.jpg", config, creds)
    print("✅ Plugin builds valid spec")
    print(f"URL: {spec['url']}")
    print(f"Method: {spec['method']}")
    print(f"Fields: {list(spec['multipart_fields'].keys())}")
except Exception as e:
    print(f"❌ Plugin failed: {e}")
```

### Validation Checklist

- [ ] Plugin file created in `modules/plugins/`
- [ ] Class inherits from `ImageHostPlugin`
- [ ] `id` property returns unique service ID
- [ ] `metadata` includes all required fields
- [ ] `build_http_request()` returns valid `HttpRequestSpec`
- [ ] Pre-request chain uses `"use_cookies": True`
- [ ] Dynamic fields reference correct extracted field names
- [ ] Response parser type matches service response format
- [ ] Tested with valid credentials
- [ ] Tested without credentials (if optional auth)
- [ ] Tested with sample file upload
- [ ] Verified URLs are correctly extracted

---

## Advanced Topics

### Custom Response Parsing

If service returns non-standard response, use regex or template tricks:

```python
# Service returns: {"data": {"images": [{"url": "...", "thumb": "..."}]}}
"response_parser": {
    "type": "json",
    "url_path": "data.images.0.url",      # Array access with .0
    "thumb_path": "data.images.0.thumb"
}
```

### Multi-File Upload

Current protocol supports single-file upload. For batch uploads, the plugin is called once per file automatically.

### Custom Headers

Add service-specific headers:

```python
"headers": {
    "X-API-Version": "2.0",
    "Accept": "application/json",
    "Referer": "https://example.com/"
}
```

### Endpoint Discovery

Some services provide upload endpoints dynamically:

```python
"pre_request": {
    "extract_fields": {
        "upload_url": "meta[name='upload-endpoint']"  # Extract dynamic URL
    }
}

# Then use in main request (requires modifying URL field dynamically - not yet supported)
# Workaround: Extract endpoint components and use in form fields
```

---

## Summary

**Creating a plugin is as simple as**:

1. Create `modules/plugins/yourservice.py`
2. Implement `build_http_request()` method
3. Return a dictionary following the protocol specification
4. Test with a sample upload

**No Go changes. No recompilation. Pure Python.**

For questions or issues, consult:
- This guide
- `ARCHITECTURE.md` for system design
- Example plugins: `imx.py`, `pixhost.py`, `vipr.py`, `turbo.py`, `imagebam.py`

---

**Version**: 2.4.0
**Last Updated**: 2026-01-09
