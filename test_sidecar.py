#!/usr/bin/env python3
"""
Test script to verify Go sidecar (uploader.exe) can be found.
Run this after building to verify the sidecar is properly bundled.
"""
import os
import sys

def test_sidecar_location():
    """Test all possible locations where sidecar might be found."""
    print("=" * 60)
    print("Sidecar Location Test")
    print("=" * 60)
    print()

    # Check if running from PyInstaller
    is_frozen = getattr(sys, "frozen", False)
    print(f"Running from PyInstaller: {is_frozen}")

    if is_frozen:
        if hasattr(sys, '_MEIPASS'):
            print(f"PyInstaller temp dir (_MEIPASS): {sys._MEIPASS}")
        print(f"Executable location: {sys.executable}")
        print(f"Executable directory: {os.path.dirname(sys.executable)}")

    print()
    print("Searching for uploader.exe...")
    print()

    # Build list of locations to check
    locations = []

    # Location 1: PyInstaller temp directory
    if hasattr(sys, '_MEIPASS'):
        locations.append(("PyInstaller _MEIPASS", sys._MEIPASS))

    # Location 2: Executable directory
    if is_frozen:
        locations.append(("Executable directory", os.path.dirname(sys.executable)))

    # Location 3: Current working directory
    locations.append(("Current working directory", os.getcwd()))

    # Location 4: Script directory (development)
    if not is_frozen:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        locations.append(("Script directory", script_dir))

    # Check each location
    found = False
    binary_name = "uploader.exe" if os.name == "nt" else "uploader"

    for idx, (name, path) in enumerate(locations, 1):
        full_path = os.path.join(path, binary_name)
        exists = os.path.exists(full_path)

        status = "✓ FOUND" if exists else "✗ Not found"
        print(f"{idx}. {name}")
        print(f"   Path: {full_path}")
        print(f"   Status: {status}")

        if exists:
            size = os.path.getsize(full_path)
            print(f"   Size: {size:,} bytes ({size / 1024 / 1024:.2f} MB)")
            found = True

        print()

    print("=" * 60)
    if found:
        print("✓ SUCCESS: uploader.exe found!")
    else:
        print("✗ FAILURE: uploader.exe NOT found!")
        print()
        print("Troubleshooting:")
        print("1. Ensure you built uploader.exe with: go build uploader.go")
        print("2. Check PyInstaller command includes: --add-data 'uploader.exe;.'")
        print("3. Verify uploader.exe exists in project root before building")
        print("4. Try deleting dist/ and build/ folders and rebuilding")
    print("=" * 60)

    return found

if __name__ == "__main__":
    success = test_sidecar_location()
    sys.exit(0 if success else 1)
