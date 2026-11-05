# ONYX CORE v0.5.1 — Windows Gateway and OBS Overlays

## Overview

The ONYX CORE Windows localhost gateway provides read-only access to telemetry stored on the Raspberry Pi Zero receiver.

The gateway handles upstream authentication using the existing Windows-user-protected DPAPI credential. Browser dashboards and OBS overlays do not receive the receiver's bearer token.

Version 0.5.1 introduces a dedicated portrait OBS overlay while preserving the original landscape overlay.

**Latest published release:** v0.5.0 — Desktop Companion & Streaming

**Production deployment:** v0.5.1 — Portrait OBS Overlay

## Available Endpoints

The production gateway listens on `127.0.0.1:18766`.

| Endpoint | Purpose |
| --- | --- |
| `/dashboard` | Full desktop and Streaming dashboard |
| `/overlay` | Original landscape OBS overlay |
| `/overlay-portrait` | New portrait OBS overlay |
| `/api/v1/latest` | Latest telemetry sample |
| `/api/v1/history?limit=60` | Bounded historical telemetry |
| `/api/v1/health` | Telemetry freshness and receiver health |

Both overlay routes support an optional trailing slash.

The portrait route does not accept arbitrary query parameters.

## Architecture

```text
Windows 11 — SQUALL
|
|-- PowerShell Telemetry Collector
|     |
|     +-- Authenticated telemetry submission
|             |
|             v
|     Raspberry Pi Zero Receiver
|       - SQLite telemetry history
|       - Latest telemetry API
|       - Telemetry health API
|
+-- Windows Local Gateway
      - Loopback HTTP: 127.0.0.1:18766
      - DPAPI-protected upstream credential
      |
      +-- /dashboard
      +-- /overlay
      +-- /overlay-portrait
      |
      +-- Authenticated read-only receiver API
```

The gateway does not replace the telemetry collector, Raspberry Pi receiver, or SQLite storage.

## Development and Production Worktrees

ONYX CORE uses two Windows Git worktrees.

| Directory | Purpose |
| --- | --- |
| `D:\github_repos\onyx-core` | Production repository, branch `main` |
| `D:\github_repos\onyx-core-v050` | Isolated feature development |

The production gateway uses files in the production repository.

Version 0.5.1 was tested using a separate development gateway on port `18767`, while production v0.5.0 continued operating on port `18766`.

Do not modify running production source files before completing isolated testing and preparing rollback backups.

## Requirements

- Windows 11
- Python 3
- PowerShell 5.1
- Existing ONYX CORE telemetry collector
- Reachable Raspberry Pi receiver
- Saved DPAPI-protected telemetry credential
- Windows Task Scheduler for production startup

The deployed reference environment uses Python 3.13.

The gateway expects the following files in its directory:

- `OnyxGateway.py`
- `Get-OnyxGatewayToken.ps1`
- `gateway-dashboard.html`
- `overlay.html`
- `overlay-portrait.html`

The portrait HTML file is required by the v0.5.1 gateway.

Do not put bearer tokens in command-line arguments, Git, URLs, or logs.

## Production Gateway

The production scheduled task is:

`ONYX CORE - Local Gateway`

Its source files reside in:

`D:\github_repos\onyx-core\windows\gateway`

The task runs Python under the Windows account that owns the protected DPAPI credential.

The current implementation loads dashboard and overlay HTML into memory when the gateway starts.

Changing HTML files therefore requires restarting the relevant gateway instance before the changes become visible.

### Inspect Production Status

```powershell
Get-ScheduledTask -TaskName "ONYX CORE - Local Gateway" |
    Select-Object TaskName, State

Invoke-WebRequest `
    -Uri "http://127.0.0.1:18766/dashboard" `
    -UseBasicParsing
```

Production gateway restarts must be controlled and performed independently of the telemetry collector.

## Development Gateway

The development gateway can run alongside production using port `18767`.

From the development worktree:

```powershell
cd D:\github_repos\onyx-core-v050

python -u .\windows\gateway\OnyxGateway.py `
    --dashboard ".\windows\gateway\gateway-dashboard.html" `
    --receiver svr-onyxcore.local `
    --port 18767 `
    --load-dpapi
```

The command must run under the same Windows user context that owns the DPAPI credential.

The development instance is started manually and is not the production scheduled task.

## OBS Browser Source Configuration

ONYX CORE supports two separate transparent OBS overlays.

| Setting | Landscape | Portrait |
| --- | --- | --- |
| Route | `/overlay` | `/overlay-portrait` |
| Width | 1280 | 450 |
| Height | 720 | 800 |
| Background | Transparent | Transparent |
| Refresh interval | 15 seconds | 15 seconds |
| CPU temperature | Not displayed | Displayed |

### Landscape Overlay

The original landscape overlay remains unchanged in v0.5.1.

Production URL:

`http://127.0.0.1:18766/overlay`

Recommended OBS browser-source dimensions: **1280 × 720**.

### Portrait Overlay

The new portrait overlay uses a vertically stacked telemetry layout.

Production URL after v0.5.1 deployment:

`http://127.0.0.1:18766/overlay-portrait`

Recommended OBS browser-source dimensions: **450 × 800**.

It displays:

- CPU utilization
- CPU temperature
- System memory utilization
- GPU utilization
- GPU temperature
- GPU VRAM usage and capacity
- Ethernet receive throughput
- Ethernet transmit throughput
- Telemetry health and freshness

CPU temperature is sourced from the existing LibreHardwareMonitor integration.

The HUD occupies only part of the transparent browser canvas, allowing positioning within a larger OBS scene.

### Add the Portrait Overlay to OBS

1. Create a new Browser Source in OBS.
2. Name it `ONYX CORE - Portrait`.
3. Enter the portrait overlay URL.
4. Set Width to `450`.
5. Set Height to `800`.
6. Leave Custom CSS empty initially.
7. Use OBS Transform controls to position and scale the overlay.

For development testing, use:

`http://127.0.0.1:18767/overlay-portrait`

Do not replace the existing production OBS source until the new gateway is deployed and verified.

## Telemetry Refresh and Health

Both OBS overlays refresh their displayed telemetry approximately every 15 seconds.

The Windows collector submits new measurements approximately every 30 seconds.

The overlay health indicator can report:

- LIVE
- STALE
- OFFLINE
- NO SIGNAL
- UNREACHABLE

A successful HTTP 200 response proves that the HTML is served, but does not by itself confirm that telemetry is fresh.

Always inspect the displayed values and health indicator.

## Security Boundaries

The Windows gateway is intentionally restricted.

- HTTP binds to `127.0.0.1`, not `0.0.0.0`.
- Upstream API access is read-only.
- Only approved API paths are proxied.
- Arbitrary proxy destinations are not supported.
- Authentication credentials remain outside browser content.
- Host-header validation remains enabled.
- Origin and Fetch Metadata restrictions remain enabled.
- Unapproved overlay query parameters are rejected.
- HTTP write methods remain blocked.

The service must not be port-forwarded or exposed directly to LAN/WAN.

Localhost binding does not prevent other software running on the same PC from accessing non-sensitive telemetry.

The receiver connection over private USB networking uses plain HTTP. It is not suitable for carrying sensitive information across an untrusted network.

## Testing and Validation

Run the gateway regression tests from the development worktree:

```powershell
cd D:\github_repos\onyx-core-v050

python .\windows\gateway\Test-OnyxGateway.py
```

For the Raspberry Pi receiver tests:

```powershell
python -m unittest discover `
    -s tests/services `
    -p "test_*.py"
```

### v0.5.1 Development Results

| Validation | Result |
| --- | --- |
| Receiver automated tests | 52 passed |
| Gateway automated tests | 25 passed |
| Existing landscape overlay | Verified |
| Portrait overlay endpoint | Verified |
| Portrait trailing-slash route | Verified |
| CPU temperature integration | Verified |
| Transparent canvas | Verified |
| Query parameter rejection | Passed |
| Host-rebinding protection | Passed |
| Cross-site protection | Passed |
| Development gateway HTTP validation | Passed |
| Live portrait telemetry | Verified |

**77 regression checks passed** across the receiver and gateway test suites.

The portrait overlay was also inspected visually with real telemetry using the development gateway on port `18767`.

These results do not imply that production v0.5.1 deployment has been completed.

## Safe Deployment and Rollback

Before deploying gateway changes:

1. Confirm all regression tests pass.
2. Back up production gateway source and overlay files.
3. Preserve the currently deployed Git revision.
4. Stop only the gateway scheduled task.
5. Confirm its Python process has exited.
6. Deploy the tested gateway and overlay files.
7. Restart the gateway scheduled task.
8. Verify both overlay routes and the dashboard.
9. Verify live telemetry and health status.

If the update fails, restore the saved gateway files or revert to the previous tested Git revision, restart the gateway, and verify the previous endpoints.

Do not modify the collector's DPAPI token or restart the Raspberry Pi receiver for a gateway-only overlay update.

`Start-OnyxGateway.ps1` remains available as a legacy/manual compatibility launcher. The production scheduled task runs Python directly.

## Known Limitations

- CPU temperature currently depends on LibreHardwareMonitor and the configured Ryzen sensor path.
- The original landscape OBS overlay does not include CPU temperature.
- Reboot and automatic startup recovery validation remains outstanding.
- Temporary USB-network interruption recovery validation remains outstanding.
- The portrait overlay was developed against the reference Windows and Raspberry Pi deployment.

## Release Status

**Latest published:** ONYX CORE v0.5.0 — Desktop Companion & Streaming

**Production deployment:** ONYX CORE v0.5.1 — Portrait OBS Overlay

Development validation and production deployment are complete. GitHub v0.5.1 release publication remains pending.
