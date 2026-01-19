#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""
Script to add SPDX license headers to all Python and Go source files.
"""

import os
import sys
from pathlib import Path
from typing import List, Tuple

PYTHON_HEADER = """# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""

GO_HEADER = """// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

"""

SHEBANG_PYTHON_HEADER = """#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""


def has_license_header(content: str) -> bool:
    """Check if content already has an SPDX license header."""
    return "SPDX-License-Identifier" in content[:500]


def add_python_header(file_path: Path) -> bool:
    """Add SPDX header to a Python file. Returns True if modified."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if has_license_header(content):
            return False

        # Check if file starts with shebang
        if content.startswith("#!"):
            # Find end of shebang line
            first_newline = content.find("\n")
            if first_newline == -1:
                header = SHEBANG_PYTHON_HEADER
                new_content = content
            else:
                shebang = content[: first_newline + 1]
                rest = content[first_newline + 1 :]
                # Remove shebang and add it with header
                new_content = shebang + PYTHON_HEADER[len(shebang) :] + rest
        else:
            new_content = PYTHON_HEADER + content

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return True
    except Exception as e:
        print(f"Error processing {file_path}: {e}", file=sys.stderr)
        return False


def add_go_header(file_path: Path) -> bool:
    """Add SPDX header to a Go file. Returns True if modified."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if has_license_header(content):
            return False

        new_content = GO_HEADER + content

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return True
    except Exception as e:
        print(f"Error processing {file_path}: {e}", file=sys.stderr)
        return False


def find_source_files(root_dir: Path) -> Tuple[List[Path], List[Path]]:
    """Find all Python and Go source files."""
    python_files = []
    go_files = []

    # Directories to skip
    skip_dirs = {"venv", ".venv", "env", "__pycache__", ".git", "node_modules", "build", "dist"}

    for root, dirs, files in os.walk(root_dir):
        # Remove skip directories from dirs list to prevent traversal
        dirs[:] = [d for d in dirs if d not in skip_dirs]

        for file in files:
            file_path = Path(root) / file

            if file.endswith(".py"):
                python_files.append(file_path)
            elif file.endswith(".go"):
                go_files.append(file_path)

    return python_files, go_files


def main():
    """Main function to add license headers to all source files."""
    root_dir = Path(__file__).parent

    print("Finding source files...")
    python_files, go_files = find_source_files(root_dir)

    print(f"\nFound {len(python_files)} Python files and {len(go_files)} Go files")

    # Process Python files
    python_modified = 0
    print("\nProcessing Python files...")
    for file_path in python_files:
        if add_python_header(file_path):
            print(f"  ✓ Added header to {file_path.relative_to(root_dir)}")
            python_modified += 1
        else:
            print(f"  - Skipped {file_path.relative_to(root_dir)} (already has header)")

    # Process Go files
    go_modified = 0
    print("\nProcessing Go files...")
    for file_path in go_files:
        if add_go_header(file_path):
            print(f"  ✓ Added header to {file_path.relative_to(root_dir)}")
            go_modified += 1
        else:
            print(f"  - Skipped {file_path.relative_to(root_dir)} (already has header)")

    print(f"\n✅ Complete!")
    print(f"   Python files modified: {python_modified}/{len(python_files)}")
    print(f"   Go files modified: {go_modified}/{len(go_files)}")
    print(f"   Total modified: {python_modified + go_modified}/{len(python_files) + len(go_files)}")


if __name__ == "__main__":
    main()
