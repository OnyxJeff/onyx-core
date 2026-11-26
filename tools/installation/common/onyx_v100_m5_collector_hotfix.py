#!/usr/bin/env python3
"""Derive the Windows S5 candidate from the accepted immutable S2B archive.
No installation, activation, credential or state operations. Historical ZIP stays valid.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import zipfile

BASE_SHA = '059d08c6e5b53141fc5faa4a43e7d4ab03ed6cd849c81eb91ed388688cf51a7c'
LAUNCHER_SHA = '41abca13545a04938d03bdad08d90496841c28a1221bc1fa18384f7cae7a4149'
MANIFEST = 'm5-candidate-manifest.json'
COLLECTOR = 'windows/collector/Send-OnyxTelemetry-v100.ps1'
LAUNCHER = 'windows/collector/Launch-OnyxTelemetry.vbs'
SOURCE_LAUNCHER = 'windows/collector/v100/Launch-OnyxTelemetry.vbs'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_regular(path, limit):
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Absolute path required')
    for p in (*reversed(path.parents), path):
        s = p.lstat()
        if stat.S_ISLNK(s.st_mode) or getattr(s, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Redirected input refused')
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_size > limit:
        raise ValueError('Unsafe input')
    with path.open('rb') as f:
        raw = f.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Oversized input')
    return raw


def once(raw, old, new):
    if raw.count(old) != 1 or new in raw:
        raise ValueError('Reviewed source transformation differs')
    return raw.replace(old, new, 1)


def candidate(base, launcher):
    if sha(base) != BASE_SHA:
        raise ValueError('Accepted Windows archive differs')
    launcher = launcher.replace(b'\r\n', b'\n')
    if sha(launcher) != LAUNCHER_SHA:
        raise ValueError('Launcher source differs')
    with zipfile.ZipFile(io.BytesIO(base)) as z:
        files = {name: z.read(name) for name in z.namelist()}
    manifest = json.loads(files.pop(MANIFEST))
    if len(files) != 24 or manifest['role'] != 'windows' or LAUNCHER in files:
        raise ValueError('Accepted inventory differs')
    original = files[COLLECTOR]
    patched = once(original, b'    [switch]$DryRun\n',
                   b'    [switch]$RequireLauncher,\n    [switch]$DryRun\n')
    patched = once(patched, b'        $mutex = New-Object System.Threading.Mutex',
                   b"        if ($RequireLauncher -and $null -eq $launcherPid) { throw 'Expected supervised launcher missing.' }\n        $mutex = New-Object System.Threading.Mutex")
    files[COLLECTOR] = patched
    files[LAUNCHER] = launcher
    manifest['kind'] = 'onyxcore-v100-m5-s5-inactive-runtime-candidate'
    manifest['base_archive_sha256'] = BASE_SHA
    manifest['hotfix_inputs'] = [{'path': SOURCE_LAUNCHER, 'sha256': LAUNCHER_SHA}]
    manifest['collector_supervision_required_by_launcher'] = True
    manifest['files'] = [{'path': p, 'sha256': sha(b), 'size': len(b)} for p,b in sorted(files.items())]
    files[MANIFEST] = (json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', allowZip64=False) as z:
        for name, raw in sorted(files.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED
            z.writestr(info, raw)
    return out.getvalue()


def build(base, launcher, target):
    raw = candidate(base, launcher)
    # Never overwrite. Caller supplies a fresh, private build directory.
    with target.open('xb') as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    if target.read_bytes() != raw:
        raise ValueError('Written artifact differs')
    return sha(raw)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=('plan', 'build', 'verify'))
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--launcher', type=Path, required=True)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    try:
        base = read_regular(args.base, 8*1024*1024)
        launcher = read_regular(args.launcher, 65536)
        raw = candidate(base, launcher)
        if args.operation == 'build':
            if args.output is None: raise ValueError('Output required')
            # Require an existing, non-redirected absolute output parent.
            if not args.output.is_absolute() or '..' in args.output.parts: raise ValueError('Absolute output required')
            for node in (*reversed(args.output.parent.parents), args.output.parent):
                s = node.lstat()
                if not stat.S_ISDIR(s.st_mode) or getattr(s, 'st_file_attributes', 0) & 0x400: raise ValueError('Unsafe output parent')
            build(base, launcher, args.output)
        elif args.operation == 'verify':
            if args.output is None or read_regular(args.output, 8*1024*1024) != raw: raise ValueError('Output differs')
        elif args.output is not None: raise ValueError('Plan does not write')
        print(json.dumps({'operation': args.operation, 'archive_sha256': sha(raw), 'payload_files':25, 'base_archive_sha256': BASE_SHA, 'installation_performed':False, 'activation_performed':False}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print('STOP: '+str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
