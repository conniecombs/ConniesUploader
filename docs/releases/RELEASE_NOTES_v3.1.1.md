# Release Notes - v3.1.1 "Activity Hide & IMX Thumbnail Fix"

**Release Date**: September 7, 2026
**Git Tag**: `v3.1.1`
**Previous Version**: `v3.1.0`

## Overview

v3.1.1 is a maintenance release for two user-visible workflow fixes: the Activity panel now stays hidden when the user hides it, and IMX thumbnail output is normalized to the durable thumbnail URL format.

## Fixed

- Fixed the Activity panel `Hide` button so new scan, queue, upload, retry, copy, save, and completion events do not reopen the panel after the user hides it.
- Kept hidden Activity panel events in the current in-memory session log so `View > Show Activity` restores the latest activity.
- Normalized IMX thumbnail URLs from `https://i.imx.to/t/...` to `https://image.imx.to/u/t/...` before generated output files or copied output receive them.

## Changed

- Bumped app, build-script, and active plugin metadata to `3.1.1`.
- Updated README, release, user, architecture, contributor, repository-layout, plugin, and troubleshooting docs for the current Activity panel behavior.

## Verification

- Run Python tests from `frontend/`:

```bash
python -m pytest tests -q
```

- Run Go sidecar tests from `backend/`:

```bash
go test ./...
```

## Download

**[Download v3.1.1](https://github.com/conniecombs/ConniesUploader/releases/tag/v3.1.1)**

Expected artifacts:

- `ConniesUploader-v3.1.1-windows-x64.zip`
- `ConniesUploader-v3.1.1-linux-x64.tar.gz`
- `ConniesUploader-v3.1.1-macos-x64.zip`

Each artifact includes a SHA256 checksum.

## Tagging

```bash
git tag -a v3.1.1 -m "Release v3.1.1"
git push origin v3.1.1
```
