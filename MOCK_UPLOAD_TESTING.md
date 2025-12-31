# Mock Upload Testing - User Guide

## Overview

The Mock Upload Test Program provides comprehensive testing of the plugin system with simulated uploads. No actual uploads are performed - everything is mocked for safe, fast testing.

**File**: `tests/test_mock_uploads.py`

---

## Features

### ✅ Complete Plugin Testing
- Tests all 6 plugins (Pixhost, IMX, Turbo, ImageBam, Imgur, Vipr)
- Validates metadata completeness
- Tests schema structure
- Validates configuration
- Simulates full upload workflow

### ✅ Mock Upload Simulation
- Realistic upload responses for each service
- Progress callback testing
- Multi-file upload simulation
- Gallery/album testing

### ✅ Helper Function Integration
- Tests helper functions in action
- Validates helper usage across plugins
- Demonstrates code reduction benefits

### ✅ Flexible Testing Modes
- Quick mode for fast validation
- Verbose mode for detailed output
- Single plugin testing
- Full suite testing

---

## Usage

### Basic Usage

```bash
# Run complete test suite
python tests/test_mock_uploads.py

# Quick test (minimal output)
python tests/test_mock_uploads.py --quick

# Verbose test (detailed output)
python tests/test_mock_uploads.py --verbose
```

### Test Specific Plugin

```bash
# Test only Pixhost
python tests/test_mock_uploads.py --plugin pixhost.to

# Test only Imgur
python tests/test_mock_uploads.py --plugin imgur.com

# Test with verbose output
python tests/test_mock_uploads.py --plugin turboim agehost.com --verbose
```

### Command Line Options

| Option | Short | Description |
|--------|-------|-------------|
| `--plugin PLUGIN` | | Test specific plugin only |
| `--verbose` | `-v` | Detailed output with progress bars |
| `--quick` | `-q` | Quick mode with minimal output |
| `--help` | `-h` | Show help message |

---

## Sample Output

### Quick Mode (Default)

```
======================================================================
            Plugin System Mock Upload Test Suite
======================================================================

──────────────────────────────────────────────────────────────────────
  Testing Plugin Discovery
──────────────────────────────────────────────────────────────────────
  ✓ Loaded 6 plugins
    • Pixhost (pixhost.to)
    • IMX.to (imx.to)
    • TurboImageHost (turboimagehost.com)
    • ImageBam.com (imagebam.com)
    • Imgur (imgur.com)
    • Vipr (vipr.im)

──────────────────────────────────────────────────────────────────────
  Testing Helper Function Integration
──────────────────────────────────────────────────────────────────────
  ✓ validate_cover_count: cover_limit = 5
  ✓ is_cover_image: /a.jpg = True, /c.jpg = False
  ✓ normalize_boolean('yes') = True
  ✓ normalize_int('42') = 42

══════════════════════════════════════════════════════════════════════
                        Testing: Pixhost
══════════════════════════════════════════════════════════════════════

──────────────────────────────────────────────────────────────────────
  Testing Pixhost Validation
──────────────────────────────────────────────────────────────────────
  ✓ Configuration valid
    • cover_count converted to: 2

──────────────────────────────────────────────────────────────────────
  Testing Pixhost Mock Upload
──────────────────────────────────────────────────────────────────────
  Group: Group: Test Gallery - Pixhost (5 files)
  Files: 5
  Uploading 1/2: image_1.jpg... ✓
  Uploading 2/2: image_2.jpg... ✓

  ✓ Upload complete: 2/2 successful

[... similar output for other plugins ...]

======================================================================
                     Test Results Summary
======================================================================
  Total Tests: 24
  Passed: 24
  Failed: 0
  Success Rate: 100.0%

  Plugin Results:
    ✓ Pixhost               4/4 tests passed
    ✓ IMX.to                4/4 tests passed
    ✓ TurboImageHost        4/4 tests passed
    ✓ ImageBam.com          4/4 tests passed
    ✓ Imgur                 4/4 tests passed
    ✓ Vipr                  4/4 tests passed
```

### Verbose Mode

```bash
python tests/test_mock_uploads.py --plugin pixhost.to --verbose
```

```
──────────────────────────────────────────────────────────────────────
  Testing Pixhost Metadata
──────────────────────────────────────────────────────────────────────
  ✓ version: 2.0.0
  ✓ author: Connie's Uploader Team
  ✓ description: Upload images to Pixhost.to with gallery support
  ✓ implementation: python

  Features:
    • galleries: True
    • covers: True
    • authentication: optional

──────────────────────────────────────────────────────────────────────
  Testing Pixhost Schema
──────────────────────────────────────────────────────────────────────
  ✓ Schema has 6 fields
    1. Type: dropdown      Key: content_type        Label: Content Type
    2. Type: dropdown      Key: thumbnail_size      Label: Thumbnail Size
    3. Type: inline_group  Key: N/A                 Label: N/A
    4. Type: checkbox      Key: save_links          Label: Save Links.txt
    5. Type: separator     Key: N/A                 Label: N/A
    ... and 1 more fields

──────────────────────────────────────────────────────────────────────
  Testing Pixhost Mock Upload
──────────────────────────────────────────────────────────────────────
  Group: Group: Test Gallery - Pixhost (5 files)
  Files: 5

  Uploading: image_1.jpg
  Size: 512KB
  Progress: [██████████████████████████████] 100.0%
  Result: ✓ https://pixhost.to/show/abc13def

  Uploading: image_2.jpg
  Size: 1024KB
  Progress: [██████████████████████████████] 100.0%
  Result: ✓ https://pixhost.to/show/abc13def

  ✓ Upload complete: 2/2 successful
```

---

## What Gets Tested

### 1. Plugin Discovery
- Automatic plugin loading
- Plugin count verification
- Load error detection

### 2. Plugin Metadata
- Required fields present (version, author, description, implementation)
- Features structure
- Credentials configuration
- Limits specification

### 3. Plugin Schema
- Schema structure validation
- Field types checking
- Key/label presence
- Standard key usage

### 4. Configuration Validation
- Config validation logic
- Helper function integration (validate_cover_count, etc.)
- Error reporting

### 5. Mock Upload Workflow
- File creation
- Group creation
- Progress callbacks
- Upload simulation
- Result validation

### 6. Helper Functions
- validate_cover_count()
- is_cover_image()
- normalize_boolean()
- normalize_int()
- And more...

---

## Mock Data

### Mock Files
```python
MockFile(
    path="/mock/path/image_1.jpg",
    name="image_1.jpg",
    size=512 * 1024  # 512KB
)
```

### Mock Groups
```python
MockGroup(
    title="Test Gallery - Pixhost",
    files=["/mock/path/image_1.jpg", "/mock/path/image_2.jpg", ...],
    auto_gallery=True
)
```

### Mock Upload Responses
Each plugin returns realistic mock responses:

**Pixhost**:
- Viewer: `https://pixhost.to/show/abc123def`
- Thumb: `https://t0.pixhost.to/thumbs/abc123def/test.jpg`

**Imgur**:
- Viewer: `https://imgur.com/abc123XYZ`
- Thumb: `https://i.imgur.com/abc123XYZm.jpg`

**TurboImageHost**:
- Viewer: `https://www.turboimagehost.com/p/turbo123`
- Thumb: `https://www.turboimagehost.com/th/turbo123.jpg`

---

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: Plugin Mock Upload Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - run: pip install -r requirements.txt
      - run: python tests/test_mock_uploads.py --quick
```

---

## Exit Codes

- `0` - All tests passed
- `1` - One or more tests failed

Perfect for CI/CD integration:
```bash
python tests/test_mock_uploads.py && echo "Success!" || echo "Failed!"
```

---

## Advanced Usage

### Testing During Development

```bash
# Quick validation after changes
python tests/test_mock_uploads.py --quick

# Detailed test of specific plugin
python tests/test_mock_uploads.py --plugin pixhost.to --verbose

# Full regression test
python tests/test_mock_uploads.py --verbose
```

### Pre-Commit Testing

```bash
#!/bin/bash
# .git/hooks/pre-commit

echo "Running plugin tests..."
python tests/test_mock_uploads.py --quick || exit 1
echo "Tests passed!"
```

---

## Architecture

### Components

```
test_mock_uploads.py
├── MockFile           - Simulates file objects
├── MockGroup          - Simulates upload groups
├── MockUploadResult   - Simulates upload responses
├── MockUploadResponses - Service-specific responses
├── MockUploadSimulator - Upload simulation engine
└── PluginTestRunner   - Main test orchestrator
```

### Test Flow

```
1. Load Plugins (PluginManager)
   ↓
2. Test Metadata (validate_configuration)
   ↓
3. Test Schema (settings_schema)
   ↓
4. Create Mock Data (MockGroup, MockFile)
   ↓
5. Simulate Upload (MockUploadSimulator)
   ↓
6. Validate Results (MockUploadResult)
   ↓
7. Generate Report (PluginTestRunner)
```

---

## Benefits

### ✅ Safe Testing
- No actual uploads performed
- No API keys required
- No rate limiting concerns

### ✅ Fast Testing
- Instant responses
- No network latency
- Parallel execution possible

### ✅ Comprehensive Coverage
- All 6 plugins tested
- All helper functions tested
- Full workflow simulation

### ✅ Developer Friendly
- Clear output
- Verbose mode for debugging
- Exit codes for automation

### ✅ CI/CD Ready
- Fast execution (~2 seconds)
- Deterministic results
- No external dependencies

---

## Troubleshooting

### Import Errors

```bash
# Ensure you're in the project root
cd /path/to/GolangVersion

# Run from project root
python tests/test_mock_uploads.py
```

### Plugin Not Found

```bash
# Check plugin ID (use exact ID)
python tests/test_mock_uploads.py --plugin pixhost.to  # Correct
python tests/test_mock_uploads.py --plugin pixhost     # Wrong
```

### Module Not Found

```bash
# Install dependencies
pip install -r requirements.txt

# Verify Python version
python --version  # Should be 3.8+
```

---

## Future Enhancements

Potential additions:
- Performance benchmarking
- Network failure simulation
- Rate limit testing
- Schema rendering tests
- UI integration tests

---

## Summary

The Mock Upload Test Program provides:
- ✅ Complete plugin system testing
- ✅ Safe mock upload simulation
- ✅ Fast, deterministic results
- ✅ CI/CD integration ready
- ✅ Developer-friendly output

Perfect for:
- Pre-commit validation
- CI/CD pipelines
- Plugin development
- Regression testing
- Release verification

---

*Mock Upload Testing Guide*  
*Version: 1.0*  
*Last Updated: 2025-12-31*
