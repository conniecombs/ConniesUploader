"""Opt-in live check: create one IMX gallery with two synthetic images.

Run with the repository venv and --live. Loads the required IMX upload credentials
and API key from the OS keyring. Leaves the gallery for inspection; never deletes it.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import sys
import threading
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Authorize uploading two synthetic images to IMX",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required: this creates a real gallery on your IMX account")

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "frontend"))
    import keyring
    from PIL import Image, ImageDraw
    from modules.upload_manager import UploadManager
    from modules.imx_api import require_upload_credentials

    creds = {
        "imx_api": keyring.get_password("ImageUploader:imx_api_key", "api"),
        "imx_user": keyring.get_password("ImageUploader:imx_username", "user"),
        "imx_pass": keyring.get_password("ImageUploader:imx_password", "pass"),
    }
    require_upload_credentials(creds)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    class Group:
        title = f"ConniesUploader verification {stamp}"
        gallery_id = ""
        gallery_service = ""

    group = Group()
    group.files = []
    for index in (1, 2):
        path = output / f"imx-verification-{stamp}-{index}.png"
        canvas = Image.new("RGB", (480, 240), (28, 54, 80))
        ImageDraw.Draw(canvas).text(
            (32, 90),
            f"ConniesUploader gallery verification\nImage {index} of 2\n{stamp} UTC",
            fill="white",
        )
        canvas.save(path)
        group.files.append(str(path))

    progress, results = queue.Queue(), queue.Queue()
    manager = UploadManager(progress, results, threading.Event())
    records, errors = [], []
    completed = Counter()
    try:
        manager.start_batch(
            {group: group.files},
            {
                "service": "imx.to",
                "auto_gallery": True,
                "threads": 1,
                "imx_cover_count": 1,
            },
            creds,
        )
        deadline = time.monotonic() + 180
        while (
            len(records) < 2 or set(completed) != set(group.files)
        ) and time.monotonic() < deadline:
            try:
                path, url, thumbnail = results.get(timeout=0.5)
                records.append({"file": Path(path).name, "url": url, "thumbnail": thumbnail})
            except queue.Empty:
                pass
            while not progress.empty():
                kind, path, data = progress.get_nowait()
                if kind == "status":
                    if data == "Done":
                        completed[path] += 1
                    elif data == "Failed" or str(data).lower().startswith("error"):
                        errors.append(str(data))
            if errors:
                break
        report = {
            "gallery_name": group.title,
            "gallery_id": group.gallery_id,
            "gallery_url": getattr(group, "gallery_url", ""),
            "images": records,
            "completion_events": {Path(path).name: count for path, count in completed.items()},
            "errors": errors,
        }
        (output / f"imx-verification-{stamp}.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, indent=2), flush=True)
        if (
            errors
            or len(records) != 2
            or not all(item["url"] for item in records)
            or not group.gallery_id
            or completed != Counter(group.files)
        ):
            raise SystemExit(
                "Live verification incomplete. Inspect the report/account before retrying."
            )
    finally:
        manager.shutdown()
        manager.bridge.shutdown()


if __name__ == "__main__":
    main()
