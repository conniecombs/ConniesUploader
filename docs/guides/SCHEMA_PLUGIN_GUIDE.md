# Schema Plugin Guide

The schema system lets image-host plugins declare their settings as data. The app renders the settings UI, restores saved values, extracts configuration, validates field types, and attaches tooltips automatically.

Use this guide for plugin settings UI. Use [Plugin Creation Guide](PLUGIN_CREATION_GUIDE.md) for upload request specs and sidecar behavior.

## Why Use Schemas

Schema settings are preferred for active plugins because they:

- Keep host settings consistent across services.
- Remove manual widget boilerplate.
- Provide built-in required/range validation.
- Support tooltips through `help`.
- Support collapsible advanced host settings.
- Work in source and packaged builds.

Manual `render_settings()` / `get_configuration()` methods still exist for compatibility, but new plugins should use `settings_schema`.

## Minimal Example

```python
from typing import Any, Dict, List

from .base import ImageHostPlugin


class MyPlugin(ImageHostPlugin):
    @property
    def id(self) -> str:
        return "myservice.com"

    @property
    def name(self) -> str:
        return "My Service"

    @property
    def settings_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "dropdown",
                "key": "thumbnail_size",
                "label": "Thumbnail Size",
                "values": ["150", "250", "500"],
                "default": "250",
                "required": True,
                "help": "Thumbnail size requested from the image host.",
            },
            {
                "type": "checkbox",
                "key": "save_links",
                "label": "Save Links.txt",
                "default": False,
                "help": "Also save raw host links beside generated output.",
            },
        ]

    def validate_configuration(self, config: Dict[str, Any]) -> List[str]:
        return []
```

With this schema, the base plugin class auto-generates `render_settings()` and `get_configuration()`.

## Field Basics

Every data field needs:

| Key | Purpose |
| --- | --- |
| `type` | Widget type. |
| `key` | Config key saved/extracted for uploads. |
| `label` | User-facing label. |
| `default` | Fallback value when no saved setting exists. |

Common optional keys:

| Key | Purpose |
| --- | --- |
| `required` | Adds non-empty validation. |
| `help` | Tooltip text shown on hover. |
| `advanced` | Moves the field into collapsed Advanced Host Settings. |
| `validate` | Custom field-level validation callback. |
| `value_labels` | Maps stored dropdown values to friendlier display labels. |

## Supported Field Types

### Dropdown

```python
{
    "type": "dropdown",
    "key": "thumbnail_size",
    "label": "Thumbnail Size",
    "values": ["150", "250", "500"],
    "default": "250",
    "required": True,
    "help": "Thumbnail size requested from the host.",
}
```

Dropdown output is a string.

Use `value_labels` when the host wants compact IDs but users should see readable names:

```python
{
    "type": "dropdown",
    "key": "thumbnail_size",
    "label": "Thumbnail Size",
    "values": ["2", "5", "8"],
    "value_labels": {
        "2": "180 px",
        "5": "500 px",
        "8": "Original",
    },
    "default": "2",
}
```

The UI shows labels, while extracted config stores the original values.

### Checkbox

```python
{
    "type": "checkbox",
    "key": "save_links",
    "label": "Save Links.txt",
    "default": False,
    "help": "Save raw host links in addition to generated output.",
}
```

Checkbox output is a Boolean.

### Number

```python
{
    "type": "number",
    "key": "cover_count",
    "label": "Auto Covers",
    "min": 0,
    "max": 10,
    "default": 0,
    "help": "Automatically mark the first N images as covers.",
}
```

Number fields render as a constrained dropdown and extract an integer.

### Text

```python
{
    "type": "text",
    "key": "gallery_hash",
    "label": "Gallery Hash",
    "default": "",
    "placeholder": "Optional",
    "help": "Use an existing host gallery hash.",
}
```

Text output is a string.

### Label

```python
{
    "type": "label",
    "text": "Requires credentials set from Tools > Set Credentials.",
    "color": "red",
}
```

Labels are display-only and do not produce config output.

### Separator

```python
{
    "type": "separator",
}
```

Separators are visual-only and do not produce config output.

### Inline Group

```python
{
    "type": "inline_group",
    "fields": [
        {"type": "label", "text": "Auto Covers:", "width": 100},
        {
            "type": "dropdown",
            "key": "cover_count",
            "values": [str(i) for i in range(11)],
            "default": "0",
            "width": 80,
        },
    ],
}
```

Inline groups currently support labels and dropdowns. Use them sparingly for compact settings that are clearly related.

## Advanced Host Settings

Add `"advanced": True` to move fields into a collapsed `Advanced Host Settings` section:

```python
{
    "type": "text",
    "key": "custom_endpoint",
    "label": "Custom Endpoint",
    "default": "",
    "placeholder": "Leave blank for default",
    "advanced": True,
}
```

Use this for rarely changed or troubleshooting-oriented host options. Do not hide settings that users need for normal uploads.

## Validation

### Built-In Validation

The schema renderer validates:

- Required fields.
- Number fields with `min` and `max`.
- Number field type conversion.

When validation fails, `get_configuration()` raises `ValidationError` with all collected errors.

### Field-Level Validation

Use a `validate` callback for one field:

```python
def validate_gallery_hash(value):
    if value and not value.replace("-", "").isalnum():
        return "Gallery Hash may only contain letters, numbers, or hyphens."
    return None


{
    "type": "text",
    "key": "gallery_hash",
    "label": "Gallery Hash",
    "default": "",
    "validate": validate_gallery_hash,
}
```

The callback may return `None`, a string, or a list of strings.

### Plugin-Level Validation

Use `validate_configuration()` for rules that depend on multiple fields:

```python
def validate_configuration(self, config: Dict[str, Any]) -> List[str]:
    errors = []
    if config.get("one_gallery_per_folder") and config.get("gallery_hash"):
        errors.append("Do not set Gallery Hash when One Gallery Per Folder is enabled.")
    return errors
```

## Common Patterns

### Content Type

```python
{
    "type": "dropdown",
    "key": "content_type",
    "label": "Content Type",
    "values": ["Safe", "Adult"],
    "default": "Safe",
}
```

### Thumbnail Size

```python
{
    "type": "dropdown",
    "key": "thumbnail_size",
    "label": "Thumbnail Size",
    "values": ["150", "200", "250", "300", "500"],
    "default": "250",
}
```

### Cover Count

```python
{
    "type": "number",
    "key": "cover_count",
    "label": "Auto Covers",
    "min": 0,
    "max": 10,
    "default": 0,
}
```

`cover_count` is the preferred key for automatic cover selection. Selected covers can later be rendered with `#cover_images#` or `[for cover]...[/for]`.

### Existing Gallery

```python
{
    "type": "text",
    "key": "gallery_id",
    "label": "Gallery ID",
    "default": "",
    "placeholder": "Optional",
}
```

Use the key that matches the service (`gallery_id`, `gallery_hash`, or another host-specific identifier). Gallery Manager assignment should preserve the real gallery name separately when available.

### Save Raw Links

```python
{
    "type": "checkbox",
    "key": "save_links",
    "label": "Save Links.txt",
    "default": False,
}
```

## Migration From Manual UI

1. Find `render_settings()` in the plugin.
2. List every setting key returned by `get_configuration()`.
3. Convert each widget into a schema field using the same config key where possible.
4. Add `value_labels` if old values were host IDs but UI labels were friendlier.
5. Move cross-field rules into `validate_configuration()`.
6. Delete manual `render_settings()` and `get_configuration()` unless custom UI is truly required.
7. Run plugin/schema tests and one source-run upload.

Legacy plugins still work, but active maintained plugins should use schemas so service settings stay consistent.

## Testing Schema Changes

Run:

```bash
(cd frontend && pytest tests/test_plugins.py -v)
(cd frontend && pytest tests/test_service_settings_contract.py -v)
(cd frontend && pytest tests/ -v)
```

For UI-affecting schema changes, manually check:

- Defaults render correctly.
- Saved settings reload correctly.
- Tooltips show for `help`.
- Required errors are readable.
- Number fields clamp/report invalid values.
- Advanced settings collapse and expand.
- Upload Checks report validation problems before upload starts.

## Troubleshooting

**Field does not appear**

Check `type` spelling and make sure the field is not inside an unsupported inline group type.

**Value is missing from upload config**

Display-only fields (`label`, `separator`) do not produce config output. Data fields need a `key`.

**Dropdown stores the visible label instead of host value**

Use `value_labels` with stored values in `values`.

**Number value is a string**

Number fields extract integers. Dropdown fields extract strings, even if their values look numeric.

**Tooltip does not show**

Tooltips are attached to labels or checkboxes. Make sure the field has non-empty `help` text and that the widget is not immediately destroyed/re-rendered.

**Manual UI is still used**

If `settings_schema` returns an empty list, the base class falls back to legacy `render_settings()` and `get_configuration()`.

## Related Docs

- [Plugin Creation Guide](PLUGIN_CREATION_GUIDE.md)
- [Architecture](../ARCHITECTURE.md)
- [Repository Layout](REPOSITORY_LAYOUT.md)

- **Guide Version:** 2.1
- **Last Updated:** 2026-06-30
