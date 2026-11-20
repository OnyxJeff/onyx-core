# M1-S10 — Source identity and SQLite bootstrap compatibility

Status: development-only correction, not deployed or committed by application.

## Findings addressed

- v0.9's fixed `SQUALL` receiver validation refused valid v1 Windows collector
  telemetry using other configured source names. The Pi config now declares
  the expected source, the launcher passes `--expected-source`, and the v1
  receiver enforces the declared value for every authenticated POST.
- Old `IntegratedStore` could import the legacy receiver validator when
  restoring a snapshot into a new SQLite database. The additive v1 store
  uses the v1-configured validator for bootstrap and rejects mismatched cached
  snapshots before database creation, without touching the cached data.
- The receiver generator now pins the entire original Git blob rather than
  relying on individual text signatures or solely on an external review guard.

## Static cross-host contract

Windows `collector.source` must equal Pi `receiver.source`; Windows and Pi
`receiver.port` must also match. Both configs remain secret-free and must be
installed through an independently approved host-specific enrollment step.
No live endpoint is probed by these tests or source transformations.

## Offline tests

- Cross-host config mismatch refusal.
- Windows-shaped telemetry accepted by the v1 receiver validator and synthetic
  HTTP POST handler; unexpected source rejected with no store write.
- Snapshot-only validation refuses wrong identity without modifying its file.
- SQLite bootstrap accepts a matching snapshot but fails before DB creation on
  wrong identity. Existing SQLite history with legacy `SQUALL` rows stays
  present after an authorized installation changes the configured source.
- Generator rejects changes anywhere in original receiver source, detects
  mixed line endings and writes deterministic LF output.
- Original installed receiver, integrated store, `history.py`, systemd service,
  Windows tasks, DPAPI token, and real telemetry database remain unchanged.

## Not yet accepted

No Pi runtime activation, clean installation, automatic credential enrollment,
network authorization, rollback, or end-to-end host installation has occurred.
Native ARMv6 and reproducible M2 installer tests remain necessary.
