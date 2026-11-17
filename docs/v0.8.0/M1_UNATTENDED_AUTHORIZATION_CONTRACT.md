# ONYX CORE v0.8.0 — M1 Unattended Monitoring Authorization Contract

**Status:** Candidate, development-only, **offline validation only**. Not a deployment approval or an enrollment mechanism.

**Source baseline:** v0.7.0, `06ec81582791fc797f74ad294195d68b2023cb66`.
**Target worktree:** `D:\github_repos\onyx-core-v080`, `feature/v0.8.0-continuous-monitoring`.

## 1. Problem and safety boundary

v0.7.0 supports one explicitly authorized live diagnostic at a time. Its release
policy refuses scheduling, and the guarded release one-shot code must remain
unchanged. A recurring trigger cannot constitute per-cycle consent. This M1
adds a *separate* schema and a **pure, offline-only** enrollment data-matching
contract to define how a future unattended supervisor might be authorized.

This package does **not** create a scheduled task, execute diagnostics, enroll
an operator, modify a user profile, create state, configure ICS, or contact the
Pi. It does not import v0.7.0 launchers. It has no task installer or background
process. The only command exposed in the module is `--check-example`.

## 2. M1 deliverables

- `windows/monitoring/v080/OnyxUnattendedPolicy.py`: Python 3.13 standard-library
  validator and **data-only** enrollment matcher; no runtime entry point.
- `windows/monitoring/v080/monitoring.unattended.example.json`: reviewed
  SQUALL-specific **disabled** example; it is **not** an active user config.
- `tests/monitoring/v080/test_unattended_policy.py`: deterministic adversarial
  tests using temporary data and in-memory inputs only.
- This document.

M1's `assess_offline_enrollment()` always returns `runtime_enabled=false`,
`live_probe_authorized=false`, and `task_creation_authorized=false`, even for
matching hypothetical enrollment data. A passing test can never approve a
live probe or Task Scheduler operation.

## 3. Intended future runtime contract — not yet implemented

Only after separate deployment approval may a **new** v0.8.0 supervisor:

1. Confirm the operator is the approved, logged-in Windows account.
2. Validate independently the approved source revision, trusted Git/source
   identity, executable paths, ACLs, and non-redirected repository/config/
   state/enrollment paths. Never trust fields or environment variables alone.
3. Read a separate enrollment record from
   `%LOCALAPPDATA%\OnyxCore-v080\Authorization\enrollment.json`. Do not create
   this record implicitly. Verify Windows ACL ownership and permitted writers.
4. Verify explicit consent scope, account match, pinned source commit,
   configuration SHA-256, and `repair_action=None`. A checksum detects byte
   changes, **not authorization/authenticity**; ACLs and account/source checks
   are mandatory. A new reviewed source revision or changed configuration
   requires renewed operator enrollment.
5. Confirm enabled intent and existing isolated, validated v0.8.0 state.
   Initialization requires separate authorization; never migrate or reset the
   five original v0.7.0 release incident files or four development files.
6. Acquire a real interprocess lock and revalidate under the lock before
   performing any bounded read-only evidence collection.
7. Classify incomplete evidence separately from verified connectivity faults;
   persist bounded history atomically; suppress duplicate alerts. Never repair.
8. Stop before probing if any precondition fails. A task trigger cannot bypass
   these checks.

Disabling a future monitor must revoke authorization independently of Task
Scheduler. A disable request while an operation is running must have explicitly
specified behavior (wait for bounded completion or supervised cancellation)
that preserves atomic history writes. The M1 package **does not** implement it.

## 4. Proposed polling and alert policy

- Default `interval_seconds=120` (restricted to 60–120 during initial design).
- One bounded cycle, max 120 seconds, no overlap, no catch-up flood.
- Default startup grace 180 seconds, logged-in operator session only.
- The v0.7.0 recovery reducer requires two healthy observations separated by
  30–300 seconds; corroboration uses a five-minute observation window.
  A 120-second interval is a *candidate*, not proof that three valid checks
  always fit within five minutes under scheduling jitter and varying duration.
  Test this explicitly in M2/M3; change cadence if evidence shows it is needed.
- Confirmed incident/recovery alerts should be emitted once per transition.
- Three consecutive incomplete cycles are a candidate for a distinct
  *monitor-health* alert, not a claim that ICS is broken.
- Initial notifications are local only; reliable Windows desktop toast
  delivery from Task Scheduler needs separately validated interactive-session
  behavior, or a simpler status/journal fallback.

## 5. Identity and persisted data boundaries

| Data | Proposed location | M1 effect |
| --- | --- | --- |
| v0.7.0 release incident files | `%LOCALAPPDATA%\OnyxCore-v070-Release\Monitoring` | Never read or write |
| v0.7.0 development files | `%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring` | Never read or write |
| v0.8.0 operational state | `%LOCALAPPDATA%\OnyxCore-v080\Monitoring` | Not created |
| v0.8.0 authorization grant | `%LOCALAPPDATA%\OnyxCore-v080\Authorization\enrollment.json` | Not created |
| Existing collector backup | `windows\collector\Send-OnyxTelemetry.pre-v050.bak` in production | Not touched |
| v0.8.0 example policy | Tracked development worktree | Disabled; offline read only |

Credential material (SSH private key, Pi bearer token, DPAPI collector secret)
is **not copied** into this package or accessed by its validator.

## 6. Offline verification

Run from the isolated worktree using approved Python 3.13:

```powershell
$Dev = 'D:\github_repos\onyx-core-v080'
$Python = 'C:\Python313\python.exe'
& $Python -B (Join-Path $Dev 'windows\monitoring\v080\OnyxUnattendedPolicy.py') `
  --check-example (Join-Path $Dev 'windows\monitoring\v080\monitoring.unattended.example.json')
if ($LASTEXITCODE -ne 0) { throw 'M1 policy check failed' }
& $Python -B -m unittest discover -s (Join-Path $Dev 'tests\monitoring\v080') -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'M1 tests failed' }
```

**SQUALL Windows PowerShell 5.1 verification (2026-11-10): PASS.**
Using `C:\Python313\python.exe`, `--check-example` returned
`config_valid=true`, `enabled=false`, `runtime_enabled=false`,
`live_probe_authorized=false`, `task_creation_authorized=false`, and
`repair_action=None`. The offline suite reported `Ran 51 tests in 0.032s`
followed by `OK` (51/51 passing). The operator's transcript confirms the
four M1 files were installed in the isolated v0.8.0 worktree and reports
no scheduled tasks, live probes, repairs, commits, pushes or production changes.

These are operator-provided SQUALL test results; they do not authorize any
live runtime operation or constitute independent host inspection.

## 7. Explicit outstanding work / release gates

- Runtime preflight, verified Windows identity, token-free ACL enforcement,
  symlink/junction/TOCTOU safety, source identity and safe enrollment/revocation.
- Safe task installation only after explicit separate approval; default
  disabled, no unseen background processes, no privilege elevation by default.
- Connection to read-only diagnostics under a distinct, reviewed supervisor
  entry point; no v0.7.0 policy loosening, environment-token workaround, or
  direct scheduled invocation of `OnyxReleaseLiveIncident.py`.
- Full timeout and subprocess termination semantics, task lock compatibility,
  scheduled missed-run behavior and restart behavior.
- Independent monitor-health state and notification delivery journal; no
  accidental historical incident rewrite.
- End-to-end offline regression and separately approved live acceptance.
- Documentation corrections for stale root README/CHANGELOG and dated
  v0.7.0 post-publication addenda.

**M1 offline acceptance (2026-11-10): 51/51 SQUALL tests passed.**
The operator authorized documentation finalization, four-file review, and a
local development-only commit after validation. This does not authorize any
push, PR, merge, tag, publication, deployment, scheduled task, unattended
monitoring, live diagnostic, or repair.
