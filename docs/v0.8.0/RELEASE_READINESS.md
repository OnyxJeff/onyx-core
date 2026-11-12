# ONYX CORE v0.8.0 — Release Readiness (M6 DRAFT)

**Status:** NOT APPROVED FOR PRODUCTION RELEASE
**Evidence captured:** November 11–12, 2026 (SQUALL)
**Development branch:** `feature/v0.8.0-continuous-monitoring`
**M1–M5 checkpoint:** `595f9320491ae6efe2f505d0866e6740b22c8052`
**Current production:** `main` = `v0.7.0` = `06ec81582791fc797f74ad294195d68b2023cb66`

## Purpose and release boundary

M6 verifies the M1–M5 implementation, prepares operator/rollback documentation, and defines gates for any subsequent merge, tagging, and deployment. This document is **evidence, not release approval**. M2/M3 monitoring and M5 notification delivery are opt-in; a passing test does not imply background monitoring is running. No production deployment, PR, merge or release tag has been executed in the evidenced workflow.

## Recorded validation

| Gate | Observed result | Status |
|---|---|---|
| Development identity | Branch and checkpoint exact, clean working tree | PASS |
| M1–M5 automated checks | 20 M5 + 62 M1–M4 tests | PASS |
| Live M1/M2/M3 healthy path | Four authorized observations, latest three at ~2-minute intervals, all Healthy; M3 retained checks increased from 4 to 8, 0 incidents | PASS (healthy path only) |
| M4 API | `GET /api/v1/monitor/summary` at localhost `18767`, HTTP 200; eight checks, zero incidents | PASS |
| M4 stale classification | Latest saved Healthy check age 406 s, threshold 300 s => `Stale` | PASS |
| Browser rendering and co-existence | Production `18766` and isolated development `18767` dashboards visually inspected; both HTTP 200 | PASS (observed) |
| M5 local HTTP delivery | Eight isolated integration assertions: first-run baseline, Opened delivery, duplicate suppression, Changed suppression, HTTP 503 retry, Recovered delivery, retry deduplication, journal-reset fail-closed | PASS |
| M5 stored configuration | `--check-config` succeeds; real development cursor absent/uninitialized and delivery disabled | PASS |
| Production Scheduled Tasks | Local Gateway and Telemetry Collector running | PASS (state only) |
| Development storage ACL | SYSTEM, Administrators and current Windows user have inherited FullControl; no broad Users/Everyone grants observed on audited directories | PASS (directory-only audit) |
| v0.7.0 rollback anchor | Local tag resolves to exact production HEAD `06ec815...`; preserved collector backup SHA256 recorded and unchanged throughout smoke test | PASS |
| Network binding ownership | HTTP 200 and separate process identities established, but `Get-NetTCPConnection` gave no results and `netstat` gave inconsistent PID/listener lines | OPEN: independently verify bindings |
| Production task launch chains | Both Scheduled Tasks running; exact executables, expected entrypoint names, and production repository references verified without printing action arguments | PASS (entrypoints only; nested launch behavior not exhaustively audited) |
| v0.7.0 rollback source integrity | Four critical files verified against original v0.7.0 Git blobs after confirming archive-to-blob differences were CRLF-only | PASS |
| Isolated rollback startup smoke test | Full v0.7.0 archive extracted into disposable temp directory; gateway started with a disposable, non-secret stdin token on `127.0.0.1:18768`, served HTTP 200, stopped and cleaned up; production dashboard stayed HTTP 200 | PASS (unauthenticated dashboard startup only) |
| Production cutover and operational rollback | No service/task cutover or rollback of a deployed v0.8 instance has been performed | OPEN — BLOCKING |
| Production integration topology | M4 development flag refuses port `18766`, M3/M5 use a development-named user-scoped directory. No approved production activation/run model | OPEN — BLOCKING |
| Live continuous M5 CLI and external provider | Isolated localhost function-level HTTP tested; long-lived watcher and third-party webhook delivery not confirmed | OPEN (must remain disabled unless explicitly approved) |
| Recovery from journal replacement with ID reuse | Guard catches `max(id) < cursor`; identical/higher IDs after replacement are not detectable by ID alone | KNOWN LIMITATION |
| Monitoring/watchdog liveness | Stale M4 checks identify absent fresh M3 recordings; M5 is not an independent M2 liveness alarm | KNOWN LIMITATION |

## Release approval criteria

- [ ] Review `git diff --name-status v0.7.0 595f932` and verify production is an ancestor of the candidate, or resolve divergence in a reviewed PR.
- [ ] Decide whether v0.8.0 ships as **dormant/opt-in tooling only** or includes an explicitly engineered production activation path. Never silently start M2 or M5.
- [ ] Review actual Scheduled Task actions and any launcher indirection *locally* without exposing secrets. Preserve existing task exports/parameters securely for rollback.
- [ ] Decide how v0.8 M3/M5 data will be segregated from user-scoped development stores before any production monitoring activation.
- [ ] Confirm local-only binding of both gateway instances by a reliable process/socket or active-network inspection; do not equate HTTP 200 with proven binding confinement.
- [ ] Check file ACLs, inherited parent ACLs, environment variables, and optional notification secrets under the intended runtime identity.
- [ ] Re-run offline and isolated integration tests against final candidate and record their hashes/results.
- [x] Demonstrate non-destructive v0.7.0 source recovery and a separate gateway dashboard-startup smoke test using a disposable credential on `18768`.
- [ ] Rehearse the *approved production* cutover and operational rollback, including exact launcher/task restoration, DPAPI-backed telemetry, overlay endpoints and collector telemetry after each step.
- [ ] Record operator sign-off before push/PR, merge, tag or production cutover.

## Evidence notes / limitations

- M4 on `18767` is intentionally launched in a separate foreground development process with `--v080-monitor-view`; production `18766` continues to run from `D:\github_repos\onyx-core`.
- The v0.8 incident database observed on SQUALL was `%LOCALAPPDATA%\OnyxCore-v080-Development\Monitoring\incident-history.sqlite3` (24,576 bytes at audit). A notification cursor database was not yet present. Do not initialize it as a side effect of an audit.
- Production contains an untracked historical backup: `windows/collector/Send-OnyxTelemetry.pre-v050.bak`, SHA256 `59E1EE7205EFBEDB79BA3D0DCB4C9FD0D8EBD3DFA4D5D9313BBD8325976830EB`. **Preserve it**; never use `git clean -fd` or destructive reset for release preparation.
- `ONYX CORE - ICS Startup Recovery` Scheduled Task was **not found**. Do not introduce or enable it during v0.8 rollout.
- Automated tests exercise healthy and synthetic failure paths; no intentional loss of USB/ICS or deliberate Pi downtime was performed.

## Phase 10–11 rollback validation evidence

- Production `main` and `v0.7.0` resolve to `06ec81582791fc797f74ad294195d68b2023cb66`; v0.8 development HEAD remained `595f9320491ae6efe2f505d0866e6740b22c8052`.
- Four critical gateway/collector files exported from `v0.7.0` differed byte-for-byte from raw Git blobs only because exported lines used CRLF rather than the blobs' LF; converting CRLF to LF produced an exact match for every file. This is content-equivalence evidence, **not** a byte-for-byte identical archive.
- The first isolated startup attempt did not reach HTTP readiness because the gateway awaited the legacy stdin token. A subsequent test supplied a **disposable, non-secret** 48-character token through redirected stdin, not DPAPI; archived v0.7.0 gateway served HTTP 200 on loopback port `18768`, was stopped, and its temporary files removed.
- During and after the successful smoke test, production gateway port `18766` returned HTTP 200; production Git HEAD and preserved collector backup hash remained unchanged.
- This verifies basic archived gateway startability, **not** upstream authentication, telemetry, overlays, service handoff, or the safety of rolling a deployed v0.8 instance back to v0.7.

## Decision

**HOLD** for production release until the open blocking gates are completed. The non-destructive rollback source and isolated startup smoke gates have passed; operational cutover and rollback remain unproven.
