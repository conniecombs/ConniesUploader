# Phase 5: Helper Utilities - Pattern Analysis

## Common Patterns Identified

### 1. Configuration Validation Patterns

**Cover Count Conversion** (Used in 4 plugins):
```python
# pixhost.py, turbo.py, imx.py, vipr.py
try:
    config["cover_limit"] = int(config.get("cover_count", 0))
except (ValueError, TypeError):
    errors.append("Cover count must be a valid number")
```

**Gallery Hash/ID Validation**:
```python
# pixhost.py
if gallery_hash and not gallery_hash.isalnum():
    errors.append("Gallery hash must contain only letters and numbers")
```

### 2. Upload Context Patterns

**Client Creation** (Used in 4 plugins):
```python
# pixhost.py, turbo.py, imagebam.py, imgur.py
client = api.create_resilient_client()
context = {"client": client, ...}
```

**Cover Image Detection** (Used in 3 plugins):
```python
# pixhost.py, turbo.py
is_cover = False
if hasattr(group, "files"):
    try:
        idx = group.files.index(file_path)
        if idx < config.get("cover_limit", 0):
            is_cover = True
    except ValueError:
        logger.debug(f"File not found in group files")
```

### 3. Progress Callback Patterns

**Lambda Progress Wrapper** (Used in 5 plugins):
```python
lambda m: progress_callback(m.bytes_read / m.len) if m.len > 0 else None
```

### 4. Error Handling Patterns

**Upload Try/Except** (Used in all plugins):
```python
try:
    url, data, headers = uploader.get_request_params()
    if "Content-Length" not in headers and hasattr(data, "len"):
        headers["Content-Length"] = str(data.len)
    r = client.post(url, headers=headers, data=data, timeout=300)
    return uploader.parse_response(r.json())
except Exception as e:
    logger.error(f"Upload error: {e}")
    raise
```

### 5. Credential Validation Patterns

**API Key Validation**:
```python
# imx.py - checks for required credentials
if not creds.get("imx_api"):
    logger.warning("No API key provided")
```

## Proposed Helper Modules

### modules/plugins/helpers.py

1. **Validation Helpers**:
   - `validate_cover_count(config, errors)` → Standardize cover count validation
   - `validate_gallery_id(gallery_id, errors, alphanumeric=True)` → Gallery ID validation
   - `validate_credentials(creds, required_keys)` → Check required credentials

2. **Upload Helpers**:
   - `is_cover_image(file_path, group, config)` → Determine if file is cover
   - `create_progress_callback(progress_callback)` → Standard progress wrapper
   - `prepare_upload_headers(data)` → Add Content-Length if needed
   - `execute_upload(client, url, headers, data, timeout=300)` → Standard upload execution

3. **Context Helpers**:
   - `create_upload_context(creds, **extras)` → Standard context initialization
   - `get_client_from_context(context)` → Safe client retrieval

4. **Config Helpers**:
   - `get_standard_config(config, key, default)` → Get standard keys with fallback
   - `normalize_boolean(value)` → Convert various boolean representations
   - `normalize_int(value, default=0)` → Safe int conversion

5. **Error Helpers**:
   - `format_upload_error(exception)` → Standardize error messages
   - `log_upload_success(plugin_name, url)` → Standard success logging

## Benefits

1. **Code Reduction**: ~50-100 lines removed from plugins
2. **Consistency**: All plugins use same patterns
3. **Maintainability**: Fix bugs in one place
4. **Testing**: Test helpers once, all plugins benefit
5. **Documentation**: Single source of truth for patterns

## Implementation Strategy

1. Create `modules/plugins/helpers.py`
2. Implement all helper functions with docstrings
3. Update plugins to use helpers (one at a time)
4. Test that plugins still work
5. Document usage in PHASE5 docs
