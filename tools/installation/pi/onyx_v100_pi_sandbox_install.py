#!/usr/bin/env python3
"""ONYX CORE v1.0.0 M2-S3A: Pi ARMv6 INACTIVE temp-only bundle installer.

No credentials, systemd, network changes, state migration, or receiver activation.
Only a fresh, direct child of OS temp can be created, and only on native
Linux ARMv6 with Python 3.13. Preview is cross-platform and read-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import sys
import tempfile
import types
import zipfile
import zipimport

SOURCE_COMMIT = '8df66f772d5b15464290b7040621e9b03635d49e'
BUNDLE_SHA256 = 'b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d'
MANIFEST_NAME = 'bundle-manifest.json'
CONFIG_PATH = 'config/pi-armv6.config.json'
RECEIPT_PATH = 'installation-receipt.json'
TARGET_NAME = re.compile(r'OnyxV100-Pi-[A-Za-z0-9_-]{1,48}\Z')
MAX_ARCHIVE_SIZE = 8_000_000


class InstallRefused(ValueError):
    """The candidate cannot be trusted or is outside the approved sandbox."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj: dict) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


def reject_redirects(path: Path) -> None:
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or (hasattr(ancestor, 'is_junction') and ancestor.is_junction()):
            raise InstallRefused('redirected file or path refused')


def read_regular(path: Path, limit: int) -> bytes:
    reject_redirects(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise InstallRefused('input file absent or exceeds safe size')
    return path.read_bytes()


def check_target(target: Path) -> None:
    reject_redirects(target)
    if not target.is_absolute() or '..' in target.parts or not TARGET_NAME.fullmatch(target.name):
        raise InstallRefused('only new OnyxV100-Pi-* direct child of OS temp allowed')
    parent = Path(tempfile.gettempdir()).resolve(strict=True)
    if target.parent.resolve(strict=True) != parent:
        raise InstallRefused('sandbox must be directly beneath OS temp')
    if target.exists() or target.is_symlink():
        raise InstallRefused('target already exists: never overwrite')


def _safe_zip_name(path: str) -> bool:
    return (isinstance(path, str) and len(path) <= 250 and path and not path.startswith('/')
            and not path.endswith('/') and '\\' not in path and ':' not in path
            and all(bit not in ('', '.', '..') for bit in path.split('/')))


def inspect_bundle(bundle_path: Path):
    data = read_regular(bundle_path, MAX_ARCHIVE_SIZE)
    if _sha(data) != BUNDLE_SHA256:
        raise InstallRefused('core bundle does not match approved M2-S1 SHA256')
    try:
        with zipfile.ZipFile(bundle_path, 'r') as zf:
            infos = zf.infolist()
            names = [info.filename for info in infos]
            if (len(names) != 21 or len(set(names)) != 21 or
                    names.count(MANIFEST_NAME) != 1 or any(not _safe_zip_name(n) for n in names)):
                raise InstallRefused('ZIP inventory or paths invalid')
            if zf.testzip() is not None:
                raise InstallRefused('ZIP CRC failure')
            raw_manifest = zf.read(MANIFEST_NAME)
            manifest = json.loads(raw_manifest)
            if (manifest.get('schema_version') != 1 or manifest.get('source_commit') != SOURCE_COMMIT or
                    manifest.get('release_version') != '1.0.0' or
                    manifest.get('package_kind') != 'onyxcore-v100-core-runtime-candidate' or
                    manifest.get('file_count') != 20 or manifest.get('activation_performed') is not False or
                    manifest.get('credential_files_included') is not False):
                raise InstallRefused('bundle identity does not match approved M1 source')
            roles = manifest.get('roles')
            rows = manifest.get('files')
            if not isinstance(roles, dict) or set(roles) != {'common', 'windows', 'pi-armv6'}:
                raise InstallRefused('invalid bundle roles')
            if not isinstance(rows, list) or len(rows) != 20 or any(type(row) is not dict for row in rows):
                raise InstallRefused('invalid file manifest')
            selected = roles['common'] + roles['pi-armv6']
            if (not all(type(v) is list and all(type(x) is str for x in v) for v in roles.values()) or
                    len(selected) != 11 or len(set(selected)) != 11 or
                    len(roles['windows']) != 9 or
                    len(set(sum(roles.values(), []))) != 20):
                raise InstallRefused('invalid Pi/common role selection')
            declared = [row.get('path') for row in rows]
            if (len(set(declared)) != 20 or set(names) != set(declared) | {MANIFEST_NAME} or
                    set(sum(roles.values(), [])) != set(declared) or
                    any(not _safe_zip_name(n) for n in declared)):
                raise InstallRefused('manifest paths do not match ZIP members')
            result = {}
            for row in rows:
                name = row['path']
                info = zf.getinfo(name)
                if (info.date_time != (1980, 1, 1, 0, 0, 0) or info.extra or info.comment or
                        info.create_system != 3 or stat.S_IFMT(info.external_attr >> 16) != stat.S_IFREG or
                        row.get('mode') != '0644'):
                    raise InstallRefused('non-deterministic or unsafe ZIP member')
                content = zf.read(name)
                if (len(content) != row.get('size') or _sha(content) != row.get('sha256') or
                        len(content) > 500_000):
                    raise InstallRefused('bundle member differs from manifest')
                if name in selected:
                    result[name] = content
            if len(result) != 11:
                raise InstallRefused('missing Pi files')
            return result, raw_manifest
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, KeyError, TypeError, UnicodeError) as exc:
        raise InstallRefused('approved core bundle cannot be verified') from exc


def validated_config(bundle: Path, *, interface: str, ipv4_subnet: str, source: str,
                     port: int, state_dir: str, history_name: str, snapshot_name: str) -> dict:
    cfg = {'schema_version': 1, 'platform': 'pi-armv6',
           'receiver': {'interface': interface, 'port': port,
                        'ipv4_subnet': ipv4_subnet, 'source': source},
           'storage': {'state_dir': state_dir, 'history_name': history_name,
                       'snapshot_name': snapshot_name}}
    try:
        importer = zipimport.zipimporter(str(bundle) + '/tools/installation/common')
        code = importer.get_code('onyx_v100_config')
        if code is None:
            raise InstallRefused('configuration validator absent')
        module = types.ModuleType('onyx_v100_config')
        exec(code, module.__dict__)
        module.validate_config(cfg, 'pi-armv6')
    except (ImportError, ValueError, TypeError, OSError, zipimport.ZipImportError) as exc:
        raise InstallRefused('Pi configuration rejected') from exc
    return cfg


def prepare(bundle: Path, target: Path, settings: dict):
    check_target(target)
    selected, manifest = inspect_bundle(bundle)
    cfg = validated_config(bundle, **settings)
    plan = {'schema_version': 1, 'operation': 'PI_INACTIVE_SANDBOX_PREVIEW',
            'release_version': '1.0.0', 'source_commit': SOURCE_COMMIT,
            'bundle_sha256': BUNDLE_SHA256, 'target': str(target),
            'selected_runtime_files': len(selected), 'receiver_source': cfg['receiver']['source'],
            'receiver_port': cfg['receiver']['port'],
            'state_dir_untouched': True, 'usb_configuration_untouched': True,
            'credentials_accessed': False, 'systemd_changes': False,
            'network_changes': False, 'activation_performed': False,
            'installation_performed': False, 'native_armv6_verified': False}
    return plan, selected, manifest, cfg


def _native_pi() -> bool:
    return (sys.platform == 'linux' and platform.machine().lower() == 'armv6l' and
            sys.version_info[:2] == (3, 13) and os.name == 'posix')


def create_inactive(target: Path, selected: dict, manifest: bytes, cfg: dict, *, native_check=None):
    if not (_native_pi() if native_check is None else native_check()):
        raise InstallRefused('inactive Pi installation requires native ARMv6 Linux, Python 3.13')
    check_target(target)
    parent = Path(tempfile.gettempdir()).resolve(strict=True)
    staging = Path(tempfile.mkdtemp(prefix='.OnyxV100-Pi-staging-', dir=str(parent)))
    try:
        files = dict(selected)
        files[MANIFEST_NAME] = manifest
        files[CONFIG_PATH] = canonical_json(cfg)
        rows = []
        for name, contents in sorted(files.items()):
            if not _safe_zip_name(name):
                raise InstallRefused('unsafe installed path')
            output = staging.joinpath(*name.split('/'))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(contents)
            output.chmod(0o600 if name == CONFIG_PATH else 0o644)
            rows.append({'path': name, 'sha256': _sha(contents), 'size': len(contents)})
        receipt = {'schema_version': 1, 'operation': 'PI_INACTIVE_SANDBOX_INSTALLED',
                   'source_commit': SOURCE_COMMIT, 'bundle_sha256': BUNDLE_SHA256,
                   'installed_files': rows, 'credential_enrolled': False,
                   'service_registered': False, 'activation_performed': False,
                   'data_directory_modified': False}
        receipt_path = staging / RECEIPT_PATH
        receipt_path.write_bytes(canonical_json(receipt))
        receipt_path.chmod(0o600)
        # Rename is atomic on local POSIX filesystems; target remains absent until publication.
        # A native durable installer will need an additional race-safe no-replace primitive.
        check_target(target)
        staging.rename(target)
        staging = None
        return {'schema_version': 1, 'operation': 'PI_INACTIVE_SANDBOX_INSTALLED',
                'target': str(target), 'file_count': len(files) + 1,
                'source_commit': SOURCE_COMMIT, 'bundle_sha256': BUNDLE_SHA256,
                'service_registered': False, 'activation_performed': False}
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def verify_inactive(target: Path, selected: dict, manifest: bytes, cfg: dict):
    reject_redirects(target)
    if not target.is_dir():
        raise InstallRefused('inactive install directory missing')
    receipt_data = read_regular(target / RECEIPT_PATH, 100_000)
    try:
        receipt = json.loads(receipt_data)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise InstallRefused('invalid install receipt') from exc
    if (receipt.get('operation') != 'PI_INACTIVE_SANDBOX_INSTALLED' or
            receipt.get('source_commit') != SOURCE_COMMIT or
            receipt.get('bundle_sha256') != BUNDLE_SHA256 or
            receipt.get('credential_enrolled') is not False or
            receipt.get('service_registered') is not False or
            receipt.get('activation_performed') is not False):
        raise InstallRefused('invalid install provenance or activation state')
    expected = dict(selected)
    expected[MANIFEST_NAME] = manifest
    expected[CONFIG_PATH] = canonical_json(cfg)
    rows = receipt.get('installed_files')
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise InstallRefused('receipt file count mismatch')
    names = [row.get('path') if type(row) is dict else None for row in rows]
    if len(set(names)) != len(expected) or set(names) != set(expected):
        raise InstallRefused('receipt path inventory mismatch')
    found = set()
    for path in target.rglob('*'):
        reject_redirects(path)
        if path.is_file():
            found.add(path.relative_to(target).as_posix())
        elif not path.is_dir():
            raise InstallRefused('nonregular installed filesystem object')
    if found != set(expected) | {RECEIPT_PATH}:
        raise InstallRefused('unexpected installed files')
    for row in rows:
        path = row['path']
        actual = read_regular(target.joinpath(*path.split('/')), 500_000)
        if actual != expected[path] or row['size'] != len(actual) or row['sha256'] != _sha(actual):
            raise InstallRefused('installed data or receipt digest differs')
    return {'schema_version': 1, 'operation': 'PI_INACTIVE_SANDBOX_VERIFIED',
            'file_count': len(found), 'source_commit': SOURCE_COMMIT,
            'activation_performed': False, 'service_registered': False}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bundle', required=True, type=Path)
    ap.add_argument('--target', required=True, type=Path)
    ap.add_argument('--interface', default='usb0')
    ap.add_argument('--usb-subnet', default='192.168.137.0/24')
    ap.add_argument('--source', required=True)
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--state-dir', default='/var/lib/onyxcore')
    ap.add_argument('--history-name', default='telemetry.db')
    ap.add_argument('--snapshot-name', default='latest-snapshot.json')
    ap.add_argument('--install', action='store_true')
    ap.add_argument('--approve-inactive', action='store_true')
    args = ap.parse_args(argv)
    try:
        if args.install != args.approve_inactive:
            raise InstallRefused('inactive install requires BOTH --install and --approve-inactive')
        if not args.bundle.is_absolute() or not args.target.is_absolute():
            raise InstallRefused('absolute bundle and target paths required')
        settings = dict(interface=args.interface, ipv4_subnet=args.usb_subnet,
                        source=args.source, port=args.port, state_dir=args.state_dir,
                        history_name=args.history_name, snapshot_name=args.snapshot_name)
        plan, selected, manifest, cfg = prepare(args.bundle, args.target, settings)
        if not args.install:
            print(canonical_json(plan).decode('ascii').strip())
            return 0
        result = create_inactive(args.target, selected, manifest, cfg)
        verify_inactive(args.target, selected, manifest, cfg)
        print(canonical_json(result).decode('ascii').strip())
        return 0
    except (InstallRefused, OSError, TypeError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
