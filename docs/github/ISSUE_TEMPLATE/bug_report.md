---
name: Bug Report
about: Create a report to help us improve
title: '[BUG] '
labels: bug
assignees: ''
---

## Bug Description
A clear and concise description of what the bug is.

## Steps to Reproduce
Steps to reproduce the behavior:
1. Go to '...'
2. Click on '...'
3. Scroll down to '...'
4. See error

## Expected Behavior
A clear and concise description of what you expected to happen.

## Actual Behavior
A clear and concise description of what actually happened.

## Screenshots
If applicable, add screenshots to help explain your problem.

## Environment
**Desktop:**
 - OS: [e.g. Windows 10, Ubuntu 22.04, macOS 13]
 - App Version: [e.g. v3.0.0 or commit SHA]
 - Run Type: [Packaged release exe/app or source run with python main.py]
 - Python Version: [e.g. 3.11.9, if running from source or building locally]
 - Go Version: [e.g. 1.25.9 or 1.26.5, if running from source or building locally]
 - Build Command Used: [e.g. build_uploader.bat --clean, if this is a build/package issue]

**Upload Service:**
 - Service: [e.g. Pixhost, IMX, Turbo, Vipr, ImageBam, Imgur]
 - Account Type: [e.g. Free, Premium]

## Log Output
Please paste relevant output from `View > Execution Log`, the terminal, or `crash_log.log` here:
```
[Paste logs here]
```

For source-run sidecar issues, also include the output of:

```bash
python scripts/diagnostics/check_sidecar_location.py
```

## Additional Context
Add any other context about the problem here.

## Checklist
- [ ] I have searched existing issues to ensure this is not a duplicate
- [ ] I have read the [CONTRIBUTING.md](../../CONTRIBUTING.md) guidelines
- [ ] I have included all relevant information above
- [ ] I have attached logs/screenshots if applicable
