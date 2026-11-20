# Release Notes - v3.2.0 "Reliable Uploads & Python-Owned Parsing"

**Release Date**: November 20, 2026
**Git Tag**: `v3.2.0`
**Previous Version**: `v3.1.3`

## Overview

v3.2.0 fixes the 40 bugs a full bug hunt found in v3.1.3, plus the defects four follow-up code reviews found in those fixes and in the new upload parsing. It also moves upload sessions and upload-result parsing from the Go sidecar into the Python host plugins, as planned in [`V3_2_0_PYTHON_UPLOAD_PARSING_DESIGN.md`](../plans/V3_2_0_PYTHON_UPLOAD_PARSING_DESIGN.md). The full list is in the [changelog](../CHANGELOG.md).

## Highlights

- **Python-owned upload parsing.** All six hosts (IMX, Pixhost, Imgur, Vipr, TurboImageHost and ImageBam) log in, build upload requests, and read the host's answer in their Python plugins, with the same results as before on recorded host responses. Wrong passwords and refused uploads now show the host's own message. The sidecar opens isolated transport sessions, streams files, and hands back the raw response. A row shows "Processing" while the answer is read.
- **Uploads you can trust.** Rejected uploads or uploads without a link are marked Failed with the host's reason, never "Uploaded". TurboImageHost and ImageBam links always belong to the right file. A lost reply no longer creates a duplicate image, and large uploads on slow connections are no longer cut off after 3 minutes.
- **Stop, Clear List and crashes always finish.** A sidecar crash, Remove Batch, Clear List or a lost status can no longer leave an upload stuck on "Uploading", and Start after Clear List uploads the new files only.
- **Output that is never lost.** Same-named batches no longer overwrite each other's output. Finished batches produce output again after images are added or failed ones removed. `#direct_url#` is a real image link.
- **Templates behave as documented.** The editor saves the template being edited, HTML and Markdown custom templates keep their format, and conditions, loops and separators render correctly. Two windows no longer erase each other's templates.
- **Galleries and settings stay separate per host.** A gallery chosen for one host is never used for another, Gallery Manager picks follow the gallery field, and a damaged settings file is repaired instead of reset.
- **Security.** The IMX API key is no longer written to the settings file (old copies are removed), and error messages hide credentials and session values.

## Before you tag: live-host checklist

The new parsing path is verified against recorded host responses and local fake hosts, not against the live sites. Before tagging `v3.2.0`, run the checklist in §5 of the design doc for each host. The design doc also lists per-host notes and the assumptions the fixtures could not prove (for example how Vipr, Turbo and ImageBam show a refused login):

1. upload without login (where the host allows it);
2. log in and upload;
3. upload five files with Thread Limit 3;
4. create a gallery during upload;
5. try a wrong password;
6. press Stop mid-batch.

If a host fails the checklist, set `"legacy_upload_parsing": true` in `user_settings.json` to send every host through the previous Go parsing while the plugin is fixed. In code, a single host is kept on the legacy path by removing its `parse_upload_response`.

## Upgrade notes

- **IMX API key:** the key saved in `user_settings.json` by earlier versions is removed on first start; the key in the system keyring is unchanged.
- **Turbo thumbnail size:** a saved TurboImageHost thumbnail size of 180, which Turbo does not offer, becomes 200.
- **ImageBam gallery ID:** ImageBam now has its own gallery ID setting (`imagebam_gallery_id`). A gallery ID entered for another host is no longer reused.
- **Built-in templates:** built-ins can no longer be deleted or renamed; duplicate them to customise.
- **ImageBam upload order:** files in one ImageBam session now upload one at a time, so each file's link can be matched to it.

## Verification

```bash
cd frontend
python -m pytest tests -q
black --check .
flake8 main.py modules/ --max-line-length=120 --ignore=E203,E501,W503 --exclude=__pycache__
cd ../backend
go vet ./...
go test -race ./...
cd ..
python -m unittest discover -s scripts/maintenance/tests
```

## Not in this release

- Removing the legacy Go upload hooks (`pre_request`, `response_parser`, `resolve_spec`, `dynamic` fields and upload-time `{token}` substitution), milestone M5. The design keeps them until a release has shipped with the Python path and no parsing regressions.

## Download

**[Download v3.2.0](https://github.com/conniecombs/ConniesUploader/releases/tag/v3.2.0)**

Expected artifacts:

- `ConniesUploader-v3.2.0-windows-x64.zip`
- `ConniesUploader-v3.2.0-linux-x64.tar.gz`
- `ConniesUploader-v3.2.0-macos-arm64.zip`

Each artifact includes a SHA256 checksum.
