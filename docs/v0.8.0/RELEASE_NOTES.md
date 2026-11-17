# ONYX CORE v0.8.0 — Continuous Monitoring & Operational Alerts

**Release type: GitHub code-only release.** This publication does **not** deploy v0.8.0 to SQUALL. Installed production remains v0.7.0.

## Highlights

- Opt-in foreground read-only Windows/Pi USB connectivity monitoring components and protected-session policy.
- v0.8-isolated SQLite incident state, `Opened`, `Changed`, and `Recovered` lifecycle events, receipts, and restart deduplication.
- Read-only `/api/v1/monitor/summary` and monitoring dashboard: development loopback `127.0.0.1:18767`, explicitly launched release profile `127.0.0.1:18768`; v0.7.0 gateway and OBS overlays remain on `127.0.0.1:18766`.
- Optional separate notification watcher (ntfy, Discord, generic JSON webhook) stays **disabled by default**; delivery is not automatically started or accepted as part of the protected operator.
- New offline-only route, adapter, gateway, path, and Low Integrity acceptance prototypes. A synthetic `SimulatedEligible` receipt **never** attests native Windows behavior or grants runtime authorization.
- Receipt-consistency hardening rejects contradictory simulated decisions and adds adversarial regression coverage.

## Validation

- SQUALL final v0.8 offline regression: **1574 tests, 11 expected skips, zero failures/errors**.
- Nine PowerShell synthetic route-evidence cases passed.
- Original protected collector backup and v0.7 production Git baseline verified before publication; protected histories, tasks and installation not changed by release workflow.
- Earlier independent host checks: five synthetic Windows containment cases and eight release-path read-only access checks, as recorded in previous release-readiness evidence.
- Results are host-run reports, **not GitHub CI**; no live Windows/Pi end-to-end approval is claimed.

## Not enabled / not accepted

- No automatic monitoring Scheduled Task, network/ICS repair, unattended polling service, automatic credentials or notification delivery.
- No production gateway or telemetry collector replacement.
- No validated native Windows Low Integrity acceptance for the new offline prototypes.
- Protected installed-source equivalence, signed approval anchor, real foreground acceptance, native host attestation and operational rollback remain separate work.

## Documentation

- [Code-only release decision](https://github.com/OnyxJeff/onyx-core/blob/main/docs/v0.8.0/CODE_ONLY_RELEASE_DECISION.md)
- [Deployment and rollback plan](https://github.com/OnyxJeff/onyx-core/blob/main/docs/v0.8.0/DEPLOYMENT_ROLLBACK_PLAN.md)
- [Operator runbook](https://github.com/OnyxJeff/onyx-core/blob/main/docs/v0.8.0/OPERATOR_RUNBOOK.md)
- [Historical pre-merge checklist](https://github.com/OnyxJeff/onyx-core/blob/main/docs/v0.8.0/PRE_MERGE_RELEASE_CHECKLIST.md)

**Security:** Keep the Pi receiver on the private USB interface. Its link uses HTTP, not TLS. Never expose receiver credentials or privileged monitoring sources to LAN/WAN.
