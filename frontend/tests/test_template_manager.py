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
from modules.template_manager import TemplateEditor, TemplateManager, TemplateValidationError  # noqa: E402


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

    def test_default_template_path_does_not_migrate_when_new_file_exists(self, tmp_path, monkeypatch):
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

            template_content = "[url={viewer}][img]{thumb}[/img][/url]"
            tm.add_template("Test Template", template_content)

            templates = tm.get_all_templates()
            assert "Test Template" in templates
            assert templates["Test Template"] == template_content

    def test_get_template(self):
        """Test retrieving a specific template"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            template_content = "[img]{direct}[/img]"
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

            tm.add_template("To Delete", "[url]{viewer}[/url]")
            assert "To Delete" in tm.get_all_templates()

            tm.delete_template("To Delete")
            assert "To Delete" not in tm.get_all_templates()

    def test_update_template(self):
        """Test updating an existing template"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            original = "[img]{thumb}[/img]"
            updated = "[url={viewer}][img]{thumb}[/img][/url]"

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

            tm.add_template("Test", "[img]{thumb}[/img]")
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
            tm1.add_template("Persistent", "[url]{viewer}[/url]")

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
            assert json.loads(templates_file.read_text(encoding="utf-8"))["BBCode"] == tm.defaults["BBCode"]


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
            duplicate_else = tm.validate_template("[if gallery_link]A[else]B[else]C[/if]#all_images#")

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

            long_template = "[img]{thumb}[/img]" * 1000
            tm.add_template("Long", long_template)

            retrieved = tm.get_template("Long")
            assert len(retrieved) == len(long_template)

    def test_special_characters_in_template(self):
        """Test templates with special characters"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            template_with_special = (
                '<a href="{viewer}" title="View & Download">[img]{thumb}[/img]</a>'
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
            tm.add_template("Workflow", "[url={viewer}]{thumb}[/url]")

            # Retrieve and use template
            template = tm.get_template("Workflow")
            result = template.format(
                viewer="http://example.com", thumb="http://example.com/thumb.jpg"
            )
            assert result == "[url=http://example.com]http://example.com/thumb.jpg[/url]"

            # Update template
            tm.add_template("Workflow", "[img]{thumb}[/img]")
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

            data = {
                "cover_url": "thumb1",
                "gallery_name": "Test"
            }

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

            result_with_link = mgr.apply("Cond Test", {"gallery_link": "http://example.com"}, images)
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

            assert "Template has a closing [/for] without a matching [for image] or [for cover]." in errors

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

            assert TemplateEditor.get_tags(editor, "Bold") == ("[b]", "[/b]")
            assert TemplateEditor.get_tags(editor, "Color", "#ff0000") == (
                "[color=#ff0000]",
                "[/color]",
            )

            editor.fmt = FakeVar("HTML")
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
        image_labels = {
            label for label, _value in TemplateEditor.PLACEHOLDER_CATEGORIES["Images"]
        }
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

    def test_preview_output_uses_current_editor_template_and_preview_context(self, tmp_path, monkeypatch):
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
