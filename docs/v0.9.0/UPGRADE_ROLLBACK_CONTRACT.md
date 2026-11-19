# ONYX CORE v0.9.0 — v0.7.0 to v0.9.0 upgrade and rollback contract

Status: **IMPLEMENTATION REVIEW; NO PRODUCTION CUTOVER AUTHORIZATION**. Source baseline: `8a8007d925fedc4eb31a3e1bc9a68109b3373312` is a development checkpoint, **not** an installable candidate release. A later frozen commit and package SHA-256 must be independently approved before any installation.

## Verified reference host (2026-11-17)

- SQUALL Windows 11, PowerShell 5.1, Python 3.13.8; v0.7.0 production checkout at `D:\github_repos\onyx-core` HEAD `06ec81582791fc797f74ad294195d68b2023cb66` with one preserved, untracked legacy collector backup. Both legacy collector and gateway Scheduled Tasks are running and point to that checkout. LibreHardwareMonitor is running; no ICS Startup Recovery task is currently registered.
- `C:\Program Files\OnyxCore\v0.8.0` and its approval anchor are protected; v0.9.0 is not installed. v0.8 monitoring histories, credentials and task approvals stay independent.
- The original Raspberry Pi Zero Rev 1.3 is `armv6l`, Python 3.13.5; `onyxcore-receiver.service` is enabled and active, launching `/opt/onyxcore/receiver.py` on port 8765 with `--state-file /var/lib/onyxcore/latest-snapshot.json` and `--history-file /var/lib/onyxcore/telemetry.db`. The latter was observed at 2,400,256 bytes. Candidate unit is absent.
- GitHub comparison of v0.7.0 against v0.8.0 found no changed `pi/` source files. This is encouraging but **does not prove** deployed Pi file identity, SQLite schema compatibility or native ARMv6 acceptance.

## Cutover invariants

1. **No shared runtime:** Never run two receivers against port 8765 or the shared SQLite file. Never run two Windows telemetry collectors simultaneously. Preserve v0.7 production port 18766 for rollback; use a separate port for candidate preview if needed, not a silently altered OBS URL.
2. **Immutable code identity:** Build each Windows/Pi artifact from one later reviewed and committed candidate SHA. Independently verify package digest, embedded manifest, exact install receipt and all installed file hashes. Do not build/install directly from uncommitted worktree files.
3. **Protected state remains external:** Preserve `/var/lib/onyxcore/telemetry.db`, its WAL/SHM if present, `latest-snapshot.json`, `/etc/onyxcore/receiver.env`, all DPAPI material, all v0.7/v0.8 incident histories and source/approval anchors. Do not copy secrets into evidence bundles.
4. **Audit original task/service identity:** Privately export exact original Windows task XML and Pi unit/dispatcher/launcher bytes to separately protected backup storage **only when authorized**; record digests. Operator must review task principal, triggers, process ownership and effective ACLs before accepting any cutover method.
5. **No implicit promotion:** The existing v0.9 clean-host task and Pi registration scripts intentionally **refuse** a host that already has legacy tasks/units. Never bypass their guards. A separate reviewed upgrade orchestration procedure is required for production cutover.
6. **Rollback avoids database replacement by default:** With the same database and schema, roll back executable code and services only. Restore an older database *only* if a separately approved recovery plan proves the need and both receiver processes are stopped. The new Pi backup utility NEVER restores or modifies the source.

## New supported backup utility — approval-gated, not a cutover

The versioned `tools/installation/pi/onyx_pi_live_backup.py` is a specialized SQLite backup helper. In preview it checks file/path metadata only and **does not open SQLite**. For an independently authorized live backup, run as root on the original ARMv6 Pi with a pre-existing root-owned 0700 `/var/backups/onyxcore` directory. The script refuses any other production source/destination, demands `--approve-live-backup`, uses Python SQLite online backup (WAL-consistent), verifies integrity and per-file SHA-256, and creates a new non-overwriting root-private snapshot directory. No restore-to-production action exists.

Examples **for later explicit authorization only** (do not run as part of development):

```sh
sudo python3 -I -B /opt/onyxcore/v0.9.0/tools/installation/pi/onyx_pi_live_backup.py \
  --preview --backup-id v090-APPROVED_UTC_ID
# Separate authorizations are required both to provision /var/backups/onyxcore
# and to execute --backup --approve-live-backup with the approved backup ID.
```

The receipt records source identity and SQLite schema/table names, not telemetry rows or authentication secrets. The backup is a *point-in-time copy*. Samples accepted after that point are not in it; therefore automatic database restoration during rollback would risk losing telemetry.

## Required upgrade sequence (future authorization only)

1. Freeze/review the candidate, run one final regression, and verify native Windows 5.1 and Pi ARMv6 acceptance in an isolated environment. Verify the deployed legacy Pi code hash and compare schema on **isolated copies**, never by attempting to mutate the live DB.
2. Install verified candidate files into *new* version directories (`C:\Program Files\OnyxCore\v0.9.0`; `/opt/onyxcore/v0.9.0`) under separate administrator/root approvals, without starting anything. Preserve protected v0.8 and legacy v0.7.
3. Inventory original task/service references and capture private rollback definitions and independent hashes. Confirm sufficient space, a valid SQLite-consistent backup and restore rehearsal in disposable storage.
4. During an approved maintenance window, stop the legacy Windows collector and gateway and the legacy Pi receiver, verify process exit, then switch startup definitions through a separately reviewed orchestrator. Do **not** register candidate clean-host tasks in parallel with existing production tasks.
5. Start one candidate Pi service only after verifying the legacy receiver is stopped and disabled from automatic restart. Verify USB-only `:8765` listener, telemetry acceptance, growing SQLite history and fresh authenticated API responses. If any check fails, stop candidate and restore the legacy unit/service **before** proceeding.
6. Start one Windows collector and one gateway. Verify a fresh telemetry sample, `/dashboard`, both OBS overlay routes, and loopback-only gateway binding. HTTP 200 alone is insufficient. Verify reboot/login recovery in native acceptance; do not mutate USB/ICS or send notifications.
7. Preserve an evidence receipt with exact verified SHA, start/stop states, rollback artifact hashes, schema comparison and operator decision. Never publish credentials, private XML, or any user identity/SID.

## Rollback gates

- Stop the candidate Windows collector/gateway and candidate Pi receiver. Confirm process exit and release of ports/SQLite handles.
- Restore the *exact* saved legacy task definitions and original Pi service/dispatcher references. Re-enable and start legacy services only after candidate services are confirmed stopped/disabled.
- Reuse existing `/var/lib/onyxcore/telemetry.db` and snapshot state unless a separately approved data recovery demands otherwise; do not overwrite the database from a pre-cutover backup by default.
- Verify previous task identities, fresh collector-to-receiver telemetry, dashboard, landscape/portrait OBS, health and persistent SQLite history. On uncertainty, leave the system stopped and preserve evidence rather than guessing.
- Do not delete v0.9 code or backups during rollback; keep until postmortem and a separate cleanup approval.

## Outstanding release gates

The new backup implementation and read-only Windows upgrade preflight can be tested offline. **Actual migration activation, task XML export/restoration, deployed Pi schema comparison, native ARMv6 backup acceptance, and two-host rollback rehearsal are not yet verified.** Those are release-blocking until the operator approves a cutover implementation/test window. Git commits, pushes, installation and cleanup are separate approvals.
