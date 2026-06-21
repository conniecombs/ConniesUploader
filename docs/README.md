# Documentation Index

Complete guide to all documentation for Connie's Uploader Ultimate.

## 📚 Quick Links

| Document | Description | Location |
|----------|-------------|----------|
| **README** | Main project documentation | [Root](../README.md) |
| **Architecture** | System design and architecture | [Root](../ARCHITECTURE.md) |
| **Contributing** | How to contribute | [Root](../CONTRIBUTING.md) |
| **Code of Conduct** | Community standards | [Root](../CODE_OF_CONDUCT.md) |
| **Changelog** | Version history | [Root](../CHANGELOG.md) |
| **Remaining Issues** | Technical debt tracker | [Root](../REMAINING_ISSUES.md) |

---

## 🎯 Documentation by Purpose

### For New Users
Start here if you're new to the project:

1. **[README.md](../README.md)** - Overview, features, installation, and quick start
2. **[User Tutorial](guides/USER_TUTORIAL.md)** - Complete walkthrough of uploads, settings, galleries, templates, and output
3. **[Build Troubleshooting](guides/BUILD_TROUBLESHOOTING.md)** - Common build issues and solutions
4. **[Latest Release Notes](releases/RELEASE_NOTES_v1.4.0.md)** - Latest detailed release notes

### For Contributors
Development and contribution guides:

1. **[CONTRIBUTING.md](../CONTRIBUTING.md)** - Contribution guidelines and workflow
2. **[ARCHITECTURE.md](../ARCHITECTURE.md)** - System architecture and design patterns
3. **[Plugin Creation Guide](guides/PLUGIN_CREATION_GUIDE.md)** - Create new service plugins
4. **[Schema Plugin Guide](guides/SCHEMA_PLUGIN_GUIDE.md)** - Schema-based plugin development
5. **[Release Process](releases/RELEASE_PROCESS.md)** - How to create releases

### For Maintainers
Project management and planning:

1. **[REMAINING_ISSUES.md](../REMAINING_ISSUES.md)** - Technical debt and roadmap (45 issues completed)
2. **[CHANGELOG.md](../CHANGELOG.md)** - Detailed version history
3. **[Release Process](releases/RELEASE_PROCESS.md)** - Release workflow and checklist

---

## 📂 Directory Structure

```
docs/
├── README.md                    # This file - documentation index
├── guides/                      # Developer and user guides
│   ├── PLUGIN_CREATION_GUIDE.md
│   ├── SCHEMA_PLUGIN_GUIDE.md
│   ├── BUILD_TROUBLESHOOTING.md
│   └── USER_TUTORIAL.md
├── releases/                    # Release documentation
│   ├── RELEASE_NOTES.md
│   ├── RELEASE_NOTES_v1.4.0.md
│   ├── RELEASE_NOTES_v1.3.0.md
│   ├── RELEASE_NOTES_v1.2.4.md
│   ├── RELEASE_NOTES_v1.2.2.md
│   ├── RELEASE_NOTES_v1.1.0.md
│   ├── RELEASE_NOTES_v1.0.5.md
│   ├── release_notes_v1.0.4.md
│   └── RELEASE_PROCESS.md
└── history/                     # Historical documentation and analyses
    ├── PHASE1_IMPLEMENTATION_SUMMARY.md
    ├── PHASE2_METADATA_SYSTEM.md
    ├── PHASE3_AUTO_DISCOVERY.md
    ├── PHASE4_STANDARD_CONFIG_KEYS.md
    ├── PHASE5_HELPER_UTILITIES.md
    ├── PHASE6_TESTING_FRAMEWORK.md
    ├── BUILD_VERIFICATION_REPORT.md
    ├── CODE_REVIEW_VALIDATION.md
    ├── CONFIG_KEY_ANALYSIS.md
    ├── CRITICAL_FIX_UPLOAD_DEADLOCK.md
    ├── DOCUMENTATION.md
    ├── DRAG_DROP_FIX_SUMMARY.md
    ├── FEATURES.md
    ├── IMPLEMENTATION_ANALYSIS.md
    ├── IMPROVEMENTS.md
    ├── MOCK_UPLOAD_TESTING.md
    ├── PHASE5_PATTERN_ANALYSIS.md
    ├── PLUGIN_ARCHITECTURE_ANALYSIS.md
    ├── PROJECT_STATUS.md
    ├── PR_DESCRIPTION.md
    ├── PR_SUBMISSION_SUMMARY.md
    ├── REFACTORING_PLAN.md
    ├── RELEASE_PREPARATION_SUMMARY.md
    ├── STDERR_DEADLOCK_FIX.md
    └── TEST_RESULTS.md
```

---

## 📖 Core Documentation (Root Directory)

### [README.md](../README.md) (30KB)
Main project documentation covering:
- Features and capabilities
- Installation instructions
- Quick start guide
- Troubleshooting
- Version history

### [ARCHITECTURE.md](../ARCHITECTURE.md) (19KB)
Complete system architecture documentation:
- Plugin-driven architecture (v2.4.0)
- Go HTTP runner design
- Python-Go bridge communication
- Session management
- Generic HTTP request protocol

### [CONTRIBUTING.md](../CONTRIBUTING.md) (7KB)
Contribution guidelines:
- Development setup
- Code style and standards
- Testing requirements
- Pull request process
- Plugin development workflow

### [CHANGELOG.md](../CHANGELOG.md) (22KB)
Detailed version history:
- All releases from v1.0.0 to v1.4.0
- Feature additions
- Bug fixes
- Breaking changes

### [REMAINING_ISSUES.md](../REMAINING_ISSUES.md) (39KB)
Technical debt tracker and roadmap:
- **Status**: 45 issues completed, optional future enhancements only
- **High Priority**: ✅ 100% complete (6/6)
- **Medium Priority**: ✅ 100% complete (17/17)
- **Low Priority**: 100% complete (12/12)
- Implementation notes for completed phases

---

## 🛠️ Developer Guides (docs/guides/)

### [PLUGIN_CREATION_GUIDE.md](guides/PLUGIN_CREATION_GUIDE.md) (28KB)
Comprehensive guide to creating upload service plugins:
- Plugin structure and requirements
- API integration patterns
- Gallery creation and management
- Error handling best practices
- Testing and validation
- Real examples (imx.to, pixhost.to, etc.)

### [SCHEMA_PLUGIN_GUIDE.md](guides/SCHEMA_PLUGIN_GUIDE.md) (16KB)
Schema-based plugin development guide:
- Schema definition format
- Field types and validation
- Dynamic UI generation
- Settings persistence
- Advanced features (regex extraction, templates)

### [BUILD_TROUBLESHOOTING.md](guides/BUILD_TROUBLESHOOTING.md) (4KB)
Common build issues and solutions:
- Go compilation errors
- Python dependency issues
- Platform-specific problems
- Cross-platform build guide

### [USER_TUTORIAL.md](guides/USER_TUTORIAL.md)
Complete end-user walkthrough:
- Basic upload workflow
- All visible app settings
- Service-specific upload options
- Gallery Manager, Template Editor, ViperGirls posting, output files, and troubleshooting

---

## 🚀 Release Documentation (docs/releases/)

### [RELEASE_NOTES_v1.4.0.md](releases/RELEASE_NOTES_v1.4.0.md)
Latest release - "User Experience Polish & Safer Upload Controls" (June 20, 2026):
- Task-oriented empty queue, checks, activity, and completion states
- Clearer queue rows with visible actions, retry controls, and failed reasons
- Worker Count and Thread Limit grouped in Advanced App Settings with enforced ranges

### [RELEASE_NOTES_v1.3.0.md](releases/RELEASE_NOTES_v1.3.0.md)
"Protocol Hardening & Release Reliability" release (June 2, 2026):
- Generic HTTP runner support for chained prerequests, cookie sessions, template substitution, and richer extraction
- Sidecar request IDs that keep concurrent upload responses correlated
- Security workflow hardening for Go and Python dependency scans

### [RELEASE_NOTES_v1.2.4.md](releases/RELEASE_NOTES_v1.2.4.md)
"CI & Packaging Reliability" release (May 20, 2026):
- Packaged executable startup fix for the `tkinter.tix` import crash
- Pillow `12.2.0` security update and `pip-audit` dependency scanning
- Cross-platform CI test hardening for Windows and macOS

### [RELEASE_NOTES_v1.2.2.md](releases/RELEASE_NOTES_v1.2.2.md)
"Batch Upload Stability" release (Jan 22, 2026):
- Worker count settings correctly apply via sidecar restart
- Large batches process without UI stalls
- Progress and output-folder handling fixes

### [RELEASE_NOTES_v1.1.0.md](releases/RELEASE_NOTES_v1.1.0.md) (15KB)
"Performance & Polish" release (Jan 15-16, 2026):
- Comprehensive Python test suite (2,200+ lines)
- 20-30% faster uploads (HTTP connection pooling)
- ALL HIGH PRIORITY ISSUES RESOLVED (6/6)
- 30 bug fixes and enhancements

### [RELEASE_NOTES_v1.0.5.md](releases/RELEASE_NOTES_v1.0.5.md) (19KB)
"Resilience & Intelligence" release (Jan 13, 2026):
- 🔄 Intelligent retry logic (15-20% fewer failures)
- 📊 Real-time progress streaming
- 🔒 Enhanced security validation
- ⚡ Configurable rate limiting

### [RELEASE_NOTES.md](releases/RELEASE_NOTES.md) (2KB)
General release notes and summary of all versions.

### [RELEASE_PROCESS.md](releases/RELEASE_PROCESS.md) (9KB)
How to create and publish releases:
- Version bumping checklist
- Building and testing
- GitHub release creation
- Documentation updates

---

## 📜 Historical Documentation (docs/history/)

Archive of implementation notes, phase summaries, and technical analyses from the project's development history.

### Implementation Phases
- **[PHASE1_IMPLEMENTATION_SUMMARY.md](history/PHASE1_IMPLEMENTATION_SUMMARY.md)** - Initial plugin system
- **[PHASE2_METADATA_SYSTEM.md](history/PHASE2_METADATA_SYSTEM.md)** - Metadata extraction
- **[PHASE3_AUTO_DISCOVERY.md](history/PHASE3_AUTO_DISCOVERY.md)** - Plugin auto-discovery
- **[PHASE4_STANDARD_CONFIG_KEYS.md](history/PHASE4_STANDARD_CONFIG_KEYS.md)** - Config standardization
- **[PHASE5_HELPER_UTILITIES.md](history/PHASE5_HELPER_UTILITIES.md)** - Helper utilities
- **[PHASE6_TESTING_FRAMEWORK.md](history/PHASE6_TESTING_FRAMEWORK.md)** - Testing infrastructure

### Technical Analyses
- **[PLUGIN_ARCHITECTURE_ANALYSIS.md](history/PLUGIN_ARCHITECTURE_ANALYSIS.md)** - Plugin system design
- **[IMPLEMENTATION_ANALYSIS.md](history/IMPLEMENTATION_ANALYSIS.md)** - Implementation review
- **[CODE_REVIEW_VALIDATION.md](history/CODE_REVIEW_VALIDATION.md)** - Code quality review
- **[CONFIG_KEY_ANALYSIS.md](history/CONFIG_KEY_ANALYSIS.md)** - Configuration analysis

### Bug Fixes & Improvements
- **[CRITICAL_FIX_UPLOAD_DEADLOCK.md](history/CRITICAL_FIX_UPLOAD_DEADLOCK.md)** - Deadlock resolution
- **[STDERR_DEADLOCK_FIX.md](history/STDERR_DEADLOCK_FIX.md)** - Stderr handling fix
- **[DRAG_DROP_FIX_SUMMARY.md](history/DRAG_DROP_FIX_SUMMARY.md)** - Drag-and-drop UX fix
- **[IMPROVEMENTS.md](history/IMPROVEMENTS.md)** - General improvements log
- **[FEATURES.md](history/FEATURES.md)** - Features documentation

### Testing & Validation
- **[TEST_RESULTS.md](history/TEST_RESULTS.md)** - Test execution results
- **[MOCK_UPLOAD_TESTING.md](history/MOCK_UPLOAD_TESTING.md)** - Mock upload tests
- **[BUILD_VERIFICATION_REPORT.md](history/BUILD_VERIFICATION_REPORT.md)** - Build verification

### Project Management
- **[PROJECT_STATUS.md](history/PROJECT_STATUS.md)** - Historical status snapshot
- **[REFACTORING_PLAN.md](history/REFACTORING_PLAN.md)** - Refactoring strategy
- **[PR_DESCRIPTION.md](history/PR_DESCRIPTION.md)** - Pull request documentation
- **[PR_SUBMISSION_SUMMARY.md](history/PR_SUBMISSION_SUMMARY.md)** - PR submission notes
- **[RELEASE_PREPARATION_SUMMARY.md](history/RELEASE_PREPARATION_SUMMARY.md)** - Release prep

---

## 🎯 Documentation by Topic

### Architecture & Design
- [ARCHITECTURE.md](../ARCHITECTURE.md) - System architecture
- [history/PLUGIN_ARCHITECTURE_ANALYSIS.md](history/PLUGIN_ARCHITECTURE_ANALYSIS.md) - Plugin design
- [history/REFACTORING_PLAN.md](history/REFACTORING_PLAN.md) - Refactoring strategy

### Plugin Development
- [guides/PLUGIN_CREATION_GUIDE.md](guides/PLUGIN_CREATION_GUIDE.md) - Main plugin guide
- [guides/SCHEMA_PLUGIN_GUIDE.md](guides/SCHEMA_PLUGIN_GUIDE.md) - Schema-based plugins
- [history/PHASE3_AUTO_DISCOVERY.md](history/PHASE3_AUTO_DISCOVERY.md) - Auto-discovery system

### Testing
- [CONTRIBUTING.md](../CONTRIBUTING.md) - Testing requirements
- [history/PHASE6_TESTING_FRAMEWORK.md](history/PHASE6_TESTING_FRAMEWORK.md) - Test framework
- [history/TEST_RESULTS.md](history/TEST_RESULTS.md) - Test results
- [history/MOCK_UPLOAD_TESTING.md](history/MOCK_UPLOAD_TESTING.md) - Mock testing

### Build & Release
- [guides/BUILD_TROUBLESHOOTING.md](guides/BUILD_TROUBLESHOOTING.md) - Build issues
- [releases/RELEASE_PROCESS.md](releases/RELEASE_PROCESS.md) - Release workflow
- [history/BUILD_VERIFICATION_REPORT.md](history/BUILD_VERIFICATION_REPORT.md) - Build verification

### Bug Fixes
- [history/CRITICAL_FIX_UPLOAD_DEADLOCK.md](history/CRITICAL_FIX_UPLOAD_DEADLOCK.md) - Upload deadlock
- [history/STDERR_DEADLOCK_FIX.md](history/STDERR_DEADLOCK_FIX.md) - Stderr deadlock
- [history/DRAG_DROP_FIX_SUMMARY.md](history/DRAG_DROP_FIX_SUMMARY.md) - Drag-and-drop fix

---

## 📊 Documentation Statistics

| Category | Count | Total Size |
|----------|-------|------------|
| **Root Documentation** | 6 files | ~110 KB |
| **Developer Guides** | 4 files | ~67 KB |
| **Release Documentation** | 7 files | ~65 KB |
| **Historical Documentation** | 26 files | ~200+ KB |
| **Additional Markdown** | 3 files | ~15 KB |
| **Total** | **46 files** | **~457 KB** |

---

## 🔄 Recent Documentation Updates

**2026-05-22**: User Tutorial
- Added a complete user tutorial covering upload flow, all visible settings, templates, galleries, ViperGirls posting, and troubleshooting
- Added fresh main window, upload queue, and template editor screenshots

**2026-05-20**: v1.2.4 Release
- Published RELEASE_NOTES_v1.2.4.md
- Updated current release links, dependency security notes, and tag examples
- Synced project version references to v1.2.4

**2026-01-16**: Documentation reorganization (Issue #24)
- Moved 8 files to `docs/history/` (analysis and status docs)
- Moved 3 files to `docs/guides/` (plugin and build guides)
- Moved 5 files to `docs/releases/` (release documentation)
- Root directory reduced from 21 to 5 essential files (76% reduction)
- Created this comprehensive documentation index

**2026-01-16**: v1.1.0 Release
- Updated REMAINING_ISSUES.md with Phase 8 completion
- Published RELEASE_NOTES_v1.1.0.md
- Updated README.md with latest features

**2026-01-13**: v1.0.5 Release
- Published comprehensive RELEASE_NOTES_v1.0.5.md (704 lines)
- Created FEATURES.md guide (501 lines)
- Updated ARCHITECTURE.md with graceful shutdown

---

## 💡 Need Help?

- **General questions**: Start with [README.md](../README.md)
- **Build issues**: See [BUILD_TROUBLESHOOTING.md](guides/BUILD_TROUBLESHOOTING.md)
- **Contributing**: Read [CONTRIBUTING.md](../CONTRIBUTING.md)
- **Plugin development**: Check [PLUGIN_CREATION_GUIDE.md](guides/PLUGIN_CREATION_GUIDE.md)
- **Architecture questions**: Review [ARCHITECTURE.md](../ARCHITECTURE.md)
- **Technical debt**: See [REMAINING_ISSUES.md](../REMAINING_ISSUES.md)

---

**Last Updated**: 2026-06-20
**Documentation Version**: 2.1
**Project Version**: v1.4.0
