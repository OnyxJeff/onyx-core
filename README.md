# ONYX CORE

USB-connected telemetry companion platform for an original Raspberry Pi Zero Rev 1.3 (ARMv6), collecting live measurements from the Windows 11 host SQUALL.

## Current release: v0.3.0 — SQLite history and dashboard

- Windows collector transmits CPU utilization, memory utilization and uptime over the private USB RNDIS/ICS link.
- Pi receiver authenticates bearer-token requests, writes accepted samples to SQLite and maintains a JSON latest-snapshot compatibility cache.
- Durable acceptance watermark protects replay ordering even after seven-day history pruning.
- Local dashboard charts history and current usage; updates approximately every 30 seconds.
- Standard-library Python receiver; no runtime PyPI dependencies.

The production Pi service listens only on its `192.168.137.x` USB address, TCP `8765`. Use `http://<Pi-USB-IP>:8765/dashboard` from the attached Windows host, and paste the existing token **locally** into the dashboard. This is HTTP on a private USB link; do **not** port-forward it to your LAN or the internet.

## Validation

34 regression/integration tests passed on both Windows and original Pi Zero ARMv6; live authenticated dashboard, SQLite integrity and production collector writes verified. See [deployment and rollback](docs/v0.3.0-deployment-rollback-draft.md) for evidence, paths and limitations.

Run tests from the repo root:

```bash
python3 -m unittest discover -s tests/services -p 'test_*.py' -v
```

## Development principles

- GitHub is the source of truth.
- No secrets in Git or logs.
- Separate isolated tests from production and preserve tested deployment artifacts.
- Small, versioned releases with explicit rollback instructions.
- Prefer standard-library dependencies and hardware-conscious operation.

## Hardware

- Raspberry Pi Zero Rev 1.3 / ARMv6, 32 GB microSD
- USB RNDIS/ICS connection to Windows 11 SQUALL

## Roadmap

- v0.1.0: USB networking foundation
- v0.2.0: authenticated telemetry collector and receiver
- **v0.3.0: SQLite history and dashboard**
- v0.4.0: health monitoring and alerts
- v0.5.0: operational resilience
- v1.0.0: stable installation and maintenance baseline

See the `docs/` directory for operational guidance.
