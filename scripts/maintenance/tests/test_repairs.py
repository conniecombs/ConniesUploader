import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


repair = load("repair_dependencies")
verify = load("verify_repair")
dependabot = load("merge_dependabot")


class RepairTests(unittest.TestCase):
    def test_dependabot_requires_both_current_successful_workflows(self):
        pr = {'user': {'login': 'dependabot[bot]'}, 'draft': False,
              'head': {'sha': 'sha', 'repo': {'full_name': 'owner/repo'}},
              'base': {'repo': {'full_name': 'owner/repo'}},
              'body': 'update-type: version-update:semver-minor'}
        runs = [{'id': i, 'name': name, 'head_sha': 'sha', 'event': 'pull_request',
                 'status': 'completed', 'conclusion': 'success'} for i, name in enumerate(
                     ['CI - Build and Test', 'Security Scanning'])]
        self.assertTrue(dependabot.eligible(pr, runs, 'sha'))
        self.assertFalse(dependabot.eligible(pr, runs[:1], 'sha'))
        self.assertFalse(dependabot.eligible(pr, runs, 'stale'))
        runs[1]['conclusion'] = 'failure'
        self.assertFalse(dependabot.eligible(pr, runs, 'sha'))
        runs[1]['conclusion'] = 'success'
        pr['body'] = 'update-type: version-update:semver-major'
        self.assertFalse(dependabot.eligible(pr, runs, 'sha'))

    def test_advisories_choose_highest_fix_and_ignore_toolchain(self):
        def finding(module, version):
            return json.dumps({"finding": {"fixed_version": version, "trace": [{"module": module}]}})
        stream = '\n'.join([finding('golang.org/x/net', 'v0.62.0'),
                            finding('golang.org/x/net', 'v0.61.0'),
                            finding('stdlib', 'v1.26.10'), finding('example.org/m', '')])
        self.assertEqual(repair.findings(stream), ['golang.org/x/net@v0.62.0'])

    def test_invalid_report_does_not_pass(self):
        with self.assertRaises(ValueError):
            repair.findings('network error')

    def test_tool_failure_does_not_become_clean_scan(self):
        with patch.object(repair.subprocess, 'run', side_effect=[None, subprocess.CompletedProcess([], 1, '', 'offline')]):
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                repair.main()

    def exercise_verifier(self, *, changed=False, disallowed=False, failed=False):
        calls = []
        read_count = 0
        run_count = {}
        def gh(*args):
            nonlocal read_count
            calls.append(args)
            if args[0] != 'api':
                return ''
            endpoint = args[1]
            if '/files?' in endpoint:
                return json.dumps([{'filename': '.github/workflows/ci.yml' if disallowed else 'backend/go.mod'}])
            if '/runs?' in endpoint:
                run_count[endpoint] = run_count.get(endpoint, 0) + 1
                return json.dumps({'workflow_runs': [] if run_count[endpoint] == 1 else [{'id': 10, 'head_sha': 'candidate'}]})
            read_count += 1
            return json.dumps({'head': {'sha': 'candidate', 'ref': 'connie/automated-ci-repair', 'repo': {'full_name': 'owner/repo'}},
                               'base': {'sha': 'moved' if changed and read_count > 1 else 'base'}, 'changed_files': 1})
        with patch.dict(verify.os.environ, {'GH_REPO': 'owner/repo', 'REPAIR_PR': '1'}), patch.object(verify, 'gh', gh), patch.object(verify.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'gh') if failed else None):
            if changed or disallowed or failed:
                with self.assertRaises((RuntimeError, subprocess.CalledProcessError)):
                    verify.main()
                self.assertFalse(any(c[:2] == ('pr', 'merge') for c in calls))
            else:
                verify.main()
                self.assertIn(('pr', 'merge', '1', '--auto', '--squash', '--match-head-commit', 'candidate'), calls)

    def test_success_merges_verified_head(self):
        self.exercise_verifier()

    def test_changed_base_blocks_merge(self):
        self.exercise_verifier(changed=True)

    def test_unexpected_file_blocks_merge(self):
        self.exercise_verifier(disallowed=True)

    def test_failed_workflow_blocks_merge(self):
        self.exercise_verifier(failed=True)


if __name__ == '__main__':
    unittest.main()
