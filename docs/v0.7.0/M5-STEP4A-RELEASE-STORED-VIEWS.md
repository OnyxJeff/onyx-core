# ONYX CORE v0.7.0 — M5 Step 4A: Release stored-view integration

**Status:** candidate integration; offline validation only. **Not approved for deployment or merge.**

**Development baseline:** Checkpoint L `1a17adbcaa6a64047f4b7bca58ff975bcc83f8a5` (12 commits beyond the v0.6.0 baseline). Existing production remains untouched.

## Scope

This change adds a **separate production-context operator reader**, `windows/monitoring/OnyxReleaseReadOnly.py`, without changing the legacy development-only launchers. It can read an existing release incident store as a status snapshot or age-aware report; it **cannot run a live monitoring cycle**, initialize a store, create directories, reset state, schedule a task or repair a network interface.

The new module reuses the already tested `OnyxOperatorStatus.read_status()` and `OnyxOperatorReport.summarize()` functions. It deliberately does **not** call either module's development-only CLI authorization, `OnyxLiveIncident.approved_context()`, or the PowerShell diagnostic collector. Development commands remain restricted to the `onyx-core-v070` feature branch and their isolated development data.

## Release-only safety boundary

Before reading stored history, the runtime must verify all of the following:

- Windows-only invocation, with the script physically rooted at `D:\github_repos\onyx-core` (no redirected Git repository path).
- Git branch `main`; the required release Python modules and example config are tracked; all tracked files have a clean worktree; no unexpected files are present in `windows/monitoring/`.
- Validated release configuration (`profile=release`, `read_only=true`, `repair_action=None`) at the fixed repo path; no user-selected alternate configuration file.
- Python executable matches the configured approved `C:\Python313\python.exe` runtime.
- Release state is derived from the current user's `%LOCALAPPDATA%` as `OnyxCore-v070-Release\Monitoring` and must be free of junctions/symlink redirects.
- An existing and valid initialization marker **and** checksum-validated incident store, with at least one persisted observation. A missing or corrupted release store is an error, never a blank-history reset.

Untracked files elsewhere in the repository (including the protected collector backup) are not read or used as authorization material; unlike the development guard, this reader is independent of the old v0.6.0 HEAD SHA.

**This is source/invocation preflight, not a complete security/ACL assessment.** Windows account ownership/ACLs, the release install procedure, rollback, and first-cycle authorization still require separate review and acceptance. Git checks do not authenticate a maliciously committed `main` branch; release review and protected deployment remain necessary.

## Commands *only after a later authorized production merge and first initialization*

The release-specific CLI is **not executable in the development worktree**; this is intentional. After release installation and separately authorized first cycle (future work), an operator could invoke:

```powershell
& 'C:\Python313\python.exe' `
    'D:\github_repos\onyx-core\windows\monitoring\OnyxReleaseReadOnly.py' `
    --status --events 10

& 'C:\Python313\python.exe' `
    'D:\github_repos\onyx-core\windows\monitoring\OnyxReleaseReadOnly.py' `
    --report --events 10 --stale-minutes 30
```

The commands support `--json`, allow at most 20 journal events and do not accept `--live-read-only`, `--initialize-new`, `--schedule`, `--repair`, or `--config`. They do **not** claim a historical Healthy reading represents current live connectivity.

## Test and validation boundaries

`tests/monitoring/test_release_readonly.py` exercises a disposable fake release repository and disposable release-state files. Tests mock the installation path, local Git checks and Python executable; they never run a real live diagnostic. The tests cover release authorization, modified/untracked source refusal, isolated store location, absent/corrupt marker/store, path redirection, config rejection, historical output, stale health, and no-live/no-write behavior.

**Offline source-snapshot run:** 33 new tests passed; **299 monitoring cases passed** including the previously available Linux symlink tests. SQUALL's Windows run may skip additional symlink creation tests where privileges are unavailable. Do not count a skipped Windows test as a pass.

The package must be installed into the existing `feature/v0.7.0-monitoring` worktree only after exact ZIP checksum, baseline and approved-file checks. It must contain exactly **three new files**, with no overwrites or changes to an existing Python module. It does not create or modify any release or development incident-store files.

## Explicitly NOT part of this patch

1. A release-mode one-shot diagnostic or initial release-store creation (requires separate explicit authorization, PowerShell collector and runner integration, and preflight/ACL review).
2. Background monitoring, Windows Task Scheduler integration, automatic ICS repair, adapter resets, SSH key installation, or network changes.
3. A production merge, push, tag, service deployment, or release announcement.
4. Any migration/copy/reset of the existing generation-2 development incident history.

**Next gate:** validate this view-only adapter on SQUALL, commit as a new checkpoint if approved, then design/test the explicit one-shot release cycle independently. The entire v0.7.0 release remains NO-GO until the other Milestone 5 requirements are addressed.
