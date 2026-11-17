# ONYX CORE v0.8.0 — R6.2B2E Durable Cycle Receipts

**Status: offline development proposal; v0.8.0 release HOLD until native host and independent approval gates.**

## Objective

Prevent a replay of *the same validated observation* from inserting a second check or duplicate incident transition when the first SQLite COMMIT may have completed without a clear acknowledgment. Persist no raw diagnostic output, tokens, secrets, or SSH credentials in receipts.

## Transaction contract

- The trusted parent derives a stable UUIDv5 operation ID from a SHA-256 digest of M3's allowlisted, validated observation. It is an idempotency key, **not** a credential or authorization substitute. A new probe with a fresh timestamp is a distinct observation; repeating the exact same observation uses the same ID.
- `record_cycle()` accepts optional `operation_id` for release callers. Legacy callers still work. On a write, acquire `BEGIN IMMEDIATE` before inspecting SQLite schema version to serialize concurrent first-run initialization.
- The `cycle_receipts` table is created as an additive v1 schema object **inside the authorized incident transaction**. Existing v1 journals are not replaced or reset. The receipt stores only `operation_id`, an allowlisted-observation digest, and the small allowlisted outcome JSON.
- Under that write lock, existing receipt + identical observation returns its committed outcome without inserting another check, event, or incident transition. Same operation ID + different observation is refused. Prior to COMMIT, the real release authorizer is checked again; refusal rolls back both receipt and incident changes.
- If Python reports an exception from COMMIT, close the writer, open a new **read-only** connection, and verify the exact receipt. If present and identical, accept the verified result; if absent, unreadable, or contradictory, raise `CommitOutcomeUnknown` and **do not automatically retry with a fresh ID**.
- The parent bridge is the only release path that enables receipts (`use_cycle_receipts=True`); legacy test injection and non-release calls retain old behavior. The contained child never receives journal write capability.

## Offline tests

The isolated reconstructed source subset ran **574 tests**, all passing, including **17 new receipt tests**: v1 compatibility, first-use initialization, revocation rollback, read-only lookup, conflicting IDs, simulated post-COMMIT acknowledgment loss, simulated pre-COMMIT failure, concurrent same-ID writes, stable identity and cross-session replay. It is NOT the authoritative SQUALL full-suite run.

**SQUALL acceptance target:** 1,408 tests discovered, 10 platform skips, no errors or failures, no Git operations or changes to production/v0.7.0 histories/v0.8.0 protected journal or installation.

## Explicit limitations / remaining release gates

1. A newly sampled observation is a new attempt. This mechanism deduplicates only an identical validated observation; it does not prevent a separate probe from recording a new check. It does not infer whether two distinct probes represent the same external incident.
2. A `COMMIT` that returned successfully but finishes after consent/deadline expiry may already be durable. The bridge still fails closed on post-record authorization; its in-memory completion count can disagree with the durable receipt. **Supervisor accounting/restart handling still requires independent acceptance.**
3. Persistent commit receipts do not guarantee exact physical disk-flush deadlines, protect against a malicious parent, or automatically recover a lost observation payload after total host/process failure.
4. Updating these source files invalidates any earlier digest manifest. The installed `C:\Program Files\OnyxCore\v0.8.0` source differs from this dev worktree. A reviewed source inventory, protected installation, pinned approval and real operational end-to-end acceptance are still REQUIRED.
5. Existing v1 SQLite files retain user_version=1; `cycle_receipts` is an additive table created transactionally for opt-in callers. The complete deployed schema and backup strategy require independent review before promotion.

No staging, commit, push, deployment, scheduled task, notification, live Pi probe, credential change or repair is authorized by this patch.
