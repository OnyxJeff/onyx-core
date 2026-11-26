# M4 — v1.0.0 monitoring integration foundation

Status: offline source candidate against `abf28c8a61c6ae89796cc20b0856857888d9e240`. Not deployed. The active v100 installation and receipts are unchanged.

## Changes

- v100 integrated receiver store allows a five-second future sample tolerance in the pure freshness evaluator. Within that bound age is clamped to zero and the reason is `telemetry_fresh_clock_skew`. Greater future age remains unknown; stale boundaries remain 90/180 seconds. Legacy callers retain zero tolerance. Clock synchronization remains necessary; ingestion validation and stored UTC timestamps are unchanged.
- `--v100-monitor-view` explicitly enables the read-only gateway route. It refuses legacy monitoring ports 18766, 18767 and 18768. The old v080 flag is not accepted by the v100 gateway. Legacy gateway source is unchanged.
- `OnyxV100MonitoringView` reuses the v080 SQLite projector with an explicit `%LOCALAPPDATA%/OnyxCore-v100/Monitoring/incident-history.sqlite3` path. The v080 environment storage selector is ignored. Redirected ancestors and linked or redirected database/sidecar files are refused. Missing history reports NoData without creating storage. This is not a native DACL or concurrent-path-race security proof.
- The versioned dashboard polls the local monitoring route and reveals its panel only when the route exists, independent of the configured local port. HTTP 404 hides the panel. The panel does not start diagnostic probes.
- The deterministic source transformers are updated alongside their versioned outputs. Old bundle/installation contracts and their historical receipt pins are not changed in this checkpoint.

## Source review findings / remaining integration

The v0.8.0 code-only release explicitly did not accept unattended monitoring, native protected deployment, or automatic repairs. The live v080 probe has dev/release source checks and requires Windows containment and a restricted SSH diagnostic path. Do not bypass these or substitute the Pi healthz endpoint for proof of Pi Internet reachability. Reuse sanitized classifications, journal transactions, confirmation/deduplication and authorization boundaries in a v100-specific runtime contract. The existing notification watcher stays disabled by default. Existing v070/v080 histories are not migrated or reused.

The documented old ICS recovery task was absent at the v080 release audit and from the current task inventory. The source archive documents the old host-local Repair-ICS.ps1 but does not include it. Do not silently create a privileged task based on the documentation alone. Verify current SharedAccess/USB readiness and recovery behavior before defining opt-in repair, and inspect actual script provenance if reused.

Next: design the v100 live probe/authorization and isolated writer path, package explicit dependencies (OnyxV100MonitoringView, OnyxMonitoringView, OnyxLiveIncidentHistory, OnyxContinuousMonitor, OnyxLiveConnectivity, OnyxMonitorConfig and any separately reviewed live-runtime dependencies), generate a new candidate from the accepted source checkpoint, audit Windows/Pi installation and rollback paths, then native acceptance. Keep the old package as the rollback target. A read-only SQLite connection can use SQLite sidecar machinery; do not claim OS-level write denial from `mode=ro` alone. No history writer, new scheduled task, notification, repair, credential or activation is authorized by this patch itself.

## Local fixture validation

Python 3.13.5 Linux x86_64: 12 new tests, 12 existing health/HTTP tests, 15 legacy monitoring-view tests, 12 Windows runtime generator tests, 11 dashboard tests, 12 cross-component tests; 74 tests passed, zero failures/skips. All databases and loopback servers used disposable fixtures. Native Windows ACLs, ARMv6, live monitoring, new bundle and installed-runtime updates remain pending. Archive CRLF source is normalized to the canonical Git LF form for patch generation; actual worktree verification is required.
