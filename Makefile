# Makefile for Connie's Uploader Ultimate
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
VERSION := 1.1.0

# Default target
all: build

# Show help
help:
	@echo "Connie's Uploader Ultimate - Build System v$(VERSION)"
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
	rm -rf build dist *.spec __pycache__ .pytest_cache
	rm -f $(GO_OUTPUT)
	@echo "Clean complete!"

# Install Python dependencies
install-deps:
	@echo "Installing Python dependencies..."
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	@echo "Dependencies installed!"

# Build Go sidecar
build-go:
	@echo "Building Go sidecar..."
	@echo "  - Running go mod tidy..."
	go mod tidy
	@echo "  - Compiling optimized binary..."
	go build $(GO_FLAGS) -o $(GO_OUTPUT) uploader.go
	@echo "Go sidecar built: $(GO_OUTPUT)"

# Build Python application with PyInstaller
build-python: build-go
	@echo "Building Python application..."
	pyinstaller $(PYINSTALLER_FLAGS) \
		--name "$(APP_NAME)" \
		--icon "logo.ico" \
		--add-data "$(GO_OUTPUT)$(if $(filter Windows,$(DETECTED_OS)),;.,:)" \
		--add-data "logo.ico$(if $(filter Windows,$(DETECTED_OS)),;.,:)" \
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
	$(PYTHON) -m pytest tests/ -v
	@echo "Tests complete!"

# Setup development environment
dev:
	@echo "Setting up development environment..."
	@if [ ! -d "venv" ]; then \
		echo "Creating virtual environment..."; \
		$(PYTHON) -m venv venv; \
	fi
	@echo "Installing dependencies..."
	$(VENV_BIN)/pip install -r requirements.txt
	@echo "Building Go sidecar..."
	$(MAKE) build-go
	@echo "Development environment ready!"
	@echo "Activate with: source venv/bin/activate (Linux/Mac) or venv\Scripts\activate (Windows)"

# Quick build (no clean)
quick: build-go build-python

# Run the application (for testing)
run: build-go
	@echo "Running application..."
	$(PYTHON) main.py
