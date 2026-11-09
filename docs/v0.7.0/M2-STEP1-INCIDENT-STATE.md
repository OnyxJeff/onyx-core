# ONYX CORE v0.7.0 — Milestone 2 / Step 1: Pure incident reducer

**Status:** Development-only, offline-tested proposal. **Not** integrated into a live monitoring entry point, not persisted, not scheduled, not deployed.

## Files

- `windows/monitoring/OnyxIncidentState.py`: standard-library Python, pure state transition functions; no I/O, SSH, subprocess, filesystem writes, network calls, services, or automatic repairs.
- `tests/monitoring/test_incident_state.py`: synthetic incident sequences, bad-input checks, replay tests and no-repair tests.
- `docs/v0.7.0/M2-STEP1-INCIDENT-STATE.md`: this contract.

## Input and output

Input: the exact M1 `Invoke-OnyxMonitoringCycle.ps1 -LiveReadOnly` structured JSON summary, parsed to a Python dictionary. The reducer **does not invoke the runner**. The runner's schema, source identity, timestamps, duration, error flags, classifications and `repair_action: None` are checked. Invalid, contradictory, stale, or conflicting inputs raise `InvalidIncidentInput` without changing the caller's state.

```python
from OnyxIncidentState import initial_state, apply_cycle, display_status
state = initial_state()
state, events = apply_cycle(state, cycle_summary_dict)
print(display_status(state), events)
```

The returned `state` holds `schema_version`, `phase`, `evidence_status`, open incident metadata (or `None`), last processed cycle timestamp/digest, processed count, and last recovery time. `events` is a list of **transition events only**, not a per-poll log. No state is saved in this milestone step.

## State semantics

| Input cycle | Behavior |
| --- | --- |
| `Complete` + `Healthy` with no open incident | `Healthy` (or `Recovered` → `Healthy`); no duplicate incident event |
| `Complete` + `WaitAndRetry` or `Investigate` | Opens one `Suspected` incident or updates the existing one; repeat cycles do not open more incidents |
| `Complete` + `PossibleIcsFailure` with existing evaluator corroboration (at least 3 suspects) | Escalates current incident to `Active`, or opens an `Active` incident if this is the first cycle consumed |
| One `Complete` + `Healthy` after `Suspected` | Closes incident as `Recovered` |
| `Complete` + `Healthy` after `Active` | First good cycle creates an internal recovery candidate; another good cycle **30–300 seconds** later closes as `Recovered` |
| `EvidenceIncomplete` | Records a single transition to unavailable evidence, never opens or heals a connectivity incident, resets recovery candidacy, and `display_status()` returns `Unknown` |
| Evidence returns | One `EvidenceRestored` event, followed by ordinary handling of the new cycle |
| Duplicate most recent cycle | Idempotent no-op |
| Older cycle or same timestamp with conflicting data | Error, original state unchanged |

`Active` means **corroborated suspected connectivity degradation**, *not proof that Windows ICS is the root cause*. The raw classifier string remains `PossibleIcsFailure`, and **all events are `repair_action: None`**. The distinction between `phase` (last confirmed incident state) and `display_status` (current confidence) prevents stale healthy data from appearing green during a probe outage.

Events are `IncidentOpened`, `IncidentEscalated`, `IncidentRecovered`, `EvidenceIncomplete`, `EvidenceRestored`. They carry deterministic IDs, UTC timestamp, incident ID (if any), phase transition and classification, but no raw probe errors, private keys, secrets, or free-text decision reasons. Repeated same-state cycles do not generate repeated incident events.

## Testing (offline)

From `D:\github_repos\onyx-core-v070` in Windows PowerShell:

```powershell
& 'C:\Python313\python.exe' -m unittest discover -s tests\monitoring -p 'test_*.py' -v
```

The reducer tests use only synthetic cycles with fixed timestamps. They do **not** call the Pi, change tasks, or persist anything.

## Deliberate next steps

1. M2 Step 2: Design isolated, bounded, atomic durable state and journal; corrupt state must fail closed, never silently reset an open incident. Implement explicit replay safety across crashes.
2. M2 Step 3: Add a **separately controlled** adapter between the M1 runner and reducer; handle runner exceptions as missing evidence, not a healthy cycle. Explicit manual live test only after offline tests.
3. M3: strengthen outer deadlines, reboot/resume grace, clock skew, flapping and process concurrency. M4 may introduce an unattended task **only after separate approval**.

The pure reducer intentionally has no wall-clock source. Its future timestamp/clock-skew policy belongs to the supervised adapter in a later step, rather than silently trusting the current machine clock.
