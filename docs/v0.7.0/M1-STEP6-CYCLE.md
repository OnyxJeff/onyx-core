# ONYX CORE v0.7.0 — Milestone 1, final step: Single-cycle runner

**Status:** Development-only, manually invoked. No unattended task, no incident lifecycle, no production deployment.

## Scope

- New `windows/monitoring/Invoke-OnyxMonitoringCycle.ps1` provides a thin wrapper around the already reviewed `windows/networking/Collect-OnyxRecoveryEvidence.ps1`.
- Requires explicit `-LiveReadOnly`. Without it, no network probes or history writes occur.
- Requires `feature/v0.7.0-monitoring`, the `onyx-core-v070` worktree, and Checkpoint B as an ancestor.
- Preserves collector's restricted SSH authentication, bounded execution, fail-closed decisions, mutex and isolated development observation history. The wrapper does not change probe implementations.
- Validates both repair fields as `None`, allowed classifications, history location and evidence consistency. Unexpected/contradictory results throw an error instead of returning `Healthy`.
- Returns one small, structured PowerShell object or JSON (`-Json`) for later incident-engine consumption. Includes cycle timestamps, connectivity decision, incomplete-evidence flags and counts. No raw diagnostic errors, private keys or tokens appear in the summary.
- The wrapper does **not** create a new database, persistent status file, incident log, monitoring task, service or listening endpoint.

## Safe offline validation

In Windows PowerShell 5.1, from the development worktree:

```powershell
& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `
    '.\tests\monitoring\Test-OnyxMonitoringCycle.ps1'
```

Offline tests parse the wrapper and exercise **only** its pure summarization function with synthetic evidence. They do not execute the wrapper's top-level collector call or probe the network.

## Deliberate one-cycle read-only validation (separately controlled)

```powershell
$Runner = 'D:\github_repos\onyx-core-v070\windows\monitoring\Invoke-OnyxMonitoringCycle.ps1'
$Result = & $Runner -LiveReadOnly
$Result | Format-List
# Or: & $Runner -LiveReadOnly -Json
```

Each live invocation **does** run the existing Windows/Pi network probes and writes one bounded observation to `%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring\recovery-observations.json`.

## Limitations

- A successful manual cycle is **not** an unattended monitor. There is no scheduling, restart supervision, incident deduplication or durable monitor-status record in Milestone 1.
- A collector exception or invalid report fails closed with a PowerShell error and **does not** produce a normal `Complete` summary. Incident engine handling of failed cycles belongs to Milestone 2.
- The wrapper does not impose an overall outer wall-clock timeout beyond the bounds inside the collector. A task-level deadline belongs to Milestone 3/4.
- Boot/logon/sleep grace and false-positive testing remain required in later milestones.
- No automatic ICS repair is implemented or authorized.
