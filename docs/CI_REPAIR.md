# CI repair automation

The local implementation fixes GO-2026-6860 with x/net v0.62.0 and runs real
PyInstaller packaging on Windows, Linux, and macOS for every CI candidate.
Release builds use the same packaging script, including archive inspection for
the Go sidecar. The Security Scan Summary now fails when a scanner fails.

## Automatic recovery

`repair.yml` retries failed default-branch jobs once. If that retry still fails,
it attempts dependency repairs. It also checks daily and supports manual dispatch.
It always checks out the default branch, never code from the triggering PR.

The repair script obtains fixed Go module versions from govulncheck JSON, runs
Go module tidy, tests and vet, and rescans. pip-audit repairs Python requirements,
then the workflow installs and tests them. Failures stop the workflow. The only
files permitted in the repair PR are go.mod, go.sum and frontend/requirements.txt.
There is one reusable branch, `connie/automated-ci-repair`.

The verifier explicitly dispatches both CI and Security Scanning on the repair
branch, waits for success, checks that both the candidate and base commit remain
unchanged, and requests a normal squash auto-merge for that exact head. It never
uses an administrator bypass. Existing required reviews and rulesets still apply.
Separate vulnerability jobs remain in CI and Security Scanning to preserve
existing required check names. CI scan installation and execution have distinct names.
Dependabot patch/minor auto-merge now waits for successful CI and Security Scanning
runs for the current PR head. Major upgrades remain manual.

## Activation after pushing

1. Merge these files into the default branch.
2. Enable Actions permission to create pull requests in repository settings.
3. Enable auto-merge and configure required CI/security/packaging checks with
   "Require branches to be up to date before merging" so a queued merge cannot
   use checks against an obsolete base. Required human reviews will intentionally
   prevent unattended merging.
4. For fully unattended PR-triggered checks, install a GitHub App on this repo
   with contents, pull requests and actions read/write permissions. Set variable
   `CI_REPAIR_APP_ID` and secret `CI_REPAIR_APP_PRIVATE_KEY`; the workflow creates
   a fresh short-lived token each run. Alternatively supply a fine-grained token
   as `CI_REPAIR_TOKEN`. The default GITHUB_TOKEN can dispatch checks, but GitHub
   may require approval for PR events it creates.
5. Dispatch Automated CI Repair once and inspect the end-to-end result.

No remote settings, secrets, branches, or PRs are changed by installing these
files locally. The local Windows package test does not replace the Linux/macOS
runner builds. Changes to published releases require a new deliberate release.

## Limits and unresolved failures

The workflow cannot invent upstream security fixes, correct arbitrary application
logic, restore unavailable credentials/services, or bypass repository policy.
It does not suppress tests or security findings. An unsuccessful repair leaves a
failed Actions run and explanatory summary; a new upstream fix is reconsidered on
the next daily run. It does not automatically publish releases or repair PR source
code. Dependabot remains responsible for routine dependency and action upgrades.

Scanner versions are pinned for reproducibility; update their pins in CI,
security and repair workflows together when upgrading them.
