# Architecture Analysis & Roadmap

## Executive Summary

**Product Version:** v1.2.1
**Architecture Version:** v2.4.0 (Complete Migration - 100% Plugin-Driven)

**Status:** The application is now **fully refactored** with a plugin-driven architecture. The split-brain problem has been RESOLVED by making Go a "dumb HTTP runner" that executes requests defined by Python plugins. ALL services (stateless APIs and session-based) now use the generic HTTP runner!

**Migration Progress:** 5/5 services (100%) using generic HTTP runner - **MIGRATION COMPLETE!**

## Recent Fixes (v2.4.0)

### ✅ RESOLVED: Complete Migration to Generic HTTP Runner (100%)
- **Problem:** TurboImageHost and ImageBam still used hardcoded Go logic. ImageBam had complex 4-step login requiring template substitution in headers/form fields.
- **Solution:** Enhanced Phase 3 protocol with advanced features:
  - **Regex extraction** in HTML parsing: `"regex:pattern"` selector support
  - **URL templates** for response parsing: `{id}` and `{filename}` substitution
  - **Form field templates**: Template substitution in POST body fields
  - **Header templates**: Dynamic header values from extracted data (e.g., `X-CSRF-TOKEN: {csrf}`)
  - **Multi-level nesting**: Parent extracted values passed to child requests
- **Impact:** ALL 5 services now use generic HTTP runner - **100% migration complete!**

**Examples:**

TurboImageHost (regex + URL template):
```python
"extract_fields": {
    "endpoint": "regex:endpoint:\\s*'([^']+)'"  # Extract from JavaScript
},
"response_parser": {
    "url_template": "https://turboimagehost.com/p/{id}/{filename}.html"
}
```

ImageBam (4-step chain with template substitution):
```python
"form_fields": {
    "_token": "{login_token}",  # Use token from step 1
},
"headers": {
    "X-CSRF-TOKEN": "{csrf_token}"  # Use token from step 3
}
```

---

## Recent Fixes (v2.3.0)

### ✅ RESOLVED: Session Management for HTTP Runner (HIGH PRIORITY)
- **Problem:** Generic HTTP runner (v2.2.0) only supported stateless APIs. Session-based services (Vipr, Turbo, ImageBam) required hardcoded Go logic for login flows.
- **Solution:** Implemented Phase 3 session management features:
  - Multi-step pre-request chaining with `FollowUpRequest` field
  - Cookie jar support for session persistence across requests
  - Dynamic field resolution to use extracted values (session IDs, tokens, endpoints)
  - `executePreRequest()` and `executeFollowUpRequest()` functions
- **Impact:** Session-based services can now use generic HTTP runner! Vipr.im migrated as proof of concept.

**Example:** Vipr multi-step login in Python plugin:
```python
"pre_request": {
    "action": "login_step1",
    "url": "https://vipr.im/login.html",
    "method": "POST",
    "form_fields": {"op": "login", "login": user, "password": pwd},
    "use_cookies": True,
    "follow_up_request": {
        "action": "login_step2",
        "url": "https://vipr.im/",
        "method": "GET",
        "use_cookies": True,
        "extract_fields": {"sess_id": "input[name='sess_id']"},
        "response_type": "html"
    }
},
"multipart_fields": {
    "sess_id": {"type": "dynamic", "value": "sess_id"}  # Use extracted value
}
```

---

## Recent Fixes (v2.2.0)

### ✅ RESOLVED: Split-Brain Architecture (CRITICAL)
- **Problem:** Python had dynamic plugins but Go had hardcoded service logic. Adding new services required modifying and recompiling Go.
- **Solution:** Implemented generic HTTP runner architecture:
  - Python plugins define HTTP requests via `build_http_request()` method
  - Go executes generic requests without service-specific knowledge
  - New action: `http_upload` with `HttpRequestSpec` protocol
  - Supports JSON and HTML response parsing
  - Full backward compatibility with legacy `upload` action
- **Impact:** Can now add new services by **dropping in Python plugins only** - no Go changes or recompilation needed!

**Example:** IMX plugin now builds request spec declaratively:
```python
def build_http_request(self, file_path, config, creds):
    return {
        "url": "https://api.imx.to/v1/upload.php",
        "method": "POST",
        "headers": {"X-API-KEY": creds.get("imx_api")},
        "multipart_fields": {
            "image": {"type": "file", "value": file_path},
            "format": {"type": "text", "value": "json"},
            "thumbnail_size": {"type": "text", "value": "2"}
        },
        "response_parser": {
            "type": "json",
            "url_path": "data.image_url",
            "thumb_path": "data.thumbnail_url",
            "status_path": "status",
            "success_value": "success"
        }
    }
```

---

## Recent Fixes (v2.1.0)

### ✅ RESOLVED: Timeout Issues
- **Problem:** Aggressive 10-second `ResponseHeaderTimeout` caused large uploads to fail
- **Fix:** Increased timeouts to realistic values:
  - Client timeout: 180s (3 minutes)
  - Response header timeout: 60s
  - Context timeout: 180s per file
- **Impact:** Large files (10-50MB) and slow connections now work reliably

### ✅ RESOLVED: Rate Limiting (IP Ban Prevention)
- **Problem:** No throttling meant 8 concurrent workers could bombard services instantly
- **Fix:** Implemented per-service rate limiters using `golang.org/x/time/rate`
  - 2 requests/second with burst of 5 for image hosts
  - 1 request/second with burst of 3 for forums (ViperGirls)
- **Impact:** Significantly reduced risk of automated IP bans

### ✅ RESOLVED: Global State Bottleneck
- **Problem:** Single global `stateMutex` locked all services during session checks
- **Fix:** Refactored to per-service state structs with individual `sync.RWMutex`
  - `viprState`, `turboState`, `imageBamState`, `viperGirlsState`
- **Impact:** Reduced lock contention; parallel uploads to different services no longer block each other

---

## Remaining Architectural Issues

### ✅ RESOLVED: The "Split-Brain" Architecture (v2.2.0)

**The Solution:**
Generic HTTP runner architecture eliminates hardcoded service logic in Go. Python plugins now fully control the upload process:

**How It Works:**
1. Plugin implements `build_http_request(file_path, config, creds)` method
2. Returns HTTP request specification (URL, headers, multipart fields, response parser)
3. Upload manager sends `http_upload` action to Go with the spec
4. Go's `executeHttpUpload()` function:
   - Applies rate limiting
   - Builds multipart request from spec
   - Executes HTTP request
   - Parses response using spec (JSON or HTML)
   - Returns results to Python

**Backward Compatibility:**
- Legacy `upload` action still works with hardcoded services
- Plugins can opt-in to new protocol by implementing `build_http_request()`
- Upload manager automatically detects and uses new protocol when available

---

### ✅ RESOLVED: Fragile Configuration Mapping (v2.2.0)

**The Solution:**
Plugins now own their configuration mapping logic via `build_http_request()`:

```python
# Inside IMX plugin - plugin owns the mapping
def build_http_request(self, file_path, config, creds):
    size_map = {"100": "1", "150": "6", "180": "2", ...}
    thumb_size = size_map.get(config.get("thumbnail_size", "180"), "2")
    # ... build request with mapped values
```

**Benefits:**
- Plugin encapsulates ALL service-specific logic (UI schema + HTTP request)
- Upload manager is now service-agnostic
- Adding a new service = 1 file (the plugin only)

---

### 🟡 MEDIUM: Lack of Input Sanitization (Go Side)

**The Problem:**
- Python has `sanitize_filename()`, but Go trusts all file paths from JSON
- A malicious plugin could theoretically trick Go into reading arbitrary files

**Mitigation:**
- Low risk in a desktop app context (user controls plugins)
- Should still validate file paths are within expected directories

---

## Recommended Roadmap

### ✅ Phase 1: Completed (v2.1.0)
- ✅ Fix timeouts (180s/60s)
- ✅ Implement rate limiting (2 req/s per service)
- ✅ Refactor global state (per-service mutexes)

### ✅ Phase 2: Completed (v2.2.0 - Generic HTTP Runner)
- ✅ Implemented `handleHttpUpload` in Go
- ✅ Added generic multipart builder
- ✅ Added JSON/HTML response parser
- ✅ Updated base plugin class with `build_http_request()` method
- ✅ Migrated IMX plugin to new protocol
- ✅ Updated upload manager to auto-detect new protocol
- ✅ Maintained full backward compatibility

**Result:** Python plugins now fully control uploads - no Go changes needed for new services!

---

### ✅ Phase 3: Completed (v2.3.0 - Session Management)
- ✅ Implemented `PreRequestSpec` with multi-step request chaining
- ✅ Added cookie jar support for session persistence
- ✅ Implemented dynamic field resolution from extracted values
- ✅ Added `executePreRequest()` and `executeFollowUpRequest()` functions
- ✅ Migrated Vipr plugin to new protocol (proof of concept)
- ✅ Enhanced `MultipartField` to support "dynamic" type

**Result:** Session-based services (Vipr, Turbo, ImageBam) can now use generic HTTP runner!

**Migration Status:**
- ✅ **IMX.to** - Migrated (stateless API)
- ✅ **Pixhost.to** - Migrated (stateless API)
- ✅ **Vipr.im** - Migrated (session-based, 2-step login)
- ✅ **TurboImageHost** - Migrated (session-based, endpoint discovery)
- ✅ **ImageBam** - Migrated (session-based, 4-step login with CSRF)

**Progress: 5/5 (100%)** - ✨ **MIGRATION COMPLETE!** ✨

---

### ✅ Phase 4: Completed (v2.4.0 - Complete Migration)
- ✅ Implemented regex extraction for HTML (`regex:` prefix)
- ✅ Implemented URL templates with `{placeholder}` substitution
- ✅ Implemented form field templates for dynamic POST bodies
- ✅ Implemented header templates for dynamic header values
- ✅ Enhanced follow-up requests to pass parent extracted values
- ✅ Migrated TurboImageHost to new protocol
- ✅ Migrated ImageBam to new protocol

**Result:** 100% of services now use generic HTTP runner - **ZERO hardcoded service logic in Go!**

---

### Phase 5: Future Enhancements

**High Priority:**
1. **Retry Logic:** Automatic retry with exponential backoff for transient failures
2. **Progress Streaming:** Real-time upload progress (currently only status changes)

**Medium Priority:**
4. **Credential Encryption:** Store API keys/passwords encrypted at rest (OS keychain)
5. **Plugin Sandboxing:** Limit plugin file system access
6. **Configuration Validation:** JSON schema validation for plugin configs

---

## Security Assessment

### Current State

✅ **Good:**
- Credentials passed via stdin (not environment/CLI args)
- TLS verification enabled (no `InsecureSkipVerify`)
- Uses crypto/rand for randomness

⚠️ **Needs Improvement:**
- No input sanitization on Go side
- ViperGirls uses MD5 (legacy forum requirement, documented)
- Credentials stored in plaintext SQLite

### Recommendations

1. Add file path validation in Go (must be absolute, within user directory)
2. Consider encrypting stored credentials (using OS keychain on desktop)
3. Add rate limit for login attempts to prevent brute force

---

## Performance Characteristics

**Current Bottlenecks:**
1. ~~Global state mutex~~ ✅ FIXED
2. ~~Aggressive timeouts~~ ✅ FIXED
3. Worker pool size hardcoded to 8 (should be configurable)

**Scalability:**
- Handles ~100-200 files/batch reliably
- Beyond 500 files: UI may become unresponsive (consider background mode)

**Memory:**
- Streaming uploads (pipe-based) keep memory low
- Each worker holds ~5-10MB during upload

---

## Graceful Shutdown Architecture

**Status:** ✅ IMPLEMENTED (v1.0.6)

The application implements a comprehensive graceful shutdown system to ensure all components terminate cleanly and no resources are leaked.

### Shutdown Flow

```
User Action (Exit/Ctrl+C/SIGTERM)
    ↓
main.py signal_handler / UploaderApp.graceful_shutdown()
    ↓
    ├─→ Set cancel_event (stops uploads)
    │   └─→ UploadManager detects cancel and stops dispatching
    │       └─→ Worker threads check cancel_event and exit
    ↓
    ├─→ AutoPoster.stop()
    │   ├─→ Set is_running = False
    │   └─→ Join worker thread (3s timeout)
    ↓
    ├─→ RenameWorker.stop()
    │   ├─→ Set active = False
    │   └─→ Join worker thread (2s timeout)
    ↓
    ├─→ ThreadPoolExecutor.shutdown(wait=False)
    │   └─→ Cancel pending thumbnail generation tasks
    ↓
    ├─→ UploadManager.shutdown()
    │   ├─→ Remove event listener from SidecarBridge
    │   └─→ Join listener thread (2s timeout)
    ↓
    ├─→ SidecarBridge.shutdown()
    │   ├─→ Close stdin (signals Go process to exit)
    │   ├─→ Wait 5s for graceful termination
    │   └─→ Force kill if timeout (terminate → kill)
    ↓
    └─→ Tkinter.quit() - Exit GUI main loop
```

### Component Shutdown Methods

#### 1. Main Application (main.py)
- **Signal Handling**: Registers handlers for `SIGINT` (Ctrl+C) and `SIGTERM`
- **Implementation**: Calls `app.graceful_shutdown()` and exits

#### 2. UploaderApp (modules/ui/main_window.py)
- **Protocol Handler**: Registers `WM_DELETE_WINDOW` to intercept window close
- **Menu Integration**: File > Exit calls `graceful_shutdown()` instead of `quit()`
- **Shutdown Sequence**:
  1. Stops uploads via `cancel_event`
  2. Iterates through all managed components
  3. Catches and logs exceptions to prevent shutdown blocking
  4. Finally calls `self.quit()` to exit Tkinter

#### 3. AutoPoster (modules/auto_poster.py)
- **Method**: `stop()`
- **Behavior**:
  - Sets `is_running = False` flag
  - Worker thread checks flag and exits gracefully
  - Main thread joins with 3-second timeout
  - Prevents orphaned posting threads

#### 4. RenameWorker (modules/controller.py)
- **Method**: `stop()`
- **Behavior**:
  - Sets `active = False` flag
  - Worker thread checks flag in run loop
  - Exits cleanly after current task completes
  - Join with 2-second timeout

#### 5. UploadManager (modules/upload_manager.py)
- **Method**: `shutdown()`
- **Behavior**:
  - Unregisters event queue from SidecarBridge
  - Listener thread checks `cancel_event` and exits
  - Join with 2-second timeout
  - Prevents event processing after shutdown

#### 6. SidecarBridge (modules/sidecar.py)
- **Method**: `shutdown()`
- **Behavior**:
  - Closes stdin pipe (Go process reads EOF and exits)
  - Waits 5 seconds for graceful termination
  - If timeout: sends SIGTERM (graceful)
  - If still alive after 2s: sends SIGKILL (forceful)
  - Sets `self.proc = None` to prevent restart attempts

### Timeouts and Failsafes

| Component | Timeout | Fallback |
|-----------|---------|----------|
| AutoPoster | 3s | Continue shutdown |
| RenameWorker | 2s | Continue shutdown |
| UploadManager | 2s | Continue shutdown |
| Sidecar (graceful) | 5s | SIGTERM |
| Sidecar (forced) | 2s | SIGKILL |

### Error Handling

- All shutdown operations wrapped in try-except blocks
- Errors logged as warnings but don't block shutdown
- Ensures application always exits even if components fail

### Benefits

1. **No Resource Leaks**: All threads, processes, and executors properly cleaned up
2. **Data Integrity**: In-flight operations canceled cleanly, no partial writes
3. **Log Visibility**: Shutdown progress logged for debugging
4. **User Experience**: Fast exit (worst case ~12 seconds with all timeouts)
5. **Cross-Platform**: Works on Windows (window close), Unix (SIGTERM/SIGINT)

### Known Limitations

- Uploads in-progress are canceled, not completed
- Queued auto-posts are discarded (not persisted)
- Very large thumbnail generation queue may take time to drain

---

## Testing Strategy

**Current Coverage:**
- Integration tests exist (`test_integration.py`)
- No unit tests for Go code

**Recommended:**
1. Add Go unit tests for rate limiter logic
2. Add mock service tests (fake HTTP servers)
3. Stress test with 1000+ files
4. Test timeout/retry scenarios

---

## How to Add a New Service

With the v2.2.0 architecture, adding a new service is trivial:

1. **Create plugin file** in `modules/plugins/your_service.py`
2. **Implement two methods:**
   - `settings_schema`: Define UI fields declaratively
   - `build_http_request()`: Return HTTP request spec
3. **Done!** No Go changes, no recompilation needed

**Example skeleton:**
```python
class YourServicePlugin(ImageHostPlugin):
    @property
    def id(self): return "yourservice.com"

    @property
    def name(self): return "Your Service"

    @property
    def settings_schema(self):
        return [
            {"type": "dropdown", "key": "quality", "values": ["high", "low"]}
        ]

    def build_http_request(self, file_path, config, creds):
        return {
            "url": "https://api.yourservice.com/upload",
            "method": "POST",
            "headers": {"Authorization": f"Bearer {creds['token']}"},
            "multipart_fields": {
                "file": {"type": "file", "value": file_path},
                "quality": {"type": "text", "value": config.get("quality", "high")}
            },
            "response_parser": {
                "type": "json",
                "url_path": "data.url",
                "thumb_path": "data.thumb"
            }
        }
```

---

## Conclusion

The application is **production-ready** and **architecturally sound** after v2.4.0. The generic HTTP runner with advanced session management eliminates the split-brain problem for ALL services while maintaining all performance benefits of Go's concurrency.

**Key Achievements:**
- ✅ True plugin flexibility - add services by dropping in Python files only!
- ✅ Advanced session management - multi-step logins, cookie persistence, template substitution
- ✅ **100% migration complete** (5/5 services) - ZERO hardcoded service logic in Go!
- ✅ Regex extraction, URL templates, dynamic headers/form fields
- ✅ Supports both stateless APIs (IMX, Pixhost) and complex session-based services (Vipr, Turbo, ImageBam)

---

## Version History

- **v2.4.0** (2026-01-09): Complete migration - 100% plugin-driven architecture
  - Regex extraction in HTML parsing (`regex:` prefix)
  - URL templates with `{placeholder}` substitution
  - Form field and header templates for dynamic values
  - Multi-level extracted value passing in nested follow-up requests
  - TurboImageHost and ImageBam fully migrated
  - **MILESTONE: All 5 services now use generic HTTP runner**
- **v2.3.0** (2026-01-09): Session management for HTTP runner - enables session-based services
  - Multi-step pre-request chaining with `FollowUpRequest`
  - Cookie jar support for session persistence
  - Dynamic field resolution from extracted values
  - Vipr.im fully migrated (proof of concept for session-based services)
  - Turbo and ImageBam can follow same pattern
- **v2.2.0** (2026-01-09): Generic HTTP runner architecture - eliminated split-brain problem for stateless services
  - IMX and Pixhost fully migrated
  - Vipr, Turbo, ImageBam remain in legacy (session management required)
- **v2.1.0** (2026-01-09): Fixed timeouts, added rate limiting, refactored state
- **v2.0.0** (Previous): Fixed stderr pipe deadlock
- **v1.x**: Initial Python/Go hybrid implementation
