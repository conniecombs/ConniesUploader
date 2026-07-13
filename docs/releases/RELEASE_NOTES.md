# Release Notes

This directory contains release notes and publishing guidance for Connie's Uploader.

## Latest Release

**v3.0.0 - "Python-Owned Workflows & Generic Transport"**
Release date: July 12, 2026
Tag: `v3.0.0`

Read the full notes: [RELEASE_NOTES_v3.0.0.md](RELEASE_NOTES_v3.0.0.md)
Read the branch comparison: [BRANCH_DIFF_v3.0.0.md](BRANCH_DIFF_v3.0.0.md)

### Summary

- Promoted the app, build scripts, and active plugin metadata to `3.0.0`.
- Completed the Python-owned website workflow and generic Go transport split.
- Added generic sidecar actions for standalone HTTP requests and deferred batch result resolution.
- Moved ViperGirls scheduled posting into Python's form-aware posting path.
- Recorded the full `Bleeding-Edge` branch comparison against `main` for release review.

## Release History

| Version | Date | Focus | Notes |
|---------|------|-------|-------|
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
