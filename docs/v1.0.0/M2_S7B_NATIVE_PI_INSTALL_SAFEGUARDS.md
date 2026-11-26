# ONYX CORE v1.0.0 — M2-S7B Pi native installation safeguards

**Status:** Development-only, offline acceptance. No Pi filesystem writes, SSH, privileged execution, or actual installation authorized by this checkpoint.

## Frozen inputs

- Development HEAD: `cf682b0729c8d03a0ba7c882dbdb811e752bd6a2` (local S5 checkpoint).
- M2 committed source-review candidate SHA-256: `02682acb842aed94fa006afa19b0373c4990a1dba7cf38f221e3f51a3c8dc756`.
- M2-S1 runtime candidate SHA-256: `b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d`.
- Windows inactive installation receipt SHA-256: `c4c4fc7035d5010770511d254e49007b8ac583556b9ccca919c271092eb810fe`.
- Pi evidence: operator-reported M2-S7A native inspection plus a separately completed metadata-only `sudo` check confirming absence of the config target and activation marker. This is **not** newly collected or cryptographically authenticated evidence.

## Important finding — protected legacy config parent

On `svr-onyxcore`, `/etc/onyxcore` is `root:root 0700`. This is a sensible and intentionally preserved existing security boundary. Current M2-S3D `_service_can_traverse` requires other-execute or a matching service group with group-execute. Thus the existing S3D native preparation will reject that parent. This is a **genuine design blocker**, not a reason to weaken the legacy directory or run a native installer now. Reusing existing root-owned `0700` cannot work with the current direct config path for non-root service execution.

Before persistent Pi installation: review a secure approach, such as a separately secured v1-only configuration parent with updated unit and contract, or an explicitly reviewed least-privilege traverse mechanism on the existing parent. **Neither option is approved by this milestone.** No `chmod`, `chgrp`, ACL, unit, service or credential changes permitted.

## Source and receipt review

Offline review uses the original S3C and S3D functions to build the exact 14-file code payload plus code receipt (15 files) and the external config and config receipt. Code, config and unit hashes come from the approved M2-S1 candidate with explicit `SQUALL` / `usb0` / `192.168.137.0/24` / port 8765 / `/var/lib/onyxcore-v100` settings. The portable `MyWindowsPC` example is **not acceptable** for the SQUALL-specific installation candidate.

- Release code destination: `/opt/onyxcore/v1.0.0` — no overwrite.
- Configuration destination: `/etc/onyxcore/v1.0.0` — currently untraversable by service account.
- Dedicated empty state: `/var/lib/onyxcore-v100` — remains separate from `/var/lib/onyxcore`.
- Unit candidate stays **inside the code release**, is not registered and carries `RefuseManualStart=yes` plus an absent activation-marker condition.
- Legacy receiver remains enabled and active on 8765. A future activation milestone needs a separately approved handover plan to avoid port collision.
- S3C native publisher requires `renameat2(RENAME_NOREPLACE)`; S3D consists of two separate no-replace publications, so state may be published before a config failure. There is no automatic rollback or retry; operator reconciliation is required.

## Read-only acceptance on SQUALL

The guarded acceptance script checks frozen Git HEAD, production backup, Windows receipt and ZIP hashes; stages reviewed sources in a fresh **local Windows Temp** folder; runs the offline tests and review; and adds exactly **three untracked development files** after acceptance. It does not commit, push or tag. It does not connect to the Pi. The review JSON intentionally returns `BLOCKED` for S3D's config-parent traversal rule, while test execution succeeds if that finding is correctly recognized.

## Deferred gates

Native ARMv6 non-system Temp testing, privilege and parent remediation design, root-owned no-replace code publication, config/state publication, receipt/ACL audit, credential enrollment, unit registration, activation, end-to-end USB telemetry and rollback validation each need their own review and authorization. A read-only evidence snapshot cannot authorize a live install.

## R2 cross-platform correction

The offline fixed-path comparison uses `Path.as_posix()` for the existing release-parent constant, rather than the host-native `str(Path)` representation. The literal Pi release target remains unchanged. Regression tests cover both POSIX and Windows path flavors and reject alternate, relative, traversal, drive-qualified and UNC release parents. No native installer code or permissions are changed.
