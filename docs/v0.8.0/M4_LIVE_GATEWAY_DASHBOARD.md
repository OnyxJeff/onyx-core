# ONYX CORE v0.8.0 — M4 Windows/Pi Monitoring Dashboard (Development)

## Purpose

Expose **saved** v0.8 M3 connectivity checks and incident history alongside the existing telemetry dashboard. This is a **functional** monitoring integration, not the v0.10.0 visual-redesign release.

M1, M2 and M3 must already exist. The view is deliberately separate from the Pi receiver: Windows can still show its previously saved diagnostic history if the Pi/ICS is down. It never performs connectivity checks on page load, writes incident history, changes Windows networking, creates tasks or sends notifications.

## Implementation

- Modified `windows/gateway/OnyxGateway.py`: adds **opt-in** `GET /api/v1/monitor/summary` serving local sanitized SQLite data. The endpoint is disabled by default, disallows query strings and all write methods, enforces the gateway's existing exact Host/Origin/Fetch-Site protections, and returns a generic 503 on history errors.
- New `windows/gateway/OnyxMonitoringView.py`: read-only SQLite projection using the M3 history module and validated development database path.
- Modified `windows/gateway/gateway-dashboard.html`: a compact connectivity/incident section, polled independently every 30 seconds. No changes to the existing telemetry health section, overlays, or Pi receiver.
- New focused tests and this document.

The database remains at `%LOCALAPPDATA%\OnyxCore-v080-Development\Monitoring\incident-history.sqlite3` under the account running the gateway. The only way M4 obtains new checks is when you deliberately run M3 `--record-live` in a **separate** process.

### Why `Stale` matters

Freshness defaults to **300 seconds**. If the last stored check is older than five minutes, the dashboard says **STALE**, even if the last observation was `Healthy`. This does not indicate an outage; it means the latest health observation is no longer current. If no history exists, it says `NO DATA`. Future-dated checks with more than 60 seconds of clock skew show `UNKNOWN`.

Open incidents remain visible even when the latest check has become stale; an unresolved journal incident is not automatically considered fixed. The panel displays five recent incidents and a bounded summary, not raw system output or credentials.

## Start the development gateway (Windows PowerShell 5.1)

After applying M4, open a **separate PowerShell window under the same Windows user** that owns the DPAPI collector token and M3 history. Execute:

```powershell
$Repo = 'D:\github_repos\onyx-core-v080'
& 'C:\Python313\python.exe' -B -u `
  (Join-Path $Repo 'windows\gateway\OnyxGateway.py') `
  --dashboard (Join-Path $Repo 'windows\gateway\gateway-dashboard.html') `
  --receiver 'svr-onyxcore.local' `
  --port 18767 `
  --load-dpapi `
  --v080-monitor-view
```

Open **http://127.0.0.1:18767/dashboard** in SQUALL's browser. Leave the original gateway on port `18766` running. Use **Ctrl+C** to stop the development gateway. This is a separate foreground instance, not a Scheduled Task.

**Note:** launching with `--load-dpapi` consumes your existing local DPAPI token in Python memory for the local upstream proxy; the credential is never returned to the browser. Do not copy your collector token to this chat or into command arguments. Browser requests stay on localhost.

The new M4 endpoint is **not available on LAN hosts** and isn't a remote streaming dashboard. Secured LAN viewing belongs to the v0.9 portability release.

## Inspect without a browser

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:18767/api/v1/monitor/summary'
```

The result contains only summary classifications, the latest check, recent incidents and freshness. It will show the prior M3 healthy record as `Stale` unless another M3 recording was made in the past five minutes.

To add a **new** real history entry, separately authorize and run M3:

```powershell
& 'C:\Python313\python.exe' -B `
  'D:\github_repos\onyx-core-v080\windows\monitoring\v080\OnyxLiveIncidentHistory.py' `
  --record-live --count 1
```

Refresh the page or let the 30-second poll update it. This action writes **one** development database record and performs one diagnostic; viewing the dashboard does neither.

## Acceptance criteria

1. Focused M4 tests and M1–M3 regressions pass; original gateway regression passes.
2. Starting the development gateway on `18767` leaves the existing production gateway on `18766` unaffected.
3. The UI loads actual telemetry and separately displays the saved M3 check and recent incidents.
4. Saved health transitions to `STALE` without a fresh check and refreshes after a new explicit M3 check.
5. Stop the development gateway with Ctrl+C. No tasks, production changes, or automatic repairs occur.

**Known scope limits:** The current dashboard is local-only; no automatic M3 runner is installed; the incident history view is display-only, not a notification mechanism. Only the **current Windows user account's** v0.8 development store is consulted.
