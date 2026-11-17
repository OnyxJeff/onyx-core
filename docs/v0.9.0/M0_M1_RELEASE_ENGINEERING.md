# ONYX CORE v0.9.0 — M0/M1 Development Checkpoint

Status: **local development kit, not a release**. No SQUALL installation or Raspberry Pi installation was attempted. The tools must be reviewed on Windows before promotion. Base source pinned to `76fd861f83960897c85271a62d50bb544be2d858` (v0.8.0).

## Core decisions

1. Release packages are built from committed Git objects, never the mutable worktree. They contain a canonical `manifest.json` listing the exact source commit, file sizes, and SHA-256 digests.
2. Separate Windows and original Pi Zero ARMv6 archives use fixed ZIP entry metadata, fixed ordering and ZIP_STORED payloads. Rebuilding a frozen commit must produce byte-identical artifacts.
3. The builder is offline and includes neither credentials nor runtime state; any tracked secret-like file stops the build instead of being silently packaged.
4. Build and verification are independent of installation, registration, configuration, approval or network activity.
5. The initial preview uses version `0.8.0-audit` against the pinned v0.8.0 source. **Do not call this a v0.9.0 release candidate.** The new builder itself cannot be included in the official artifact until it has been committed through a separately authorized change.
6. A later released version must include the checked-in builder, final Windows/Pi installer files and user documentation, and re-verify them from the frozen commit.

## Verified audit gaps that must be resolved for M2/M3

- The Pi service launcher currently omits `--history-file`; this would prevent the receiver from selecting its SQLite integrated history path on clean installation. Validate actual deployment and package all required modules.
- v0.8.0 protected Windows monitoring hardcodes `C:\Program Files\OnyxCore\v0.8.0`, source trust anchors, runtime Python paths and source inventories. Simply moving those modules to a v0.9.0 directory is **not** an approved compatible installation. Preserve the existing protected v0.8.0 installation while designing release-specific rebinding and trust acceptance.
- The legacy Windows collector contains host-specific CPU temperature URL/sensor selection. Do not overwrite existing configuration or silently claim portable hardware detection.
- v0.7.0 operational gateway/collector may still execute files within `D:\github_repos\onyx-core`; check real scheduled-task paths before any version cutover. No production task modifications are included in development bootstrap.
- The official release must provide a supported upgrade path, safe stopping/backup/restore semantics for SQLite WAL files and preserved DPAPI material, not only ZIP extraction.
- A Linux CI runner is not actual Pi Zero ARMv6 hardware acceptance.

## Targeted test policy

Run the eight release-tool tests during M1 development. They cover deterministic builds, commit pinning, rejection of private files, rejection of corrupted/duplicate ZIP members, ZIP-slip paths, exclusion of uncommitted work and no-overwrite behavior. They do not test receiver/monitoring runtime or imply functional installation acceptance.

Run feature-specific install/rollback tests during M2/M3; run full ONYX CORE regression **once after final candidate freeze**. Retest the whole suite only if the frozen candidate changes.

## Next code to develop

- PowerShell 5.1 prereq/config/installer with preview-by-default and explicit registration gate.
- Pi POSIX shell installer supporting a disposable test root, correct systemd files, receiver history and least-privilege ownership.
- Backup and rollback scripts with data-preserving transaction boundaries, no automatic v0.7-to-v0.9 production conversion.
- GitHub Actions for deterministic package build and manifest verification, followed by native Windows and ARMv6 acceptance.

## Authorization boundary

The devkit does not commit, push, merge, tag, publish, install services, modify scheduled tasks, touch protected v0.8.0 files, send diagnostics, or alter production v0.7.0. Staging untracked development files and adding an isolated Git worktree occurs only if the operator runs `Start-OnyxV090Development.ps1 -Apply` after review.
