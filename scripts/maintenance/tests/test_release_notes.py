import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "maintenance" / "extract_release_notes.py"


def load():
    spec = importlib.util.spec_from_file_location("extract_release_notes", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SAMPLE = """# Changelog

Intro text that must never appear in a release body.

## [Unreleased]

- Not released yet.

## [3.1.3] - 2026-11-18

The lead paragraph for 3.1.3.

### Fixed

- Fix A.

## [3.1.2] - 2026-11-06

### Fixed

- Fix B.

## [3.1] - 2026-01-01

- Old two-part version.

[3.1.3]: https://example.test/compare/v3.1.2...v3.1.3
"""


class ExtractReleaseNotesTests(unittest.TestCase):
    def setUp(self):
        self.mod = load()

    def test_extracts_only_the_requested_section(self):
        notes = self.mod.extract(SAMPLE, "3.1.3")
        self.assertEqual(notes, "The lead paragraph for 3.1.3.\n\n### Fixed\n\n- Fix A.\n")

    def test_accepts_a_leading_v(self):
        self.assertEqual(self.mod.extract(SAMPLE, "v3.1.3"), self.mod.extract(SAMPLE, "3.1.3"))

    def test_version_must_match_the_whole_heading_label(self):
        # "3.1" must not match "## [3.1.3]" or "## [3.1.2]".
        self.assertEqual(self.mod.extract(SAMPLE, "3.1"), "- Old two-part version.\n\n[3.1.3]: https://example.test/compare/v3.1.2...v3.1.3\n")

    def test_last_section_runs_to_end_of_file(self):
        text = "# Changelog\n\n## [1.0.0] - 2026-01-01\n\n- Only entry.\n"
        self.assertEqual(self.mod.extract(text, "1.0.0"), "- Only entry.\n")

    def test_missing_version_is_an_error(self):
        with self.assertRaisesRegex(LookupError, r"no '## \[9\.9\.9\]' section"):
            self.mod.extract(SAMPLE, "9.9.9")

    def test_empty_section_is_an_error(self):
        text = "## [2.0.0] - 2026-01-01\n\n## [1.0.0] - 2025-01-01\n\n- x\n"
        with self.assertRaisesRegex(LookupError, "is empty"):
            self.mod.extract(text, "2.0.0")

    def test_real_changelog_has_a_clean_3_1_3_section(self):
        notes = self.mod.extract((ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8"), "v3.1.3")
        self.assertIn("### Fixed", notes)
        self.assertNotIn("# Changelog", notes)
        self.assertNotIn("## [3.1.2]", notes)
        self.assertLess(len(notes.splitlines()), 60)

    def test_cli_prints_notes_and_fails_loudly_when_missing(self):
        ok = subprocess.run(
            [sys.executable, str(SCRIPT), "v3.1.3", str(ROOT / "docs" / "CHANGELOG.md")],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertTrue(ok.stdout.startswith("The `v3.1.2` tag was cut before"))

        missing = subprocess.run(
            [sys.executable, str(SCRIPT), "v9.9.9", str(ROOT / "docs" / "CHANGELOG.md")],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(missing.stdout, "")
        self.assertIn("::error", missing.stderr)


class ReleaseWorkflowTests(unittest.TestCase):
    def test_release_workflow_uses_the_script_and_never_copies_the_whole_changelog(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/maintenance/extract_release_notes.py", workflow)
        self.assertNotIn('cp "$CHANGELOG_PATH"', workflow)
        self.assertNotIn("awk", workflow)


if __name__ == "__main__":
    unittest.main()
