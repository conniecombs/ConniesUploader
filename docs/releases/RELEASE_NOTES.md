# Release Notes

This directory contains release notes and publishing guidance for Connie's Uploader.

## Latest Release

**v3.1.3 - "Posting Sessions & Shared Limits"**
Release date: November 18, 2026
Tag: `v3.1.3`

Read the full notes: [RELEASE_NOTES_v3.1.3.md](RELEASE_NOTES_v3.1.3.md)
Previous release notes: [RELEASE_NOTES_v3.1.2.md](RELEASE_NOTES_v3.1.2.md)

### Summary

- Ships the v3.1.2 review fixes that merged after the `v3.1.2` tag: no dropped or competing auto-posts when a new upload starts, and no late forum replies after the app reported a failure.
- Aligns the per-file size limit at 100 MB in the app and the sidecar, and sends the sidecar only the credentials a host needs.
- Splits the ViperGirls module into storage, client, and UI parts, and bumps app, build scripts, plugin metadata, and release docs to `3.1.3`.

## Release History

| Version | Date | Focus | Notes |
|---------|------|-------|-------|
| v3.1.3 | 2026-11-18 | Posting Sessions & Shared Limits | [Notes](RELEASE_NOTES_v3.1.3.md) |
| v3.1.2 | 2026-11-06 | Lifecycle Hardening | [Notes](RELEASE_NOTES_v3.1.2.md) |
| v3.1.1 | 2026-09-07 | Activity Hide & IMX Thumbnail Fix | [Notes](RELEASE_NOTES_v3.1.1.md) |
| v3.1.0 | 2026-09-04 | Folder Size Template Placeholder | [Notes](RELEASE_NOTES_v3.1.0.md) |
| vBleedingEdge | 2026-07-28 | Pixhost.cc & Import Performance Patch | [Notes](RELEASE_NOTES_vBleedingEdge.md) |
| v3.0.0 | 2026-07-12 | Python-Owned Workflows & Generic Transport | [Notes](RELEASE_NOTES_v3.0.0.md), [Diff](BRANCH_DIFF_v3.0.0.md) |
| v2.0.0 | 2026-06-22 | Posting, Templates & Gallery Workflows | [Notes](RELEASE_NOTES_v2.0.0.md) |
| v1.4.0 | 2026-06-20 | User Experience Polish & Safer Upload Controls | [Notes](RELEASE_NOTES_v1.4.0.md) |
| v1.3.0 | 2026-06-02 | Protocol Hardening & Release Reliability | [Notes](RELEASE_NOTES_v1.3.0.md) |
| v1.2.4 | 2026-05-20 | CI & Packaging Reliability | [Notes](RELEASE_NOTES_v1.2.4.md) |
| v1.2.3 | 2026-01-31 | Gallery Logic Fix | See [CHANGELOG.md](../CHANGELOG.md) |
| v1.2.2 | 2026-01-22 | Batch Upload Stability | [Notes](RELEASE_NOTES_v1.2.2.md) |
| v1.2.1 | 2026-01-18 | Gallery Fix | See [CHANGELOG.md](../CHANGELOG.md) |
| v1.2.0 | 2026-01-17 | Stability & Maintenance | See [CHANGELOG.md](../CHANGELOG.md) |
| v1.1.0 | 2026-01-16 | Performance & Polish | [Notes](RELEASE_NOTES_v1.1.0.md) |
| v1.0.5 | 2026-01-13 | Resilience & Intelligence | [Notes](RELEASE_NOTES_v1.0.5.md) |
| v1.0.4 | 2026-01-12 | Maintenance | [Notes](release_notes_v1.0.4.md) |

## Publishing

The release workflow is tag-based. For a new version, use:

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

See [RELEASE_PROCESS.md](RELEASE_PROCESS.md) for the full checklist.
