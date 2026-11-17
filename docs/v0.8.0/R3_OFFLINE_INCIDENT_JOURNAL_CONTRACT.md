# ONYX CORE v0.8.0 — R3 Offline Persistent Incident Journal Contract

**Scope:** R3 / SEC-06 — crash-safe *synthetic* incident persistence, durable replay refusal and undelivered intent journal.  
**Pinned SQUALL parent:** `61c33607e9f4fc7a5ecd4a77cef686cf50580d60` on `feature/v0.8.0-continuous-monitoring`.  
**Production pinned and untouched:** `06ec81582791fc797f74ad294195d68b2023cb66` on `main`.  
**Decision:** OFFLINE development and testing only; no runtime, installation, operator enrollment, notification, deployment, task creation or repair. Live v0.8.0 release **NO-GO**.

## 1. Architecture and trust boundary

The file `windows/monitoring/v080/OnyxOfflineIncidentJournal.py` is a **Python 3.13 temporary-fixture library**, not a Windows service or a CLI database management tool. Its command line accepts only `--check-inert`; it has no `--start`, `--persist`, `--enable`, `--notify`, `--live`, `--repair` or `--migrate` capability. It imports the checked-in M3 *synthetic* event lifecycle validator from its own directory, so M3's event schema, timestamp window, deterministic ID and transition rules remain binding.

Only tests can create a journal, and only within a **caller-created, empty `onyx-r3-*` directory directly beneath Python's temporary root**. The journal file is exactly `synthetic-incident.sqlite3`; no production, v0.7.0 release, v0.7.0 development, collector or application-state directories are accepted. Lexical, resolution, junction, symlink, missing-file, inventory and size checks are defense-in-depth only. They do **not** attest NTFS ACLs or prevent every TOCTOU attack; SEC-01/02/09 remain open.

This R3 module intentionally **writes test fixture SQLite files**; unlike the read-only R2 evidence contract, it must persist simulated state in order to test durability. It never opens or writes protected monitoring histories, does not connect to the Pi, and has no notifier or Windows API binding. Its `store_modified` field reports writes to the temporary fixture only, while `runtime_enabled`, `live_probe_authorized`, `enrollment_authorized`, `task_creation_authorized`, `notification_enabled` and `delivery_permitted` remain `false`.

## 2. Journal contents and commit ordering

SQLite uses rollback journal mode (`DELETE`), `synchronous=FULL`, and `BEGIN IMMEDIATE` for atomic appends. An application ID and schema version are mandatory. The database has exactly three tables and one explicit index:

- `meta` contains the M3 state snapshot, its SHA-256, head chain digest and next sequence number.
- `event_journal` contains *all* accepted synthetic event identities, canonical event JSON, event digest, pre/post state snapshots, references and a consecutive SHA-256 linked record chain.
- `intent_journal` contains globally deduplicated synthetic proposed intents, bound to an event/sequence, with the immutable status `NotAttempted`. An intent is **never** a delivery or a real operator authorization.

For each append, the code verifies the entire existing journal and SQLite integrity, validates the complete incoming synthetic M3 batch, checks previously seen event ID/digest conflicts and applies **new** events using M3's existing reducer one at a time. State, event identity and undelivered intent are written in **one transaction**. Any invalid event in a mixed batch, tampered row, failed SQL statement or exceeded cap aborts the entire batch. A repeated event with the exact original body is suppressed without another durable intent. A repeated ID with changed content is refused. Duplicates older than M3's in-memory window remain suppressed using the durable event index.

SQLite and the deterministic SHA-256 chain are **accidental-corruption and consistency checks**, **not** authentication against an attacker able to rewrite the database and recompute hashes. No trusted hardware clock, NTFS token, tamper-proof key or externally anchored checkpoint exists. A changed M3 state cannot be promoted into a live incident report.

## 3. Restart/crash and retention rules

Offline fault injection covers failure **before commit** (rolled back), lost confirmation **after commit** (a retry is suppressed), and an abrupt test subprocess termination before commit. A crashed test worker may leave a SQLite rollback-journal marker. The explicit `recover_test_fixture_after_crash()` operation is restricted to the same test-owned temporary directory: SQLite resolves the interrupted transaction and the entire journal is reverified. Some SQLite versions leave a harmless cold rollback-journal marker until subsequent use; code never deletes or migrates it. Normal inspection never changes a clean fixture database.

The retention policy is **non-destructive, fail closed**: maximum 512 durable event IDs, 512 distinct intent keys and a 32 MiB SQLite file. M3's bounded in-memory window is compacted to the most recent 24 entries after each validated transition, but old durable event and intent IDs are never discarded. On exhaustion, operations refuse input; they do not erase replay evidence or silently re-send alerts. Production backup, key management, checkpoint anchoring, journaling under interrupted storage power loss, archival, pruning, migration and disaster recovery are **not** implemented. A separate security review and explicit authorization are required before designing live retention or backups.

## 4. Adversarial acceptance and expected provenance

`tests/monitoring/v080/test_offline_incident_journal.py` adds **67 tests** covering:

- schema/provenance/disabled CLI guards; healthy/open, suspect, escalation, recovery, evidence loss and Unknown masking from actual M3 synthetic transitions;
- restart in a new process, duplicate replay both immediately and after the M3 in-memory window rolls over, changed-content ID collisions, intent uniqueness and `NotAttempted` status;
- atomic failure on mixed valid/invalid batches, injected pre-commit rollback, post-commit lost response and actual subprocess crash before commit followed by explicit test-fixture recovery;
- state, event, chain, schema, application-ID and intent tampering; unexpected/missing files, symlink/junction/nested/wrong-root refusal, and read-only inspection;
- no silent retention eviction, bounded writer lock, safe snapshot copies and no live network/Windows/Scheduler/notification imports.

**SQUALL acceptance target:** exactly **550 discovered offline tests** = the prior 483 + 67 R3, including M3=61, M4=64, R1=85, R2=97, and both genuine checked-in v0.7.0 reducer compatibility cases. All must pass, with no skips or only the pre-existing `test_offline_supervisor.SyntheticSupervisorTests.test_rejects_symlinked_fixture_directory` skipped because symlink creation is not permitted. The new R3 symlink test has a refusal fallback rather than adding another permission-dependent skip. Offline R3 synthetic fault tests do not validate hardware power-loss durability or real Windows process/job containment.

The guarded SQUALL installer must verify **all 29 committed M1–M5/R1/R2 source and document hashes**, the exact parent, clean worktrees, preserved original collector backup, both protected five-file v0.7.0 history inventories, and the three audited Scheduled Task definitions. It verifies the three archive members and SHA-256 digests before creating exactly three **untracked** new files, runs the complete offline suite and rechecks every protected invariant afterward.

## 5. Stop rules and release disposition

The installation checkpoint does **not** stage or commit files and does not touch the production repository or its Scheduled Tasks. If any file was created before a failure, **do not rerun**, delete, reset, clean or repair automatically. Record the output and inspect exact state first. Documentation review and Git staging each require separate authorization; any local commit requires another separate authorization. No push, PR, merge, tag, release, production integration, notification, enrollment, diagnostics, elevation or repair is implied.

**SEC-06 remains BLOCKED for live readiness** despite the synthetic durable journal. Independent Windows identity/ACL attestation, authentic evidence and clock, proven real Windows worker isolation, durable authenticity/recovery design, backup/disaster recovery validation and an independent security review are still required. This milestone must never be advertised as operational unattended monitoring.

## 6. SQUALL R3 host acceptance — 2026-11-11

**Checkpoint:** PASS for *offline synthetic development only*, on SQUALL with the exact local R2 parent `61c33607e9f4fc7a5ecd4a77cef686cf50580d60` on `feature/v0.8.0-continuous-monitoring`.

- The R3 source ZIP, installer ZIP, and Windows PowerShell 5.1 script passed the provided SHA-256 checks; PowerShell syntax parsing succeeded. The guarded installer verified the exact three archive members by name, size, and SHA-256 before writing files.
- The SQUALL preflight verified the pinned R2 HEAD, clean development/production worktrees, all **29** previously committed M1–M5/R1/R2 file hashes, the original collector backup, and both distinct five-file protected v0.7 monitoring histories. The **three audited** Scheduled Task definitions were captured read-only.
- Exactly three new R3 files were installed without overwrite: this Markdown contract, `test_offline_incident_journal.py`, and `OnyxOfflineIncidentJournal.py`.
- The integrated SQUALL suite ran **550 tests: 549 passed, 1 skipped, 0 failures or errors**, including all **67 R3**, **97 R2**, **85 R1**, and both genuine checked-in reducer compatibility tests.
- The only skip was `test_offline_supervisor.SyntheticSupervisorTests.test_rejects_symlinked_fixture_directory`, because `symlink creation not permitted`. The R3 symlink refusal test passed without introducing an additional skip; this does not establish real Windows symlink/ACL security.
- R3's host tests covered abrupt test-subprocess termination and explicit temporary-fixture recovery, restart replay suppression, lost post-commit confirmation, SQL rollback, journal/intent tamper detection, and fail-closed retention limits. These are **synthetic fixture tests**, not hardware power-loss or authenticated incident-history proofs.
- M1 remained disabled; the M2A–M4/R1/R2/R3 inert checks reported no live operation, notification, enrollment, task creation or repair. R3 reported `provenance=SyntheticTemporaryFixtureOnly`, `temp_fixture_only=true`, `store_modified=false` for its inert check, and `runtime_enabled=false`.
- Final SQUALL verification reported unchanged production, the original collector, both distinct five-file v0.7 histories, and all three Scheduled Task definitions. The development HEAD remained the pinned R2 commit, with **exactly three untracked R3 files** and nothing staged or committed.
- No push, merge, tag, release, deployment, Scheduled Task modification, live probe, elevation, enrollment, notification or repair occurred.

**Security disposition:** SEC-06 remains **BLOCKED** for authenticated incident evidence, trustworthy backup/recovery and live replay guarantees. SEC-01/02/03/04/05/09 attestation gaps also remain; this offline success does **not** permit unattended monitoring. **Live v0.8.0 release: NO-GO.**

**Next authorization boundary:** Documentation review/staging, any local commit, real Windows diagnostic/attestation, deployment, and release each require separately granted permission. This reviewed preview makes no change to SQUALL or either repository.
