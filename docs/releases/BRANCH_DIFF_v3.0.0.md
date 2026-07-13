# v3.0.0 Branch Difference Record

This record captures the differences between `main` and `Bleeding-Edge` for the v3.0.0 release-preparation pass.

Captured on July 12, 2026 after:

```bash
git fetch origin main Bleeding-Edge --tags --prune
```

GitHub compare source: `conniecombs/ConniesUploader` `main...Bleeding-Edge`

## Compare Summary

| Field | Value |
| --- | --- |
| Base branch | `main` |
| Head branch | `Bleeding-Edge` |
| Compare status | `diverged` |
| Ahead by | 21 commits |
| Behind by | 4 commits |
| Base commit | `07bf56f45bcc21344c0037ec87067ae8f0609b4e` |
| Head commit | `dfc7cf022a27054ca758f0c6d5eabc2916abfc52` |
| Merge base | `210af79e99c018ee3be51b8fb171bf491f1dc311` |
| Branch-side file count | 152 files |
| Branch-side diff stat | 15,576 insertions, 10,243 deletions |

The file list below is the exact branch-side comparison captured before this local release-prep documentation was added. That avoids making the diff record recursively list itself.

## Branch-Only Commits

```text
dfc7cf0 Update .md files
305f18f fix(turbo): resolve sanitized filenames in result pages
34465c1 Move parsing to Python, rate limits to job specs
e978be6 Move ViperGirls workflow ownership to Python
d3942ce Mark Viper extract fields as optional
0a04a4c Support optional fields in pre-request extraction
9abd98c Enhance error handling, build script, and sidecar robustness
45c7adf Tests
236b239 Update clean_generated.py
d641f31 Prepare for BETA release
11bf5a9 Refactor main window into organized mixin-based package
c6e0805 Fix buttons bug
d39f6c2 Fix ViperGirls reply posting flow
4a12a1c Host logic fix
f09a819 Delete Bugs.txt
65bd8a5 Fix Vipr gallery creation and upload targeting
ec82e74 Execute Bleeding Edge Branch
77ca727 Add deferred batch upload + activity log terminal
c313f81 Enhance Turbo uploader, progress & throttling
2c73582 docs: expand Template Editor tutorial
9090f16 Move docs into docs/ and migrate user settings
```

## Main-Only Commits

These commits are on `main` but not in `Bleeding-Edge` at capture time:

```text
07bf56f Update template_manager.py
dd1c593 Remove Unreleased section from CHANGELOG
a280173 Merge pull request #137 from conniecombs/WorkingBranch
bdc50c4 Merge pull request #135 from conniecombs/WorkingBranch
```

## Change Themes

- Source split: Go sidecar files moved under `backend/`, Python GUI/runtime files moved under `frontend/`, and packaging assets moved under `packaging/`.
- Transport architecture: Python now owns host/forum workflow decisions and parsing while Go executes generic upload/request/batch-resolve transport actions.
- UI/runtime: Main window code moved into focused mixins under `frontend/modules/ui/Main_Window/`, with scheduled-post and system-tray surfaces added.
- Plugin behavior: active plugins moved toward declarative Python request specs and Python-owned gallery/forum sequencing.
- Docs and release surfaces: root docs moved under `docs/` while the root `README.md` remains in place; current docs describe the source split, transport contract, activity logging, scheduled posts, and v3 release state.
- Tests: Python tests moved under `frontend/tests/`, Go tests moved under `backend/`, and new contract/gallery/transport coverage was added.

## Full File Status

| Status | Path | Previous path |
| --- | --- | --- |
| A | `.github/ISSUE_TEMPLATE/bug_report.yml` |  |
| A | `.github/ISSUE_TEMPLATE/feature_request.yml` |  |
| M | `.github/workflows/ci.yml` |  |
| M | `.github/workflows/release.yml` |  |
| M | `.github/workflows/security.yml` |  |
| M | `.gitignore` |  |
| D | `.pytest_cache/v/cache/nodeids` |  |
| M | `Makefile` |  |
| M | `README.md` |  |
| R100 | `backend/.golangci.yml` | `.golangci.yml` |
| A | `backend/core/http.go` |  |
| A | `backend/core/http_test.go` |  |
| R100 | `backend/core/output.go` | `core/output.go` |
| R063 | `backend/core/progress.go` | `core/progress.go` |
| R075 | `backend/core/ratelimit.go` | `core/ratelimit.go` |
| R100 | `backend/core/retry.go` | `core/retry.go` |
| A | `backend/core/types.go` |  |
| R100 | `backend/core/util.go` | `core/util.go` |
| R083 | `backend/core/validate.go` | `core/validate.go` |
| R100 | `backend/go.mod` | `go.mod` |
| R100 | `backend/go.sum` | `go.sum` |
| A | `backend/handlers.go` |  |
| R069 | `backend/main.go` | `main.go` |
| R094 | `backend/uploader_additional_test.go` | `uploader_additional_test.go` |
| R060 | `backend/uploader_coverage_test.go` | `uploader_coverage_test.go` |
| R065 | `backend/uploader_helpers_test.go` | `uploader_helpers_test.go` |
| A | `backend/uploader_http_runner_test.go` |  |
| R084 | `backend/uploader_integration_test.go` | `uploader_integration_test.go` |
| R079 | `backend/uploader_test.go` | `uploader_test.go` |
| R100 | `backend/uploader_utils_test.go` | `uploader_utils_test.go` |
| M | `build.sh` |  |
| M | `build_uploader.bat` |  |
| D | `core/http.go` |  |
| D | `core/types.go` |  |
| R055 | `docs/ARCHITECTURE.md` | `ARCHITECTURE.md` |
| R093 | `docs/CHANGELOG.md` | `CHANGELOG.md` |
| R100 | `docs/CODE_OF_CONDUCT.md` | `CODE_OF_CONDUCT.md` |
| R064 | `docs/CONTRIBUTING.md` | `CONTRIBUTING.md` |
| M | `docs/README.md` |  |
| A | `docs/TRANSPORT_CONTRACT.md` |  |
| R072 | `docs/archive/README.md` | `archive/README.md` |
| R096 | `docs/benchmarks/README.md` | `benchmarks/README.md` |
| R100 | `docs/github/ISSUE_TEMPLATE/bug_report.md` | `.github/ISSUE_TEMPLATE/bug_report.md` |
| R100 | `docs/github/ISSUE_TEMPLATE/feature_request.md` | `.github/ISSUE_TEMPLATE/feature_request.md` |
| R096 | `docs/github/RELEASE_TEMPLATE.md` | `.github/RELEASE_TEMPLATE.md` |
| M | `docs/guides/BUILD_TROUBLESHOOTING.md` |  |
| M | `docs/guides/PLUGIN_CREATION_GUIDE.md` |  |
| M | `docs/guides/REPOSITORY_LAYOUT.md` |  |
| M | `docs/guides/SCHEMA_PLUGIN_GUIDE.md` |  |
| M | `docs/guides/USER_TUTORIAL.md` |  |
| M | `docs/history/DOCUMENTATION.md` |  |
| M | `docs/history/README.md` |  |
| R099 | `docs/history/REMAINING_ISSUES.md` | `REMAINING_ISSUES.md` |
| M | `docs/releases/RELEASE_NOTES.md` |  |
| M | `docs/releases/RELEASE_NOTES_v1.2.2.md` |  |
| M | `docs/releases/RELEASE_PROCESS.md` |  |
| R100 | `frontend/.coveragerc` | `.coveragerc` |
| A | `frontend/main.py` |  |
| A | `frontend/modules/api.py` |  |
| R100 | `frontend/modules/auto_poster.py` | `modules/auto_poster.py` |
| R093 | `frontend/modules/config.py` | `modules/config.py` |
| R099 | `frontend/modules/controller.py` | `modules/controller.py` |
| R100 | `frontend/modules/credentials_manager.py` | `modules/credentials_manager.py` |
| R100 | `frontend/modules/dnd.py` | `modules/dnd.py` |
| R100 | `frontend/modules/exceptions.py` | `modules/exceptions.py` |
| R100 | `frontend/modules/file_handler.py` | `modules/file_handler.py` |
| R090 | `frontend/modules/gallery_cache.py` | `modules/gallery_cache.py` |
| R061 | `frontend/modules/gallery_manager.py` | `modules/gallery_manager.py` |
| A | `frontend/modules/gallery_service.py` |  |
| R100 | `frontend/modules/plugin_manager.py` | `modules/plugin_manager.py` |
| R100 | `frontend/modules/plugins/base.py` | `modules/plugins/base.py` |
| R100 | `frontend/modules/plugins/helpers.py` | `modules/plugins/helpers.py` |
| A | `frontend/modules/plugins/imagebam.py` |  |
| R100 | `frontend/modules/plugins/imgur.py` | `modules/plugins/imgur.py` |
| R095 | `frontend/modules/plugins/imx.py` | `modules/plugins/imx.py` |
| R098 | `frontend/modules/plugins/pixhost.py` | `modules/plugins/pixhost.py` |
| R097 | `frontend/modules/plugins/pixhost_v2_legacy.py` | `modules/plugins/pixhost_v2_legacy.py` |
| R100 | `frontend/modules/plugins/schema_renderer.py` | `modules/plugins/schema_renderer.py` |
| R051 | `frontend/modules/plugins/turbo.py` | `modules/plugins/turbo.py` |
| R076 | `frontend/modules/plugins/vipr.py` | `modules/plugins/vipr.py` |
| R087 | `frontend/modules/settings_manager.py` | `modules/settings_manager.py` |
| R097 | `frontend/modules/sidecar.py` | `modules/sidecar.py` |
| R099 | `frontend/modules/template_manager.py` | `modules/template_manager.py` |
| A | `frontend/modules/transport.py` |  |
| A | `frontend/modules/ui/Main_Window/__init__.py` |  |
| A | `frontend/modules/ui/Main_Window/app.py` |  |
| A | `frontend/modules/ui/Main_Window/common.py` |  |
| A | `frontend/modules/ui/Main_Window/cover_helpers.py` |  |
| A | `frontend/modules/ui/Main_Window/diagnostics.py` |  |
| A | `frontend/modules/ui/Main_Window/file_queue.py` |  |
| A | `frontend/modules/ui/Main_Window/gallery_actions.py` |  |
| A | `frontend/modules/ui/Main_Window/layout.py` |  |
| A | `frontend/modules/ui/Main_Window/menu_actions.py` |  |
| A | `frontend/modules/ui/Main_Window/posting.py` |  |
| A | `frontend/modules/ui/Main_Window/runtime.py` |  |
| A | `frontend/modules/ui/Main_Window/settings.py` |  |
| A | `frontend/modules/ui/Main_Window/upload_checks.py` |  |
| R100 | `frontend/modules/ui/__init__.py` | `modules/ui/__init__.py` |
| A | `frontend/modules/ui/main_window.py` |  |
| R100 | `frontend/modules/ui/safe_scrollable_frame.py` | `modules/ui/safe_scrollable_frame.py` |
| A | `frontend/modules/ui/scheduled_posts_window.py` |  |
| A | `frontend/modules/ui/system_tray.py` |  |
| R072 | `frontend/modules/upload_manager.py` | `modules/upload_manager.py` |
| R100 | `frontend/modules/utils.py` | `modules/utils.py` |
| R100 | `frontend/modules/validation.py` | `modules/validation.py` |
| R076 | `frontend/modules/viper_api.py` | `modules/viper_api.py` |
| R100 | `frontend/modules/widgets.py` | `modules/widgets.py` |
| R100 | `frontend/pyproject.toml` | `pyproject.toml` |
| R100 | `frontend/pytest.ini` | `pytest.ini` |
| R094 | `frontend/requirements.txt` | `requirements.txt` |
| R100 | `frontend/tests/__init__.py` | `tests/__init__.py` |
| A | `frontend/tests/test_api_contract.py` |  |
| A | `frontend/tests/test_build_contract.py` |  |
| R100 | `frontend/tests/test_controller.py` | `tests/test_controller.py` |
| R100 | `frontend/tests/test_exceptions.py` | `tests/test_exceptions.py` |
| R100 | `frontend/tests/test_file_handler.py` | `tests/test_file_handler.py` |
| A | `frontend/tests/test_gallery_service.py` |  |
| R092 | `frontend/tests/test_main_window_contract.py` | `tests/test_main_window_contract.py` |
| R100 | `frontend/tests/test_mock_uploads.py` | `tests/test_mock_uploads.py` |
| R100 | `frontend/tests/test_plugin_manager.py` | `tests/test_plugin_manager.py` |
| R073 | `frontend/tests/test_plugins.py` | `tests/test_plugins.py` |
| R056 | `frontend/tests/test_service_settings_contract.py` | `tests/test_service_settings_contract.py` |
| R100 | `frontend/tests/test_sidecar.py` | `tests/test_sidecar.py` |
| R100 | `frontend/tests/test_template_manager.py` | `tests/test_template_manager.py` |
| A | `frontend/tests/test_transport_contract.py` |  |
| R100 | `frontend/tests/test_utils.py` | `tests/test_utils.py` |
| R100 | `frontend/tests/test_validation.py` | `tests/test_validation.py` |
| R071 | `frontend/tests/test_viper_targets.py` | `tests/test_viper_targets.py` |
| D | `handlers.go` |  |
| M | `main.py` |  |
| D | `modules/api.py` |  |
| D | `modules/gallery_service.py` |  |
| D | `modules/plugins/imagebam.py` |  |
| D | `modules/ui/main_window.py` |  |
| R100 | `packaging/logo.ico` | `logo.ico` |
| R100 | `packaging/pyinstaller_hooks/hook-customtkinter.py` | `pyinstaller_hooks/hook-customtkinter.py` |
| M | `scripts/diagnostics/check_plugins.py` |  |
| M | `scripts/diagnostics/check_sidecar_location.py` |  |
| M | `scripts/maintenance/clean_generated.py` |  |
| D | `services/imagebam/imagebam.go` |  |
| D | `services/imx/imx.go` |  |
| D | `services/pixhost/pixhost.go` |  |
| D | `services/pixhost/pixhost_test.go` |  |
| D | `services/service.go` |  |
| D | `services/turbo/turbo.go` |  |
| D | `services/vipergirls/vipergirls.go` |  |
| D | `services/vipr/vipr.go` |  |
| D | `services/vipr/vipr_test.go` |  |
| D | `tests/test_api_contract.py` |  |
| D | `tests/test_build_contract.py` |  |
| D | `tests/test_gallery_service.py` |  |
| D | `uploader_http_runner_test.go` |  |
