# Release Notes

This directory contains release notes and publishing guidance for Connie's Uploader.

## Latest Release

**vBleedingEdge - "Pixhost.cc & Import Performance Patch"**
Release date: July 28, 2026
Tag: `vBleedingEdge`

Read the full notes: [RELEASE_NOTES_vBleedingEdge.md](RELEASE_NOTES_vBleedingEdge.md)
Previous architecture release notes: [RELEASE_NOTES_v3.0.0.md](RELEASE_NOTES_v3.0.0.md)

### Summary

- Bumped app, build scripts, and active plugin metadata to `BleedingEdge`.
- Updated Pixhost from `pixhost.to` to `pixhost.cc` across active upload, gallery, output, docs, and test surfaces.
- Preserved legacy `pixhost.to` saved settings and gallery cache records by normalizing them to `pixhost.cc`.
- Improved large-folder import responsiveness with background scanning, larger bounded UI batches, and deferred thumbnails.

## Release History

| Version | Date | Focus | Notes |
|---------|------|-------|-------|
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
