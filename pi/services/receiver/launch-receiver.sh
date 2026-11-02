#!/bin/sh
# ONYX CORE v0.2.0 receiver launcher. systemd runs this as onyxcore.
set -eu
IP=$(/usr/sbin/ip -4 -o addr show dev usb0 scope global | /usr/bin/awk '$4 ~ /^192[.]168[.]137[.]/ { sub(/\/.*/, "", $4); print $4; exit }')
if [ -z "$IP" ]; then
  echo "No USB ICS IPv4 address on usb0; systemd will retry" >&2
  exit 1
fi
exec /usr/bin/python3 -B /opt/onyxcore/receiver.py --bind "$IP" --port 8765 --state-file /var/lib/onyxcore/latest-snapshot.json
