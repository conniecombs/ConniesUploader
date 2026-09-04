# Release Notes - v3.1.0 "Folder Size Template Placeholder"

**Git Tag**: `v3.1.0`
**Release Type**: Minor release
**Release Date**: 2026-09-04
**Previous Version**: `vBleedingEdge`

v3.1.0 adds a folder-size template placeholder for users who want generated output to include the total size of the current upload batch.

## Added

- Added `#folder_size#` to the supported template placeholder set.
- Added Template Editor insertion support for `#folder_size#` in the Batch placeholder category.
- Added folder-size values to saved batch output, Template Editor previews, and ViperGirls post previews.
- Added readable size formatting with up to two decimal places, such as `714 KB`, `114 MB`, or `1.34 GB`.

## Changed

- Bumped the app version, build scripts, and active plugin metadata to `3.1.0`.
- Updated current-facing docs and release indexes for v3.1.0.

## Implementation Notes

`#folder_size#` is calculated from the readable files accepted into the current batch. That means it follows the files that Connie's Uploader will actually upload and render, even when a batch came from a folder, multiple folders, or manually added files.

If a file is no longer readable by the time output is generated, it is skipped for the size total instead of blocking the finished output file.

## Verification

The release-prep pass was verified locally with:

- `python -m pytest tests/test_file_handler.py tests/test_template_manager.py tests/test_main_window_contract.py tests/test_controller.py -q` from `frontend/` (`186 passed`)
- `python -m pytest -q -p no:cacheprovider --no-cov` from `frontend/` (`518 passed, 1 skipped`)
- `python -m flake8 main.py modules/ --max-line-length=120 --ignore=E501,W503 --exclude=__pycache__` from `frontend/`
- `go test ./...` from `backend/`
- Version and placeholder searches across active code and current docs

## Download

**[Download v3.1.0](https://github.com/conniecombs/ConniesUploader/releases/tag/v3.1.0)**

Expected release artifacts:

- `ConniesUploader-v3.1.0-windows-x64.zip`
- `ConniesUploader-v3.1.0-linux-x64.tar.gz`
- `ConniesUploader-v3.1.0-macos-x64.zip`

Each release artifact includes a SHA256 checksum.

## Tagging

Use the annotated release tag when you are ready to publish:

```bash
git tag -a v3.1.0 -m "Release v3.1.0"
git push origin v3.1.0
```
