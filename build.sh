#!/usr/bin/env bash
# Connie's Uploader Ultimate - Cross-Platform Build Script
# For Linux and macOS

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Configuration
PYTHON_CMD="python3"
GO_VERSION_MIN="1.21"
PYTHON_VERSION_MIN="3.11"
APP_NAME="ConniesUploader"
VERSION="1.1.0"

# Functions
print_header() {
    echo -e "${BLUE}========================================================${NC}"
    echo -e "${BLUE}      Connie's Uploader Ultimate - Build Tool${NC}"
    echo -e "${BLUE}      Version: $VERSION${NC}"
    echo -e "${BLUE}      Platform: $(uname -s) $(uname -m)${NC}"
    echo -e "${BLUE}========================================================${NC}"
    echo
}

print_step() {
    echo -e "${GREEN}[$1] $2${NC}"
}

print_error() {
    echo -e "${RED}[ERROR] $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
}

check_command() {
    if ! command -v "$1" &> /dev/null; then
        return 1
    fi
    return 0
}

check_python() {
    print_step "1/5" "Checking Python installation..."

    if ! check_command "$PYTHON_CMD"; then
        print_error "Python 3 not found!"
        echo "Please install Python 3.11 or higher:"
        echo "  - Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
        echo "  - macOS: brew install python@3.11"
        echo "  - Fedora: sudo dnf install python3"
        exit 1
    fi

    PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
    echo "  ✓ Found Python $PYTHON_VERSION"
}

check_go() {
    print_step "2/5" "Checking Go installation..."

    if ! check_command "go"; then
        print_error "Go not found!"
        echo "Please install Go 1.21 or higher:"
        echo "  - Ubuntu/Debian: sudo snap install go --classic"
        echo "  - macOS: brew install go"
        echo "  - Fedora: sudo dnf install golang"
        echo "  - Or download from: https://go.dev/dl/"
        exit 1
    fi

    GO_VERSION=$(go version | awk '{print $3}' | sed 's/go//')
    echo "  ✓ Found Go $GO_VERSION"
}

build_go_sidecar() {
    print_step "3/5" "Building Go sidecar..."

    if [ ! -f "uploader.go" ]; then
        print_error "uploader.go not found!"
        exit 1
    fi

    echo "  - Running go mod tidy..."
    go mod tidy

    echo "  - Compiling optimized binary..."
    go build -ldflags="-s -w" -o uploader uploader.go

    if [ ! -f "uploader" ]; then
        print_error "Failed to build uploader binary!"
        exit 1
    fi

    echo "  ✓ Go sidecar built successfully"

    # Make it executable
    chmod +x uploader
}

setup_python_env() {
    print_step "4/5" "Setting up Python environment..."

    if [ ! -f "requirements.txt" ]; then
        print_error "requirements.txt not found!"
        exit 1
    fi

    # Create venv if it doesn't exist
    if [ ! -d "venv" ]; then
        echo "  - Creating virtual environment..."
        $PYTHON_CMD -m venv venv
    else
        echo "  - Using existing virtual environment..."
    fi

    # Activate venv
    source venv/bin/activate

    echo "  - Installing Python dependencies..."
    pip install --upgrade pip > /dev/null
    pip install -r requirements.txt

    echo "  ✓ Python environment ready"
}

build_executable() {
    print_step "5/5" "Building final executable..."

    if [ ! -f "uploader" ]; then
        print_error "uploader binary not found! Build Go sidecar first."
        exit 1
    fi

    # Activate venv if not already activated
    if [ -z "$VIRTUAL_ENV" ]; then
        source venv/bin/activate
    fi

    echo "  - Packaging with PyInstaller..."
    pyinstaller --noconsole --onefile --clean \
        --name "$APP_NAME" \
        --icon "logo.ico" \
        --add-data "uploader:." \
        --add-data "logo.ico:." \
        --collect-all tkinterdnd2 \
        --collect-submodules modules.plugins \
        --hidden-import modules.plugins.imx \
        --hidden-import modules.plugins.pixhost \
        --hidden-import modules.plugins.pixhost_v2 \
        --hidden-import modules.plugins.vipr \
        --hidden-import modules.plugins.turbo \
        --hidden-import modules.plugins.imagebam \
        --hidden-import modules.plugins.imgur \
        main.py

    if [ ! -f "dist/$APP_NAME" ]; then
        print_error "Build failed! No executable found in dist/ folder."
        exit 1
    fi

    # Make it executable
    chmod +x "dist/$APP_NAME"

    echo "  ✓ Executable built successfully"
}

show_success() {
    echo
    echo -e "${GREEN}========================================================${NC}"
    echo -e "${GREEN}                  BUILD SUCCESS!${NC}"
    echo -e "${GREEN}========================================================${NC}"
    echo
    echo "Your application is ready:"
    echo "  Location: dist/$APP_NAME"
    echo "  Version: $VERSION"
    echo

    # Show file size
    if [ -f "dist/$APP_NAME" ]; then
        SIZE=$(du -h "dist/$APP_NAME" | cut -f1)
        echo "  Size: $SIZE"
    fi

    echo
    echo "To run: ./dist/$APP_NAME"
    echo
}

clean_build() {
    echo "Cleaning build artifacts..."
    rm -rf build dist *.spec __pycache__ .pytest_cache
    rm -f uploader
    echo "Clean complete!"
}

# Main script
main() {
    print_header

    # Handle command line arguments
    case "${1:-}" in
        clean)
            clean_build
            exit 0
            ;;
        --clean)
            clean_build
            ;;
        help|--help|-h)
            echo "Usage: $0 [OPTION]"
            echo
            echo "Options:"
            echo "  (no args)    Full build"
            echo "  clean        Clean build artifacts"
            echo "  --clean      Clean before building"
            echo "  help         Show this help message"
            exit 0
            ;;
    esac

    # Build process
    check_python
    check_go
    build_go_sidecar
    setup_python_env
    build_executable
    show_success
}

# Run main
main "$@"
