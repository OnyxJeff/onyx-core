# ONYX CORE v0.8.0 — M2C Offline Evidence Integration

**Scope:** Development-only, synthetic evidence, no persisted state.
**Required parent:** `28a01bed990300af62b30fa526d46d70d3151afe` on `feature/v0.8.0-continuous-monitoring`.
**Status:** Local sandbox and SQUALL offline tests passed; staged review pending. **No local commit authorized by this document.**

## Safety boundary

M2C adds `windows/monitoring/v080/OnyxOfflineEvidenceIntegration.py` and an offline-only test suite. The CLI supports **only** `--check-inert`. There is no CLI to run an evidence cycle, no monitoring installation, no enrollment writer, no Task Scheduler action, no network socket, no SSH, no PowerShell diagnostic runner, no ICS action, no self-heal and no incident-store writer. Neither v0.7.0 release nor development histories are read or modified by M2C.

An importable function, `run_offline_evidence(auth_fixture, supervisor_fixture, evidence_raw, worker_mode="ok")`, is provided **only for offline development tests**. It validates synthetic JSON bytes, uses the existing M2B simulated authorization fixture reader, runs one existing M2A fixed Python subprocess fixture with a temporary-directory lock, then applies synthetic observations **in memory** through the existing v0.7.0 pure `OnyxIncidentState.py` reducer. It does not import `OnyxIncidentStore.py`, `OnyxReleaseLiveIncident.py` or the collector. No incident state or event is written to disk.

The tested M2B config uses an **in-memory** enabled copy of the checked-in disabled M1 example, never a real enrollment or trusted identity. Its approval, ACL, source, and revocation attributes remain caller-supplied simulated assertions. Even if M2B returns `EligibleDataOnly`, the result is **not** authorization to execute real monitoring. A malicious or mistaken caller can forge these test fixture inputs; do not expose the offline function as a production service.

## Why the v0.7.0 reducer needs a schema discriminator

The existing **pure** v0.7.0 reducer requires `source="LiveRestrictedDiagnostic"` in an incoming cycle. For **in-memory schema compatibility only**, M2C constructs a private reducer cycle with that literal after checking `provenance="SyntheticFixtureOnly"` on the input. This is **not** a statement that any real diagnostic ran. M2C **never returns or stores** that internal v0.7.0-compatible object. All public M2C results are explicitly labeled `source="OnyxV080M2COfflineEvidence"`, `provenance="SyntheticFixtureOnly"`, `simulation_only=true`, `real_incident_confirmed=false`, and all runtime, live, task, and store capability fields are false.

This adapter is a **contract exercise**, not a trusted provenance attestor; production evidence must use a separate independently authenticated and reviewed adapter. Never route M2C's private reducer cycle to the v0.7.0 live adapter or incident store.

## Input contract and derivation

- `evidence_raw` is a strict, bounded UTF-8 JSON document with exact fields `schema_version`, `provenance`, `reference_utc`, and `samples`. The provenance is exactly `SyntheticFixtureOnly`.
- `samples` contains 1–12 strictly increasing offset-aware timestamps, each at most 300 seconds old and no more than five seconds ahead of the **synthetic** `reference_utc` (the reference is not the system clock). Each sample has exact Windows/Pi classification fields and three boolean error flags. Duplicate keys, non-finite numbers, unknown fields, bad flags, stale/future timestamps and inconsistent schemas are rejected **before** a mock process is launched.
- Windows class is one of `WindowsPathReady`, `WindowsPathUnverified`; Pi class is one of `PiInternetVerified`, `ExternalTcpUnverified`, `PiUnreachable`. The internal adapter derives the decision instead of accepting a caller-supplied incident verdict. Incomplete flags force `Investigate`/`EvidenceIncomplete`, never Healthy or PossibleIcsFailure.
- `WindowsPathReady` with `PiInternetVerified` and complete evidence derives Healthy. `WindowsPathReady` with `ExternalTcpUnverified` derives WaitAndRetry until **three consecutive corroborated synthetic observations** within the bounded window; only then does it derive **PossibleIcsFailure**, not proof of ICS root cause. Other complete mismatches derive Investigate.
- Once the M2A synthetic worker succeeds, the exact existing v0.7.0 reducer determines incident phases and event types. In an Active phase, it requires two independent Healthy cycles spaced 30–300 seconds apart to recover; incomplete evidence breaks recovery continuity. Missing evidence always displays Unknown, including when there is a simulated Active incident.
- Mock worker timeout/nonzero exit/invalid output/repair claim causes an **Unavailable/Unknown** result with zero processed cycles and no incident transitions. M2A's Job Object/process-group safety and cross-process fixture lock remain in force. Unknown or unauthorized actions are refused.

## Files and storage isolation

- M2B uses a temporary `onyx-v080-m2b-*` folder directly under the OS temp root containing exactly `config.json`, `enrollment.json`, `revocation.json`, and `facts.json` written **only by the tests**. The M2C module reads these through M2B; it does not create or modify them.
- M2A uses a separate temporary `onyx-v080-m2-*` folder directly under the temp root, and its fixture-only `fixture-cycle.lock` is the **only** expected file it may create. The directory and lock are rejected when redirected.
- The immutable v0.7.0 pure reducer is loaded from the fixed in-repository path `windows/monitoring/OnyxIncidentState.py`, not an arbitrary caller-supplied module. The installer must verify the expected v0.8.0 commit and a clean pre-install worktree.
- No `incident-state.json`, `recovery-observations.json`, production config, enrollment, task or state directory is created by M2C. Tests verify the four fake M2B inputs remain and only the M2A temporary lock appears. Python test execution runs with `-B` to avoid bytecode files.

## Failure tests and acceptance criteria

The new suite exercises the genuine M1/M2A/M2B Python implementations, a synthetic preflight, both process-containment outcomes, the v0.7.0 pure reducer API, and input invalidation. Cases include: healthy-without-real-health claim, 1–2 suspects vs three corroborated suspects, broken continuity, a two-cycle recovery window, incomplete-evidence handling, suppressed recovery after missing evidence, unverified Windows/Pi classifications, worker timeout/nonzero/invalid/repair, denial before launching a worker, forged authorization/supervisor capability, duplicate/out-of-order timestamps, stale/future samples, malformed/oversized JSON, nonfinite/duplicate keys, and CLI refusal of live switches.

**Local sandbox result (2026-11-10):** 176/176 tests passed with the M1/M2A/M2B package source and the M2C additions. **Limitation:** The sandbox lacks the user's checked-in v0.7.0 reducer, so this local run used a **sandbox-only reducer-interface mirror** for validation. That mirror is **not packaged or installed**. SQUALL must run against the actual `windows/monitoring/OnyxIncidentState.py`, so its test result is an independent required acceptance gate. On Windows, one preexisting M2A symlink-creation test may be skipped due to non-elevated permissions; no M2C test may be skipped.

**Pre-acceptance SQUALL criteria:** 176 total; typically 175 passed, one preexisting symlink test skipped, zero failed. The installer performs guarded SHA-256, source checks, original collector backup and protected history checks before and after the test suite. Stop on any failure; do not rerun an installer that partially installed files, or reset Git without review.

**SQUALL offline acceptance (2026-11-10): PASS.** Windows PowerShell 5.1 / Python 3.13 reported `Ran 176 tests` and `OK (skipped=1)`: 175 passed, 1 skipped, 0 failed. All 38 M2C integration tests passed against the checked-in v0.7.0 pure incident reducer, including incident escalation, recovery spacing, incomplete-evidence handling, and pre-spawn authorization refusal. The skip is M2A's symlink-creation test, which requires unavailable Windows permissions. The M2C CLI reported `simulation_only=true`, `runtime_enabled=false`, `live_probe_authorized=false`, `task_creation_authorized=false`, `store_modified=false`, and `repair_action=None`. The installer verified exactly three untracked development files, no new commit, unchanged production, collector backup, protected incident histories and existing tasks. No live probes, enrollment, scheduling, deployment, push, merge, tag or repair. This is operator-provided host evidence, not production authorization.

**Stage gate:** Inspect the exact three-file staged diff. A local M2C commit requires separate explicit operator authorization; no real diagnostics or scheduling are authorized.

## Deferred production work

M2C supplies neither actual Windows identity/ACL attestation nor authoritative revocation, crash-safe v0.8.0 incident history, live-probe intake, task creation, notifications, or repair. The M2 milestone remains open. M3 will address durable incident/alert lifecycle separately. Real enrollment, live diagnostics, scheduled monitoring, deployments, releases, push/merge/tag and auto-repair require independent explicit operator approval.
