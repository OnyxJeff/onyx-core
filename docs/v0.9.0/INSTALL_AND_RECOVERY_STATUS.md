# ONYX CORE v0.9.0 — Install and recovery operator status

**This is an honest operator preflight, not a full installation guide yet.** The M3/M4 code can produce a new *inactive* versioned code tree from a verified artifact. It does not automatically launch the Windows collector/gateway, install the Pi systemd unit, configure Windows ICS, install credentials, or safely replace an existing receiver.

## Prerequisites and hard boundaries

- Windows 11, Windows PowerShell 5.1, Python 3.13 at the reviewed interpreter path, user-scoped DPAPI token, and a private USB RNDIS/ICS link.
- Original Pi Zero Rev 1.3 ARMv6, 32-bit Raspberry Pi OS, Python 3 stdlib, NetworkManager USB gadget and an existing `onyxcore` system user/secret provisioned through a separate authorized process.
- Confirm the actual Pi SQLite filename (`telemetry.db` versus historical `companion.db`) and running service configuration before any migration. The candidate launcher defaults to `/var/lib/onyxcore/telemetry.db`; changing this without verified migration may silently fork history.
- v0.7.0 existing Windows tasks reference `D:\github_repos\onyx-core`; do not update that checkout or change task actions during v0.9.0 development.
- v0.8.0 protected operator and approval anchor are pinned to `C:\Program Files\OnyxCore\v0.8.0`. Its runtime is not relabeled or used from v0.9.0. Monitoring enrollment and notifications are not included in a fresh inactive installation.

## Verified software boundaries

- Package: independently pinned `.sha256` plus source Git commit, manifest and per-file integrity.
- Inactive installation: new version directory, no overwrites, exact install receipt, all files hash-auditable.
- Windows candidate loopback dashboard proposal: 18769; production 18766 and v0.8 release 18768 stay reserved.
- Pi candidate receiver port: 8765, **conflicts with a running legacy receiver**. The candidate service definition must not be enabled until an approved stop/rollback transaction exists.
- SQLite backup/restore helper: only disposable temporary-directory databases, with WAL-aware consistent snapshots. It is not a production backup utility yet.

## Not implemented / cannot be claimed

Operational installer from a clean Windows + Pi pair; user-aware Windows logon task setup; Pi OS/base USB gadget provisioning; validated runtime configuration and credentials; authorized service cutover; reversible task/unit changes; production-safe SQLite backup/restore; end-to-end monitoring/correct native ACL trust acceptance; native ARMv6 reboot acceptance.

## Rollback principles for later authorized testing

- Preserve old task XML and service unit definitions, executable paths, installation approvals, receipts, DPAPI secrets, Pi receiver.env, monitoring stores, SQLite WAL and SHM state, and both versions' installation trees.
- Prove candidate shutdown/process exit before restoring an older launcher or reusing port 8765/18766.
- Do not restore a SQLite database over a live process; do not mix one version's database/WAL with another's snapshot.
- After rollback, verify collector-to-Pi acceptance, `/api/v1/health`, Windows local dashboard, landscape/portrait OBS overlay and persistent histories; if any fail, stop and preserve evidence.
- Separate approval is required for every production/path/task/service mutation, not just the initial Git merge.
