"""Build the same desktop package in CI and release workflows."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    sidecar = "uploader.exe" if os.name == "nt" else "uploader"
    subprocess.run(["go", "build", "-trimpath", "-ldflags=-s -w", "-o",
                    str(ROOT / sidecar), "."], cwd=ROOT / "backend", check=True)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--noupx",
               "--onefile", "--noconsole", "--name", "ConniesUploader",
               "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"),
               "--specpath", str(ROOT / "packaging"),
               "--add-binary", f"{ROOT / sidecar}{os.pathsep}.",
               "--add-data", f"{ROOT / 'packaging/logo.ico'}{os.pathsep}.",
               "--additional-hooks-dir", str(ROOT / "packaging/pyinstaller_hooks"),
               "--collect-all", "tkinterdnd2", "--collect-all", "customtkinter",
               "--collect-submodules", "modules.plugins"]
    if os.name == "nt":
        command += ["--icon", str(ROOT / "packaging/logo.ico")]
    subprocess.run(command + ["main.py"], cwd=ROOT / "frontend", check=True)
    from PyInstaller.archive.readers import CArchiveReader
    binary = ROOT / "dist" / ("ConniesUploader.exe" if os.name == "nt" else "ConniesUploader")
    archive = CArchiveReader(str(binary))
    if sidecar not in archive.toc:
        raise RuntimeError(f"Package is missing {sidecar}")
    print(f"Verified package and embedded sidecar: {binary}")


if __name__ == "__main__":
    main()
