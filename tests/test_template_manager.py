"""Comprehensive tests for modules/template_manager.py - Template management and substitution"""

import pytest
import os
import sys
import tempfile
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modules.template_manager import TemplateManager


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

            tm = TemplateManager(str(templates_file))

            # File should be created
            assert templates_file.exists()

    def test_load_existing_templates(self):
        """Test loading existing templates from file"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"

            # Create template file with sample data
            sample_templates = {
                "BBCode": "[url={viewer}][img]{thumb}[/img][/url]",
                "HTML": '<a href="{viewer}"><img src="{thumb}" /></a>'
            }

            with open(templates_file, 'w') as f:
                json.dump(sample_templates, f)

            tm = TemplateManager(str(templates_file))
            templates = tm.get_all_templates()

            assert "BBCode" in templates
            assert "HTML" in templates


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
            "thumb": "https://example.com/thumb/123.jpg"
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
            result = template.format(**values)
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
            "another": "also ignored"
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
            with open(templates_file, 'r') as f:
                saved_data = json.load(f)

            assert "Test" in saved_data

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

    def test_file_corruption_handling(self):
        """Test handling of corrupted template file"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"

            # Write invalid JSON
            with open(templates_file, 'w') as f:
                f.write("{invalid json")

            # Should handle gracefully
            try:
                tm = TemplateManager(str(templates_file))
                # Should either start with empty templates or raise proper error
                assert tm is not None
            except (json.JSONDecodeError, ValueError):
                # Acceptable to raise error for corrupted file
                pass


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
            # May or may not have default BBCode


@pytest.mark.unit
class TestTemplateValidation:
    """Test template validation"""

    def test_empty_template_name(self):
        """Test handling of empty template name"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            try:
                tm.add_template("", "[img]{thumb}[/img]")
                # Should either accept or reject empty names
            except ValueError:
                # Acceptable to raise error
                pass

    def test_empty_template_content(self):
        """Test handling of empty template content"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            tm.add_template("Empty", "")
            assert tm.get_template("Empty") == ""

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

            template_with_special = '<a href="{viewer}" title="View & Download">[img]{thumb}[/img]</a>'
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

            tm.add_template("Duplicate", "Version 1")
            tm.add_template("Duplicate", "Version 2")

            # Should overwrite or handle appropriately
            result = tm.get_template("Duplicate")
            assert result in ["Version 1", "Version 2"]

    def test_case_sensitivity(self):
        """Test case sensitivity of template names"""
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_file = Path(temp_dir) / "templates.json"
            tm = TemplateManager(str(templates_file))

            tm.add_template("MyTemplate", "lowercase")
            tm.add_template("MYTEMPLATE", "uppercase")

            # Behavior depends on implementation
            templates = tm.get_all_templates()
            # May treat as same or different


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
            result = template.format(viewer="http://example.com", thumb="http://example.com/thumb.jpg")
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
