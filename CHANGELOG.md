# ONYX CORE Changelog

All notable project changes will be documented here.

## Unreleased — v0.1.0 (release preparation)

- Rebuilt the foundation on original Raspberry Pi Zero Rev 1.3 (ARMv6), using Raspberry Pi OS Lite 32-bit (Trixie), official USB gadget mode and SSH.
- Documented Raspberry Pi Imager v2.0.12 custom manifest setup, including five screenshots.
- Verified Windows 11 SQUALL Internet Connection Sharing over USB RNDIS, with Pi DHCP client mode, default route, external internet connectivity and DNS.
- **Acceptance:** three controlled Pi reboots and one Windows reboot retest passed without manual network repair on November 1, 2026.
- Documented the initial failed Windows reboot, ICS/DHCP switching recovery, and an outstanding `g_strjoinv` watcher warning.
- **Out of scope:** telemetry receiver, Windows collector, dashboard, and alerting; these belong in a subsequent release.

### Before publishing v0.1.0

- Verify exact flashed OS image and custom manifest provenance; vendor metadata does not establish a locally computed archive hash.
- Confirm old Windows installation paths are removed and six legacy recovery archives remain stored safely outside Git.
- Document offline microSD recovery with an explicit tested/untested status.
- Review security, open and merge release documentation PR, then publish tag and release.

## Project initialization

- Initialized version control and the development/release workflow.
