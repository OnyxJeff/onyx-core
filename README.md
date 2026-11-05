# ONYX CORE

**USB-connected desktop telemetry companion for Windows 11 and an original Raspberry Pi Zero (ARMv6).**

[![Latest release](https://img.shields.io/github/v/release/OnyxJeff/onyx-core?label=release)](https://github.com/OnyxJeff/onyx-core/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Windows%2011%20%2B%20Raspberry%20Pi-blue)](https://github.com/OnyxJeff/onyx-core)
[![Development](https://img.shields.io/badge/status-active%20development-orange)](https://github.com/OnyxJeff/onyx-core/releases)

ONYX CORE collects hardware telemetry from a Windows gaming and streaming PC over a private USB Ethernet gadget connection, stores readings on a Raspberry Pi Zero, and presents them through desktop and streaming dashboards. The reference deployment monitors **SQUALL**, a Windows 11 PC with an AMD Ryzen 7 5800X and NVIDIA GeForce RTX 3070 Ti, using **svr-onyxcore**, an original Raspberry Pi Zero Rev 1.3.

**Latest published release: [v0.5.0 — Desktop Companion & Streaming](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.5.0)**

**Production deployment verified: v0.5.1 — Portrait OBS Overlay**

Version 0.5.1 adds a dedicated portrait OBS overlay while preserving the existing landscape overlay and telemetry architecture.

## Features

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


### v0.5.1 validation

The portrait OBS overlay has passed **25 gateway regression checks**, alongside **52 receiver regression tests** (77 checks total). The existing landscape route, new portrait route, query restrictions, and security checks passed.

The portrait overlay has also been verified against live telemetry using a separate development gateway on port `18767`. Production deployment verified on the Windows localhost gateway. GitHub release publication is pending.

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
| **[v0.5.0](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.5.0)** | **Desktop Companion & Streaming — latest release** |
| v0.5.1 | Portrait OBS Overlay — production verified; release publication pending |
| v1.0.0 | Planned stable installation and maintenance baseline |

See [all releases](https://github.com/OnyxJeff/onyx-core/releases) for detailed release notes.

## Known limitations and roadmap

- LibreHardwareMonitor must be running with its HTTP JSON endpoint enabled for CPU temperature collection.
- CPU sensor endpoint/path configuration is currently reference-host-specific.
- CPU temperature is supported by the new portrait OBS overlay in v0.5.1; the original landscape overlay remains unchanged.
- Windows automatic startup and reboot recovery remain to be validated.
- Temporary USB-network failure/reconnection recovery remains to be validated.
- Future work includes more portable sensor discovery, overlay customization, operational documentation, and a stable v1.0.0 installation/maintenance baseline.

## Documentation and troubleshooting

See the [`docs/` directory](docs/) for operational guidance. The [USB gadget / Windows ICS troubleshooting runbook](docs/troubleshooting/usb-gadget-networking.md) covers observed environment-specific failures, read-only diagnostics, safe recovery, and rollback; it is **not** a required setup step for every installation (see [issue #10](https://github.com/OnyxJeff/onyx-core/issues/10)).

## Project links

- [Source repository](https://github.com/OnyxJeff/onyx-core)
- [v0.5.0 release notes](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.5.0)
- [OnyxNet infrastructure portfolio](https://onyxnet.live)
- [OnyxJeff creator / streaming website](https://onyxjeff.live)

---

*ONYX CORE is developed and maintained by OnyxJeff.*
