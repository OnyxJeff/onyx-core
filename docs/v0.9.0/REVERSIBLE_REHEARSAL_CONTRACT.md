# ONYX CORE v0.9.0 — reversible Windows/Pi rehearsal source

**Status: staged source review, NOT authorized for live execution.** This is a **manual, supervised, non-reboot-safe rehearsal**, not the final unattended v0.9.0 installer or v1.0.0 upgrade experience. Never claim production migration or reboot recovery is accepted based solely on offline tests.

## Source and production boundaries

- Development base: `8a8007d925fedc4eb31a3e1bc9a68109b3373312` plus separately staged source changes. Any installation must instead be built from a *future frozen, reviewed and committed* full SHA with reproducible artifacts and verified receipts.
- SQUALL production code: `D:\github_repos\onyx-core` at `06ec81582791fc797f74ad294195d68b2023cb66`, with one known preserved local change. Legacy tasks are `ONYX CORE - Telemetry Collector` and `ONYX CORE - Local Gateway`. Original collector is `wscript.exe` with `powershell.exe` child; gateway is `pythonw.exe` on `127.0.0.1:18766`. Do not use the ephemeral observed PIDs in an automation.
- Original Pi Zero Rev 1.3 receiver: active, enabled `onyxcore-receiver.service`, `usb0:8765`, `/var/lib/onyxcore/telemetry.db`, `/var/lib/onyxcore/latest-snapshot.json`. Both source and snapshot must persist unchanged across rollback. ARMv6 and Python 3.13 required.
- `C:\Program Files\OnyxCore\v0.8.0`, its integrity anchor, both monitoring histories, the DPAPI collector token and all existing Pi secrets are protected and never included in public evidence or test fixtures.

## Controllers (read-only default)

`tools/installation/windows/Invoke-OnyxV090Rehearsal.ps1`: accepts `Preview`, `Escrow`, `Quiesce`, `StartCandidate`, `StopCandidate`, and `RestoreLegacy` phases. Every non-preview phase requires an exact, separately approved live-change switch and an immutable expected candidate SHA. Candidate Pi confirmation is required before starting the Windows candidate; restored Pi confirmation is required before restoring legacy Windows tasks. Default Preview reads task/process/socket state only. The script uses a user-private escrow under `%LOCALAPPDATA%\OnyxCore-v090-Cutover-Escrow`, retains original task definitions and allows no candidate logon triggers during rehearsal. It checks process identity and parent ownership on every stop and refuses a foreign port listener. It does not connect to Pi or touch databases.

`tools/installation/pi/onyx_pi_rehearsal.py`: phases `preview`, `escrow`, `quiesce`, `activate`, `rollback`. Live phases require explicit separate approval, root on ARMv6, a verified installed release, and a pre-provisioned root-owned `0700` `/var/backups/onyxcore`. The private escrow stores the original unit and hashes of legacy NetworkManager dispatcher scripts. It sets a **temporary systemd condition in `/run`** to prevent the old receiver being restarted by the dispatcher, and actively tests that a `systemctl start` request cannot bring the legacy unit back before activating the candidate. The candidate unit is manual-only, not enabled at boot. Rollback stops candidate, removes the exact transient guard, restores the legacy enabled state, and never copies a database snapshot onto the current SQLite database.

**The temporary Pi guard is not reboot-persistent.** After a reboot, the candidate is not configured for automatic startup and legacy dispatcher behavior may change. Consequently, an authorized rehearsal MUST be rolled back before reboot. An unattended production deployment needs a separately validated persistent legacy-dispatcher cutover, logon trigger installation, and reboot acceptance.

## Required operation order (future approval only; no live execution instructions in this source staging)

1. Freeze and commit new code, pass CI, build reproducible Windows/Pi ZIPs, verify both package/install receipts, and perform native PowerShell 5.1 and ARMv6 preflight. Verify schema compatibility on isolated database copies.
2. Prepare **inactive** Windows and Pi versioned installs. Confirm the `onyxcore` service user and group exist, and prepare the private root-owned Pi backup parent before any live stopping. Independently approve and verify a SQLite-consistent backup and restoration rehearsal.
3. Windows **Escrow**, then Windows **Quiesce**. Confirm original collector child exited and port `18766` is free. Failure leaves the original task escrow in place.
4. Pi **escrow**, **quiesce**, **activate**; verify the legacy restart guard, receiver on USB-only port `8765`, authenticated API and history behavior.
5. Windows **StartCandidate**; verify one collector, one gateway, dashboard, `/overlay` and `/overlay-portrait`, fresh samples and SQLite history. Do not reboot.
6. Roll back in order: Windows **StopCandidate**, Pi **rollback**, Windows **RestoreLegacy**. Confirm legacy tasks/receiver, fresh samples, both overlays and long-lived history. Keep all escrow files and candidate source for review.

An interrupted Windows quiesce is captured as `quiescing` and can be recovered by `RestoreLegacy` **only after the Pi legacy receiver has been confirmed** and the Windows original processes are either fully stopped or consistently running. Ambiguous partial processes are refused for manual review. An interrupted Pi quiesce is recorded as `quiescing` before creating the temporary systemd condition and supports a cautious rollback.

## Offline acceptance and remaining blockers

- `tests/installation/test_onyx_cutover_rehearsal.py` simulates success, failed candidate activation, a faulty legacy-restart guard, wrong phase, and non-mutating preview. Linux runs the full synthetic Pi suite; Windows runs Windows source-contract checks and relies on native PS5.1 parser acceptance. Synthetic success does not establish safety of native `systemctl` or Task Scheduler operations.
- **Not validated yet:** candidate `User=onyxcore` provisioning on the actual Pi, native PowerShell process supervision, protected escrow ACLs on SQUALL, systemd condition behavior on actual Pi, real USB/ICS lease changes, authenticated end-to-end telemetry, SQLite compatibility against deployed code, reboot/login durability, GitHub CI, or full post-freeze regression.
- This rehearsal intentionally does **not** create persistent logon triggers, enable candidate systemd autostart, delete original tasks, restore database bytes, read secrets, or modify any protected v0.8.0 installation.
- Git commits, push/merge/tag, installation, escrow creation, database snapshot, process stop/restart, task registration and filesystem cleanup all require separate operator approval. Source staging alone authorizes none of these actions.

## Additive reboot-safety promotion (development source; *no live authorization*)

`PromoteBoot` is distinct from the earlier non-autostarting rehearsal. Only after the
candidate has been successfully exercised end to end, the Pi may execute
`promote-boot` (separate root/ARMv6 approval) followed by Windows `PromoteBoot`
(separate Windows approval and explicit Pi readiness acknowledgement). The original
Windows tasks remain **disabled** and their full XML remains escrowed. The Windows
candidate tasks gain a **user-specific AtLogOn trigger** with limited privileges.
Rollback `StopCandidate` accepts both manual-only and *exactly one expected*
logon trigger, disables candidate tasks **first**, then stops candidate processes
and verifies port `18766` is free before enabling original tasks.

Pi `promote-boot` writes a **persistent** `/etc/systemd/system/onyxcore-receiver.service.d/90-v090-block-legacy.conf`
that requires an absent `/etc/onyxcore/v090-legacy-receiver-allow` marker before
legacy receiver startup can proceed. The existing `/run` guard also remains for
that boot; after a reboot it disappears but the `/etc` guard persists.
Only after the guard is installed, hashed, and the original unit is still stopped
and disabled is `onyxcore-v090-receiver.service` enabled at boot. This protects
against audited NetworkManager dispatcher scripts calling `systemctl` on the
old service; it does not protect against independent direct `python3 receiver.py`
launches. Dispatcher inventory must match the private escrow exactly.

A controlled rollback first **disables and stops the candidate unit**, checks that
port `8765` is free, removes only exactly recognized legacy-restart guards,
reloads systemd, and restores legacy start/enable. It never copies an old database
snapshot over `/var/lib/onyxcore/telemetry.db` and never deletes
`latest-snapshot.json`. If files or task triggers diverge, rollback refuses rather
than guessing.

**Post-reboot acceptance is NOT implicit.** `audit-boot` on the Pi and `PreviewBoot`
on Windows are read-only and emit `reboot_observed`. Pi compares the current Linux
boot UUID with the UUID stored at promotion; Windows compares the last OS boot
with the promotion UTC timestamp. Both also require the exact startup-policy,
process/socket, provenance, and current service/task state. Only a later reboot
with `reboot_observed=true` plus real authenticated telemetry, history and overlays
can satisfy the release's reboot acceptance. A logon-only Windows task will not
start until the intended user logs in, so headless/unattended boot-before-logon
is NOT a supported claim.

**Failure policy:** During partially completed promotion the durable journal
records `boot-promoting`; supervised rollback may disable candidate startup
and restore legacy after checks. Interrupted power loss may leave telemetry
unavailable rather than allow two receivers; this is a deliberate fail-closed
choice. All SQUALL/Pi live operations and reboots remain separately unauthorized.

**Still not native-accepted:** Windows ScheduledTasks trigger API behavior and
principals under Windows PowerShell 5.1; Pi user/group/ACL prerequisites;
actual systemd drop-in/dispatcher behavior on ARMv6; post-boot ICS lease,
SQLite schema validation, API authentication, dashboards/OBS overlays and final
recovery timing. Synthetic replay is not a substitute.
