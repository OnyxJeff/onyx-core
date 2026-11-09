# ONYX CORE v0.7.0 — M4 Step 2: Age-Aware Operator Report

**Scope:** Additional read-only development CLI on SQUALL; no production change.

## Purpose

`OnyxOperatorReport.py` builds on `OnyxOperatorStatus.read_status()` to explain the **age of the last persisted incident observation**, summarize the selected transition events, and provide cautious operational guidance. The report does not assert that a historically Healthy observation proves current connectivity.

## Execution

```powershell
& 'C:\Python313\python.exe' 'D:\github_repos\onyx-core-v070\windows\monitoring\OnyxOperatorReport.py' --report --events 10
& 'C:\Python313\python.exe' 'D:\github_repos\onyx-core-v070\windows\monitoring\OnyxOperatorReport.py' --report --json --events 10 --stale-minutes 30
```

The first command displays human-readable output; the second displays sanitized JSON. `--report` is mandatory. Event counts in this report apply to **selected recent events only**, not necessarily all historical events. The retained journal is bounded, and older entries may have been discarded.

## Freshness semantics

- `Recent`: Last observation no older than the configured threshold, default **30 minutes**. Still historical, never a new connectivity probe.
- `Stale`: Older than threshold. The program recommends an explicitly authorized **separate** read-only monitoring cycle, but it never starts that cycle.
- `FutureClockSkew`: Stored observation is more than **120 seconds ahead** of the PC clock. The report refuses to calculate a reliable positive age and advises checking time synchronization.

CLI threshold is `--stale-minutes N`, constrained to **1–1440** minutes. `--events N` is constrained to **0–20**.

For a stored incident phase of `Active` with evidence `Incomplete`, the report preserves `phase=Active` while presenting the last displayed status as `Unknown`; it never falsely declares recovery. A `Recovered` phase still reflects only the last observation.

## Security and isolation

- CLI calls `OnyxLiveIncident.approved_context()` to verify the approved development worktree, Git branch, pinned production commit, protected backup SHA-256, validated development config, and Python executable. It checks that **Checkpoint J** (`3c2a1dd99ef928caa56a8ae13e4b690eaefb5e6b`) is an ancestor of HEAD.
- Reuses `OnyxOperatorStatus.read_status` for initialization-marker verification, checksum validation, bounded event selection, and symlink/directory protections.
- Does not accept arbitrary CLI paths or enable initialization, live probes, network changes, repairs, scheduling, disk writes, or Git operations.
- JSON output excludes diagnostic decision reasons, SSH details, collector tokens, and filesystem paths.
- The historical incident store is maintained by a separate component; this command cannot update its `generation`.

## New tests

`tests/monitoring/test_operator_report.py` contains **30 offline tests** using temporary directories. Coverage includes timestamp-age boundaries, stale and future-clock-skew behavior, incomplete evidence, Active/Recovered incidents, truncated event selection, secret exclusion, no-write verification, CLI flag validation, ancestry guards and no probe invocation.

Expected SQUALL results after the package is installed: 30 new tests and **235 total** monitoring Python tests (two symlink-related tests may still be skipped due to Windows permissions). The existing two PowerShell offline suites must remain passing. Previous production and incident-history checks are prerequisites to accepting the package.

## Caveats

A timestamp can be `Recent` even if connectivity failed immediately afterward. The freshness classification describes **when data was collected**, not the machine's current availability. No real outage is injected or repaired by these tests. This milestone remains development-only until separately reviewed and deployed.
