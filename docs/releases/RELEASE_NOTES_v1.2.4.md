# Release Notes - v1.2.4 "Python 3.14 Packaging Fix"

**Release Date**: May 20, 2026
**Type**: Patch Release (Packaging Bug Fix)
**Previous Version**: v1.2.3
**Git Tag**: `v1.2.4`

---

## Release Highlights

This patch release fixes an executable startup crash seen when building with Python 3.14. The crash came from the older drag-and-drop dependency importing `tkinter.tix`, which is no longer available in the active Python runtime.

### Key Fixes
- Updated `tkinterdnd2` from `0.3.0` to `0.4.3`
- Fixed the packaged executable startup crash caused by the missing `tkinter.tix` module
- Synced application, build script, documentation, and release tag references to `v1.2.4`

---

## Bug Fixes

### Python 3.14 Drag-and-Drop Packaging Fix

**Priority**: High
**Impact**: Packaged executable failed during startup

- **Problem**: Running the executable produced `ImportError: cannot import name 'tix' from 'tkinter'`
- **Root Cause**: `tkinterdnd2==0.3.0` imports `tkinter.tix`, which is not present in Python 3.14
- **Fix**: Updated the pinned dependency to `tkinterdnd2==0.4.3`
- **Benefit**: Drag-and-drop support imports correctly and the packaged GUI can start

### Release Metadata Sync

- Updated `APP_VERSION` to `1.2.4`
- Updated Windows, Linux/macOS, and Makefile build banners to `1.2.4`
- Updated README, architecture, issue tracker, documentation index, and release process references
- Confirmed release links and examples use the correct `v1.2.4` tag

---

## Files Changed

- `requirements.txt`
- `modules/config.py`
- `build_uploader.bat`
- `build.sh`
- `Makefile`
- `.github/workflows/release.yml`
- `README.md`
- `CHANGELOG.md`
- `ARCHITECTURE.md`
- `REMAINING_ISSUES.md`
- `docs/README.md`
- `docs/releases/RELEASE_NOTES_v1.2.4.md`
- `docs/releases/RELEASE_PROCESS.md`

---

## Installation

### Download the Latest Release

**[Download v1.2.4](https://github.com/conniecombs/conniesuploader/releases/tag/v1.2.4)**

**Available builds:**
- **Windows**: `ConniesUploader-v1.2.4-windows-x64.zip`
- **Linux**: `ConniesUploader-v1.2.4-linux-x64.tar.gz`
- **macOS**: `ConniesUploader-v1.2.4-macos-x64.zip`

### Verify Your Download

```bash
# Windows (PowerShell)
certutil -hashfile ConniesUploader.exe SHA256

# Linux/macOS
sha256sum ConniesUploader  # or shasum -a 256 on macOS
```

Compare the output with the checksum file included in the release.

---

## Upgrading from v1.2.3

No settings or credential migrations are required. This is a drop-in replacement for v1.2.3.

Recommended steps:

1. Close any running `ConniesUploader` process.
2. Replace the old executable with the v1.2.4 build.
3. Start the app normally.

---

## Release Tag

Use the annotated tag below to publish this release:

```bash
git tag -a v1.2.4 -m "Release v1.2.4"
git push origin v1.2.4
```

**Full Changelog**: [v1.2.3...v1.2.4](https://github.com/conniecombs/conniesuploader/compare/v1.2.3...v1.2.4)
