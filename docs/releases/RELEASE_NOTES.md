# Release Notes

This directory contains release notes and publishing guidance for Connie's Uploader Ultimate.

## Latest Release

**v1.2.4 - "CI & Packaging Reliability"**
Release date: May 20, 2026
Tag: `v1.2.4`

Read the full notes: [RELEASE_NOTES_v1.2.4.md](RELEASE_NOTES_v1.2.4.md)

### Summary

- Fixed packaged executable startup by updating `tkinterdnd2` to avoid the legacy `tkinter.tix` import path.
- Updated Pillow to `12.2.0` for current image-processing security fixes.
- Replaced Safety dependency checks with `pip-audit==2.10.0`.
- Hardened Windows and macOS CI path assertions.
- Mocked GUI dialogs that could stall headless CI.

## Release History

| Version | Date | Focus | Notes |
|---------|------|-------|-------|
| v1.2.4 | 2026-05-20 | CI & Packaging Reliability | [Notes](RELEASE_NOTES_v1.2.4.md) |
| v1.2.3 | 2026-01-31 | Gallery Logic Fix | See [CHANGELOG.md](../../CHANGELOG.md) |
| v1.2.2 | 2026-01-22 | Batch Upload Stability | [Notes](RELEASE_NOTES_v1.2.2.md) |
| v1.2.1 | 2026-01-18 | Gallery Fix | See [CHANGELOG.md](../../CHANGELOG.md) |
| v1.2.0 | 2026-01-17 | Stability & Maintenance | See [CHANGELOG.md](../../CHANGELOG.md) |
| v1.1.0 | 2026-01-16 | Performance & Polish | [Notes](RELEASE_NOTES_v1.1.0.md) |
| v1.0.5 | 2026-01-13 | Resilience & Intelligence | [Notes](RELEASE_NOTES_v1.0.5.md) |
| v1.0.4 | 2026-01-12 | Maintenance | [Notes](release_notes_v1.0.4.md) |

## Publishing

The release workflow is tag-based. For v1.2.4, use:

```bash
git tag -a v1.2.4 -m "Release v1.2.4"
git push origin v1.2.4
```

See [RELEASE_PROCESS.md](RELEASE_PROCESS.md) for the full checklist.
