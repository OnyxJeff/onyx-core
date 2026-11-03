# ONYX CORE v0.5.0 — Windows localhost gateway and OBS overlay

## Purpose

The Windows gateway exposes a **read-only** view of ONYX CORE telemetry on `127.0.0.1:18766`. It authenticates to the Raspberry Pi receiver using the existing Windows-user-protected DPAPI credential. The web dashboard and OBS overlay never receive the bearer token.

Endpoints:

| URL | Purpose |
| --- | --- |
| `http://127.0.0.1:18766/dashboard` | Full dashboard, automatic authentication |
| `http://127.0.0.1:18766/overlay` | Transparent compact OBS telemetry HUD; `/overlay/` also supported |
| `/api/v1/latest` | Allowed read-only telemetry API |
| `/api/v1/history?limit=60` | Allowed read-only history API (validated query) |
| `/api/v1/health` | Allowed read-only receiver health API |

The gateway and OBS Browser Source run on the same Windows computer. The Pi receiver remains at `svr-onyxcore.local:8765` over the USB network link. The collector, receiver, SQLite database, and the Pi's own dashboard do not depend on this gateway.

## Prerequisites

- Windows 11, Python 3.13 installed at `C:\Python313\` (adjust paths to your installation), and PowerShell 5.1.
- Existing saved DPAPI token at `%LOCALAPPDATA%\OnyxCore\collector-token.dpapi`.
- Run the gateway scheduled task **as the same Windows account that created the DPAPI token**. An unrelated service identity cannot normally decrypt this user-scoped credential.
- Working name resolution for `svr-onyxcore.local`, or a verified reachable receiver address.
- A local copy of `OnyxGateway.py`, `Get-OnyxGatewayToken.ps1`, `gateway-dashboard.html`, and `overlay.html` in the same directory.

Do **not** put token values in task arguments, URLs, Git, command histories, or logs.

## Development worktree (verified configuration)

Example source directory:

```text
D:\github_repos\onyx-core-v050\windows\gateway
```

The gateway currently runs from this development worktree. **Do not remove or rename that directory until the scheduled task is migrated and tested during the production release.**

Run unit tests without stopping the production task:

```powershell
cd D:\github_repos\onyx-core-v050
python .\windows\gateway\Test-OnyxGateway.py
```

The Phase 5 suite has 16 checks: dashboard and overlay routes, transparent markup, token-free overlay, request restrictions, and authenticated API proxy reads through a simulated upstream receiver.

## Manual launch and Windows Task Scheduler

`OnyxGateway.py --load-dpapi` calls the adjacent `Get-OnyxGatewayToken.ps1` helper to decrypt the existing token under the current Windows user. The Python process captures the helper's output privately; the token is not written to browser content or command-line arguments. Legacy stdin-based launch remains available for compatibility, but is **not** the configured production startup method.

For interactive troubleshooting, **stop the scheduled task first** to avoid a port conflict, then run:

```powershell
$gatewayDir = 'D:\github_repos\onyx-core-v050\windows\gateway'
python "$gatewayDir\OnyxGateway.py" `
  --dashboard "$gatewayDir\gateway-dashboard.html" `
  --receiver svr-onyxcore.local `
  --port 18766 `
  --load-dpapi
```

The current scheduled task is named **`ONYX CORE - Local Gateway`**, is triggered at Windows user logon, and runs `C:\Python313\pythonw.exe` directly (no persistent PowerShell parent). Its action is equivalent to:

```text
Program: C:\Python313\pythonw.exe
Arguments: -u "D:\github_repos\onyx-core-v050\windows\gateway\OnyxGateway.py" --dashboard "D:\github_repos\onyx-core-v050\windows\gateway\gateway-dashboard.html" --receiver svr-onyxcore.local --port 18766 --load-dpapi
Start in: D:\github_repos\onyx-core-v050\windows\gateway
```

This direct process ownership allows `Stop-ScheduledTask` to terminate the gateway without leaving an orphaned Python process. `pythonw.exe` has no console; debug with interactive `python.exe` when needed.

Inspect operational state:

```powershell
Get-ScheduledTask -TaskName 'ONYX CORE - Local Gateway' | Select-Object TaskName,State
(Invoke-WebRequest http://127.0.0.1:18766/dashboard -UseBasicParsing -TimeoutSec 5).StatusCode
(Invoke-WebRequest http://127.0.0.1:18766/overlay -UseBasicParsing -TimeoutSec 5).StatusCode
```

Expected: task `Running` and HTTP `200` from both routes. Confirm the metrics and health status populate in a browser/OBS, not merely that HTML is served. Task stop/start and HTTP checks have been validated; a fresh Windows logoff/logon trigger check is still pending.

## OBS Browser Source

Create a Browser Source in an OBS test scene:

- URL: `http://127.0.0.1:18766/overlay`
- Width: `1280`; Height: `720`; FPS: `30`.
- Optional Custom CSS: `body { margin: 0; background: rgba(0,0,0,0) !important; }`
- Adjust placement using OBS Transform; the HUD occupies only a small portion of the transparent canvas.

The HUD polls the gateway every 15 seconds; Windows collector samples arrive approximately every 30 seconds. Use LIVE/STALE/UNREACHABLE and sample age to distinguish current data from cached readings. The overlay needs no API token prompt or layout selector.

## Security boundaries

- The HTTP service must remain bound to `127.0.0.1`, **never** `0.0.0.0`; do not port-forward or publish it on the LAN.
- Allowed proxy reads are restricted to `/api/v1/history`, `/api/v1/latest`, and `/api/v1/health`; no telemetry POST, arbitrary proxy URL, or write method is enabled.
- Host-header, Origin, and Fetch Metadata checks help restrict browser-originated access. The gateway is **not a security boundary against other local software**: a process on the PC that can access loopback may read the non-sensitive telemetry.
- The full Pi dashboard may store only the `onyxcore-layout` UI preference in browser `localStorage`, **not** the API bearer token. The localhost gateway and overlay do not expose that token to the browser.
- The receiver connection across the isolated USB network is plain HTTP; localhost also uses HTTP. Do not treat either link as appropriate for sensitive data on an untrusted network.

## Safe restart and rollback

When changing a deployed gateway file, back up `OnyxGateway.py` first; stop only the gateway task; validate that its Python process has exited; update files; run gateway tests; and restart it. Do not restart the Pi receiver or collector for a gateway-only update.

```powershell
$taskName = 'ONYX CORE - Local Gateway'
Stop-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 3
Get-CimInstance Win32_Process | Where-Object {
  $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'OnyxGateway\.py'
} | Select-Object ProcessId,Name
```

The last command should return **no matching process** before files are replaced. If an update fails, restore the saved `OnyxGateway.py`, restart the scheduled task and verify `/dashboard` (and `/overlay` if the restored version supports it). Keep the existing DPAPI token file untouched.

`Start-OnyxGateway.ps1` is retained as a **legacy/manual compatibility launcher**, not the current scheduled-task action. Phase-specific rollback notes and `.pre-phase*.py` copies are development artifacts and should not be added to the release.

## Release status

This document describes the validated Phase 4C/5 Windows configuration used during **v0.5.0 release preparation**. Production-worktree migration, merge, release tag, and post-logon validation are separate remaining steps; do not consider them complete merely because the current gateway is running.
