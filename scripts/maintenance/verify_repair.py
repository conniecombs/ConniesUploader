"""Dispatch complete checks and only merge the exact candidate they validated."""
import json
import os
import subprocess
import time


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True, encoding="utf-8").strip()


def main():
    repo, number = os.environ["GH_REPO"], os.environ["REPAIR_PR"]
    path = f"repos/{repo}/pulls/{number}"
    pr = json.loads(gh("api", path))
    sha, base = pr["head"]["sha"], pr["base"]["sha"]
    branch = pr["head"]["ref"]
    if branch != "connie/automated-ci-repair" or pr["head"]["repo"]["full_name"] != repo:
        raise RuntimeError("Unexpected repair branch")
    allowed = {"backend/go.mod", "backend/go.sum", "frontend/requirements.txt"}
    files = json.loads(gh("api", f"{path}/files?per_page=100"))
    if len(files) != pr["changed_files"] or not files or any(f["filename"] not in allowed for f in files):
        raise RuntimeError("Repair PR includes files outside the repair policy")
    runs = []
    for workflow in ("ci.yml", "security.yml"):
        endpoint = f"repos/{repo}/actions/workflows/{workflow}/runs?event=workflow_dispatch&branch={branch}&per_page=100"
        previous = {r["id"] for r in json.loads(gh("api", endpoint))["workflow_runs"]}
        gh("workflow", "run", workflow, "--ref", branch)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            candidates = [r for r in json.loads(gh("api", endpoint))["workflow_runs"]
                          if r["id"] not in previous and r["head_sha"] == sha]
            if candidates:
                runs.append(candidates[0]["id"])
                break
            time.sleep(10)
        else:
            raise RuntimeError(f"No dispatched run appeared for {workflow}")
    for run in runs:
        subprocess.run(["gh", "run", "watch", str(run), "--exit-status", "--interval", "15"], check=True)
    current = json.loads(gh("api", path))
    if current["head"]["sha"] != sha or current["base"]["sha"] != base:
        raise RuntimeError("Branch changed during validation; wait for the next repair run")
    # Normal merge honors rulesets and required reviews; no admin override.
    gh("pr", "merge", number, "--auto", "--squash", "--match-head-commit", sha)


if __name__ == "__main__":
    main()
