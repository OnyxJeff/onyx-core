# ONYX CORE v0.8.0 — M3 Live Incident History (Development)

## Purpose

Record the actual read-only Windows/Pi connectivity observations already provided by M1 and the M2 foreground monitoring loop. This is a **manual opt-in development feature**, not an unattended production service.

M3 preserves one SQLite journal across foreground runs, with separate check records and incident lifecycle events. It does not change networking, start Scheduled Tasks, repair ICS, or notify anyone.

## Storage

`%LOCALAPPDATA%\OnyxCore-v080-Development\Monitoring\incident-history.sqlite3`

This is intentionally separate from v0.7 production and development release stores and the Raspberry Pi telemetry database. The directory and database are created only by `--record-live`. `--history` does not initialize or modify a missing database.

An individual-check retention window of 30 days is enforced during writes. Incident and lifecycle-event records are retained. Stored values are allowlisted classifications, timestamps, and durations — never raw diagnostic output, tokens, usernames, or SSH content.

## Modes (Windows PowerShell 5.1)

Assuming the source tree is `D:\github_repos\onyx-core-v080` and Python is at `C:\Python313\python.exe`:

```powershell
$Py = 'C:\Python313\python.exe'
$M3 = 'D:\github_repos\onyx-core-v080\windows\monitoring\v080\OnyxLiveIncidentHistory.py'

# No probe, no file creation:
& $Py -B $M3 --check-config

# No probe, read-only view of existing history:
& $Py -B $M3 --history

# Explicitly run two live checks and write development history:
& $Py -B $M3 --record-live --count 2 --interval-seconds 120

# Read the results after completion (optional machine-readable output):
& $Py -B $M3 --history --json
```

`--record-live` is an explicit authorization for a real foreground probe *and local development history writes*. It uses M2's sequential run loop and Windows singleton mutex, so do not start M2 alongside M3. An ongoing `--continuous` session can be stopped with Ctrl+C. M3 does not configure itself to run automatically.

## Incident interpretation

- `Healthy`: record check; if an incident is open, record `Recovered` and close it.
- First `Degraded` or `Unknown` check: record `Opened` and keep one incident open.
- Another unhealthy check, same details: update the current incident's observation count without creating duplicate incidents/events.
- A changed unhealthy cause or status: keep the same incident and record a `Changed` event.
- `Unknown` is *not* considered recovery and does not erase an earlier confirmed problem.
- After a recovery, a new unhealthy result starts a new incident.

Incidents are based on observed check times; the actual failure may have started at any point since the preceding healthy check. A powered-off Windows PC cannot report its own failure. This release does not yet expose incidents through the dashboard or provide notifications.

## Targeted offline tests

```powershell
$Tests = 'D:\github_repos\onyx-core-v080\tests\monitoring\v080'
& 'C:\Python313\python.exe' -B -m unittest discover -s $Tests -p 'test_live_incident_history.py' -v
```

The 19 M3 tests use mocked probe results and temporary SQLite databases; they do not call the real network or write to the development store. M1/M2 regression suites are also run during installation.

## Next acceptance criteria

1. Install only three additive development files and pass 19 M3 + 14 M2 + 14 M1 focused offline tests.
2. Explicitly record one or two real checks using `--record-live` on SQUALL.
3. Query `--history` to confirm the checks persisted after the process ended; healthy checks should **not** create spurious incidents.
4. Later, test a controlled or simulated outage/recovery separately without disrupting family-critical services.

Do not treat M3 as production-ready or commit/release it based on offline tests alone.
