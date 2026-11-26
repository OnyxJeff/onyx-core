#!/usr/bin/env python3
"""Reproducible, fail-closed v1.0.0 dashboard source transform (no install)."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

EXPECTED_LEGACY_SHA256 = '72465bc34f5bfcd41f6e67f5ad0740cf692afd2a0580b98bdcb4daa06f03b42f'

REPLACEMENTS = (
    (
        "const monitorView=gatewayMode&&['18767','18768'].includes(location.port);",
        "const monitorView=gatewayMode;",
    ),
    (
        "  if(!response.ok)throw new Error('history_unavailable');",
        "  if(response.status===404){document.body.classList.remove('monitor-enabled');return;}\n  document.body.classList.add('monitor-enabled');\n  if(!response.ok)throw new Error('history_unavailable');",
    ),
    (
        " document.body.classList.add('monitor-enabled');\n pollMonitoring();",
        " // The endpoint decides whether the monitoring panel is available.\n pollMonitoring();",
    ),
    (
        "No stored connectivity check. Run M3 explicitly to start recording.",
        "No stored connectivity check. The monitoring view does not start probes.",
    ),
    (
        "<title>ONYX CORE | SQUALL telemetry — v0.5.0 Phase 3F</title>",
        "<title>ONYX CORE | USB telemetry — v1.0.0</title>",
    ),
    (
        "<small>SQUALL / USB TELEMETRY</small>",
        "<small>USB TELEMETRY</small>",
    ),
    (
        "const gatewayMode=['http://127.0.0.1:18766','http://127.0.0.1:18767','http://127.0.0.1:18768'].includes(location.origin);",
        "const gatewayMode=location.protocol==='http:'&&location.hostname==='127.0.0.1';",
    ),
)


class DashboardRefused(ValueError):
    pass


def normalize(raw: bytes) -> bytes:
    if b'\r\r\n' in raw or b'\r' in raw.replace(b'\r\n', b''):
        raise DashboardRefused('Mixed or malformed line endings refused')
    if b'\r\n' in raw and b'\n' in raw.replace(b'\r\n', b''):
        raise DashboardRefused('Mixed line endings refused')
    return raw.replace(b'\r\n', b'\n')


def transform(raw: bytes) -> bytes:
    src = normalize(raw)
    if hashlib.sha256(src).hexdigest() != EXPECTED_LEGACY_SHA256:
        raise DashboardRefused('Reviewed base dashboard fingerprint changed; STOP')
    try:
        text = src.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise DashboardRefused('Base dashboard is not UTF-8') from exc
    for old, new in REPLACEMENTS:
        if text.count(old) != 1 or new in text:
            raise DashboardRefused('Reviewed dashboard source contract changed; STOP')
        text = text.replace(old, new, 1)
    if 'SQUALL' in text:
        raise DashboardRefused('Unexpected legacy workstation branding remains')
    return text.encode('utf-8')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if not args.source.is_file() or args.source.is_symlink():
            raise DashboardRefused('Source must be an existing regular file')
        if args.output.exists() or args.output.is_symlink():
            raise DashboardRefused('Output exists: refusing overwrite')
        output = transform(args.source.read_bytes())
        if not args.output.parent.is_dir():
            raise DashboardRefused('Output parent must already exist')
        with args.output.open('xb') as fp:
            fp.write(output)
        print('VERSIONED_DASHBOARD_SHA256=' + hashlib.sha256(output).hexdigest())
        return 0
    except (OSError, DashboardRefused) as exc:
        parser.exit(2, 'STOP: ' + str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
