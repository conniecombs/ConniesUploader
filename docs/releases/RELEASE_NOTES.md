# Release Notes

This directory contains release notes and publishing guidance for Connie's Uploader Ultimate.

## Latest Release

**v1.3.0 - "Protocol Hardening & Release Reliability"**
Release date: June 2, 2026
Tag: `v1.3.0`

Read the full notes: [RELEASE_NOTES_v1.3.0.md](RELEASE_NOTES_v1.3.0.md)

### Summary

- Expanded the generic Go HTTP runner with chained prerequests, cookie sessions, template substitution, and richer extraction support.
- Added sidecar request IDs to keep concurrent upload responses correlated.
- Added Imgur request-building support for the shared sidecar workflow.
- Updated Go security-sensitive dependencies and pinned strict Python audit tools.
- Tightened release/security gates around `govulncheck`, gosec, `pip-audit`, and Bandit.

## Release History

| Version | Date | Focus | Notes |
|---------|------|-------|-------|
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

The release workflow is tag-based. For v1.3.0, use:

```bash
git tag -a v1.3.0 -m "Release v1.3.0"
git push origin v1.3.0
```

See [RELEASE_PROCESS.md](RELEASE_PROCESS.md) for the full checklist.
