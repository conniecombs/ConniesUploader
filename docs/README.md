# Documentation Index

Complete guide to the current documentation for Connie's Uploader.

## Start Here

| Need | Document |
| --- | --- |
| Install, build, run, and understand the project at a glance | [README](../README.md) |
| Learn the app as a user | [User Tutorial](guides/USER_TUTORIAL.md) |
| Master the Template Editor, loops, and formats | [Template Editor Tutorial](guides/TEMPLATE_EDITOR_TUTORIAL.md) |
| Fix source/build/package problems | [Build Troubleshooting](guides/BUILD_TROUBLESHOOTING.md) |
| Understand the Python/Go architecture | [Architecture](ARCHITECTURE.md) |
| Understand the Python/Go transport boundary | [Transport Contract](TRANSPORT_CONTRACT.md) |
| Contribute code/docs | [Contributing](CONTRIBUTING.md) |
| Add or maintain upload plugins | [Plugin Creation Guide](guides/PLUGIN_CREATION_GUIDE.md) |
| Define plugin settings UI | [Schema Plugin Guide](guides/SCHEMA_PLUGIN_GUIDE.md) |
| Prepare a release | [Release Process](releases/RELEASE_PROCESS.md) |

## Current User Docs

- [README](../README.md) covers features, installation, usage, data locations, architecture summary, CI/security/release workflows, and common troubleshooting.
- [User Tutorial](guides/USER_TUTORIAL.md) is the detailed user walkthrough with examples for uploads, folders, galleries, templates, covers, ViperGirls posting, output files, settings, troubleshooting, and internal mechanics.
- [Template Editor Tutorial](guides/TEMPLATE_EDITOR_TUTORIAL.md) is the complete guide to custom templates, format families (BBCode, Markdown, HTML), loops (`[for image]`, `[for cover]`), separators, conditionals, and copy-paste recipes.
- [Build Troubleshooting](guides/BUILD_TROUBLESHOOTING.md) covers sidecar lookup, PyInstaller packaging, Tkinter bundling, plugin bundling, toolchain setup, cleanup, and bug-report details.

## Current Developer Docs

- [Architecture](ARCHITECTURE.md) describes the current Python GUI plus Go sidecar architecture, active plugins, data storage, security model, test strategy, and known hardening opportunities.
- [Contributing](CONTRIBUTING.md) describes setup, repository layout, PR workflow, code standards, plugin workflow, testing, building, and documentation expectations.
- [Repository Layout](guides/REPOSITORY_LAYOUT.md) explains what belongs in source control and what is generated/user data.
- [Plugin Creation Guide](guides/PLUGIN_CREATION_GUIDE.md) explains plugin discovery, metadata, request specs, pre-requests, dynamic extraction, galleries, covers, tests, and packaging updates.
- [Schema Plugin Guide](guides/SCHEMA_PLUGIN_GUIDE.md) explains declarative plugin settings fields, validation, tooltips, advanced settings, and migration from manual UI.
- [Transport Contract](TRANSPORT_CONTRACT.md) defines the Python-owned website workflow and Go-owned transport boundary.

## Release Docs

- [Current Release Notes](releases/RELEASE_NOTES.md)
- [v3.1.0 Release Notes](releases/RELEASE_NOTES_v3.1.0.md)
- [vBleedingEdge Release Notes](releases/RELEASE_NOTES_vBleedingEdge.md)
- [v3.0.0 Release Notes](releases/RELEASE_NOTES_v3.0.0.md)
- [v3.0.0 Branch Difference Record](releases/BRANCH_DIFF_v3.0.0.md)
- [v2.0.0 Release Notes](releases/RELEASE_NOTES_v2.0.0.md)
- [v1.4.0 Release Notes](releases/RELEASE_NOTES_v1.4.0.md)
- [v1.3.0 Release Notes](releases/RELEASE_NOTES_v1.3.0.md)
- [v1.2.4 Release Notes](releases/RELEASE_NOTES_v1.2.4.md)
- [v1.2.2 Release Notes](releases/RELEASE_NOTES_v1.2.2.md)
- [v1.1.0 Release Notes](releases/RELEASE_NOTES_v1.1.0.md)
- [v1.0.5 Release Notes](releases/RELEASE_NOTES_v1.0.5.md)
- [v1.0.4 Release Notes](releases/release_notes_v1.0.4.md)
- [Release Process](releases/RELEASE_PROCESS.md)

Release-specific files are historical records for those versions. Do not rewrite old release behavior to match current code unless the file has broken links or factual publishing metadata.

## Historical Docs

The [history](history/) folder contains older implementation notes, phase summaries, PR drafts, and technical analyses. These are useful for project archaeology, but they are not current user or contributor guidance.

Use current docs first:

- Current architecture: [Architecture](ARCHITECTURE.md)
- Current plugin workflow: [Plugin Creation Guide](guides/PLUGIN_CREATION_GUIDE.md)
- Current build guidance: [Build Troubleshooting](guides/BUILD_TROUBLESHOOTING.md)
- Current user workflow: [User Tutorial](guides/USER_TUTORIAL.md)

Historical docs may mention old file names, old version numbers, old coverage values, old Go versions, or old plugin registration patterns.

## Root Docs

- [README](../README.md)
- [Architecture](ARCHITECTURE.md)
- [Transport Contract](TRANSPORT_CONTRACT.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)

The older technical debt tracker now lives in [Historical Remaining Issues](history/REMAINING_ISSUES.md). Treat `CHANGELOG.md`, active GitHub issues, and this docs index as the current source of truth for ongoing work.

## Directory Structure

```text
docs/
├── README.md
├── ARCHITECTURE.md
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── TRANSPORT_CONTRACT.md
├── assets/
│   └── screenshots/
├── archive/
│   └── README.md
├── benchmarks/
│   └── README.md
├── guides/
│   ├── BUILD_TROUBLESHOOTING.md
│   ├── PLUGIN_CREATION_GUIDE.md
│   ├── REPOSITORY_LAYOUT.md
│   ├── SCHEMA_PLUGIN_GUIDE.md
│   └── USER_TUTORIAL.md
├── releases/
│   ├── RELEASE_NOTES.md
│   ├── RELEASE_NOTES_v3.1.0.md
│   ├── RELEASE_NOTES_vBleedingEdge.md
│   ├── RELEASE_NOTES_v3.0.0.md
│   ├── BRANCH_DIFF_v3.0.0.md
│   ├── RELEASE_NOTES_v2.0.0.md
│   ├── RELEASE_NOTES_v1.4.0.md
│   ├── RELEASE_NOTES_v1.3.0.md
│   ├── RELEASE_NOTES_v1.2.4.md
│   ├── RELEASE_NOTES_v1.2.2.md
│   ├── RELEASE_NOTES_v1.1.0.md
│   ├── RELEASE_NOTES_v1.0.5.md
│   ├── release_notes_v1.0.4.md
│   └── RELEASE_PROCESS.md
├── github/
│   ├── RELEASE_TEMPLATE.md
│   └── ISSUE_TEMPLATE/
│       ├── bug_report.md
│       └── feature_request.md
└── history/
    ├── REMAINING_ISSUES.md
    └── historical implementation notes and analysis
```

## Recent Documentation Updates

### 2026-09-04

- Promoted current release documentation, build metadata, and app metadata to `v3.1.0`.
- Added v3.1.0 release notes for the folder-size template placeholder.
- Documented `#folder_size#` for batch output templates.

### 2026-07-28

- Promoted current release documentation, build metadata, and app metadata to `vBleedingEdge`.
- Added vBleedingEdge release notes for the Pixhost.cc migration and large-folder import responsiveness patch.
- Kept v3.0.0 release notes and branch-difference records as historical release artifacts.

### 2026-07-12

- Promoted current release documentation, build metadata, and app metadata to `v3.0.0`.
- Added v3.0.0 release notes for the Python-owned workflow and generic Go transport architecture.
- Added a branch-difference record for `Bleeding-Edge` compared with `main`, including compare metadata, ahead/behind commits, and full file status.

### 2026-06-30

- Updated current docs for the `BETA` development build, shorter app title, scheduled-post menu, activity terminal, persisted activity log, and current Python/Go transport ownership.
- Fixed current guide links and source/test commands after the `frontend/` and `backend/` split.
- Kept historical release notes as published records while pointing current guidance at the active docs.

### 2026-06-22

- Published v2.0.0 release metadata and release notes for ViperGirls posting, Template Editor, Gallery Manager, cache, cover, and queue workflow changes.

### 2026-06-21

- Updated active docs for Gallery Manager cache/pins/last-used behavior.
- Updated architecture docs to describe the current plugin-first sidecar model and remaining Go service helpers.
- Updated contributor and plugin docs for automatic plugin discovery, current schema settings, current build commands, and current test commands.
- Updated build troubleshooting for PyInstaller hooks, Tkinter/Tcl bundling, plugin bundling, and current Go/Python toolchain expectations.
- Added documentation for current Template Manager, cover, ViperGirls, repository cleanup, and user tutorial improvements in `CHANGELOG.md`.
- Refreshed the Template Editor screenshot to show search, template actions, categorized placeholders, and current cover controls.

### 2026-06-20

- Published v1.4.0 user experience and safer upload control documentation.
- Updated screenshots for the main upload workflow, checks, activity, completion summaries, and advanced app settings.

## Maintenance Rules

- Update [CHANGELOG.md](CHANGELOG.md) for every user-visible feature, fix, behavior change, or documentation change worth release notes.
- Update screenshots when visible UI changes.
- Update [Build Troubleshooting](guides/BUILD_TROUBLESHOOTING.md) when build scripts, PyInstaller arguments, toolchain versions, or packaging checks change.
- Update plugin docs when plugin discovery, schema fields, request specs, or packaging hidden imports change.
- Keep historical docs clearly separated from current guidance.

- **Last Updated:** 2026-09-04
- **Documentation Version:** 3.1.0
- **Project Version:** v3.1.0
