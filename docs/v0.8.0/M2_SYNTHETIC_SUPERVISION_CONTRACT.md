# ONYX CORE v0.8.0 — M2A Synthetic Supervision Contract

**Status:** Candidate development-only, synthetic-only. This is *not* a runtime
monitor, live diagnostic, enrollment system, scheduler, incident writer, or
production deployment approval.

**Starting commit:** local M1 `8b9a8d5a1bd09ded824ecf07e59d05e5a580cdcf`.
**Worktree:** `D:\github_repos\onyx-core-v080`.

## Review of v0.7.0 boundaries

- `windows/monitoring/OnyxReleaseLiveIncident.py` requires explicit manual
  `--live-read-only` and production release source verification before invoking
  PowerShell. It must not be used as a scheduled or unattended launcher.
- `windows/monitoring/Invoke-OnyxReleaseCycle.ps1` requires the production
  `main` root and v0.7.0 supervision environment string. This string is **not
  authentication** and is not a lawful shortcut for v0.8.0.
- `windows/networking/Collect-OnyxReleaseEvidence.ps1` **writes** its bounded
  `recovery-observations.json` inside the v0.7.0 release state. Therefore
  invoking this collector as-is in a v0.8.0 supervisor would modify protected
  v0.7.0 history and is expressly prohibited.
- `OnyxIncidentState.py` is a pure reducer; `OnyxIncidentStore.py` is a bounded,
  checksummed atomic store whose caller chooses the storage location. These
  can be evaluated for future v0.8.0 integration, but M2A does not import them
  or create any persistent incident state.
- The Pi restricted SSH command is an existing read-only capability, **not**
  a grant of unattended Windows permission. M2A does not invoke SSH.

## M2A implemented scope

- `windows/monitoring/v080/OnyxOfflineSupervisor.py` has one CLI operation:
  `--check-inert`. This never starts any child.
- The importable `run_synthetic_cycle()` is the only process exercise: it
  launches a **hardcoded Python fixture**, never an arbitrary command or
  diagnostic. Its supported modes are fixed test strings.
- The child pauses on stdin until the parent has created and assigned a
  Windows Job Object, or started a new POSIX process group. No SSH,
  PowerShell, network code, services, registry changes, or task installation
  are reachable by this path.
- A temporary, exclusive OS file lock enforces no overlap. Tests use a named
  subdirectory directly under the system temp directory and remove it after
  execution. Nothing is stored in `%LOCALAPPDATA%`.
- Each fixture run has a caller-selected 0.05–5.0-second mock timeout.
  Timeout, nonzero exit, malformed output, oversized output, and attempted
  repair output never claim connectivity health. The launcher kills the mock
  process tree and refuses to report success if teardown fails.
- Every returned record states `synthetic_only=true`,
  `connectivity_assessed=false`, `runtime_enabled=false`,
  `live_probe_authorized=false`, `task_creation_authorized=false`,
  `store_modified=false`, `repair_action=None`.
- No monitor runtime, enrollment record, Task Scheduler task, history
  initialization, or real diagnostic adapter exists.

## Critical limitations and follow-on gates

1. Windows job attachment uses a fixture-specific stdin handshake to prevent
   descendants from launching before assignment. A real executable without
   that handshake needs an independently reviewed **atomic start-and-assign**
   strategy (or an equivalent robust Windows process-tree containment method).
2. Windows PowerShell 5.1 behavior and Job Object test results must be
   verified on SQUALL. Cross-platform tests do not establish Windows behavior.
3. The future real worker MUST NOT call the existing v0.7.0 release scripts
   or write into v0.7.0 histories. Extract a separate, reviewed read-only
   evidence adapter whose config and history directory are v0.8.0-specific.
4. Runtime eligibility, Windows identity, ACLs, redirects, repository/source
   binding, enrollment/revocation, trusted executable identity, and
   revalidation under an OS lock remain unimplemented. The M1 `operator_approved`
   field is not proof of authorization.
5. A monitoring interval of 120 seconds and production per-cycle deadline of
   90 seconds are **candidates**, not validated by the short synthetic fixture
   timeouts. End-to-end diagnostic and scheduling jitter tests are required.
6. Atomic persistence, no-reset checks, independent monitor-health history,
   and alert journaling remain future work. A hard process crash cannot be
   considered safely contained merely by this fixture exercise.
7. Future integration must preserve the v0.7.0 incident reducer semantics:
   incomplete evidence must never mean healthy or confirmed ICS failure; a
   corroborated incident requires three qualifying observations within the
   bounded window; an active incident recovers on two healthy cycles spaced
   30–300 seconds apart.
8. No runtime, live, scheduled, production, push, merge or repair action is
   approved by this milestone.

## Local offline verification

From the isolated development worktree, with Python 3.13:

```powershell
$Dev = 'D:\github_repos\onyx-core-v080'
$Python = 'C:\Python313\python.exe'
& $Python -B (Join-Path $Dev 'windows\monitoring\v080\OnyxOfflineSupervisor.py') --check-inert
if ($LASTEXITCODE -ne 0) { throw 'M2 inert check failed' }
& $Python -B -m unittest discover -s (Join-Path $Dev 'tests\monitoring\v080') -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'M1/M2 offline tests failed' }
```

**SQUALL Windows PowerShell 5.1 verification (2026-11-10): PASS (offline only).**
The initial 75-test run failed one Windows process-tree PID capture case.
After a targeted fix, the integrated M1 + M2A suite reported
`Ran 76 tests` and `OK (skipped=1)`: 75 passed, zero failed.
Both Windows process-tree timeout/cleanup and missing-partial-stdout
regression tests passed. The skipped symlink test could not create a
symlink under the current Windows privileges; this adversarial case
remains unverified on SQUALL.
The inert CLI reported `runtime_enabled=false`,
`live_probe_authorized=false`, `task_creation_authorized=false`,
`store_modified=false`, `synthetic_only=true`, and `repair_action=None`.
These are operator-provided host results. No tasks, live probes, state
initialization, deployment, commits, pushes, or merges were performed.

**SQUALL M2A hardening verification (2026-11-10): PASS (offline only).**
Added a simulated Windows junction-path refusal test and strengthened
descendant process verification to reject errors other than a nonexistent PID.
The integrated suite reported `Ran 77 tests` and `OK (skipped=1)`:
76 passed, 1 skipped, and no failures. Both process-tree tests and the new
junction-refusal test passed. The symlink-creation case remains skipped.
No M2A commit, task, live probe, deployment, push, or merge occurred.

**Gate:** M2A synthetic-only tests are accepted for review, but no
production execution, scheduling, Pi diagnostics, or monitoring runtime
is authorized. M2 remains open.
