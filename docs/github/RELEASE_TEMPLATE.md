<!--
Release Notes Template for Connie's Uploader Ultimate

Use this template when creating a new version section in docs/CHANGELOG.md
The automated release workflow will extract this content for the GitHub Release
-->

## [VERSION] - YYYY-MM-DD

### 🎉 Highlights

<!-- 2-3 sentences summarizing the most important changes in this release -->

---

### ✨ Added

<!-- New features and capabilities -->

- **Feature Name** - Description of the feature
  - Additional details or use case
  - Related issue/PR if applicable

### 🔧 Fixed

<!-- Bug fixes and corrections -->

- **Bug Name** - Description of what was fixed
  - Impact: [High/Medium/Low]
  - Root cause (if interesting/educational)

### 🚀 Improved

<!-- Performance improvements and optimizations -->

- **Component Name** - Description of improvement
  - Metrics: before/after if available
  - Impact on user experience

### 🔒 Security

<!-- Security-related changes - ALWAYS highlight these -->

- **Security Issue** - Description
  - CVE reference if applicable
  - Severity: [Critical/High/Medium/Low]
  - Recommendation for users

### 📊 Performance

<!-- If this section is significant, separate from Improved -->

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Build Time | X min | Y min | Z% |
| Binary Size | X MB | Y MB | Z% |
| Memory Usage | X MB | Y MB | Z% |

### 🔄 Changed

<!-- Breaking changes or significant modifications to existing features -->

- **Component** - Description of change
  - **⚠️ Breaking Change:** If applicable
  - Migration guide or compatibility notes

### 🗑️ Deprecated

<!-- Features marked for future removal -->

- **Feature Name** - Will be removed in vX.Y.Z
  - Replacement or alternative
  - Migration timeline

### ❌ Removed

<!-- Features completely removed -->

- **Feature Name** - Reason for removal
  - Alternative solution if available

---

### 📦 Installation

**Download the latest release:**

👉 **[Download vVERSION](https://github.com/conniecombs/ConniesUploader/releases/tag/vVERSION)**

**Available builds:**
- Windows: `ConniesUploader-vVERSION-windows-x64.zip`
- Linux: `ConniesUploader-vVERSION-linux-x64.tar.gz`
- macOS: `ConniesUploader-vVERSION-macos-x64.zip`

**Verify your download:**
```bash
# Windows (PowerShell)
certutil -hashfile ConniesUploader.exe SHA256

# Linux/macOS
sha256sum ConniesUploader  # or shasum -a 256 on macOS
```

---

### 🐛 Known Issues

<!-- Document any known issues or limitations -->

- Issue description
  - Workaround if available
  - Expected fix version

### 📝 Notes

<!-- Additional information for this release -->

- **Go Version:** 1.25.9+ required for local builds; CI currently builds with Go 1.26.4
- **Python Version:** 3.11+ required
- **Tested On:** Windows 11, Ubuntu 22.04, macOS 13+

### 🙏 Contributors

<!-- Thank contributors if applicable -->

Special thanks to:
- @username for Feature X
- @username for Bug fix Y

### 📈 Statistics

<!-- Optional: Release metrics -->

- Files changed: X
- Lines added: +Y
- Lines removed: -Z
- Commits: N
- Contributors: M

---

### 🔗 Links

- [Full Changelog](https://github.com/conniecombs/ConniesUploader/compare/vPREVIOUS...vVERSION)
- [Documentation](https://github.com/conniecombs/ConniesUploader#readme)
- [Report Issues](https://github.com/conniecombs/ConniesUploader/issues)

---

**Note**: This tool is intended for personal use and legitimate content sharing. Users are responsible for complying with the terms of service of all image hosting platforms used.
