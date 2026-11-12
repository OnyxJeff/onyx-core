# ONYX CORE v0.8.0 — M5 Incident Notifications (Development)

## Purpose

Optional outbound notifications on **new incident opened** and **incident recovered** events recorded by the already-running M3 monitor. M5 is a separate **foreground** watcher, not another diagnostic runner. It reads the existing v0.8 development SQLite incident journal and maintains its own cursor in a separate local SQLite file.

**Nothing sends by default.** This package does not enable alerts, change the Windows gateway, install tasks, touch production, alter DPAPI, or run probes.

## How it works

- M3 continues to record sanitized checks and the `Opened`, `Changed`, `Recovered` incident-event sequence in `incident-history.sqlite3`.
- The M5 watcher observes new event IDs every 15 seconds (configurable 5–300s). It sends **one** webhook on `Opened` and **one** on `Recovered`, ignoring `Changed` to prevent spam. Ordinary `Healthy` checks do not create events.
- The first watcher start **baselines existing events without sending old alerts**. It sees only new events afterward.
- The cursor is saved to `%LOCALAPPDATA%\OnyxCore-v080-Development\Monitoring\alert-delivery.sqlite3`, separate from the M3 database. Each completed delivery advances the cursor. Failures leave it unchanged for retry, with bounded backoff.
- Journal reset guard: if the M3 journal disappears or its highest event ID becomes lower than the saved M5 cursor, the watcher and `--status` refuse to proceed with `operator recovery required`. The cursor is not rewound and no alerts are sent. This guard does not detect a replaced journal that has already advanced beyond the old cursor; do not replace or restore the journal while M5 is running.
- At-least-once delivery: if the process crashes after the remote endpoint accepts an alert but before the cursor is written, a retry could duplicate that one alert. There is no claim of exactly-once delivery.
- Only incident ID, status, event type, timestamp and fixed text are transmitted — not the Windows hostname, API token, IP addresses, SSH data or raw probe details.
- On `Unknown`, opening an incident may notify just like `Degraded`. A recovered notification requires a confirmed healthy observation.
- If M3 stops recording, there are **no new events to alert on**. M4 marks the last connectivity check `STALE`. Independent watcher/monitor-liveness notifications are not in M5's current scope.

## Journal reset recovery (manual only)

If M5 reports `incident journal is behind saved notification cursor; operator recovery required`, **stop M5** and investigate M3's incident journal and any database restoration. Do **not** delete or edit either database merely to clear the error. Keep M3 monitoring intact and preserve copies of both state files before deciding on a recovery approach. Re-establish the correct journal or arrange an explicitly reviewed re-baseline; this milestone does not include an automatic cursor reset or state deletion command. An incident journal replaced with a new journal that already has an equal or higher ID cannot be detected by the ID-only guard. If a restore or replacement is known, stop M5 regardless of `--status` output and reconcile with operator review.

## Provider support

- `ntfy` (default): plain text POST; can use HTTPS ntfy server or an explicitly allowed private LAN HTTP ntfy instance.
- `discord`: JSON `{ "content": "..." }` to a user-created HTTPS Discord webhook.
- `json`: small JSON webhook for home automation or a compatible service.

Do not share webhook URLs or tokens in chat, Git, screenshots, or release logs. Set the destination URL only as a **process environment variable**. The watcher will not print the URL, and excludes secret paths from error messages. HTTP requires loopback unless `--allow-private-http` explicitly permits RFC1918/private LAN addresses; HTTPS is recommended. No redirects or system HTTP proxies are followed.

## Install and offline inspect

On SQUALL (normal user account):

```powershell
$Py = 'C:\Python313\python.exe'
$M5 = 'D:\github_repos\onyx-core-v080\windows\monitoring\v080\OnyxIncidentNotifications.py'
& $Py -B $M5 --check-config
& $Py -B $M5 --status
```

Both commands are **inert**: no DB creation, notifications or network probes. An uninitialized cursor is expected until a watcher starts.

## Deliberately enable alerts later

Only after the user chooses their provider and securely configures a destination (example uses a **placeholder**, not a real URL):

```powershell
# In this PowerShell window only; NEVER commit or publish this value.
$env:ONYXCORE_V080_ALERT_WEBHOOK_URL = '<YOUR HTTPS NOTIFICATION URL>'

& 'C:\Python313\python.exe' -B `
  'D:\github_repos\onyx-core-v080\windows\monitoring\v080\OnyxIncidentNotifications.py' `
  --watch --provider ntfy --poll-seconds 15
```

Run in a separate PowerShell window from the continuous M3 monitor. Ctrl+C stops M5. Set `--provider discord` or `--provider json` for compatible endpoints. For self-hosted ntfy on a trusted private HTTP IP, `--allow-private-http` must be supplied deliberately. `ONYXCORE_V080_ALERT_TOKEN` is an optional bearer token for ntfy/json destinations; do not set it for Discord.

No notification is sent merely by starting the watcher. Its first run marks existing incident events as its starting position. Subsequent `Opened`/`Recovered` events generate webhooks.

## Current development limits

- M5 notification delivery is an **opt-in user-session process**, not a service or Scheduled Task. It stops when its PowerShell window/user session ends.
- Two alert watcher processes in the **same Windows logon session** are blocked by a separate mutex. This does not guarantee exclusivity across separate logon sessions.
- Alert state is user-scoped; run M3 and M5 under the same Windows account.
- No browser credential prompt, gateway modifications or OBS changes are introduced.
- Avoid deliberately disconnecting the Pi or breaking ICS for testing. The unit tests use synthetic transitions and mocked HTTP delivery.

## Targeted tests

```powershell
$Tests = 'D:\github_repos\onyx-core-v080\tests\monitoring\v080'
& 'C:\Python313\python.exe' -B -m unittest discover -s $Tests -p 'test_incident_notifications.py' -v
```

Acceptance: 20 notification tests (16 original + 4 journal guard regression tests) plus M1–M4 regression tests, `--check-config` and `--status` on SQUALL. A real delivery test requires explicitly configuring an endpoint; it is not enabled by installation.
