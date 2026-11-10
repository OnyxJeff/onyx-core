# ONYX CORE v0.7.0 — Milestone 5, Step 2: release context contract

**Status: development-only specification and offline tests. NOT a deployable release, installer, or permission to run live probes.**

**Source baseline:** Checkpoint K `49ebccf9296ba81d3b85d5dcb840f305998ae9c7`. Existing production at v0.6.0 remains unchanged.

## Intent and scope

The source audit identified a release blocker: the live incident bridge, PowerShell cycle runner, evidence collector, and both operator CLIs intentionally reject any context other than the isolated v0.7.0 development branch and fixed v0.6.0 production HEAD. Removing those guards without a replacement would undermine the read-only boundary.

This step introduces **`OnyxReleasePolicy.py`**, a pure, no-probe release policy checker, plus a proposed **`monitoring.release.example.json`**. It does **not** alter or enable any live call path. These new files are a testable contract for the next integration step. Existing development guards are retained and continue to block release-mode execution at Checkpoint K.

For now, the release scope is explicitly **manual, operator-authorized read-only USB/ICS diagnostics and stored incident history**. There is **no unattended monitoring, auto-detection between manual invocations, schedule, task installation, or automatic ICS repair**. The configuration field `monitoring_interval_seconds` remains validated but not acted on by this release scope. An unattended monitor would require a separate approved implementation and acceptance tests.

## Two distinct runtime contexts

| Requirement | Development (existing) | Proposed release (not enabled yet) |
|---|---|---|
| Repository | `D:\github_repos\onyx-core-v070` | `D:\github_repos\onyx-core` |
| Git branch | `feature/v0.7.0-monitoring` | `main` |
| Configuration profile | `development` | `release` |
| Configuration filename | `monitoring.development.example.json` | `monitoring.release.example.json` |
| State directory | `%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring` | `%LOCALAPPDATA%\OnyxCore-v070-Release\Monitoring` |
| Private SSH identity | `%USERPROFILE%\.ssh\onyxcore_monitor_ed25519` | Same restricted, forced-command identity |
| Repair action | `None` | `None`, mandatory |
| Scheduling | Not provided | Not provided |

The release contract must **not** depend on the old v0.6.0 HEAD or the untracked protected collector backup. It still needs a separate, verifiable Git/source/ACL/install contract before production launch can be enabled. Checking branch name alone is not sufficient, and SHA-256 over the incident store detects corruption but is not file authentication.

**No implicit migration:** The proposed release state directory is deliberately separate from both the existing development generation-2 incident store and any v0.6.0 operational files. It must not be initialized, cleared, migrated, or recreated as part of this step. Before any future first live release cycle, the operator must explicitly verify backup/restore and marker/store state and authorize a one-time initialization; a missing store after an initialized marker must fail closed.

## Safety contract for future integration

- `status` and `report` are exclusively **read-only stored-data operations**. They reject a live-probe flag or initialization. They must never create a directory or incident store.
- A `one-shot-cycle` requires a separate **explicit live-read-only authorization**, and the existing pre-probe integrity and nonblocking cycle lock must remain in force. This contract is not itself authorization to run such a cycle.
- All operations reject automatic repair, scheduling, unexpected root/branch, and unrecognized fields.
- The proposed release configuration reuses the exact strict field schema enforced by the development validator, with only `profile` and `state_dir` adjusted **for offline validation only**. Nothing passes this substituted development config to a live caller.
- The eventual release preflight must separately enforce approved Windows executable paths, configuration file and state ACLs, no redirected/junction/reparse-point paths, approved SSH key and strict host-key verification, correct Windows adapter/receiver targets, source integrity, no repair code path, and a documented rollback.
- The Python policy deliberately returns `runtime_enabled: false` and `requires_runtime_preflight: true`. A passing offline policy result is **not** a production-ready indication.

## Offline validation

These checks are permitted on SQUALL's **development** worktree after the Step 2 ZIP is verified and extracted:

```powershell
$Dev = 'D:\github_repos\onyx-core-v070'
$Python = 'C:\Python313\python.exe'

& $Python (Join-Path $Dev 'windows\monitoring\OnyxReleasePolicy.py') `
    --check (Join-Path $Dev 'windows\monitoring\monitoring.release.example.json')

Push-Location $Dev
try {
    & $Python -m unittest discover -s tests\monitoring `
        -p 'test_release_policy.py' -v
    & $Python -m unittest discover -s tests\monitoring `
        -p 'test_*.py' -q
}
finally { Pop-Location }
```

Expected: **31** new test cases; **266** total monitoring cases on SQUALL (two Windows symlink tests may still skip). All test scenarios are offline and only use disposable temporary files. No live runner, SSH, receiver, PowerShell network probe, monitoring task or persistent store is invoked.

## Remaining gates (not satisfied by this patch)

1. Wire a **real, independently validated** release context into the evidence collector, cycle runner, live bridge and operator entry points; continue to default to development policy unless an explicit reviewed release mode is selected. Do not add a switch that bypasses all checks.
2. Add release-mode and negative-path tests for all launchers, with no actual network probes during tests; keep development tests green.
3. Create the approved, SQUALL-specific manual setup/preflight, retention, backup, restoration and rollback procedure. Record which adapter, receiver address, Python/SSH binaries and user account were verified.
4. Run the complete Windows release-candidate regression matrix and a separately authorized **manual read-only** test only after a release-context gate has passed. Do not merge, deploy, schedule, or tag before explicit approval.

**This patch adds four files only. It does not modify production, existing development code, the saved incident store, or the protected collector backup.**
