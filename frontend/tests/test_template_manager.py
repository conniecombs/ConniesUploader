# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Comprehensive tests for modules/template_manager.py - Template management and substitution"""

import pytest
import os
import sys
import tempfile
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules import template_manager  # noqa: E402
from modules.template_manager import (
    TemplateEditor,
    TemplateManager,
    TemplateValidationError,
)  # noqa: E402


@pytest.mark.unit
class TestTemplateManagerImports:
    """Test template manager module imports"""

    def test_module_import(self):
        """Test that template_manager module imports successfully"""
        from modules import template_manager

        assert template_manager is not None

    def test_template_manager_class_exists(self):
        """Test that TemplateManager class exists"""
        assert TemplateManager is not None


@pytest.mark.unit
class TestTemplateManagerInstantiation:
    """Test template manager instantiation and initialization"""

    def test_can_instantiate(self):
        """Test that TemplateManager can be instantiated"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))
            assert tm is not None

    def test_templates_file_created(self):
        """Test that templates file is created if it doesn't exist"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            assert not templates_file.exists()

            TemplateManager(str(templates_file))

            # File should be created
            assert templates_file.exists()

    def test_load_existing_templates(self):
        """Test loading existing templates from file"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"

            # Create template file with sample data
            sample_templates = {
                "BBCode": "[url={viewer}][img]{thumb}[/img][/url]",
                "HTML": '<a href="{viewer}"><img src="{thumb}" /></a>',
            }

            with open(templates_file, "w") as f:
                json.dump(sample_templates, f)

            tm = TemplateManager(str(templates_file))
            templates = tm.get_all_templates()

            assert "BBCode" in templates
            assert "HTML" in templates

    def test_default_template_path_uses_user_data_dir(self, tmp_path, monkeypatch):
        template_path = tmp_path / ".conniesuploader" / "templates.json"
        legacy_path = tmp_path / "user_templates.json"
        monkeypatch.setattr(template_manager, "DEFAULT_TEMPLATE_FILE", str(template_path))
        monkeypatch.setattr(template_manager, "LEGACY_TEMPLATE_FILE", str(legacy_path))

        tm = TemplateManager()

        assert Path(tm.filepath) == template_path
        assert template_path.exists()

    def test_default_template_path_migrates_legacy_file(self, tmp_path, monkeypatch):
        template_path = tmp_path / ".conniesuploader" / "templates.json"
        legacy_path = tmp_path / "user_templates.json"
        legacy_path.write_text(json.dumps({"Legacy": "#all_images#"}), encoding="utf-8")
        monkeypatch.setattr(template_manager, "DEFAULT_TEMPLATE_FILE", str(template_path))
        monkeypatch.setattr(template_manager, "LEGACY_TEMPLATE_FILE", str(legacy_path))

        tm = TemplateManager()

        assert tm.get_template("Legacy") == "#all_images#"
        assert template_path.exists()
        assert not legacy_path.exists()
        assert list(tmp_path.glob("user_templates.json.migrated-*.bak"))

    def test_default_template_path_does_not_migrate_when_new_file_exists(
        self, tmp_path, monkeypatch
    ):
        template_path = tmp_path / ".conniesuploader" / "templates.json"
        legacy_path = tmp_path / "user_templates.json"
        template_path.parent.mkdir()
        template_path.write_text(json.dumps({"Current": "#all_images#"}), encoding="utf-8")
        legacy_path.write_text(json.dumps({"Legacy": "#all_images#"}), encoding="utf-8")
        monkeypatch.setattr(template_manager, "DEFAULT_TEMPLATE_FILE", str(template_path))
        monkeypatch.setattr(template_manager, "LEGACY_TEMPLATE_FILE", str(legacy_path))

        tm = TemplateManager()

        assert tm.get_template("Current") == "#all_images#"
        assert legacy_path.exists()
        assert not list(tmp_path.glob("user_templates.json.migrated-*.bak"))


@pytest.mark.unit
class TestTemplateOperations:
    """Test template CRUD operations"""

    def test_add_template(self):
        """Test adding a new template"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            template_content = "[url=#image_url#][img]#thumb_url#[/img][/url]"
            tm.add_template("Test Template", template_content)

            templates = tm.get_all_templates()
            assert "Test Template" in templates
            assert templates["Test Template"] == template_content

    def test_get_template(self):
        """Test retrieving a specific template"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            template_content = "[img]#direct_url#[/img]"
            tm.add_template("Direct Link", template_content)

            retrieved = tm.get_template("Direct Link")
            assert retrieved == template_content

    def test_get_nonexistent_template(self):
        """Test retrieving a template that doesn't exist"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            result = tm.get_template("Nonexistent")
            assert result is None or result == ""

    def test_delete_template(self):
        """Test deleting a template"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            tm.add_template("To Delete", "[url]#image_url#[/url]")
            assert "To Delete" in tm.get_all_templates()

            tm.delete_template("To Delete")
            assert "To Delete" not in tm.get_all_templates()

    def test_update_template(self):
        """Test updating an existing template"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            original = "[img]#thumb_url#[/img]"
            updated = "[url=#image_url#][img]#thumb_url#[/img][/url]"

            tm.add_template("MyTemplate", original)
            assert tm.get_template("MyTemplate") == original

            tm.add_template("MyTemplate", updated)  # Update by adding again
            assert tm.get_template("MyTemplate") == updated

    def test_filter_template_names_matches_name_and_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            tm.add_template("Gallery Layout", "[url=#gallery_link#]Gallery[/url] #all_images#")
            tm.add_template("Plain Images", "#all_images#")

            assert "Gallery Layout" in tm.filter_template_names("gallery")
            assert "Gallery Layout" in tm.filter_template_names("gallery_link")
            assert "Plain Images" not in tm.filter_template_names("gallery_link")

    def test_import_export_templates_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_path = Path(temp_dir) / "templates-export.json"
            source_path = Path(temp_dir) / "source.json"
            target_path = Path(temp_dir) / "target.json"
            source = TemplateManager(str(source_path))
            target = TemplateManager(str(target_path))

            source.add_template("Exported", "#all_images#")
            exported = source.export_templates_file(str(export_path), names=["Exported"])
            imported, skipped, errors = target.import_templates_file(str(export_path))

            assert exported == 1
            assert imported == 1
            assert skipped == 0
            assert errors == []
            assert target.get_template("Exported") == "#all_images#"

    def test_export_templates_file_includes_version_timestamp_and_selected_templates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_path = Path(temp_dir) / "templates-export.json"
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))
            tm.add_template("Exported", "#all_images#")

            exported = tm.export_templates_file(str(export_path), names=["Exported"])
            payload = json.loads(export_path.read_text(encoding="utf-8"))

            assert exported == 1
            assert payload["version"] == template_manager.TEMPLATE_EXPORT_VERSION
            assert payload["exported_at"]
            assert payload["templates"] == {"Exported": "#all_images#"}

    def test_import_templates_respects_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            import_path = Path(temp_dir) / "templates-import.json"
            templates_file = Path(temp_dir) / "templates.json"
            import_path.write_text(
                json.dumps({"templates": {"Existing": "#all_images# imported"}}),
                encoding="utf-8",
            )
            tm = TemplateManager(str(templates_file))
            tm.add_template("Existing", "#all_images# original")

            imported, skipped, errors = tm.import_templates_file(
                str(import_path),
                overwrite=False,
            )

            assert imported == 0
            assert skipped == 1
            assert errors == []
            assert tm.get_template("Existing") == "#all_images# original"

    def test_import_templates_skips_invalid_templates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            import_path = Path(temp_dir) / "bad-import.json"
            templates_file = Path(temp_dir) / "templates.json"
            import_path.write_text(
                json.dumps(
                    {
                        "templates": {
                            "Good": "#all_images#",
                            "Bad": "#not_a_real_placeholder#",
                        }
                    }
                ),
                encoding="utf-8",
            )
            tm = TemplateManager(str(templates_file))

            imported, skipped, errors = tm.import_templates_file(str(import_path))

            assert imported == 1
            assert skipped == 1
            assert "Good" in tm.get_all_templates()
            assert any("Bad:" in error for error in errors)


@pytest.mark.unit
class TestTemplatePlaceholders:
    """Test template placeholder handling"""

    def test_common_placeholders(self):
        """Test that common placeholders are recognized"""
        placeholders = ["{viewer}", "{thumb}", "{direct}", "{gallery_link}", "{gallery_name}"]

        template = " ".join(placeholders)

        for placeholder in placeholders:
            assert placeholder in template

    def test_placeholder_substitution(self):
        """Test substituting placeholders with values"""
        template = "[url={viewer}][img]{thumb}[/img][/url]"

        values = {
            "viewer": "https://example.com/view/123",
            "thumb": "https://example.com/thumb/123.jpg",
        }

        result = template.format(**values)

        assert "https://example.com/view/123" in result
        assert "https://example.com/thumb/123.jpg" in result
        assert "{viewer}" not in result
        assert "{thumb}" not in result

    def test_missing_placeholder_handling(self):
        """Test behavior when placeholder is missing from values"""
        template = "[url={viewer}][img]{thumb}[/img][/url]"

        values = {
            "viewer": "https://example.com/view/123"
            # Missing 'thumb'
        }

        try:
            template.format(**values)
            pytest.fail("Should raise KeyError for missing placeholder")
        except KeyError:
            # Expected behavior
            pass

    def test_extra_values_ignored(self):
        """Test that extra values in dict are ignored"""
        template = "[img]{thumb}[/img]"

        values = {
            "thumb": "https://example.com/thumb.jpg",
            "extra": "ignored",
            "another": "also ignored",
        }

        result = template.format(**values)
        assert "https://example.com/thumb.jpg" in result
        assert "ignored" not in result


@pytest.mark.unit
class TestTemplatePersistence:
    """Test template persistence to file"""

    def test_templates_saved_to_file(self):
        """Test that templates are saved to disk"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            tm.add_template("Test", "[img]#thumb_url#[/img]")
            tm.save()  # Assuming save method exists

            # Read file directly
            with open(templates_file, "r") as f:
                saved_data = json.load(f)

            assert "Test" in saved_data

    def test_templates_save_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            tm.add_template("Atomic", "#all_images#")

            assert templates_file.exists()
            assert not Path(f"{templates_file}.tmp").exists()
            saved_data = json.loads(templates_file.read_text(encoding="utf-8"))
            assert saved_data["Atomic"] == "#all_images#"

    def test_templates_persist_across_instances(self):
        """Test that templates persist when creating new instance"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"

            # First instance
            tm1 = TemplateManager(str(templates_file))
            tm1.add_template("Persistent", "[url]#image_url#[/url]")

            # Second instance
            tm2 = TemplateManager(str(templates_file))
            templates = tm2.get_all_templates()

            assert "Persistent" in templates

    def test_restore_defaults_removes_custom_templates(self):
        """Test that defaults can be restored after user edits"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            tm.add_template("Custom", "[img]#image_url#[/img]")
            assert "Custom" in tm.get_all_templates()

            tm.restore_defaults()
            templates = tm.get_all_templates()

            assert "Custom" not in templates
            assert templates["BBCode"] == tm.defaults["BBCode"]
            assert tm.get_recovery_issue() is None

    def test_file_corruption_handling(self):
        """Test handling of corrupted template file"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"

            # Write invalid JSON
            broken_json = "{invalid json"
            templates_file.write_text(broken_json, encoding="utf-8")

            tm = TemplateManager(str(templates_file))
            issue = tm.get_recovery_issue()

            assert issue is not None
            assert Path(issue["filepath"]).resolve() == templates_file.resolve()
            assert issue["backup_path"]
            backup_path = Path(issue["backup_path"])
            assert backup_path.exists()
            assert backup_path.read_text(encoding="utf-8") == broken_json

            restored_data = json.loads(templates_file.read_text(encoding="utf-8"))
            assert restored_data["BBCode"] == tm.defaults["BBCode"]

    def test_file_recovery_handles_valid_json_that_is_not_an_object(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            templates_file.write_text('["not", "a", "template", "object"]', encoding="utf-8")

            tm = TemplateManager(str(templates_file))
            issue = tm.get_recovery_issue()

            assert issue is not None
            assert "Template file must contain a JSON object" in issue["error"]
            assert Path(issue["backup_path"]).exists()
            assert (
                json.loads(templates_file.read_text(encoding="utf-8"))["BBCode"]
                == tm.defaults["BBCode"]
            )


@pytest.mark.unit
class TestDefaultTemplates:
    """Test default template functionality"""

    def test_has_default_templates(self):
        """Test that default templates are provided"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            templates = tm.get_all_templates()

            # Should have at least one default template
            assert len(templates) > 0

    def test_default_bbcode_template(self):
        """Test that BBCode template exists"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            templates = tm.get_all_templates()

            # Common default template names
            has_bbcode = any(key.lower().find("bbcode") >= 0 for key in templates.keys())
            assert has_bbcode

    def test_builtin_template_categories_include_vipergirls_templates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            categories = tm.get_category_names()
            vipergirls_templates = tm.get_all_keys("ViperGirls")

            assert categories[0] == "All"
            assert "ViperGirls" in categories
            assert tm.get_template_category("ViperGirls Gallery Post") == "ViperGirls"
            assert "ViperGirls Gallery Post" in vipergirls_templates
            assert "ViperGirls Compact Grid" in vipergirls_templates
            assert "BBCode" not in vipergirls_templates

    def test_template_filter_can_limit_by_category(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            filtered = tm.filter_template_names("gallery", category="ViperGirls")

            assert "ViperGirls Gallery Post" in filtered
            assert "Cover + Gallery ID" not in filtered

    def test_all_builtin_templates_validate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            assert tm.validate_all_templates() == {}


@pytest.mark.unit
class TestTemplateValidation:
    """Test template validation"""

    def test_empty_template_name(self):
        """Test handling of empty template name"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            with pytest.raises(TemplateValidationError):
                tm.add_template("", "[img]{thumb}[/img]")

    def test_empty_template_content(self):
        """Test handling of empty template content"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            with pytest.raises(TemplateValidationError):
                tm.add_template("Empty", "")

    def test_template_validation_reports_unknown_placeholders_and_unclosed_conditionals(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            errors = tm.validate_template("[if #bad_placeholder#]#all_images#")

            assert "Unknown placeholder(s): #bad_placeholder#" in errors
            assert "Template has an unclosed [if] block." in errors

    def test_template_validation_requires_image_output_placeholder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            errors = tm.validate_template("[url=#gallery_link#]Gallery[/url]")

            assert any("image output placeholder" in error for error in errors)

    def test_template_validation_reports_unmatched_else_and_duplicate_else(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            else_without_if = tm.validate_template("#all_images#[else]")
            duplicate_else = tm.validate_template(
                "[if gallery_link]A[else]B[else]C[/if]#all_images#"
            )

            assert "Template has an [else] without a matching [if]." in else_without_if
            assert "Template has more than one [else] in an [if] block." in duplicate_else

    def test_template_validation_reports_mismatched_nested_blocks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            errors = tm.validate_template("[if gallery_link][for image]#image_url#[/if][/for]")

            assert "Template has a closing [/if] without a matching [if]." in errors
            assert "Template has an unclosed [if] block." in errors

    def test_very_long_template(self):
        """Test handling of very long templates"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            long_template = "[img]#thumb_url#[/img]" * 1000
            tm.add_template("Long", long_template)

            retrieved = tm.get_template("Long")
            assert len(retrieved) == len(long_template)

    def test_special_characters_in_template(self):
        """Test templates with special characters"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            template_with_special = (
                '<a href="#image_url#" title="View & Download">[img]#thumb_url#[/img]</a>'
            )
            tm.add_template("Special", template_with_special)

            retrieved = tm.get_template("Special")
            assert "&" in retrieved
            assert '"' in retrieved


@pytest.mark.unit
class TestTemplateEdgeCases:
    """Test edge cases and error conditions"""

    def test_duplicate_template_names(self):
        """Test handling of duplicate template names"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            tm.add_template("Duplicate", "#all_images# Version 1")
            tm.add_template("Duplicate", "#all_images# Version 2")

            # Should overwrite or handle appropriately
            result = tm.get_template("Duplicate")
            assert result in ["#all_images# Version 1", "#all_images# Version 2"]

    def test_case_sensitivity(self):
        """Test case sensitivity of template names"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            tm.add_template("MyTemplate", "#all_images# lowercase")
            tm.add_template("MYTEMPLATE", "#all_images# uppercase")

            # Behavior depends on implementation
            templates = tm.get_all_templates()
            assert "MyTemplate" in templates

    def test_duplicate_and_rename_template_helpers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            tm.add_template("Source", "#all_images#")
            tm.duplicate_template("Source", "Copy")
            tm.rename_template("Copy", "Renamed")

            assert tm.get_template("Source") == "#all_images#"
            assert "Copy" not in tm.get_all_templates()
            assert tm.get_template("Renamed") == "#all_images#"


@pytest.mark.integration
class TestTemplateManagerIntegration:
    """Integration tests for template manager"""

    def test_full_template_workflow(self):
        """Test complete workflow: create, use, update, delete"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"

            # Create manager and add template
            tm = TemplateManager(str(templates_file))
            tm.add_template("Workflow", "[url=#image_url#]#thumb_url#[/url]")

            # Retrieve and use template
            result = tm.apply(
                "Workflow",
                {},
                [("http://example.com", "http://example.com/thumb.jpg", "")],
            )
            assert result == "[url=http://example.com]http://example.com/thumb.jpg[/url]"

            # Update template
            tm.add_template("Workflow", "[img]#thumb_url#[/img]")
            updated = tm.get_template("Workflow")
            assert "[img]" in updated

            # Delete template
            tm.delete_template("Workflow")
            assert "Workflow" not in tm.get_all_templates()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "unit"])


@pytest.mark.unit
class TestTemplateManagerAdvanced:
    def test_template_manager_multiple_covers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))

            template = "[img]#cover_url#[/img]\n[img]#cover_url#[/img]\n\n#all_images#"
            mgr.set_template("Custom Covers", template)

            images = [
                ("viewer1", "thumb1", "direct1"),
                ("viewer2", "thumb2", "direct2"),
                ("viewer3", "thumb3", "direct3"),
                ("viewer4", "thumb4", "direct4"),
            ]

            data = {"cover_url": "thumb1", "gallery_name": "Test"}

            result = mgr.apply("Custom Covers", data, images)

            assert "[img]thumb1[/img]" in result
            assert "[img]thumb2[/img]" in result

            assert "[url=viewer3][img]thumb3[/img][/url]" in result
            assert "[url=viewer4][img]thumb4[/img][/url]" in result

            all_images_part = result.split("\n\n")[1] if "\n\n" in result else result
            assert "thumb1" not in all_images_part
            assert "thumb2" not in all_images_part

    def test_user_template_with_four_cover_images_renders_displayable_bbcode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))

            template = (
                "[center][b]#batch_name#[/b]\n"
                "#cover_image#\n"
                "#cover_image#\n"
                "#cover_image#\n"
                "#cover_image#\n\n"
                "#all_images#[/center]"
            )
            mgr.set_template("Four Covers", template)

            images = [
                ("viewer1", "thumb1", "direct1"),
                ("viewer2", "thumb2", "direct2"),
                ("viewer3", "thumb3", "direct3"),
                ("viewer4", "thumb4", "direct4"),
                ("viewer5", "thumb5", "direct5"),
            ]

            result = mgr.apply("Four Covers", {"batch_name": "Batch"}, images)

            for index in range(1, 5):
                assert f"[url=viewer{index}][img]thumb{index}[/img][/url]" in result
            assert "[url=viewer5][img]thumb5[/img][/url]" in result
            all_images_part = result.split("\n\n")[1]
            for index in range(1, 5):
                assert f"thumb{index}" not in all_images_part

    def test_cover_images_placeholder_expands_selected_covers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))
            mgr.set_template("Auto Covers", "#cover_images#\n--\n#all_images#")

            result = mgr.apply(
                "Auto Covers",
                {"cover_count": 2},
                [
                    ("viewer1", "thumb1", "direct1"),
                    ("viewer2", "thumb2", "direct2"),
                    ("viewer3", "thumb3", "direct3"),
                    ("viewer4", "thumb4", "direct4"),
                ],
            )

            cover_part, all_images_part = result.split("\n--\n")
            assert "[url=viewer1][img]thumb1[/img][/url]" in cover_part
            assert "[url=viewer2][img]thumb2[/img][/url]" in cover_part
            assert "thumb1" not in all_images_part
            assert "thumb2" not in all_images_part
            assert "[url=viewer3][img]thumb3[/img][/url]" in all_images_part
            assert "[url=viewer4][img]thumb4[/img][/url]" in all_images_part

    def test_cover_images_placeholder_is_empty_without_selected_covers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))
            mgr.set_template("Auto Covers Empty", "#cover_count#|#cover_images#|#all_images#")

            result = mgr.apply(
                "Auto Covers Empty",
                {"cover_count": 0},
                [("viewer1", "thumb1", "direct1"), ("viewer2", "thumb2", "direct2")],
            )

            assert result.startswith("0||")
            assert "[url=viewer1][img]thumb1[/img][/url]" in result
            assert "[url=viewer2][img]thumb2[/img][/url]" in result

    def test_cover_loop_renders_selected_covers_with_separator(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))
            mgr.set_template(
                "Cover Loop",
                "[for cover separator=blankline]#thumb_url#[/for]\n--\n"
                "[for image separator=space]#thumb_url#[/for]",
            )

            result = mgr.apply(
                "Cover Loop",
                {"cover_count": 2},
                [
                    ("viewer1", "thumb1", "direct1"),
                    ("viewer2", "thumb2", "direct2"),
                    ("viewer3", "thumb3", "direct3"),
                ],
            )

            assert result == "thumb1\n\nthumb2\n--\nthumb3"

    def test_vipergirls_template_resolves_to_bbcode_for_covers_and_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))

            result = mgr.apply(
                "ViperGirls Gallery Post",
                {"batch_name": "Batch", "cover_count": 2},
                [
                    ("viewer1", "thumb1", "direct1"),
                    ("viewer2", "thumb2", "direct2"),
                    ("viewer3", "thumb3", "direct3"),
                ],
            )

            assert mgr.resolve_output_format("ViperGirls Gallery Post") == "BBCode"
            assert "[url=viewer1][img]thumb1[/img][/url]" in result
            assert "[url=viewer2][img]thumb2[/img][/url]" in result
            assert "[url=viewer3][img]thumb3[/img][/url]" in result
            assert "<a href=" not in result
            assert '<img src="' not in result

    def test_process_conditionals(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))
            template = "[if gallery_link][url=#gallery_link#]Gallery[/url][/if]#all_images#"
            mgr.set_template("Cond Test", template)

            images = []

            result_no_link = mgr.apply("Cond Test", {"gallery_link": ""}, images)
            assert "Gallery" not in result_no_link

            result_with_link = mgr.apply(
                "Cond Test", {"gallery_link": "http://example.com"}, images
            )
            assert "[url=http://example.com]Gallery[/url]" in result_with_link

    def test_conditionals_support_forum_safe_placeholder_variants(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))
            template = (
                "[IF #gallery_link#][url=#gallery_link#]Gallery[/url][ELSE]No gallery[/IF]\n"
                "[if #gallery_id#='PREV_123']Preview[/if]\n"
                "#all_images#"
            )
            mgr.set_template("Forum Safe Conditionals", template)

            result = mgr.apply(
                "Forum Safe Conditionals",
                {"gallery_link": "http://example.com", "gallery_id": "PREV_123"},
                [],
            )

            assert "[url=http://example.com]Gallery[/url]" in result
            assert "Preview" in result
            assert "[IF" not in result
            assert "[/IF" not in result
            assert "[ELSE]" not in result

    def test_nested_conditionals_render_reliably(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))
            template = (
                "[if gallery_link]"
                "Gallery [if thread_id]Thread #thread_id#[else]No thread[/if]"
                "[else]No gallery[/if] #all_images#"
            )
            mgr.set_template("Nested Conditionals", template)

            with_thread = mgr.apply(
                "Nested Conditionals",
                {"gallery_link": "https://gallery", "thread_id": "123"},
                [],
            )
            without_thread = mgr.apply(
                "Nested Conditionals",
                {"gallery_link": "https://gallery", "thread_id": ""},
                [],
            )
            without_gallery = mgr.apply("Nested Conditionals", {"gallery_link": ""}, [])

            assert "Gallery Thread 123" in with_thread
            assert "No thread" in without_thread
            assert "No gallery" in without_gallery
            assert "[if" not in with_thread.lower()

    def test_image_loop_renders_custom_body_with_blank_line_separator(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))
            mgr.set_template(
                "Loop",
                "[for image separator=blankline]#image_url#|#thumb_url#|#direct_url#[/for]",
            )

            result = mgr.apply(
                "Loop",
                {},
                [("viewer1", "thumb1", "direct1"), ("viewer2", "thumb2", "direct2")],
            )

            assert result == "viewer1|thumb1|direct1\n\nviewer2|thumb2|direct2"

    def test_image_loop_supports_nested_conditionals_and_space_separator(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))
            mgr.set_template(
                "Loop Conditionals",
                "[for image separator=space][if direct_url]#direct_url#[else]missing[/if][/for]",
            )

            result = mgr.apply(
                "Loop Conditionals",
                {},
                [("viewer1", "thumb1", "direct1"), ("viewer2", "thumb2", "")],
            )

            assert result == "direct1 missing"

    def test_image_loop_accepts_custom_separator(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))
            mgr.set_template(
                "Loop Custom Separator",
                '[for image separator=", "]#image_url#[/for]',
            )

            result = mgr.apply(
                "Loop Custom Separator",
                {},
                [("viewer1", "thumb1", "direct1"), ("viewer2", "thumb2", "direct2")],
            )

            assert result == "viewer1, viewer2"

    def test_template_validation_reports_unclosed_image_loop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))

            errors = mgr.validate_template("[for image]#image_url#")

            assert "Template has an unclosed [for image] block." in errors

    def test_template_validation_reports_unclosed_cover_loop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))

            errors = mgr.validate_template("[for cover]#thumb_url#")

            assert "Template has an unclosed [for cover] block." in errors

    def test_template_validation_reports_unmatched_image_loop_close(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))

            errors = mgr.validate_template("#all_images#[/for]")

            assert (
                "Template has a closing [/for] without a matching [for image] or [for cover]."
                in errors
            )

    def test_metadata_placeholders_render_from_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))
            mgr.set_template(
                "Metadata",
                (
                    "#batch_name#|#service#|#upload_date#|#image_count#|"
                    "#folder_size#|#thread_name#|#thread_id#|#all_images#"
                ),
            )

            result = mgr.apply(
                "Metadata",
                {
                    "batch_name": "Batch Alpha",
                    "service": "pixhost.cc",
                    "upload_date": "2026-06-21",
                    "image_count": 2,
                    "folder_size": "1.34 GB",
                    "thread_name": "Thread Alpha",
                    "thread_id": "98765",
                },
                [("viewer1", "thumb1", "direct1"), ("viewer2", "thumb2", "direct2")],
            )

            assert result.startswith(
                "Batch Alpha|pixhost.cc|2026-06-21|2|1.34 GB|Thread Alpha|98765|"
            )
            assert "[url=viewer1][img]thumb1[/img][/url]" in result

    def test_folder_size_placeholder_is_allowed_and_renders_blank_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))
            mgr.set_template("Folder Size", "Size: #folder_size#\n#all_images#")

            result = mgr.apply(
                "Folder Size",
                {},
                [("viewer1", "thumb1", "direct1")],
            )

            assert result.startswith("Size: \n")
            assert "#folder_size#" not in result

    def test_unresolved_conditionals_do_not_reach_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))
            template = "Before [if gallery_link]Gallery[/if] [if broken]After"
            mgr.set_template("No Raw Conditionals", template, validate=False)

            result = mgr.apply("No Raw Conditionals", {"gallery_link": ""}, [])

            assert "[if" not in result.lower()
            assert "[/if" not in result.lower()
            assert "[else]" not in result.lower()

    def test_conditional_cleanup_does_not_strip_similar_bbcode_tags(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))
            mgr.set_template("Similar Tags", "[iframe]https://example.com[/iframe]", validate=False)

            result = mgr.apply("Similar Tags", {}, [])

            assert "[iframe]https://example.com[/iframe]" in result

    def test_preview_html_contains_rendered_and_raw_output(self):
        preview = TemplateEditor.build_preview_html(
            "[url=https://example.com][img]thumb.jpg[/img][/url]",
            "BBCode",
            "200",
        )

        assert "Rendered Preview" in preview
        assert "Raw Generated Output" in preview
        assert '<a href="https://example.com">' in preview
        assert "[url=https://example.com]" in preview

    def test_editor_toolbar_uses_resolved_output_format(self):
        class FakeVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))
            editor = TemplateEditor.__new__(TemplateEditor)
            editor.mgr = mgr
            editor.fmt = FakeVar("ViperGirls Gallery Post")
            editor.current_template_name = "ViperGirls Gallery Post"
            editor.txt = _FakeText(mgr.get_template("ViperGirls Gallery Post"))

            assert TemplateEditor.get_tags(editor, "Bold") == ("[b]", "[/b]")
            assert TemplateEditor.get_tags(editor, "Color", "#ff0000") == (
                "[color=#ff0000]",
                "[/color]",
            )

            editor.fmt = FakeVar("HTML")
            editor.current_template_name = "HTML"
            editor.txt = _FakeText(mgr.get_template("HTML"))
            assert TemplateEditor.get_tags(editor, "Bold") == ("<b>", "</b>")

    def test_template_warnings_flag_html_in_bbcode_forum_templates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))

            warnings = mgr.template_warnings(
                "ViperGirls Gallery Post",
                "<span>Bad for forum</span>\n#all_images#",
            )

            assert warnings
            assert "treated as BBCode" in warnings[0]
            assert mgr.template_warnings("HTML", "<span>Fine</span>\n#all_images#") == []

    def test_placeholder_categories_cover_all_supported_hash_placeholders(self):
        categorized = {
            match.group(1)
            for value in TemplateEditor.supported_placeholder_values()
            for match in TemplateManager.HASH_PLACEHOLDER_PATTERN.finditer(value)
        }
        image_labels = {label for label, _value in TemplateEditor.PLACEHOLDER_CATEGORIES["Images"]}
        cover_labels = [
            label
            for label, _value in TemplateEditor.PLACEHOLDER_CATEGORIES["Images"]
            if "Cover" in label
        ]

        assert categorized <= TemplateManager.ALLOWED_PLACEHOLDERS
        assert "cover_image" in categorized
        assert "cover_images" in categorized
        assert "cover_count" in categorized
        assert "folder_size" in categorized
        assert "cover_url" not in categorized
        assert "Cover{s}" in image_labels
        assert "Folder Size" in image_labels
        assert ("Folder Size", "#folder_size#") in TemplateEditor.PLACEHOLDER_CATEGORIES["Images"]
        assert ("Folder Size", "#folder_size#") in TemplateEditor.PLACEHOLDER_CATEGORIES["Batch"]
        assert cover_labels == ["All Covers", "Cover{s}", "Cover Count", "Cover Loop"]
        assert "#cover_image#" in TemplateEditor.supported_placeholder_values()

    def test_direct_image_placeholders_resolve_when_used_in_template_body(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            mgr = TemplateManager(str(templates_file))
            mgr.set_template(
                "Single Image",
                "#image_url#|#thumb_url#|#direct_url#",
            )

            result = mgr.apply(
                "Single Image",
                {},
                [("viewer1", "thumb1", "direct1"), ("viewer2", "thumb2", "direct2")],
            )

            assert result == "viewer1|thumb1|direct1"

    def test_preview_output_uses_current_editor_template_and_preview_context(
        self, tmp_path, monkeypatch
    ):
        class FakeText:
            def __init__(self, content):
                self.content = content

            def get(self, *_args):
                return self.content

        class FakeVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

        errors = []
        warnings = []
        monkeypatch.setattr(
            template_manager.messagebox,
            "showerror",
            lambda title, message: errors.append((title, message)),
        )
        monkeypatch.setattr(
            template_manager.messagebox,
            "showwarning",
            lambda title, message: warnings.append((title, message)),
        )

        image_one = tmp_path / "first image.jpg"
        image_two = tmp_path / "second.jpg"
        image_one.write_bytes(b"one")
        image_two.write_bytes(b"two")
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        editor = TemplateEditor.__new__(TemplateEditor)
        editor.mgr = mgr
        editor.txt = FakeText(
            (
                "#batch_name#|#service#|#thread_name#|#thread_id#|#folder_size#\n"
                "[for image separator=space]#image_url#[/for]"
            )
        )
        editor.fmt = FakeVar("Preview Custom")
        editor.current_template_name = "Preview Custom"
        editor.data_callback = lambda: (
            [str(image_one), str(image_two)],
            "Preview Batch",
            "180",
        )

        preview = TemplateEditor._build_preview_output(editor)

        assert errors == []
        assert warnings == []
        assert preview is not None
        raw, fmt, size = preview
        assert fmt == "BBCode"
        assert size == "180"
        assert raw.startswith("Preview Batch|preview|Preview Thread|PREV_THREAD|6 B")
        assert "first%20image.jpg" in raw
        assert "second.jpg" in raw

    def test_preview_output_accepts_cover_count_from_callback(self, tmp_path, monkeypatch):
        class FakeText:
            def __init__(self, content):
                self.content = content

            def get(self, *_args):
                return self.content

        class FakeVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

        monkeypatch.setattr(template_manager.messagebox, "showerror", lambda *_args: None)
        monkeypatch.setattr(template_manager.messagebox, "showwarning", lambda *_args: None)

        image_one = tmp_path / "cover.jpg"
        image_two = tmp_path / "standard.jpg"
        image_one.write_bytes(b"cover")
        image_two.write_bytes(b"standard")
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        editor = TemplateEditor.__new__(TemplateEditor)
        editor.mgr = mgr
        editor.txt = FakeText("#cover_images#\n--\n#all_images#")
        editor.fmt = FakeVar("Preview Custom")
        editor.current_template_name = "Preview Custom"
        editor.data_callback = lambda: (
            [str(image_one), str(image_two)],
            "Preview Batch",
            "180",
            1,
        )

        preview = TemplateEditor._build_preview_output(editor)

        assert preview is not None
        raw, _fmt, _size = preview
        cover_part, all_images_part = raw.split("\n--\n")
        assert "cover.jpg" in cover_part
        assert "standard.jpg" in all_images_part
        assert "cover.jpg" not in all_images_part

    def test_preview_without_data_callback_reports_empty_state(self, monkeypatch):
        warnings = []
        monkeypatch.setattr(
            template_manager.messagebox,
            "showwarning",
            lambda title, message: warnings.append((title, message)),
        )
        editor = TemplateEditor.__new__(TemplateEditor)
        editor.data_callback = None

        assert TemplateEditor._build_preview_output(editor) is None
        assert warnings
        assert "Preview needs files" in warnings[0][1]


THREE_IMAGES = [
    ("viewer1", "thumb1", "direct1"),
    ("viewer2", "thumb2", "direct2"),
    ("viewer3", "thumb3", "direct3"),
]


@pytest.mark.unit
class TestTemplateLoopLayout:
    def test_line_breaks_next_to_loop_tags_are_layout_not_content(self, tmp_path):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        snippets = dict(TemplateEditor.PLACEHOLDER_CATEGORIES["Images"])
        block = "[url=viewer{0}][img]thumb{0}[/img][/url]"
        blocks = [block.format(index) for index in range(1, 4)]

        mgr.templates["Newline"] = snippets["Loop: Newline"]
        mgr.templates["Blank"] = snippets["Loop: Blank Line"]
        mgr.templates["Space"] = (
            "[for image separator=space]\n[url=#image_url#][img]#thumb_url#[/img][/url]\n[/for]"
        )

        assert mgr.apply("Newline", {}, THREE_IMAGES) == "\n".join(blocks)
        assert mgr.apply("Blank", {}, THREE_IMAGES) == "\n\n".join(blocks)
        assert mgr.apply("Space", {}, THREE_IMAGES) == " ".join(blocks)

    def test_only_one_layout_line_break_is_removed_on_each_side(self, tmp_path):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        mgr.templates["Padded"] = "[for image separator=none]\n\n#thumb_url#\n\n[/for]"
        mgr.templates["Windows"] = "[for image separator=comma]\r\n#thumb_url#\r\n[/for]"

        assert mgr.apply("Padded", {}, THREE_IMAGES[:2]) == "\nthumb1\n\nthumb2\n"
        assert mgr.apply("Windows", {}, THREE_IMAGES[:2]) == "thumb1, thumb2"

    def test_documented_covers_and_grid_example_renders_rows(self, tmp_path):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        mgr.set_template(
            "Example C",
            "[center]\n[b]Covers:[/b]\n[for cover separator=space]\n"
            "[url=#image_url#][img]#thumb_url#[/img][/url]\n[/for]\n\n"
            "[b]Gallery Set:[/b]\n[for image separator=space]\n"
            "[url=#image_url#][img]#thumb_url#[/img][/url]\n[/for]\n[/center]",
        )
        images = THREE_IMAGES + [("viewer4", "thumb4", "direct4")]

        result = mgr.apply("Example C", {"cover_count": 2}, images)

        assert result == (
            "[center]\n[b]Covers:[/b]\n"
            "[url=viewer1][img]thumb1[/img][/url] [url=viewer2][img]thumb2[/img][/url]\n\n"
            "[b]Gallery Set:[/b]\n"
            "[url=viewer3][img]thumb3[/img][/url] [url=viewer4][img]thumb4[/img][/url]\n"
            "[/center]"
        )

    def test_quoted_separator_may_contain_closing_bracket(self, tmp_path):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        template = '[for image separator="[hr]"][img]#thumb_url#[/img][/for]'

        assert mgr.validate_template(template) == []
        mgr.set_template("Rule Between", template)

        assert mgr.apply("Rule Between", {}, THREE_IMAGES[:2]) == (
            "[img]thumb1[/img][hr][img]thumb2[/img]"
        )

    def test_quoted_condition_value_may_contain_closing_bracket(self, tmp_path):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        mgr.set_template("Bracket Name", '[if gallery_name="[HD] Set"]HD [/if]#all_images#')

        result = mgr.apply("Bracket Name", {"gallery_name": "[HD] Set"}, [])

        assert result == "HD "

    def test_unquoted_values_still_end_at_the_first_closing_bracket(self, tmp_path):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        mgr.set_template("Apostrophe", "[if gallery_name=it's]Match[/if] #all_images# it's")

        result = mgr.apply("Apostrophe", {"gallery_name": "it's"}, [])

        assert result == "Match  it's"


FOUR_IMAGES = THREE_IMAGES + [("viewer4", "thumb4", "direct4")]


def _thumb_block(index):
    return f"[url=viewer{index}][img]thumb{index}[/img][/url]"


@pytest.mark.unit
class TestTemplateConditionsMatchRender:
    def test_conditional_cover_image_keeps_every_image(self, tmp_path):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        mgr.set_template("Optional Cover", "[if cover_image]#cover_image#\n[/if]#all_images#")

        for cover_count in (0, 1):
            result = mgr.apply("Optional Cover", {"cover_count": cover_count}, FOUR_IMAGES)

            assert result == _thumb_block(1) + "\n" + " ".join(
                _thumb_block(index) for index in range(2, 5)
            )

    def test_conditions_on_image_lists_never_drop_an_image(self, tmp_path):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        mgr.set_template("Cover If Rest", "[if all_images]#cover_image#[/if]")
        mgr.set_template("Optional Covers", "[if cover_images]#cover_images#\n[/if]#all_images#")

        assert mgr.apply("Cover If Rest", {}, THREE_IMAGES[:1]) == _thumb_block(1)
        assert mgr.apply("Optional Covers", {"cover_count": 0}, THREE_IMAGES) == " ".join(
            _thumb_block(index) for index in range(1, 4)
        )
        assert mgr.apply("Optional Covers", {"cover_count": 2}, THREE_IMAGES) == (
            f"{_thumb_block(1)} {_thumb_block(2)}\n{_thumb_block(3)}"
        )

    def test_numeric_zero_is_false_in_conditions(self, tmp_path):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        mgr.set_template("Count", "[if cover_count]Covers: #cover_images#\n[/if]#all_images#")

        without_covers = mgr.apply("Count", {"cover_count": 0}, FOUR_IMAGES)
        with_covers = mgr.apply("Count", {"cover_count": 2}, FOUR_IMAGES)

        assert without_covers == " ".join(_thumb_block(index) for index in range(1, 5))
        assert with_covers == (
            f"Covers: {_thumb_block(1)} {_thumb_block(2)}\n{_thumb_block(3)} {_thumb_block(4)}"
        )
        assert mgr.process_conditionals(
            "[if image_count]Some[else]None[/if]", {"image_count": 0}
        ) == ("None")
        assert mgr.process_conditionals("[if thread_id]T[else]None[/if]", {"thread_id": "0"}) == (
            "None"
        )
        assert mgr.process_conditionals("[if image_count]Some[/if]", {"image_count": 3}) == "Some"
        assert mgr.process_conditionals("[if cover_count=0]Zero[/if]", {"cover_count": 0}) == (
            "Zero"
        )

    def test_cover_count_condition_sees_the_rendered_cover_count(self, tmp_path):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        mgr.set_template(
            "Two Slots",
            "[if cover_count=2]Two covers: [/if]#cover_image# #cover_image#\n"
            "#cover_count# #all_images#",
        )

        result = mgr.apply("Two Slots", {"cover_count": 0}, THREE_IMAGES)

        assert result == f"Two covers: {_thumb_block(1)} {_thumb_block(2)}\n2 {_thumb_block(3)}"

    def test_brace_placeholders_are_rejected_with_a_hint(self, tmp_path):
        mgr = TemplateManager(str(tmp_path / "templates.json"))

        errors = mgr.validate_template("[url={viewer}][img]{thumb}[/img][/url]")
        direct_errors = mgr.validate_template("#all_images# [img]{direct}[/img]")

        assert any(
            "{viewer}" in error and "{thumb}" in error and "#image_url#" in error
            for error in errors
        )
        assert any("image output placeholder" in error for error in errors)
        assert len(direct_errors) == 1
        assert "{direct}" in direct_errors[0] and "#direct_url#" in direct_errors[0]
        with pytest.raises(TemplateValidationError):
            mgr.set_template("Legacy", "[url={viewer}][img]{thumb}[/img][/url]")


class _FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _FakeText:
    def __init__(self, content=""):
        self.content = content

    def get(self, *_args):
        return self.content + "\n"

    def delete(self, *_args):
        self.content = ""

    def insert(self, _index, value):
        self.content = value + self.content


class _FakeCombo:
    def __init__(self):
        self.values = []
        self.value = ""

    def configure(self, **kwargs):
        self.values = kwargs.get("values", self.values)

    def set(self, value):
        self.value = value


IMAGE_BLOCKS = {
    "BBCode": "[url=viewer1][img]thumb1[/img][/url]",
    "Markdown": "[![Image](thumb1)](viewer1)",
    "HTML": '<a href="viewer1"><img src="thumb1"></a>',
}


@pytest.mark.unit
class TestCustomTemplateOutputFormat:
    @pytest.mark.parametrize(
        "source, expected",
        [
            ("HTML", "HTML"),
            ("HTML Page Wrapper", "HTML"),
            ("Markdown", "Markdown"),
            ("Reddit Markdown", "Markdown"),
            ("BBCode", "BBCode"),
            ("Basic List", "BBCode"),
            ("ViperGirls Gallery Post", "BBCode"),
        ],
    )
    def test_duplicate_of_a_builtin_keeps_its_output_format(self, tmp_path, source, expected):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        mgr.duplicate_template(source, "My copy")

        result = mgr.apply("My copy", {"gallery_link": "https://gallery"}, THREE_IMAGES[:1])

        assert mgr.resolve_output_format("My copy") == expected
        assert IMAGE_BLOCKS[expected] in result
        for other_format, block in IMAGE_BLOCKS.items():
            if other_format != expected:
                assert block not in result

    @pytest.mark.parametrize(
        "name, content, expected",
        [
            ("My Markdown", "# #batch_name#\n\n#all_images#", "Markdown"),
            ("Reddit post", "**#batch_name#**\n\n#all_images#", "Markdown"),
            ("Blog", "<p>#batch_name#</p>\n#all_images#", "HTML"),
            ("Forum post", "[b]#batch_name#[/b]\n#all_images#", "BBCode"),
            ("Markdown for forums", "[b]#batch_name#[/b]\n#all_images#", "BBCode"),
            ("my markdown list", "#all_images#", "Markdown"),
            ("Gallery HTML", "#batch_name#\n#all_images#", "HTML"),
            ("Plain list", "#batch_name#\n#all_images#", "BBCode"),
        ],
    )
    def test_custom_template_format_follows_content_then_name(
        self, tmp_path, name, content, expected
    ):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        mgr.set_template(name, content)

        assert mgr.resolve_output_format(name) == expected
        assert mgr.resolve_output_format(name, content) == expected
        assert IMAGE_BLOCKS[expected] in mgr.apply(name, {}, THREE_IMAGES[:1])

    def test_preview_and_toolbar_use_the_detected_format(self, tmp_path, monkeypatch):
        monkeypatch.setattr(template_manager.messagebox, "showerror", lambda *_args: None)
        monkeypatch.setattr(template_manager.messagebox, "showwarning", lambda *_args: None)
        image = tmp_path / "a.jpg"
        image.write_bytes(b"a")
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        mgr.duplicate_template("HTML", "Web copy")
        editor = TemplateEditor.__new__(TemplateEditor)
        editor.mgr = mgr
        editor.txt = _FakeText(mgr.get_template("Web copy"))
        editor.fmt = _FakeVar("Web copy")
        editor.current_template_name = "Web copy"
        editor.data_callback = lambda: ([str(image)], "Batch", "180", 0)

        raw, output_format, size = TemplateEditor._build_preview_output(editor)
        page = TemplateEditor.build_preview_html(raw, output_format, size)

        assert output_format == "HTML"
        assert '<a href="file:///' in raw
        assert "[url=" not in raw
        assert '<a href="http://localhost/preview">Click here for Gallery</a>' in page
        assert TemplateEditor.get_tags(editor, "Bold") == ("<b>", "</b>")

        editor.txt = _FakeText("[Gallery](#gallery_link#)\n#all_images#")
        assert TemplateEditor.get_tags(editor, "Bold") == ("**", "**")
        _raw, output_format, _size = TemplateEditor._build_preview_output(editor)
        assert output_format == "Markdown"


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@pytest.mark.unit
class TestTemplateFileRobustness:
    def test_saves_from_two_windows_merge_instead_of_overwriting(self, tmp_path):
        path = tmp_path / "templates.json"
        first = TemplateManager(str(path))
        second = TemplateManager(str(path))

        first.set_template("From A", "A #all_images#")
        second.set_template("From B", "B #all_images#")
        second.set_template("BBCode", "edited #all_images#")

        on_disk = _read_json(path)
        assert on_disk["From A"] == "A #all_images#"
        assert on_disk["From B"] == "B #all_images#"
        assert on_disk["BBCode"] == "edited #all_images#"
        assert second.get_template("From A") == "A #all_images#"
        assert TemplateManager(str(path)).get_template("From A") == "A #all_images#"

    def test_merge_keeps_other_windows_deletions_renames_and_edits(self, tmp_path):
        path = tmp_path / "templates.json"
        first = TemplateManager(str(path))
        first.set_template("Shared", "shared #all_images#")
        first.set_template("Old Name", "old #all_images#")
        first.set_template("Edited", "v1 #all_images#")
        second = TemplateManager(str(path))

        first.delete_template("Shared")
        first.rename_template("Old Name", "New Name")
        first.set_template("Edited", "v2 #all_images#")
        second.set_template("Other", "other #all_images#")

        on_disk = _read_json(path)
        assert "Shared" not in on_disk
        assert "Old Name" not in on_disk
        assert on_disk["New Name"] == "old #all_images#"
        assert on_disk["Edited"] == "v2 #all_images#"
        assert on_disk["Other"] == "other #all_images#"

    def test_restore_defaults_replaces_the_whole_file(self, tmp_path):
        path = tmp_path / "templates.json"
        first = TemplateManager(str(path))
        second = TemplateManager(str(path))
        first.set_template("Mine", "mine #all_images#")

        second.restore_defaults()

        assert _read_json(path) == second.defaults
        assert "Mine" not in second.get_all_templates()

    def test_templates_file_with_utf8_bom_loads(self, tmp_path):
        path = tmp_path / "templates.json"
        path.write_text(json.dumps({"Mine": "X #all_images#"}), encoding="utf-8-sig")

        tm = TemplateManager(str(path))

        assert tm.get_recovery_issue() is None
        assert tm.get_template("Mine") == "X #all_images#"
        assert not list(tmp_path.glob("*.bak"))
        assert _read_json(path)["Mine"] == "X #all_images#"

    def test_import_accepts_utf8_bom(self, tmp_path):
        import_path = tmp_path / "export.json"
        import_path.write_text(
            json.dumps({"version": 1, "templates": {"Mine": "X #all_images#"}}),
            encoding="utf-8-sig",
        )
        tm = TemplateManager(str(tmp_path / "templates.json"))

        assert tm.import_templates_file(str(import_path)) == (1, 0, [])
        assert tm.get_template("Mine") == "X #all_images#"
        assert tm.import_name_conflicts(str(import_path)) == ["Mine"]

    def test_non_text_entries_are_dropped_and_reported(self, tmp_path):
        path = tmp_path / "templates.json"
        original = {"BBCode": None, "Mine": 5, "L": ["#all_images#"], "Good": "G #all_images#"}
        path.write_text(json.dumps(original), encoding="utf-8")

        tm = TemplateManager(str(path))

        issue = tm.get_recovery_issue()
        assert issue is not None
        for name in ("BBCode", "Mine", "L"):
            assert name in issue["error"]
        assert "Good" not in issue["error"]
        assert _read_json(issue["backup_path"]) == original
        assert tm.get_template("BBCode") == tm.defaults["BBCode"]
        assert "Mine" not in tm.get_all_templates()
        assert "L" not in tm.get_all_templates()
        assert tm.get_template("Good") == "G #all_images#"
        assert IMAGE_BLOCKS["BBCode"] in tm.apply("BBCode", {}, THREE_IMAGES[:1])
        assert all(isinstance(value, str) for value in _read_json(path).values())
        assert TemplateManager(str(path)).get_recovery_issue() is None

    @pytest.mark.parametrize(
        "payload",
        [
            {"version": 1, "templates": []},
            {"templates": "#all_images#"},
            {"version": 1, "exported_at": "x", "templates": None},
            {"BBCode": "new #all_images#", "version": "#all_images#"},
            [1],
            "#all_images#",
        ],
    )
    def test_import_rejects_files_that_are_not_template_exports(self, tmp_path, payload):
        import_path = tmp_path / "import.json"
        import_path.write_text(json.dumps(payload), encoding="utf-8")
        tm = TemplateManager(str(tmp_path / "templates.json"))
        before = tm.get_all_templates()

        with pytest.raises(TemplateValidationError):
            tm.import_templates_file(str(import_path))

        assert tm.get_all_templates() == before

    def test_import_skips_entries_whose_content_is_not_text(self, tmp_path):
        import_path = tmp_path / "import.json"
        plain_path = tmp_path / "plain.json"
        import_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "templates": {
                        "A": ["#all_images#"],
                        "B": {"content": "#all_images#"},
                        "C": None,
                        "D": "#all_images#",
                    },
                }
            ),
            encoding="utf-8",
        )
        plain_path.write_text(json.dumps({"E": {"content": "#all_images#"}}), encoding="utf-8")
        tm = TemplateManager(str(tmp_path / "templates.json"))

        imported, skipped, errors = tm.import_templates_file(str(import_path))
        plain_result = tm.import_templates_file(str(plain_path))

        assert (imported, skipped) == (1, 3)
        for name in ("A", "B", "C"):
            assert any(error.startswith(f"{name}:") for error in errors)
            assert name not in tm.get_all_templates()
        assert tm.get_template("D") == "#all_images#"
        assert plain_result[:2] == (0, 1)
        assert "E" not in tm.get_all_templates()

    def test_import_reports_names_that_collide_after_trimming(self, tmp_path):
        import_path = tmp_path / "import.json"
        import_path.write_text(
            json.dumps({"templates": {"A": "first #all_images#", " A ": "second #all_images#"}}),
            encoding="utf-8",
        )
        tm = TemplateManager(str(tmp_path / "templates.json"))

        imported, skipped, errors = tm.import_templates_file(str(import_path))

        assert (imported, skipped) == (1, 1)
        assert len(errors) == 1 and "A" in errors[0]
        assert tm.get_template("A") == "first #all_images#"


def _make_editor(mgr, name="BBCode", category=None):
    """A TemplateEditor wired to fake widgets, in the state __init__ leaves it in."""
    editor = TemplateEditor.__new__(TemplateEditor)
    editor.mgr = mgr
    editor.data_callback = None
    editor.update_callback = None
    editor.initial_mode = name
    editor.current_template_name = ""
    editor.loaded_content = ""
    editor.last_preview_output = ""
    editor.fmt = _FakeVar(name)
    editor.saved_tmpl_var = _FakeVar(name)
    editor.template_search_var = _FakeVar("")
    editor.template_category_var = _FakeVar(category or mgr.CATEGORY_ALL)
    editor.cb_fmt = _FakeCombo()
    editor.cb_saved = _FakeCombo()
    editor.cb_category = _FakeCombo()
    editor.template_empty_label = _FakeCombo()
    editor.txt = _FakeText()
    editor._load_template_content(name)
    return editor


@pytest.mark.unit
class TestBuiltinTemplatesStay:
    def test_builtin_templates_cannot_be_deleted_or_renamed(self, tmp_path):
        path = tmp_path / "templates.json"
        tm = TemplateManager(str(path))

        with pytest.raises(TemplateValidationError) as deleted:
            tm.delete_template("Reddit Markdown")
        with pytest.raises(TemplateValidationError) as renamed:
            tm.rename_template("BBCode", "Mine")

        assert "built-in" in str(deleted.value)
        assert "Duplicate" in str(renamed.value)
        assert "Reddit Markdown" in _read_json(path)
        assert "BBCode" in tm.get_all_templates()
        assert "Mine" not in tm.get_all_templates()
        tm.rename_template("BBCode", "BBCode", "edited #all_images#")
        assert tm.get_template("BBCode") == "edited #all_images#"

    def test_custom_templates_can_still_be_deleted_and_renamed(self, tmp_path):
        path = tmp_path / "templates.json"
        tm = TemplateManager(str(path))
        tm.set_template("Mine", "#all_images#")

        tm.rename_template("Mine", "Yours")
        tm.delete_template("Yours")

        restarted = TemplateManager(str(path)).get_all_templates()
        assert "Mine" not in restarted
        assert "Yours" not in restarted

    def test_editor_delete_offers_to_reset_an_edited_builtin(self, tmp_path, monkeypatch):
        path = tmp_path / "templates.json"
        mgr = TemplateManager(str(path))
        mgr.set_template("BBCode", "edited #all_images#")
        editor = _make_editor(mgr, "BBCode")
        questions = []
        monkeypatch.setattr(
            template_manager.messagebox,
            "askyesno",
            lambda _title, message: questions.append(message) or True,
        )
        monkeypatch.setattr(template_manager.messagebox, "showinfo", lambda *_args: None)

        editor.delete_current()

        assert len(questions) == 1 and "built-in" in questions[0]
        assert mgr.get_template("BBCode") == mgr.defaults["BBCode"]
        assert _read_json(path)["BBCode"] == mgr.defaults["BBCode"]
        assert editor.current_template_name == "BBCode"
        assert editor._editor_content() == mgr.defaults["BBCode"]

    def test_editor_delete_or_rename_of_an_unchanged_builtin_only_explains(
        self, tmp_path, monkeypatch
    ):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        editor = _make_editor(mgr, "Reddit Markdown")
        infos = []

        def unexpected(*_args, **_kwargs):
            raise AssertionError("should not ask")

        monkeypatch.setattr(template_manager.messagebox, "askyesno", unexpected)
        monkeypatch.setattr(template_manager.ctk, "CTkInputDialog", unexpected)
        monkeypatch.setattr(
            template_manager.messagebox,
            "showinfo",
            lambda _title, message: infos.append(message),
        )

        editor.delete_current()
        editor.rename_current()

        assert len(infos) == 2
        assert all("built-in" in message and "Duplicate" in message for message in infos)
        assert mgr.get_template("Reddit Markdown") == mgr.defaults["Reddit Markdown"]


class _FakeInputDialog:
    answer = ""

    def __init__(self, **_kwargs):
        pass

    def get_input(self):
        return self.answer


@pytest.mark.unit
class TestTemplateEditorSavesTheEditedTemplate:
    def _two_templates(self, tmp_path):
        path = tmp_path / "templates.json"
        mgr = TemplateManager(str(path))
        mgr.set_template("Mine A", "[b]A original[/b] #all_images#")
        mgr.set_template("Mine B", "[i]B original[/i] #all_images#")
        return path, mgr

    def test_switch_prompt_saves_the_previous_template(self, tmp_path, monkeypatch):
        path, mgr = self._two_templates(tmp_path)
        editor = _make_editor(mgr, "Mine A")
        monkeypatch.setattr(template_manager.messagebox, "askyesnocancel", lambda *_args: True)
        monkeypatch.setattr(template_manager.messagebox, "showinfo", lambda *_args: None)
        editor.txt.content = "[b]A EDITED[/b] #all_images#"

        # CTkComboBox's dropdown and the mouse-wheel handler write the bound
        # variable before they call the command.
        editor.fmt.set("Mine B")
        editor._handle_template_change("Mine B")

        on_disk = _read_json(path)
        assert on_disk["Mine A"] == "[b]A EDITED[/b] #all_images#"
        assert on_disk["Mine B"] == "[i]B original[/i] #all_images#"
        assert editor.current_template_name == "Mine B"
        assert editor.fmt.get() == "Mine B"
        assert editor._editor_content() == "[i]B original[/i] #all_images#"

    def test_cancelled_switch_keeps_editing_and_saving_the_same_template(
        self, tmp_path, monkeypatch
    ):
        path, mgr = self._two_templates(tmp_path)
        editor = _make_editor(mgr, "Mine A")
        monkeypatch.setattr(template_manager.messagebox, "askyesnocancel", lambda *_args: None)
        monkeypatch.setattr(template_manager.messagebox, "showinfo", lambda *_args: None)
        editor.txt.content = "[b]A EDITED[/b] #all_images#"

        editor.fmt.set("Mine B")
        editor._handle_template_change("Mine B")
        assert editor.current_template_name == "Mine A"
        assert editor.fmt.get() == "Mine A"
        assert _read_json(path)["Mine A"] == "[b]A original[/b] #all_images#"

        editor.fmt.set("Mine B")  # a stale selection must not redirect the save
        assert editor.save() is True

        on_disk = _read_json(path)
        assert on_disk["Mine A"] == "[b]A EDITED[/b] #all_images#"
        assert on_disk["Mine B"] == "[i]B original[/i] #all_images#"

    def test_duplicate_under_a_category_filter_edits_and_saves_the_copy(
        self, tmp_path, monkeypatch
    ):
        path = tmp_path / "templates.json"
        mgr = TemplateManager(str(path))
        editor = _make_editor(mgr, "BBCode")
        infos = []
        monkeypatch.setattr(template_manager.messagebox, "askyesno", lambda *_args: True)
        monkeypatch.setattr(
            template_manager.messagebox,
            "showinfo",
            lambda _title, message: infos.append(message),
        )
        _FakeInputDialog.answer = "My Post"
        monkeypatch.setattr(template_manager.ctk, "CTkInputDialog", _FakeInputDialog)

        editor.template_category_var.set("ViperGirls")
        editor.fmt.set("ViperGirls Gallery Post")
        editor._handle_template_change("ViperGirls Gallery Post")
        original = mgr.get_template("ViperGirls Gallery Post")
        editor.duplicate_current()

        assert editor.current_template_name == "My Post"
        assert editor.fmt.get() == "My Post"
        assert "My Post" in editor.cb_fmt.values

        editor.txt.content = "[b]MY EXPERIMENT[/b] #all_images#"
        assert editor.save() is True

        assert mgr.get_template("ViperGirls Gallery Post") == original
        assert _read_json(path)["ViperGirls Gallery Post"] == original
        assert _read_json(path)["My Post"] == "[b]MY EXPERIMENT[/b] #all_images#"
        assert infos[-1] == "Template 'My Post' updated."

    def test_loading_a_template_hidden_by_the_search_clears_the_filters(self, tmp_path):
        mgr = TemplateManager(str(tmp_path / "templates.json"))
        mgr.set_template("Zebra", "zebra #all_images#")
        editor = _make_editor(mgr, "BBCode")
        editor.template_search_var.set("gallery")
        editor.template_category_var.set("Forum")

        editor._load_template_content("Zebra")

        assert editor.template_category_var.get() == mgr.CATEGORY_ALL
        assert editor.template_search_var.get() == ""
        assert "Zebra" in editor.cb_fmt.values
        assert editor.fmt.get() == "Zebra"
        assert editor.saved_tmpl_var.get() == "Zebra"
