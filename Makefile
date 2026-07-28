# Makefile for Connie's Uploader
# Cross-platform build system for Windows, Linux, and macOS

.PHONY: all clean build test help install-deps build-go build-python package dev

# Detect OS
ifeq ($(OS),Windows_NT)
    DETECTED_OS := Windows
    VENV_BIN := venv\Scripts
    PYTHON := python
    GO_OUTPUT := uploader.exe
    FINAL_EXE := dist\ConniesUploader.exe
else
    DETECTED_OS := $(shell uname -s)
    VENV_BIN := venv/bin
    PYTHON := python3
    GO_OUTPUT := uploader
    FINAL_EXE := dist/ConniesUploader
endif

# Build configuration
GO_FLAGS := -ldflags="-s -w"
PYINSTALLER_FLAGS := --noconsole --onefile --clean
APP_NAME := ConniesUploader
VERSION := 3.0.1

# Default target
all: build

# Show help
help:
	@echo "Connie's Uploader - Build System v$(VERSION)"
	@echo ""
	@echo "Detected OS: $(DETECTED_OS)"
	@echo ""
	@echo "Available targets:"
	@echo "  make build         - Full build (Go + Python + package)"
	@echo "  make build-go      - Build Go sidecar only"
	@echo "  make build-python  - Build Python app with PyInstaller"
	@echo "  make install-deps  - Install Python dependencies"
	@echo "  make test          - Run tests"
	@echo "  make clean         - Remove build artifacts"
	@echo "  make dev           - Setup development environment"
	@echo "  make package       - Package final executable"
	@echo "  make help          - Show this help message"

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	$(PYTHON) scripts/maintenance/clean_generated.py

# Install Python dependencies
install-deps:
	@echo "Installing Python dependencies..."
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r frontend/requirements.txt
	@echo "Dependencies installed!"

# Build Go sidecar
build-go:
	@echo "Building Go sidecar..."
	@echo "  - Running go mod tidy..."
	cd backend && go mod tidy
	@echo "  - Compiling optimized binary..."
	cd backend && go build $(GO_FLAGS) -o ../$(GO_OUTPUT) .
	@echo "Go sidecar built: $(GO_OUTPUT)"

# Build Python application with PyInstaller
build-python: build-go
	@echo "Building Python application..."
	cd frontend && pyinstaller $(PYINSTALLER_FLAGS) \
		--name "$(APP_NAME)" \
		--icon "../packaging/logo.ico" \
		--add-data "../$(GO_OUTPUT)$(if $(filter Windows,$(DETECTED_OS)),;.,:)" \
		--add-data "../packaging/logo.ico$(if $(filter Windows,$(DETECTED_OS)),;.,:)" \
		--additional-hooks-dir "../packaging/pyinstaller_hooks" \
		--distpath "../dist" \
		--workpath "../build" \
		--specpath "../packaging" \
		--collect-all tkinterdnd2 \
		--collect-submodules modules.plugins \
		--hidden-import modules.plugins.imx \
		--hidden-import modules.plugins.pixhost \
		--hidden-import modules.plugins.vipr \
		--hidden-import modules.plugins.turbo \
		--hidden-import modules.plugins.imagebam \
		--hidden-import modules.plugins.imgur \
		main.py
	@echo "Build complete: $(FINAL_EXE)"

# Full build
build: clean install-deps build-python
	@echo "========================================="
	@echo "Build successful!"
	@echo "Executable: $(FINAL_EXE)"
	@echo "========================================="

# Package (alias for build-python)
package: build-python

# Run tests
test:
	@echo "Running tests..."
	cd frontend && $(PYTHON) -m pytest tests/ -v
	cd backend && go test ./...
	@echo "Tests complete!"

# Setup development environment
dev:
	@echo "Setting up development environment..."
	@if [ ! -d "venv" ]; then \
		echo "Creating virtual environment..."; \
		$(PYTHON) -m venv venv; \
	fi
	@echo "Installing dependencies..."
	$(VENV_BIN)/pip install -r frontend/requirements.txt
	@echo "Building Go sidecar..."
	$(MAKE) build-go
	@echo "Development environment ready!"
	@echo "Activate with: source venv/bin/activate (Linux/Mac) or venv\Scripts\activate (Windows)"

# Quick build (no clean)
quick: build-go build-python

# Run the application (for testing)
run: build-go
	@echo "Running application..."
	cd frontend && $(PYTHON) main.py
