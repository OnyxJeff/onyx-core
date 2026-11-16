# ONYX CORE v0.8.0 — Continuous Monitoring & Operational Alerts

**Status: PRE-MERGE REVIEW — NOT RELEASED.** This is the proposed GitHub release text. It must not be published until the final operator review, merge, protected-install acceptance, and publication approval.

## Summary

v0.8.0 extends ONYX CORE's Windows 11 + Raspberry Pi Zero USB telemetry companion with **opt-in** USB/ICS connectivity monitoring, persisted incident state, a local monitoring dashboard, and optional foreground notification tooling. The v0.7.0 telemetry collector, gateway, OBS overlays, and protected histories are preserved during pre-merge review.

**Release scope:** foreground, explicitly authorized read-only monitoring and independently started optional components. **No unattended polling service, automatic monitoring Scheduled Task, automatic network repair, notification startup, or webhook activation is included or authorized by the release.**

## What's new

- **Connectivity diagnostics:** on-demand Windows USB/ICS and Pi forwarding classification, with bounded monitoring-cycle controls and a restricted Pi diagnostic path.
- **Incident history:** isolated v0.8.0 SQLite checks and `Opened`, `Changed`, and `Recovered` transitions, protected transaction and first-use schema authorization, durable operation receipts and restart deduplication.
- **Operator view:** read-only monitoring summary at `/api/v1/monitor/summary` and a dashboard panel; development monitoring uses loopback `127.0.0.1:18767`; separately authorized release-profile gateway uses loopback `127.0.0.1:18768` when explicitly launched. The production v0.7.0 gateway stays on `127.0.0.1:18766`.
- **Opt-in notification watcher:** optional ntfy, Discord, or JSON-webhook delivery of `Opened`/`Recovered` with first-run baseline, retry cursor, and at-least-once behavior. The watcher remains **disabled** unless separately configured and started; real third-party delivery is not accepted as part of the protected foreground operator.
- **Security and reliability:** protected-source/SID/console admission, bounded foreground sessions and consent revocation, low-integrity diagnostic worker under Windows Job Object containment, confirmed process-tree exit, parent-controlled journal commits, transaction receipts, and expiration-aware accounting.

## Validation available before merge

- **1,410** SQUALL offline tests discovered: **1,400 passed**, **10 expected skips**, **0 failures/errors**, following the final accounting correction in commit `e1b1d596513fd04ef7434b7a587e8f3381b61300`.
- **5/5** SQUALL synthetic native worker-containment checks passed: low-integrity write denial, hard timeout, revocation, descendant exit, and scratch integrity.
- **8/8** exact release-path low-integrity access checks passed (**40** write-capable handle requests denied; protected hashes unchanged).
- R7 evidence collection independently verified **76 source/document/test files** at the earlier `56ee3d5` checkpoint; the two-file final accounting amendment was separately checked and regression-tested on SQUALL.
- These are **host transcripts and source-review evidence**, not GitHub Actions CI or complete end-to-end protected-install acceptance.

## Safety / behavior

- Existing production telemetry tasks, protected v0.7.0 stores, DPAPI credentials, and the Pi receiver must not be silently modified by release deployment.
- Monitoring requires an approved protected source and explicit logged-on-user consent. Expired sessions do not report successful completion, even when a confirmed journal write is correctly accounted for.
- Notifications are optional, may deliver duplicates in the narrow remote-acceptance/local-cursor crash window, and are not a substitute for a monitoring watchdog.
- A `Stale` dashboard reading indicates lack of fresh recorded evidence, not proof that the USB connection is down.
- The private USB receiver uses HTTP on a restricted USB network. Do not expose it to LAN/WAN.

## Known limits and pending acceptance

- The previously installed protected `C:\Program Files\OnyxCore\v0.8.0` tree did **not** match the final candidate source. Its new **19-file** source inventory and administrator-pinned approval digest still require independent reconciliation and approval.
- A logged-on-console-user `--audit-installed`, bounded real read-only Windows/Pi cycle(s), explicit revocation, optional release dashboard and safe stop/rollback are **not yet documented as passed** for the final candidate.
- Notification providers are optional, and external-provider production delivery, unattended notification/monitoring, and automatic repairs are not part of the accepted protected foreground path.
- No GitHub CI checks were reported on the draft PR at the time of this review.

## Operator / release references

- [Pre-merge release checklist](PRE_MERGE_RELEASE_CHECKLIST.md)
- [Deployment and rollback plan](DEPLOYMENT_ROLLBACK_PLAN.md)
- [Operator runbook](OPERATOR_RUNBOOK.md)
- [RC1 operational acceptance contract](RC1_OPERATIONAL_LAUNCH_AND_ACCEPTANCE.md)
- [R6.2B2B worker-containment contract](R62B2B_WORKER_CONTAINMENT.md)
- [R6.2B2E commit-receipt contract](R62B2E_DURABLE_CYCLE_RECEIPTS.md)

**Release decision:** HOLD for merge/tag/GitHub publication and protected installation until the remaining pre-merge acceptance gates are reviewed and approved. Do not describe this draft as a published v0.8.0 release.
