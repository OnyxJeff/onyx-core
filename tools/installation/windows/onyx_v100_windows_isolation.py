#!/usr/bin/env python3
"""M2-S4A: deterministic OFFLINE Windows runtime isolation assets.

Derives isolated collector, DPAPI helper and Windows runtime launcher from the
SHA256-approved M2-S1 runtime ZIP. Never installs, enrolls tokens, calls
PowerShell, contacts hosts, or changes a running service.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

BUNDLE_SHA256 = 'b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d'
COMMIT = '8df66f772d5b15464290b7040621e9b03635d49e'
MANIFEST_NAME = 'runtime-isolation-manifest.json'
SOURCES = {
    'windows/collector/Send-OnyxTelemetry-v100.ps1': 'b7f22dc7f6dee64083538fa91dd42333c7f3cb14b93a71c779223443aa558175',
    'windows/gateway/Get-OnyxGatewayToken.ps1': 'bcaf96cb7299907a9db31aee7fe5fc57fdfc8b80fd41948a052fd40eacd8b816',
    'tools/installation/windows/Invoke-OnyxV100WindowsRuntime.ps1': 'd0e92af0f93c0848b18331cbf44ce2c6592d0faf51773c2490b81563ef381e69',
}
GATEWAY_PATH = 'windows/gateway/OnyxGateway_v100.py'
GATEWAY_SHA256 = '5460225e677f868e247ae3e6c7315e5b5cee11acc4d4a1ea6378ca8c66a5ccce'
# Byte strings intentionally preserve the original Windows PowerShell UTF-8 BOM.
REPLACEMENTS = {
    'windows/collector/Send-OnyxTelemetry-v100.ps1': (
        (b"$logDir = Join-Path $env:LOCALAPPDATA 'OnyxCore'",
         b"$logDir = Join-Path $env:LOCALAPPDATA 'OnyxCore-v100'"),
        (b"'Local\\OnyxCoreCollector'", b"'Local\\OnyxCoreV100Collector'"),
    ),
    'windows/gateway/Get-OnyxGatewayToken.ps1': (
        (b"'OnyxCore\\collector-token.dpapi'", b"'OnyxCore-v100\\collector-token.dpapi'"),
    ),
    'tools/installation/windows/Invoke-OnyxV100WindowsRuntime.ps1': (
        (b"'OnyxCore\\collector-token.dpapi'", b"'OnyxCore-v100\\collector-token.dpapi'"),
    ),
}


class IsolationRefused(ValueError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical(obj) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


def expected(bundle: Path) -> tuple[dict[str, bytes], dict]:
    """Return exclusively approved source-derived bytes and static manifest."""
    if not bundle.is_file() or bundle.is_symlink() or bundle.stat().st_size > 2_000_000:
        raise IsolationRefused('reviewed regular bundle required')
    if sha_file(bundle) != BUNDLE_SHA256:
        raise IsolationRefused('M2-S1 core runtime SHA256 mismatch')
    output = {}
    with zipfile.ZipFile(bundle, 'r', allowZip64=False) as archive:
        names = archive.namelist()
        if len(names) != 21 or len(set(names)) != len(names) or 'bundle-manifest.json' not in names:
            raise IsolationRefused('approved bundle inventory missing')
        content = {}
        for relative, fingerprint in {**SOURCES, GATEWAY_PATH: GATEWAY_SHA256}.items():
            raw = archive.read(relative)
            if sha(raw) != fingerprint:
                raise IsolationRefused('reviewed source changed: ' + relative)
            content[relative] = raw
        # Gateway must load the helper from the same installed directory.
        if content[GATEWAY_PATH].count(b"with_name('Get-OnyxGatewayToken.ps1')") != 1:
            raise IsolationRefused('gateway DPAPI helper reference changed')
        for name, pairs in REPLACEMENTS.items():
            raw = content[name]
            for previous, replacement in pairs:
                if raw.count(previous) != 1 or replacement in raw:
                    raise IsolationRefused('runtime isolation replacement contract changed: ' + name)
                raw = raw.replace(previous, replacement, 1)
            if b'OnyxCore\\collector-token.dpapi' in raw or b'Local\\OnyxCoreCollector\'' in raw:
                raise IsolationRefused('legacy credential or mutex reference remains: ' + name)
            if name.endswith('.ps1') and b'\r\n' in raw:
                raise IsolationRefused('unexpected PowerShell line endings')
            output[name] = raw
    rows = [{'path': name, 'sha256': sha(output[name]), 'size': len(output[name])}
            for name in sorted(output)]
    manifest = {'schema_version': 1,
                'operation': 'WINDOWS_V100_ISOLATED_RUNTIME_DERIVATIVE',
                'source_commit': COMMIT, 'bundle_sha256': BUNDLE_SHA256,
                'files': rows, 'file_count': len(rows),
                'credential_path': '%LOCALAPPDATA%\\OnyxCore-v100\\collector-token.dpapi',
                'logging_directory': '%LOCALAPPDATA%\\OnyxCore-v100',
                'collector_mutex': 'Local\\OnyxCoreV100Collector',
                'credential_enrolled': False, 'activation_performed': False,
                'installation_performed': False, 'production_modified': False,
                'requires_install_integration': True}
    return output, manifest


def read_verified(directory: Path, expected_files: dict[str, bytes], manifest: dict) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise IsolationRefused('regular isolated staging directory required')
    exact = set(expected_files) | {MANIFEST_NAME}
    observed = set()
    for entry in directory.rglob('*'):
        if entry.is_symlink() or not (entry.is_file() or entry.is_dir()):
            raise IsolationRefused('redirected or unusual staging entry refused')
        if entry.is_file():
            observed.add(entry.relative_to(directory).as_posix())
    if observed != exact:
        raise IsolationRefused('derived file inventory differs from approved contract')
    for rel, raw in expected_files.items():
        node = directory.joinpath(*rel.split('/'))
        if node.read_bytes() != raw:
            raise IsolationRefused('derived runtime file differs: ' + rel)
    if (directory / MANIFEST_NAME).read_bytes() != canonical(manifest):
        raise IsolationRefused('derived manifest differs')


def build(bundle: Path, target: Path) -> dict:
    derived, manifest = expected(bundle)
    if not target.is_absolute() or '..' in target.parts or target.exists() or target.is_symlink():
        raise IsolationRefused('new absolute output directory required; overwrite refused')
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise IsolationRefused('ordinary existing output parent required')
    for ancestor in (target.parent, *target.parent.parents):
        if ancestor.is_symlink():
            raise IsolationRefused('redirected output parent refused')
    # Synthetic output only. The host installer never installs a runtime.
    staging = Path(tempfile.mkdtemp(prefix='.onyx-v100-isolation-', dir=target.parent))
    try:
        for relative, data in derived.items():
            dest = staging.joinpath(*relative.split('/'))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        (staging / MANIFEST_NAME).write_bytes(canonical(manifest))
        read_verified(staging, derived, manifest)
        if target.exists() or target.is_symlink():
            raise IsolationRefused('target created during staging; overwrite refused')
        # Windows os.rename directory fails when destination exists. Native
        # integration must use its own no-overwrite publication contract.
        if os.name == 'nt':
            staging.rename(target)
            staging = None
        else:
            # The output is a disposable artifact; still refuse an empty-dir race.
            if target.exists() or target.is_symlink():
                raise IsolationRefused('target appeared; stop')
            staging.rename(target)
            staging = None
        read_verified(target, derived, manifest)
        return {'operation': 'WINDOWS_V100_DERIVATIVE_BUILT', 'output': str(target),
                'file_count': len(derived), 'manifest_sha256': sha(canonical(manifest)),
                'activation_performed': False, 'credential_enrolled': False}
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--output', type=Path)
    group.add_argument('--verify-directory', type=Path)
    parser.add_argument('--approve-build', action='store_true')
    args = parser.parse_args(argv)
    try:
        derived, manifest = expected(args.bundle)
        if args.output is not None:
            if not args.approve_build:
                raise IsolationRefused('explicit --approve-build required for synthetic directory')
            result = build(args.bundle, args.output)
        elif args.verify_directory is not None:
            if args.approve_build:
                raise IsolationRefused('verification is read-only')
            read_verified(args.verify_directory, derived, manifest)
            result = {'operation': 'WINDOWS_V100_DERIVATIVE_VERIFIED',
                      'file_count': len(derived), 'manifest_sha256': sha(canonical(manifest)),
                      'activation_performed': False, 'credential_enrolled': False}
        else:
            if args.approve_build:
                raise IsolationRefused('build approval without output refused')
            result = {'operation': 'WINDOWS_V100_ISOLATION_PREVIEW',
                      'source_commit': COMMIT, 'bundle_sha256': BUNDLE_SHA256,
                      'file_count': len(derived),
                      'manifest_sha256': sha(canonical(manifest)),
                      'derived_files': sorted(derived),
                      'legacy_credential_references_removed': True,
                      'legacy_mutex_reference_removed': True,
                      'credential_enrolled': False, 'installation_performed': False,
                      'integration_completed': False, 'activation_performed': False}
        print(canonical(result).decode('ascii').strip())
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
