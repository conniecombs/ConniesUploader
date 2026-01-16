# Build Troubleshooting Guide

## Issue: Uploads Don't Work in Built EXE

### Symptoms
- Built exe is only ~26MB (too small)
- Uploads fail immediately
- Log shows "Sidecar executable not found"

### Root Cause
The Go sidecar (`uploader.exe`) was not properly bundled into the PyInstaller package.

### Solution

#### 1. Verify Go Sidecar Exists
Before running the build script, ensure `uploader.exe` exists in the project root:

```bash
# Build Go sidecar manually if needed
go build -ldflags="-s -w" -o uploader.exe uploader.go

# Verify it was created
ls -l uploader.exe
# Should be ~12-15 MB
```

#### 2. Clean Previous Build
Delete old build artifacts that might interfere:

```batch
# Windows
rmdir /s /q build
rmdir /s /q dist
del *.spec

# Linux/Mac
rm -rf build dist *.spec
```

#### 3. Rebuild with Clean Flag
Run the build script with the `--clean` flag:

```batch
build_uploader.bat --clean
```

#### 4. Verify Built EXE Size
The final exe should be **40-50 MB**, not 26 MB:

```
Components:
- Python runtime + libraries: ~20 MB
- uploader.exe (Go sidecar): ~12 MB
- tkinterdnd2 + dependencies: ~15 MB
- Total: ~47 MB
```

If your exe is only 26 MB, the Go sidecar is missing.

#### 5. Test Sidecar Inclusion
Run the diagnostic script:

```python
python test_sidecar.py
```

This will show exactly where the script is looking for uploader.exe and whether it's found.

#### 6. Manual PyInstaller Build
If the automatic build fails, try building manually:

```batch
# 1. Build Go sidecar
go build -ldflags="-s -w" -o uploader.exe uploader.go

# 2. Verify it exists
dir uploader.exe

# 3. Run PyInstaller
pyinstaller ^
    --noconsole ^
    --onefile ^
    --clean ^
    --name "ConniesUploader" ^
    --icon "logo.ico" ^
    --add-data "uploader.exe;." ^
    --add-data "logo.ico;." ^
    --collect-all tkinterdnd2 ^
    main.py

# 4. Verify output
dir dist\ConniesUploader.exe
```

## Issue: "go: command not found"

### Solution
Install Go from https://go.dev/dl/ or let the build script install it automatically.

## Issue: "python: command not found"

### Solution
Install Python 3.11+ from https://www.python.org/downloads/ or let the build script install it.

## Issue: PyInstaller Fails with "module not found"

### Solution
Ensure virtual environment is activated and all dependencies installed:

```batch
# Recreate venv
build_uploader.bat --clean

# Or manually:
python -m venv venv
call venv\Scripts\activate
pip install -r requirements.txt
```

## Issue: EXE Runs but Shows "Failed to Load Plugin"

This is different from sidecar issues. This means plugins can't be imported.

### Solution
Ensure the `modules` directory structure is preserved:

```
ConniesUploader.exe  (in dist/)
modules/
  ├── plugins/
  │   ├── __init__.py
  │   ├── imx.py
  │   ├── pixhost.py
  │   └── ...
  └── ...
```

If modules aren't found, add to PyInstaller command:
```
--hidden-import=modules.plugins.imx
--hidden-import=modules.plugins.pixhost
```

## Verification Checklist

Before distributing the built exe:

- [ ] EXE file size is 40-50 MB (not 26 MB)
- [ ] Run `test_sidecar.py` and verify sidecar is found
- [ ] Test upload to at least one service (IMX, Pixhost, etc.)
- [ ] Check log window for errors
- [ ] Verify plugins load in Settings > Service dropdown
- [ ] Test drag-and-drop file adding
- [ ] Verify gallery creation works

## Getting Help

If issues persist:

1. Check the log window (View > View Log)
2. Run from command line to see console output:
   ```
   ConniesUploader.exe --console
   ```
3. Run `test_sidecar.py` and save output
4. Open an issue with:
   - Build command used
   - EXE file size
   - test_sidecar.py output
   - Error messages from log
