# Contributing to Connie's Uploader Ultimate

Thank you for your interest in contributing! This document provides guidelines and information for contributors.

## Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Help maintain a welcoming environment

## Getting Started

### Development Setup

1. **Fork and clone the repository:**
```bash
git clone https://github.com/YOUR_USERNAME/ConniesUploader.git
cd ConniesUploader
```

2. **Set up Go development environment:**
```bash
go mod download
```

3. **Set up Python development environment:**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

4. **Build the Go backend:**
```bash
go build -o uploader .  # On Windows: uploader.exe
```

5. **Run the application:**
```bash
python main.py
```

## Project Structure

```
ConniesUploader/
├── main.py                 # Main application entry point
├── uploader.go            # Go backend for uploads
├── modules/               # Python modules
│   ├── api.py            # API interactions with Go backend
│   ├── config.py         # Application configuration
│   ├── controller.py     # Business logic controllers
│   ├── dnd.py           # Drag and drop functionality
│   ├── file_handler.py  # File operations and validation
│   ├── gallery_manager.py # Gallery management UI
│   ├── settings_manager.py # Settings persistence
│   ├── template_manager.py # Template system
│   ├── upload_manager.py # Upload orchestration
│   ├── utils.py         # Utility functions
│   ├── viper_api.py     # ViperGirls forum API
│   ├── widgets.py       # Custom UI widgets
│   └── plugins/         # Service-specific plugins
│       ├── base.py
│       ├── imx.py
│       ├── imagebam.py
│       ├── pixhost.py
│       ├── turbo.py
│       └── vipr.py
├── build_uploader.bat    # Windows build script
├── go.mod               # Go dependencies
├── requirements.txt     # Python dependencies
└── LICENSE             # MIT License
```

## How to Contribute

### Reporting Bugs

1. Check if the bug has already been reported in [Issues](https://github.com/conniecombs/conniesuploader/issues)
2. If not, create a new issue with:
   - Clear title and description
   - Steps to reproduce
   - Expected vs actual behavior
   - Screenshots if applicable
   - Your environment (OS, Python version, Go version)
   - Relevant logs from `crash_log.log` or execution log

### Suggesting Features

1. Check existing [Issues](https://github.com/conniecombs/conniesuploader/issues) for similar suggestions
2. Create a new issue with:
   - Clear description of the feature
   - Use case / motivation
   - Proposed implementation (if you have ideas)
   - Any relevant mockups or examples

### Pull Requests

1. **Create a feature branch:**
```bash
git checkout -b feature/your-feature-name
```

2. **Make your changes:**
   - Follow existing code style
   - Add comments for complex logic
   - Update documentation as needed

3. **Test your changes:**
   - Run the application and test affected features
   - Test on Windows if possible (primary platform)
   - Check for Python errors and Go compilation issues

4. **Commit your changes:**
```bash
git add .
git commit -m "Add feature: brief description"
```

5. **Push to your fork:**
```bash
git push origin feature/your-feature-name
```

6. **Create a Pull Request:**
   - Provide clear title and description
   - Reference any related issues
   - Explain what changed and why
   - Include screenshots for UI changes

## Coding Standards

### Python Code

- **Style**: Follow PEP 8
- **Imports**: Group standard library, third-party, and local imports
- **Naming**:
  - `snake_case` for functions and variables
  - `PascalCase` for classes
  - `UPPER_CASE` for constants
- **Documentation**: Add docstrings for complex functions
- **Error Handling**: Use try-except blocks appropriately

### Go Code

- **Style**: Follow Go conventions (use `gofmt`)
- **Naming**: Use Go naming conventions
- **Error Handling**: Always handle errors, don't ignore them
- **Comments**: Add comments for exported functions

### UI/UX Guidelines

- Maintain consistency with existing UI
- Test with both Light and Dark themes
- Ensure responsive layouts
- Provide user feedback for long operations
- Add helpful error messages

## Adding New Image Hosts

To add support for a new image hosting service:

1. **Create a plugin** in `modules/plugins/your_service.py`:
```python
from .base import BasePlugin

class YourServicePlugin(BasePlugin):
    def upload(self, file_path, config):
        # Implementation
        pass
```

2. **Add Go backend support** in `uploader.go`:
   - Add new case in `handleUpload()`
   - Implement `uploadYourService()` function
   - Add any required login/authentication functions

3. **Add UI components** in `modules/widgets.py`:
   - Create settings frame
   - Add configuration options

4. **Update configuration** in `modules/config.py`:
   - Add service-specific constants
   - Add keyring service names if needed

5. **Test thoroughly**:
   - Upload single files
   - Upload batches
   - Test gallery creation
   - Verify output formatting

## Testing

### Manual Testing Checklist

- [ ] Upload single file
- [ ] Upload multiple files
- [ ] Upload folder
- [ ] Create gallery
- [ ] Template output
- [ ] Retry failed uploads
- [ ] Settings persistence
- [ ] Credential storage
- [ ] Drag and drop
- [ ] Dark/Light mode switching
- [ ] ViperGirls posting (if applicable)

### Building for Testing

**Windows:**
```batch
build_uploader.bat
```

**Manual build:**
```bash
# Build Go backend
go build -ldflags="-s -w" -o uploader.exe .

# Build Python executable
pyinstaller --noconsole --onefile --clean --name "ConniesUploader" \
    --icon "logo.ico" \
    --add-data "uploader.exe;." \
    --add-data "logo.ico;." \
    --collect-all tkinterdnd2 \
    main.py
```

## Version Numbering

We follow [Semantic Versioning](https://semver.org/):

- **MAJOR** version: Incompatible API changes
- **MINOR** version: New features (backward-compatible)
- **PATCH** version: Bug fixes (backward-compatible)

Update version in `modules/config.py`:
```python
APP_VERSION = "X.Y.Z"
```

## Documentation

When making changes:

- Update README.md if you add features or change usage
- Update CHANGELOG.md with your changes
- Add comments for complex code
- Update docstrings if you change function behavior

## Questions?

- Open an issue for questions
- Check existing issues and pull requests
- Review the code and comments

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing to Connie's Uploader Ultimate! 🎉
