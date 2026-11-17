#!/bin/sh
# ONYX CORE v0.9.0 candidate receiver. Not registered/started by M4.
set -eu
# Deploy only to /opt/onyxcore/v0.9.0 following an independently approved review.
root='/opt/onyxcore/v0.9.0'
receiver="$root/pi/services/receiver/receiver.py"
[ -f "$receiver" ] || { echo 'Verified versioned receiver missing' >&2; exit 1; }
command -v ip >/dev/null 2>&1 || { echo 'ip command missing' >&2; exit 1; }
command -v awk >/dev/null 2>&1 || { echo 'awk command missing' >&2; exit 1; }
ip_addr=$(ip -4 -o addr show dev usb0 scope global | awk '$4 ~ /^192[.]168[.]137[.]/ {sub(/\/.*/, "", $4); print $4; exit}')
case "$ip_addr" in
    192.168.137.0|192.168.137.1|192.168.137.255|'')
        echo 'No acceptable USB IPv4 lease; systemd may retry' >&2; exit 1 ;;
    192.168.137.*) ;;
    *) echo 'Unexpected USB IPv4 address' >&2; exit 1 ;;
esac
# Source in the versioned tree; existing state/credential paths remain external.
# Both -state-file and -history-file are required for SQLite-backed history.
exec /usr/bin/python3 -B "$receiver" --bind "$ip_addr" --port 8765 \
    --state-file /var/lib/onyxcore/latest-snapshot.json \
    --history-file /var/lib/onyxcore/telemetry.db
