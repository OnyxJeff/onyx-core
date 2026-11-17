#!/bin/sh
# ONYX CORE v0.9.0 M2 read-only Pi Zero Rev 1.3 acceptance inventory.
# No sudo, no network packets, no system writes, no service changes.
set -eu
printf '%s\n' '=== ONYX CORE v0.9.0 PI READINESS (READ ONLY) ==='
printf 'kernel_arch: '; uname -m
printf 'python: '; python3 --version 2>&1 || true
for cmd in python3 systemctl ip awk; do
    if command -v "$cmd" >/dev/null 2>&1; then
        printf '%s: present\n' "$cmd"
    else
        printf '%s: missing\n' "$cmd"
    fi
done
if [ -d /sys/class/net/usb0 ]; then
    printf '%s\n' 'usb0: present'
else
    printf '%s\n' 'usb0: missing'
fi
if [ -e /etc/onyxcore/receiver.env ]; then
    printf '%s\n' 'receiver_credentials: present (not read)'
else
    printf '%s\n' 'receiver_credentials: absent'
fi
if [ -e /var/lib/onyxcore/telemetry.db ]; then
    printf '%s\n' 'receiver_history: present (not read)'
else
    printf '%s\n' 'receiver_history: absent or stored elsewhere'
fi
printf '%s\n' 'No changes performed.'
