# ONYX CORE v0.8.0 - R6.2A Deadline Guard Review

**Status: OFFLINE DEVELOPMENT ONLY; release security HOLD.**

Baseline commit: `047a753b5506729ac782b4a0d09a6074644580ed`.
Production baseline: `06ec81582791fc797f74ad294195d68b2023cb66`.

## Scope and observed behavior

This narrowly scoped code-only proposal:

- Prioritizes natural expiration ahead of consent checks at an absolute deadline.
- Counts a worker that returns after its deadline as an expired attempt rather than a successful timely cycle.
- Binds the runtime bridge's `authorize_cycle` callback to the parent foreground session's monotonic deadline, including a check before and after native authorization.
- Rechecks runtime authorization after probe return and after recorder return. Late results now fail closed instead of falsely returning a successful runtime result.
- Preserves R4's existing three-consecutive-failure policy and exception propagation.

## Explicitly NOT proven

- The synchronous worker still runs in the operator's interpreter. It is NOT terminated at the deadline. This patch only detects expiry after control returns.
- The recorder currently includes SQLite COMMIT. A write can begin before revocation or expiry and finish afterward. Post-recorder rejection cannot undo it.
- R5's persisted-cycle count and R4's completed-cycle count can diverge after a late write; the existing integration will refuse with a mismatch. That is safer than a false success, but it does not demonstrate clean state or no-write guarantees.
- The existing diagnostic subprocess Job Object does not contain the entire Python probe/persistence cycle.
- The four initial red-phase tests are baseline demonstrations; they should not be treated as final security gate tests. New focused tests verify only R6.2A's limited behavior.

## Verification

In an isolated copy, 47 preexisting R4-R6 unit tests and 6 new R6.2A tests passed. This is neither the full SQUALL suite nor Windows native host acceptance.

## Blocking R6.2B work

Before any live release, complete a reviewed full-worker/descendant containment boundary, parent-only journal writes with bounded SQLite transaction policy, native process-exit verification, deadline-authorized commits, no late/duplicate persistence testing, renewed protected 18-file source inventory (or independently reviewed new inventory), and Windows host acceptance. Unattended services and notification delivery remain unapproved.

Do not stage, commit, tag, merge, push, deploy, enroll, or activate monitoring based solely on this patch.
