# ONYX CORE v0.8.0 — R5 Bound Foreground Runtime and Alert Cursor Integration

**Status:** Development-only, offline integration. **Baseline:** R4 commit `beee45a23eb2298643d88a3a8acf1c3e320729c6` (parent: RC3 commit `2d1d5c9bbb7c17254eb512d9955f8d3b9546c369`). Not a protected release candidate.

## What R5 proves

1. `OnyxV080SessionIntegration.py` connects the **R4 session supervisor** to the existing **v0.8 release binding** API using **one persisted cycle per bounded worker**. Its source, console and monitoring authorization callbacks are freshly invoked by the R4 supervisor. A session expires or refuses immediately on revoked consent, lost console, or source change; no extra cycle begins afterward. It rejects a nonrelease storage profile, incompatible interval, unverified worker result, notifications, repairs and task creation.
2. `OnyxV080NotificationIntegration.py` connects **R4 separate alert consent** to the existing **M5 per-event cursor**. Consent is evaluated before cursor initialization and again for each `Opened`/`Recovered` message. `Changed` is skipped by M5. Invalid, expired, revoked, wrong-source, wrong-SID, wrong-destination, or wrong-session authorization refuses before delivery. The cursor remains behind any denied/failed event (at-least-once retry); this is not exactly-once delivery.
3. Offline tests inject a fake worker and delivery callback; one test exercises the real **M3 disposable SQLite journal + M5 cursor** without sending HTTP or reading Windows credentials.

## Security boundary — NOT yet a live operator

The R5 modules contain **no trusted launcher, CLI live switch, Windows grant issuer or webhook configuration**. They cannot independently establish that a callback or JSON grant originates from an admin-protected trust anchor. There is **no new executable live path** in the protected RC3 operator. A caller passing fake `True` callbacks is a test fixture, **not authorization**.

Before activation, a later independently reviewed integration must:

- Pin the new modules (and all transitive imports) into the administrator-owned approval manifest and native NTFS/handle attestation file inventory. Changing pinned files requires a new frozen candidate and protected-installation review.
- Extend the installed operator to construct the real R4 callbacks from `OnyxWindowsRuntimeAttestation`, `OnyxWindowsUserConsent`, native console/session checks, and the existing Job Object/binding/bridge. Supply no developer-injectable authorizer on the operational CLI.
- Verify the per-cycle runtime reacquires native locks, bounds child execution, checks consent before both probes and journal writes, and cannot start if a previous session holds the lock. A false return is a **worker fault only**, never a consent or source denial.
- Independently approve and securely store a **separate** alert authorization, with explicit revocation and expiration. An existing monitoring grant **does not** authorize notifications. Recheck native source, session and alert grant before *each* send; bind provider, transport and destination hash. Never log webhook tokens, and never silently authorize private HTTP.
- Strictly bind release journal and cursor paths to the actual v0.8 release profile. Tests use a disposable path; that must not become a runtime override.
- Complete native tests for shutdown, revocation, worker restart budgets and cursor replay. Foreground session continuity does **not** mean 24/7 unattended operation.

## Scope protection

Exactly five **new** development files: two integration modules, two offline test suites and this contract. No existing source changed; no Git commit, push, tag, source release, protected installation, enrollments, diagnostics, notifications, repairs, tasks, services or gateway listeners.

**Release remains HOLD.** This patch demonstrates the composition but neither starts supervision nor delivers alerts from the installed release operator.
