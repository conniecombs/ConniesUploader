# Plugin Architecture Analysis & Improvement Recommendations

## Executive Summary

The current plugin system provides a working foundation for multi-service image uploads, but has significant opportunities for improvement. Key issues include manual plugin registration, repetitive UI code, inconsistent implementation patterns, and lack of automatic plugin discovery.

**Recommendation**: Implement a declarative, schema-based plugin system with automatic discovery, shared UI components, and standardized configuration patterns.

---

## Current Architecture

### Component Overview

```
modules/
├── plugin_manager.py          # Manual plugin registration
├── plugins/
│   ├── base.py               # Abstract base class (ImageHostPlugin)
│   ├── imx.py                # Go-based plugin (UI only)
│   ├── vipr.py               # Go-based plugin (UI only)
│   ├── pixhost.py            # Python-based plugin (full implementation)
│   ├── turbo.py              # Python-based plugin (full implementation)
│   └── imagebam.py           # Python-based plugin (full implementation)
└── upload_manager.py          # Hardcoded service-specific logic
```

### Plugin Interface (base.py)

**Abstract Methods:**
- `id` - Service identifier (e.g., "imx.to")
- `name` - Display name (e.g., "IMX.to")
- `render_settings()` - Create UI widgets
- `get_configuration()` - Extract config from UI
- `initialize_session()` - Setup login/session
- `upload_file()` - Upload single file
- `prepare_group()` - Pre-upload group setup (optional)
- `finalize_batch()` - Post-upload cleanup (optional)

### Two Implementation Patterns

#### Pattern 1: Go-Based Plugins (imx, vipr)
```python
# Only implements UI methods
def render_settings(...)  # Creates UI
def get_configuration(...) # Returns config dict
# Upload handled entirely by Go sidecar
```

#### Pattern 2: Python-Based Plugins (pixhost, turbo, imagebam)
```python
# Full implementation
def render_settings(...)       # Creates UI
def get_configuration(...)     # Returns config dict
def initialize_session(...)    # Python login logic
def upload_file(...)           # Python upload logic
def prepare_group(...)         # Optional pre-processing
def finalize_batch(...)        # Optional cleanup
```

---

## Issues & Pain Points

### 🔴 Critical Issues

#### 1. Manual Plugin Registration

**Current Implementation** (plugin_manager.py:11-17):
```python
def load_plugins(self):
    # Register available plugins here
    classes = [imx.ImxPlugin, pixhost.PixhostPlugin, turbo.TurboPlugin,
               vipr.ViprPlugin, imagebam.ImageBamPlugin]

    for cls in classes:
        instance = cls()
        self._plugins[instance.id] = instance
```

**Problems:**
- Must manually import each plugin at top of file
- Must manually add to `classes` list
- Adding new plugin requires modifying plugin_manager.py
- No automatic discovery
- Easy to forget to register a new plugin

**Impact**: HIGH - Makes adding new plugins cumbersome

---

#### 2. Repetitive UI Code

Every plugin manually creates UI widgets with nearly identical code.

**Example Repetition Across All Plugins:**

```python
# From pixhost.py:24-28
ctk.CTkLabel(parent, text="Content:").pack(anchor="w")
MouseWheelComboBox(parent, variable=vars['content'], values=["Safe", "Adult"]).pack(fill="x")

ctk.CTkLabel(parent, text="Thumb Size:").pack(anchor="w")
MouseWheelComboBox(parent, variable=vars['thumb'], values=["150","200","250",...]).pack(fill="x")
```

```python
# From turbo.py:24-25 - IDENTICAL PATTERN
ctk.CTkLabel(parent, text="Thumb Size:").pack(anchor="w")
MouseWheelComboBox(parent, variable=vars['thumb'], values=["150","200","250",...]).pack(fill="x")
```

```python
# From imagebam.py:20-23 - IDENTICAL PATTERN
ctk.CTkLabel(parent, text="Content Type:").pack(anchor="w")
MouseWheelComboBox(parent, variable=vars['content'], values=["Safe", "Adult"]).pack(fill="x")
```

**Common Repeated Patterns:**
- ✅ Thumb size dropdown (5/5 plugins)
- ✅ Cover count selector (4/5 plugins)
- ✅ Links.txt checkbox (4/5 plugins)
- ✅ Gallery ID/hash entry (3/5 plugins)
- ✅ Content type (Safe/Adult) (3/5 plugins)

**Impact**: VERY HIGH - 80% of UI code is boilerplate

---

#### 3. Hardcoded Service Logic

**upload_manager.py:43-56** - Service-specific cover count logic:
```python
svc = cfg.get("service", "")
cover_cnt = 0
try:
    if "imx" in svc:
        cover_cnt = int(cfg.get("imx_cover_count", 0))
    elif "pix" in svc:
        cover_cnt = int(cfg.get("pix_cover_count", 0))
    elif "turbo" in svc:
        cover_cnt = int(cfg.get("turbo_cover_count", 0))
    elif "vipr" in svc:
        cover_cnt = int(cfg.get("vipr_cover_count", 0))
except (ValueError, TypeError) as e:
    logger.debug(f"Could not get cover count for {svc}: {e}")
```

**upload_manager.py:72-77** - Service-specific thumbnail overrides:
```python
cover_cfg = cfg.copy()
cover_cfg["imx_thumb"] = "600"
cover_cfg["pix_thumb"] = "500"
cover_cfg["turbo_thumb"] = "600"
cover_cfg["vipr_thumb"] = "800x800"
cover_cfg["imagebam_thumb"] = "300"
```

**Problems:**
- Adding new service requires modifying upload_manager.py
- Violates Open/Closed Principle
- Config key naming inconsistency

**Impact**: VERY HIGH - Core upload logic tightly coupled to plugins

---

#### 4. Inconsistent Configuration Keys

Each service uses different naming patterns:

| Service | Thumb Key | Cover Key | Format Key | Gallery Key |
|---------|-----------|-----------|------------|-------------|
| IMX | `imx_thumb_id` | `imx_cover_count` | `imx_format_id` | `gallery_id` |
| Pixhost | `thumb_size` | `cover_limit` | N/A | `gallery_hash` |
| Turbo | `thumb_size` | `cover_limit` | N/A | `gallery_id` |
| Vipr | `vipr_thumb` | `vipr_cover_count` | N/A | `vipr_gal_id` |
| ImageBam | `thumb_size` | N/A | N/A | N/A |

**Problems:**
- No standard naming convention
- Hard to write generic code
- Confusing for developers

**Impact**: MEDIUM - Makes code harder to maintain

---

#### 5. No Plugin Metadata

Plugins lack important metadata:

```python
# Current - only id and name
@property
def id(self): return "imx.to"
@property
def name(self): return "IMX.to"
```

**Missing Information:**
- Version (for compatibility tracking)
- Author/maintainer
- Description (for user help)
- Required credentials
- Supported features (galleries, covers, etc.)
- Go vs Python implementation type
- API endpoint URLs
- Rate limits

**Impact**: MEDIUM - Hard to document and maintain

---

### 🟡 Medium Priority Issues

#### 6. No Plugin Discovery

**Current**: Must manually import and register
**Desired**: Drop plugin file in folder, auto-detected

**Benefits of Auto-Discovery:**
- Easier to add community plugins
- Simpler deployment (just copy file)
- Plugin enable/disable without code changes
- Hot-reload capability

**Impact**: MEDIUM - Affects extensibility

---

#### 7. Missing Validation

No validation of plugin configuration before upload starts.

**Current Behavior:**
```python
def get_configuration(self, ui_handle):
    return {
        'gallery_id': ui_handle['gallery'].get(),  # Could be empty!
        'thumb_size': ui_handle['thumb'].get(),    # Could be invalid!
    }
```

**Problems:**
- Invalid config discovered during upload (too late)
- No type checking
- No range validation
- No required field checking

**Impact**: MEDIUM - Poor user experience

---

#### 8. Credential Management in Plugins

Some plugins directly access keyring:

**vipr.py:48-50**:
```python
def _refresh_galleries(self, parent_widget):
    u = keyring.get_password("ImageUploader:vipr_user", "user")
    p = keyring.get_password("ImageUploader:vipr_pass", "pass")
```

**Problems:**
- Hardcoded keyring service names
- Plugin should receive credentials, not fetch them
- Tight coupling to credential storage

**Impact**: MEDIUM - Violates separation of concerns

---

### 🟢 Minor Issues

#### 9. Hardcoded Service Order

**plugin_manager.py:28-29**:
```python
order = ["imx.to", "pixhost.to", "turboimagehost", "vipr.im", "imagebam.com"]
return [k for k in order if k in self._plugins]
```

**Problems:**
- Adding new plugin requires updating this list
- No way for user to reorder services
- No plugin priority/weight system

**Impact**: LOW - Minor inconvenience

---

#### 10. No Error Context in Upload Methods

Python plugins implement upload but error handling is generic:

```python
def upload_file(self, file_path, group, config, context, progress_callback):
    # If this raises, caller doesn't know which plugin failed
    uploader = api.PixhostUploader(...)
    r = client.post(url, headers=headers, data=data, timeout=300)
    return uploader.parse_response(r.json())
```

**Missing:**
- Plugin name in exceptions
- Retry capability hooks
- Detailed error codes

**Impact**: LOW - Debugging slightly harder

---

## Improvement Recommendations

### Phase 1: Schema-Based UI Generation (HIGH PRIORITY)

**Goal**: Eliminate 80% of repetitive UI code

#### Concept: Declarative Settings Schema

Instead of manually creating widgets, plugins declare their settings:

```python
class PixhostPlugin(ImageHostPlugin):
    @property
    def id(self): return "pixhost.to"

    @property
    def name(self): return "Pixhost.to"

    @property
    def settings_schema(self):
        return [
            {
                "type": "dropdown",
                "key": "content",
                "label": "Content Type",
                "values": ["Safe", "Adult"],
                "default": "Safe",
                "required": True
            },
            {
                "type": "dropdown",
                "key": "thumb_size",
                "label": "Thumbnail Size",
                "values": ["150", "200", "250", "300", "350", "400", "450", "500"],
                "default": "200",
                "required": True
            },
            {
                "type": "number",
                "key": "cover_count",
                "label": "Cover Images",
                "min": 0,
                "max": 10,
                "default": 0
            },
            {
                "type": "checkbox",
                "key": "save_links",
                "label": "Save Links.txt",
                "default": False
            },
            {
                "type": "text",
                "key": "gallery_hash",
                "label": "Gallery Hash (Optional)",
                "default": "",
                "placeholder": "Leave blank for auto-gallery"
            }
        ]
```

#### Implementation Plan

**Step 1: Create SchemaRenderer**

```python
# modules/plugins/schema_renderer.py
class SchemaRenderer:
    """Automatically generates UI from plugin schema."""

    def render(self, parent, schema, current_settings):
        """Creates UI widgets from schema definition."""
        ui_vars = {}

        for field in schema:
            if field['type'] == 'dropdown':
                self._render_dropdown(parent, field, current_settings, ui_vars)
            elif field['type'] == 'checkbox':
                self._render_checkbox(parent, field, current_settings, ui_vars)
            elif field['type'] == 'number':
                self._render_number(parent, field, current_settings, ui_vars)
            elif field['type'] == 'text':
                self._render_text(parent, field, current_settings, ui_vars)

        return ui_vars

    def extract_config(self, ui_vars, schema):
        """Extracts configuration from UI variables with validation."""
        config = {}
        errors = []

        for field in schema:
            key = field['key']
            value = ui_vars[key].get()

            # Validate required fields
            if field.get('required') and not value:
                errors.append(f"{field['label']} is required")

            # Validate ranges
            if field['type'] == 'number':
                try:
                    num_val = int(value)
                    if num_val < field.get('min', 0) or num_val > field.get('max', 999):
                        errors.append(f"{field['label']} must be between {field['min']} and {field['max']}")
                except ValueError:
                    errors.append(f"{field['label']} must be a number")

            config[key] = value

        if errors:
            raise ValidationError(errors)

        return config
```

**Step 2: Update Base Plugin**

```python
# modules/plugins/base.py
class ImageHostPlugin(abc.ABC):
    @property
    @abc.abstractmethod
    def settings_schema(self) -> List[Dict]:
        """
        Returns declarative UI schema.

        Example:
        [
            {
                "type": "dropdown",  # dropdown, checkbox, number, text, label
                "key": "thumb_size",
                "label": "Thumbnail Size",
                "values": ["100", "200", "300"],
                "default": "200",
                "required": True,
                "help": "Optional tooltip text"
            }
        ]
        """
        pass

    # REMOVED: render_settings (auto-generated from schema)
    # REMOVED: get_configuration (auto-extracted from schema)

    # NEW: Optional custom validation
    def validate_configuration(self, config: Dict) -> List[str]:
        """
        Optional: Override to add custom validation logic.
        Returns list of error messages (empty if valid).
        """
        return []
```

**Benefits:**
- ✅ Reduce plugin UI code by ~80%
- ✅ Consistent UI appearance
- ✅ Built-in validation
- ✅ Easy to add new field types
- ✅ Auto-generate documentation from schema

**Effort**: 2-3 days

---

### Phase 2: Plugin Metadata System (HIGH PRIORITY)

**Goal**: Add comprehensive plugin metadata

```python
class ImageHostPlugin(abc.ABC):
    @property
    def metadata(self) -> Dict:
        """Plugin metadata."""
        return {
            "version": "1.0.0",
            "author": "Plugin Author",
            "description": "Upload images to ServiceName",
            "website": "https://example.com",
            "implementation": "go",  # "go" or "python"
            "features": {
                "galleries": True,
                "covers": True,
                "authentication": "required",  # "required", "optional", "none"
                "direct_links": True
            },
            "credentials": [
                {"key": "pixhost_user", "label": "Username", "required": False},
                {"key": "pixhost_pass", "label": "Password", "required": False}
            ],
            "limits": {
                "max_file_size": 50 * 1024 * 1024,  # 50MB
                "allowed_formats": [".jpg", ".jpeg", ".png", ".gif"],
                "rate_limit": "100/hour"
            }
        }
```

**Benefits:**
- ✅ Self-documenting plugins
- ✅ Can validate file size before upload
- ✅ Can check credentials availability
- ✅ Better error messages
- ✅ Plugin compatibility checking

**Effort**: 1 day

---

### Phase 3: Automatic Plugin Discovery (MEDIUM PRIORITY)

**Goal**: Drop plugin file in folder, automatically discovered

#### Implementation

```python
# modules/plugin_manager.py
import importlib
import inspect
from pathlib import Path

class PluginManager:
    def __init__(self):
        self._plugins = {}
        self.load_plugins()

    def load_plugins(self):
        """Automatically discover and load all plugins."""
        plugins_dir = Path(__file__).parent / "plugins"

        # Find all .py files except __init__ and base
        plugin_files = plugins_dir.glob("*.py")

        for plugin_file in plugin_files:
            if plugin_file.stem in ["__init__", "base", "schema_renderer"]:
                continue

            try:
                # Import module
                module_name = f"modules.plugins.{plugin_file.stem}"
                module = importlib.import_module(module_name)

                # Find plugin classes (subclasses of ImageHostPlugin)
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, ImageHostPlugin) and obj != ImageHostPlugin:
                        instance = obj()
                        self._plugins[instance.id] = instance
                        logger.info(f"Loaded plugin: {instance.name} v{instance.metadata['version']}")

            except Exception as e:
                logger.error(f"Failed to load plugin {plugin_file.stem}: {e}")

        # Sort by priority if defined
        self._plugins = dict(sorted(
            self._plugins.items(),
            key=lambda x: x[1].metadata.get('priority', 50)
        ))
```

**Benefits:**
- ✅ No manual registration needed
- ✅ Community plugins supported
- ✅ Enable/disable by renaming file (.disabled)
- ✅ Plugin load errors don't crash app

**Effort**: 1 day

---

### Phase 4: Standardized Configuration Keys (MEDIUM PRIORITY)

**Goal**: Consistent naming across all plugins

#### Standard Configuration Schema

```python
# All plugins use these standard keys
{
    # Core settings (all plugins)
    "thumbnail_size": "200",
    "cover_count": 3,
    "save_links_txt": True,

    # Gallery settings (if supported)
    "gallery_id": "",
    "auto_gallery": True,
    "gallery_name": "",

    # Content settings (if supported)
    "content_type": "safe",  # "safe" or "adult"

    # Service-specific (namespaced)
    "service_specific": {
        "imx_format": "Fixed Width",
        "pixhost_hash": "abc123"
    }
}
```

#### Migration Strategy

```python
class ImageHostPlugin:
    def migrate_legacy_config(self, old_config: Dict) -> Dict:
        """
        Optional: Override to migrate from old config format.
        Called automatically when loading saved settings.
        """
        return old_config  # Default: no migration
```

**Benefits:**
- ✅ Cleaner code in upload_manager
- ✅ Can write generic utilities
- ✅ Easier for users to understand
- ✅ Backward compatible via migration

**Effort**: 2 days

---

### Phase 5: Plugin Configuration Helpers (LOW PRIORITY)

**Goal**: Shared utilities for common plugin tasks

```python
# modules/plugins/helpers.py
class PluginHelpers:
    """Common utilities for plugin developers."""

    @staticmethod
    def get_cover_files(group, config):
        """Returns (covers, standards) file lists."""
        cover_count = config.get('cover_count', 0)
        covers = group.files[:cover_count]
        standards = group.files[cover_count:]
        return covers, standards

    @staticmethod
    def get_max_thumbnail_size(service_id):
        """Returns maximum thumb size for service."""
        max_sizes = {
            "imx.to": "600",
            "pixhost.to": "500",
            "turboimagehost": "600",
            "vipr.im": "800x800",
            "imagebam.com": "300"
        }
        return max_sizes.get(service_id, "300")

    @staticmethod
    def build_gallery_name(group_title, config):
        """Sanitizes and builds gallery name."""
        name = group_title
        # Remove invalid characters
        name = name.replace('[', '').replace(']', '').strip()
        return name

    @staticmethod
    def validate_file(file_path, plugin_metadata):
        """Validates file against plugin limits."""
        limits = plugin_metadata.get('limits', {})

        # Check file size
        if 'max_file_size' in limits:
            size = os.path.getsize(file_path)
            if size > limits['max_file_size']:
                raise ValidationError(f"File too large: {size} bytes")

        # Check format
        if 'allowed_formats' in limits:
            ext = os.path.splitext(file_path)[1].lower()
            if ext not in limits['allowed_formats']:
                raise ValidationError(f"Invalid format: {ext}")
```

**Benefits:**
- ✅ Less code duplication
- ✅ Consistent behavior
- ✅ Easier testing

**Effort**: 1 day

---

### Phase 6: Plugin Testing Framework (LOW PRIORITY)

**Goal**: Easy testing for plugin developers

```python
# tests/test_plugins.py
import pytest
from modules.plugin_manager import PluginManager

class TestPluginInterface:
    """Generic tests that all plugins must pass."""

    @pytest.fixture
    def plugins(self):
        manager = PluginManager()
        return manager.get_all_plugins()

    def test_all_plugins_have_metadata(self, plugins):
        """All plugins must define complete metadata."""
        for plugin in plugins:
            assert hasattr(plugin, 'metadata')
            assert 'version' in plugin.metadata
            assert 'author' in plugin.metadata

    def test_all_plugins_have_valid_schema(self, plugins):
        """All plugins must define valid settings schema."""
        for plugin in plugins:
            assert hasattr(plugin, 'settings_schema')
            schema = plugin.settings_schema
            assert isinstance(schema, list)

            for field in schema:
                assert 'type' in field
                assert 'key' in field
                assert 'label' in field

    def test_schema_validation(self, plugins):
        """Schema validation should catch invalid configs."""
        for plugin in plugins:
            # Test with missing required fields
            empty_config = {}
            with pytest.raises(ValidationError):
                plugin.validate_configuration(empty_config)

# Plugin-specific tests
class TestPixhostPlugin:
    def test_upload_flow(self):
        """Test complete upload flow."""
        # Mock implementation
        pass
```

**Benefits:**
- ✅ Catch bugs early
- ✅ Ensure plugin quality
- ✅ Regression testing

**Effort**: 2 days

---

## Implementation Roadmap

### Quick Wins (1-2 weeks)

✅ **Phase 1: Schema-Based UI** (2-3 days)
- Biggest impact
- Eliminates most boilerplate
- Improves consistency

✅ **Phase 2: Plugin Metadata** (1 day)
- Easy to implement
- Big documentation improvement

✅ **Phase 3: Auto-Discovery** (1 day)
- Immediate extensibility improvement

### Medium Term (1 month)

✅ **Phase 4: Standardized Config** (2 days)
- Requires coordination with upload_manager
- Breaking change (needs migration)

✅ **Phase 5: Helper Utilities** (1 day)
- Incremental improvement
- Can be adopted gradually

### Long Term (Future)

✅ **Phase 6: Testing Framework** (2 days)
- Quality of life
- Not blocking other work

---

## Example: Complete Refactored Plugin

### Before (pixhost.py - 104 lines)

```python
def render_settings(self, parent, settings):
    vars = {
        'content': ctk.StringVar(value=settings.get('pix_content', "Safe")),
        'thumb': ctk.StringVar(value=settings.get('pix_thumb', "200")),
        'cover_count': ctk.StringVar(value=str(settings.get('pix_cover_count', "0"))),
        'links': ctk.BooleanVar(value=settings.get('pix_links', False)),
        'hash': ctk.StringVar(value=settings.get('pix_gallery_hash', ""))
    }

    ctk.CTkLabel(parent, text="Content:").pack(anchor="w")
    MouseWheelComboBox(parent, variable=vars['content'], values=["Safe", "Adult"]).pack(fill="x")

    ctk.CTkLabel(parent, text="Thumb Size:").pack(anchor="w")
    MouseWheelComboBox(parent, variable=vars['thumb'], values=["150","200","250","300","350","400","450","500"]).pack(fill="x")

    # ... 20+ more lines of UI code ...

    return vars
```

### After (pixhost.py - 35 lines)

```python
@property
def metadata(self):
    return {
        "version": "2.0.0",
        "author": "Connie's Uploader Team",
        "description": "Upload images to Pixhost.to with gallery support",
        "implementation": "python",
        "features": {
            "galleries": True,
            "covers": True,
            "authentication": "optional"
        }
    }

@property
def settings_schema(self):
    return [
        {
            "type": "dropdown",
            "key": "content_type",
            "label": "Content Type",
            "values": ["Safe", "Adult"],
            "default": "Safe"
        },
        {
            "type": "dropdown",
            "key": "thumbnail_size",
            "label": "Thumbnail Size",
            "values": ["150", "200", "250", "300", "350", "400", "450", "500"],
            "default": "200"
        },
        {
            "type": "number",
            "key": "cover_count",
            "label": "Cover Images",
            "min": 0,
            "max": 10,
            "default": 0
        },
        {
            "type": "checkbox",
            "key": "save_links_txt",
            "label": "Save Links.txt",
            "default": False
        },
        {
            "type": "text",
            "key": "gallery_hash",
            "label": "Gallery Hash (Optional)",
            "placeholder": "Leave blank for auto-gallery",
            "default": ""
        }
    ]

# render_settings() - AUTO-GENERATED from schema
# get_configuration() - AUTO-GENERATED from schema

# Only custom upload logic remains
def initialize_session(self, config, creds):
    # ... upload implementation ...
```

**Result**:
- ❌ 104 lines → ✅ 35 lines
- ❌ Manual UI → ✅ Declarative schema
- ❌ No validation → ✅ Built-in validation
- ❌ Undocumented → ✅ Self-documenting

---

## Migration Strategy

### Backward Compatibility

To avoid breaking existing code:

```python
class ImageHostPlugin(abc.ABC):
    # NEW: Schema-based approach (preferred)
    @property
    def settings_schema(self) -> List[Dict]:
        return []  # Default: empty, use legacy methods

    # LEGACY: Keep old methods for backward compatibility
    def render_settings(self, parent, settings):
        """Legacy method - use settings_schema instead."""
        if self.settings_schema:
            # Auto-generate from schema
            renderer = SchemaRenderer()
            return renderer.render(parent, self.settings_schema, settings)
        else:
            # Must be overridden by plugin
            raise NotImplementedError

    def get_configuration(self, ui_handle):
        """Legacy method - use settings_schema instead."""
        if self.settings_schema:
            renderer = SchemaRenderer()
            return renderer.extract_config(ui_handle, self.settings_schema)
        else:
            raise NotImplementedError
```

### Migration Path

1. **Week 1**: Implement schema system with backward compatibility
2. **Week 2**: Migrate one plugin (pixhost) to new system, test thoroughly
3. **Week 3**: Migrate remaining plugins
4. **Week 4**: Remove legacy methods (breaking change, bump version)

---

## Additional Recommendations

### 1. Plugin Configuration Presets

Allow users to save/load plugin configurations:

```python
# User saves "High Quality Preset"
{
    "preset_name": "High Quality",
    "pixhost": {
        "thumbnail_size": "500",
        "content_type": "Safe"
    },
    "imx": {
        "thumbnail_size": "600",
        "format": "Proportional"
    }
}
```

### 2. Plugin Hooks System

Allow plugins to hook into application lifecycle:

```python
class ImageHostPlugin:
    def on_application_start(self):
        """Called when app starts."""
        pass

    def on_upload_start(self):
        """Called before batch upload."""
        pass

    def on_upload_complete(self):
        """Called after batch completes."""
        pass
```

### 3. Plugin Dependencies

Allow plugins to declare dependencies:

```python
@property
def metadata(self):
    return {
        "dependencies": {
            "python": ">=3.8",
            "packages": ["requests>=2.31.0", "pillow>=10.0.0"]
        }
    }
```

### 4. Plugin Documentation Generator

Auto-generate plugin documentation:

```bash
$ python -m modules.plugin_manager --generate-docs

# Outputs:
# docs/plugins/pixhost.md
# docs/plugins/imx.md
# etc.
```

---

## Conclusion

The current plugin system works but has significant room for improvement. The recommended schema-based approach will:

- ✅ **Reduce plugin code by 60-80%**
- ✅ **Eliminate repetitive UI boilerplate**
- ✅ **Enable automatic plugin discovery**
- ✅ **Improve validation and error handling**
- ✅ **Make adding new services much easier**
- ✅ **Better documentation and metadata**

**Total Implementation Effort**: ~2 weeks
**Impact**: VERY HIGH - Transforms plugin system from manual to declarative

**Recommended Start**: Begin with Phase 1 (Schema-Based UI) for immediate 80% code reduction.

---

*Analysis Date: 2025-12-31*
*Current Version: v3.5.0*
*Plugin Count: 5 (imx, pixhost, turbo, vipr, imagebam)*
