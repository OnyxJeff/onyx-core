# v0.1.0 — Offline microSD recovery (untested contingency)

**Status: DOCUMENTED, NOT TESTED.** No offline repair of the new ONYX CORE Pi Zero installation has been performed. This is a safety-first recovery procedure, not evidence that the procedure will restore a corrupted card.

## Before acting

1. Leave the working Pi alone if its USB network currently passes tests. Record the failure first using [USB troubleshooting](../troubleshooting/usb-network.md).
2. Do not mistake Windows ICS client-mode `192.168.137.x` for the fallback `10.12.194.1/28`. Check the adapter's address and route before concluding the OS is damaged.
3. If you must remove the microSD card, shut down Pi cleanly while SSH is available: `sudo poweroff`, then confirm it has stopped before disconnecting power.
4. Preserve all available data before editing: image the card with a suitable disk imaging tool to a **different** drive with enough capacity. Do not store the only recovery copy on the card being repaired. Verify that the copy is readable.
5. Use a separate supported Linux machine or live environment to inspect Linux ext4 partitions. Windows may show only the small FAT boot partition; this does **not** mean the Linux root partition is missing.

## Inspection-first approach on Linux

Identify the SD card with `lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINTS,MODEL` **before** selecting a device. Never infer its device path from example output. Record its partitions and mount status. If repair is required, work on a verified backup image or unmounted card, not the only copy. Mount the suspected root filesystem **read-only** to inspect logs and network configuration. Do not run automatic filesystem repair or write boot overrides until the failing component and rollback are understood.

Inspect the system's NetworkManager profile **names** and the official gadget service configuration; avoid publishing the contents of secret-bearing profiles. For this deployment, the observed profiles are `USB Gadget (client)` and `USB Gadget (shared)`; expected service is `rpi-usb-gadget-ics.service`. Do not add duplicate `g_ether` or `dwc2` hacks to a system provisioned with the official gadget integration.

## Recovery choices

- If the problem is Windows ICS/RNDIS or an IP route, restore Windows-side connectivity first; SD-card edits will not address an ICS DHCP failure.
- If a Linux network profile is proven corrupt, back up the original before considering an offline edit, and record precisely what changed. No generic write command is supplied because partition and configuration details have not been verified for an offline session.
- If the filesystem cannot be recovered, reimage using the documented 32-bit Raspberry Pi OS Lite installation flow only after confirming which data and settings must be restored. Old ONYX CORE recovery archives are from a prior application installation and **are not** a verified full-disk image of this new OS.

## Evidence required before claiming tested recovery

Record actual target SD card identification, backup image validation, read-only inspection results, repair steps and rollback, successful boot, USB RNDIS address, default route, SSH, and repeat reboot test. Until performed, report the offline path as **untested**.
