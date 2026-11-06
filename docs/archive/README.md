# Archived Legacy Code

The files described here no longer exist in the working tree. They were kept
for reference for several releases and were removed in v3.1.2 because nothing
imported them. Git history still has every version.

## Removed in v3.1.2

| Path | What it was | Last commit before removal |
| --- | --- | --- |
| `archive/legacy_plugins/*.py` | Early plugin implementations superseded by `frontend/modules/plugins/` (archived 2026-01-03) | `git log -- archive/legacy_plugins` |
| `frontend/modules/controller.py` and `frontend/tests/test_controller.py` | A second, older upload/post lifecycle that diverged from the Main_Window package; nothing in the app imported it | `git log -- frontend/modules/controller.py` |
| `frontend/modules/validation.py` and `frontend/tests/test_validation.py` | Path/filename validators used only by their own tests; `frontend/modules/file_handler.py` owns import validation | `git log -- frontend/modules/validation.py` |
| `VGPost.txt` | A stale forum post draft for an earlier release | `git log -- VGPost.txt` |

## If You Need Them

```bash
git log --oneline -- frontend/modules/controller.py
git show <commit>:frontend/modules/controller.py
```

**Do not restore these files to active use.** Port anything still needed into
the current implementation and cover it with tests.
