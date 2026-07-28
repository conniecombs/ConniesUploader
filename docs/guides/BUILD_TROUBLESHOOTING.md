# Build Troubleshooting Guide

This guide covers source-run and packaged-build problems for Connie's Uploader.

## Quick Rules

- Source runs need a sidecar binary in the repo root: `uploader.exe` on Windows or `uploader` on Linux/macOS.
- Packaged releases bundle the Go sidecar inside the final PyInstaller executable.
- Use the build scripts before hand-writing PyInstaller commands.
- If you do build manually, mirror the current build script exactly.

## Supported Toolchain

Local builds:

- Python 3.11 or newer. The Windows build script accepts Python 3.11 through 3.13.
- Go 1.25.9 or newer.

CI/release workflows currently use:

- Python 3.11
- Go 1.26.5

## Preferred Build Commands

Windows:

```batch
build_uploader.bat --clean
```

Linux/macOS:

```bash
./build.sh --clean
```

Makefile:

```bash
make clean
make build
```

Non-interactive Windows CI-style build:

```batch
build_uploader.bat --ci
```

## Source Run: Sidecar Not Found

### Symptoms

When running `python main.py` from the repo root, or `cd frontend && python main.py`, logs show:

```text
Sidecar executable 'uploader.exe' was not found
```

### Meaning

This is expected if you start from source before building the Go sidecar. The Python GUI can open, but uploads cannot run until the sidecar exists.

### Fix

Windows:

```powershell
cd backend
go build -ldflags="-s -w" -o ../uploader.exe .
cd ..
cd frontend
python main.py
```

Linux/macOS:

```bash
cd backend
go build -ldflags="-s -w" -o ../uploader .
cd ..
cd frontend
python main.py
```

You can inspect lookup paths with:

```bash
python scripts/diagnostics/check_sidecar_location.py
```

## Packaged EXE: Sidecar Missing

### Symptoms

- Uploads fail immediately in `dist/ConniesUploader.exe`.
- Build verification says `uploader.exe` was not bundled.
- Packaged executable is unexpectedly tiny.

### Fix

Run:

```batch
build_uploader.bat --clean
```

The Windows build script verifies that:

- `uploader.exe` exists before PyInstaller runs.
- `uploader.exe` is present inside the PyInstaller archive.
- `_tkinter.pyd`, Tcl/Tk runtime data, `tcl86t.dll`, `tk86t.dll`, and tkinterdnd2 assets are bundled.

The release workflow uses a minimum final executable threshold of 15 MB to catch obviously incomplete packages. Do not rely on old 40-50 MB size expectations; stripped Go binaries and dependency changes can make final size vary.

## Manual Windows PyInstaller Build

Use this only for debugging. The command should include local hooks, tkinterdnd2 assets, plugin submodules, and explicit active plugin imports.

```batch
cd backend
go build -ldflags="-s -w" -o ../uploader.exe .
cd ..

pyinstaller ^
  --noconsole ^
  --onefile ^
  --clean ^
  --noupx ^
  --name "ConniesUploader" ^
  --icon "packaging/logo.ico" ^
  --add-data "uploader.exe;." ^
  --add-data "packaging/logo.ico;." ^
  --additional-hooks-dir "packaging/pyinstaller_hooks" ^
  --collect-all tkinterdnd2 ^
  --collect-submodules modules.plugins ^
  --hidden-import modules.plugins.imx ^
  --hidden-import modules.plugins.pixhost ^
  --hidden-import modules.plugins.vipr ^
  --hidden-import modules.plugins.turbo ^
  --hidden-import modules.plugins.imagebam ^
  --hidden-import modules.plugins.imgur ^
  --workpath build ^
  --distpath dist ^
  --specpath packaging ^
  frontend/main.py
```

If a new active plugin is added, update this command, `build_uploader.bat`, `build.sh`, `Makefile`, `.github/workflows/release.yml`, and `frontend/tests/test_build_contract.py`.

## Manual Linux/macOS PyInstaller Build

```bash
cd backend
go build -ldflags="-s -w" -o ../uploader .
cd ..

pyinstaller \
  --noconsole \
  --onefile \
  --clean \
  --name "ConniesUploader" \
  --add-binary "uploader:." \
  --add-data "packaging/logo.ico:." \
  --additional-hooks-dir "packaging/pyinstaller_hooks" \
  --collect-all tkinterdnd2 \
  --collect-submodules modules.plugins \
  --hidden-import modules.plugins.imx \
  --hidden-import modules.plugins.pixhost \
  --hidden-import modules.plugins.vipr \
  --hidden-import modules.plugins.turbo \
  --hidden-import modules.plugins.imagebam \
  --hidden-import modules.plugins.imgur \
  --workpath build \
  --distpath dist \
  --specpath packaging \
  frontend/main.py
```

## EXE Crashes Importing `_tkinter`

### Symptoms

The executable shows an unhandled exception like:

```text
ImportError: DLL load failed while importing _tkinter
```

### Meaning

PyInstaller did not bundle the Python Tkinter extension or the Tcl/Tk runtime correctly.

### Fix

1. Rebuild with the current script:

```batch
build_uploader.bat --clean
```

2. Confirm `packaging/pyinstaller_hooks/` exists and the build command includes:

```text
--additional-hooks-dir "packaging/pyinstaller_hooks"
```

3. Let the build script run its archive verification. It checks for:

- `_tkinter.pyd`
- `_tcl_data`
- `_tk_data`
- `tcl86t.dll`
- `tk86t.dll`

If any of those checks fail, recreate the virtual environment and rebuild.

```batch
rmdir /s /q venv
build_uploader.bat --clean
```

## EXE Crashes Importing `tkinter.tix`

### Symptoms

The traceback mentions `tkinterdnd2`, `TkinterDnD.py`, and `tkinter.tix`.

### Meaning

An old `tkinterdnd2` version is installed.

### Fix

```batch
pip install -r frontend/requirements.txt
build_uploader.bat --clean
```

`frontend/requirements.txt` should pin:

```text
tkinterdnd2==0.5.0
```

## Plugins Missing In Packaged Build

### Symptoms

- The app starts, but services are missing.
- Logs show plugin import failures.
- The service dropdown has fewer than the expected active services.

### Expected Active Plugins

- `imagebam.com`
- `imgur.com`
- `imx.to`
- `pixhost.cc`
- `turboimagehost`
- `vipr.im`

### Fix

Ensure the PyInstaller command includes:

```text
--collect-submodules modules.plugins
--hidden-import modules.plugins.imx
--hidden-import modules.plugins.pixhost
--hidden-import modules.plugins.vipr
--hidden-import modules.plugins.turbo
--hidden-import modules.plugins.imagebam
--hidden-import modules.plugins.imgur
```

Then run:

```bash
python scripts/diagnostics/check_plugins.py
```

## Python Not Found

### Windows

`build_uploader.bat` can install Python 3.11.9 for the current user on 64-bit Windows if no compatible Python is found.

For manual setup, install Python from [python.org](https://www.python.org/downloads/) and enable the Python launcher.

### Linux/macOS

Install Python with your system package manager or pyenv. Then recreate the venv:

```bash
python -m venv venv
source venv/bin/activate
pip install -r frontend/requirements.txt
```

## Go Not Found

### Windows

`build_uploader.bat` can install a portable Go 1.25.9 toolchain under `.build-tools/` if no compatible Go is found.

### Linux/macOS

Install Go from [go.dev](https://go.dev/dl/) or your package manager.

Verify:

```bash
go version
(cd backend && go mod download)
(cd backend && go build -ldflags="-s -w" -o ../uploader .)
```

## Dependency Installation Fails

Recreate the virtual environment:

Windows:

```batch
rmdir /s /q venv
python -m venv venv
call venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r frontend/requirements.txt
```

Linux/macOS:

```bash
rm -rf venv
python -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r frontend/requirements.txt
```

The pip “new release available” notice is informational and does not mean the build failed.

## Build Cleanup

Use:

```bash
python scripts/maintenance/clean_generated.py --dry-run
python scripts/maintenance/clean_generated.py
```

The cleanup helper removes generated build/test artifacts such as:

- `.coverage`, `.coverage.*`
- `htmlcov/`
- `build/`
- `dist/`
- `.pytest_cache/`
- `uploader`, `uploader.exe`
- `packaging/ConniesUploader.spec`
- `crash_log*.log`

It leaves user data alone unless explicitly told otherwise.

## Verification Checklist

Before distributing a build:

- [ ] Build completed with the platform script.
- [ ] Sidecar binary was built.
- [ ] Packaged executable was created.
- [ ] Archive verification found the sidecar.
- [ ] Archive verification found Tk/Tcl runtime files on Windows.
- [ ] Plugins load and show six active services.
- [ ] `View > Execution Log` does not show startup import errors.
- [ ] `View > Activity Terminal` can open the persisted activity log when testing long uploads.
- [ ] A one-file upload works.
- [ ] Drag and drop works.
- [ ] Gallery Manager opens.
- [ ] Template Editor opens.

## What To Include In A Bug Report

Include:

- Build command used.
- Whether this is a source run or packaged executable.
- Operating system.
- Python version.
- Go version.
- Final executable size, if packaged.
- `python scripts/diagnostics/check_sidecar_location.py` output for source-run sidecar issues.
- Relevant `View > Execution Log` output.
- Relevant `View > Activity Terminal` output from `~/.conniesuploader/activity.log`, if upload activity is involved.
- Screenshot of the error dialog, if present.
