#!/usr/bin/env python3
"""ONYX CORE v1.0.0 M2-S1: reproducible, INERT core runtime bundle.

No network, installation, extraction, secrets, tasks, service changes or activation.
Requires the reviewed local M1 commit; emits canonical, uncompressed ZIP bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

VERSION = '1.0.0'
SOURCE_COMMIT = '8df66f772d5b15464290b7040621e9b03635d49e'
SOURCE_BRANCH = 'feature/v1.0.0-stable-installation'
MANIFEST_NAME = 'bundle-manifest.json'
KIND = 'onyxcore-v100-core-runtime-candidate'
DOS_DATE = (1980, 1, 1, 0, 0, 0)
MAX_FILE_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024

# Explicit, reviewed runtime allowlist. Additions require source review.
# M2-S1 is a *core runtime candidate*, not an installable complete release.
FILES_BY_ROLE = {
    'common': (
        'docs/v1.0.0/examples/pi-armv6.config.example.json',
        'docs/v1.0.0/examples/windows.config.example.json',
        'tools/installation/common/onyx_v100_config.py',
    ),
    'pi-armv6': (
        'pi/services/receiver/receiver_v100.py',
        'pi/services/receiver/integrated_store_v100.py',
        'pi/services/receiver/history.py',
        'pi/services/receiver/health.py',
        'pi/services/receiver/dashboard.html',
        'tools/installation/pi/onyx_v100_pi_launch.py',
        'tools/installation/pi/onyx_v100_usb_binding.py',
        'tools/installation/pi/onyx_v100_pi_readiness.py',
    ),
    'windows': (
        'windows/collector/Send-OnyxTelemetry-v100.ps1',
        'windows/gateway/OnyxGateway_v100.py',
        'windows/gateway/Get-OnyxGatewayToken.ps1',
        'windows/gateway/gateway-dashboard.html',
        'windows/gateway/overlay.html',
        'windows/gateway/overlay-portrait.html',
        'tools/installation/windows/Invoke-OnyxV100WindowsRuntime.ps1',
        'tools/installation/windows/Invoke-OnyxV100Readiness.ps1',
        'tools/installation/windows/OnyxV100ReadinessCore.ps1',
    ),
}

ALL_FILES = tuple(sorted(path for paths in FILES_BY_ROLE.values() for path in paths))
assert len(ALL_FILES) == len(set(ALL_FILES))
assert all('/' in p and not p.startswith('/') and '..' not in p.split('/') for p in ALL_FILES)
HEX = re.compile(r'[0-9a-f]{64}\Z')


class BundleRefused(ValueError):
    pass


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(root: Path, *args: str) -> bytes:
    command = ['git', '-C', str(root), *args]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=25, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BundleRefused('Local Git command unavailable or timed out') from exc
    if result.returncode:
        # Do not echo local paths, Git stderr, credentials or environment.
        raise BundleRefused('Git source verification failed')
    return result.stdout


def check_source_root(root: Path) -> Path:
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise BundleRefused('Absolute, existing, non-redirected Git root required')
    resolved = root.resolve(strict=True)
    top = Path(os.fsdecode(git(root, 'rev-parse', '--show-toplevel')).strip()).resolve()
    if resolved != top:
        raise BundleRefused('Source path is not the Git worktree root')
    branch = git(root, 'branch', '--show-current').decode('ascii').strip()
    commit = git(root, 'rev-parse', 'HEAD').decode('ascii').strip()
    if branch != SOURCE_BRANCH or commit != SOURCE_COMMIT:
        raise BundleRefused('Unexpected local source branch or reviewed M1 commit')
    # Development tooling may be untracked; tracked edits and staged changes are not allowed.
    if git(root, 'diff', '--name-only', 'HEAD', '--'):
        raise BundleRefused('Tracked source modifications detected')
    if git(root, 'diff', '--cached', '--name-only', '--'):
        raise BundleRefused('Staged source modifications detected')
    return resolved


def committed_payload(root: Path, verify_head: bool = True) -> dict[str, bytes]:
    if verify_head:
        check_source_root(root)
    data = {}
    total = 0
    for name in ALL_FILES:
        tree = git(root, 'ls-tree', SOURCE_COMMIT, '--', name)
        expected = ('100644 blob ', '\t' + name + '\n')
        try:
            raw = tree.decode('ascii')
        except UnicodeDecodeError as exc:
            raise BundleRefused('Non-regular Git source entry refused') from exc
        if (not raw.startswith(expected[0]) or not raw.endswith(expected[1])
                or len(raw.splitlines()) != 1):
            raise BundleRefused('Required regular source file missing: ' + name)
        sha = raw.split(' ', 2)[2].split('\t', 1)[0]
        if not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise BundleRefused('Invalid reviewed Git blob ID')
        content = git(root, 'show', SOURCE_COMMIT + ':' + name)
        if len(content) > MAX_FILE_BYTES:
            raise BundleRefused('Source file exceeds size limit: ' + name)
        total += len(content)
        if total > MAX_TOTAL_BYTES:
            raise BundleRefused('Source bundle exceeds size limit')
        data[name] = content
    return data


def manifest_for(data: dict[str, bytes]) -> dict:
    if set(data) != set(ALL_FILES):
        raise BundleRefused('Source inventory differs from the pinned allowlist')
    rows = [{'path': path, 'sha256': digest(data[path]), 'size': len(data[path]),
             'mode': '0644'} for path in ALL_FILES]
    return {'schema_version': 1, 'package_kind': KIND,
            'release_version': VERSION, 'source_commit': SOURCE_COMMIT,
            'source_branch': SOURCE_BRANCH, 'activation_performed': False,
            'credential_files_included': False,
            'installable_without_further_steps': False,
            'roles': {name: list(paths) for name, paths in sorted(FILES_BY_ROLE.items())},
            'file_count': len(rows), 'files': rows}


def zip_entry(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=DOS_DATE)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (0o100644 << 16)
    info.flag_bits = 0
    return info


def write_archive(target: Path, files: dict[str, bytes]) -> dict:
    manifest = manifest_for(files)
    if not target.is_absolute() or '..' in target.parts or target.name in ('', '.', '..'):
        raise BundleRefused('Absolute output path without traversal required')
    if target.exists() or target.is_symlink():
        raise BundleRefused('Output already exists; overwrite refused')
    parent = target.parent
    if not parent.is_dir():
        raise BundleRefused('Output parent directory does not exist')
    node = parent
    while True:
        if node.is_symlink() or (hasattr(node, 'is_junction') and node.is_junction()):
            raise BundleRefused('Redirected output path refused')
        if node.parent == node:
            break
        node = node.parent
    manifest_bytes = canonical(manifest)
    fd, temporary = tempfile.mkstemp(prefix='.onyx-v100-m2s1-', suffix='.tmp', dir=parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            with zipfile.ZipFile(stream, 'w', allowZip64=False) as zf:
                for path in ALL_FILES:
                    zf.writestr(zip_entry(path), files[path])
                zf.writestr(zip_entry(MANIFEST_NAME), manifest_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        # Verify the completely written candidate before publishing it.
        verification = verify_archive(Path(temporary))
        # Atomic, exclusive create; never replace an existing user artifact.
        os.link(temporary, target)
        return {**verification, 'archive_sha256': hash_file(target),
                'archive_path': str(target)}
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def verify_archive(path: Path, *, source_root: Path | None = None) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_TOTAL_BYTES + 131072:
        raise BundleRefused('Expected bounded, regular ZIP archive')
    try:
        with zipfile.ZipFile(path, 'r', allowZip64=False) as zf:
            infos = zf.infolist()
            names = [i.filename for i in infos]
            if (names != list(ALL_FILES) + [MANIFEST_NAME] or
                    len(set(names)) != len(names) or zf.comment):
                raise BundleRefused('ZIP inventory/order/comment mismatch')
            for info in infos:
                if (info.date_time != DOS_DATE or info.compress_type != zipfile.ZIP_STORED
                        or info.create_system != 3 or info.external_attr != (0o100644 << 16)
                        or info.extra or info.comment or info.file_size > MAX_FILE_BYTES):
                    raise BundleRefused('Unexpected ZIP member metadata')
            manifest_bytes = zf.read(MANIFEST_NAME)
            if len(manifest_bytes) > 32768:
                raise BundleRefused('Manifest too large')
            manifest = json.loads(manifest_bytes.decode('ascii'))
            files = {name: zf.read(name) for name in ALL_FILES}
            expected_manifest = manifest_for(files)
            if manifest != expected_manifest or manifest_bytes != canonical(expected_manifest):
                raise BundleRefused('Manifest content or canonical encoding mismatch')
    except (OSError, UnicodeError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile,
            zipfile.LargeZipFile) as exc:
        if isinstance(exc, BundleRefused):
            raise
        raise BundleRefused('Archive inspection failed') from exc
    if source_root is not None:
        committed = committed_payload(source_root)
        if files != committed:
            raise BundleRefused('Archived payload disagrees with the pinned local Git commit')
    return {'verified': True, 'package_kind': KIND,
            'source_commit': SOURCE_COMMIT, 'file_count': len(files),
            'payload_sha256': digest(canonical(expected_manifest)),
            'git_source_verified': source_root is not None,
            'installation_accepted': False, 'activation_performed': False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    preview = sub.add_parser('plan', help='Read-only local Git inventory')
    preview.add_argument('--repo', required=True, type=Path)
    build = sub.add_parser('build', help='Create a candidate archive; never overwrite')
    build.add_argument('--repo', required=True, type=Path)
    build.add_argument('--output', required=True, type=Path)
    build.add_argument('--approve-build', action='store_true')
    verify = sub.add_parser('verify', help='Read-only archive verification')
    verify.add_argument('--archive', required=True, type=Path)
    verify.add_argument('--repo', type=Path, help='Also compare payload with pinned local Git source')
    args = parser.parse_args(argv)
    try:
        if args.operation == 'verify':
            result = verify_archive(args.archive, source_root=args.repo)
            result['archive_sha256'] = hash_file(args.archive)
        else:
            content = committed_payload(args.repo)
            manifest = manifest_for(content)
            if args.operation == 'plan':
                result = {'operation': 'READ_ONLY_BUNDLE_PLAN',
                          'file_count': len(content), 'payload_bytes': sum(map(len, content.values())),
                          'manifest_sha256': digest(canonical(manifest)),
                          'source_commit': SOURCE_COMMIT, 'activation_performed': False,
                          'installation_accepted': False}
            else:
                if not args.approve_build:
                    raise BundleRefused('Explicit --approve-build is required to write a candidate ZIP')
                if args.output.resolve(strict=False).is_relative_to(args.repo.resolve(strict=True)):
                    raise BundleRefused('Output must be outside the source repository')
                result = {'operation': 'BUNDLE_BUILT', **write_archive(args.output, content)}
        print(canonical(result).decode('ascii'), end='')
        return 0
    except (BundleRefused, OSError, ValueError, UnicodeError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
