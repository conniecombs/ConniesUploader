# Release Notes - v1.4.0 "User Experience Polish & Safer Upload Controls"

**Release Date**: June 20, 2026  
**Git Tag**: `v1.4.0`  
**Release Type**: Minor feature release

## Overview

v1.4.0 focuses on making Connie's Uploader feel clearer, safer, and more task-oriented for everyday users. The main window now guides users from adding files through preflight checks, upload progress, and completion without relying on modal popups or hidden right-click actions.

## Highlights

- Empty queue drop zone with centered Add Files and Add Folder actions.
- Context-aware top queue actions that appear after files are added.
- Hideable Activity panel with visible upload history.
- Import Checks and Upload Checks panels with actionable fixes.
- Inline completion summaries with generated files, clipboard status, copy again, open folder, and retry failed actions.
- Clearer queue rows with remove buttons, retry controls, failed reasons, and better no-preview spacing.
- Advanced App Settings now contains Worker Count and Thread Limit together.
- Worker counts clamp to `1-16`; upload thread limits clamp to `1-10`.
- Service settings render from plugin schemas, including Imgur configuration support.
- Corrupted template data can be reset or opened from the UI.

## Build Notes

The Windows build path remains automated through:

```bat
build_uploader.bat --ci
```

The build verifies the bundled Go sidecar, tkinterdnd2 assets, and final executable output.

## Download

**[Download v1.4.0](https://github.com/conniecombs/ConniesUploader/releases/tag/v1.4.0)**

Expected release artifacts:

- `ConniesUploader-v1.4.0-windows-x64.zip`
- `ConniesUploader-v1.4.0-linux-x64.tar.gz`
- `ConniesUploader-v1.4.0-macos-x64.zip`

## Upgrade Notes

Existing settings are preserved. Worker and upload-thread values outside the supported ranges are normalized automatically when settings are loaded or saved.

## Tagging

```bash
git tag -a v1.4.0 -m "Release v1.4.0"
git push origin v1.4.0
```
