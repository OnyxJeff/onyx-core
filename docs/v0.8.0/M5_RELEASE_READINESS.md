# ONYX CORE v0.8.0 — M5 Release Readiness Decision

**Readiness class:** Offline development checkpoint only.  
**Pinned source parent:** `27071dcdbb41616096107bfa3a7fcc8be337b7ce`.  
**Production baseline:** `06ec81582791fc797f74ad294195d68b2023cb66`.  
**As prepared:** 2026-11-10. **SQUALL M5 offline execution:** PASS (2026-11-10); staged review and local commit pending.

## Executive decision

**PASS (historical):** M1–M4 local development commits and the operator's SQUALL M4 test transcript record 301 offline tests, 300 passing with one expected symlink-permission skip, and no failures. All documented M3 and M4 integration cases passed on SQUALL.  
**PASS (M5 SQUALL host):** Corrected M5 guarded installer verified four-document SHA-256 inventory and installation; the full 301 offline tests completed with 300 passed, one known Windows symlink-permission skip and no failures. Three existing scheduled-task definitions, original collector, production Git baseline and both five-file protected histories were preserved.  **PENDING:** Staged documentation review and separately authorized local M5 commit.  
**NO-GO:** live unattended monitoring, actual Windows/ICS/Pi diagnostics, authenticated enrollment, automatic notifications, Task Scheduler changes, production merge/tag/release or deployment.

The code deliberately contains synthetic-only contracts and in-memory/state-free adapters. **A v0.8.0 live supervisor does not exist in these milestones.** “Release readiness” here means identifying blocking prerequisites and preserving a rollback path—not certifying an installable production feature.

## Evidence inventory

| Workstream | Deliverable | Local source status |
|---|---|---|
| M1 | Unattended authorization contract, policy validator and disabled example | Committed; hash-guarded |
| M2A | Synthetic supervisor and timeout/process-tree tests | Committed; hash-guarded |
| M2B | Simulated authorization/consent/ACL/revocation checks | Committed; hash-guarded |
| M2C | Synthetic evidence integrated with pure v0.7.0 reducer | Committed; hash-guarded |
| M3 | In-memory alert lifecycle, deduplication and fake acknowledgement | Committed; hash-guarded |
| M4 | Static synthetic-only operator HTML/text view | Committed at `27071dc`; hash-guarded |
| M5 | Audit, prerequisites, rollback plan and operator checklist | This package; **four new untracked documentation files**, not committed |

## Offline release gates

- [ ] Pin development `feature/v0.8.0-continuous-monitoring` HEAD to `27071dc...`; require a clean worktree before the M5 installer writes anything.
- [ ] Verify exact hashes of the reviewed M1–M4 tracked files and the genuine checked-in v0.7.0 reducer.
- [ ] Verify production `main` HEAD and tracked cleanliness; original collector backup unchanged.
- [ ] Verify both v0.7.0 protected monitoring directories contain exactly five files with their audited SHA-256 hashes.
- [ ] Snapshot relevant ONYX CORE and LibreHardwareMonitor Scheduled Task definitions read-only; compare before/after.
- [ ] Confirm the M1 sample policy is disabled and M2A–M4 CLIs report only denied capabilities.
- [ ] Run exact 301 Python 3.13 offline tests; require all 61 M3 and 64 M4 cases, both real-reducer tests, no failures/errors, and only the known symlink test may skip.
- [ ] Install exactly four reviewed M5 Markdown files without overwriting or staging; recheck SHA-256 and Git untracked inventory.
- [ ] Review the proposed M5 documentation and separately authorize **one local documentation commit** if acceptable. This M5 approval does **not** include a commit.

## Live runtime prerequisites — explicitly outside M5 authorization

1. Independent operator decisions: scope, authentic enrollment, revocation/disable, Windows account, current approved source and config, non-repair policy; **never** infer consent from a JSON boolean or Task Scheduler trigger.
2. Real Windows identity and path/ACL attestation with race-safe final-path and digest checks; no reliance on fixture-provided identity claims.
3. A new v0.8.0-only bounded, **read-only** evidence worker with no v0.7.0 file writes; tested Windows Job Object containment and watchdog behavior.
4. Isolated v0.8.0 operational state, atomic crash recovery, bounded retention, durable deduplication, and an explicit never-touch-v0.7.0 compatibility boundary.
5. Measured timing and overlap behavior including 30–300-second two-cycle recovery and five-minute corroboration under jitter, restart and sleep/resume.
6. Separate reviewed local notification transport and delivery journal, only if separately approved; no external channels implied.
7. Independent approval to test in a controlled host environment; capture real safety evidence without turning on unattended execution by default.
8. New explicit authorization before any live installation, schedule, production merge, tag, publication or release promotion.

These are **open implementation gates**, not steps performed by this package. The protected histories must never be used as test fixtures or altered to make a release candidate pass.

## Release decision table

| Proposed action | Decision after this M5 checkpoint |
|---|---|
| Read/edit four local M5 documents in isolated worktree | Allowed by M5 development approval |
| Run the guarded SQUALL synthetic offline suite | Allowed; required |
| Stage M5 documents | **Not part of installer**; separate documented review checkpoint first |
| Create local M5 commit | **Not authorized**; separate approval |
| Push, PR, merge, tag, GitHub release, website update | **Not authorized** |
| Enable task, enroll, send notification, probe, change ICS, repair or deploy | **Not authorized** |
| Announce unattended v0.8.0 monitoring production ready | **Prohibited by current evidence** |

**Decision owner:** Operator. **Current decision:** Hold production and close M5 offline documentation/testing first. See `M5_INTEGRATION_SECURITY_AUDIT.md`, `M5_DEPLOYMENT_ROLLBACK_PLAN.md` and `M5_OPERATOR_CHECKLIST.md`.

## M5 SQUALL offline host acceptance — 2026-11-10

**Result: PASS for offline documentation and synthetic regression; live NO-GO unchanged.** The operator verified the SHA-256 checksums of the M5 documentation ZIP and corrected installer ZIP/script, and PowerShell 5.1 parsed the corrected script without errors. The original installer first failed closed because it assumed four matching ONYX CORE/LibreHardwareMonitor tasks. A read-only audit identified exactly three root-level relevant tasks, and the corrected installer pinned those three task identities without changing them.

The corrected no-overwrite installation successfully wrote exactly four M5 Markdown files into the isolated development worktree. It verified the 19 tracked M1–M4 file hashes, pinned development HEAD `27071dcdbb41616096107bfa3a7fcc8be337b7ce`, unchanged production baseline `06ec81582791fc797f74ad294195d68b2023cb66`, original collector backup, and both five-file protected v0.7.0 monitoring histories. All three relevant Scheduled Task definitions were snapshotted read-only and confirmed unchanged at the end. No M5 content was staged or committed.

The exact SQUALL Python 3.13 offline suite reported `Ran 301 tests` and `OK (skipped=1)` (**300 passed, one skipped, zero failures/errors**). All 61 M3 tests, all 64 M4 tests and the two tests against the genuine checked-in v0.7.0 reducer passed. The sole skip remained the previously documented M2A Windows symlink-creation permission test. M1 remained disabled and the M2A–M4 inert-only capability checks denied runtime, live probing, repair, scheduling, state writing and notification delivery.

**Scope note:** These results document operator-provided host acceptance of the offline development milestone. They are not evidence of live unattended monitoring readiness, authenticated enrollment, Windows ACL attestation, persistent alert delivery or safe deployment. The M5 staging review remains separate; a local commit, all remote Git operations, release publication and any production action remain unauthorized without additional approval.
