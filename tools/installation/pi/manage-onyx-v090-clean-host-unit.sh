#!/bin/sh
# ONYX CORE v0.9.0: register only an INACTIVE candidate systemd unit on clean ARMv6 host.
# PREVIEW by default. Does not start/enable receiver, change USB/ICS, or touch databases.
set -eu
usage() { echo 'Usage: script --commit FULL_SHA [--register --approve-registration | --remove --approve-removal]' >&2; exit 2; }
commit='' action='preview' approve='no'
while [ "$#" -gt 0 ]; do
    case "$1" in
        --commit) [ "$#" -ge 2 ] || usage; commit=$2; shift 2 ;;
        --register) [ "$action" = preview ] || usage; action='register'; shift ;;
        --approve-registration) approve='register'; shift ;;
        --remove) [ "$action" = preview ] || usage; action='remove'; shift ;;
        --approve-removal) approve='remove'; shift ;;
        *) usage ;;
    esac
done
case "$commit" in *[!0123456789abcdef]*|'') usage ;; esac
[ "${#commit}" -eq 40 ] || usage
if [ "$action" != preview ] && [ "$action" != "$approve" ]; then
    echo 'Explicit matching action approval required' >&2; exit 2
fi
if [ "$action" = preview ] && [ "$approve" != no ]; then
    echo 'Approval without action refused' >&2; exit 2
fi
root='/opt/onyxcore/v0.9.0'
unit="$root/tools/installation/pi/onyxcore-v090-receiver.service"
dispatcher="$root/tools/installation/pi/90-onyx-v090-receiver"
planner="$root/tools/installation/common/onyx_runtime_plan.py"
unit_target='/etc/systemd/system/onyxcore-v090-receiver.service'
dispatcher_target='/etc/NetworkManager/dispatcher.d/90-onyx-v090-receiver'
[ -f "$unit" ] && [ -f "$dispatcher" ] && [ -f "$planner" ] || {
    echo 'Versioned candidate code not installed' >&2; exit 2;
}
[ ! -L "$unit_target" ] && [ ! -L "$dispatcher_target" ] || {
    echo 'Redirected target refused' >&2; exit 2;
}
command -v python3 >/dev/null 2>&1 || { echo 'Python 3 required' >&2; exit 2; }
python3 -I -B "$planner" --installed-root "$root" --platform pi-armv6 --expected-commit "$commit" >/dev/null || {
    echo 'Candidate file hashes/commit/receipt invalid' >&2; exit 2;
}
printf '%s\n' 'ONYX CORE v0.9 clean-host Pi service registration plan' \
    'Unit: onyxcore-v090-receiver.service (INACTIVE)' \
    'Port 8765 requires the legacy receiver to be absent before activation.' \
    'No automatic start, enable, credential reads, DB changes or network repairs.'
[ "$action" != preview ] || { echo 'PREVIEW ONLY'; exit 0; }
[ "$(uname -m)" = armv6l ] && [ "$(id -u)" -eq 0 ] || {
    echo 'Native ARMv6/root required' >&2; exit 2;
}
command -v systemctl >/dev/null 2>&1 || { echo 'systemd required' >&2; exit 2; }
if [ "$action" = register ]; then
    [ ! -e "$unit_target" ] && [ ! -e "$dispatcher_target" ] || {
        echo 'Candidate registration already exists' >&2; exit 2;
    }
    # Candidate must never compete with an older service for the same USB address/port.
    [ ! -e /etc/systemd/system/onyxcore-receiver.service ] || {
        echo 'Legacy receiver unit present; clean-host registration refused' >&2; exit 2;
    }
    [ -d /var/lib/onyxcore ] && [ -f /etc/onyxcore/receiver.env ] && id onyxcore >/dev/null 2>&1 || {
        echo 'Missing separately provisioned state directory, token file or service account' >&2; exit 2;
    }
    command -v install >/dev/null 2>&1 || { echo 'install utility unavailable' >&2; exit 2; }
    umask 077
    install -o root -g root -m 0644 "$unit" "$unit_target"
    if ! install -o root -g root -m 0755 "$dispatcher" "$dispatcher_target"; then
        rm -f -- "$unit_target"
        echo 'Dispatcher registration failed; new unit removed' >&2; exit 2
    fi
    systemctl daemon-reload
    echo 'Candidate service/dispatcher registered but NOT enabled/started.'
else
    [ -f "$unit_target" ] && [ -f "$dispatcher_target" ] || {
        echo 'Candidate files missing; refusing partial removal' >&2; exit 2;
    }
    cmp -s "$unit" "$unit_target" && cmp -s "$dispatcher" "$dispatcher_target" || {
        echo 'Registered candidate files modified; removal refused' >&2; exit 2;
    }
    if systemctl is-active --quiet onyxcore-v090-receiver.service || \
       systemctl is-enabled --quiet onyxcore-v090-receiver.service; then
        echo 'Candidate active/enabled; separately approve stop/disable before removal' >&2; exit 2
    fi
    rm -f -- "$unit_target" "$dispatcher_target"
    systemctl daemon-reload
    echo 'Removed only inactive, exact candidate registration; retained code, config and data.'
fi
