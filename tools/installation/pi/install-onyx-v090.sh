#!/bin/sh
# ONYX CORE v0.9.0: code-only, inactive release preparation (no service activation).
# Preview unless --apply. Never overwrites /opt/onyxcore's existing code.
set -eu
usage() { echo "Usage: $0 --archive ZIP --commit FULL_SHA --sha256 SHA256 [--version 0.9.0] [--system] [--apply] [--approve-inactive-system-preparation]" >&2; exit 2; }
archive='' commit='' sha='' version='0.9.0' mode='sandbox' apply='no' approval='no'
while [ "$#" -gt 0 ]; do
    case "$1" in
        --archive) [ "$#" -ge 2 ] || usage; archive=$2; shift 2 ;;
        --commit) [ "$#" -ge 2 ] || usage; commit=$2; shift 2 ;;
        --sha256) [ "$#" -ge 2 ] || usage; sha=$2; shift 2 ;;
        --version) [ "$#" -ge 2 ] || usage; version=$2; shift 2 ;;
        --system) mode='system'; shift ;;
        --apply) apply='yes'; shift ;;
        --approve-inactive-system-preparation) approval='yes'; shift ;;
        *) usage ;;
    esac
done
[ -n "$archive" ] && [ -n "$commit" ] && [ -n "$sha" ] || usage
command -v python3 >/dev/null 2>&1 || { echo 'Python3 unavailable' >&2; exit 2; }
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
installer="$script_dir/../common/onyx_install.py"
[ -f "$installer" ] || { echo 'Installer code missing' >&2; exit 2; }
if [ "$mode" = 'system' ]; then
    [ "$(uname -m)" = 'armv6l' ] || { echo 'System Pi install requires native ARMv6 host' >&2; exit 2; }
    target='/opt/onyxcore/v0.9.0'
    if [ "$apply" = 'yes' ]; then
        [ "$approval" = 'yes' ] || { echo 'System installation approval missing' >&2; exit 2; }
        [ "$(id -u)" -eq 0 ] || { echo 'Root required for system release preparation' >&2; exit 2; }
    fi
    set -- --system
    [ "$approval" = 'yes' ] && set -- "$@" --approve-inactive-system-preparation
else
    [ "$approval" = 'no' ] || { echo 'System approval cannot be used for sandbox' >&2; exit 2; }
    target="${TMPDIR:-/tmp}/OnyxV090-$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
    set --
fi
[ "$apply" = 'yes' ] && set -- "$@" --apply
exec python3 -I -B "$installer" --archive "$archive" --target "$target" --platform pi-armv6 \
    --expected-commit "$commit" --expected-version "$version" --expected-sha256 "$sha" "$@"
