# Archived Legacy Plugin Notes

The deprecated code lives in `archive/legacy_plugins/`. It has been removed from active use but preserved for historical reference.

## Legacy Plugins (Archived: 2026-01-03)

The following plugin files were archived as part of Phase 3 code cleanup:

### Archived Files
- `archive/legacy_plugins/imagebam_legacy.py` (92 lines)
- `archive/legacy_plugins/imx_legacy.py` (74 lines)
- `archive/legacy_plugins/pixhost_legacy.py` (103 lines)
- `archive/legacy_plugins/turbo_legacy.py` (103 lines)
- `archive/legacy_plugins/vipr_legacy.py` (79 lines)

**Total**: 451 lines removed from active codebase

### Reason for Archival
These files were early plugin implementations that have been superseded by newer versions:
- Plugin discovery automatically skips `*_legacy.py` files
- No active imports or references found in codebase
- Functionality replaced by current plugin implementations
- Kept for historical reference and to preserve git history

### Migration Notes
The current active plugins are:
- `modules/plugins/imagebam.py` - Active ImageBam plugin
- `modules/plugins/imx.py` - Active IMX plugin
- `modules/plugins/pixhost.py` - Active Pixhost plugin
- `modules/plugins/turbo.py` - Active Turbo plugin
- `modules/plugins/vipr.py` - Active Vipr plugin

All legacy configuration keys are still supported for backward compatibility through the `upload_manager.py` mapping system.

### If You Need to Reference Legacy Code
1. Check `archive/legacy_plugins/`
2. Review git history: `git log -- archive/legacy_plugins/<filename>`
3. Compare with current implementation to understand changes

---

**Do not restore these files to active use.** If functionality is needed, port it to the current plugin implementations.
