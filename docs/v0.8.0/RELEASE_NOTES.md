# ONYX CORE v0.8.0 — Continuous Monitoring (DRAFT RELEASE NOTES)

> **Not published.** This draft records the M1–M5 development checkpoint and observed M6 validation. Do not publish as an official GitHub release until the release-readiness gates are approved.

## Summary

v0.8.0 adds opt-in Windows/Pi USB connectivity monitoring with persisted incident history, a local gateway dashboard summary, and optional outbound incident notifications. The design keeps monitoring and notifications separate from the existing telemetry collector and gateway, and does not install automatic repair logic or a scheduled notification service.

## Highlights

- **M1 — Real connectivity checks:** Explicit read-only diagnostics classify the Windows USB path and Pi internet reachability. Live probes require deliberate invocation.
- **M2 — Continuous foreground monitoring:** An explicitly started monitor can collect bounded or continuous observations; no automatic startup is established by this release candidate.
- **M3 — Incident history:** Local SQLite stores retained checks and incident events (`Opened`, `Changed`, `Recovered`), with safe history inspection.
- **M4 — Local monitoring dashboard:** An opt-in gateway endpoint, `GET /api/v1/monitor/summary`, projects sanitized saved history into a lightweight dashboard panel. Stale health is distinguished from a current outage. The development view runs on its own localhost port and does not write to the Pi.
- **M5 — Incident notifications:** Separate foreground watcher can deliver `Opened` and `Recovered` events through ntfy, Discord or JSON webhook providers, while suppressing `Changed` events. First run establishes a baseline; successful sends advance the durable cursor. Retry follows at-least-once semantics. Added journal-behind-cursor guard prevents silent non-delivery after certain journal resets.

## Validation recorded

- 82 focused offline tests passed (20 M5 + 62 M1–M4).
- Four authorized live connectivity checks were healthy; M3 retained-check count reached eight and no incidents were recorded during that verification.
- Isolated development and production dashboards each returned HTTP 200; M4 summary returned eight retained checks, no incidents, and correctly classified a 406-second-old Healthy observation as `Stale` with 300-second threshold.
- Eight isolated M5 integration assertions passed using actual localhost HTTP POSTs and temporary SQLite databases, including HTTP 503 retry and journal reset refusal.
- Verified production v0.7.0 launch entrypoints, Scheduled Task Running states, preserved collector backup SHA256 and HTTP 200 on the existing dashboard.
- Four critical v0.7.0 files were recovered from Git and compared against stored blob content; only CRLF/LF differences were found. A temporary archived v0.7 gateway started on loopback `18768` with a disposable, non-secret stdin token, served HTTP 200, then was stopped and cleaned up without affecting production `18766`.
- Development checkpoint committed as `595f9320491ae6efe2f505d0866e6740b22c8052`; no production deployment evidenced.

## Configuration and safety

- M1/M3 connectivity checks are only performed after explicit operator invocation.
- M4 monitoring endpoint is off unless enabled on a separate gateway instance (`--v080-monitor-view`); this development mode rejects port `18766`.
- M5 does not send without `--watch`, an explicit provider and webhook URL configuration. No Scheduled Task, auto-start, ICS repair or automatic webhook is enabled.
- Notification content is sanitized; avoid putting webhook URLs, bearer tokens or DPAPI secrets into commands shared in logs, issues or screenshots.

## Known limitations

- `Stale` denotes missing recent M3 observations, not necessarily an actual outage.
- M5 is not a watchdog for M2; an inactive monitor produces no new incident alerts.
- Notification delivery is **at least once**, not exactly once; a narrow crash window may duplicate an alert.
- The journal reset guard catches event IDs below the saved cursor but cannot identify every replacement with IDs already caught up.
- M3/M5 development paths are user-scoped; a production runtime/store design has not been approved.
- Real third-party webhook provider delivery and long-lived CLI watcher operation have not been validated in the supplied evidence.
- Isolated rollback source validation and basic gateway startup passed; authenticated upstream telemetry, overlays and an actual v0.8 production cutover/rollback remain untested.
- Independent network-listener binding ownership remains a release-readiness follow-up.

## Release status

**HOLD for deployment and publication.** See `RELEASE_READINESS.md` and `DEPLOYMENT_ROLLBACK_PLAN.md` for outstanding release gates.
