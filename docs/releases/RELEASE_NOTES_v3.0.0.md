# Release Notes - v3.0.0 "Python-Owned Workflows & Generic Transport"

**Release Date**: July 12, 2026
**Git Tag**: `v3.0.0`
**Release Type**: Major architecture release

## Overview

v3.0.0 completes Connie's Uploader's move away from host-specific Go services. Python now owns website workflows, form parsing, success checks, gallery/forum sequencing, scheduled ViperGirls posts, and host-specific upload specifications. The Go sidecar remains the fast local transport runner for generic upload, request, retry, rate-limit, cookie, and thumbnail work.

The full branch comparison captured for this release is recorded in [BRANCH_DIFF_v3.0.0.md](BRANCH_DIFF_v3.0.0.md).

## Highlights

- Promoted the app, build scripts, and active plugin metadata to `3.0.0`.
- Completed the `frontend/` and `backend/` source split for the Python GUI/runtime and Go sidecar.
- Added the Python/Go transport contract so Python owns website-specific interpretation while Go returns transport facts such as response body, status code, and final URL.
- Added the Go `http_request` action for standalone non-upload requests such as login, gallery creation, and forum posting.
- Added the Go `http_batch_resolve` action for deferred batch result polling.
- Moved ViperGirls scheduled posting into Python so scheduled posts use the same form-aware path as immediate posts.
- Moved host-specific default sidecar rate limits into Python job/request payloads.
- Added current release documentation for the v3.0.0 branch comparison against `main`.

## Notable Changes

- Removed the legacy Go `backend/services/` host modules from the active sidecar architecture.
- Replaced legacy Go actions such as `upload`, `login`, `verify`, `create_gallery`, `finalize_gallery`, `list_galleries`, `viper_login`, and `viper_post` with generic transport actions.
- Updated `frontend/modules/api.py`, `frontend/modules/gallery_service.py`, `frontend/modules/plugins/turbo.py`, and `frontend/modules/viper_api.py` around Python-owned request construction and response validation.
- Refreshed current docs for the source split, v3.0.0 release status, scheduled posts, activity logging, and Python-owned transport parsing model.
- Kept historical release notes as records while routing current guidance through the root README, docs index, architecture guide, transport contract, and v3.0.0 release notes.

## Fixes

- Fixed Turbo deferred result matching when host result pages refer to sanitized filenames.
- Moved app settings storage from legacy repo-local `user_settings.json` to `~/.conniesuploader/user_settings.json`, with startup migration that removes legacy settings files from the checkout without printing their contents.

## Tests

v3.0.0 adds or expands coverage for the source split, sidecar build contracts, generic transport contracts, gallery service behavior, plugin request generation, ViperGirls target/history behavior, and the organized main-window package.

Recommended verification before publishing the tag:

```bash
cd backend && go test ./...
cd ../frontend && python -m pytest -q -p no:cacheprovider --no-cov
```

## Download

**[Download v3.0.0](https://github.com/conniecombs/ConniesUploader/releases/tag/v3.0.0)**

Expected release artifacts:

- `ConniesUploader-v3.0.0-windows-x64.zip`
- `ConniesUploader-v3.0.0-linux-x64.tar.gz`
- `ConniesUploader-v3.0.0-macos-x64.zip`

## Upgrade Notes

Existing application settings are preserved. Current settings live at `~/.conniesuploader/user_settings.json`; legacy repo-local settings files are migrated out of the checkout automatically. Custom templates, gallery cache, ViperGirls posting targets, posting history, scheduled posts, and activity logs remain under `~/.conniesuploader/`.

## Tagging

```bash
git tag -a v3.0.0 -m "Release v3.0.0"
git push origin v3.0.0
```
