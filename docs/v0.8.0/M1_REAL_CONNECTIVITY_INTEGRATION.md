# ONYX CORE v0.8.0 — M1 Real Connectivity Integration

**Status:** implementation candidate; offline unit tests passed in isolation. Real SQUALL/Pi diagnostics **not yet executed** for this candidate.

## Goal

Deliver a single useful, *manual* read-only Windows/Pi connectivity report from the existing v0.8.0 development worktree. Reuse the real `Test-OnyxUsbIcsReadiness.ps1` diagnostic and the existing restricted, forced-command SSH Pi monitor. Do not repurpose the v0.7.0 production-only one-shot runner or change protected v0.7.0 state.

## New components

- `windows/monitoring/v080/OnyxLiveConnectivity.py`: explicit CLI, config validation, bounded PowerShell and SSH subprocesses, fail-closed JSON validation, single combined report.
- `windows/monitoring/v080/Invoke-OnyxV080WindowsReadiness.ps1`: thin PowerShell 5.1 adapter that calls the existing read-only Windows diagnostic and emits one sanitized JSON result.
- `tests/monitoring/v080/test_live_connectivity.py`: isolated tests using injected subprocess fakes; **no real network access**.

## What the real one-shot can establish

- Windows USB adapter presence/up status, expected gateway address, route to Pi, ICS service status, TCP reachability of the Pi receiver.
- Pi USB route, gateway reachability, external TCP, DNS and HTTPS using the already installed, restricted Pi monitor script over SSH.
- A combined `Healthy`, `Degraded`, or `Unknown` result with explanatory classifications and timestamp. If evidence is missing or contradictory, never report `Healthy`. A confirmed Windows fault remains `Degraded` even when Pi SSH is unavailable.

**Limits:** a reachable TCP receiver does not prove telemetry samples are fresh, and Pi internet connectivity is not a guarantee of end-to-end telemetry. M2–M4 will add recurring checks, incident state, telemetry freshness, and dashboard presentation. This code does not perform ICS repair, scheduler installation, incident-store changes, notification delivery, or production updates.

## Offline acceptance (no probes)

From `D:\github_repos\onyx-core-v080` with the existing Python 3.13 interpreter:

```powershell
& 'C:\Python313\python.exe' -B -m unittest discover -s tests/monitoring/v080 -p test_live_connectivity.py -v
& 'C:\Python313\python.exe' -B windows/monitoring/v080/OnyxLiveConnectivity.py --check-config
```

The `--check-config` mode reads the tracked development config only; no SSH, network diagnostic, scheduling, or persistent writes.

## Live one-shot — REQUIRES FRESH SEPARATE AUTHORIZATION

Do not run this as part of source installation or offline acceptance. A real check performs Windows network reads and an existing noninteractive SSH Pi diagnostic, which itself makes outgoing TCP, DNS, and HTTPS probes. Once separately approved:

```powershell
& 'C:\Python313\python.exe' -B windows/monitoring/v080/OnyxLiveConnectivity.py --live-read-only
# Optional machine-readable output:
# & 'C:\Python313\python.exe' -B windows/monitoring/v080/OnyxLiveConnectivity.py --live-read-only --json
```

**Prerequisites:** exact existing v0.8.0 development branch and Phase C ancestor; Windows PowerShell 5.1; existing reviewed development config; `Ethernet 3` adapter and `192.168.137.x` settings appropriate to the reference host; previously configured SSH public-key forced command `onyxcore-monitor` on the Pi; no elevation required. The command sanitizes SSH/process errors; `Unknown` means evidence is missing, not necessarily an outage.

## Development boundaries and next milestones

- **M1:** implement manual real read-only check, offline acceptance, then separately approved SQUALL/Pi functional validation.
- **M2:** opt-in continuous worker with non-overlap, bounded lifecycle, backoff and clean shutdown.
- **M3:** persist incidents and recovery state in an isolated development store; fail closed on stale/incomplete evidence.
- **M4:** bridge incident history and freshness into the dashboard/overlay APIs.
- **M5:** notification channel with explicit opt-in, deduplication and recovery messages.
- **M6:** end-to-end acceptance, reproducible operations and release decision.

No production code, v0.7 histories, Scheduled Tasks, tokens or Pi services were modified to create this candidate.
