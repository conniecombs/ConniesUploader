# Release Notes - v1.2.4 "CI & Packaging Reliability"

**Release Date**: May 20, 2026
**Previous Version**: v1.2.3
**Git Tag**: `v1.2.4`
**Release Type**: Patch

---

## Overview

v1.2.4 is a reliability and maintenance release. It keeps the app behavior stable while fixing the packaged executable startup crash, bringing dependency security checks up to date, and hardening CI tests across Windows, macOS, and Linux.

## Highlights

- Fixed the packaged executable startup crash caused by older `tkinterdnd2` builds importing the removed legacy `tkinter.tix` module path.
- Updated Pillow to `12.2.0` for current image-processing security fixes.
- Replaced Safety dependency scanning with `pip-audit==2.10.0` in GitHub Actions.
- Pinned `flake8==7.1.1` for stable lint results.
- Normalized path-sensitive tests for Windows short paths and macOS `/private/var` aliases.
- Mocked GUI message boxes in menu tests so headless CI runs do not stall.

## Fixes

### Packaged Executable Startup

The executable could crash at startup while importing `tkinterdnd2` because older dependency versions attempted to import `tkinter.tix`.

**Fix**: `tkinterdnd2` is pinned to `0.4.3`, which avoids that legacy import path while preserving drag-and-drop support.

### Cross-Platform CI Reliability

Several tests were correct in intent but too strict about platform-specific path formatting or GUI dialog behavior.

**Fixes**:
- Normalized macOS `/var` and `/private/var` comparisons in file-handler tests.
- Normalized Windows short 8.3 path comparisons in validation tests.
- Mocked the success dialog in menu removal tests to prevent headless UI stalls.

### Validation Behavior

Validation expectations were aligned with current behavior:
- Empty sanitized filenames fall back to `untitled`.
- Dangerous filename characters include brackets, braces, and parentheses.
- Thread count validation clamps and coerces values consistently with the configured limits.

## Security

- Updated `Pillow` to `12.2.0`, covering the latest audited image-processing dependency fixes, including CVE-2026-40192, CVE-2026-42308, CVE-2026-42309, CVE-2026-42310, and CVE-2026-42311.
- CI now uses `pip-audit==2.10.0` for Python dependency vulnerability checks.
- Existing Go security checks continue to run through gosec and govulncheck.

## Verification

The release was verified with:
- GitHub Actions CI build and test workflow
- GitHub Actions security scanning workflow
- Python test suite
- Go vet, tests, and build checks
- Targeted Windows/macOS path normalization tests
- Packaged executable startup validation

## Download

**[Download v1.2.4](https://github.com/conniecombs/conniesuploader/releases/tag/v1.2.4)**

Expected release artifacts:
- `ConniesUploader-v1.2.4-windows-x64.zip`
- `ConniesUploader-v1.2.4-linux-x64.tar.gz`
- `ConniesUploader-v1.2.4-macos-x64.zip`

Each artifact includes a SHA256 checksum for verification.

## Upgrading from v1.2.3

No settings or credential migrations are required. This is a drop-in patch release.

Recommended steps:
1. Back up any local settings if desired.
2. Download the `v1.2.4` artifact for your platform.
3. Replace the old executable or extracted app folder.
4. Run the app and confirm drag-and-drop and uploads still work.

## Tag Commands

Use the annotated release tag:

```bash
git tag -a v1.2.4 -m "Release v1.2.4"
git push origin v1.2.4
```

**Full Changelog**: [v1.2.3...v1.2.4](https://github.com/conniecombs/conniesuploader/compare/v1.2.3...v1.2.4)
