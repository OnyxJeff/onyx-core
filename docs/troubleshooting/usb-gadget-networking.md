# Troubleshooting USB gadget networking and Windows ICS

> **Scope:** Environment-specific deployment guidance for an original Raspberry Pi Zero Rev 1.3 (ARMv6), Raspberry Pi OS based on Debian 13, NetworkManager 1.52.1, USB `g_ether`/RNDIS and a Windows 11 host. This is a case study and diagnostic runbook, **not** a universal fix or an ONYX CORE application bug. Tracks [issue #10](https://github.com/OnyxJeff/onyx-core/issues/10).
>
> **Safety:** Do not run the repair commands blindly or while relying solely on the connection you are about to change. Make a verified bootable SD image, preserve existing NetworkManager connection files and arrange offline SD-card access first. Never publish bearer tokens, `receiver.env`, database files or host credentials.

## Expected architecture and tested state

```text
Windows SQUALL
  uplink "Ethernet" -> internet (ICS public)
  USB RNDIS "Ethernet 3" -> Pi (ICS private)
  Windows USB gateway: 192.168.137.1/24
  Windows recovery-side example: 10.12.194.9 [observed /24]
             |
             | one powered USB data connection; dwc2 + g_ether / usb0
             v
Pi Zero ONYX CORE
  usb0: 192.168.137.167/24; default via 192.168.137.1
  usb0: 10.12.194.1/28 (recovery)
  receiver: 192.168.137.167:8765 (private USB only)
```

The addresses, Windows adapter names and recovery subnet **describe one observed deployment only**. Do not copy them into another network without checking conflicts. The Windows recovery-side address was observed with a /24 prefix, while the Pi recovery address used /28; standardize compatible, non-overlapping subnet masks on a new installation rather than relying on these historical settings. Windows ICS DHCP behavior and chosen private subnet can vary. ONYX CORE's application receiver must remain on its private USB interface; never expose TCP 8765 to LAN/WAN.

## Quick fault isolation: distinguish layers

| Observation | Check | Likely layer |
| --- | --- | --- |
| No Windows RNDIS device | Device Manager / `Get-PnpDevice` and USB cable | USB enumeration/driver |
| RNDIS present but Windows adapter disconnected | `Get-NetAdapter`, Pi kernel journal | Link/carrier/startup |
| `usb0` exists but no profile/IP | `nmcli device status`, NetworkManager journal | Device unmanaged/profile |
| Pi reaches Windows USB gateway but not public IP | Pi gateway/external ping, Windows ICS roles | Windows ICS/NAT/forwarding |
| Public IP reachable, hostname resolution fails | `getent ahostsv4 github.com` | DNS |
| Internet/DNS work but clock unsynchronized | `timedatectl status`, NTP logs | Time service/startup |
| Telemetry receiver inactive despite network | `systemctl status onyxcore-receiver.service` | Application/service |

**Never interpret `SharedAccess: Running` or a configured public/private ICS role as proof that outbound forwarding works.** Similarly, an RNDIS device visible in Windows does not prove Linux has configured `usb0`.

### Read-only checks on Raspberry Pi

```bash
ip -4 addr show usb0
ip -4 route
nmcli device status
nmcli -f GENERAL.STATE,GENERAL.CONNECTION,GENERAL.REASON device show usb0
journalctl -b -u NetworkManager --no-pager -o short-monotonic | grep -Ei 'usb0|unmanaged|carrier|activation|connected'
journalctl -b -k --no-pager -o short-monotonic | grep -Ei 'dwc2|g_ether|usb0'
ping -c 3 -W 2 192.168.137.1
ping -c 3 -W 2 1.1.1.1
getent ahostsv4 github.com
timedatectl status
systemctl is-active onyxcore-receiver.service
systemctl is-active rpi-usb-gadget-ics.service
```

If `resolvectl` is unavailable, that is not itself a DNS failure; use `getent` and examine the resolver configured by the OS.

### Read-only checks on Windows (Administrator PowerShell)

```powershell
Get-NetAdapter -Name 'Ethernet 3' | Format-List Name,Status
Get-NetIPAddress -InterfaceAlias 'Ethernet 3' -AddressFamily IPv4 |
    Format-Table IPAddress,PrefixLength,AddressState
Get-Service SharedAccess | Format-List Name,Status,StartType
ping.exe -4 -n 3 192.168.137.167
ping.exe -4 -n 3 1.1.1.1

$ics = New-Object -ComObject HNetCfg.HNetShare
foreach ($connection in $ics.EnumEveryConnection()) {
    $props = $ics.NetConnectionProps($connection)
    $config = $ics.INetSharingConfigurationForINetConnection($connection)
    [pscustomobject]@{
        Adapter = $props.Name
        SharingEnabled = $config.SharingEnabled
        ConnectionType = if ($config.SharingEnabled) {
            if ($config.SharingConnectionType -eq 0) {'Public'}
            elseif ($config.SharingConnectionType -eq 1) {'Private'}
            else {'Unknown'}
        } else {'Not shared'}
    }
}
```

Replace example adapter names and addresses with those actually observed. Confirm the Windows uplink reaches the internet and the Pi can reach the private gateway before blaming ICS forwarding.

## Failure A: NetworkManager leaves USB gadget unmanaged

On the affected image, the installed `/usr/lib/udev/rules.d/85-nm-unmanaged.rules` contained:

```udev
ENV{DEVTYPE}=="gadget", ENV{NM_UNMANAGED}="1"
```

The failed boot journal showed the kernel creating `usb0`, but no subsequent NetworkManager profile activation. An offline inspection found the gadget-specific unmanaged rule. **Only when NetworkManager is intentionally responsible for `usb0`**, a targeted configuration override was successful:

```ini
# /etc/NetworkManager/conf.d/90-onyxcore-usb-gadget.conf
[device-onyxcore-usb0]
match-device=interface-name:usb0
managed=1
ignore-carrier=yes
```

Do not edit the vendor rule under `/usr/lib/udev/rules.d`. On systems using `systemd-networkd`, ifupdown, or another manager, first determine which service owns the interface. Verify `nmcli -f GENERAL.STATE,GENERAL.CONNECTION device show usb0` and the boot journal after applying the override. `ignore-carrier=yes` alone did **not** resolve the tested issue.

### Verified local persistent profile

The tested deployment used a named NetworkManager Ethernet profile bound to `usb0`, automatic activation, manual IPv4 addresses `192.168.137.167/24` and `10.12.194.1/28`, IPv4 default route through `192.168.137.1`, and IPv6 disabled. NetworkManager's `USB Gadget (shared)` profile **name** remained from a previous setup; despite that name its IPv4 method was `manual`, not shared/NAT. Always inspect the actual configuration rather than inferring behavior from its name.

If a shipped `rpi-usb-gadget-ics.service` is continuously switching client/shared profiles, its repeated six-second DHCP failures or activations may produce SSH lag and unstable carrier. In this deployment the switcher was disabled **after** the static replacement profile existed. Do not disable an active network service without a verified fallback path.

## Failure B: Local gateway works but internet sharing does not

During an observed simultaneous cold boot:
- Pi `usb0` had both expected addresses, an IPv4 default route, and `LOWER_UP`.
- Pi → Windows ICS gateway `192.168.137.1`: 3/3 replies.
- Pi → `1.1.1.1`: 0/3 replies; hostname lookup produced no result; NTP reported unsynchronized.
- Windows `SharedAccess` was running with public `Ethernet` and private `Ethernet 3` correctly assigned, and Windows itself could reach `1.1.1.1`.

A **single manual** Windows Administrator PowerShell recovery command restored internet, DNS and NTP:

```powershell
Restart-Service -Name SharedAccess
```

This can briefly disrupt internet sharing for USB clients; do not apply it to an unrelated production host without considering other ICS clients. If Windows cannot reach the internet itself, or the Pi cannot reach its Windows gateway, diagnose those problems before restarting ICS.

### Windows startup recovery task: tested behavior and limits

The host used a PowerShell 5.1 script at `C:\ProgramData\OnyxCore\scripts\Repair-ICS.ps1` and a SYSTEM-account Scheduled Task `ONYX CORE - ICS Startup Recovery` with two-minute boot and logon triggers. The script waited for `Ethernet 3` to be `Up` and for gateway `192.168.137.1` to be preferred, then restarted (or started) `SharedAccess` once, checked its state and wrote to `C:\ProgramData\OnyxCore\logs\ics-recovery.log`.

**Verified:** manual Scheduled Task execution returned exit code 0; after a Windows sign-in, Task Scheduler event 119 recorded the logon trigger at 2026-11-02 16:04:07, and events 201/102 and script log recorded a successful `SharedAccess` restart at 16:04:20. Pi internet, DNS and NTP were also verified following ICS recovery in separate tests.

**Not verified:** execution before sign-in, or an automatic restart on *every* shutdown/power-on combination. Windows Fast Startup was configured enabled; its role in missing a particular boot trigger was a plausible hypothesis, **not** conclusively proven. The script **unconditionally restarts ICS** when its RNDIS/gateway checks pass; it does not test Pi-to-internet forwarding, and it is not an end-to-end health checker. Multiple triggers can cause redundant restarts unless guarding is added. Do not call this solution fully unattended or universally applicable.

For deployments needing pre-logon recovery, design and verify a SYSTEM-level startup mechanism and a safe end-to-end health probe. Consider retries, event logging, no simultaneous instances and a policy not to flap a healthy network. Do not install broad/constant restarters based only on a running service check.

## Offline recovery if SSH is lost

1. Power off the Pi cleanly if possible. Remove the microSD and attach it to a Linux computer.
2. **Identify the SD drive by size and partitions**, e.g., `lsblk -f`. Do not assume it is `/dev/sda`; avoid the host's OS disk.
3. Image the card before writing, if not already backed up. Mount the root filesystem read-only for diagnosis (for ext4, use `-o ro,noload` when appropriate).
4. Inspect `/etc/NetworkManager/conf.d/`, `/etc/NetworkManager/system-connections/`, and persistent logs with `journalctl --directory=/mnt/onyxcore-root/var/log/journal`.
5. For a targeted fix only, remount the **verified SD root partition** read-write; back up the specific config file and edit the minimal override. Verify file ownership and profile permissions (connections are normally root-owned and `0600`).
6. `sync`, unmount, restore the card and validate carrier, active profile, both addresses, gateway, internet, DNS, NTP and receiver. Revert only the changed file if the test fails.

If using `sudo` with glob patterns beneath root-only directories, the calling shell may not expand `*.nmconnection`; use `sudo find ... -name '*.nmconnection'` to inspect entries. Never reimage or overwrite the telemetry database merely to troubleshoot networking.

## Validation record (November 2, 2026)

| Test | Observed result |
| --- | --- |
| Pi-only reboot | USB disconnect ~8s; USB reconnect ~40s; SSH successful ~1m58s |
| Pi network state | `usb0` connected, `UP,LOWER_UP`, two addresses, default route |
| Pi-only reboot checks | Receiver active; switcher inactive; public ping 3/3; NTP synchronized |
| PC and hub simultaneous cold boot | SSH and ping responding by ~1m38s |
| Cold-boot ICS forwarding | Gateway 3/3; internet 0/3 **before** Windows service restart |
| After manual ICS restart | Public ping 3/3, DNS resolution and NTP restored |
| Manual Windows Scheduled Task | Exit 0; receiver/internet/DNS/NTP healthy |
| Automated Windows **logon** task | Trigger event 119 at 16:04:07; exit 0 at 16:04:20 |
| Boot task before login | **Not verified** |

This is evidence from one installation with a small number of boot tests, not a reliability guarantee or a tested universal installation recipe.

## Rollback and change control

- **Pi:** Restore the previously backed-up NetworkManager override/profile only with an offline-access plan; preserve the OS, SQLite history and credentials. If reverting to a prior profile-management model, restore the corresponding switcher state deliberately rather than mix conflicting managers.
- **Windows:** Disable the recovery task before deleting it; keep its script and logs for diagnosis. To remove only the task, use Administrator PowerShell `Disable-ScheduledTask -TaskName 'ONYX CORE - ICS Startup Recovery'`. This does not change the Pi. Undo ICS adapter or address changes only if you explicitly made them and have recorded the original values.
- **Application:** No ONYX CORE v0.3.0 receiver, database or collector modifications were required for this incident.
- **Security:** Redact user identities, local hosts, tokens, raw database contents and logs before attaching evidence publicly.

See also [v0.3.0 deployment and rollback](../v0.3.0-deployment-rollback-draft.md) for the application's independent release validation. Changes to this runbook follow branch → PR → review → merge; no release is implied by documentation alone.
