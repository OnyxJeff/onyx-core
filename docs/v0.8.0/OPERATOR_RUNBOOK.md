# ONYX CORE v0.8.0 — Operator Runbook (M6 DRAFT)

**Applies to:** Windows 11 SQUALL; development worktree `D:\github_repos\onyx-core-v080`; Python `C:\Python313\python.exe`.
**Safety boundary:** The v0.7.0 production gateway and telemetry collector are separate. The following development commands do not reconfigure production or schedule services.

## Operational layout

| Layer | What it does | Default behavior |
|---|---|---|
| M1 | Approved connectivity classification | No probe without an explicit live command |
| M2 | Foreground/bounded read-only monitor | No installed automatic task established |
| M3 | SQLite connectivity observations, incident events and `--history` | Writes only when recording is explicitly invoked |
| M4 | Read-only HTTP monitoring summary on an opt-in local gateway | Disabled unless `--v080-monitor-view` is passed with a separate port |
| M5 | Foreground notification watcher reading M3 events | Not running or sending unless explicitly `--watch` with a destination |

## Read-only status commands

```powershell
$Repo = 'D:\github_repos\onyx-core-v080'
$Py   = 'C:\Python313\python.exe'
& $Py -B (Join-Path $Repo 'windows\monitoring\v080\OnyxContinuousMonitor.py') --check-config
& $Py -B (Join-Path $Repo 'windows\monitoring\v080\OnyxLiveIncidentHistory.py') --history
& $Py -B (Join-Path $Repo 'windows\monitoring\v080\OnyxIncidentNotifications.py') --check-config
& $Py -B (Join-Path $Repo 'windows\monitoring\v080\OnyxIncidentNotifications.py') --status
Invoke-RestMethod 'http://127.0.0.1:18767/api/v1/monitor/summary'
```

The last command requires the *development* gateway to already be running. `--status` must not create notification state. Do not interpret absent/uninitialized cursor as a failed service; it means M5 has not been activated.

## Explicit, bounded live verification

This command performs **one real connectivity check and writes one development M3 observation**. Run only when approved; it is not a health-only read:

```powershell
& 'C:\Python313\python.exe' -B `
  'D:\github_repos\onyx-core-v080\windows\monitoring\v080\OnyxLiveIncidentHistory.py' `
  --record-live --count 1
```

The output may be Healthy, Degraded, or Unknown. A Degraded/Unknown result can correctly create an incident. Avoid deliberate USB/ICS outages for release testing.

## Optional development dashboard (foreground)

Run under the same Windows account as M3 and the DPAPI token. Leave the v0.7.0 production gateway on `18766` untouched. Run this in a separate PowerShell window:

```powershell
$Repo = 'D:\github_repos\onyx-core-v080'
& 'C:\Python313\python.exe' -B -u `
  (Join-Path $Repo 'windows\gateway\OnyxGateway.py') `
  --dashboard (Join-Path $Repo 'windows\gateway\gateway-dashboard.html') `
  --receiver 'svr-onyxcore.local' --port 18767 `
  --load-dpapi --v080-monitor-view
```

Visit `http://127.0.0.1:18767/dashboard`; `GET /api/v1/monitor/summary` returns sanitized persisted history. Use Ctrl+C in that same foreground window to stop the development instance. **Do not** add `--v080-monitor-view` to the existing production task or port `18766`; the development flag deliberately rejects that port.

## Reading dashboard states

- `Healthy` denotes the *last observed* check, not continuous connectivity.
- `Stale` is expected when the last recorded observation exceeds the 300-second freshness threshold. It is **not** itself an outage.
- `No Data` means no saved checks were available; clock anomalies can yield `Unknown`.
- Open incidents remain visible until M3 records recovery; a stale check alone never closes one.

## Notifications: disabled by default

M5 is not a Scheduled Task or service. It needs a separate foreground Windows user session, a deliberately supplied webhook URL in `ONYXCORE_V080_ALERT_WEBHOOK_URL`, a provider, and `--watch`. It baselines existing events on first run without backfilling them. `Changed` events are suppressed; `Opened` and `Recovered` can generate delivery. Token variable `ONYXCORE_V080_ALERT_TOKEN` is optional for ntfy/json, not Discord. Do **not** paste webhook URLs/tokens into tickets, Git, output screenshots or chat.

**Do not activate M5 as part of this draft runbook.** For later approved activation, follow the reviewed M5 milestone document and provider-specific policy. Do not point testing at the real M3 journal when synthetic cases will do.

## Known failure behavior

- HTTP delivery failures preserve the last successful cursor for retry. At-least-once semantics mean a crash between remote acceptance and cursor persistence can produce a duplicate alert.
- If `max(incident_events.id)` falls behind the saved cursor, M5 refuses and requires operator intervention; do not automatically rewind or delete cursor state.
- A journal replaced with reused IDs that have caught up to the cursor may evade that guard. Treat *all known journal restoration/replacement* as an operator review event before re-enabling notifications.
- If M2 is not recording, there will be no new incident events for M5; watching an empty journal does not prove the Pi is healthy.
- A 503 from the M4 summary should be investigated as incident-history unavailability, not reported as a live USB failure.

## Archived v0.7.0 smoke-test note (M6)

A read-only restoration rehearsal has already passed: a complete `v0.7.0` archive was extracted into a disposable temporary directory and its gateway served HTTP 200 on loopback `18768`, while production on `18766` stayed healthy. The archived gateway used a **disposable non-secret credential through stdin** solely to complete its legacy startup path; its upstream telemetry API was **not** authenticated or tested. After testing, the process was stopped and temporary files removed.

For operational rollback, do **not** substitute that disposable credential for the DPAPI-backed production gateway token. Restore only reviewed launch targets and securely preserved task configurations. An actual production cutover and rollback have not been rehearsed.

## Production checks without configuration changes

```powershell
Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 'http://127.0.0.1:18766/dashboard' | Select-Object StatusCode
Get-ScheduledTask -TaskName 'ONYX CORE - Local Gateway','ONYX CORE - Telemetry Collector' | Select-Object TaskName,State
```

Task `Running` indicates scheduler state, not end-to-end service health. Verify telemetry and overlays visually. The ICS recovery task was absent at audit; do not install it for v0.8.

## Operator stop conditions

Stop the rollout and refer to `DEPLOYMENT_ROLLBACK_PLAN.md` if the production dashboard/collector stops responding, credentials leak, an unexpected network listener appears, notification traffic is sent without explicit approval, data is read from the wrong user store, or journal reset is detected. Preserve logs without printing credentials.
