# ONYX CORE v0.8.0 — R5 Offline Lifecycle & Timing Contract

**Checkpoint:** R5 synthetic development only. **Parent:** `5177665b6e9bf0d3164c8248590ded38feab0ba3` (R4).  
**SQUALL host acceptance:** **accepted offline** (771 tests: 770 passed, 1 documented Windows symlink-permission skip, 0 failures/errors). **Live unattended monitoring:** **NO-GO**.

## 1. Purpose and hard boundaries

Model a deterministic unattended lifecycle, bounded intervals, one synthetic run at a time, late/missed work, clean shutdown, restart ambiguity, explicit quarantine, and clock anomalies. **This is not a scheduler or a service.** No process is started, no Scheduled Task is created/edited/run, no network/SSH/USB probe occurs, no notification is sent, no enrollment is granted, and no repair is attempted.

The sole development additions are:

- `windows/monitoring/v080/OnyxOfflineLifecycleTiming.py` — pure synthetic transition model.
- `tests/monitoring/v080/test_offline_lifecycle_timing.py` — adversarial offline unit tests.
- `docs/v0.8.0/R5_OFFLINE_LIFECYCLE_TIMING_CONTRACT.md` — this contract.

No prior module, real v0.7 monitoring history, existing collector, Task Scheduler entry or production repository is changed.

## 2. Provenance and public interface

- `SOURCE = OnyxV080R5SyntheticLifecycleTiming`
- `PROVENANCE = SyntheticInputOnly`
- `SCHEMA = onyx-r5-offline-v1`
- `POLICY_SCHEMA = onyx-r5-policy-v1`
- Public pure functions: `policy_example()`, `new_state(policy, boot_id, mono_ms, wall_ms)`, `inspect(policy, state)`, `transition(policy, state, event)`, `dump_state(policy, state)`, `load_state(policy, serialized)`, `inert_status()`.
- CLI accepts **only** `--check-inert`, which reports `runtime_enabled=false`, `scheduler_started=false`, `task_creation_authorized=false`, `worker_spawned=false`, `transport_calls=0`, `notification_enabled=false`, `delivery_permitted=false`, `repair_action=None`. Any other flag is refused.
- No `os`, `pathlib`, socket, subprocess, timer, scheduler, Windows API, SQLite, real time source, or filesystem write in the runtime implementation. A caller may *simulate* persistence by passing serialized state between Python processes; R5 does **not** persist it to production or even to its own persistent database.

## 3. Policy and lifecycle

| Policy field | Synthetic bounds | Example |
|---|---|---:|
| `interval_ms` | 30,000–3,600,000 | 60,000 |
| `max_run_ms` | 1,000–300,000; strictly less than interval | 30,000 |
| `restart_quarantine_ms` | 30,000–3,600,000 | 90,000 |
| `max_missed` | 0–8 | 2 |
| `clock_skew_ms` | 0–10,000 | 2,000 |

`simulation_only=true` is mandatory and immutable. Policy keys must match exactly; JSON values must have correct types. Boolean numeric impostors are rejected.

Phases: `Idle`, `Due`, `Running`, `Quarantined`, `Stopped`, `FailedClosed`.

| Synthetic event | Core rule | Result |
|---|---|---|
| `Tick` | Due at or after aligned interval | `Due`, never launches a worker |
| `Start` | Requires unclaimed `Due`; unique run ID; before slot expiry | One `Running` lease with finite deadline |
| `Finish` | Requires matching active run ID and finite deadline | Success → `Idle`; failure/late → `FailedClosed` |
| `Tick` during active run | Past deadline | `FailedClosed`, synthetic abort counter increments |
| `Tick` after gaps | Count missed slots; no burst catch-up | Up to bound → single `Due`; beyond bound → `FailedClosed` |
| `Shutdown` | Explicit fixture event | `Stopped`; active run counted as aborted |
| `Restart` | New boot ID; old monotonic origin not compared to new boot | Idle/stopped → `Quarantined`; active/due/failed → `FailedClosed` |
| `Resume` | Only in `Quarantined`, after quarantine duration | Fresh `Idle` with new due interval; **not** authenticated operator consent |

A started run cannot be started again. An unclaimed due slot cannot roll forward indefinitely. A failed-closed snapshot never auto-recovers. Shutdown cannot clear a prior failure.

## 4. Clock and replay model

Each event includes a synthetic boot ID, monotonic milliseconds, wall milliseconds and unique event ID. Non-restart events must remain in the same boot and cannot reverse monotonic time. An unexpected wall-vs-monotonic delta beyond `clock_skew_ms` moves the simulation to `FailedClosed`; a backward monotonic event is rejected with no state change. Restart is an explicit event marking a new boot origin; a significant wall-clock rollback on restart is rejected. **No timestamp is attested by Windows or by a monotonic hardware clock.**

Snapshots have a policy digest, bounded event history, exact event schema, SHA-256 event chain, recomputed state projection and checked head digest. Every `inspect`, `transition`, `dump_state`, and `load_state` fully verifies and replays history. Exact event-ID replay is idempotent; same ID with changed contents is rejected. Invalid operations do not mutate the caller's state. History is capped at 128 events; capacity failure refuses new events and **does not prune** old history. Serialized inputs are bounded at 64 KiB.

SHA-256 checks are **unkeyed consistency checks, not malicious-writer authentication**. A party that can rewrite an entire snapshot can recompute the digest chain. R5 does not guarantee durable atomic filesystem persistence, Windows ACL protection, monotonic clock continuity across a real restart, distributed or cross-process exclusion, or actual Task Scheduler timing.

## 5. Adversarial offline acceptance

The R5 suite exercises scheduling boundaries, overlap refusal, no burst catch-up, run-timeout/failure handling, restart ambiguity and quarantine, clock jumps and rollback, idempotent replay, malformed provenance and schema, digest/projection tampering, event-capacity failure, and all inert CLI/transport/task restrictions.

Host gate: **655 previously accepted offline tests + 116 new R5 tests = exactly 771**. Only the previously documented Windows symlink-creation permission skip is allowed; no test errors/failures or other skips. The two genuine v0.7 reducer compatibility tests must still be discovered and pass.

Before and after installation, verify:

- Exact R4 parent `5177665b6e9bf0d3164c8248590ded38feab0ba3` and development branch `feature/v0.8.0-continuous-monitoring`.
- All **35** previously pinned M1–M5/R1–R4 artifact hashes; production `main` HEAD and clean tracked files; original collector backup hash.
- Exactly five original monitoring-history files in **each** protected v0.7 release/development store, with unchanged hashes.
- Exactly three audited task identities and unchanged **exported task definition XML** before vs. after.
- Source package contains exactly three SHA-256-pinned additions, installed **CreateNew** without overwrite, with exactly three untracked files and **no Git staging/commit**.

## 6. Remaining blockers / non-goals

R5 provides no verified Windows Task Scheduler behavior, job-object execution containment, real boot/restart attestation, Windows authentication/ACL enforcement, authoritative revocation, genuine health evidence, trusted clock, incident authenticity, production durability/backup, or delivery provider. It cannot clear SEC-01–SEC-10 or R1–R4 live blockers by itself. **R6 independent security/release verification remains necessary.**

**Explicitly excluded:** scheduled/automated execution, tasks/registry/service changes, deployment, production writes, live diagnostics, enrollment, repair, notification, push/merge/tag/release, elevation, and any staging or local commit without separate authorization.

## 7. SQUALL offline acceptance — 2026-11-11

**Disposition: PASS for offline synthetic host validation only; live unattended monitoring remains NO-GO.** This section documents the accepted follow-up recovery checkpoint after a validation-only installer defect.

- SQUALL verified the source ZIP, installer ZIP, and installer PS1 against pinned SHA-256 values; PowerShell 5.1 syntax validation passed. The initial installer confirmed the exact three ZIP members, correct R4 parent `5177665b6e9bf0d3164c8248590ded38feab0ba3`, 35 prior source hashes, clean worktrees, collector backup, two separate five-file v0.7 histories, and read-only snapshots of three audited Scheduled Task definitions before installing exactly three new R5 development files using no-overwrite creation.
- The original installer **stopped after creating the three files** at its R5 inert-status check. Its StrictMode guard tried to access nonexistent `task_created`, whereas the R5 module actually exposes `task_creation_authorized=false`. This was a **guard-script property-name defect**, not a failing R5 unit test; the module and tests were not modified.
- The separately supplied `Resume-ONYXCORE-v080-R5-Acceptance.ps1` recovery checkpoint verified its own ZIP/script hashes and PowerShell syntax; it **did not reinstall or overwrite** the three existing files. It performed the missed validation checks using the correct R5 inert-status field.
- The SQUALL integrated suite ran **exactly 771 tests in 19.758 seconds: 770 passed, 1 skipped, 0 failures/errors**. All **116 R5 cases** passed, along with the 655 earlier cases (including 105 R4, 67 R3, 97 R2, 85 R1) and both real checked-in v0.7 reducer compatibility cases.
- The sole skip was `test_offline_supervisor.SyntheticSupervisorTests.test_rejects_symlinked_fixture_directory`: Windows reported `symlink creation not permitted`. This is an unresolved platform-specific validation gap, **not** a successful real symlink/ACL attestation.
- All M1–M5 and R1–R5 inert interfaces remained disabled/synthetic-only. R5 explicitly reported `runtime_enabled=false`, `scheduler_started=false`, `worker_spawned=false`, `transport_calls=0`, `task_creation_authorized=false`, `notification_enabled=false`, `delivery_permitted=false`, `windows_clock_attested=false`, and `identity_authenticated_in_windows=false`.
- The recovery's final read-only checks verified the exact R4 parent, all 35 prior SHA-256-pinned source artifacts, the original collector backup, both separate protected five-file v0.7 histories, the unchanged production repository, unchanged exported XML definitions of all three audited Scheduled Tasks, and the byte-identical original R5 files. Exactly **three R5 files remained untracked**, with **no staging or commit**.
- No push, merge, tag, release, deployment, real scheduler run, worker launch, live diagnostic, elevation, enrollment, notification, task modification, or repair was performed.

**Security disposition:** R5 models scheduling, overlap, bounded timing, restart quarantine and clock failure from synthetic inputs only. It does not authenticate real clocks or operators, enforce Windows scheduling/exclusion, establish a protected persistent store, or clear SEC-01–SEC-10 or previous R1–R4 live blockers. **Live unattended monitoring: NO-GO.**

**Next authorization boundary:** Review and staging of precisely these three R5 additions, followed by any local commit, require separate express operator authorization. This Markdown is a preview; it has not been applied to SQUALL.
