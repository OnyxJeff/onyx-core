# ONYX CORE v0.9.0 — Release candidate notes

- **Candidate:** `0.9.0-rc2`
- **Native-tested source:** `ed41e4d0cf8049b627bc2b2613d0d231b9bb7478`
- **Date:** 2026-11-19
- **Status:** Branch candidate for CI review and merge; **not** a published final v0.9.0 release.

## What changed

- Deterministic, immutable-source Windows and Raspberry Pi ARMv6 package generation, including manifests, hash sidecars and independent rebuild verification.
- Native inactive installation into fixed, versioned Windows/Pi release trees with installed-file provenance verification and no overwrite of existing release directories.
- Windows installation ACL provisioning, validated under the actual non-elevated runtime account.
- Pi receiver readiness and bounded startup verification; Windows PowerShell Scheduled Task trigger handling corrected for missing/null trigger enumeration.
- Explicit interrupted-state recovery operations and dedicated focused regression tests.
- Privately escrowed two-host activation and rollback procedures that preserve the legacy production task/service definitions, Pi telemetry database and historical backups.

## Real-hardware acceptance

On SQUALL and the original ARMv6 Pi Zero, both RC2 archives installed inactive. The receiver, Windows collector and local gateway then activated successfully. Fresh SQUALL telemetry reached the Pi, the SQLite-backed history API worked, and the dashboard and both OBS overlay endpoints returned HTTP 200. Native recovery controllers restored both original hosts without manual repair. See [RC2_NATIVE_ACCEPTANCE.md](RC2_NATIVE_ACCEPTANCE.md) for the exact acceptance record and independent archive digests.

## Not delivered by this candidate

No blank-host or unattended installation experience, no proven reboot/logon durability, no blanket validation of intentionally interrupted live transitions, and no activation of protected v0.8.0 monitoring/notifications. This version is not yet a one-click v1.0.0 installer. It requires operator-controlled existing-host prerequisites and an explicit migration/recovery plan.

**Publication rule:** CI success and operator review are prerequisites for merging this candidate branch. Any later v0.9.0 final release must be built and checksum-attested from the actual merged commit; the RC2 hardware-tested artifact hashes belong to `ed41e4d...` only.
