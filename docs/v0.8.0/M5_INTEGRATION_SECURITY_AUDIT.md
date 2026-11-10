# ONYX CORE v0.8.0 — M5 Integration and Security Boundary Audit

**Artifact:** Development-only, offline review.  
**Baseline:** `27071dcdbb41616096107bfa3a7fcc8be337b7ce`, branch `feature/v0.8.0-continuous-monitoring`, worktree `D:\github_repos\onyx-core-v080`.  
**Production baseline to preserve:** `06ec81582791fc797f74ad294195d68b2023cb66` on `main`.  
**Decision:** **Offline validation candidate; NO-GO for unattended monitoring, production deployment, or release publication.**

## 1. Evidence and assessment method

This audit is based on the committed M1–M4 Python modules, reviewed milestone contracts, the original v0.7.0 reducer compatibility tests, and operator-provided SQUALL acceptance transcripts through the M4 commit. Prior M4 host output reported **301 discovered tests, 300 passed, one known Windows symlink-permission skip, zero failures**, including all 61 M3 and 64 M4 cases and both genuine-reducer compatibility cases. This establishes test results for the pinned *offline* development snapshot, not a trusted live Windows or network assessment. M5's own host recheck is **pending** until its guarded installer returns an independent success log.

The M5 installer is limited to adding four Markdown documents under `docs/v0.8.0/`. It pins hashes of all 19 M1–M4 source/document/config artifacts, requires a clean development HEAD, reads—not mutates—Task Scheduler definitions and both protected history inventories, checks the inert CLI contracts, and executes the complete preexisting 301-test suite. It introduces no new executable repository code and does not change the test count.

## 2. Integration path and authority

| Stage | Committed code boundary | Verified offline behavior | NOT established |
|---|---|---|---|
| M1: unattended policy | `OnyxUnattendedPolicy.py`; disabled `monitoring.unattended.example.json` | Strict config/enrollment schema, hypothetical matching; `--check-example` only | Live consent, real Windows identity, enabled policy, runtime capability |
| M2A: supervisor | `OnyxOfflineSupervisor.py` | Fixed synthetic Python subprocess, temporary lock, timeout/kill-tree exercises; `--check-inert` only | Atomic containment for a real diagnostic worker; real task/scheduler behavior |
| M2B: authorization | `OnyxOfflineAuthorization.py` | Synthetic config, account, SID, source digest, ACL, revocation and consent matching; `--check-inert` only | Authentication, actual NTFS DACL inspection, trusted revocation store |
| M2C: evidence | `OnyxOfflineEvidenceIntegration.py` | Synthetic bounded observation validation, fixed M2A fixture, real checked-in v0.7.0 **pure reducer** used in memory | Independent live read-only collection, trusted observations, isolated atomic v0.8.0 state |
| M3: alerts | `OnyxOfflineAlertLifecycle.py` | In-memory event/intent dedup, synthetic acknowledgement, evidence-loss handling, recovery candidates | Persistent dedup journal, notification delivery, restart replay control |
| M4: operator view | `OnyxOfflineOperatorView.py` | Static escaped HTML and text for validated synthetic M3 results; no JavaScript or polling | Live UI, authenticated operator controls, actual health or delivery status |

**No runtime trust chain exists across these stages.** The integration is exercised by test harnesses and importable in-memory functions, not by a source-bound, permissioned production supervisor. A `--check-inert` success is a denial of capability, not a deployment-ready feature flag. No earlier component may be promoted by changing `enabled`, using an existing SSH key, trusting self-reported booleans, or scheduling a v0.7.0 release launcher.

## 3. Security and correctness findings

| ID | Finding / current behavior | Live readiness | Required closure evidence |
|---|---|---|---|
| SEC-01 | M1 approved-looking JSON and M2B simulated consent are **data only**; a fixture author can forge them | **BLOCKED** | Independently authenticated operator grant with per-cycle identity/source/config checks, revocation and fail-closed disable |
| SEC-02 | Simulated SID, DACL and source digests do not inspect real Windows tokens or every ancestor/inherited ACE | **BLOCKED** | Real token/session and NTFS ACL attestation, final-path checks, race-safe source/config validation |
| SEC-03 | M2A fixture-specific stdin gate is not atomic process containment for an arbitrary Windows worker | **BLOCKED** | Windows start-suspended/job-object or equivalent safe containment, full tree timeout/abort tests |
| SEC-04 | Existing v0.7.0 release evidence collector **writes** `recovery-observations.json` to protected release history | **BLOCKED** | Independently reviewed v0.8-only read-only evidence adapter; provable avoidance of both v0.7.0 stores |
| SEC-05 | M2C timestamps are relative to a **synthetic reference**, not an attested host clock; classifications are simulated | **BLOCKED** | Trusted live evidence and time/clock semantics with explicit unknown/error handling |
| SEC-06 | M3 event IDs and hashes establish consistency, **not authenticity**; 256-record in-memory ledger refuses exhaustion; no restart durability | **BLOCKED** | Crash-safe v0.8-only incident/intent store, replay policy and retention/backup validation |
| SEC-07 | M4 renders snapshot text without active controls or network; a synthetic `acknowledged` actor is not a Windows identity | **BLOCKED** for live UI | Separate authenticated operator action protocol, safe read-only live renderer, independent authorization for any action |
| SEC-08 | No real notifier/delivery journal, missed-run policy, or independently tested desktop-session delivery exists | **BLOCKED** | Opt-in local notification design, dedup/delivery audit, explicit separate authorization |
| SEC-09 | M2A symlink-creation refusal test is skipped on SQUALL for user privilege limitations | **OPEN TEST GAP** | Run adversarial path test under separately approved Windows test conditions; no elevated installer implied |
| SEC-10 | No measured live 120-second polling cadence / 90-second budget, restart/overlap, 30–300-second recovery spacing or five-minute corroboration under jitter | **BLOCKED** | Offline integration/hardware timing tests, then separately approved bounded live acceptance |

## 4. Protected invariants

- Production `D:\github_repos\onyx-core` remains `main` at `06ec81582791fc797f74ad294195d68b2023cb66` during M5 review; no tracked changes. The original collector backup `windows\collector\Send-OnyxTelemetry.pre-v050.bak` retains SHA-256 `59E1EE7205EFBEDB79BA3D0DCB4C9FD0D8EBD3DFA4D5D9313BBD8325976830EB`.
- Both `%LOCALAPPDATA%\OnyxCore-v070-Release\Monitoring` and `%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring` retain **exactly five expected files**, including `incident-state.json.lock`, with the hashes pinned in the M5 checkpoint. No deletion, initialization, rewrite, migration, or rollback into these stores is allowed.
- Existing ONYX CORE / LibreHardwareMonitor Scheduled Task **definitions** are captured read-only before and after the offline suite and must compare equal. Runtime state/last-run timestamps are not proof of an unchanged definition, and the checkpoint does not start/stop/enable/disable any task.
- The v0.7.0 manual release flow, task definitions, networking/ICS, SSH key restrictions, Pi, bearer token and DPAPI secret are not touched. The M5 package makes no remote or network requests.
- The source-target folders and paths are checked for redirection before any new files are created. After the first file write, do **not** rerun a partially completed installer.

## 5. Test gate and disposition

**Required SQUALL gate:** Python 3.13 `unittest` discovers **exactly 301** cases (including M3=61, M4=64 and both checked-in v0.7.0 reducer tests), runs all, and reports zero failures/errors with **no skips** or only `test_offline_supervisor.SyntheticSupervisorTests.test_rejects_symlinked_fixture_directory` skipped. All five M2A–M4 inert CLI checks must deny runtime, live probe, task creation and repair. The M1 example must remain disabled.

The installer must then recheck source hashes, exact four **untracked M5 Markdown files**, unchanged dev parent, production, backup, histories, and task definitions. A successful host recheck approves **documentation for separate review only**; it does not prove a live service, approve local Git commit, or grant any network/scheduling/deployment permission.

**Release verdict:** Offline M1–M4 implementation **can proceed to source/document review** if these checks pass. The actual unattended feature and production release **remain NO-GO** until SEC-01–SEC-10 and the independently authorized rollout gates are closed. Do not publish a v0.8.0 release with claims of operational unattended monitoring on the basis of this audit.
