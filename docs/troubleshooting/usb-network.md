# v0.1.0 USB gadget and Windows ICS troubleshooting

## Healthy configuration

- Windows ICS Public: SQUALL primary Ethernet. ICS Private: `Ethernet 3` Raspberry Pi USB RNDIS.
- Windows USB address: `192.168.137.1/24`.
- Pi `usb0`: `USB Gadget (client)` via DHCP; observed `192.168.137.167/24`; default route/DNS via `192.168.137.1`.
- Use `ssh onyxpi@svr-onyxcore.local`, verifying hostname resolution and SSH fingerprint. DHCP addresses can change.
- Official watcher is `rpi-usb-gadget-ics.service`, not `rpi-usb-gadget.service`.
- Fallback `USB Gadget (shared)` profile uses `10.12.194.1/28`; this is *not* the expected ICS client-mode address.

## RNDIS Up but SSH unreachable after Windows reboot

Read-only Windows diagnostics:

```powershell
Get-NetAdapter -Name "Ethernet 3"
Get-NetIPAddress -InterfaceAlias "Ethernet 3" -AddressFamily IPv4
Get-Service SharedAccess
Find-NetRoute -RemoteIPAddress 10.12.194.1
Resolve-DnsName svr-onyxcore.local -Type A
Test-NetConnection svr-onyxcore.local -Port 22
```

A correct ARP or mDNS record is **not proof** of working IP routing. During the initial failure, Windows had ICS address `192.168.137.1/24` and incorrectly sent `10.12.194.1` traffic through the ordinary LAN.

Confirm sharing roles without changing them:

```powershell
$manager = New-Object -ComObject HNetCfg.HNetShare
$manager.EnumEveryConnection() | ForEach-Object {
  $p = $manager.NetConnectionProps($_)
  $c = $manager.INetSharingConfigurationForINetConnection($_)
  [PSCustomObject]@{
    Name = $p.Name
    Sharing = $c.SharingEnabled
    Role = if (-not $c.SharingEnabled) {'Disabled'} elseif ($c.SharingConnectionType -eq 0) {'Public'} else {'Private'}
  }
} | Format-Table
```

Correct binding alone does not guarantee Windows DHCP is answering requests.

## Gadget oscillates between client and shared

The Pi previously attempted `USB Gadget (client)`, timed out with `ip-config-unavailable`, briefly activated shared mode and its dnsmasq DHCP server, then automatically retried client mode. Diagnosis:

```bash
ip -br addr
ip -4 route
nmcli device status
nmcli -f NAME,UUID,TYPE,DEVICE connection show
systemctl status rpi-usb-gadget-ics.service --no-pager -l
journalctl -u rpi-usb-gadget-ics.service -b --no-pager -n 80
journalctl -u NetworkManager -b --no-pager -n 80
```

The historical temporary repair added secondary Windows `10.12.194.5/28` using `New-NetIPAddress -InterfaceAlias "Ethernet 3" -IPAddress "10.12.194.5" -PrefixLength 28 -PolicyStore ActiveStore`. **This is a diagnostic-only ActiveStore address, not a persistent configuration or DHCP fix.** Do not apply it to a healthy ICS client-mode system.

## Warning remains unresolved

`g_strjoinv: assertion 'str_array != NULL' failed` occurred during Windows restart at 15:15:46 EST. Network recovered; do not claim warning-free operation or disable the official gadget watcher based only on the warning. Monitor for recurrence associated with connectivity loss.

## Recovery precautions

Do not add a second custom USB gadget stack (`g_ether`, manual `modules-load`, arbitrary watchdogs), disable the official watcher, or blindly reset Windows ICS. If SSH stays inaccessible, capture Windows IP/route/ICS diagnostics before changing configuration. **Offline SD card recovery has not been tested**; document and test it before describing it as verified.

Never publish production secrets, SSH private keys, NetworkManager secret-bearing profiles, recovery archives, or unsanitized logs.
