# ONYX CORE v0.9.0 — Cleanup decision register (not deletion authorization)

**Date:** 2026-11-17. **Host:** SQUALL. **Evidence:** operator's read-only `Audit-OnyxV090Cleanup.ps1` transcript. **No cleanup performed or authorized.**

## Downloads

The audit found **323** matching top-level files; only the **first 50** were printed. The other 273 files were not enumerated in the shared evidence. No safe-to-delete determination is possible from that partial inventory.

- **HOLD UNTIL v0.9.0 COMMIT/RC VERIFICATION:** `ONYX_CORE_v090_M0_M1_Devkit.zip`, `ONYX_CORE_v090_M2_Sandbox_Devkit.zip`, `ONYX_CORE_v090_M3_InactiveInstall_Devkit.zip`, `ONYX_CORE_v090_M4_RuntimeRecovery_Devkit.zip`. Their content currently exists as uncommitted v0.9.0 worktree source.
- **REVIEW / POSSIBLE ARCHIVE AFTER SOURCE EQUIVALENCE:** v0.8.0 source review kits, installers, offline patch ZIPs and logs in Downloads. Never classify solely by `v080` filename; keep evidence or custom modifications not in Git.
- **KEEP UNLESS INDEPENDENTLY REVIEWED:** credentials, DPAPI files, real database snapshots, authorization/approval hashes, original collector backups, evidence needed to reconstruct release events.
- **TEMP DEVKIT STAGING:** `%TEMP%\ONYX_CORE_v090_M0_M1_Devkit`, `%TEMP%\OnyxV090-M2Devkit`, `%TEMP%\OnyxV090-M3Devkit`, `%TEMP%\OnyxV090-M4Devkit`. Retain until actual candidate commit, package comparison and recovery checkpoints succeed.

A read-only classification helper `tools/cleanup/onyx_cleanup_report.py --downloads <PATH>` can summarize **all** matching Downloads names without printing file contents. It makes no deletion decisions and never writes files.

## Program Files and protected state

**KEEP** `C:\Program Files\OnyxCore\v0.8.0`, `v0.8.0-release.sha256`, all existing rollback/backup directories and their corresponding `*-release.sha256` files until an independent per-tree source, digest, protected-ACL, and rollback-dependency inventory has been reviewed. The audit found four such backup directories:

- `rollback-v080-2d1d5c9-20261116T182855Z`
- `rollback-v080-57dd07b-20261116T192358Z`
- `v0.8.0-rc1-backup-3c38f75`
- `v0.8.0-rc2-backup-1b52295`

Keep all `C:\ProgramData\OnyxCore` contents and `%LOCALAPPDATA%\OnyxCore*` state without modification. No auto-uninstall or directory-level cleanup is approved.

## Repositories and live services

- **KEEP** production `D:\github_repos\onyx-core`, locally at v0.7.0 commit `06ec81582791fc797f74ad294195d68b2023cb66`, and its untracked `windows/collector/Send-OnyxTelemetry.pre-v050.bak`.
- **KEEP** active v0.9.0 `D:\github_repos\onyx-core-v090`; 23 development files were untracked at the cleanup audit. This is source, *not garbage*.
- **REVIEW, no deletion** `onyx-core-v070`, `onyx-core-v070-release-docs`, `onyx-core-v080`. Compare each worktree's HEAD against its remote/merged ancestry and inspect tracked/untracked status before considering `git worktree remove` in a separate approved maintenance window.
- **KEEP** the running `ONYX CORE - Telemetry Collector`, `ONYX CORE - Local Gateway`, and `LibreHardwareMonitor` Scheduled Tasks. Two tasks explicitly reference the production checkout; do not move/rename that directory.

## Later deletion gate (separate approval)

1. Freeze and independently verify the new source commit and both installable artifacts.
2. Inventory **all 323** named Downloads entries, their significance and unique backup/evidence value.
3. Compare source/evidence files against committed Git objects or archived verified evidence, and record hashes where appropriate, without disclosing secrets.
4. Create a precise allowlist of full paths and intended operations (archive or delete), with no wildcards or recursive `Remove-Item`.
5. Present the allowlist to the operator and obtain explicit authorization **before** executing cleanup. No automatic cleanup is part of v0.9.0 installation.
