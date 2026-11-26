# ONYX CORE — v1.0.0-rc.1 (prerelease draft)

Selected release designation: `v1.0.0-rc.1`. Publication is not yet authorized or completed.

## Highlights

- Deterministic Windows 11 and Raspberry Pi OS Trixie ARMv6 runtime packages.
- Validated matching platform configurations, clean inactive publication, receipts,
  separate credential preparation and explicit activation and deactivation tooling.
- Hidden WScript collector launcher, loopback dashboard and OBS overlays; monitoring
  panel branding updated to v1.0.0.
- USB-connected telemetry receiver with persistent history; supervised read-only monitoring
  projection and explicit observation workflow. No unattended monitoring or repairs by default.
- Guarded, non-destructive rollback preserves runtime, credentials and persistent history.

## Installation

Read M5_S6_INSTALLATION.md in the authenticated package before running any installer.
Python 3.13, Windows PowerShell 5.1 and WScript/VBScript are prerequisites on Windows;
Raspberry Pi OS Trixie ARMv6 and Python 3.13 on the Pi. USB gadget networking, ICS and
Pi service account setup are operator prerequisites. A direct Pi IPv4 address is required.
Verify independently published SHA-256 checksums; never put a token in CLI arguments or
configuration. This clean installer refuses existing ONYX installations; it is not an upgrade.

## Qualification and known limitations

Existing operational application and lifecycle tests passed; R2 isolated native Windows and
ARMv6 installation and rollback components passed. Complete installation and rollback on
previously unused hosts has not been qualified. Final launcher-plan correction and docs are
offline changes; the candidate is not a new native deployment. Physical USB removal/hot-plug
is not qualified; manual ICS restoration was required after device removal. VBScript availability
must be checked. A partially completed activation may require manual ownership review.

M5 final review passed: Linux 86/88 and Windows 82/88 tests passed, with two and six
platform-specific skips respectively and no failures. Both candidate archives reproduced
byte-for-byte. The archive manifest identifies runtime version 1.0.0 and its M4 source
lineage; the public release designation is the prerelease v1.0.0-rc.1.

Final release asset names, checksums bound to the final release commit and publication
date will be supplied during M6. Do not use an RC as proof of a fully qualified stable installer.
