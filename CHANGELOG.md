# ONYX CORE Changelog

All notable project changes are documented here. Detailed release notes are available in the [GitHub Releases](https://github.com/OnyxJeff/onyx-core/releases).

## Unreleased

- No unreleased application changes recorded.
- Windows startup, LibreHardwareMonitor startup, and USB-network recovery validation are planned follow-up work.

## [v0.5.1](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.5.1) — 2026-11-05

### Portrait OBS Overlay
- Added `/overlay-portrait` for transparent 450x800 OBS browser sources.
- Included CPU temperature, CPU/RAM, GPU/VRAM, and Ethernet throughput telemetry.
- Added LIVE, STALE, OFFLINE, and connection-status indicators.
- Preserved the original landscape `/overlay` behavior.
- Verified 52 receiver and 25 gateway regression checks (77 total).
- Deployed and verified the production gateway.
- No receiver schema, SQLite migration, or collector change was required.

## [v0.5.0](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.5.0) — 2026-11-04

### Desktop Companion & Streaming
- Introduced the Windows localhost gateway on port 18766.
- Added the desktop dashboard and landscape OBS overlay.
- Added authenticated upstream access using a DPAPI-protected credential.
- Expanded telemetry with CPU temperature via LibreHardwareMonitor, GPU utilization, GPU temperature, VRAM, and Ethernet throughput.
- Improved Portrait, Landscape, Ultrawide, and Streaming dashboard layouts.
- Preserved existing receiver history and optional-sensor compatibility.
- Passed 75 automated checks across receiver, gateway, and CPU-temperature integration suites.
- Production deployment verified; reboot and recovery validation remained outstanding.

## [v0.4.0](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.4.0) — 2026-11-03

### Health Monitoring & Local Alerts
- Added authenticated `GET /api/v1/health`.
- Introduced HEALTHY, WARNING, CRITICAL, NO DATA, UNKNOWN, and DEGRADED health states.
- Added local dashboard alerts and recovery transitions.
- Improved single-sample charts and last-known readings during outages.
- Preserved SQLite history and acceptance watermark.
- Passed 52 regression tests on both Windows and Raspberry Pi Zero.
- Production deployment verified without database migration.

## [v0.3.0](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.3.0) — 2026-11-02

### Telemetry History & Dashboard
- Added seven-day SQLite telemetry history.
- Implemented persistent replay protection.
- Introduced authenticated history APIs and a live browser dashboard.
- Passed 34 tests on Windows and Raspberry Pi Zero ARMv6.
- Verified production telemetry and database integrity.

## [v0.2.0](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.2.0) — 2026-11-02

### USB Telemetry Foundation
- Added an ARMv6-compatible Python telemetry receiver.
- Implemented authenticated HTTP ingestion over USB RNDIS.
- Added Windows CPU, memory, and uptime collection.
- Introduced DPAPI-protected credentials and hidden collector startup after sign-in.
- Added the restricted systemd receiver and latest-snapshot persistence.
- Implemented collector shutdown handling and network retry behavior.
- Passed 14 receiver tests; restart and USB interruption recovery were validated for the tested release scenarios.
- Long-term endurance and live DHCP reassignment remained unverified.

## [v0.1.0](https://github.com/OnyxJeff/onyx-core/releases/tag/v0.1.0) — 2026-11-01

### USB Foundation
- Established Raspberry Pi OS Lite 32-bit (Trixie) on the original Raspberry Pi Zero Rev 1.3.
- Configured official USB gadget mode, Windows RNDIS, and Internet Connection Sharing.
- Verified SSH, DNS, and internet connectivity.
- Passed three Pi reboot tests and one Windows reboot retest.
- Added installation, troubleshooting, validation, and recovery documentation.
- Preserved historical limitations concerning gadget watcher warnings, image provenance, offline microSD recovery, and long-term stability.

## Project Initialization

- Established version control and the feature-branch, review, and release workflow.
