# Release Process Guide

This document describes how to create and publish releases for Connie's Uploader Ultimate.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Release Workflow](#release-workflow)
- [Creating a Release](#creating-a-release)
- [Release Checklist](#release-checklist)
- [Troubleshooting](#troubleshooting)
- [Rollback Procedure](#rollback-procedure)

## Overview

Our release process is fully automated using GitHub Actions. When you push a version tag, the workflow automatically:

1. ✅ Builds cross-platform binaries (Windows, Linux, macOS)
2. ✅ Generates SHA256 checksums for verification
3. ✅ Extracts release notes from CHANGELOG.md
4. ✅ Creates a GitHub Release with all artifacts
5. ✅ Uploads packaged distributions (.zip, .tar.gz)

## Prerequisites

Before creating a release, ensure:

- [ ] All tests pass on the main branch
- [ ] CHANGELOG.md is updated with the new version
- [ ] Version number follows [Semantic Versioning](https://semver.org/)
- [ ] You have push access to the repository
- [ ] All security scans pass (see `.github/workflows/security.yml`)

## Release Workflow

### Automated Release (Tag-based) - Recommended

This is the primary method for creating releases.

**Step 1: Update CHANGELOG.md**

Add a new version section at the top of `CHANGELOG.md`:

```markdown
## [1.0.1] - 2025-01-15

### Added
- New feature X
- Enhancement Y

### Fixed
- Bug fix Z

### Changed
- Improvement W
```

**Step 2: Commit Changes**

```bash
git add CHANGELOG.md
git commit -m "Prepare release v1.0.1"
git push origin main
```

**Step 3: Create and Push Tag**

```bash
# Create an annotated tag
git tag -a v1.0.1 -m "Release v1.0.1"

# Push the tag to trigger the release workflow
git push origin v1.0.1
```

**Step 4: Monitor the Release**

1. Go to the [Actions tab](https://github.com/conniecombs/GolangVersion/actions)
2. Watch the "Release - Build and Publish" workflow
3. Once complete, check the [Releases page](https://github.com/conniecombs/GolangVersion/releases)

### Manual Release (Workflow Dispatch)

You can also trigger a release manually from the GitHub UI:

1. Go to **Actions** → **Release - Build and Publish**
2. Click **Run workflow**
3. Enter the version (e.g., `v1.0.1`)
4. Click **Run workflow**

This is useful for:
- Re-releasing a version
- Creating releases from branches
- Testing the release process

## Release Checklist

Use this checklist when creating a new release:

### Pre-Release

- [ ] Run full test suite locally: `go test ./... && python -m pytest`
- [ ] Update version in CHANGELOG.md
- [ ] Review all changes since last release
- [ ] Ensure security scans pass (check GitHub Actions)
- [ ] Update README.md if needed (features, installation)
- [ ] Test build on all platforms locally (optional but recommended)

### Release

- [ ] Create version entry in CHANGELOG.md
- [ ] Commit and push to main branch
- [ ] Create annotated git tag: `git tag -a vX.Y.Z -m "Release vX.Y.Z"`
- [ ] Push tag: `git push origin vX.Y.Z`
- [ ] Monitor GitHub Actions workflow

### Post-Release

- [ ] Verify release appears on [Releases page](https://github.com/conniecombs/GolangVersion/releases)
- [ ] Download and test artifacts on each platform
- [ ] Verify SHA256 checksums match
- [ ] Update documentation/website if applicable
- [ ] Announce release (social media, forums, etc.)

## Version Numbering

We follow [Semantic Versioning](https://semver.org/):

- **MAJOR** (v2.0.0): Incompatible API changes
- **MINOR** (v1.1.0): New functionality, backwards-compatible
- **PATCH** (v1.0.1): Bug fixes, backwards-compatible

Examples:
- Bug fix: `v1.0.0` → `v1.0.1`
- New feature: `v1.0.1` → `v1.1.0`
- Breaking change: `v1.1.0` → `v2.0.0`

## Release Artifacts

Each release includes:

### Windows
- `ConniesUploader.exe` - Standalone executable
- `ConniesUploader.exe.sha256` - Checksum file
- `ConniesUploader-vX.Y.Z-windows-x64.zip` - ZIP package

### Linux
- `ConniesUploader-vX.Y.Z-linux-x64.tar.gz` - Tarball with binary and checksum

### macOS
- `ConniesUploader-vX.Y.Z-macos-x64.zip` - ZIP package with binary and checksum

### Additional
- `CHANGELOG.md` - Full changelog file

## Verifying Downloads

Users should verify downloads using SHA256 checksums:

**Windows (PowerShell):**
```powershell
certutil -hashfile ConniesUploader.exe SHA256
# Compare output with ConniesUploader.exe.sha256
```

**Linux/macOS:**
```bash
sha256sum ConniesUploader  # or shasum -a 256 on macOS
# Compare with included .sha256 file
```

## Troubleshooting

### Workflow Fails to Build

**Problem:** Build fails on one platform

**Solution:**
1. Check the Actions logs for specific errors
2. Test build locally on that platform
3. Fix the issue and push a new commit
4. Delete the tag: `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z`
5. Re-create the tag with the fix

### Release Notes Are Empty

**Problem:** Release has no description or wrong content

**Solution:**
1. Ensure CHANGELOG.md has a section for this version
2. Format must be: `## [X.Y.Z] - YYYY-MM-DD`
3. Re-run the workflow or edit the release manually on GitHub

### Checksum Mismatch

**Problem:** Users report checksum doesn't match

**Solution:**
1. Download the artifact from the release
2. Calculate checksum locally
3. If they match, ask user to re-download (corruption)
4. If they don't match, delete release and investigate build process

### Tag Already Exists

**Problem:** `git push` fails because tag already exists

**Solution:**
```bash
# Delete local tag
git tag -d vX.Y.Z

# Delete remote tag
git push origin :refs/tags/vX.Y.Z

# Re-create tag
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

## Rollback Procedure

If a release has critical issues:

### Option 1: Delete Release (Pre-Production)

If no one has downloaded the release yet:

1. Go to [Releases page](https://github.com/conniecombs/GolangVersion/releases)
2. Click **Delete** on the problematic release
3. Delete the git tag:
   ```bash
   git tag -d vX.Y.Z
   git push origin :refs/tags/vX.Y.Z
   ```

### Option 2: Create Patch Release (Production)

If users have already downloaded the release:

1. Fix the critical issue
2. Update CHANGELOG.md with the patch version
3. Create a new patch release (e.g., v1.0.1 → v1.0.2)
4. Mark the problematic release as pre-release:
   - Edit the release on GitHub
   - Check **This is a pre-release**
   - Add warning to description

### Option 3: Yanked Release

For security issues:

1. **DO NOT DELETE** - users need to know about the vulnerability
2. Edit the release and add prominent security warning
3. Create a security advisory on GitHub
4. Release a patched version immediately
5. Update README.md with security notice

## CI/CD Pipeline Details

### Workflow Files

- `.github/workflows/release.yml` - Main release workflow
- `.github/workflows/ci.yml` - Continuous integration (tests)
- `.github/workflows/security.yml` - Security scanning

### Build Process

1. **Prepare Release** - Extract version and release notes
2. **Build Windows** - PyInstaller build on Windows runner
3. **Build Linux** - PyInstaller build on Ubuntu runner
4. **Build macOS** - PyInstaller build on macOS runner
5. **Publish Release** - Collect artifacts and create GitHub release

### Caching

The workflow uses caching for faster builds:
- Go modules cache
- Python pip cache
- Build cache

## Best Practices

1. **Never force-push tags** - Tags should be immutable
2. **Always test locally first** - Build on your machine before releasing
3. **Keep CHANGELOG.md updated** - Update it with every PR/commit
4. **Use draft releases for testing** - Create draft releases to test the process
5. **Announce releases promptly** - Keep users informed
6. **Monitor download stats** - Track which platforms are most popular
7. **Collect feedback** - Use GitHub Discussions or Issues for feedback

## Security Considerations

- All releases are scanned for vulnerabilities
- Dependencies are pinned to exact versions
- SHA256 checksums prevent tampering
- Code is signed (Windows builds can be signed with certificates)
- No secrets are exposed in logs or artifacts

## Additional Resources

- [GitHub Releases Documentation](https://docs.github.com/en/repositories/releasing-projects-on-github)
- [Semantic Versioning Specification](https://semver.org/)
- [Keep a Changelog](https://keepachangelog.com/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)

## Questions?

If you have questions about the release process:

1. Check existing [GitHub Issues](https://github.com/conniecombs/GolangVersion/issues)
2. Review [GitHub Discussions](https://github.com/conniecombs/GolangVersion/discussions)
3. Create a new issue with the `question` label

---

**Last Updated:** 2025-01-01
**Maintained By:** conniecombs
