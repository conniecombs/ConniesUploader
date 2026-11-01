"""Repair Go vulnerability findings without guessing versions or hiding failures."""
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def findings(output):
    """govulncheck emits a stream of JSON objects, not a JSON array."""
    decoder = json.JSONDecoder()
    result = {}
    while output.strip():
        item, end = decoder.raw_decode(output.lstrip())
        output = output.lstrip()[end:]
        finding = item.get("finding", {})
        version = finding.get("fixed_version", "")
        for frame in finding.get("trace", [])[:1]:
            module = frame.get("module", "")
            if module not in ("stdlib", "toolchain") and re.fullmatch(r"[A-Za-z0-9._~+/-]+", module) and re.fullmatch(r"v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", version):
                previous = result.get(module)
                # Advisories can list several fixes for the same module.
                key = lambda value: tuple(int(n) for n in value[1:].split('-')[0].split('.'))
                if previous is None or key(version) > key(previous):
                    result[module] = version
    return [f"{module}@{version}" for module, version in sorted(result.items())]


def main():
    backend = ROOT / "backend"
    subprocess.run(["go", "mod", "tidy"], cwd=backend, check=True)
    scan = subprocess.run(["govulncheck", "-json", "./..."], cwd=backend,
                          capture_output=True, text=True, encoding="utf-8")
    if scan.returncode not in (0, 3):
        raise RuntimeError(scan.stderr or "govulncheck could not complete")
    fixes = findings(scan.stdout)
    if fixes:
        subprocess.run(["go", "get", *fixes], cwd=backend, check=True)
        subprocess.run(["go", "mod", "tidy"], cwd=backend, check=True)
    # A missing upstream fix or a failed repair must remain a failure.
    subprocess.run(["govulncheck", "./..."], cwd=backend, check=True)
    subprocess.run(["go", "test", "./..."], cwd=backend, check=True)
    subprocess.run(["go", "vet", "./..."], cwd=backend, check=True)


if __name__ == "__main__":
    main()
