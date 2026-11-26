#!/usr/bin/env python3
"""ONYX CORE M2-S5C: inactive user-publisher integration.

Public CLI: read-only LocalAppData preview, or two-flag OS Temp acceptance.
An internal user-scope publication function exists for a FUTURE separately
approved installer; the CLI deliberately has no persistent-install mode.
No credentials, service/task registration, network access or auto-cleanup.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

M2_HEAD = '00c6ba630a18b054308bb7119b610602790e44be'
S4C_SHA = 'a3d96181da4e0907d8ca50eb1e9a6d7e4e70a6f7b0adcbe381d7e674d063b83f'
R3_SHA = '9c8fe4fae2a7422ae927fbe2adcbea9b539735e8a4916379a84f943ab4c54a03'
S5B_SHA = '9c42a2d270a5af3523e070e0ac1a2eb242bb508f987de6c7cd1805f270e12391'
BUNDLE_SHA = 'b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d'
DASHBOARD_SHA = '16cec6731032a444bf944e165b22fdc179cca6ae6d48252520b77a51be6d8a57'
# Populated at packaging, only the reviewed SAFE helper may run.
SAFE_HELPER_SHA = '865006780490c0329a922374d31fb40b449c4be43153bf2fc7c54308e66a868e'
PREVIEW_NAME = 'OnyxCore-v100-Inactive-M2S5CPreview'


class SafePublishRefused(ValueError):
    pass


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')


def pinned_module(filename: str, digest: str, modname: str):
    path = Path(__file__).with_name(filename)
    if not path.is_file() or path.is_symlink() or sha(path.read_bytes()) != digest:
        raise SafePublishRefused('reviewed dependency hash mismatch: ' + filename)
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise SafePublishRefused('reviewed dependency import failed: ' + filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def reviewed():
    s4c = pinned_module('onyx_v100_windows_user_integrated.py', S4C_SHA, 'onyx_s5c_s4c')
    r3 = pinned_module('onyx_v100_windows_native_acl_fixture.py', R3_SHA, 'onyx_s5c_r3')
    s5b = pinned_module('onyx_v100_windows_atomic_publish.py', S5B_SHA, 'onyx_s5c_s5b')
    if r3.M2_COMMIT != M2_HEAD or s5b.M2_HEAD != M2_HEAD:
        raise SafePublishRefused('accepted M2 HEAD mismatch')
    return s4c, r3, s5b


def helper_path() -> Path:
    helper = Path(__file__).with_name('Set-OnyxV100SafeUserDacl.ps1')
    if not helper.is_file() or helper.is_symlink() or sha(helper.read_bytes()) != SAFE_HELPER_SHA:
        raise SafePublishRefused('new DACL-only helper does not match pinned source')
    return helper


def settings_from(a) -> dict:
    return dict(receiver_host=a.receiver_host, receiver_port=a.receiver_port,
                source=a.source, network_adapter=a.network_adapter,
                usb_adapter=a.usb_adapter, gateway_port=a.gateway_port,
                interval=a.interval_seconds)


def expected_install(bundle: Path, dashboard: Path, settings: dict, *, s4c=None):
    s4c = s4c or reviewed()[0]
    if (not bundle.is_absolute() or not dashboard.is_absolute() or
            bundle.is_symlink() or dashboard.is_symlink() or
            sha(bundle.read_bytes()) != BUNDLE_SHA or sha(dashboard.read_bytes()) != DASHBOARD_SHA):
        raise SafePublishRefused('approved bundle/dashboard source mismatch')
    expected, cfg = s4c.expected_user_install(bundle, dashboard, settings)
    if len(expected) != 16 or len(set(expected)) != 16:
        raise SafePublishRefused('17-file integrated payload is incomplete')
    return expected, cfg


def native_guard() -> None:
    if (sys.platform != 'win32' or sys.version_info[:2] != (3, 13) or
            ctypes.windll.shell32.IsUserAnAdmin() != 0):
        raise SafePublishRefused('non-elevated native Windows Python 3.13 required')


def preview(bundle: Path, dashboard: Path, settings: dict) -> dict:
    s4c, _, _ = reviewed()
    root = s4c.reviewed_modules()[2].native_user_root()
    target = root / PREVIEW_NAME
    report = s4c.preview_user(bundle, dashboard, target, settings)
    if report['file_count_if_installed'] != 17 or report['installation_performed']:
        raise SafePublishRefused('unsafe user preview result')
    return {'schema_version': 1, 'operation': 'M2_S5C_SAFE_USER_PREVIEW',
            'target': str(target), 'file_count_if_installed': 17,
            'old_unsafe_acl_helper_used': False, 'real_user_installation_performed': False,
            'credentials_read': False, 'tasks_or_services_modified': False,
            'persistent_approval_required': True}


def safe_dacl(mode: str, scope: str, root: Path, path: Path) -> None:
    helper = helper_path()
    args = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(helper), '-Mode', mode, '-Scope', scope,
            '-Root', str(root), '-ContentPath', str(path)]
    args += (['-ApproveTempFixture'] if scope == 'Temp' else
             ['-ApproveInactiveUser', '-ApproveUserDacl'])
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SafePublishRefused('DACL helper invocation failed') from exc
    if result.returncode != 0 or 'PASS: DACL-only' not in result.stdout:
        diagnostic = ' '.join((result.stderr or result.stdout or '').split())[:1000]
        raise SafePublishRefused(f'DACL-only {mode} failed (exit={result.returncode}): {diagnostic}')


def native_move_new(staging: Path, target: Path, root: Path) -> None:
    """Native Windows no-replace rename, no copy/replace/delete fallback."""
    if (sys.platform != 'win32' or staging.parent != root or target.parent != root or
            staging.drive.lower() != target.drive.lower() or
            target.exists() or target.is_symlink() or
            (hasattr(target, 'is_junction') and target.is_junction())):
        raise SafePublishRefused('unsafe native no-replace publication paths')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    move = kernel.MoveFileExW
    move.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    move.restype = ctypes.c_int
    if not move(str(staging), str(target), 0):
        raise SafePublishRefused('native no-replace directory publication failed (Win32 error=' +
                                 str(ctypes.get_last_error()) + ')')


def install_core(expected: dict, *, root: Path, target: Path, scope: str,
                 s4c, r3, harden=safe_dacl, move=native_move_new,
                 approve_persistent=False, approve_inactive=False,
                 approve_no_replace=False) -> dict:
    """Safe publication core. No automatic cleanup: incomplete stages retain evidence.

    Scope User cannot be reached through CLI. Requires separate explicit
    authorization at a future caller; fixture mode is a new marked Temp root.
    """
    native_guard()
    if scope == 'Temp':
        r3.guard_fixture(root, target)
    elif scope == 'User':
        if not (approve_persistent and approve_inactive and approve_no_replace):
            raise SafePublishRefused('three explicit future user-scope approvals required')
        user = s4c.reviewed_modules()[2]
        user.validate_target(target, root=user.native_user_root())
        if root != user.native_user_root():
            raise SafePublishRefused('LocalAppData root disagreement')
    else:
        raise SafePublishRefused('invalid scope')
    if not root.is_dir() or root.is_symlink():
        raise SafePublishRefused('publication parent is absent or redirected')
    if len(expected) != 16:
        raise SafePublishRefused('integrated runtime inventory not exactly 16 payloads')
    # All paths are pinned and fully materialized BEFORE any durable user publication.
    user = s4c.reviewed_modules()[2]
    entries = []
    for rel, data in sorted(expected.items()):
        if (not isinstance(rel, str) or rel.startswith('/') or '\\' in rel or ':' in rel or
                '..' in rel.split('/') or not isinstance(data, bytes)):
            raise SafePublishRefused('unsafe runtime payload path/data')
        entries.append({'path': rel, 'size': len(data), 'sha256': sha(data)})
    receipt = {'schema_version': 1, 'operation': 'INACTIVE_WINDOWS_USER_INSTALL',
               'release_version': '1.0.0', 'source_commit': user.SOURCE_COMMIT,
               'bundle_sha256': user.sandbox_module().BUNDLE_SHA256,
               'dashboard_sha256': user.sandbox_module().DASHBOARD_SHA256,
               'installed_files': entries, 'credential_enrolled': False,
               'service_or_task_changes': False, 'activation_performed': False,
               'network_scope_verified': False, 'acl_hardened': True}
    staging = Path(tempfile.mkdtemp(prefix='.OnyxCore-v100-staging-', dir=str(root)))
    if staging.parent != root or staging.is_symlink() or staging.drive.lower() != target.drive.lower():
        raise SafePublishRefused('staging path changed unexpectedly; incomplete stage retained')
    try:
        for rel, data in sorted(expected.items()):
            path = staging.joinpath(*rel.split('/'))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (staging / user.RECEIPT_NAME).write_bytes(user.canonical_json(receipt))
        harden('Harden', scope, root, staging)
        # Recheck target and path after the ACL hardened stage exists.
        if scope == 'User':
            user.validate_target(target, root=root)
        else:
            r3.guard_fixture(root, target)
        move(staging, target, root)
        user.verify_inactive(target, expected, root=root)
        harden('Audit', scope, root, target)
    except Exception as exc:
        raise SafePublishRefused('INCOMPLETE: staged/published evidence retained; ' + str(exc)) from exc
    return {'schema_version': 1, 'operation': 'M2_S5C_INACTIVE_PUBLISHED',
            'target': str(target), 'file_count': 17, 'scope': scope,
            'credentials_enrolled': False, 'activation_performed': False,
            'production_modified': False}


def fixture_acceptance(bundle: Path, dashboard: Path, settings: dict) -> dict:
    native_guard()
    s4c, r3, s5b = reviewed()
    helper_path()
    expected, cfg = expected_install(bundle, dashboard, settings, s4c=s4c)
    root, target = s5b.make_root(r3)
    result = install_core(expected, root=root, target=target, scope='Temp', s4c=s4c, r3=r3)
    collision = s5b.collision_fixture(r3)
    if not collision['no_replace_refusal'] or result['file_count'] != 17:
        raise SafePublishRefused('integrated native fixture acceptance incomplete')
    return {'schema_version': 1, 'operation': 'M2_S5C_NATIVE_TEMP_INTEGRATION_ACCEPTED',
            'published_fixture': str(target), 'collision_fixture': collision['root'],
            'file_count': 17, 'user_scope_written': False,
            'credentials_enrolled': False, 'tasks_or_services_modified': False}


def cli(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', required=True, type=Path)
    p.add_argument('--dashboard', required=True, type=Path)
    p.add_argument('--receiver-host', required=True)
    p.add_argument('--receiver-port', type=int, default=8765)
    p.add_argument('--source', required=True)
    p.add_argument('--network-adapter', required=True)
    p.add_argument('--usb-adapter', required=True)
    p.add_argument('--gateway-port', type=int, required=True)
    p.add_argument('--interval-seconds', type=int, default=30)
    p.add_argument('--mode', choices=('preview', 'native-temp'), default='preview')
    p.add_argument('--approve-native-temp', action='store_true')
    p.add_argument('--approve-no-replace-test', action='store_true')
    a = p.parse_args(argv)
    try:
        flags = (a.approve_native_temp, a.approve_no_replace_test)
        settings = settings_from(a)
        if a.mode == 'preview':
            if any(flags):
                raise SafePublishRefused('preview refuses write approval flags')
            report = preview(a.bundle, a.dashboard, settings)
        else:
            if not all(flags):
                raise SafePublishRefused('two approvals needed for native Temp fixture')
            report = fixture_acceptance(a.bundle, a.dashboard, settings)
        print(canonical(report).decode('ascii').strip())
        return 0
    except (SafePublishRefused, ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(cli())
