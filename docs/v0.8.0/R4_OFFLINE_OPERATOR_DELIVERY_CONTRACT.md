# ONYX CORE v0.8.0 — R4 Offline Operator Controls & Alert Delivery Contract

**Development boundary:** strictly offline, synthetic-only, operator-reviewed. **Not deployable.**

## 1. Scope and parent

- Required parent: `47cf9405e9718026d3ec3e90230c5a7e60b01ba5` on `feature/v0.8.0-continuous-monitoring` in `D:\github_repos\onyx-core-v080`.
- This checkpoint adds exactly three files: this document, `windows/monitoring/v080/OnyxOfflineOperatorDelivery.py`, and `tests/monitoring/v080/test_offline_operator_delivery.py`.
- No existing M1–M5, R1, R2, R3, production, collector, v0.7 state-history, or Scheduled Task file is modified.
- No external network calls, live probes, Windows authentication, privilege elevation, SSH, enrollment, notification delivery, task actions, repair or production store migrations.
- CLI accepts **only** `--check-inert`. No execution, alert delivery, or fixture flags are permitted via CLI.

## 2. Input trust boundaries

### R3 ledger input

- R4 opens a **test-created R3 temporary** `onyx-r3-*` SQLite journal read-only using the reviewed R3 schema, full synthetic replay validation, source/intent digests and R3 `NotAttempted` state.
- Initialization freezes the verified R3 head, event count, alert snapshot and intent proposals into the separate R4 fixture. Every R4 read/write re-verifies the R3 fixture and refuses a changed source snapshot.
- The R3 journal remains immutable during all R4 operations. R4 never reads or touches either protected v0.7 history.
- The R3 SHA-256 record chain is unkeyed and cannot prove authentic real-world evidence or an independently trusted baseline.

### Operator control and synthetic grants

- All actors are explicitly `synthetic:*`; no Windows logon token, credential, authenticated identity, genuine consent, trustworthy authorization or authoritative revocation is established.
- Each **data-only** mock grant is tied to the actor, incident, role `Responder`, sorted allowed scopes, canonical UTC issue/expiry times (no longer than 15 minutes), nonzero test-only revocation generation, and `revoked=false`.
- Claims that Windows identity is authenticated, that revocation is authoritative or that delivery is authorized are refused. Invalid, expired, not-yet-valid, revoked, mis-scoped, forged or structurally incorrect grants fail closed.
- The `Observer` role cannot perform writes. These role rules are a **simulation of policy enforcement**, not a substitute for an OS-backed identity and consent boundary.
- Request IDs bind canonical JSON to `req-` plus 24 lowercase hex SHA-256 characters. Identical IDs with identical body suppress replay; conflicting or invalid identities are refused.
- All requests use canonical microsecond UTC `Z` timestamps and disallow new backdated actions.

## 3. Operator and delivery-state transitions

The implementation imports the **checked-in M3 pure synthetic acknowledgement validator**, preserving M3 incident, phase, evidence and actor rules. An acknowledgment is accepted only for a matching open synthetic incident with complete evidence; it never resolves an incident or changes R3.

| R4 action | Required prior state | Result in **R4 temporary journal only** |
|---|---|---|
| `Acknowledge` | Matching open incident, complete evidence, unacknowledged | Synthetic M3 acknowledgement snapshot |
| `Plan` | Verified R3 intent, `NotEvaluated`, complete evidence | `SimulatedWouldSend` |
| `Suppress` | `NotEvaluated` or `SimulatedWouldSend` | `SimulatedSuppressed` (terminal) |
| `Uncertain` | `SimulatedWouldSend` | `SimulatedUncertain` (terminal; no automatic retry) |

No action is a real notification or confirms a transport attempt. **`SimulatedWouldSend` means only a decision; `SimulatedUncertain` means a fabricated ambiguous outcome, not a real attempt.** There is no `Delivered`, email, HTTP, webhook, SMTP, recipient, retry worker, send queue, network client, background service, or task registration. All responses expose `delivery_permitted=false`, `notification_enabled=false`, `transport_calls=0`, and `runtime_enabled=false`.

## 4. Durable synthetic R4 journal

- The caller explicitly supplies a newly created, empty, direct `onyx-r4-*` folder beneath the Python temporary directory; SQLite writes are confined to `synthetic-operator.sqlite3` inside that folder. This narrow Python path check is **not an OS security boundary or race-proof ACL attestation**.
- Only an explicit test call initializes the empty R4 fixture. All other calls refuse missing, redirected, oversized, or unexpected files.
- Uses SQLite `synchronous=FULL`, rollback journal (`DELETE`), `BEGIN IMMEDIATE`, unique request IDs, immutable initial R3 snapshot, ordered action log, canonical JSON, SHA-256 chains and independently rebuilt state verification.
- Each request, state transition, request ID and resulting decision are committed atomically. Injected `before_commit` faults roll back; lost `after_commit` responses are safely deduplicated by committed request ID upon retry.
- Retention cap: **128 R4 actions and 128 imported R3 intents**. Exhaustion fails closed: no eviction, silent replay-history deletion or automatic pruning. This is a deliberate proof-of-contract limit, **not an operational retention policy**.
- Read-only inspection replays the synthetic journal for corruption, missing or extra records, tampered metadata, forged decisions or mismatched snapshots. Unkeyed SHA-256 chains cannot resist a knowledgeable attacker who can rewrite the entire database consistently.
- The simulation does not claim production crash durability on every filesystem/storage controller, authenticated actor identity, secure revocation, production backups or at-least/exactly-once notification semantics.

## 5. Offline host acceptance

- New focused suite: **105 R4 tests**, including permissions, mock-grant forgery, partial evidence, replay after Python process restart, request collisions, failed/ambiguous delivery decisions, tampered SQLite, R3 snapshot drift, rollback, lost post-commit confirmation and no notification side effects.
- Prior SQUALL integration baseline: **550 tests** (R1 85, R2 97, R3 67), with only the known Windows symlink-creation permission skip.
- Required host integration after no-overwrite installation: **655 total** (550 baseline + 105 R4), zero failures/errors; **at most one** skip, exactly `test_offline_supervisor.SyntheticSupervisorTests.test_rejects_symlinked_fixture_directory`.
- Two checked-in v0.7 reducer compatibility tests remain mandatory. Host acceptance cannot be inferred from focused tests or from the isolated development runner, which lacks the production reducer and differs from the full SQUALL baseline.
- Prior hash-pinned **32** M1–M5/R1–R3 artifacts, production `main`, the original collector backup, both exact five-file protected v0.7 monitoring histories, and exactly three read-only snapshotted Scheduled Task definitions must be verified before and after.
- After host success, **exactly three untracked R4 files**. No staging, commit, push, merge, tag, release, deployment, enrollment, real diagnostic, elevation, notification, task modification or repair.
- If an installation fails after any file is created, **do not rerun, overwrite or reset Git**. Inspect the partial state first.

## 6. Security disposition

**R4 offline policy-model checkpoint only.** Independent Windows operator authentication, authoritative grants and revocation, immutable evidence, real notification transport authentication, genuine delivery confirmation, crash-safe exactly-once semantics, and operational consent remain unresolved release blockers. No SEC finding is closed for live use by these synthetic tests.

**Production remains v0.7.0. Live unattended monitoring: NO-GO.** A separate operator authorization is required for review/staging, and another for any local commit. Live enablement is outside this checkpoint.

## 7. SQUALL R4 host acceptance — 2026-11-11

**Checkpoint:** PASS for *offline synthetic development only*, on SQUALL (Windows PowerShell 5.1) with pinned R3 parent `47cf9405e9718026d3ec3e90230c5a7e60b01ba5` and development branch `feature/v0.8.0-continuous-monitoring`.

- The R4 source ZIP, installer ZIP and PowerShell script passed the operator's SHA-256 verification; the script passed PowerShell syntax parsing. The guarded installer validated exactly three ZIP members by path, size and SHA-256 before any installation.
- Preflight confirmed the pinned R3 HEAD, clean development and production repositories, all **32** prior M1–M5/R1/R2/R3 artifact hashes, the original collector backup and both separate protected **five-file** v0.7 monitoring histories. Exactly **three audited Scheduled Task definitions** were captured read-only.
- The installer added exactly three R4 files without overwrites: this contract, `tests/monitoring/v080/test_offline_operator_delivery.py`, and `windows/monitoring/v080/OnyxOfflineOperatorDelivery.py`.
- On SQUALL the integrated suite ran **655 tests: 654 passed, 1 skipped, 0 failures or errors**. This included all **105 R4 tests**, **67 R3 tests**, **97 R2 tests**, **85 R1 tests**, and both genuine checked-in v0.7 reducer compatibility tests.
- The only skip was `test_offline_supervisor.SyntheticSupervisorTests.test_rejects_symlinked_fixture_directory` because `symlink creation not permitted`. This remains an unresolved platform-specific security-test gap, not a passed symlink/ACL attestation.
- Passing R4 cases covered mock operator grant scope and revocation checks, M3-compatible synthetic acknowledgment, simulated decision states, restart/replay and idempotency, pre-commit rollback and lost post-commit response handling, R3 snapshot preservation, corrupted/tampered SQLite refusal and no delivery side effects. These results validate **synthetic fixtures only**.
- M1 remained disabled; M2A–M4/R1–R4 inert checks reported no live probes, task creation, repair or notification delivery. R4 reported `provenance=SyntheticTemporaryFixtureOnly`, `temp_fixture_only=true`, `transport_calls=0`, `notification_enabled=false`, `runtime_enabled=false`, `identity_authenticated_in_windows=false` and `revocation_authoritative=false`.
- Final host checks confirmed production, the original collector backup, both protected five-file v0.7 histories and all three audited Scheduled Task definitions unchanged. The development HEAD remained the pinned R3 parent with **exactly three untracked R4 files**, none staged or committed.
- No push, merge, tag, release, deployment, live diagnostic, elevation, enrollment, notification, task modification or repair was performed.

**Security disposition:** Independent Windows operator identity, authoritative revocation, authenticated notification transport and delivery-confirmation semantics remain **BLOCKED**. The unkeyed synthetic SQLite journal and mock grants do not establish live security or exactly-once notification delivery. **Live v0.8.0 release: NO-GO.**

**Next authorization boundary:** Review/staging of these three R4 additions and any subsequent local commit require independent operator approval. This preview itself does not modify SQUALL or either repository.
