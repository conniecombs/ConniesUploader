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
    echo       - Detected 32-bit Operating System.
    set "ARCH=32"
) else (
    echo       - Detected 64-bit Operating System.
)

REM --- Step 1: Cleanup Old/Corrupt Installers ---
echo [1/6] Cleaning up old installer files...
if exist python_installer.exe del python_installer.exe
if exist go_installer.msi del go_installer.msi
if exist uploader.exe del uploader.exe
if exist venv rmdir /s /q venv

REM --- Step 2: Auto-Install Python ---
python --version >nul 2>&1
if %errorlevel% equ 0 goto CHECK_GO

echo [2/6] Downloading Python (%ARCH%-bit)...
if "%ARCH%"=="64" (
    curl -L -o python_installer.exe https://www.python.org/ftp/python/3.11.7/python-3.11.7-amd64.exe
) else (
    curl -L -o python_installer.exe https://www.python.org/ftp/python/3.11.7/python-3.11.7.exe
)

if not exist python_installer.exe (
    echo [ERROR] Failed to download Python. Check internet connection.
    pause
    exit /b
)

echo       - Installing Python (this takes a moment)...
start /wait python_installer.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
del python_installer.exe

REM Add Python to PATH for this session
if "%ARCH%"=="64" (
    set "PATH=%PATH%;C:\Program Files\Python311;C:\Program Files\Python311\Scripts"
) else (
    set "PATH=%PATH%;C:\Program Files (x86)\Python311;C:\Program Files (x86)\Python311\Scripts"
)

:CHECK_GO
REM --- Step 3: Auto-Install Go ---
go version >nul 2>&1
if %errorlevel% equ 0 goto BUILD_GO

echo [3/6] Downloading Go (%ARCH%-bit)...
if "%ARCH%"=="64" (
    curl -L -o go_installer.msi https://go.dev/dl/go1.21.6.windows-amd64.msi
) else (
    curl -L -o go_installer.msi https://go.dev/dl/go1.21.6.windows-386.msi
)

if not exist go_installer.msi (
    echo [ERROR] Failed to download Go. Check internet connection.
    pause
    exit /b
)

echo       - Installing Go...
start /wait msiexec /i go_installer.msi /quiet /norestart
del go_installer.msi

REM Add Go to PATH for this session
if "%ARCH%"=="64" (
    set "PATH=%PATH%;C:\Program Files\Go\bin"
) else (
    set "PATH=%PATH%;C:\Program Files (x86)\Go\bin"
)

:BUILD_GO
REM --- Step 4: Build Go Sidecar ---
echo.
echo [4/6] Compiling Go Sidecar...
if not exist go.mod go mod init uploader_sidecar
go mod tidy
go get github.com/PuerkitoBio/goquery

if "%ARCH%"=="32" (
    set GOARCH=386
) else (
    set GOARCH=amd64
)
go build -ldflags="-s -w" -o uploader.exe uploader.go

if not exist uploader.exe (
    echo [ERROR] uploader.exe was not created. Go build failed.
    echo         Ensure uploader.go is in the same folder as this script.
    pause
    exit /b
)

REM --- Step 5: Python Environment ---
echo.
echo [5/6] Setting up Python dependencies...
python -m venv venv
call venv\Scripts\activate

REM Create requirements.txt
echo customtkinter > requirements.txt
echo tkinterdnd2 >> requirements.txt
echo Pillow >> requirements.txt
echo requests >> requirements.txt
echo loguru >> requirements.txt
echo keyring >> requirements.txt
echo pyperclip >> requirements.txt
echo pyinstaller >> requirements.txt

pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Python dependency install failed.
    pause
    exit /b
)

REM --- Step 6: Build Final EXE ---
echo.
echo [6/6] Building Final Executable...
pyinstaller --noconsole --onefile --clean --name "ConniesUploader" ^
    --icon "logo.ico" ^
    --add-data "uploader.exe;." ^
    --add-data "logo.ico;." ^
    --collect-all tkinterdnd2 ^
    main.py

if not exist dist\ConniesUploader.exe (
    echo [ERROR] Build failed. No EXE found in 'dist' folder.
    pause
    exit /b
)

echo.
echo ========================================================
echo       SUCCESS!
echo ========================================================
echo.
echo Your program is in the "dist" folder.
pause
start dist