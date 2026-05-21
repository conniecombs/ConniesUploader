@echo off
setlocal EnableExtensions

REM Connie's Uploader Ultimate - Windows Build Script
REM Builds the Go sidecar and packages the Python GUI with PyInstaller.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%" || exit /b 1
title Connie's Uploader - Build Tool

set "APP_NAME=ConniesUploader"
set "VERSION=1.2.4"

REM requirements.txt pins pyinstaller==6.11.1, which supports Python <3.14.
set "PYTHON_MIN_MINOR=11"
set "PYTHON_MAX_MINOR=13"
set "PYTHON_INSTALL_VERSION=3.11.9"
set "PYTHON_INSTALLER=python-%PYTHON_INSTALL_VERSION%-amd64.exe"
set "PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_INSTALL_VERSION%/%PYTHON_INSTALLER%"
set "PYTHON_SHA256=5ee42c4eee1e6b4464bb23722f90b45303f79442df63083f05322f1785f5fdde"

set "GO_INSTALL_VERSION=1.25.9"
set "GO_AMD64_SHA256=207e998936913ad4e7e0c79c0c7e038ba8726cdcbb885b66071ed097a31ac458"
set "GO_386_SHA256=02a9199011c255a80778d9602d11df7bfb90c858258ec8317a57f202dedcf9e3"

set "DO_CLEAN="
set "CLEAN_ONLY="
set "NO_PAUSE="
set "NO_OPEN="

:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--clean" (
    set "DO_CLEAN=1"
    shift
    goto parse_args
)
if /i "%~1"=="clean" (
    set "DO_CLEAN=1"
    set "CLEAN_ONLY=1"
    shift
    goto parse_args
)
if /i "%~1"=="--no-pause" (
    set "NO_PAUSE=1"
    shift
    goto parse_args
)
if /i "%~1"=="--no-open" (
    set "NO_OPEN=1"
    shift
    goto parse_args
)
if /i "%~1"=="--ci" (
    set "NO_PAUSE=1"
    set "NO_OPEN=1"
    shift
    goto parse_args
)
if /i "%~1"=="--help" (
    call :show_help
    exit /b 0
)
if /i "%~1"=="-h" (
    call :show_help
    exit /b 0
)
if /i "%~1"=="help" (
    call :show_help
    exit /b 0
)
echo [ERROR] Unknown option: %~1
echo.
call :show_help
exit /b 1

:args_done
call :print_header

REM --- Detect Architecture ---
set "ARCH=64"
if not defined ProgramFiles(x86) set "ARCH=32"
echo [INFO] Detected %ARCH%-bit Windows
echo.

if defined DO_CLEAN (
    call :clean_build
    if errorlevel 1 exit /b 1
)
if defined CLEAN_ONLY exit /b 0

REM --- Cleanup files that can mask failed builds ---
if exist "%SCRIPT_DIR%python_installer.exe" del /q "%SCRIPT_DIR%python_installer.exe"
if exist "%SCRIPT_DIR%go_installer.msi" del /q "%SCRIPT_DIR%go_installer.msi"
if exist "%SCRIPT_DIR%uploader.exe" del /q "%SCRIPT_DIR%uploader.exe"
if exist "%SCRIPT_DIR%dist\%APP_NAME%.exe" del /q "%SCRIPT_DIR%dist\%APP_NAME%.exe"

REM --- Check/Install Python ---
echo [1/6] Checking Python...
call :find_python
if errorlevel 1 (
    echo       - No compatible Python found. Need Python 3.%PYTHON_MIN_MINOR% through 3.%PYTHON_MAX_MINOR%.
    echo       - Installing Python %PYTHON_INSTALL_VERSION%...
    call :install_python
    if errorlevel 1 exit /b 1

    call :find_python
    if errorlevel 1 (
        echo [ERROR] Python install completed, but a compatible Python was not found.
        exit /b 1
    )
)
for /f "delims=" %%V in ('"%PYTHON_EXE%" --version 2^>^&1') do set "PYTHON_VERSION=%%V"
echo       - Found %PYTHON_VERSION% at "%PYTHON_EXE%"
echo.

REM --- Check/Install Go ---
echo [2/6] Checking Go...
go version >nul 2>&1
if errorlevel 1 (
    echo       - Go not found. Installing Go %GO_INSTALL_VERSION%...
    call :install_go
    if errorlevel 1 exit /b 1
)
for /f "delims=" %%V in ('go version 2^>^&1') do set "GO_VERSION=%%V"
echo       - Found %GO_VERSION%
echo.

REM --- Build Go Sidecar ---
echo [3/6] Building Go sidecar...
if not exist "%SCRIPT_DIR%go.mod" (
    echo [ERROR] go.mod not found!
    exit /b 1
)
if not exist "%SCRIPT_DIR%main.go" (
    echo [ERROR] main.go not found!
    exit /b 1
)

go mod tidy
if errorlevel 1 (
    echo [ERROR] go mod tidy failed!
    exit /b 1
)

set "GOOS=windows"
if "%ARCH%"=="32" (
    set "GOARCH=386"
) else (
    set "GOARCH=amd64"
)

go build -ldflags="-s -w" -o "%SCRIPT_DIR%uploader.exe" .
if errorlevel 1 (
    echo [ERROR] Go build failed!
    exit /b 1
)
if not exist "%SCRIPT_DIR%uploader.exe" (
    echo [ERROR] Go build did not create uploader.exe!
    exit /b 1
)
echo       - uploader.exe built successfully
echo.

REM --- Setup Python Environment ---
echo [4/6] Setting up Python environment...
if not exist "%SCRIPT_DIR%requirements.txt" (
    echo [ERROR] requirements.txt not found!
    exit /b 1
)

set "VENV_DIR=%SCRIPT_DIR%venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

if exist "%VENV_DIR%" if not exist "%VENV_PYTHON%" (
    echo       - Existing venv is incomplete; recreating...
    rmdir /s /q "%VENV_DIR%"
    if exist "%VENV_DIR%" (
        echo [ERROR] Failed to remove incomplete virtual environment!
        exit /b 1
    )
)

if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" -c "import sys; v=sys.version_info; raise SystemExit(0 if v.major == 3 and %PYTHON_MIN_MINOR% <= v.minor <= %PYTHON_MAX_MINOR% else 1)" >nul 2>&1
    if errorlevel 1 (
        echo       - Existing venv uses an incompatible Python; recreating...
        rmdir /s /q "%VENV_DIR%"
        if exist "%VENV_DIR%" (
            echo [ERROR] Failed to remove incompatible virtual environment!
            exit /b 1
        )
    )
)

if not exist "%VENV_PYTHON%" (
    echo       - Creating virtual environment...
    "%PYTHON_EXE%" -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment!
        exit /b 1
    )
) else (
    echo       - Using existing compatible venv...
)

echo       - Installing dependencies...
"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] pip upgrade failed!
    exit /b 1
)
"%VENV_PYTHON%" -m pip install -r "%SCRIPT_DIR%requirements.txt"
if errorlevel 1 (
    echo [ERROR] Python dependency install failed!
    exit /b 1
)
echo.

REM --- Build Final Executable ---
echo [5/6] Building final executable...
if not exist "%SCRIPT_DIR%uploader.exe" (
    echo [ERROR] uploader.exe not found!
    exit /b 1
)
if exist "%SCRIPT_DIR%dist\%APP_NAME%.exe" del /q "%SCRIPT_DIR%dist\%APP_NAME%.exe"

"%VENV_PYTHON%" -m PyInstaller --noconsole --onefile --clean --name "%APP_NAME%" ^
    --icon "logo.ico" ^
    --add-data "uploader.exe;." ^
    --add-data "logo.ico;." ^
    --collect-all tkinterdnd2 ^
    --collect-submodules modules.plugins ^
    --hidden-import modules.plugins.imx ^
    --hidden-import modules.plugins.pixhost ^
    --hidden-import modules.plugins.vipr ^
    --hidden-import modules.plugins.turbo ^
    --hidden-import modules.plugins.imagebam ^
    --hidden-import modules.plugins.imgur ^
    main.py

if errorlevel 1 (
    echo [ERROR] PyInstaller failed!
    exit /b 1
)
if not exist "%SCRIPT_DIR%dist\%APP_NAME%.exe" (
    echo [ERROR] Build failed! dist\%APP_NAME%.exe was not created.
    exit /b 1
)
echo.

REM --- Verify Build ---
echo [6/6] Verifying build...
set "DIST_EXE=%SCRIPT_DIR%dist\%APP_NAME%.exe"
for %%A in ("%DIST_EXE%") do set "DIST_SIZE=%%~zA"
echo       - Final size: %DIST_SIZE% bytes

set "ARCHIVE_LIST=%TEMP%\cu_archive_%RANDOM%%RANDOM%.txt"
"%VENV_DIR%\Scripts\pyi-archive_viewer.exe" "%DIST_EXE%" <nul > "%ARCHIVE_LIST%" 2>nul
if errorlevel 1 (
    echo [ERROR] Could not inspect PyInstaller archive!
    if exist "%ARCHIVE_LIST%" del /q "%ARCHIVE_LIST%"
    exit /b 1
)

findstr /L /C:"uploader.exe" "%ARCHIVE_LIST%" >nul
if errorlevel 1 (
    echo [ERROR] uploader.exe was not bundled into %APP_NAME%.exe!
    del /q "%ARCHIVE_LIST%"
    exit /b 1
)
echo       - Go sidecar bundled

findstr /L /C:"tkinterdnd2" "%ARCHIVE_LIST%" >nul
if errorlevel 1 (
    echo [ERROR] tkinterdnd2 native assets were not bundled!
    del /q "%ARCHIVE_LIST%"
    exit /b 1
)
echo       - tkinterdnd2 assets bundled
del /q "%ARCHIVE_LIST%"
echo.

echo ========================================================
echo                  BUILD SUCCESS!
echo ========================================================
echo.
echo Executable: dist\%APP_NAME%.exe
echo Build completed: %date% %time%
echo.
if not defined NO_PAUSE pause
if not defined NO_OPEN start "" "%SCRIPT_DIR%dist"
exit /b 0

REM ========================================================
REM Helper Functions
REM ========================================================

:print_header
echo ========================================================
echo       Connie's Uploader Ultimate - Build v%VERSION%
echo ========================================================
echo.
exit /b 0

:show_help
echo Connie's Uploader Ultimate - Windows Build v%VERSION%
echo.
echo Usage: build_uploader.bat [options]
echo.
echo Options:
echo   ^(no args^)      Full build
echo   --clean        Clean build artifacts before building
echo   clean          Clean build artifacts and exit
echo   --ci           Build without pause or opening dist
echo   --no-pause     Do not pause when the build finishes
echo   --no-open      Do not open the dist folder when the build finishes
echo   help, -h       Show this help message
exit /b 0

:clean_build
echo [INFO] Cleaning build artifacts...
if exist "%SCRIPT_DIR%build" rmdir /s /q "%SCRIPT_DIR%build"
if exist "%SCRIPT_DIR%dist" rmdir /s /q "%SCRIPT_DIR%dist"
if exist "%SCRIPT_DIR%venv" rmdir /s /q "%SCRIPT_DIR%venv"
if exist "%SCRIPT_DIR%__pycache__" rmdir /s /q "%SCRIPT_DIR%__pycache__"
if exist "%SCRIPT_DIR%.pytest_cache" rmdir /s /q "%SCRIPT_DIR%.pytest_cache"
if exist "%SCRIPT_DIR%%APP_NAME%.spec" del /q "%SCRIPT_DIR%%APP_NAME%.spec"
if exist "%SCRIPT_DIR%uploader.exe" del /q "%SCRIPT_DIR%uploader.exe"
echo [INFO] Clean complete.
echo.
exit /b 0

:find_python
set "PYTHON_EXE="
call :try_python_command "py -3.11" && exit /b 0
call :try_python_command "py -3.12" && exit /b 0
call :try_python_command "py -3.13" && exit /b 0
call :try_python_exe "%LocalAppData%\Programs\Python\Python311\python.exe" && exit /b 0
call :try_python_exe "%ProgramFiles%\Python311\python.exe" && exit /b 0
call :try_python_command "python" && exit /b 0
exit /b 1

:try_python_command
set "PYTHON_EXE="
for /f "delims=" %%P in ('%~1 -c "import sys; v=sys.version_info; ok=v.major == 3 and %PYTHON_MIN_MINOR% <= v.minor <= %PYTHON_MAX_MINOR%; print(sys.executable) if ok else None; sys.exit(0 if ok else 1)" 2^>nul') do set "PYTHON_EXE=%%P"
if defined PYTHON_EXE exit /b 0
exit /b 1

:try_python_exe
set "PYTHON_EXE="
if not exist "%~1" exit /b 1
for /f "delims=" %%P in ('"%~1" -c "import sys; v=sys.version_info; ok=v.major == 3 and %PYTHON_MIN_MINOR% <= v.minor <= %PYTHON_MAX_MINOR%; print(sys.executable) if ok else None; sys.exit(0 if ok else 1)" 2^>nul') do set "PYTHON_EXE=%%P"
if defined PYTHON_EXE exit /b 0
exit /b 1

:install_python
if "%ARCH%"=="32" (
    echo [ERROR] 32-bit Windows is not supported for Python auto-install.
    echo         Install Python 3.11 manually from python.org.
    exit /b 1
)

echo       - Downloading Python %PYTHON_INSTALL_VERSION%...
curl.exe -L -o "%SCRIPT_DIR%python_installer.exe" "%PYTHON_URL%"
if errorlevel 1 (
    echo [ERROR] Python download failed!
    exit /b 1
)
if not exist "%SCRIPT_DIR%python_installer.exe" (
    echo [ERROR] Python installer was not downloaded!
    exit /b 1
)

echo       - Verifying SHA256...
call :verify_hash "%SCRIPT_DIR%python_installer.exe" "%PYTHON_SHA256%"
if errorlevel 1 (
    del /q "%SCRIPT_DIR%python_installer.exe"
    exit /b 1
)

echo       - Installing for current user...
start "" /wait "%SCRIPT_DIR%python_installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1
if errorlevel 1 (
    echo [ERROR] Python installer failed!
    del /q "%SCRIPT_DIR%python_installer.exe"
    exit /b 1
)
del /q "%SCRIPT_DIR%python_installer.exe"
set "PATH=%LocalAppData%\Programs\Python\Python311;%LocalAppData%\Programs\Python\Python311\Scripts;%PATH%"
exit /b 0

:install_go
if "%ARCH%"=="64" (
    set "GO_URL=https://go.dev/dl/go%GO_INSTALL_VERSION%.windows-amd64.msi"
    set "GO_SHA256=%GO_AMD64_SHA256%"
) else (
    set "GO_URL=https://go.dev/dl/go%GO_INSTALL_VERSION%.windows-386.msi"
    set "GO_SHA256=%GO_386_SHA256%"
)

echo       - Downloading Go %GO_INSTALL_VERSION%...
curl.exe -L -o "%SCRIPT_DIR%go_installer.msi" "%GO_URL%"
if errorlevel 1 (
    echo [ERROR] Go download failed!
    exit /b 1
)
if not exist "%SCRIPT_DIR%go_installer.msi" (
    echo [ERROR] Go installer was not downloaded!
    exit /b 1
)

echo       - Verifying SHA256...
call :verify_hash "%SCRIPT_DIR%go_installer.msi" "%GO_SHA256%"
if errorlevel 1 (
    del /q "%SCRIPT_DIR%go_installer.msi"
    exit /b 1
)

echo       - Installing...
msiexec.exe /i "%SCRIPT_DIR%go_installer.msi" /quiet /norestart
if errorlevel 1 (
    echo [ERROR] Go installer failed!
    del /q "%SCRIPT_DIR%go_installer.msi"
    exit /b 1
)
del /q "%SCRIPT_DIR%go_installer.msi"
if "%ARCH%"=="64" (
    set "PATH=%PATH%;%ProgramFiles%\Go\bin"
) else (
    set "PATH=%PATH%;%ProgramFiles(x86)%\Go\bin"
)
exit /b 0

:verify_hash
set "HASH_FILE=%TEMP%\cu_hash_%RANDOM%%RANDOM%.txt"
set "ACTUAL_FILE=%TEMP%\cu_actual_hash_%RANDOM%%RANDOM%.txt"
certutil -hashfile "%~1" SHA256 > "%HASH_FILE%"
if errorlevel 1 (
    echo [ERROR] Could not calculate SHA256 for %~1
    if exist "%HASH_FILE%" del /q "%HASH_FILE%"
    exit /b 1
)
findstr /v ":" "%HASH_FILE%" > "%ACTUAL_FILE%"
set /p ACTUAL_HASH=<"%ACTUAL_FILE%"
del /q "%HASH_FILE%" "%ACTUAL_FILE%"

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
