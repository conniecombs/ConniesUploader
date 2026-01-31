{
type: file_update
fileName: build_uploader.bat
fileContent:
@echo off
setlocal
REM Connie's Uploader Ultimate - Windows Build Script
REM Simplified version with auto-install features

cd /d "%~dp0"
title Connie's Uploader - Build Tool

echo ========================================================
echo       Connie's Uploader Ultimate - Build v1.2.2
echo ========================================================
echo.

REM --- Detect Architecture ---
set "ARCH=64"
if not defined ProgramFiles(x86) set "ARCH=32"
echo [INFO] Detected %ARCH%-bit Windows
echo.

REM --- Cleanup ---
if exist "%~dp0python_installer.exe" del "%~dp0python_installer.exe"
if exist "%~dp0go_installer.msi" del "%~dp0go_installer.msi"
if exist "%~dp0uploader.exe" del "%~dp0uploader.exe"
if "%1"=="--clean" (
    echo [INFO] Cleaning virtual environment...
    if exist "%~dp0venv" rmdir /s /q "%~dp0venv"
)

REM --- Check/Install Python ---
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [1/6] Installing Python...
    call :install_python
    if %errorlevel% neq 0 exit /b 1
) else (
    echo [1/6] Python found
)

REM --- Check/Install Go ---
go version >nul 2>&1
if %errorlevel% neq 0 (
    echo [2/6] Installing Go...
    call :install_go
    if %errorlevel% neq 0 exit /b 1
) else (
    echo [2/6] Go found
)

REM --- Build Go Sidecar ---
echo [3/6] Building Go sidecar...
if not exist go.mod (
    echo [ERROR] go.mod not found!
    exit /b 1
)

go mod tidy
if "%ARCH%"=="32" (set GOARCH=386) else (set GOARCH=amd64)
go build -ldflags="-s -w" -o "%~dp0uploader.exe" "%~dp0uploader.go"

if not exist "%~dp0uploader.exe" (
    echo [ERROR] Go build failed!
    exit /b 1
)
echo       - uploader.exe built successfully
echo.

REM --- Setup Python Environment ---
echo [4/6] Setting up Python environment...
if not exist "%~dp0requirements.txt" (
    echo [ERROR] requirements.txt not found!
    exit /b 1
)

if not exist "%~dp0venv" (
    echo       - Creating virtual environment...
    python -m venv "%~dp0venv"
) else (
    echo       - Using existing venv...
)

call "%~dp0venv\Scripts\activate"
echo       - Installing dependencies...
pip install -q --upgrade pip
pip install -q -r "%~dp0requirements.txt"
if %errorlevel% neq 0 (
    echo [ERROR] Python dependency install failed!
    exit /b 1
)
echo.

REM --- Build Final Executable ---
echo [5/6] Building final executable...
if not exist "%~dp0uploader.exe" (
    echo [ERROR] uploader.exe not found!
    exit /b 1
)

REM Fixed line continuations (^) below
pyinstaller --noconsole --onefile --clean --name "ConniesUploader" ^
    --icon "logo.ico" ^
    --add-data "uploader.exe;." ^
    --add-data "logo.ico;." ^
    --collect-all tkinterdnd2 ^
    --collect-submodules modules.plugins ^
    --hidden-import modules.plugins.imx ^
    --hidden-import modules.plugins.pixhost ^
    --hidden-import modules.plugins.pixhost_v2 ^
    --hidden-import modules.plugins.vipr ^
    --hidden-import modules.plugins.turbo ^
    --hidden-import modules.plugins.imagebam ^
    --hidden-import modules.plugins.imgur ^
    main.py

if not exist "%~dp0dist\ConniesUploader.exe" (
    echo [ERROR] Build failed!
    exit /b 1
)
echo.

REM --- Verify Build ---
echo [6/6] Verifying build...
for %%A in ("%~dp0dist\ConniesUploader.exe") do set DIST_SIZE=%%~zA
echo       - Final size: %DIST_SIZE% bytes

if %DIST_SIZE% LSS 40000000 (
    echo [WARNING] EXE seems too small (^<%DIST_SIZE:~0,-6% MB^)
    echo           Expected ^>40MB. Rebuild may be needed.
) else (
    echo       - Size verification passed
)
echo.

echo ========================================================
echo                  BUILD SUCCESS!
echo ========================================================
echo.
echo Executable: dist\ConniesUploader.exe
echo Build completed: %date% %time%
echo.
pause
start dist
exit /b 0

REM ========================================================
REM Helper Functions
REM ========================================================

:install_python
if "%ARCH%"=="32" (
    echo [ERROR] 32-bit Windows not supported for auto-install
    echo         Install Python 3.11+ manually from python.org
    exit /b 1
)

set "PYTHON_URL=https://www.python.org/ftp/python/3.11.7/python-3.11.7-amd64.exe"
set "PYTHON_SHA256=6a26a06d0c1cf46cd5c17144c7c994d0f38ddab369c2299c28e06e1c3e34fa5c"

echo       - Downloading Python 3.11.7...
curl -L -o "%~dp0python_installer.exe" "%PYTHON_URL%"
if not exist "%~dp0python_installer.exe" (
    echo [ERROR] Download failed!
    exit /b 1
)

echo       - Verifying SHA256...
call :verify_hash "%~dp0python_installer.exe" "%PYTHON_SHA256%"
if %errorlevel% neq 0 (
    del "%~dp0python_installer.exe"
    exit /b 1
)

echo       - Installing...
start /wait "%~dp0python_installer.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
del "%~dp0python_installer.exe"
set "PATH=%PATH%;C:\Program Files\Python311;C:\Program Files\Python311\Scripts"
exit /b 0

:install_go
REM ==================================================================================
REM Updated with correct SHA256 checksums for Go 1.24.0
REM ==================================================================================
if "%ARCH%"=="64" (
    set "GO_URL=https://go.dev/dl/go1.24.0.windows-amd64.msi"
    set "GO_SHA256=4e78016d889431eb16aa0f87868cf52479b90059791c94a4ff45872d0573089e"
) else (
    set "GO_URL=https://go.dev/dl/go1.24.0.windows-386.msi"
    set "GO_SHA256=f07677013cd7861c5e16067b0a82144c23c4bf72c139c762e142440f4c926f61"
)

echo       - Downloading Go 1.24.0...
curl -L -o "%~dp0go_installer.msi" "%GO_URL%"
if not exist "%~dp0go_installer.msi" (
    echo [ERROR] Download failed!
    exit /b 1
)

echo       - Verifying SHA256...
call :verify_hash "%~dp0go_installer.msi" "%GO_SHA256%"
if %errorlevel% neq 0 (
    del "%~dp0go_installer.msi"
    exit /b 1
)

echo       - Installing...
start /wait msiexec /i "%~dp0go_installer.msi" /quiet /norestart
del "%~dp0go_installer.msi"
if "%ARCH%"=="64" (
    set "PATH=%PATH%;C:\Program Files\Go\bin"
) else (
    set "PATH=%PATH%;C:\Program Files (x86)\Go\bin"
)
exit /b 0

:verify_hash
certutil -hashfile "%~1" SHA256 > "%~dp0temp_hash.txt"
findstr /v ":" "%~dp0temp_hash.txt" > "%~dp0actual_hash.txt"
set /p ACTUAL_HASH=<"%~dp0actual_hash.txt"
del "%~dp0temp_hash.txt" "%~dp0actual_hash.txt"

set "ACTUAL_HASH=%ACTUAL_HASH: =%"
set "EXPECTED_HASH=%~2"
set "EXPECTED_HASH=%EXPECTED_HASH: =%"

if /i not "%ACTUAL_HASH%"=="%EXPECTED_HASH%" (
    echo [ERROR] SHA256 mismatch!
    echo       Expected: %EXPECTED_HASH%
    echo       Got:      %ACTUAL_HASH%
    exit /b 1
)
echo       - Checksum verified
exit /b 0
}