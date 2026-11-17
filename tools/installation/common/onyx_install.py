#!/usr/bin/env python3
"""ONYX CORE v0.9.0: offline, atomic, INACTIVE code installation.

No task/service changes, credentials, database migration, network access or activation.
System target installation requires an explicit platform-native privileged session
and two approval flags; default mode makes no filesystem changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform as host_platform
from pathlib import Path
import re
import shutil
import sys
import tempfile
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I drops script directory from sys.path
from onyx_stage import inspect  # package validator, from the adjacent common directory

RELEASE = re.compile(r'0\.9\.0(?:[-.][A-Za-z0-9.-]+)?\Z')
SYSTEM_TARGETS = {
    'windows': r'C:\Program Files\OnyxCore\v0.9.0',
    'pi-armv6': '/opt/onyxcore/v0.9.0',
}


class InstallRefused(ValueError):
    pass


def _is_admin(platform: str) -> bool:
    if platform == 'windows':
        if os.name != 'nt':
            return False
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() == 1
        except (AttributeError, OSError):
            return False
    return os.name == 'posix' and os.geteuid() == 0


def _no_redirects(path: Path) -> None:
    """Check every existing ancestor; refusal is conservative, not a native ACL attestation."""
    node = path
    while True:
        if node.exists() or node.is_symlink():
            if node.is_symlink() or (hasattr(node, 'is_junction') and node.is_junction()):
                raise InstallRefused('redirected path component forbidden')
            if node == path and not node.is_dir():
                raise InstallRefused('target is not a directory')
        if node.parent == node:
            break
        node = node.parent


def check_target(target: Path, *, platform: str, system: bool,
                 admin_check=_is_admin) -> None:
    if not target.is_absolute() or '..' in target.parts:
        raise InstallRefused('absolute target without traversals required')
    _no_redirects(target)
    if target.exists() or target.is_symlink():
        raise InstallRefused('version target already exists; refusing overwrite')
    if system:
        # Never allow a custom system path via caller-supplied switches.
        if platform == 'windows':
            if os.name != 'nt' or os.path.normcase(str(target)) != os.path.normcase(SYSTEM_TARGETS[platform]):
                raise InstallRefused('not the exact Windows release path')
        elif platform == 'pi-armv6':
            if (os.name != 'posix' or host_platform.machine().lower() != 'armv6l'
                    or str(target) != SYSTEM_TARGETS[platform]):
                raise InstallRefused('not the exact Pi release path')
        else:
            raise InstallRefused('unknown system platform')
        if not admin_check(platform):
            raise InstallRefused('elevated local administrator/root required for system preparation')
        if not target.parent.is_dir():
            raise InstallRefused('system root absent; prepare root separately with approval')
    else:
        tmp = Path(tempfile.gettempdir()).resolve(strict=True)
        try:
            parent = target.parent.resolve(strict=True)
        except OSError as exc:
            raise InstallRefused('sandbox parent unavailable') from exc
        if parent != tmp or not re.fullmatch(r'OnyxV090-[A-Za-z0-9_-]{1,50}', target.name):
            raise InstallRefused('sandbox target must be new OnyxV090-* directly under OS temp')


def _json(data: dict) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def prepare(archive: Path, target: Path, *, platform: str, commit: str,
            version: str, digest: str, system: bool = False, apply: bool = False,
            admin_check=_is_admin) -> dict:
    if not RELEASE.fullmatch(version):
        raise InstallRefused('only v0.9.0 prerelease/final code can be prepared')
    # Caller-supplied independent hash and commit, verified before creating anything.
    manifest = inspect(archive, platform=platform, expected_commit=commit,
                       expected_version=version, expected_sha256=digest)
    check_target(target, platform=platform, system=system, admin_check=admin_check)
    result = {'status': 'PREVIEW' if not apply else 'PREPARED',
              'platform': platform, 'version': version, 'source_commit': commit,
              'archive_sha256': digest.lower(), 'target': str(target),
              'file_count': len(manifest['files']), 'activated': False}
    if not apply:
        return result
    if system and not target.parent.is_dir():
        raise InstallRefused('system parent missing')
    # Staging is created in the SAME filesystem as target for atomic rename.
    # Not a general upgrade: existing target is always refused.
    temporary = Path(tempfile.mkdtemp(prefix='.onyx-v090-inactive-', dir=str(target.parent)))
    try:
        with zipfile.ZipFile(archive, 'r') as zf:
            for row in manifest['files']:
                rel = row['path']
                output = temporary.joinpath(*rel.split('/'))
                output.parent.mkdir(parents=True, exist_ok=True)
                data = zf.read(rel)
                if len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['sha256']:
                    raise InstallRefused('archive changed during extraction')
                # exclusive create prevents accidental replacement inside staging.
                with output.open('xb') as stream:
                    stream.write(data)
                if platform == 'pi-armv6':
                    output.chmod(0o755 if output.suffix == '.sh' else 0o644)
        (temporary / 'manifest.json').write_bytes(_json(manifest))
        receipt = dict(result)
        receipt['mode'] = 'inactive-code-only'
        (temporary / 'installation-receipt.json').write_bytes(_json(receipt))
        if platform == 'pi-armv6':
            for directory in (p for p in temporary.rglob('*') if p.is_dir()):
                directory.chmod(0o755)
            (temporary / 'manifest.json').chmod(0o644)
            (temporary / 'installation-receipt.json').chmod(0o644)
            temporary.chmod(0o755)
        # Preserve original install bytes even when installers set execution mode.
        for row in manifest['files']:
            if _sha(temporary.joinpath(*row['path'].split('/'))) != row['sha256']:
                raise InstallRefused('staged file hash mismatch: ' + row['path'])
        if _sha(temporary / 'manifest.json') != hashlib.sha256(_json(manifest)).hexdigest():
            raise InstallRefused('staged manifest mismatch')
        check_target(target, platform=platform, system=system, admin_check=admin_check)
        temporary.rename(target)  # only into a NEW version directory
        temporary = None
        return result
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--platform', choices=('windows', 'pi-armv6'), required=True)
    parser.add_argument('--expected-commit', required=True)
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--system', action='store_true', help='require exact system path and privileged session')
    parser.add_argument('--apply', action='store_true', help='write an INACTIVE versioned code tree')
    parser.add_argument('--approve-inactive-system-preparation', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.system and args.apply and not args.approve_inactive_system_preparation:
            raise InstallRefused('separate explicit system installation approval flag required')
        if not args.system and args.approve_inactive_system_preparation:
            raise InstallRefused('system approval flag without --system is refused')
        result = prepare(args.archive, args.target, platform=args.platform,
                         commit=args.expected_commit, version=args.expected_version,
                         digest=args.expected_sha256, system=args.system, apply=args.apply)
        print(_json(result).decode('ascii').strip())
        if args.apply:
            print('INACTIVE ONLY: no services/tasks, credentials, databases, Pi network or live deployment changed.')
        return 0
    except (InstallRefused, ValueError, OSError, KeyError, zipfile.BadZipFile,
            json.JSONDecodeError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
