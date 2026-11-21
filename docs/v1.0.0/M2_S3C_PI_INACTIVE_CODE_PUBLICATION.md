# ONYX CORE v1.0.0 - M2-S3C Pi Inactive Code Publication

**Development status:** Offline-accepted code proposal only. No Pi writes or operator authorization for a native installation.

## Scope

A future Linux ARMv6/root command could atomically create **only** `/opt/onyxcore/v1.0.0`, using a source-verified 11-file Pi runtime from the pinned M2-S1 bundle. The release contains a canonical internal Pi config, untouched original bundle manifest, **uninstalled** unit candidate, and a SHA-256 installation receipt (15 files total). It does not provision `/etc/onyxcore`, `/var/lib/onyxcore-v100`, credentials, service accounts, network interfaces, or active units. The legacy state `/var/lib/onyxcore` is forbidden in this phase.

## Native protection (for later separately authorized work)

- CLI previews by default; actual system publishing needs `--install --approve-inactive --approve-system` AND root, Linux ARMv6, Python 3.13 and required OS tools.
- Parent `/opt/onyxcore` must already exist and be root-owned, with no symlink on the open path and no group/other write permission. No parent auto-creation.
- New directories have owner `root`, group `onyxcore`, mode `0750`; files `0640`, including internal nonsecret config. No external credential is read or copied.
- Builds into a new private sibling `.onyx-v100-staging-<random>` in the **same directory**; Linux `renameat2(RENAME_NOREPLACE)` prevents overwriting even if the target appears between preflight and publish. No fallback to ordinary rename.
- No automatic unit registration, service enable/start, privilege escalation, state migration, rollback, or history modification. An inert unit file inside the release directory is not installed as a systemd unit.

## Known remaining blockers

- A future native preflight must inspect real `/opt/onyxcore` ownership/permissions; this milestone has **not** done so.
- Configuration must later be installed to `/etc/onyxcore/v1.0.0/pi-armv6.config.json` as referenced by the unit candidate. The internal config is a review snapshot, **not** a system configuration installation.
- The `onyxcore` service user must exist, and a separate `/var/lib/onyxcore-v100` with safe ownership is needed. Credentials and activation guard must be enrolled separately.
- Package assembly for final v1.0.0 release must bundle the installer tooling and documented native prerequisites; M2-S1 remains a core runtime candidate.
- Acceptance with real native ARMv6 hardware remains mandatory before allowing any Pi deployment.

## SQUALL offline acceptance

M2-S3C's guarded PowerShell application accepts three new development files only, runs Python tests using the pinned candidate and checks read-only CLI preview. It does not run any native `--install` command and does not use SSH.
