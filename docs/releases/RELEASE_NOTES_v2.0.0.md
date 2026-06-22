# Release Notes - v2.0.0 "Posting, Templates & Gallery Workflows"

**Release Date**: June 22, 2026
**Git Tag**: `v2.0.0`
**Release Type**: Major feature release

## Overview

v2.0.0 expands Connie's Uploader from an upload-focused desktop tool into a fuller posting workflow. The release adds ViperGirls target management and posting history, a much stronger template system, persistent gallery caching, richer Gallery Manager controls, improved cover handling, and selection-aware queue cleanup.

## Highlights

- ViperGirls posting workflow with saved targets, per-batch target selection, post previews, optional confirmation, background posting, and persisted posting history.
- ViperGirls target manager with URL/thread-ID normalization, live title fetching, tags, notes, validation, import/export, bulk delete, open-thread actions, and credential health checks.
- Template migration from `user_templates.json` to `~/.conniesuploader/templates.json`, with atomic saves and corrupted JSON recovery.
- Template Editor search, category filtering, import/export, duplicate, rename, delete, dirty-state protection, rendered/raw previews, and copy-preview support.
- Nested template conditionals, image loops, cover loops, loop separators, cover placeholders, cover counts, direct image placeholders, and BBCode/HTML mismatch warnings.
- Dedicated Gallery Service layer with normalized gallery responses, service-specific credential checks, IMX parsing, Pixhost creation normalization, and standardized error states.
- Persistent Gallery Cache at `~/.conniesuploader/gallery_cache.json` with pins, last-used timestamps, cached fallback display, and corrupt-cache backups.
- Resizable Gallery Manager with search, sorting, copy ID/hash, copy URL, open gallery, pin/unpin, refresh-from-host, and assign-to-batches support.
- Upload preflight checks for selected galleries, one-gallery-per-folder mode, Pixhost upload hashes, ViperGirls posting targets, invalid gallery choices, and missing credentials.
- Compact queue controls with selected-image removal, bulk cover set/clear, right-click actions, and keyboard shortcuts.

## Notable Changes

- Selected covers now render separately from regular `#all_images#` output, can use host-specific large thumbnail overrides, and keep cover state when moved between batches.
- Per-row Remove and Set Cover buttons were replaced by a compact `Cover` checkbox plus selection-aware actions.
- IMX gallery scraping/session behavior moved out of the UI layer and into service/plugin code.
- Cross-service gallery credential fallbacks were removed so each service uses only its own credentials.
- Vipr credential access now uses the centralized credentials manager, and Turbo uploads include the schema-selected thumbnail size.
- Architecture, contributor, plugin, schema, build troubleshooting, repository layout, release, and tutorial documentation were refreshed for the current app.

## Fixes

- Prevented stale Gallery Manager refresh/create responses from overwriting the current service view.
- Improved Gallery Manager errors for missing credentials, login failures, unsupported services, parse failures, empty lists, unreadable responses, and cached fallback states.
- Improved ViperGirls auto-poster failure reporting for missing credentials, failed login, missing targets, invalid thread IDs, empty post text, rejected posts, and failed submissions.
- Fixed posting target parsing, posting-history persistence, corrupt-history recovery, template validation, preview rendering, and BBCode toolbar output behavior.
- Fixed gallery cache behavior so empty live host results do not incorrectly fall back to stale cache data.

## Tests

v2.0.0 adds or expands coverage for ViperGirls target parsing and history, auto-poster outcomes, template migration and parser edge cases, gallery normalization and cache persistence, upload preflight checks, selected gallery metadata, cover ordering, queue selection actions, Turbo thumbnail propagation, cover thumbnail overrides, and Vipr Go service behavior.

## Download

**[Download v2.0.0](https://github.com/conniecombs/ConniesUploader/releases/tag/v2.0.0)**

Expected release artifacts:

- `ConniesUploader-v2.0.0-windows-x64.zip`
- `ConniesUploader-v2.0.0-linux-x64.tar.gz`
- `ConniesUploader-v2.0.0-macos-x64.zip`

## Upgrade Notes

Existing application settings are preserved. Custom templates are migrated from repository-local `user_templates.json` to `~/.conniesuploader/templates.json` the first time the new Template Manager path is used. Gallery cache and ViperGirls posting history are stored under `~/.conniesuploader/`.

## Tagging

```bash
git tag -a v2.0.0 -m "Release v2.0.0"
git push origin v2.0.0
```
