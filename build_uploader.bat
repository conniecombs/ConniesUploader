@echo off
setlocal
REM --- FIX: Force script to run in its own folder, not System32 ---
cd /d "%~dp0"

title Connie's Uploader - Smart Build Tool

echo ========================================================
echo       Connie's Uploader - Smart Build Utility
echo ========================================================
echo.

REM --- Step 0: Detect Architecture ---
echo [0/6] Detecting System Architecture...
set "ARCH=64"
if not defined ProgramFiles(x86) (
    echo       - 32-bit Windows is no longer supported.
    echo       - Please use a 64-bit Windows system.
    pause
    exit /b 1
) else (
    echo       - Detected 64-bit Operating System.
)

REM --- Step 1: Cleanup Old/Corrupt Installers ---
echo [1/6] Cleaning up old installer files...
REM Sanitize paths - only delete in current directory
if exist "%~dp0python_installer.exe" del "%~dp0python_installer.exe"
if exist "%~dp0go_installer.msi" del "%~dp0go_installer.msi"
if exist "%~dp0uploader.exe" del "%~dp0uploader.exe"
REM Only clean venv if --clean flag is passed
if "%1"=="--clean" (
    echo       - Removing virtual environment (--clean flag)...
    if exist "%~dp0venv" rmdir /s /q "%~dp0venv"
)

REM --- Step 2: Auto-Install Python ---
python --version >nul 2>&1
if %errorlevel% equ 0 goto CHECK_GO

echo [2/6] Downloading Python 3.11.7 (64-bit)...
set "PYTHON_URL=https://www.python.org/ftp/python/3.11.7/python-3.11.7-amd64.exe"
set "PYTHON_SHA256=6a26a06d0c1cf46cd5c17144c7c994d0f38ddab369c2299c28e06e1c3e34fa5c"

curl -L -o "%~dp0python_installer.exe" "%PYTHON_URL%"

if not exist "%~dp0python_installer.exe" (
    echo [ERROR] Failed to download Python. Check internet connection.
    pause
    exit /b
)

echo       - Verifying download integrity (SHA256)...
certutil -hashfile "%~dp0python_installer.exe" SHA256 > "%~dp0temp_hash.txt"
findstr /v ":" "%~dp0temp_hash.txt" > "%~dp0actual_hash.txt"
set /p ACTUAL_HASH=<"%~dp0actual_hash.txt"
del "%~dp0temp_hash.txt" "%~dp0actual_hash.txt"

REM Remove spaces from hash for comparison
set "ACTUAL_HASH=%ACTUAL_HASH: =%"
set "EXPECTED_HASH=%PYTHON_SHA256: =%"

if /i not "%ACTUAL_HASH%"=="%EXPECTED_HASH%" (
    echo [ERROR] SHA256 checksum mismatch!
    echo         Expected: %EXPECTED_HASH%
    echo         Got:      %ACTUAL_HASH%
    echo         Download may be corrupted or tampered with.
    del "%~dp0python_installer.exe"
    pause
    exit /b
)
echo       - Checksum verified successfully!

echo       - Installing Python (this takes a moment)...
start /wait "%~dp0python_installer.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
del "%~dp0python_installer.exe"

REM Add Python to PATH for this session
set "PATH=%PATH%;C:\Program Files\Python311;C:\Program Files\Python311\Scripts"

:CHECK_GO
REM --- Step 3: Auto-Install Go ---
go version >nul 2>&1
if %errorlevel% equ 0 goto BUILD_GO

echo [3/6] Downloading Go 1.24.7 (64-bit)...
REM Note: Go 1.24.7 required (matches toolchain in go.mod) for security fixes and goquery v1.11.0
set "GO_URL=https://go.dev/dl/go1.24.7.windows-amd64.msi"
REM TODO: Update SHA256 from https://go.dev/dl/ - Verify manually for security
REM Current hash is placeholder - verification will be skipped if not updated
set "GO_SHA256=PLACEHOLDER_UPDATE_FROM_GOLANG_DOT_DEV_DOWNLOADS_PAGE"

curl -L -o "%~dp0go_installer.msi" "%GO_URL%"

if not exist "%~dp0go_installer.msi" (
    echo [ERROR] Failed to download Go. Check internet connection.
    pause
    exit /b
)

echo       - Verifying download integrity (SHA256)...
REM Skip verification if placeholder hash
if "%GO_SHA256%"=="PLACEHOLDER_UPDATE_FROM_GOLANG_DOT_DEV_DOWNLOADS_PAGE" (
    echo       - WARNING: SHA256 verification skipped (placeholder hash)
    echo       - Please update GO_SHA256 in this script for security
    echo       - Download SHA256 from: https://go.dev/dl/
) else (
    certutil -hashfile "%~dp0go_installer.msi" SHA256 > "%~dp0temp_hash.txt"
    findstr /v ":" "%~dp0temp_hash.txt" > "%~dp0actual_hash.txt"
    set /p ACTUAL_HASH=<"%~dp0actual_hash.txt"
    del "%~dp0temp_hash.txt" "%~dp0actual_hash.txt"

    REM Remove spaces from hash for comparison
    set "ACTUAL_HASH=%ACTUAL_HASH: =%"
    set "EXPECTED_HASH=%GO_SHA256: =%"

    if /i not "%ACTUAL_HASH%"=="%EXPECTED_HASH%" (
        echo [ERROR] SHA256 checksum mismatch!
        echo         Expected: %EXPECTED_HASH%
        echo         Got:      %ACTUAL_HASH%
        echo         Download may be corrupted or tampered with.
        del "%~dp0go_installer.msi"
        pause
        exit /b
    )
    echo       - Checksum verified successfully!
)

echo       - Installing Go...
start /wait msiexec /i "%~dp0go_installer.msi" /quiet /norestart
del "%~dp0go_installer.msi"

REM Add Go to PATH for this session
set "PATH=%PATH%;C:\Program Files\Go\bin"

:BUILD_GO
REM --- Step 4: Build Go Sidecar ---
echo.
echo [4/6] Compiling Go Sidecar...

REM Verify go.mod exists (should already exist in repo)
if not exist go.mod (
    echo [ERROR] go.mod not found in project directory!
    echo         This file should be committed to the repository.
    pause
    exit /b
)

REM Ensure dependencies are up to date
go mod tidy

REM Build for 64-bit Windows (32-bit no longer supported)
set GOARCH=amd64
go build -ldflags="-s -w" -o "%~dp0uploader.exe" "%~dp0uploader.go"

if not exist "%~dp0uploader.exe" (
    echo [ERROR] uploader.exe was not created. Go build failed.
    echo         Ensure uploader.go is in the same folder as this script.
    pause
    exit /b
)
echo       - uploader.exe built successfully!

REM --- Step 5: Python Environment ---
echo.
echo [5/6] Setting up Python dependencies...

REM Verify requirements.txt exists
if not exist "%~dp0requirements.txt" (
    echo [ERROR] requirements.txt not found in project directory!
    echo         This file should be committed to the repository.
    pause
    exit /b
)

REM Create venv if it doesn't exist
if not exist "%~dp0venv" (
    echo       - Creating virtual environment...
    python -m venv "%~dp0venv"
) else (
    echo       - Using existing virtual environment...
)

call "%~dp0venv\Scripts\activate"

REM Install dependencies from the actual requirements.txt file
echo       - Installing Python packages (this may take a moment)...
pip install -r "%~dp0requirements.txt"
if %errorlevel% neq 0 (
    echo [ERROR] Python dependency install failed.
    pause
    exit /b
)

REM --- Step 6: Build Final EXE ---
echo.
echo [6/6] Building Final Executable...

REM Verify uploader.exe exists before packaging
if not exist "%~dp0uploader.exe" (
    echo [ERROR] uploader.exe not found! Cannot build without Go sidecar.
    echo         Run this script again or build uploader.exe manually.
    pause
    exit /b
)

echo       - Packaging with PyInstaller...
echo       - Including: uploader.exe, logo.ico, tkinterdnd2
pyinstaller --noconsole --onefile --clean --name "ConniesUploader" ^
    --icon "logo.ico" ^
    --add-data "uploader.exe;." ^
    --add-data "logo.ico;." ^
    --collect-all tkinterdnd2 ^
    main.py

if not exist "%~dp0dist\ConniesUploader.exe" (
    echo [ERROR] Build failed. No EXE found in 'dist' folder.
    pause
    exit /b
)

echo.
echo ========================================================
echo       BUILD VERIFICATION
echo ========================================================
echo.

REM Check file size to verify uploader.exe was included
for %%A in ("%~dp0dist\ConniesUploader.exe") do set DIST_SIZE=%%~zA
echo Final EXE size: %DIST_SIZE% bytes

REM Expected size should be >40MB if uploader.exe is included
REM (Python ~20MB + uploader.exe ~12MB + dependencies ~15MB = ~47MB)
if %DIST_SIZE% LSS 40000000 (
    echo.
    echo [WARNING] EXE seems too small (^<%DIST_SIZE:~0,-6% MB^)
    echo           Expected ^>40MB when uploader.exe is included.
    echo           The Go sidecar may not be bundled correctly!
    echo.
    echo Recommendation: Delete dist\ folder and rebuild.
    echo.
) else (
    echo Status: OK - Size indicates uploader.exe is included
)

echo.
echo ========================================================
echo       SUCCESS!
echo ========================================================
echo.
echo Your program is in the "dist" folder.
echo File: dist\ConniesUploader.exe
echo.
echo Build completed: %date% %time%
echo.
pause
start dist
