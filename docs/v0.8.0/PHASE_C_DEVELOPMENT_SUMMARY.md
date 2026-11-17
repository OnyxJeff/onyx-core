# ONYX CORE v0.8.0 — Phase C Final Development Summary (Draft)

**Document class:** Post-R6 offline development handoff and evidence inventory. **Status:** DRAFT FOR REVIEW — not installed or committed.  
**Prepared:** 2026-11-11. **Evidence cutoff:** operator-provided SQUALL R6 commit and post-R6 audit transcripts, November 11, 2026.  
**Development:** `D:\github_repos\onyx-core-v080`, `feature/v0.8.0-continuous-monitoring`, `6e4ddef5a30e36742387432448f67e8dcf8bd469`.  
**Production:** `D:\github_repos\onyx-core`, `main`, `06ec81582791fc797f74ad294195d68b2023cb66` (v0.7.0), protected and unchanged.  
**Development acceptance:** PASS for offline synthetic scope. **Live unattended monitoring / production release:** **NO-GO**.

## 1. Executive determination

M1–M5 established offline policy, synthetic supervision, simulated authorization, evidence/reducer integration, alerts, operator view and security-boundary documentation. R1–R6 then extended *offline-only* trust, execution evidence, journal, operator/delivery, lifecycle and independent security review. The verified chain ends in a clean local R6 commit. The work is valuable as specification, adversarial test coverage and a development checkpoint; it is **not** an enabled monitoring agent, installed Windows service, safe live probe, delivery system or production release candidate.

The post-R6 read-only audit reported: all R1–R6 commits have the required direct-parent ancestry and exactly three added files each; **41 reviewed source/document/config SHA-256 values**, the v0.7 reducer, the three R6 Git blobs and **664 R6 insertions** match the approved inventory. It verified exact production and development HEADs, clean repositories, the original collector backup, both separate five-file protected v0.7 histories and unchanged XML definitions of all three audited Scheduled Tasks. These are locally observed *read-only* integrity facts, not live security proof.

## 2. Source and history inventory

| Milestone | Local commit (full SHA) | Tested contract / non-live deliverable |
|---|---|---|
| M1–M5 baseline | `8673a5cd3e67a966fa88baf28dccc778db54c6c5` | Offline contracts and integration/security documentation; baseline for R1 |
| R1 | `038ad1b7d39ff666a6319ea5e00c223ae6599d0d` | Synthetic Windows trust and operator authorization boundary |
| R2 | `61c33607e9f4fc7a5ecd4a77cef686cf50580d60` | Synthetic process containment and execution/evidence contracts |
| R3 | `47cf9405e9718026d3ec3e90230c5a7e60b01ba5` | Synthetic temporary-SQLite incident journal and replay safeguards |
| R4 | `5177665b6e9bf0d3164c8248590ded38feab0ba3` | Offline operator actions, simulated delivery decisions and action ledger |
| R5 | `7f22513e82c2a27dcbddad9a8e1d3203ae75e2d4` | Pure synthetic lifecycle, scheduling boundaries, restart/quarantine and clock model |
| R6 | `6e4ddef5a30e36742387432448f67e8dcf8bd469` | Independent negative-capability security review and adversarial regression |

Each R1–R6 commit adds exactly three approved paths in the audit. R6 added `docs/v0.8.0/R6_OFFLINE_INDEPENDENT_SECURITY_REVIEW.md` (88 lines), `tests/monitoring/v080/test_offline_independent_security_review.py` (364 lines), and `windows/monitoring/v080/OnyxOfflineIndependentSecurityReview.py` (212 lines): **664 insertions, zero deletions**. The R6 documentation has SHA-256 `B14BEBE46237977D8C009B0AE6217A7294AE0321AAF1489C9602FC88A73BEC20` and was committed with the approved Git blob. Neither R6 Python file changed between the original offline source and final commit.

## 3. Host regression evidence and limits

| Evidence checkpoint | Discovered | Passed | Known skips | Failures/errors | Meaning |
|---|---:|---:|---:|---:|---|
| M5 SQUALL offline checkpoint, 2026-11-10 | 301 | 300 | 1 | 0 | Historic offline baseline; M5 added documentation, not runtime |
| R5 SQUALL offline acceptance, 2026-11-11 | 771 | 770 | 1 | 0 | Includes 116 new synthetic R5 tests |
| R6 SQUALL local-commit checkpoint, 2026-11-11 | **924** | **923** | **1** | **0** | Includes all 153 new R6 cases and two genuine v0.7 reducer compatibility tests |

The sole permitted skip was `test_offline_supervisor.SyntheticSupervisorTests.test_rejects_symlinked_fixture_directory` because symlink creation was not permitted under the ordinary Windows account. **SEC-09 remains OPEN TEST GAP**; a skipped adversarial case is not a validated Windows symlink refusal. The Phase A audit read and recited historical SQUALL transcripts; it **did not independently rerun** 924 tests. No signed independent live attestation has been provided.

## 4. Operational and environment preservation

- Production `main` remained at `06ec81582791fc797f74ad294195d68b2023cb66`, with clean tracked state. No v0.8 change was merged or deployed.
- The original collector backup `windows/collector/Send-OnyxTelemetry.pre-v050.bak` retained SHA-256 `59E1EE7205EFBEDB79BA3D0DCB4C9FD0D8EBD3DFA4D5D9313BBD8325976830EB`.
- Both `%LOCALAPPDATA%\OnyxCore-v070-Release\Monitoring` and `%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring` retained their **five distinct, hash-pinned files**. No migration, initialization, overwrite or cleanup was authorized.
- Exact audited task definitions: `\LibreHardwareMonitor`, `\ONYX CORE - Local Gateway`, and `\ONYX CORE - Telemetry Collector`; exported XML before/after was unchanged. This does not assert anything about live task runtime or task last-run state.
- R6's inert classifier reports `live_release_decision=NO-GO`, `live_security_evidence_verified=false`, and refuses runtime, task creation, enrollment, probes, notification, delivery and repair.

## 5. Verification defects and resolved *checkpoint* errors

- The first R6 installer **created exactly three source files**, then failed at an incorrectly assembled Python import path containing a hidden vertical-tab character. The separately hashed resume gate fixed the *invocation*, verified original bytes and completed 924 tests. There was no R6 source edit and no second installation.
- The initial R6 staging script stopped before editing/staging because a Python `-c` version-check string lost its embedded quotes through PowerShell 5.1 argument passing. A separately hashed corrected script used a quote-free check, then documented acceptance and staged the exact three expected blobs. A later separately authorized local-commit script created `6e4ddef` and confirmed a clean worktree.
- These are **packaging/checkpoint script defects**, not demonstrated R6 runtime failures. They also are not evidence of live reliability.

## 6. Current disposition and next boundary

**Offline development and local commit history: accepted. Production release: NO-GO.** Nine independent security requirements (**SEC-01–SEC-08 and SEC-10**) remain **BLOCKED**, and the native Windows symlink case (**SEC-09**) remains **OPEN TEST GAP**. A positive live decision requires future independently reviewed implementations, safe and specifically authorized host exercises, complete closure evidence, and a new operator decision. It does not follow automatically from test counts or Git hashes.

This document is a **reviewable Phase C draft external to the repository**. Neither its preparation nor its read-only audit authorizes staging, commit, push, PR, merge, tag, release, deployment, Task Scheduler changes, live diagnostics, elevation, enrollment, notification, or repair.
