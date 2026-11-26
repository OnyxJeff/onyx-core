#!/usr/bin/env python3
"""ONYX CORE v1.0.0 M2-S2C: new, inactive user-scoped Windows install.

Preview is default; permanent LocalAppData publication needs THREE explicit flags.
No credentials, network probes, Scheduled Tasks, registry, firewall, or activation.
The previous S2B sandbox installer provides SHA256-pinned bundle/config validation.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

SOURCE_COMMIT = '8df66f772d5b15464290b7040621e9b03635d49e'
S2B_SOURCE_SHA256 = 'a6b29d1706f8a1be281daf59c124537f2d97168770e4169854f8793760513e14'
ACL_HELPER_SHA256 = '7e8b1f0b70a99684cfeaab3ad59d369dc1df6b50e6c4e7446eae1789bee5d5d5'
TARGET_PATTERN = re.compile(r'OnyxCore-v100-Inactive-[A-Za-z0-9_-]{8,48}\Z')
RECEIPT_NAME = 'installation-receipt.json'
CONFIG_NAME = 'config/windows.config.json'


class UserInstallRefused(ValueError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')


def sandbox_module():
    """Load only the previously accepted and SHA256-pinned S2B dependency."""
    source = Path(__file__).with_name('onyx_v100_windows_install.py')
    if not source.is_file() or source.is_symlink() or sha256(source.read_bytes()) != S2B_SOURCE_SHA256:
        raise UserInstallRefused('reviewed M2-S2B Windows installer source required')
    spec = importlib.util.spec_from_file_location('onyx_v100_windows_install', source)
    if spec is None or spec.loader is None:
        raise UserInstallRefused('cannot load reviewed installer')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reject_redirects(path: Path) -> None:
    part = path
    while True:
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise UserInstallRefused('redirected path component refused')
        if part.parent == part:
            return
        part = part.parent


def native_user_root() -> Path:
    """Get LocalAppData from Windows Known Folder API, not a caller-supplied target."""
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 13):
        raise UserInstallRefused('Windows Python 3.13 is required')
    buffer = ctypes.create_unicode_buffer(32768)
    # CSIDL_LOCAL_APPDATA = 0x1c; SHGFP_TYPE_CURRENT = 0
    result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x001c, None, 0, buffer)
    if result != 0 or not buffer.value:
        raise UserInstallRefused('cannot resolve native LocalAppData known folder')
    root = Path(buffer.value)
    environment = os.environ.get('LOCALAPPDATA')
    if not environment or os.path.normcase(os.path.abspath(environment)) != os.path.normcase(str(root)):
        raise UserInstallRefused('LocalAppData environment and native known folder disagree')
    reject_redirects(root)
    if not root.is_absolute() or not root.is_dir():
        raise UserInstallRefused('native LocalAppData is not an ordinary directory')
    return root


def validate_target(target: Path, *, root: Path) -> Path:
    """Require a NEW version-specific direct child of the trusted user folder."""
    if not root.is_absolute() or not root.is_dir():
        raise UserInstallRefused('user installation root must already exist')
    reject_redirects(root)
    if not target.is_absolute() or '..' in target.parts or not TARGET_PATTERN.fullmatch(target.name):
        raise UserInstallRefused('target must be new OnyxCore-v100-Inactive-* directory')
    reject_redirects(target)
    if target.parent.resolve(strict=True) != root.resolve(strict=True):
        raise UserInstallRefused('target must be a direct child of LocalAppData')
    if target.exists() or target.is_symlink():
        raise UserInstallRefused('user installation target already exists; refusing overwrite')
    return target


def _expected_payload(payload: dict, dashboard: bytes, manifest: bytes, cfg: dict) -> dict:
    expected = dict(payload)
    expected['windows/gateway/gateway-dashboard.html'] = dashboard
    expected['windows/gateway/gateway-dashboard-v100.html'] = dashboard
    expected['bundle-manifest.json'] = manifest
    expected[CONFIG_NAME] = canonical_json(cfg)
    if len(expected) != 15:
        raise UserInstallRefused('incomplete Windows/common installed runtime inventory')
    return expected


def prepare_plan(bundle: Path, dashboard_path: Path, target: Path, settings: dict, *, root: Path):
    validate_target(target, root=root)
    base = sandbox_module()
    payload, dashboard, manifest = base.inspect_inputs(bundle, dashboard_path)
    cfg = base.validate_configuration(bundle, **settings)
    expected = _expected_payload(payload, dashboard, manifest, cfg)
    plan = {
        'schema_version': 1, 'operation': 'WINDOWS_USER_INSTALL_PREVIEW',
        'source_commit': SOURCE_COMMIT, 'target': str(target),
        'file_count': len(expected) + 1,
        'receiver_host': cfg['receiver']['host'],
        'receiver_port': cfg['receiver']['port'],
        'collector_source': cfg['collector']['source'],
        'gateway_port': cfg['gateway']['port'],
        'installation_performed': False, 'activation_performed': False,
        'acl_verified': False, 'credentials_read': False,
        'service_or_task_changes': False, 'network_scope_verified': False,
    }
    return plan, expected, cfg


def protect_staging(staging: Path, *, root: Path) -> None:
    """Set and audit the DACL using the pinned PowerShell helper, before publish."""
    helper = Path(__file__).with_name('Set-OnyxV100UserInstallAcl.ps1')
    if not helper.is_file() or helper.is_symlink() or sha256(helper.read_bytes()) != ACL_HELPER_SHA256:
        raise UserInstallRefused('user-install ACL helper does not match reviewed fingerprint')
    if staging.parent.resolve(strict=True) != root.resolve(strict=True):
        raise UserInstallRefused('ACL staging location mismatch')
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
             '-File', str(helper), '-StagingPath', str(staging)],
            capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UserInstallRefused('user-install ACL operation failed') from exc
    if result.returncode != 0 or 'PASS: User-scoped staging DACL restricted and audited.' not in result.stdout:
        raise UserInstallRefused('user-install ACL hardening/verification failed')


def install_inactive(target: Path, expected: dict, *, root: Path,
                     native_check=None, acl_guard=None) -> dict:
    if native_check is None:
        native_check = lambda: sys.platform == 'win32' and sys.version_info[:2] == (3, 13) and ctypes.windll.shell32.IsUserAnAdmin() == 0
    if not native_check():
        raise UserInstallRefused('non-elevated native Windows Python 3.13 required')
    validate_target(target, root=root)
    if acl_guard is None:
        acl_guard = lambda path: protect_staging(path, root=root)
    staging = Path(tempfile.mkdtemp(prefix='.OnyxCore-v100-staging-', dir=str(root)))
    try:
        files = []
        for name, data in sorted(expected.items()):
            if (not isinstance(name, str) or name.startswith('/') or '..' in name.split('/') or
                    '\\' in name or ':' in name or not isinstance(data, bytes)):
                raise UserInstallRefused('unsafe installed file')
            dest = staging.joinpath(*name.split('/'))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            files.append({'path': name, 'size': len(data), 'sha256': sha256(data)})
        receipt = {
            'schema_version': 1, 'operation': 'INACTIVE_WINDOWS_USER_INSTALL',
            'release_version': '1.0.0', 'source_commit': SOURCE_COMMIT,
            'bundle_sha256': sandbox_module().BUNDLE_SHA256,
            'dashboard_sha256': sandbox_module().DASHBOARD_SHA256,
            'installed_files': files, 'credential_enrolled': False,
            'service_or_task_changes': False, 'activation_performed': False,
            'network_scope_verified': False, 'acl_hardened': True,
        }
        (staging / RECEIPT_NAME).write_bytes(canonical_json(receipt))
        acl_guard(staging)
        validate_target(target, root=root)
        staging.rename(target)
        staging = None
        return {'schema_version': 1, 'operation': 'WINDOWS_USER_INACTIVE_INSTALLED',
                'target': str(target), 'file_count': len(expected) + 1,
                'source_commit': SOURCE_COMMIT, 'credential_enrolled': False,
                'service_or_task_changes': False, 'activation_performed': False,
                'acl_hardened': True}
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def verify_inactive(target: Path, expected: dict, *, root: Path) -> dict:
    if not target.is_absolute() or not TARGET_PATTERN.fullmatch(target.name):
        raise UserInstallRefused('invalid verification target')
    if target.parent.resolve(strict=True) != root.resolve(strict=True):
        raise UserInstallRefused('verification target outside LocalAppData')
    reject_redirects(target)
    if not target.is_dir():
        raise UserInstallRefused('installation target missing')
    receipt_path = target / RECEIPT_NAME
    if not receipt_path.is_file() or receipt_path.stat().st_size > 100000:
        raise UserInstallRefused('installation receipt missing or oversized')
    receipt = json.loads(receipt_path.read_bytes())
    if (receipt.get('operation') != 'INACTIVE_WINDOWS_USER_INSTALL' or
            receipt.get('source_commit') != SOURCE_COMMIT or
            receipt.get('acl_hardened') is not True or
            receipt.get('credential_enrolled') is not False or
            receipt.get('activation_performed') is not False):
        raise UserInstallRefused('installation receipt identity mismatch')
    rows = receipt.get('installed_files')
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise UserInstallRefused('installation receipt inventory mismatch')
    names = [row.get('path') for row in rows]
    if len(set(names)) != len(expected) or set(names) != set(expected):
        raise UserInstallRefused('receipt names differ from expected files')
    actual = set()
    for item in target.rglob('*'):
        reject_redirects(item)
        if item.is_file():
            actual.add(item.relative_to(target).as_posix())
    if actual != set(expected) | {RECEIPT_NAME}:
        raise UserInstallRefused('installed filesystem contains unexpected or missing files')
    for row in rows:
        path = target.joinpath(*row['path'].split('/'))
        if not path.is_file() or path.stat().st_size != row['size'] or path.read_bytes() != expected[row['path']]:
            raise UserInstallRefused('installed file differs from verified runtime source')
        if row['sha256'] != sha256(expected[row['path']]):
            raise UserInstallRefused('installed file SHA256 differs from receipt')
    return {'schema_version': 1, 'operation': 'WINDOWS_USER_INSTALL_VERIFIED',
            'source_commit': SOURCE_COMMIT, 'file_count': len(actual),
            'activation_performed': False}


def cli(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--dashboard', required=True, type=Path)
    parser.add_argument('--target', required=True, type=Path)
    parser.add_argument('--receiver-host', required=True)
    parser.add_argument('--receiver-port', type=int, default=8765)
    parser.add_argument('--source', required=True)
    parser.add_argument('--network-adapter', required=True)
    parser.add_argument('--usb-adapter', required=True)
    parser.add_argument('--gateway-port', type=int, required=True)
    parser.add_argument('--interval-seconds', type=int, default=30)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--approve-inactive', action='store_true')
    parser.add_argument('--approve-user-scope', action='store_true')
    args = parser.parse_args(argv)
    try:
        approvals = (args.install, args.approve_inactive, args.approve_user_scope)
        if any(approvals) and not all(approvals):
            raise UserInstallRefused('user installation requires all three explicit flags')
        root = native_user_root()
        settings = dict(receiver_host=args.receiver_host, receiver_port=args.receiver_port,
                        source=args.source, network_adapter=args.network_adapter,
                        usb_adapter=args.usb_adapter, gateway_port=args.gateway_port,
                        interval=args.interval_seconds)
        plan, expected, _ = prepare_plan(args.bundle, args.dashboard, args.target, settings, root=root)
        if not args.install:
            print(canonical_json(plan).decode('ascii').strip())
            return 0
        result = install_inactive(args.target, expected, root=root)
        verify_inactive(args.target, expected, root=root)
        print(canonical_json(result).decode('ascii').strip())
        return 0
    except (UserInstallRefused, ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(cli())
