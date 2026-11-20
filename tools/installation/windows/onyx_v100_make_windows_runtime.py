#!/usr/bin/env python3
"""Create separate ONYX CORE v1 Windows runtimes from SHA-pinned v0.9 sources.

Offline only. Never overwrites existing files. Normalizes consistent Git checkout
line endings and refuses unreviewed source, mixed endings, or redirects.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sys


class GenerationRefused(ValueError):
    pass


SOURCES = {
    'collector': ('Send-OnyxTelemetry.ps1', 'Send-OnyxTelemetry-v100.ps1',
                  '74abf45a9a275a311477c164e3e9dee583a181b4'),
    'gateway': ('OnyxGateway.py', 'OnyxGateway_v100.py',
                '4e9d3fb40d50eaa558ed2b1476c75db03179dcfd'),
}


def canonical_bytes(raw: bytes) -> bytes:
    # BOM is retained, as required for PowerShell 5.1 Unicode source.
    try:
        raw.decode('utf-8-sig')
    except UnicodeError as exc:
        raise GenerationRefused('Legacy source encoding invalid') from exc
    if b'\r\n' in raw:
        clean = raw.replace(b'\r\n', b'')
        if b'\n' in clean or b'\r' in clean:
            raise GenerationRefused('Mixed source line endings refused')
        return raw.replace(b'\r\n', b'\n')
    if b'\r' in raw:
        raise GenerationRefused('Bare CR source line endings refused')
    return raw


def blob_sha(content: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(content)).encode('ascii') + b'\x00' + content).hexdigest()


def _one(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise GenerationRefused('Reviewed ' + label + ' signature changed; manual review required')
    return source.replace(old, new, 1)


def transform_collector(src: str) -> str:
    src = _one(src,
        "    [string]$Receiver = 'svr-onyxcore.local',",
        """    [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$Receiver,
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')][string]$Source,
    [ValidateRange(1024,65535)][int]$ReceiverPort = 8765,
    [switch]$EnableCpuTemperature,
    [string]$CpuSensorEndpoint = '',
    [string]$CpuSensorPath = '',""",
        'collector receiver parameters')
    src = _one(src, "    [string]$AdapterName = 'Ethernet',",
                    "    [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$AdapterName,",
                    'collector adapter parameter')
    src = _one(src,
        '$endpoint = "http://${Receiver}:8765/api/v1/telemetry"',
        '$endpoint = "http://${Receiver}:${ReceiverPort}/api/v1/telemetry"',
        'collector receiver port')
    src = _one(src,
        "if ($current -eq '/Sensor/SQUALL/AMD Ryzen 7 5800X/Temperatures/Core (Tctl/Tdie)') {",
        'if ($current -eq $CpuSensorPath) {',
        'collector CPU sensor path')
    src = _one(src,
        "$tree = Invoke-RestMethod -Uri 'http://192.168.137.1:8085/data.json' -TimeoutSec 2 -ErrorAction Stop",
        '$tree = Invoke-RestMethod -Uri $CpuSensorEndpoint -TimeoutSec 2 -ErrorAction Stop',
        'collector CPU sensor endpoint')
    src = _one(src, "                source = 'SQUALL'",
                    '                source = $Source', 'collector telemetry source')
    src = _one(src,
        '            if (-not $DryRun) { Add-CpuTemperatureMetrics -Metrics $metrics }',
        '            if (-not $DryRun -and $EnableCpuTemperature) { Add-CpuTemperatureMetrics -Metrics $metrics }',
        'collector temperature opt-in')
    old = "if ($DryRun -and $Count -eq 0) { throw 'DryRun requires a finite -Count.' }"
    new = old + "\n" + '''if ($EnableCpuTemperature -and
    ([string]::IsNullOrWhiteSpace($CpuSensorEndpoint) -or
     [string]::IsNullOrWhiteSpace($CpuSensorPath))) {
    throw 'Enabled CPU sensor requires validated endpoint and path.'
}
if (-not $EnableCpuTemperature -and
    ($CpuSensorEndpoint -ne '' -or $CpuSensorPath -ne '')) {
    throw 'Disabled CPU sensor must not specify endpoint or path.'
}'''
    src = _one(src, old, new, 'collector sensor preflight')
    if 'svr-onyxcore.local' in src or '/Sensor/SQUALL/' in src or '192.168.137.1:8085' in src:
        raise GenerationRefused('Legacy collector identity remains in transformed source')
    return src


def transform_gateway(src: str) -> str:
    src = _one(src,
        "    p.add_argument('--receiver', default='svr-onyxcore.local')",
        """    p.add_argument('--receiver', required=True)
    p.add_argument('--receiver-port', type=int, required=True)""",
        'gateway receiver arguments')
    old = "    if not 1024 <= args.port <= 65535:\n        p.error('invalid port')"
    src = _one(src, old, old + "\n" + "    if not 1024 <= args.receiver_port <= 65535:\n        p.error('invalid receiver port')", 'gateway upstream port validation')
    src = _one(src,
        "    server.upstream = f'http://{args.receiver}:8765'",
        "    server.upstream = f'http://{args.receiver}:{args.receiver_port}'",
        'gateway upstream address')
    if "default='svr-onyxcore.local'" in src or "{args.receiver}:8765" in src:
        raise GenerationRefused('Legacy gateway identity remains in transformed source')
    compile(src, 'OnyxGateway_v100.py', 'exec')
    return src


def _no_redirect(path: Path):
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise GenerationRefused('Redirected source or destination refused')


def build(kind: str, source: Path, output: Path) -> str:
    if kind not in SOURCES:
        raise GenerationRefused('Unsupported runtime kind')
    src_name, out_name, expected_blob = SOURCES[kind]
    source = Path(source)
    output = Path(output)
    if (not source.is_file() or source.name != src_name or
            output.name != out_name or source.parent != output.parent or
            output.exists() or output.is_symlink()):
        raise GenerationRefused('Only adjacent, absent versioned runtime outputs are allowed')
    _no_redirect(source)
    _no_redirect(output)
    raw = canonical_bytes(source.read_bytes())
    if blob_sha(raw) != expected_blob:
        raise GenerationRefused('Frozen Git source fingerprint mismatch')
    text = raw.decode('utf-8-sig')
    result = transform_collector(text) if kind == 'collector' else transform_gateway(text)
    content = result.encode('utf-8-sig') if kind == 'collector' else result.encode('utf-8')
    try:
        with output.open('xb') as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise GenerationRefused('Versioned runtime already exists') from exc
    if output.read_bytes() != content:
        raise GenerationRefused('Generated runtime readback mismatch')
    return hashlib.sha256(content).hexdigest()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--component', choices=sorted(SOURCES), required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(argv)
    try:
        digest = build(args.component, args.source, args.output)
    except (OSError, GenerationRefused, UnicodeError, SyntaxError) as exc:
        print('STOP: '+str(exc), file=sys.stderr)
        return 2
    print(args.component.upper() + '_V100_SHA256=' + digest)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
