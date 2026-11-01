"""Request Dependabot auto-merge after both complete workflows pass."""
import json
import os
import re
import subprocess


def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', path], text=True, encoding="utf-8"))


def eligible(pr, runs, sha):
    if (pr['user']['login'] != 'dependabot[bot]' or pr['draft'] or
            pr['head']['sha'] != sha or pr['head']['repo']['full_name'] != pr['base']['repo']['full_name']):
        return False
    types = re.findall(r'update-type:\s*(version-update:semver-\w+)', pr.get('body') or '')
    if not types or any(t not in ('version-update:semver-patch', 'version-update:semver-minor') for t in types):
        return False
    for name in ('CI - Build and Test', 'Security Scanning'):
        matching = [r for r in runs if r['name'] == name and r['head_sha'] == sha and r['event'] == 'pull_request']
        if not matching:
            return False
        latest = max(matching, key=lambda r: r['id'])
        if latest['status'] != 'completed' or latest['conclusion'] != 'success':
            return False
    return True


def main():
    repo, sha = os.environ['GH_REPO'], os.environ['CHECKED_SHA']
    runs = api(f'repos/{repo}/actions/runs?head_sha={sha}&per_page=100')['workflow_runs']
    for pr in api(f'repos/{repo}/pulls?state=open&per_page=100'):
        if eligible(pr, runs, sha):
            subprocess.run(['gh', 'pr', 'merge', str(pr['number']), '--auto', '--squash',
                            '--match-head-commit', sha], check=True)


if __name__ == '__main__':
    main()
