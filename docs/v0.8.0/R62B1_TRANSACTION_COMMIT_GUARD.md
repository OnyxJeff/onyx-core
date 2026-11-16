# ONYX CORE v0.8.0 — R6.2B1 Transaction Commit Guard

**Status: OFFLINE DEVELOPMENT PROPOSAL; RC1 release security HOLD.**

## Scope

R6.2B1 adds an optional, fail-closed authorization callback to M3's `record_cycle()` and explicitly supplies it through the protected release binding's runtime bridge.

The v0.8 release binding now supplies `transactional_recorder=m3.record_cycle` to the bridge. The bridge's parent-side `guarded_record` invokes the transactional recorder with a fresh, independently rechecked `authorize_commit` callback. M3 checks that callback **before opening** the SQLite store, **before `BEGIN IMMEDIATE`**, and **inside the transaction immediately before `COMMIT`**. A denied or non-boolean callback raises and rolls back in-flight changes. Old non-release/inert callers retain the existing optional callback behavior and the compatibility tests must continue passing.

The callback must come from the pinned release operator's real authorizer. Synthetic callbacks used in tests are not authorization for production. This does not install a new process, service, task, notification channel, or repair capability.

## Validated in an isolated source copy

- 21 existing Phase 18I tests passed, including the corrected revocation test fixture.
- 47 existing R4, R5 and R6 session tests passed.
- 6 R6.2A deadline tests passed.
- 9 new R6.2B1 transaction authorization tests passed.
- Total: 83 focused offline tests passed. **The full 1,363-test SQUALL suite has not yet been executed with this proposal.**

## Explicitly not guaranteed

1. **No hard process timeout.** The existing parent interpreter executes the Python monitoring loop synchronously. The native Job Object protects individual diagnostic subprocesses; it does NOT currently contain the entire monitoring worker.
2. **No strict no-late-durable-write guarantee.** A SQLite `COMMIT` permitted while consent is valid may complete a disk flush after its deadline or after revocation. Pre-COMMIT checks cannot reverse a commit already started. A post-recording rejection is only fail-closed reporting, not rollback.
3. **No reconciled post-commit accounting.** The R5 supervisor and bridge may disagree about a cycle that committed but returned after the deadline.
4. **No protection against a compromised same-privilege Python worker.** Separate process and OS-level filesystem permissions must prevent a child from touching a parent's journal.
5. **No source inventory promotion.** Updating these source modules invalidates the existing hash-pinned protected release inventory. Re-attestation and independent review are required before host acceptance.

## Required next checkpoint

R6.2B2: whole diagnostic-worker child process running under a Windows Job Object, restricted child privileges and inherited handles, parent-only SQLite writer, bounded cancellation, authoritative exit cleanup and post-commit reconciliation. Validate using synthetic long-running child, late result, descendant-survival, invalid child output, revocation during commit, and restart ambiguity tests. Keep current release HOLD until independently verified.

No commit, push, tag, deployment, enrollment, scheduled task, notification, live probe, or production change is authorized by this package.
