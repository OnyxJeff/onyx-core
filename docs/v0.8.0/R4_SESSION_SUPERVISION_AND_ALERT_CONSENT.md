# ONYX CORE v0.8.0 — R4 Session Supervision and Alert Consent (Offline Foundation)

**Status:** Development-only, uncommitted; release remains HOLD. **Baseline:** RC3 commit `2d1d5c9bbb7c17254eb512d9955f8d3b9546c369`.

## Objective

Implement the **pure, deterministic foundations** of a supervised, consent-bound Windows/Pi monitoring session and a separate opt-in operational-alert authorization. Do not enable unattended 24/7 service operation, scheduling, automatic repairs, credential issuance, or delivery of notifications merely because the policy foundation passes tests.

## R4 supervisor policy

- Foreground session only, never a service or scheduled task.
- At most 20 successful diagnostic cycles and at most 24 hours, with an explicit elapsed-time limit. Interval 90–3600 seconds; success and worker failure tracked separately.
- Recheck **active local console**, **protected source** and **user consent** before each attempt and before/after every wait slice of at most two seconds.
- Honor expiration even if an attestation callback consumes time. Fail closed on revoked consent, lost session or source mismatch.
- Treat only an explicit `True` result as a completed cycle. Only an explicit `False` result is a retryable *worker-execution* fault, with bounded backoff and a maximum three consecutive failures. Other exceptions propagate; do not hide denial as a worker failure.
- The eventual live adapter MUST independently verify native ACL/source/identity, acquire the existing single-instance lock, contain the worker in the existing Windows Job Object, check authorization at actual probe/persistence boundaries, and confirm journal persistence. R4 policy alone cannot do these jobs.
- Existing M1/M2/M3 live components are not invoked by the policy or offline tests.

## R4 notification authorization

- Separate, user-approved, expiring notification consent; a *monitoring* grant does not authorize outbound alerts.
- Bind an exact source commit, Windows SID, release profile, event types `Opened`/`Recovered`, provider and hash of the exact destination. A consent value must have an independently verified origin; a user-controlled JSON document is **not** an authorization credential.
- Recheck consent and native session/source **for each message**, not only when a notification watcher starts.
- Maximum notification consent lifetime: 24 hours. `Changed` events are not delivered, consistent with the existing M5 watcher behavior.
- Future integration must validate transport security using the existing watcher, avoid disclosing URLs or tokens in logs, use its saved event cursor (at-least-once semantics), and stop delivery promptly on revoked approval.
- R4 does **not** issue grants, read Windows Credential Manager, register tasks, configure webhook addresses, or POST notifications.

## Acceptance and release boundaries

R4 adds exactly five **development-only** files: two policy modules, two test modules and this document. The main RC3 installation, v0.7.0 production, all release candidates/approval anchors, protected histories, Scheduled Tasks, network and Pi are not modified. Default audit makes no file changes; `-Apply` copies only reviewed development files and runs focused and full offline regressions, without commit.

Integration work still needed **before v0.8.0 release**:

1. Add native-release source inventory/manifest and standalone protected operator support for the supervisor and notification consent modules. Do not call unpinned modules from the protected installation.
2. Add an authenticated Windows grant issuer and revocation path for notification delivery separate from monitoring enrollment; prove expiry and concurrent revocation on SQUALL.
3. Integrate the session supervisor with existing Job Object worker, consent rechecks and M3 journal; prove shutdown, restart budgets and no double writes.
4. Integrate M5 watcher behind per-event authorization and an explicitly configured provider; prove no POST when revoked or expired and cursor recovery with safe synthetic endpoints.
5. Distinguish **session-bound continuous** monitoring from genuine **24/7 unattended** operation. Because RC3 requires the active local-console session and short-lived user approval, a true background service needs a separate security design and operator approval; it cannot inherit these permissions silently.
6. Produce next frozen candidate, repeat relevant native acceptance and rollback gates, and only then decide the release scope and publish.

This contract is a development foundation; it is **not** a claim that 24/7 monitoring or automatic alerts already work.
