# Phase 4: Config Key Standardization Analysis

## Current State (Inconsistent Keys)

### Thumbnail Size Keys
- **pixhost.py**: `thumb_size` → "100", "180", "250", "300", "350"
- **turbo.py**: `thumb_size` → "150", "200", "250", "300", "350", "400", "500", "600"
- **imagebam.py**: `thumb_size` → "100", "180", "250", "300"
- **imx.py**: `imx_thumb_id` ❌ → "100", "180", "250", "300", "600"
- **vipr.py**: `vipr_thumb` ❌ → "100x100", "170x170", "250x250", etc.

### Cover Count Keys
- **pixhost.py**: `cover_count` → 0-10
- **turbo.py**: `cover_count` → 0-10
- **imx.py**: `imx_cover_count` ❌ → 0-10
- **vipr.py**: `vipr_cover_count` ❌ → 0-10
- **imagebam.py**: No covers support

### Save Links Keys
- **pixhost.py**: `save_links` → boolean
- **turbo.py**: `save_links` → boolean
- **imx.py**: `imx_links` ❌ → boolean
- **vipr.py**: `vipr_links` ❌ → boolean
- **imagebam.py**: No save links option

### Content Type Keys
- **pixhost.py**: `content` → "Safe", "Adult"
- **imagebam.py**: `content` → "Safe", "Adult"
- **turbo.py**: Hardcoded to "all" (no UI field)

### Gallery Keys
- **pixhost.py**: `gallery_hash` → text (specific to Pixhost)
- **turbo.py**: `gallery_id` → text
- **imx.py**: `gallery_id` → text
- **vipr.py**: `vipr_gallery_name` → dropdown (dynamic, maps to ID)

## Issues Identified

1. **Prefixed Keys**: imx and vipr use service-specific prefixes (`imx_`, `vipr_`)
2. **Inconsistent Naming**: `thumb_size` vs `imx_thumb_id` vs `vipr_thumb`
3. **Value Formats**: Some use "180", some use "180x180"
4. **Optional Features**: Not all plugins have all features (covers, content type)

## Proposed Standard Keys

### Core Standard Keys (All Plugins Should Use)
- `thumbnail_size` → Standard thumbnail dimension key
- `cover_count` → Number of cover images (0-10)
- `save_links` → Save links.txt file (boolean)
- `content_type` → Content rating ("Safe", "Adult", "All")
- `gallery_id` → Gallery identifier (text)

### Service-Specific Keys (When Needed)
- `thumbnail_format` → IMX-specific format option
- `gallery_name` → Vipr-specific gallery name
- `gallery_hash` → Pixhost-specific hash

## Migration Strategy

### Approach: Clean Break with Documentation
Since this is a major version (preparing for release), we'll:
1. Standardize all keys to new names
2. Update all code to use new keys
3. Document in release notes that users need to reconfigure plugins once

### Why Not Backward Compatibility?
- Config files are local user data, not in repo
- Adding dual-key support complicates code long-term
- One-time reconfiguration is acceptable for major release
- Clean codebase is more maintainable going forward

## Implementation Checklist

- [ ] Update IMX plugin: `imx_thumb_id` → `thumbnail_size`, `imx_cover_count` → `cover_count`, `imx_links` → `save_links`
- [ ] Update Vipr plugin: `vipr_thumb` → `thumbnail_size`, `vipr_cover_count` → `cover_count`, `vipr_links` → `save_links`
- [ ] Update Pixhost plugin: `thumb_size` → `thumbnail_size`, `content` → `content_type`
- [ ] Update Turbo plugin: `thumb_size` → `thumbnail_size`, `content` → `content_type`
- [ ] Update ImageBam plugin: `thumb_size` → `thumbnail_size`, `content` → `content_type`
- [ ] Update validate_configuration in all plugins
- [ ] Update upload_file in all plugins
- [ ] Add standard key reference to base.py docs
- [ ] Test all plugins still work

## Benefits

1. **Consistency**: All plugins use same key names for same features
2. **Predictability**: Developers know what keys to use
3. **Generic Code**: Can write code that works across all plugins
4. **Better UX**: Clearer, more professional config files
5. **Future-Proof**: Easy to add new plugins with correct keys from start
