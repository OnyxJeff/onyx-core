# ONYX CORE v0.9.0 — clean-host installation and startup contract

**Scope:** first-time installations only. The scripts are preview-only by default. **Do not run registration on SQUALL or its existing `svr-onyxcore` Pi.** Do not replace the installed v0.7.0 operational tasks or the v0.8.0 protected monitor.

## Package provenance and prerequisites

Obtain both official release `.zip` artifacts and their SHA-256 sidecars from one **published, reviewed** Git commit. Check each archive's independent SHA-256 digest and embedded manifest's exact 40-character source commit *before* extraction; never use an unreviewed ZIP in Downloads as the source of truth. Create Windows and Pi inactive versioned directories via `tools/installation/windows/Install-OnyxV090.ps1` and `tools/installation/pi/install-onyx-v090.sh` in preview mode first; use `--apply` and the system-preparation consent only after review and separate operator authorization.

- **Windows:** Windows 11 PowerShell 5.1, administrator privileges for *inactive* system preparation, then the regular logged-on intended user for DPAPI token enrollment and task registration; verified Python 3.13 executable and `pythonw.exe` under `C:\Python313`; OpenSSH optional for v0.8 diagnostics, not mandatory for basic telemetry. USB RNDIS + ICS must already be functional; SQUALL's adapter/IP and LibreHardwareMonitor sensor endpoint are *reference-specific*, not universal.
- **Pi:** original Pi Zero Rev 1.3 ARMv6, 32-bit Raspberry Pi OS with NetworkManager and working USB gadget/ICS DHCP, Python 3 standard library, systemd. Independently create `onyxcore` system user, `/var/lib/onyxcore` (owned by that user), and root-owned mode 0700 `/etc/onyxcore` with mode 0600 `receiver.env` containing a new 32+ character `ONYXCORE_TOKEN`. The same token is saved interactively under Windows CurrentUser DPAPI with `windows/collector/Save-OnyxToken.ps1` as the future scheduled-task principal; never put it in command arguments, screenshots, Git, or release logs.
- **Storage:** new Pi installation uses `/var/lib/onyxcore/telemetry.db` and `/var/lib/onyxcore/latest-snapshot.json`. These paths are **not** a migration recipe; older installations may use `companion.db` and require a separate backup/migration acceptance. Versioned code lives at `/opt/onyxcore/v0.9.0` and `C:\Program Files\OnyxCore\v0.9.0`.

## Clean Windows host: audit then register (only after explicit authorization)

From a normal non-elevated interactive PowerShell 5.1 session, once the Windows package is **inactive-installed**, check the receipt with `onyx_runtime_plan.py` and preview task registration:

```powershell
$SourceCommit = '<FULL_REVIEWED_40_CHARACTER_SHA>'
$Script = 'C:\Program Files\OnyxCore\v0.9.0\tools\installation\windows\Manage-OnyxV090CleanHostTasks.ps1'
& $Script -ExpectedCommit $SourceCommit
```

Once a **clean-host** operator has reviewed the output and confirmed no legacy ONYX tasks or live collector, the separately approved registration is:

```powershell
& $Script -ExpectedCommit $SourceCommit -Register -ApproveNewLogonTasks
```

It registers two **user logon**, limited-privilege candidate tasks, but **does not start** either. Next login may launch the collector and the local gateway (`127.0.0.1:18769`); do not register on a production host. The new gateway does not activate v0.8 protected monitoring. If both tasks remain stopped, separately approved rollback removes only exact matching candidate task definitions:

```powershell
& $Script -ExpectedCommit $SourceCommit -Unregister -ApproveTaskRemoval
```

If either task is running, removal refuses. Stop it with separate operator approval, then repeat the verified unregistration. DPAPI state and program files are not removed.

## Clean Pi ARMv6: audit then register (only after explicit authorization)

After a separately approved inactive installation at `/opt/onyxcore/v0.9.0`, on the Pi:

```sh
sudo /opt/onyxcore/v0.9.0/tools/installation/pi/manage-onyx-v090-clean-host-unit.sh --commit '<FULL_REVIEWED_40_CHARACTER_SHA>'
```

On a truly fresh host, with an existing provisioned `onyxcore` user and locked-down token file, separate authorization permits *registration only*:

```sh
sudo /opt/onyxcore/v0.9.0/tools/installation/pi/manage-onyx-v090-clean-host-unit.sh --commit '<FULL_REVIEWED_40_CHARACTER_SHA>' --register --approve-registration
```

This writes `/etc/systemd/system/onyxcore-v090-receiver.service` and `/etc/NetworkManager/dispatcher.d/90-onyx-v090-receiver`, runs `daemon-reload` and leaves the candidate disabled/stopped. It **refuses** registration when the legacy `onyxcore-receiver.service` exists, to avoid two receivers competing on port 8765. **A separate explicit operator decision is required to enable/start the new unit.** After clean-host activation, inspect `systemctl is-active onyxcore-v090-receiver.service`, `ss -lntp`, and the USB-bound API; validate telemetry history, gateway and both OBS overlays rather than trusting HTTP 200 alone.

For stopped/disabled candidate registration, separately authorized removal uses `--remove --approve-removal`. It refuses modified unit/dispatcher files and any active or enabled service. No database, token or installation directory is deleted.

## Recovery and unsupported migrations

These scripts are **not** v0.7→v0.9 production upgrade automation. They refuse preexisting legacy tasks/units. Preserve the v0.7 source checkout and Scheduled Tasks, all protected v0.8 files/approval anchors, SQLite state, WAL/SHM, secrets and backup receipts. Never copy a live SQLite file; use an independently verified, data-consistent snapshot and restore into an isolated location. Do not run a second receiver against the same database or TCP port.

A v0.9.0 release candidate is not accepted until real clean-install Windows and **native ARMv6** acceptance, reboot/login behavior, fallback recovery, GitHub CI, and one full post-freeze regression are documented. Linux CI cannot certify the original Pi hardware. v0.8.0 protected monitoring is **not rebound to v0.9.0** by these scripts; monitoring remains a distinct, explicitly authorized operational capability.
