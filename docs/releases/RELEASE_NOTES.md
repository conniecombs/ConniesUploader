# Release Notes

This directory contains release notes and publishing guidance for Connie's Uploader Ultimate.

## Latest Release

**v2.0.0 - "Posting, Templates & Gallery Workflows"**
Release date: June 22, 2026
Tag: `v2.0.0`

Read the full notes: [RELEASE_NOTES_v2.0.0.md](RELEASE_NOTES_v2.0.0.md)

### Summary

- Added ViperGirls posting targets, previews, background posting, and posting history.
- Added richer Template Editor workflows, template migration, nested conditionals, image loops, cover loops, and BBCode/HTML warnings.
- Added a dedicated Gallery Service and persistent Gallery Cache with pins, last-used timestamps, cached fallback display, and stronger Gallery Manager actions.
- Reworked cover handling and queue controls with compact cover toggles, selection-aware removal, and keyboard shortcuts.
- Expanded tests across posting targets, templates, galleries, preflight checks, cover behavior, and service integrations.

## Release History

| Version | Date | Focus | Notes |
|---------|------|-------|-------|
| v2.0.0 | 2026-06-22 | Posting, Templates & Gallery Workflows | [Notes](RELEASE_NOTES_v2.0.0.md) |
| v1.4.0 | 2026-06-20 | User Experience Polish & Safer Upload Controls | [Notes](RELEASE_NOTES_v1.4.0.md) |
| v1.3.0 | 2026-06-02 | Protocol Hardening & Release Reliability | [Notes](RELEASE_NOTES_v1.3.0.md) |
| v1.2.4 | 2026-05-20 | CI & Packaging Reliability | [Notes](RELEASE_NOTES_v1.2.4.md) |
| v1.2.3 | 2026-01-31 | Gallery Logic Fix | See [CHANGELOG.md](../../CHANGELOG.md) |
| v1.2.2 | 2026-01-22 | Batch Upload Stability | [Notes](RELEASE_NOTES_v1.2.2.md) |
| v1.2.1 | 2026-01-18 | Gallery Fix | See [CHANGELOG.md](../../CHANGELOG.md) |
| v1.2.0 | 2026-01-17 | Stability & Maintenance | See [CHANGELOG.md](../../CHANGELOG.md) |
| v1.1.0 | 2026-01-16 | Performance & Polish | [Notes](RELEASE_NOTES_v1.1.0.md) |
| v1.0.5 | 2026-01-13 | Resilience & Intelligence | [Notes](RELEASE_NOTES_v1.0.5.md) |
| v1.0.4 | 2026-01-12 | Maintenance | [Notes](release_notes_v1.0.4.md) |

## Publishing

The release workflow is tag-based. For v2.0.0, use:

```bash
git tag -a v2.0.0 -m "Release v2.0.0"
git push origin v2.0.0
```

See [RELEASE_PROCESS.md](RELEASE_PROCESS.md) for the full checklist.
