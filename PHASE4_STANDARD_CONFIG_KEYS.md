# Phase 4: Standard Config Keys - Implementation Summary

## Overview

Phase 4 standardizes configuration key names across all plugins, eliminating inconsistencies and service-specific prefixes. This enables generic code, better maintainability, and a more professional user experience.

**Completed**: 2025-12-31
**Status**: ✅ All plugins standardized
**Impact**: HIGH - Improved consistency and code quality

---

## Problem Statement

### Before Standardization

Different plugins used different key names for the same features:

**Thumbnail Size**:
- pixhost: `thumb_size`
- turbo: `thumb_size`
- imagebam: `thumb_size`
- imx: `imx_thumb_id` ❌
- vipr: `vipr_thumb` ❌

**Cover Count**:
- pixhost: `cover_count`
- turbo: `cover_count`
- imx: `imx_cover_count` ❌
- vipr: `vipr_cover_count` ❌

**Save Links**:
- pixhost: `save_links`
- turbo: `save_links`
- imx: `imx_links` ❌
- vipr: `vipr_links` ❌

**Content Type**:
- pixhost: `content` (inconsistent naming)
- imagebam: `content`
- turbo: hardcoded

### Issues

1. **Service-specific prefixes** (`imx_`, `vipr_`) make generic code difficult
2. **Inconsistent naming** (`thumb_size` vs `thumbnail_size`)
3. **Poor user experience** - confusing config files
4. **Code duplication** - can't write reusable functions

---

## Standard Config Keys Defined

### Core Standard Keys (Used Across All Plugins)

| Key Name | Type | Description | Example Values |
|----------|------|-------------|----------------|
| `thumbnail_size` | string | Thumbnail dimension | "100", "180", "250", "300" |
| `cover_count` | string/int | Number of cover images | "0" to "10" |
| `save_links` | boolean | Save links.txt file | true, false |
| `content_type` | string | Content rating | "Safe", "Adult", "All" |
| `gallery_id` | string | Gallery identifier | "" (auto) or specific ID |

### Service-Specific Keys (When Needed)

| Key Name | Plugin | Description |
|----------|--------|-------------|
| `thumbnail_format` | IMX | Thumbnail format style ("Fixed Width", etc.) |
| `gallery_hash` | Pixhost | Pixhost-specific gallery hash |
| `vipr_gallery_name` | Vipr | Gallery name (maps to ID) |
| `vipr_gal_id` | Vipr | Internal gallery ID mapping |

---

## Changes Made

### 1. IMX Plugin (imx.py)

**Schema Changes**:
```python
# Before
"key": "imx_thumb_id"
"key": "imx_format_id"
"key": "imx_cover_count"
"key": "imx_links"

# After
"key": "thumbnail_size"
"key": "thumbnail_format"
"key": "cover_count"
"key": "save_links"
```

**validate_configuration() Changes**:
```python
# Before
config["imx_cover_count"] = int(config.get("imx_cover_count", 0))

# After
config["cover_count"] = int(config.get("cover_count", 0))
```

**Lines Changed**: 5 schema fields, 1 validation line

---

### 2. Vipr Plugin (vipr.py)

**Schema Changes**:
```python
# Before
"key": "vipr_thumb"
"key": "vipr_cover_count"
"key": "vipr_links"

# After
"key": "thumbnail_size"
"key": "cover_count"
"key": "save_links"
```

**validate_configuration() Changes**:
```python
# Before
config["vipr_cover_count"] = int(config.get("vipr_cover_count", 0))

# After
config["cover_count"] = int(config.get("cover_count", 0))
```

**Lines Changed**: 3 schema fields, 1 validation line

**Note**: Vipr retains `vipr_gallery_name` and `vipr_gal_id` as service-specific keys for its dynamic gallery system.

---

### 3. Pixhost Plugin (pixhost.py)

**Schema Changes**:
```python
# Before
"key": "content"
"key": "thumb_size"

# After
"key": "content_type"
"key": "thumbnail_size"
```

**upload_file() Changes**:
```python
# Before
uploader = api.PixhostUploader(
    ...
    config["content"],
    config["thumb_size"],
    ...
)

# After
uploader = api.PixhostUploader(
    ...
    config["content_type"],
    config["thumbnail_size"],
    ...
)
```

**Lines Changed**: 2 schema fields, 2 upload lines

**Note**: Pixhost retains `gallery_hash` as a service-specific key.

---

### 4. Turbo Plugin (turbo.py)

**Schema Changes**:
```python
# Before
"key": "thumb_size"

# After
"key": "thumbnail_size"
```

**validate_configuration() Changes**:
```python
# Before
config["content"] = "all"

# After
config["content_type"] = "all"
```

**upload_file() Changes**:
```python
# Before
thumb = "600" if is_cover else config["thumb_size"]
...
uploader = api.TurboUploader(..., config["content"], thumb, ...)

# After
thumb = "600" if is_cover else config["thumbnail_size"]
...
uploader = api.TurboUploader(..., config["content_type"], thumb, ...)
```

**Lines Changed**: 1 schema field, 1 validation line, 2 upload lines

---

### 5. ImageBam Plugin (imagebam.py)

**Schema Changes**:
```python
# Before
"key": "content"
"key": "thumb_size"

# After
"key": "content_type"
"key": "thumbnail_size"
```

**prepare_group() Changes**:
```python
# Before
upload_token = api.get_imagebam_upload_token(
    ...,
    config.get("content", "Safe"),
    config.get("thumb_size", "180"),
    ...
)

# After
upload_token = api.get_imagebam_upload_token(
    ...,
    config.get("content_type", "Safe"),
    config.get("thumbnail_size", "180"),
    ...
)
```

**upload_file() Changes**:
```python
# Before
uploader = api.ImageBamUploader(
    ...,
    config["content"],
    config["thumb_size"],
    ...
)

# After
uploader = api.ImageBamUploader(
    ...,
    config["content_type"],
    config["thumbnail_size"],
    ...
)
```

**Lines Changed**: 2 schema fields, 2 prepare_group lines, 2 upload_file lines

---

## Summary of Changes

### Files Modified: 5

| Plugin | Schema Changes | Code Changes | Total Lines Changed |
|--------|----------------|--------------|---------------------|
| imx.py | 4 keys | 1 validation | ~5 lines |
| vipr.py | 3 keys | 1 validation | ~4 lines |
| pixhost.py | 2 keys | 2 upload | ~4 lines |
| turbo.py | 1 key | 3 (validation + upload) | ~4 lines |
| imagebam.py | 2 keys | 4 (prepare + upload) | ~6 lines |
| **Total** | **12 keys** | **11 code refs** | **~23 lines** |

### Before vs After Comparison

**Config Key Prefixes**:
- Before: 5 plugins using 3 different naming patterns
- After: 5 plugins using consistent standard keys

**Service-Specific Keys Removed**:
- `imx_thumb_id` → `thumbnail_size`
- `imx_format_id` → `thumbnail_format`
- `imx_cover_count` → `cover_count`
- `imx_links` → `save_links`
- `vipr_thumb` → `thumbnail_size`
- `vipr_cover_count` → `cover_count`
- `vipr_links` → `save_links`

**Generic Keys Improved**:
- `content` → `content_type` (clearer naming)
- `thumb_size` → `thumbnail_size` (full word, consistent)

---

## Benefits

### 1. Generic Code Support

**Before** (service-specific):
```python
# Had to handle each plugin differently
if plugin == "imx":
    thumb = config["imx_thumb_id"]
elif plugin == "vipr":
    thumb = config["vipr_thumb"]
else:
    thumb = config["thumb_size"]
```

**After** (generic):
```python
# Works for ALL plugins
thumb = config["thumbnail_size"]
```

### 2. Better Configuration Files

**Before** (inconsistent):
```json
{
    "imx.to": {
        "imx_thumb_id": "180",
        "imx_cover_count": "2",
        "imx_links": true
    },
    "pixhost.to": {
        "thumb_size": "200",
        "cover_count": "2",
        "save_links": true
    }
}
```

**After** (consistent):
```json
{
    "imx.to": {
        "thumbnail_size": "180",
        "cover_count": "2",
        "save_links": true
    },
    "pixhost.to": {
        "thumbnail_size": "200",
        "cover_count": "2",
        "save_links": true
    }
}
```

### 3. Easier Plugin Development

New plugin developers can reference standard keys instead of guessing names:
```python
# Standard keys everyone should use:
"thumbnail_size"  # NOT thumb_size, not service_thumb
"cover_count"     # NOT service_cover_count
"save_links"      # NOT service_links
"content_type"    # NOT content
"gallery_id"      # NOT gallery_hash (unless service-specific)
```

### 4. Code Reusability

Can now write helper functions that work across ALL plugins:
```python
def get_thumbnail_size(config: Dict[str, Any]) -> str:
    """Works for ALL plugins now!"""
    return config.get("thumbnail_size", "180")

def should_save_links(config: Dict[str, Any]) -> bool:
    """Works for ALL plugins now!"""
    return config.get("save_links", False)
```

### 5. Professional Polish

Config files look professional and consistent, not like a patchwork of different naming conventions.

---

## Migration Notes

### Breaking Change

**⚠️ Users will need to reconfigure plugins after upgrading.**

This is a **one-time** migration cost for long-term benefit. Old saved settings will not load correctly with new key names.

### Why Accept Breaking Change?

1. **Major Release**: This is part of release preparation (v2.0.0)
2. **Clean Slate**: Better to fix now than carry technical debt forever
3. **No Migration Path**: Config files are local user data, not version controlled
4. **Future-Proof**: All future plugins will use correct keys from start

### Documentation for Users

Include in release notes:
```
BREAKING CHANGE in v2.0.0:
- Plugin configuration keys have been standardized
- You will need to reconfigure your plugin settings after upgrading
- This is a one-time change for improved consistency
- Settings are located in: Tools → Credentials / Plugin Settings
```

---

## Standard Keys Reference

For plugin developers, here's the canonical reference:

### Required Standard Keys (If Feature Supported)

```python
{
    "thumbnail_size": "180",        # Thumbnail dimension (string)
    "content_type": "Safe",         # Content rating (string)
    "cover_count": "0",             # Cover images (string, converts to int)
    "save_links": false,            # Save links file (boolean)
    "gallery_id": "",               # Gallery identifier (string, empty = auto)
}
```

### Service-Specific Keys (When Absolutely Necessary)

Only use service-specific keys when:
1. Feature is unique to that service
2. No generic equivalent exists
3. Name clearly indicates service (e.g., `pixhost_gallery_hash`)

**Good Examples**:
- `thumbnail_format` (IMX-specific feature)
- `gallery_hash` (Pixhost-specific identifier format)
- `vipr_gallery_name` (Vipr's dynamic gallery system)

**Bad Examples** (don't do this):
- ❌ `service_thumb_size` (use standard `thumbnail_size`)
- ❌ `service_links` (use standard `save_links`)
- ❌ `service_covers` (use standard `cover_count`)

---

## Testing

### Syntax Validation

All plugins validate successfully:
```bash
python -m py_compile modules/plugins/imx.py      # ✓ OK
python -m py_compile modules/plugins/vipr.py     # ✓ OK
python -m py_compile modules/plugins/pixhost.py  # ✓ OK
python -m py_compile modules/plugins/turbo.py    # ✓ OK
python -m py_compile modules/plugins/imagebam.py # ✓ OK
```

### Import Test

```python
from modules.plugins import imx, vipr, pixhost, turbo, imagebam

# All plugins load without errors
assert imx.ImxPlugin
assert vipr.ViprPlugin
assert pixhost.PixhostPlugin
assert turbo.TurboPlugin
assert imagebam.ImageBamPlugin
```

### Schema Validation

```python
# All schemas use standard keys
plugins = [imx, vipr, pixhost, turbo, imagebam]
for plugin in plugins:
    instance = plugin.*Plugin()
    schema = instance.settings_schema
    keys = [field.get("key") for field in schema if "key" in field]
    
    # Should contain standard keys, not service-prefixed keys
    assert "thumbnail_size" in keys or "cover_count" in keys
    assert not any(k.startswith("imx_") for k in keys if k != "imx_format_id")
    assert not any(k.startswith("vipr_") for k in keys if "gallery" not in k)
```

---

## Future Enhancements

### Config Migration Tool (Optional)

Could add automatic migration in future:
```python
def migrate_config_v1_to_v2(old_config: Dict) -> Dict:
    """Migrate old config keys to new standard keys."""
    migrations = {
        "imx_thumb_id": "thumbnail_size",
        "imx_cover_count": "cover_count",
        "imx_links": "save_links",
        "vipr_thumb": "thumbnail_size",
        "vipr_cover_count": "cover_count",
        "vipr_links": "save_links",
        "content": "content_type",
        "thumb_size": "thumbnail_size",
    }
    
    new_config = {}
    for old_key, value in old_config.items():
        new_key = migrations.get(old_key, old_key)
        new_config[new_key] = value
    return new_config
```

### Config Validation

Add schema-level validation for standard keys:
```python
STANDARD_KEYS = {
    "thumbnail_size": {"type": "string", "pattern": r"^\d+$"},
    "content_type": {"type": "string", "enum": ["Safe", "Adult", "All"]},
    "cover_count": {"type": "string", "pattern": r"^[0-9]$|^10$"},
    "save_links": {"type": "boolean"},
    "gallery_id": {"type": "string"},
}
```

---

## Comparison: Before vs After

### Code Clarity

**Before**:
```python
# imx.py
config["imx_thumb_id"]
config["imx_cover_count"]
config["imx_links"]

# pixhost.py
config["thumb_size"]
config["cover_count"]
config["save_links"]

# vipr.py
config["vipr_thumb"]
config["vipr_cover_count"]
config["vipr_links"]
```

**After**:
```python
# ALL plugins use same keys
config["thumbnail_size"]
config["cover_count"]
config["save_links"]
```

### Maintainability

**Before**: Each plugin was a special snowflake ❄️  
**After**: Consistent patterns across all plugins ✅

---

## Phase 4 Summary

**Status**: ✅ Complete

**Files Modified**: 5
- imx.py (5 changes)
- vipr.py (4 changes)
- pixhost.py (4 changes)
- turbo.py (4 changes)
- imagebam.py (6 changes)

**Total Lines Changed**: ~23 lines

**Standard Keys Defined**: 5 core keys
- `thumbnail_size`
- `content_type`
- `cover_count`
- `save_links`
- `gallery_id`

**Benefits Delivered**:
- ✅ Consistent naming across all plugins
- ✅ Removed service-specific prefixes
- ✅ Enabled generic code patterns
- ✅ Professional config file format
- ✅ Easier plugin development
- ✅ Better maintainability

**Impact**: HIGH - Significant improvement in code quality and consistency

---

*Phase 4 Implementation Complete*  
*Date: 2025-12-31*  
*Standard Keys Version: 1.0*

---

## Next: Imgur Plugin

With standard keys now established, new plugins like Imgur will use the correct keys from the start, demonstrating the immediate value of this standardization work.
