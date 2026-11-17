# ONYX CORE v0.8.0 - R6.2B2A: Atomic Schema Initialization

**Status: isolated offline implementation proposal. v0.8.0-rc.1 remains on SECURITY HOLD.**

## Evidence and exact scope

- Input: SQUALL R6.2B1 source-review snapshot: 36 files verified against the uploaded SHA256 manifest.
- Archived source: development `047a753b5506729ac782b4a0d09a6074644580ed` and protected production `06ec81582791fc797f74ad294195d68b2023cb66`.
- The R6.2B1 release binding currently passes a fresh authorization callback to `record_cycle()`.
- Defect: on an empty SQLite DB, `_connect(write=True)` used `executescript(SCHEMA)`, which implicitly commits DDL before the incident-transaction authorization checks.

## Changes

1. `_connect(write=True, authorize_schema=...)` now executes the static schema's complete SQLite statements within a single explicit `BEGIN IMMEDIATE` transaction, with `PRAGMA user_version=1` in that same transaction.
2. When called via `record_cycle(..., authorize_commit=...)`, first-use initialization rechecks authorization **before the DDL transaction** and **immediately before its `COMMIT`**. Any denial, malformed DDL, or SQL exception rolls back the schema transaction.
3. Existing initialized DBs retain the prior three transaction-authorization checks. The existing R6.2B1 tests explicitly set up an empty initialized DB when testing those three boundaries, rather than assuming first-use schema commit has no consent checks.
4. Seven new synthetic tests cover denial before storage open, denial before DDL, denial at DDL commit, successful first-use commit, rollback after partial DDL, existing database behavior, and refusal to migrate unknown unversioned tables.

## Validation

In the reconstructed archive-only source subset, `python -B -m unittest discover -s tests/monitoring/v080 -p 'test_*.py' -q` completed **536/536 tests**. The source collector contains only a subset of the full v0.8 test tree; it **cannot** independently reproduce SQUALL's previous 1,363-test run. Expected SQUALL full-suite count after this patch: **1,370 tests** (with 9 previously skipped). This is a target, not a verified result.

## Security limits that remain

- A SQLite connection may create an **empty, uninitialized file** before the newly guarded schema transaction begins. This patch guarantees rolled-back **DDL**, not absence of every filesystem side effect.
- A schema or journal COMMIT started with valid consent may finish after revocation. Python cannot undo an in-progress disk commit. No hard deadline for whole-worker execution has been proven.
- M1/M2 still execute synchronously in the release parent's Python process. The existing Windows Job Object protects individual PowerShell and SSH subprocesses only, not the Python worker or SQLite writer.
- A separate child running under the **same Windows security identity** can still open a same-user journal. A Job Object alone does **not** enforce parent-only filesystem writes. Implement and independently verify restricted token/separate SID + ACL denial before enabling a child.
- R5 counts may diverge from the actual journal state after ambiguous late commits. The parent needs durable idempotence/reconciliation before automatic retry.
- A new reviewed, admin-pinned runtime-source manifest and native Windows acceptance are required before release.

## Next engineering checkpoint: R6.2B2B worker process

Build a fixed, pinned, read-only M1 worker launched suspended and assigned to a Windows Job Object before resumption. The trusted parent must retain consent/SID/source checks, hold mutexes, enforce one absolute monotonic deadline with bounded polling and Job termination on revocation or timeout, validate finite schema-bounded child output, and be the only process with OS-level write permission to the release incident journal. Evidence of child + descendant exit and refusal of journal access by the child must be demonstrated **natively on SQUALL**, not asserted by a self-reported JSON flag. Finally, reconcile a journal commit whose acknowledgment is lost, without blindly writing a duplicate.

No staging, commits, push, merge, tag, release, deployment, monitoring enablement, repair, notification, or Scheduled Task changes are authorized by this review package.
