# main.py Refactoring Plan

## Overview
main.py is currently 1097 lines with the `UploaderApp` class having too many responsibilities. This plan outlines refactoring opportunities to improve maintainability, testability, and code organization.

## Current Issues

### 1. Massive Monolithic Class (1097 lines)
**Problem**: UploaderApp handles too many concerns:
- UI creation and layout
- Upload orchestration
- File handling and drag-and-drop
- ViperGirls forum posting
- Settings management
- Credentials management
- Template management
- Progress tracking

**Impact**: High - Makes testing difficult, hard to maintain

### 2. Long __init__ Method (85 lines, lines 59-144)
**Problem**: Initializes 70+ instance variables, creates managers, builds UI
```python
def __init__(self):
    # 85 lines of initialization
    # Too many responsibilities
```

**Impact**: High - Violates Single Responsibility Principle

### 3. Credentials Dialog Repetition (78 lines, lines 293-370)
**Problem**: Repetitive pattern for 5 services:
```python
# Pattern repeated 5 times:
nb.add("ServiceName")
t = nb.tab("ServiceName")
ctk.CTkLabel(t, text="Username:").pack(anchor="w")
v_user = ctk.StringVar(value=self.creds["service_user"])
ctk.CTkEntry(t, textvariable=v_user).pack(fill="x")
# ... password field ...
```

**Impact**: Medium - Code duplication, hard to add new services

### 4. Settings Apply/Gather Duplication
**Problem**: Repetitive code for each service

`_apply_settings` (49 lines, lines 476-524):
```python
self.var_imx_thumb.set(s.get("imx_thumb", "180"))
self.var_imx_format.set(s.get("imx_format", "Fixed Width"))
# ... repeated for 5 services ...
```

`_gather_settings` (33 lines, lines 537-580):
```python
{
    "imx_thumb": self.var_imx_thumb.get(),
    "imx_format": self.var_imx_format.get(),
    # ... repeated for 5 services ...
}
```

**Impact**: Medium - Makes adding new services tedious

### 5. Magic Numbers
**Problem**: Hard-coded values scattered throughout:
- Line 70: `ThreadPoolExecutor(max_workers=4)` → should use `config.THUMBNAIL_WORKERS`
- Line 99: `self.POST_COOLDOWN = 1.5` → should use `config.POST_COOLDOWN_SECONDS`
- Line 824: `ui_limit = 10` → unnamed constant
- Line 834: `prog_limit = 50` → unnamed constant
- Line 869: `self.after(10, ...)` → UI refresh rate

**Impact**: Low - But reduces code clarity

### 6. Long Methods
**Methods over 50 lines:**
- `update_ui_loop` (56 lines) - processes 3 different queues
- `start_upload` (74 lines) - setup and orchestration
- `generate_group_output` (85 lines) - output generation and posting
- `open_creds_dialog` (78 lines) - UI creation with repetition

**Impact**: Medium - Reduces readability

### 7. Embedded ViperGirls Posting Logic (lines 779-812)
**Problem**: Auto-posting to forum is embedded in main app class
```python
def _process_post_queue(self):
    # 34 lines of forum posting logic
    # Should be extracted to separate class
```

**Impact**: Medium - Mixed concerns

### 8. Service Frame Coupling
**Problem**: main.py references `self.service_frames` created in `ServiceSettingsView`
```python
def _swap_service_frame(self, service_name):
    for frame in self.service_frames.values():  # Tight coupling
        frame.pack_forget()
```

**Impact**: Low - But indicates design issue

## Refactoring Recommendations

### Priority 1: High Impact, Low Risk

#### 1.1 Extract Magic Numbers to config.py
**Effort**: Low | **Impact**: Medium
```python
# Add to modules/config.py:
UI_UPDATE_INTERVAL_MS = 10
UI_QUEUE_BATCH_SIZE = 10
PROGRESS_QUEUE_BATCH_SIZE = 50
THUMBNAIL_WORKERS = 4  # Already exists
POST_COOLDOWN_SECONDS = 1.5  # Already exists
```

**Changes**: main.py lines 70, 99, 824, 834, 869

#### 1.2 Extract Credentials Management
**Effort**: Medium | **Impact**: High

Create `modules/credentials_manager.py`:
```python
class CredentialsManager:
    """Manages service credentials using system keyring."""

    SERVICE_CONFIGS = {
        "imx.to": {
            "fields": [
                {"key": "imx_api", "label": "API Key", "show": "*"},
                {"key": "imx_user", "label": "Username"},
                {"key": "imx_pass", "label": "Password", "show": "*"},
            ]
        },
        "turboimagehost": {...},
        # ... other services
    }

    def load_all_credentials(self) -> Dict[str, str]:
        """Load credentials for all services."""

    def save_credentials(self, creds: Dict[str, str]):
        """Save credentials to keyring."""

    def create_credentials_dialog(self, parent) -> None:
        """Create credentials dialog using SERVICE_CONFIGS."""
```

**Benefits**:
- Eliminates 78-line repetitive dialog
- Easy to add new services
- Testable in isolation

#### 1.3 Data-Driven Settings Management
**Effort**: High | **Impact**: High

Create settings schema and use it for apply/gather:
```python
# modules/settings_schema.py
SERVICE_SETTINGS = {
    "imx.to": [
        {"key": "imx_thumb", "var": "var_imx_thumb", "default": "180"},
        {"key": "imx_format", "var": "var_imx_format", "default": "Fixed Width"},
        # ...
    ],
    # ... other services
}

def apply_settings_from_schema(app, settings, schema):
    """Apply settings using schema."""
    for service_settings in schema.values():
        for setting in service_settings:
            var = getattr(app, setting["var"])
            var.set(settings.get(setting["key"], setting["default"]))
```

**Benefits**:
- Reduces `_apply_settings` from 49 lines to ~10
- Reduces `_gather_settings` from 33 lines to ~10
- Single source of truth for settings

### Priority 2: Medium Impact, Medium Risk

#### 2.1 Extract ViperGirls Auto-Poster
**Effort**: Medium | **Impact**: Medium

Create `modules/auto_poster.py`:
```python
class AutoPoster:
    """Handles automatic posting to ViperGirls forum."""

    def __init__(self, credentials, saved_threads_data):
        self.vg_api = viper_api.ViperGirlsAPI()
        self.post_queue = {}
        self.next_index = 0

    def queue_post(self, batch_index: int, content: str, thread_name: str):
        """Queue content for posting."""

    def process_queue(self, is_uploading_callback, cancel_event):
        """Process queued posts with cooldown."""
```

**Benefits**:
- Separates forum posting from upload logic
- Easier to test posting independently
- Reduces main.py by ~40 lines

#### 2.2 Split Long Methods
**Effort**: Medium | **Impact**: Medium

Extract sub-methods from long methods:

`update_ui_loop` → 3 methods:
- `_process_result_queue()`
- `_process_ui_queue()`
- `_process_progress_queue()`

`start_upload` → 3 methods:
- `_prepare_upload_session(pending_groups)`
- `_initialize_auto_posting(pending_groups)`
- `_start_upload_workers(pending_groups, config, creds)`

`generate_group_output` → 3 methods:
- `_collect_group_results(group)`
- `_generate_output_text(group, results)`
- `_save_output_files(group, text)`

**Benefits**:
- Improves readability
- Easier to test individual pieces
- Better error isolation

#### 2.3 Split __init__ Method
**Effort**: Low | **Impact**: Medium

Break __init__ into logical chunks:
```python
def __init__(self):
    super().__init__()
    self._init_window()
    self._init_managers()
    self._init_state()
    self._init_ui()
    self._load_startup_file()

def _init_window(self):
    """Initialize window properties."""

def _init_managers(self):
    """Initialize manager objects."""

def _init_state(self):
    """Initialize application state variables."""

def _init_ui(self):
    """Initialize user interface."""
```

**Benefits**:
- Clearer initialization flow
- Easier to understand responsibilities
- Better organization

### Priority 3: Lower Impact (Future Improvements)

#### 3.1 Extract UI Builder Classes
**Effort**: High | **Impact**: Low (already using ServiceSettingsView)

Create dedicated UI builder classes:
- `MenuBuilder` - creates menu bar
- `LeftPanelBuilder` - creates settings panel
- `RightPanelBuilder` - creates file list panel

**Note**: May be overkill for current needs

#### 3.2 Extract File Processing
**Effort**: Medium | **Impact**: Low (already using file_handler module)

Move `_process_files` logic to `modules/file_handler.py`

**Note**: Already well-organized in separate module

## Recommended Implementation Order

### Phase 1: Quick Wins (2-3 hours)
1. ✅ Extract magic numbers to config.py
2. ✅ Split __init__ into sub-methods
3. ✅ Split long methods into smaller pieces

### Phase 2: Structural Improvements (4-6 hours)
4. Extract CredentialsManager class
5. Create data-driven settings schema
6. Extract AutoPoster class

### Phase 3: Polish (2-3 hours)
7. Update tests for new structure
8. Update documentation
9. Remove any remaining duplication

## Success Metrics

- ✅ main.py reduced from 1097 lines to < 700 lines
- ✅ No method longer than 40 lines
- ✅ All magic numbers replaced with named constants
- ✅ Credentials and settings logic extracted and testable
- ✅ Clear separation of concerns (UI, upload, posting)

## Testing Strategy

- Run full application after each phase
- Test all service uploads (imx, pixhost, turbo, vipr, imagebam)
- Test credentials dialog
- Test settings persistence
- Test ViperGirls auto-posting
- Test drag-and-drop functionality

## Risks and Mitigation

**Risk**: Breaking existing functionality
**Mitigation**:
- Incremental changes with testing after each step
- Git commits after each working phase
- Keep original logic, just reorganize it

**Risk**: ServiceSettingsView coupling
**Mitigation**:
- Review ServiceSettingsView implementation
- May need to refactor how service_frames are stored

**Risk**: Complex state management
**Mitigation**:
- Document state variables clearly
- Group related state into objects
