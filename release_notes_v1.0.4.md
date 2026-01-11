## v1.0.4 - Release Automation & Build Verification Enhancements

### ✨ Added

#### **Enhanced Release Automation**
- **Modern GitHub Actions Release Workflow**
  - Upgraded from deprecated `actions/create-release@v1` to `softprops/action-gh-release@v2`
  - Added workflow_dispatch support for manual release triggering
  - Intelligent CHANGELOG.md extraction for release notes
  - Automatic artifact collection and publishing
  - Build caching for faster releases (Go modules + pip)

- **Comprehensive Release Documentation**
  - New `RELEASE_PROCESS.md` guide with step-by-step instructions
  - Release checklist and best practices
  - Troubleshooting guide for common release issues
  - Rollback procedures for critical issues
  - Security considerations and verification steps

- **Release Template**
  - `.github/RELEASE_TEMPLATE.md` for consistent release notes
  - Structured sections for all change types
  - Performance metrics template
  - Installation and verification instructions

### 🚀 Improved

#### **Release Workflow Enhancements**
- **Better Artifact Organization**
  - Separate build artifacts for each platform
  - Consolidated release asset preparation
  - Clearer naming for cross-platform binaries
  - Improved checksum file organization

- **Build Verification**
  - **Critical:** Sidecar bundling verification now fails build if not detected
  - Pre-build verification ensures Go sidecar exists before PyInstaller runs
  - Post-build size verification (40MB minimum) ensures sidecar was bundled
  - Enhanced error messages with debug information for troubleshooting
  - Better artifact validation before publishing

- **Performance**
  - Parallel platform builds (Windows, Linux, macOS)
  - Go modules caching reduces build time by ~60%
  - Pip caching for faster Python dependency installation
  - Artifact retention optimization (5 days for builds, 1 day for notes)

### 📝 Changed

#### **Workflow Structure**
- Reorganized release workflow into distinct jobs:
  1. `prepare-release` - Version and release notes extraction
  2. `build-windows` - Windows build with PyInstaller
  3. `build-linux` - Linux build with PyInstaller
  4. `build-macos` - macOS build with PyInstaller
  5. `publish-release` - GitHub Release creation

#### **Release Notes Extraction**
- Automatic extraction of version-specific content from CHANGELOG.md
- Falls back to git log if CHANGELOG section not found
- Improved parsing for Keep a Changelog format
- Better error handling for malformed CHANGELOG entries

### 🔒 Security

#### **Release Security Improvements**
- SHA256 checksums generated for all artifacts
- Checksums included in release assets
- Documented verification process for users
- No secrets exposed in workflow logs

### 📚 Documentation

#### **Updated Documentation**
- README.md enhanced with release automation section
- RELEASE_PROCESS.md comprehensive guide added
- RELEASE_TEMPLATE.md for maintainers
- Workflow dispatch instructions
- Best practices and troubleshooting

---

**Installation:**

Download the latest release for your platform from the assets below:
- **Windows**: `ConniesUploader-windows.zip`
- **Linux**: `ConniesUploader-linux.tar.gz`
- **macOS**: `ConniesUploader-macos.zip`

All releases include SHA256 checksums for verification.

**Full Changelog**: https://github.com/conniecombs/conniesuploader/compare/v1.0.3...v1.0.4
