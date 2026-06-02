#!/usr/bin/env bash
# Connie's Uploader Ultimate - Linux/macOS build script.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="ConniesUploader"
VERSION="1.3.0"
PYTHON_MIN_MINOR=11
PYTHON_MAX_MINOR=13
GO_VERSION_MIN="1.25.9"

PYTHON_CMD=""
VENV_DIR="$SCRIPT_DIR/venv"
PLATFORM="$(uname -s)"

case "$PLATFORM" in
    MINGW*|MSYS*|CYGWIN*)
        SIDECAR_NAME="uploader.exe"
        DIST_EXE="dist/$APP_NAME.exe"
        ADD_DATA_SEP=";"
        VENV_PYTHON="$VENV_DIR/Scripts/python.exe"
        PYI_ARCHIVE_VIEWER="$VENV_DIR/Scripts/pyi-archive_viewer.exe"
        ;;
    *)
        SIDECAR_NAME="uploader"
        DIST_EXE="dist/$APP_NAME"
        ADD_DATA_SEP=":"
        VENV_PYTHON="$VENV_DIR/bin/python"
        PYI_ARCHIVE_VIEWER="$VENV_DIR/bin/pyi-archive_viewer"
        ;;
esac

print_header() {
    echo -e "${BLUE}========================================================${NC}"
    echo -e "${BLUE}      Connie's Uploader Ultimate - Build Tool${NC}"
    echo -e "${BLUE}      Version: $VERSION${NC}"
    echo -e "${BLUE}      Platform: $PLATFORM $(uname -m)${NC}"
    echo -e "${BLUE}========================================================${NC}"
    echo
}

print_step() {
    echo -e "${GREEN}[$1] $2${NC}"
}

print_error() {
    echo -e "${RED}[ERROR] $1${NC}" >&2
}

print_warning() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
}

show_help() {
    echo "Usage: $0 [OPTION]"
    echo
    echo "Options:"
    echo "  (no args)    Full build"
    echo "  clean        Clean build artifacts and exit"
    echo "  --clean      Clean build artifacts before building"
    echo "  --ci         Accepted for parity with build_uploader.bat"
    echo "  help, -h     Show this help message"
}

version_ge() {
    local current="$1"
    local required="$2"
    local IFS=.
    local -a current_parts required_parts

    current="${current%%[^0-9.]*}"
    required="${required%%[^0-9.]*}"
    read -r -a current_parts <<< "$current"
    read -r -a required_parts <<< "$required"

    for i in 0 1 2; do
        local current_part="${current_parts[$i]:-0}"
        local required_part="${required_parts[$i]:-0}"
        current_part="${current_part:-0}"
        required_part="${required_part:-0}"

        if ((10#$current_part > 10#$required_part)); then
            return 0
        fi
        if ((10#$current_part < 10#$required_part)); then
            return 1
        fi
    done

    return 0
}

python_is_compatible() {
    "$1" -c "import sys; v=sys.version_info; raise SystemExit(0 if v.major == 3 and $PYTHON_MIN_MINOR <= v.minor <= $PYTHON_MAX_MINOR else 1)" >/dev/null 2>&1
}

find_python() {
    local candidates=(python3.13 python3.12 python3.11 python3 python)

    for candidate in "${candidates[@]}"; do
        if command -v "$candidate" >/dev/null 2>&1 && python_is_compatible "$candidate"; then
            PYTHON_CMD="$candidate"
            return 0
        fi
    done

    return 1
}

check_python() {
    print_step "1/6" "Checking Python installation..."

    if ! find_python; then
        print_error "Compatible Python not found."
        echo "Need Python 3.$PYTHON_MIN_MINOR through 3.$PYTHON_MAX_MINOR because requirements.txt pins pyinstaller==6.11.1."
        echo "Install Python 3.11, 3.12, or 3.13 and rerun this script."
        exit 1
    fi

    local python_version
    python_version="$($PYTHON_CMD --version 2>&1 | awk '{print $2}')"
    echo "  - Found Python $python_version via $PYTHON_CMD"
}

check_go() {
    print_step "2/6" "Checking Go installation..."

    if ! command -v go >/dev/null 2>&1; then
        print_error "Go not found."
        echo "Install Go $GO_VERSION_MIN or newer from https://go.dev/dl/ and rerun this script."
        exit 1
    fi

    local go_version
    go_version="$(go version | awk '{print $3}' | sed 's/^go//')"
    if ! version_ge "$go_version" "$GO_VERSION_MIN"; then
        print_error "Go $go_version found, but Go $GO_VERSION_MIN or newer is required."
        exit 1
    fi

    echo "  - Found Go $go_version"
}

build_go_sidecar() {
    print_step "3/6" "Building Go sidecar..."

    if [ ! -f "go.mod" ]; then
        print_error "go.mod not found!"
        exit 1
    fi
    if [ ! -f "main.go" ]; then
        print_error "main.go not found!"
        exit 1
    fi

    echo "  - Downloading Go modules..."
    go mod download

    echo "  - Compiling optimized binary..."
    go build -ldflags="-s -w" -o "$SIDECAR_NAME" .

    if [ ! -f "$SIDECAR_NAME" ]; then
        print_error "Failed to build uploader binary!"
        exit 1
    fi

    chmod +x "$SIDECAR_NAME"
    echo "  - Go sidecar built successfully"
}

setup_python_env() {
    print_step "4/6" "Setting up Python environment..."

    if [ ! -f "requirements.txt" ]; then
        print_error "requirements.txt not found!"
        exit 1
    fi

    if [ -d "$VENV_DIR" ] && [ ! -x "$VENV_PYTHON" ]; then
        echo "  - Existing venv is incomplete; recreating..."
        rm -rf "$VENV_DIR"
    fi

    if [ -x "$VENV_PYTHON" ] && ! python_is_compatible "$VENV_PYTHON"; then
        echo "  - Existing venv uses an incompatible Python; recreating..."
        rm -rf "$VENV_DIR"
    fi

    if [ ! -x "$VENV_PYTHON" ]; then
        echo "  - Creating virtual environment..."
        "$PYTHON_CMD" -m venv "$VENV_DIR"
    else
        echo "  - Using existing compatible virtual environment..."
    fi

    echo "  - Installing Python dependencies..."
    "$VENV_PYTHON" -m pip install --upgrade pip
    "$VENV_PYTHON" -m pip install -r requirements.txt

    echo "  - Python environment ready"
}

build_executable() {
    print_step "5/6" "Building final executable..."

    if [ ! -f "$SIDECAR_NAME" ]; then
        print_error "$SIDECAR_NAME binary not found! Build Go sidecar first."
        exit 1
    fi

    echo "  - Packaging with PyInstaller..."
    "$VENV_PYTHON" -m PyInstaller --noconsole --onefile --clean \
        --name "$APP_NAME" \
        --icon "logo.ico" \
        --add-data "$SIDECAR_NAME$ADD_DATA_SEP." \
        --add-data "logo.ico$ADD_DATA_SEP." \
        --collect-all tkinterdnd2 \
        --collect-submodules modules.plugins \
        --hidden-import modules.plugins.imx \
        --hidden-import modules.plugins.pixhost \
        --hidden-import modules.plugins.vipr \
        --hidden-import modules.plugins.turbo \
        --hidden-import modules.plugins.imagebam \
        --hidden-import modules.plugins.imgur \
        main.py

    if [ ! -f "$DIST_EXE" ]; then
        print_error "Build failed! No executable found in dist/ folder."
        exit 1
    fi

    chmod +x "$DIST_EXE"
    echo "  - Executable built successfully"
}

verify_build() {
    print_step "6/6" "Verifying build..."

    local archive_list
    archive_list="$(mktemp)"
    trap "rm -f '$archive_list'" EXIT

    if [ ! -x "$PYI_ARCHIVE_VIEWER" ]; then
        print_error "pyi-archive_viewer not found in virtual environment."
        rm -f "$archive_list"
        exit 1
    fi

    echo "l" | "$PYI_ARCHIVE_VIEWER" "$DIST_EXE" >"$archive_list" 2>/dev/null

    if ! grep -Fq "$SIDECAR_NAME" "$archive_list"; then
        print_error "uploader sidecar was not bundled into $APP_NAME."
        rm -f "$archive_list"
        exit 1
    fi
    echo "  - Go sidecar bundled"

    if ! grep -Fq "tkinterdnd2" "$archive_list"; then
        print_error "tkinterdnd2 assets were not bundled."
        rm -f "$archive_list"
        exit 1
    fi
    echo "  - tkinterdnd2 assets bundled"

    rm -f "$archive_list"

    local size
    size="$(du -h "$DIST_EXE" | cut -f1)"
    echo "  - Final size: $size"
}

show_success() {
    echo
    echo -e "${GREEN}========================================================${NC}"
    echo -e "${GREEN}                  BUILD SUCCESS!${NC}"
    echo -e "${GREEN}========================================================${NC}"
    echo
    echo "Executable: $DIST_EXE"
    echo "Version: $VERSION"
    echo
}

clean_build() {
    echo "Cleaning build artifacts..."
    rm -rf build dist __pycache__ .pytest_cache
    rm -f "$APP_NAME.spec" uploader uploader.exe
    echo "Clean complete!"
}

main() {
    print_header

    case "${1:-}" in
        clean)
            clean_build
            exit 0
            ;;
        --clean)
            clean_build
            ;;
        --ci)
            ;;
        help|--help|-h)
            show_help
            exit 0
            ;;
        "")
            ;;
        *)
            print_error "Unknown option: $1"
            echo
            show_help
            exit 1
            ;;
    esac

    check_python
    check_go
    build_go_sidecar
    setup_python_env
    build_executable
    verify_build
    show_success
}

main "$@"
