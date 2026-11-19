# ONYX CORE

## Latest release: v0.9.0 — Reproducible Packaging & Native Recovery

**[GitHub v0.9.0 release](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.9.0)** — published, checksum-verified Windows 11 and Raspberry Pi Zero (ARMv6) release archives. This release is **not automatically installed** on SQUALL or svr-onyxcore. The existing v0.7.0-era production runtime was restored after testing; protected v0.8.0 monitoring remains separate and was not activated by this release.

v0.9.0 introduces deterministic Git-commit-pinned packages, manifest/receipt-verified versioned inactive installations, Windows runtime ACL checks, guarded Pi/Windows cutover and rollback tooling, and explicit interrupted-state recovery operations. The published archives were built from merged commit `6d73f387f37857cb3885d978baa43a44c3fbc51a`.

On SQUALL and the original ARMv6 Pi Zero, the RC2 candidate passed native inactive installation, supervised two-host activation, fresh telemetry/history/overlay checks, and rollback to original production **without manual service repairs**. The hardware-tested runtime commit is `ed41e4d0cf8049b627bc2b2613d0d231b9bb7478`; the final merge adds documentation/CI changes only. See [RC2 native acceptance](docs/v0.9.0/RC2_NATIVE_ACCEPTANCE.md).

**Not yet accepted:** blank-host provisioning, unattended upgrades, native reboot/logon durability, and every interrupted-live-state recovery path. v0.9.0 is a release-engineering milestone toward v1.0.0, not a one-click installer.

**USB-connected desktop telemetry companion for Windows 11 and an original Raspberry Pi Zero (ARMv6).**

[![Latest release](https://img.shields.io/github/v/release/OnyxJeff/onyx-core?label=release)](https://github.com/OnyxJeff/onyx-core/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Windows%2011%20%2B%20Raspberry%20Pi-blue)](https://github.com/OnyxJeff/onyx-core)
[![Development](https://img.shields.io/badge/status-active%20development-orange)](https://github.com/OnyxJeff/onyx-core/releases)

ONYX CORE collects hardware telemetry from a Windows gaming and streaming PC over a private USB Ethernet gadget connection, stores readings on a Raspberry Pi Zero, and presents them through desktop and streaming dashboards. The reference deployment monitors **SQUALL**, a Windows 11 PC with an AMD Ryzen 7 5800X and NVIDIA GeForce RTX 3070 Ti, using **svr-onyxcore**, an original Raspberry Pi Zero Rev 1.3.




## Features

### v0.9.0 reproducible release engineering (published)

- Git-commit-pinned Windows and Pi ARMv6 ZIP archives with SHA-256 sidecars, source manifests, and two-build reproducibility verification.
- Inactive versioned installation and installed-file receipt checks without overwriting the existing production tree.
- Windows least-privilege runtime ACL verification and Pi receiver readiness checks on actual hardware.
- Explicitly authorized, supervised Windows/Pi activation and rollback controllers; SQLite-consistent pre-cutover backup and preserved production credentials/history.
- Manual-only RC2 rehearsal accepted on SQUALL and the Pi Zero. Reboot-safe startup promotion and fresh-machine installation remain unaccepted.
- [Release notes](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.9.0) · [Native acceptance evidence](docs/v0.9.0/RC2_NATIVE_ACCEPTANCE.md) · [Clean-host contract](docs/v0.9.0/CLEAN_INSTALL_OPERATIONS.md).

### v0.8.0 opt-in monitoring (code-only release)

- Isolated v0.8.0 incident history with transitions and durable receipts.
- Explicitly authorized foreground monitoring and separate read-only dashboard (development `127.0.0.1:18767`, opt-in release-profile `127.0.0.1:18768`).
- Optional notification watcher remains disabled by default.
- New native route/adapter/gateway/path/LOW-integrity modules are **offline evidence contracts**, not approved Windows host attestation.
- Existing production localhost gateway `127.0.0.1:18766`, telemetry collector and OBS overlays remain unchanged.


### Hardware telemetry

| Metric | Source |
| --- | --- |
| CPU utilization and RAM usage | Windows PowerShell collector |
| CPU temperature | LibreHardwareMonitor `Core (Tctl/Tdie)` sensor |
| GPU utilization, temperature and VRAM | NVIDIA `nvidia-smi` |
| Ethernet receive / transmit throughput | Windows collector |
| Host uptime | Windows collector |

The Windows collector sends authenticated samples roughly every 30 seconds. Optional sensor failures do not stop other available metrics from being reported.

### Dashboards and streaming

- **Portrait, Landscape and Ultrawide** desktop layouts.
- **Streaming** layout optimized for 1280×720, including CPU temperature, GPU and network metrics.
- Local Windows dashboard: `http://127.0.0.1:18766/dashboard`.
- Landscape OBS overlay: `http://127.0.0.1:18766/overlay` (1280×720).
- Portrait OBS overlay (v0.5.1): `http://127.0.0.1:18766/overlay-portrait` (450×800).
- Standalone Raspberry Pi dashboard: `http://<PI_USB_IP>:8765/dashboard`.

The Streaming dashboard and OBS overlays are separate interfaces. The v0.5.1 portrait overlay includes CPU temperature; the original landscape OBS overlay remains unchanged.

### Raspberry Pi receiver

- Authenticated telemetry ingestion and read-only latest/history API.
- SQLite telemetry history and JSON latest-snapshot compatibility cache.
- Durable replay/acceptance watermark, including after history pruning.
- Telemetry freshness monitoring and health alerts.
- Standard-library Python implementation without runtime PyPI dependencies.

### USB/ICS reliability diagnostics (v0.6.0)

- Check Windows USB adapter readiness, ICS gateway addressing, routing, receiver reachability, and upstream TCP connectivity.
- Check Pi USB interface readiness, forwarding routes, gateway reachability, external TCP targets, DNS, and HTTPS.
- Collect Pi evidence using a dedicated, noninteractive SSH key restricted to a forced diagnostic command.
- Retain at most 12 observations within five minutes and fail closed on corrupt or missing evidence.
- Report `Healthy`, `WaitAndRetry`, `Investigate`, or `PossibleIcsFailure`; **every decision retains `repair_action: None`**.

Diagnostics are **manually invoked**, separate from the telemetry collector and OBS gateway, and do not install scheduled tasks, restart ICS, reset network adapters, or change production network settings. See [v0.6.0 operations](docs/v0.6.0/OPERATIONS.md) and [recovery policy](docs/reliability/recovery-policy-v0.6.0.md).

## Architecture

```text
Windows 11 — SQUALL
  ├─ PowerShell collector
  │    ├─ CPU, RAM, uptime
  │    ├─ NVIDIA GPU, temperature, VRAM
  │    ├─ Ethernet throughput
  │    └─ LibreHardwareMonitor CPU temperature
  │           │
  │           └─ Authenticated telemetry over private USB RNDIS / ICS
  │                         │
  │                         ▼
  │                Raspberry Pi Zero — svr-onyxcore
  │                  ├─ Python receiver (TCP 8765, USB-bound)
  │                  ├─ SQLite history + snapshot cache
  │                  ├─ Replay protection + health monitoring
  │                  └─ Standalone dashboard
  │
  └─ Python localhost gateway (127.0.0.1:18766)
       ├─ Desktop / Streaming dashboard
       ├─ Landscape OBS browser overlay
       ├─ Portrait OBS browser overlay (v0.5.1)
       └─ Authenticated upstream reads from Pi receiver
```

Communication uses USB Ethernet gadget networking (RNDIS) and Windows Internet Connection Sharing. In the current deployment, the USB link uses the private `192.168.137.0/24` network; this subnet is **deployment-specific**, not a universal configuration requirement.

The receiver listens only on the Pi's configured USB interface (port `8765`), and the Windows browser gateway binds to loopback (port `18766`). The gateway handles upstream authentication so browser pages do not need the receiver bearer token.

**Security note:** The private USB link uses HTTP, not TLS. Do not port-forward the receiver or gateway to LAN/WAN, and never commit bearer tokens, environment files, databases, or credentials.

## Reference hardware and software

| Component | Reference deployment |
| --- | --- |
| Receiver | Original Raspberry Pi Zero Rev 1.3 (ARMv6), 32 GB microSD |
| Pi OS | 32-bit Raspberry Pi OS |
| Receiver runtime | Python 3 / systemd / SQLite |
| Windows host | Windows 11 / PowerShell 5.1 |
| Gateway runtime | Python 3 |
| CPU / GPU | AMD Ryzen 7 5800X / NVIDIA GeForce RTX 3070 Ti |
| CPU temperature provider | LibreHardwareMonitor HTTP JSON server |
| Connectivity | USB gadget RNDIS + Windows ICS |

The CPU temperature implementation currently uses a configured LibreHardwareMonitor endpoint and the exact Ryzen `Core (Tctl/Tdie)` sensor path. It is not yet general-purpose automatic sensor discovery.

## Testing and validation

From the repository root:

**Receiver regression tests**

```bash
python3 -m unittest discover -s tests/services -p 'test_*.py' -v
```

**Windows gateway tests**

```powershell
python .\windows\gateway\Test-OnyxGateway.py
```

**CPU temperature integration tests**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\windows\collector\Test-OnyxCpuTemperature.ps1"
```

In v0.5.0 testing, **52 receiver**, **16 gateway**, and **7 CPU-temperature integration** tests passed (**75 automated checks**). Collector dry runs, GPU/network probes, live CPU temperature ingestion, Windows gateway delivery, Raspberry Pi receiver health, and deployed dashboards were also verified.

**Not yet verified:** Windows startup/reboot recovery, automatic LibreHardwareMonitor startup, and recovery following a temporary USB-network interruption.


### v0.9.0 native acceptance and release CI

The frozen RC2 runtime (`ed41e4d`) was tested on the original Pi Zero ARMv6 and SQUALL Windows 11: inactive installation, live SQLite pre-cutover backup (11,109 historical samples), manual-only candidate activation, fresh authenticated telemetry, history API, dashboard, both OBS overlay endpoints, and clean rollback. Both original hosts returned to healthy production. These tests did **not** exercise candidate reboot/logon durability or a fresh-host install.

The published v0.9.0 archives were built twice from merged commit `6d73f387`, with matching platform hashes and verified archive manifests. Windows and Ubuntu GitHub Actions release-engineering jobs passed after merge. See [native acceptance](docs/v0.9.0/RC2_NATIVE_ACCEPTANCE.md) and the [v0.9.0 release](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.9.0).

### v0.5.1 validation

The portrait OBS overlay has passed **25 gateway regression checks**, alongside **52 receiver regression tests** (77 checks total). The existing landscape route, new portrait route, query restrictions, and security checks passed.

The portrait overlay has also been verified against live telemetry using a separate development gateway on port `18767`. Production deployment verified on the Windows localhost gateway.

### v0.6.0 validation

The read-only diagnostic release passed **52 receiver**, **25 gateway**, and **7 CPU-temperature integration** regression tests (84 existing application tests), plus **35 offline recovery scenarios**, decision-engine and Pi-forwarding self-tests, and SSH/history failure-injection tests. Live read-only diagnostics reported healthy connectivity, and the dashboard and both OBS overlays were visually checked with live telemetry.

For the release-readiness runner, use `windows/networking/Test-OnyxRecoveryMilestone6.ps1` from the isolated `onyx-core-v060` development worktree. Its Milestone 5/6 test guards are specific to that worktree and the original v0.5.1 baseline; they are **not general-purpose CI tests**. See [release readiness](docs/v0.6.0/RELEASE_READINESS.md).

## Development and security principles

- GitHub is the source of truth; keep release history in version tags.
- No secrets in Git or logs.
- Test in isolation before controlled deployment to production.
- Preserve backups and documented rollback paths.
- Prefer small, auditable releases and ARMv6-conscious dependencies.
- Keep the receiver and browser gateway off public networks.

## Release history

| Version | Milestone |
| --- | --- |
| [v0.1.0](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.1.0) | USB Foundation |
| [v0.2.0](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.2.0) | USB Telemetry Foundation |
| [v0.3.0](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.3.0) | Telemetry History & Dashboard |
| [v0.4.0](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.4.0) | Health Monitoring & Local Alerts |
| [v0.5.0](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.5.0) | Desktop Companion & Streaming |
| [v0.5.1](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.5.1) | Portrait OBS Overlay — production verified |
| **[v0.6.0](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.6.0)** | **USB/ICS Reliability Diagnostics — manual diagnostics, not deployed** |
| [v0.7.0](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.7.0) | Protected installed production baseline on SQUALL |
| **[v0.8.0](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.8.0)** | **Continuous Monitoring & Operational Alerts — code-only; protected operational acceptance pending** |
| **[v0.9.0](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.9.0)** | **Reproducible Packaging & Native Recovery — manual-only two-host rehearsal accepted; no unattended install** |
| v1.0.0 | Planned stable installation and maintenance baseline |

See [all releases](https://github.com/OnyxJeff/onyx-core/releases) for detailed release notes.

## Known limitations and roadmap

- LibreHardwareMonitor must be running with its HTTP JSON endpoint enabled for CPU temperature collection.
- CPU sensor endpoint/path configuration is currently reference-host-specific.
- CPU temperature is supported by the new portrait OBS overlay in v0.5.1; the original landscape overlay remains unchanged.
- v0.9.0 RC2 did not validate persistent reboot/logon startup, fresh-machine provisioning, or all deliberately interrupted native recovery cases.
- Temporary USB-network failure/reconnection recovery remains to be validated.
- v0.6.0 reliability checks are manual and currently use an isolated development worktree and restricted Pi SSH setup. No unattended monitoring or automatic ICS repair is provided.
- Future work includes more portable sensor discovery, overlay customization, a production-ready diagnostic installation, and a stable v1.0.0 installation/maintenance baseline.

## Documentation and troubleshooting

See the [`docs/` directory](docs/) for operational guidance. The [USB gadget / Windows ICS troubleshooting runbook](docs/troubleshooting/usb-gadget-networking.md) covers observed environment-specific failures, read-only diagnostics, safe recovery, and rollback; it is **not** a required setup step for every installation (see [issue #10](https://github.com/OnyxJeff/onyx-core/issues/10)).

For v0.9.0, consult [RC2 native acceptance](docs/v0.9.0/RC2_NATIVE_ACCEPTANCE.md), [clean-host installation scope](docs/v0.9.0/CLEAN_INSTALL_OPERATIONS.md), and the [published release notes](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.9.0).

For v0.6.0, consult [release readiness](docs/v0.6.0/RELEASE_READINESS.md), [manual diagnostic operations](docs/v0.6.0/OPERATIONS.md), and [deployment/rollback planning](docs/v0.6.0/DEPLOYMENT_ROLLBACK.md).

## Project links

- [Source repository](https://github.com/OnyxJeff/onyx-core)
- [v0.9.0 release notes](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.9.0)
- [v0.8.0 release notes](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.8.0)
- [v0.6.0 release notes](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.6.0)
- [v0.5.1 release notes](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.5.1)
- [v0.5.0 release notes](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.5.0)
- [OnyxNet infrastructure portfolio](https://onyxnet.live)
- [OnyxJeff creator / streaming website](https://onyxjeff.live)

---

*ONYX CORE is developed and maintained by OnyxJeff.*
