# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Print one version's section of docs/CHANGELOG.md for a GitHub release body.

Usage: extract_release_notes.py <version> [changelog_path]

The section is everything after its ``## [<version>]`` heading up to the next
``## [`` heading (or the end of the file); the heading itself is not printed.
A leading ``v`` on the version is ignored, and the label must match exactly,
so ``3.1`` never matches ``## [3.1.3]``.

A missing or empty section exits non-zero with a GitHub Actions error instead
of publishing a wrong body. (The workflow's earlier awk pipeline always came
out empty and silently fell back to copying the whole changelog.)
"""

import re
import sys
from pathlib import Path

HEADING = re.compile(r"^## \[([^\]]+)\]")


def extract(changelog_text: str, version: str) -> str:
    """Return the body of the ``## [version]`` section, ending with one newline."""
    label = version.strip()
    if label.startswith("v"):
        label = label[1:]

    found = False
    body = []
    for line in changelog_text.splitlines():
        heading = HEADING.match(line)
        if heading:
            if found:
                break
            found = heading.group(1) == label
            continue
        if found:
            body.append(line)

    if not found:
        raise LookupError(f"docs/CHANGELOG.md has no '## [{label}]' section")
    notes = "\n".join(body).strip()
    if not notes:
        raise LookupError(f"the '## [{label}]' section of docs/CHANGELOG.md is empty")
    return notes + "\n"


def main(argv: list) -> int:
    if len(argv) not in (2, 3):
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    path = Path(argv[2] if len(argv) == 3 else "docs/CHANGELOG.md")
    try:
        notes = extract(path.read_text(encoding="utf-8"), argv[1])
    except (OSError, LookupError) as exc:
        print(f"::error file={path}::Cannot build release notes: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
