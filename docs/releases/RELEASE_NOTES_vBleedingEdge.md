# Release Notes - vBleedingEdge "Pixhost.cc & Import Performance Patch"

**Git Tag**: `vBleedingEdge`
**Release Type**: Patch release
**Release Date**: 2026-07-28
**Previous Version**: `v3.0.0`

vBleedingEdge keeps the v3 Python-owned workflow architecture intact while refreshing the active Pixhost integration and improving large-folder import responsiveness.

## Changed

- Bumped the app version, build scripts, and active plugin metadata to `BleedingEdge`.
- Updated Pixhost as an active service from `pixhost.to` to `pixhost.cc`.
- Updated Pixhost upload, gallery creation, gallery finalization, Gallery Manager, output context, tests, and current-facing docs to use `pixhost.cc`.
- Moved folder import scanning off the Tk thread, increased bounded UI queue throughput, and deferred thumbnails so large folder adds remain more responsive.

## Fixed

- Fixed Pixhost upload specs to use `https://api.pixhost.cc/images`.
- Fixed Pixhost gallery creation/finalization specs to use `https://api.pixhost.cc/galleries`.
- Fixed legacy `pixhost.to` saved settings, gallery cache records, selected galleries, validation, and upload thread settings by normalizing them forward to `pixhost.cc`.
- Fixed current docs and test contracts that still described Pixhost as `pixhost.to`.

## Verification

The release-prep pass was verified locally with:

- `python -m pytest -q -p no:cacheprovider --no-cov` from `frontend/`
- `go test ./...` from `backend/` with a workspace-local `GOCACHE`
- Version and stale Pixhost-domain searches across active code, tests, and current docs
- `git diff --check`

## Download

**[Download vBleedingEdge](https://github.com/conniecombs/ConniesUploader/releases/tag/vBleedingEdge)**

Expected release artifacts:

- `ConniesUploader-vBleedingEdge-windows-x64.zip`
- `ConniesUploader-vBleedingEdge-linux-x64.tar.gz`
- `ConniesUploader-vBleedingEdge-macos-x64.zip`

Each release artifact includes a SHA256 checksum.

## Tagging

Use the annotated release tag when you are ready to publish:

```bash
git tag -a vBleedingEdge -m "Release vBleedingEdge"
git push origin vBleedingEdge
```
