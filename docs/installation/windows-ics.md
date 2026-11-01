# Windows 11 ICS and Raspberry Pi Zero USB configuration

Validated host: SQUALL. Board: original Pi Zero Rev 1.3 with official Raspberry Pi USB gadget enabled through Raspberry Pi Imager v2.0.12.

## Connection

Pi's USB data port connects to SQUALL; this cable also powers the Pi. Windows identifies it as a Raspberry Pi USB Remote NDIS Network Device, adapter `Ethernet 3`.

Windows ICS: primary Intel I211 Ethernet is **Public (internet source)**; `Ethernet 3` is **Private (shared destination)**. Wi-Fi sharing disabled in the observed setup. ICS `SharedAccess` service was Running/Automatic.

Windows USB address is `192.168.137.1/24`. Pi `usb0` uses NetworkManager `USB Gadget (client)` with `ipv4.method auto`, observed lease `192.168.137.167/24`, gateway and DNS `192.168.137.1`. The Pi's address is **not a reserved static address**.

## Read-only verification

Windows:

```powershell
Get-Service SharedAccess
Get-NetAdapter -Name "Ethernet 3"
Get-NetIPAddress -InterfaceAlias "Ethernet 3" -AddressFamily IPv4
Resolve-DnsName svr-onyxcore.local -Type A
Test-NetConnection svr-onyxcore.local -Port 22
```

Pi:

```bash
ip -4 -br addr show usb0
ip -4 route
nmcli device status
nmcli -f GENERAL.CONNECTION,GENERAL.STATE,IP4 device show usb0
systemctl is-active rpi-usb-gadget-ics.service
```

Expected: DHCP lease on USB, default via SQUALL, and SSH connectivity. The official watcher can fall back to `USB Gadget (shared)` at `10.12.194.1/28`; do not confuse this with successful ICS DHCP client mode.

## Reboot acceptance

On 2026-11-01, three Pi reboots and one SQUALL reboot retest recovered USB networking automatically, without manually changing ICS or IP addressing. See [measured results](../testing/usb-reboot-validation.md) and [failure analysis](../troubleshooting/usb-network.md).

Do not treat the observed DHCP address as permanent. Do not commit ICS credentials or a secret-bearing network profile.
