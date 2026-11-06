# Release Notes

This directory contains release notes and publishing guidance for Connie's Uploader.

## Latest Release

**v3.1.2 - "Lifecycle Hardening"**
Release date: November 6, 2026
Tag: `v3.1.2`

Read the full notes: [RELEASE_NOTES_v3.1.2.md](RELEASE_NOTES_v3.1.2.md)
Previous release notes: [RELEASE_NOTES_v3.1.1.md](RELEASE_NOTES_v3.1.1.md)

### Summary

- Fixed the batch wedge caused by filenames containing `..`, double-counted failures, and a Stop button that could not stop anything; Stop now cancels in the sidecar and rows end as `Cancelled`.
- Fixed auto-posting stalls behind non-posting batches, forum posts containing `{...}`, stale credentials, duplicate-post retries, and shared-file races.
- Enforced `black` in CI, pinned lint tools, removed dead code, and bumped app, build scripts, plugin metadata, and release docs to `3.1.2`.

## Release History

| Version | Date | Focus | Notes |
|---------|------|-------|-------|
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
