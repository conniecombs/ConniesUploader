# Remaining Codebase Issues - Technical Debt Tracker

**Created**: 2026-01-03
**Last Updated**: 2026-01-10
**Product Version**: v1.0.0
**Architecture Version**: v2.4.0
**Status**: Phase 1 ✅ Complete | Phase 2 ✅ Complete | Phase 3 ✅ Complete
**Total Remaining**: 31 issues (4 completed in Phase 3)

---

## ✅ Completed (Phases 1, 2, & 3)

### Phase 1 - Critical Fixes ✅
- [x] Fix go.mod version format (go 1.24 not 1.24.11)
- [x] Add pytest and flake8 to requirements.txt
- [x] Fix SHA256 hash security issue (removed 32-bit support)
- [x] Fix plugin discovery to include *_v2.py files
- [x] Verify .gitignore properly excludes __pycache__

### Phase 2 - Security & Error Handling ✅
- [x] Fix unsafe subprocess.call usage (now using subprocess.run)
- [x] Fix race condition in sidecar restart (added restart_lock)
- [x] Add custom exception classes (modules/exceptions.py)
- [x] Improve input sanitization (sanitize_filename function)

### Phase 3 - Testing & Code Cleanup ✅ (Partial)
- [x] Add Go unit tests (12.5% coverage, 16 tests)
- [x] Add Python test suite (26 tests passing)
- [x] Run go mod tidy (dependency cleanup)
- [x] Remove duplicate legacy code (451 lines archived)
- [x] Refactor main.py (1,078 → 23 lines, 97.9% reduction!)

---

## 🔴 High Priority Issues (6 remaining, 2 completed)

### Testing & Quality Assurance

#### **Issue #1: No Go Tests**
- **File**: `uploader.go` (1,337 lines)
- **Current**: 0% test coverage for Go code
- **Impact**: Undetected bugs in core upload logic
- **Action Items**:
  - [ ] Create `uploader_test.go` with unit tests
  - [ ] Test upload functions for each service
  - [ ] Test thumbnail generation
  - [ ] Test error handling paths
- **Estimated Effort**: Medium (2-3 days)

#### **Issue #2: Missing Python Tests**
- **Current**: No test files in repository
- **Impact**: Cannot verify code changes, regression bugs
- **Action Items**:
  - [ ] Create `tests/` directory structure
  - [ ] Add tests for plugin_manager
  - [ ] Add tests for sidecar bridge
  - [ ] Add tests for file_handler
  - [ ] Set up pytest configuration
- **Estimated Effort**: Medium (2-3 days)

### Code Organization

#### **Issue #3: Large main.py File** ✅ **COMPLETED**
- **Original Size**: 1,078 lines
- **Refactored** (2026-01-03):
  - main.py → **23 lines** (97.9% reduction! ✨)
  - modules/ui/main_window.py → 1,083 lines (UploaderApp class)
  - modules/ui/safe_scrollable_frame.py → 37 lines (utility widget)
  - modules/ui/__init__.py → 10 lines (package exports)
- **Benefits**: Clear separation, easier testing, simplified entry point
- **Action Items**:
  - [x] Extract UI code to modules/ui/ ✅
  - [x] Create modules/ui/main_window.py ✅


  - [x] Streamline main.py to 23 lines ✅
- **Actual Effort**: 1 hour (faster than estimated!)

#### **Issue #4: Duplicate Legacy Code** ✅ **COMPLETED**
- **Files Archived** (2026-01-03):
  - `pixhost_legacy.py` (103 lines) → `archive/legacy_plugins/`
  - `imx_legacy.py` (74 lines) → `archive/legacy_plugins/`
  - `turbo_legacy.py` (103 lines) → `archive/legacy_plugins/`
  - `vipr_legacy.py` (79 lines) → `archive/legacy_plugins/`
  - `imagebam_legacy.py` (92 lines) → `archive/legacy_plugins/`
- **Total**: 451 lines removed from active codebase
- **Action Items**:
  - [x] Verify no references to legacy files ✅
  - [x] Archive to `archive/` directory ✅
  - [x] Preserve git history via `git mv` ✅
  - [x] Document migration in archive/README.md ✅
- **Actual Effort**: 0.5 days

### Architecture & Design

#### **Issue #5: Incomplete TODO - Tooltip Functionality**
- **File**: `modules/plugins/schema_renderer.py:262`
- **Code**: `# TODO: Implement actual tooltip functionality`
- **Impact**: Feature advertised but not implemented
- **Action Items**:
  - [ ] Implement tooltip rendering in schema UI
  - [ ] Add hover events for schema fields
  - [ ] Test tooltip visibility and positioning
- **Estimated Effort**: Small (0.5 days)

#### **Issue #6: Incomplete Gallery Finalization**
- **File**: `uploader.go:186-189`
- **Function**: `handleFinalizeGallery()`
- **Issue**: Placeholder implementation, Pixhost gallery titles not set
- **Action Items**:
  - [ ] Implement Pixhost API call for gallery finalization
  - [ ] Add error handling for failed finalizations
  - [ ] Test with real Pixhost uploads
- **Estimated Effort**: Medium (1-2 days)

#### **Issue #7: Validation Module Hardcoding**
- **File**: `modules/validation.py:123-138`
- **Function**: `validate_service_name()`
- **Issue**: Hardcoded service list doesn't match plugin discovery
- **Action Items**:
  - [ ] Make validation dynamic based on loaded plugins
  - [ ] Use plugin_manager.get_all_plugins() for validation
  - [ ] Add test to ensure validation matches plugins
- **Estimated Effort**: Small (0.5 days)

#### **Issue #8: No Rate Limiting**
- **Impact**: Potential IP bans from image host services
- **Action Items**:
  - [ ] Implement rate limiter in Go sidecar
  - [ ] Add per-service rate limits (requests/second)
  - [ ] Add exponential backoff on rate limit errors
  - [ ] Use RateLimitException from exceptions.py
- **Estimated Effort**: Medium (2 days)

---

## 🟡 Medium Priority Issues (15 remaining)

### Code Quality

#### **Issue #9: Inconsistent Logging**
- **Files**: Multiple modules
- **Issue**: Mix of `logger.debug()`, `logger.info()`, `print()`
- **Action Items**:
  - [ ] Replace all `print()` with `logger.*()` calls
  - [ ] Standardize log levels (DEBUG, INFO, WARNING, ERROR)
  - [ ] Add logging configuration file
- **Estimated Effort**: Small (1 day)

#### **Issue #10: No Type Hints in Critical Functions**
- **Files**: `main.py`, `upload_manager.py`, `controller.py`
- **Examples**:
  - `main.py:659` - `start_upload()` missing return type
  - `upload_manager.py:22` - `start_batch()` missing param types
- **Action Items**:
  - [ ] Add type hints to all public functions
  - [ ] Add type hints to class attributes
  - [ ] Enable mypy type checking
  - [ ] Add mypy to CI/CD
- **Estimated Effort**: Medium (2-3 days)

#### **Issue #11: Magic Numbers**
- **Examples**:
  - `main.py:174` - `self.after(30000, ...)` hardcoded cleanup interval
  - `uploader.go:114` - `Timeout: 120 * time.Second` not configurable
- **Action Items**:
  - [ ] Extract magic numbers to constants
  - [ ] Create config.py constants section
  - [ ] Document meaning of each constant
- **Estimated Effort**: Small (0.5 days)

#### **Issue #12: Inconsistent Naming Conventions**
- **File**: `uploader.go:75-80`
- **Issue**: Mix of camelCase (`viprEndpoint`) and snake_case (`turbo_endpoint`)
- **Action Items**:
  - [ ] Standardize Go code to camelCase
  - [ ] Standardize Python code to snake_case
  - [ ] Run linters (gofmt, flake8)
- **Estimated Effort**: Small (1 day)

### Configuration & Validation

#### **Issue #13: No Configuration Validation**
- **File**: `modules/settings_manager.py`
- **Issue**: Settings loaded from JSON without schema validation
- **Action Items**:
  - [ ] Define JSON schema for user_settings.json
  - [ ] Validate on load with jsonschema library
  - [ ] Show helpful error messages for invalid configs
  - [ ] Use InvalidConfigException from exceptions.py
- **Estimated Effort**: Medium (1-2 days)

#### **Issue #14: Version String in Multiple Places** ✅ **RESOLVED** (2026-01-10)
- **Status**: Fixed - All version strings now consistent at v1.0.0
- **Locations Updated**:
  - `config.py:8` - `APP_VERSION = "1.0.0"` ✅
  - `README.md:3` - Badge shows v1.0.0 ✅
  - `ARCHITECTURE.md` - Now shows both Product (v1.0.0) and Architecture (v2.4.0) versions ✅
- **Action Items**:
  - [x] Standardize product version to v1.0.0 ✅
  - [ ] Read version in Go from config file (future enhancement)
  - [ ] Auto-update README badge in CI/CD (future enhancement)
- **Estimated Effort**: Completed

#### **Issue #15: No Max File Size Enforcement**
- **File**: `modules/config.py:56`
- **Issue**: `MAX_FILE_SIZE = 50 * 1024 * 1024` defined but not enforced
- **Action Items**:
  - [ ] Check file size in scan_inputs()
  - [ ] Show clear error message for oversized files
  - [ ] Use InvalidFileException from exceptions.py
- **Estimated Effort**: Small (0.5 days)

### Performance & Architecture

#### **Issue #16: No Connection Pooling**
- **File**: `uploader.go:111-114`
- **Issue**: Single HTTP client for all requests
- **Action Items**:
  - [ ] Create per-service HTTP client pools
  - [ ] Configure timeouts per service
  - [ ] Add connection limits
- **Estimated Effort**: Medium (1-2 days)

#### **Issue #17: Deprecated Go Dependency Pattern**
- **File**: `go.mod:8-14`
- **Issue**: Indirect dependencies listed explicitly
- **Action Items**:
  - [ ] Run `go mod tidy`
  - [ ] Let Go manage indirect dependencies automatically
- **Estimated Effort**: Trivial (5 minutes)

#### **Issue #18: Unclear Error Messages**
- **File**: `modules/sidecar.py:60-68`
- **Issue**: Lists 3 paths but doesn't indicate which was expected
- **Action Items**:
  - [ ] Indicate primary vs fallback paths in error
  - [ ] Show which path was attempted
- **Estimated Effort**: Small (0.5 days)

#### **Issue #19: No Mutex for Client**
- **File**: `uploader.go:69-80`
- **Issue**: `stateMutex` protects some globals but not `client`
- **Action Items**:
  - [ ] Add mutex protection for HTTP client access
  - [ ] Or make client immutable after initialization
- **Estimated Effort**: Small (0.5 days)

#### **Issue #20: Incomplete Docstrings**
- **Files**: Multiple Python files
- **Examples**:
  - `main.py:_init_state()` - no docstring
  - `main.py:_create_row()` - no docstring
- **Action Items**:
  - [ ] Add docstrings to all public functions
  - [ ] Add docstrings to all classes
  - [ ] Use Google or NumPy docstring format
- **Estimated Effort**: Medium (2 days)

#### **Issue #21: Missing File Extension Validation**
- **File**: `modules/file_handler.py`
- **Issue**: VALID_EXTENSIONS defined but not used everywhere
- **Action Items**:
  - [ ] Centralize extension checking
  - [ ] Validate extensions before upload
  - [ ] Use InvalidFileException for bad extensions
- **Estimated Effort**: Small (0.5 days)

#### **Issue #22: Unclear Plugin Priority System**
- **File**: `modules/plugin_manager.py:108`
- **Issue**: Default priority 50, no documentation on scale
- **Action Items**:
  - [ ] Document priority system (0-100 scale)
  - [ ] Add priority constants (LOW=25, MEDIUM=50, HIGH=75)
  - [ ] Show plugin load order in logs
- **Estimated Effort**: Small (0.5 days)

#### **Issue #23: README Version Mismatch**
- **File**: `README.md:8`
- **Issue**: Badge shows Go 1.24.11, config shows 3.5.0
- **Action Items**:
  - [ ] Update badge to show app version, not Go version
  - [ ] Use shields.io dynamic badge
  - [ ] Auto-generate from config.py
- **Estimated Effort**: Trivial (15 minutes)

---

## 🔵 Low Priority Issues (12 remaining)

### Documentation

#### **Issue #24: Excessive Documentation**
- **Files**: 23 markdown files (PHASE1.md, PHASE2.md, etc.)
- **Size**: 200KB+ of analysis docs
- **Action Items**:
  - [ ] Archive phase docs to `docs/history/`
  - [ ] Create single `ARCHITECTURE.md`
  - [ ] Create single `CONTRIBUTING.md`
  - [ ] Keep only essential docs in root
- **Estimated Effort**: Small (1 day)

#### **Issue #25: No Contributing Guidelines for Issues**
- **File**: `CONTRIBUTING.md` (exists but incomplete)
- **Action Items**:
  - [ ] Add issue templates to `.github/ISSUE_TEMPLATE/`
  - [ ] Create bug_report.md template
  - [ ] Create feature_request.md template
- **Estimated Effort**: Small (0.5 days)

#### **Issue #26: Missing Alt Text for README Badges**
- **File**: `README.md:3-9`
- **Issue**: Badges have no alt text for accessibility
- **Action Items**:
  - [ ] Add meaningful alt text to all badges
  - [ ] Follow accessibility best practices
- **Estimated Effort**: Trivial (10 minutes)

#### **Issue #27: Missing License Headers**
- **Files**: All source files
- **Action Items**:
  - [ ] Add SPDX license headers to all Python files
  - [ ] Add license headers to all Go files
  - [ ] Create script to auto-add headers
- **Estimated Effort**: Small (1 day)

### Code Hygiene

#### **Issue #28: Build Script Verbosity**
- **File**: `build_uploader.bat` (268 lines)
- **Action Items**:
  - [ ] Consider Makefile or Taskfile
  - [ ] Extract logic into smaller scripts
  - [ ] Add cross-platform build.sh for Linux/Mac
- **Estimated Effort**: Medium (1-2 days)

#### **Issue #29: Unused Imports**
- **File**: `main.py:8`
- **Example**: `import sys` only used once
- **Action Items**:
  - [ ] Run flake8 to detect unused imports
  - [ ] Remove or consolidate imports
  - [ ] Add pre-commit hook to check imports
- **Estimated Effort**: Small (0.5 days)

#### **Issue #30: Comment Typos**
- **File**: `uploader.go:482`
- **Typo**: `thumb_size_contaner` (should be "container")
- **Action Items**:
  - [ ] Run spell checker on comments
  - [ ] Fix all typos
- **Estimated Effort**: Trivial (30 minutes)

#### **Issue #31: Inconsistent String Quotes**
- **Files**: All Python files
- **Issue**: Mix of single `'` and double `"` quotes
- **Action Items**:
  - [ ] Choose one style (prefer double quotes)
  - [ ] Use black formatter to auto-fix
  - [ ] Add black to pre-commit hooks
- **Estimated Effort**: Trivial (10 minutes)

#### **Issue #32: Dead Code**
- **File**: `modules/api.py:26-34`
- **Function**: `check_updates()` - empty placeholder
- **Action Items**:
  - [ ] Implement or remove check_updates()
  - [ ] Add auto-update functionality if keeping
- **Estimated Effort**: Small (0.5 days)

### Features

#### **Issue #33: No Performance Benchmarks**
- **Action Items**:
  - [ ] Create benchmark tests for upload speed
  - [ ] Create benchmark tests for thumbnail generation
  - [ ] Track performance over time
- **Estimated Effort**: Medium (1-2 days)

#### **Issue #34: No Graceful Shutdown**
- **File**: `main.py:188`
- **Issue**: `self.quit()` doesn't cleanly stop Go sidecar
- **Action Items**:
  - [ ] Add shutdown handler to SidecarBridge
  - [ ] Send terminate signal to Go process
  - [ ] Wait for graceful exit or force kill after timeout
- **Estimated Effort**: Small (1 day)

#### **Issue #35: Hardcoded User Agent**
- **File**: `uploader.go:33`
- **Issue**: `UserAgent = "Mozilla/5.0 (Windows NT 10.0..."`
- **Action Items**:
  - [ ] Make user agent configurable
  - [ ] Detect actual OS and build realistic UA
  - [ ] Allow per-service user agents
- **Estimated Effort**: Small (0.5 days)

---

## 📊 Summary Statistics

| Category | Count | Estimated Effort |
|----------|-------|------------------|
| **High Priority** | 8 | 12-19 days |
| **Medium Priority** | 15 | 12-19 days |
| **Low Priority** | 12 | 6-10 days |
| **Total Remaining** | 35 | 30-48 days |

### By Type
- Testing: 2 issues
- Security: 0 issues (all fixed ✅)
- Code Quality: 14 issues
- Documentation: 6 issues
- Architecture: 8 issues
- Features: 5 issues

---

## 🎯 Recommended Next Steps

### Phase 3 - Testing & Refactoring (2-3 weeks)
1. **Priority 1**: Add Go unit tests (#1)
2. **Priority 2**: Add Python test suite (#2)
3. **Priority 3**: Refactor main.py (#3)
4. **Priority 4**: Remove duplicate legacy code (#4)
5. **Priority 5**: Implement rate limiting (#8)

### Phase 4 - Polish & Documentation (1-2 weeks)
6. Add type hints everywhere (#10)
7. Standardize logging (#9)
8. Clean up documentation (#24)
9. Add graceful shutdown (#34)
10. Configuration validation (#13)

---

## 📝 Notes

- **MD5 Password Hashing** (Issue #4 from original report): This is a documented limitation due to ViperGirls' legacy vBulletin API requirement. Not fixable without API changes. Security warning comment already in place.

- **Build Blockers**: All critical build-blocking issues have been resolved in Phase 1 ✅

- **Security Fixes**: All critical security vulnerabilities have been addressed in Phase 2 ✅

---

**Last Updated**: 2026-01-03
**Maintainer**: Connie
**Project**: GolangVersion (Connie's Uploader Ultimate)
