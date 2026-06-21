# Release Notes

This directory contains release notes and publishing guidance for Connie's Uploader Ultimate.

## Latest Release

**v1.4.0 - "User Experience Polish & Safer Upload Controls"**
Release date: June 20, 2026
Tag: `v1.4.0`

Read the full notes: [RELEASE_NOTES_v1.4.0.md](RELEASE_NOTES_v1.4.0.md)

### Summary

- Added task-oriented empty, checks, activity, and completion states.
- Improved queue readability with visible row actions, retry controls, and failed reasons.
- Moved Worker Count and Thread Limit into Advanced App Settings.
- Clamped worker counts to `1-16` and upload thread limits to `1-10`.
- Kept the Windows `build_uploader.bat --ci` path verified for automated everyday-user builds.

## Release History

| Version | Date | Focus | Notes |
|---------|------|-------|-------|
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

The release workflow is tag-based. For v1.4.0, use:

```bash
git tag -a v1.4.0 -m "Release v1.4.0"
git push origin v1.4.0
```

See [RELEASE_PROCESS.md](RELEASE_PROCESS.md) for the full checklist.
