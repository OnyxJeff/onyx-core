# ONYX CORE v0.8.0 — R2 Offline Execution & Evidence Contract

**Scope:** SEC-03 (worker containment), SEC-04 (read-only evidence isolation), SEC-05 (timestamp and classification integrity).  
**Development parent:** `038ad1b7d39ff666a6319ea5e00c223ae6599d0d` on `feature/v0.8.0-continuous-monitoring`.  
**Status:** Synthetic-only development candidate. **All three security findings remain BLOCKED for live use.**

## Contract and trust boundary

The `OnyxOfflineExecutionEvidenceContract.py` module is a **pure, in-memory JSON contract**. Its public API is `assess_synthetic_cycle(policy_bytes, containment_bytes, evidence_bytes)` and `inert_status()`. The only accepted CLI action is `--check-inert`. No configuration option allows real workers, Windows Job Objects, subprocess invocation, SSH, HTTP, USB probes, filesystem reads/writes, enrollment, Scheduled Task operations, notification delivery, or repairs.

- JSON must be bytes, canonical UTF-8, 64 KiB or smaller per document, with exactly the allowed fields, unique property names, and finite values.
- All three fixture documents must identify `R2InMemoryFixtures`, schema 1, and `simulation_only=true`. A claimed real Windows identity, job, host clock, or evidence origin is rejected.
- Policy fixes the worker identity to `r2-synthetic-observer-v1`, a 90,000 ms worker deadline, 8,192 byte stdout/stderr individual limits, four required synthetic channels, and a 2,000 ms synthetic clock disagreement tolerance. All live, repair, task, and delivery permissions must be false.

## SEC-03 — Synthetic containment transcript

A six-stage mock transcript must contain strictly ordered, monotonically increasing events: `created_suspended`, `job_attached`, `resumed`, `worker_ended`, `tree_drained`, `job_closed`. A mock job must claim assignment **before resume**, kill-on-close, no breakaway, no unbounded child hierarchy, and complete zero-descendant cleanup. The **real Windows Job Object attestation** and **real process started** flags must both be false.

A synthetic success must finish before its deadline and report exit code zero. Synthetic timeout ends **at** the 90,000 ms deadline with no exit code, and synthetic worker failure requires a nonzero exit. Cleanup must be complete and finish within the 5,000 ms cleanup allowance. Any contradictory or missing containment evidence is refused; worker failure/timeout can produce only `Unknown` and no samples.

**Not proven:** Windows start-suspended/assign-to-job atomicity, actual breakaway prevention, process-tree termination, secure launch identity, child-handle cleanup, or hardware execution. These require separately approved native Windows tests and independent engineering review.

## SEC-04 — Synthetic read-only evidence transcript

Evidence declares `read_only=true`, `attempted_writes=0`, `protected_store_accesses=0`, `external_calls=0`, and `origin=SyntheticFixtureOnly`. For success, exactly one record per fixed channel is required, in this order: `pc_usb_network`, `pi_receiver`, `gateway`, `data_freshness`. The records contain bounded monotonic tick/time pairs, a restricted status/detail code, and a reproducible SHA-256 consistency digest.

**Not proven:** The claims reflect mock inputs; a SHA-256 consistency digest is **not a signature or evidence authenticity guarantee**. The module does not read protected v0.7 monitoring stores, but an independently audited **actual read-only v0.8 adapter** is still missing.

## SEC-05 — Synthetic clock and classification semantics

`anchor_utc`, sample UTC timestamps, and capture UTC are strictly parsed canonical UTC (`YYYY-MM-DDTHH:MM:SSZ`). Monotonic ticks must agree with the synthetic wall clock within 2 seconds, increase across samples, occur within the worker lifecycle, and precede capture. Out-of-order, missing, stale, future, contradictory, invalid or forged-clock observations fail closed. A complete healthy mock yields **`SyntheticHealthy`**, any suspect yields **`SyntheticSuspect`**, and incomplete/unknown or failed execution yields **`Unknown`**.

**Not proven:** These synthetic timestamp relationships do not attest the actual Windows clock, monotonic source, remote Pi observation time, authenticated evidence, or real host health. Even `SyntheticHealthy` explicitly reports `runtime_enabled=false`, `live_probe_authorized=false`, `windows_job_attested=false`, `clock_attested=false`, `evidence_authentic=false`, and `store_modified=false`.

## Host acceptance and protected invariants

- Required development parent `038ad1b7d39ff666a6319ea5e00c223ae6599d0d`; branch `feature/v0.8.0-continuous-monitoring`; initial worktree/index clean.
- The guarded package checks SHA-256 of **26 previously committed M1–M5/R1 artifacts**, installs exactly **three new R2 files**, and leaves them **untracked**. No staging or commit is authorized.
- The 386-case prior suite must remain intact, including 61 M3, 64 M4, 85 R1, and the two real-reducer compatibility tests. R2 adds **97** cases, requiring **483** total. No failures are allowed; only the documented Windows symlink privilege skip from the existing M2A supervisor tests is permitted.
- Preserve production `main` at `06ec81582791fc797f74ad294195d68b2023cb66`, the original collector backup hash, both distinct five-file v0.7 monitoring inventories, and **exactly three** audited Scheduled Task definitions, snapshotted read-only before and after.
- The scripts do not run real worker tests, create/modify Scheduler tasks, reach the Pi/SSH, probe network/ICS, create state stores, enroll anything, elevate, stage/commit/push/merge/tag/release, deliver messages, or repair systems.

## SQUALL R2 host acceptance — 2026-11-10

**Checkpoint:** PASS for *offline synthetic development only*, verified on SQUALL against exact local development HEAD `038ad1b7d39ff666a6319ea5e00c223ae6599d0d` on `feature/v0.8.0-continuous-monitoring`.

- The source package ZIP, installer ZIP, and Windows PowerShell 5.1 installer script passed their provided SHA-256 checks; PowerShell parsing succeeded before execution. The installer verified the exact three package members by name, size, and SHA-256.
- All 26 previously committed M1–M5/R1 source hashes matched. The development and production worktrees passed the initial preflight; the existing three ONYX CORE / LibreHardwareMonitor Scheduled Task definitions were recorded read-only.
- Exactly three R2 files were installed without overwrite: this Markdown contract, `test_offline_execution_evidence_contract.py`, and `OnyxOfflineExecutionEvidenceContract.py`.
- The integrated SQUALL suite ran **483 tests: 482 passed, 1 skipped, 0 failures or errors**. All **97 R2** synthetic tests, all **85 R1** tests, both genuine reducer compatibility tests, and the previously established suite passed except for the documented skip.
- The sole skip was `test_offline_supervisor.SyntheticSupervisorTests.test_rejects_symlinked_fixture_directory` — `symlink creation not permitted`. This skip remains a Windows filesystem security-validation gap; simulated symlink tests do not close it.
- M1 remained disabled, and M2A–M4/R1/R2 `--check-inert` capabilities confirmed no runtime, live probe, task creation, repair, or message delivery. R2 also reported `windows_job_attested=false`, `clock_attested=false`, `evidence_authentic=false`, `read_only=true` and `store_modified=false`.
- Post-execution host verification confirmed the unchanged production repository, original collector backup, both distinct five-file protected v0.7 monitoring histories, and the three existing Scheduled Task definitions.
- Development HEAD remained at the pinned R1 commit with **exactly three untracked R2 additions**; none staged or committed. No push, merge, tag, release, deployment, Scheduled Task modification, live probe, elevation, enrollment, notification or repair occurred.

**Security disposition:** SEC-03, SEC-04 and SEC-05 remain **BLOCKED** for real Windows process-containment, read-only evidence provenance, and trusted time attestation. **Live unattended monitoring remains NO-GO**. R2 review/staging and any local commit still require separate operator authorizations.

**Decision:** A passing SQUALL R2 checkpoint validates the offline *contract and simulated failure handling only*. It does **not** close SEC-03, SEC-04 or SEC-05. R2 review/staging, any local commit, any native-Windows attestation, and any live test require distinct operator authorization. **Unattended monitoring release: NO-GO.**
