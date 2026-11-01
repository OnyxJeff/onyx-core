# v0.1.0 USB gadget reboot validation

Date: 2026-11-01 (EST). Hardware: original Raspberry Pi Zero Rev 1.3 (ARMv6), Raspbian GNU/Linux 13 Trixie, kernel `6.18.50+rpt-rpi-v6`. Windows 11 host: SQUALL, USB RNDIS adapter `Ethernet 3`.

## Confirmed steady-state design

Windows ICS public interface is primary Ethernet; private interface is `Ethernet 3`, `192.168.137.1/24`. The Pi uses NetworkManager connection `USB Gadget (client)` and DHCP; observed address `192.168.137.167/24`, gateway and DNS `192.168.137.1`. **Do not assume the DHCP lease stays at that address.** Prefer `svr-onyxcore.local` when name resolution works.

## Results

| Test | Pi boot timestamp (EST) | Outcome |
| --- | --- | --- |
| Pre-reboot baseline | 14:01:11 | DHCP client connected, correct default route, gadget watcher active |
| Pi reboot #1 | 14:38:10 | PASS: hostname, 4/4 ICMP, SSH, client profile, default route, no current-boot gadget warnings |
| Pi reboot #2 | 14:44:09 | PASS: hostname, 4/4 ICMP, SSH, client profile, default route, no current-boot gadget warnings |
| Pi reboot #3 | 15:11:18 | PASS: hostname, 4/4 ICMP, SSH, client profile, default route, no current-boot gadget warnings |
| SQUALL reboot retest | Pi boot unchanged at 15:11:18 | PASS: ICS running; RNDIS Up 426 Mbps; 4/4 ICMP; TCP/22 and SSH login; Pi route intact; no manual fix |

Independent checks before reboot: Pi pinged `192.168.137.1` 4/4, pinged `1.1.1.1` 4/4, and resolved `github.com`. SSH to `192.168.137.167` succeeded. The same ED25519 host key was observed across the fallback and ICS addresses.

**Open warning:** After the successful Windows reboot, `rpi-usb-gadget-ics.service` logged `g_strjoinv: assertion 'str_array != NULL' failed` at 15:15:46 EST. Connectivity recovered, but the warning cause remains unknown. The four passes demonstrate controlled restart recovery, not lifetime stability.

## Reproducible verification

On SQUALL, after each boot:

```powershell
Get-Service SharedAccess
Get-NetAdapter -Name "Ethernet 3"
Get-NetIPAddress -InterfaceAlias "Ethernet 3" -AddressFamily IPv4
Resolve-DnsName svr-onyxcore.local -Type A
ping -n 4 svr-onyxcore.local
Test-NetConnection svr-onyxcore.local -Port 22
ssh onyxpi@svr-onyxcore.local
```

On the Pi after SSH:

```bash
date -Is
uptime -s
ip -4 -br addr show usb0
ip -4 route
nmcli device status
systemctl is-active rpi-usb-gadget-ics.service
journalctl -u rpi-usb-gadget-ics.service -b --no-pager -p warning
```

Controlled Pi reboot:

```bash
sudo systemctl reboot
```

## Earlier failed Windows reboot (preserved)

An earlier Windows reboot caused the USB adapter to acquire `192.168.137.1/24`, removing its route to Pi fallback `10.12.194.1`. Windows routed attempts via LAN gateway `10.10.10.1`. A temporary `10.12.194.5/28` secondary address restored access. Pi logs then showed repeated DHCP client timeouts and watcher transitions to/from shared mode. Subsequently ICS DHCP succeeded and the four tests above passed without manual repair. See [troubleshooting](../troubleshooting/usb-network.md).
