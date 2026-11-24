#!/usr/bin/env python3
"""M2-S5A: acceptance of the 17-file Windows runtime with a real Temp-only DACL.

The default CLI previews the native LocalAppData target. Only `native-temp-acl`
can write, and it is strictly confined to a new OS Temp test fixture; it cannot
install persistently, enroll credentials, launch telemetry, or register tasks.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

M2_COMMIT = '00c6ba630a18b054308bb7119b610602790e44be'
S4C_SHA256 = 'a3d96181da4e0907d8ca50eb1e9a6d7e4e70a6f7b0adcbe381d7e674d063b83f'
ACL_FIXTURE_SHA256 = 'b1bb08c0a0471bc43576cdb5ef6dd22ce16dc9775df5496409c2494227bee0f4'
REVIEWED_ACL_SHA256 = '7e8b1f0b70a99684cfeaab3ad59d369dc1df6b50e6c4e7446eae1789bee5d5d5'
BUNDLE_SHA256 = 'b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d'
DASHBOARD_SHA256 = '16cec6731032a444bf944e165b22fdc179cca6ae6d48252520b77a51be6d8a57'
MARKER = b'ONYX-V100-S5A-NATIVE-ACL-FIXTURE'
FIXTURE_RE = re.compile(r'OnyxV100-S5A-ACL-[a-f0-9]{32}\Z')
TARGET_RE = re.compile(r'OnyxCore-v100-Inactive-S5A[a-f0-9]{32}\Z')


class AcceptanceRefused(ValueError):
    pass


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def load_reviewed():
    """Pin existing committed M2-S4C before using its 17-file installation plan."""
    path = Path(__file__).with_name('onyx_v100_windows_user_integrated.py')
    if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != S4C_SHA256:
        raise AcceptanceRefused('reviewed M2-S4C dependency differs from committed source')
    spec = importlib.util.spec_from_file_location('onyx_s5a_reviewed_s4c', path)
    if spec is None or spec.loader is None:
        raise AcceptanceRefused('cannot load reviewed S4C dependency')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def validated_fixture_helper() -> Path:
    helper = Path(__file__).with_name('Test-OnyxV100NativeAclFixture.ps1')
    if helper.is_symlink() or not helper.is_file() or digest(helper.read_bytes()) != ACL_FIXTURE_SHA256:
        raise AcceptanceRefused('S5A native fixture ACL helper hash mismatch')
    original = Path(__file__).with_name('Set-OnyxV100UserInstallAcl.ps1')
    if original.is_symlink() or not original.is_file() or digest(original.read_bytes()) != REVIEWED_ACL_SHA256:
        raise AcceptanceRefused('reviewed native ACL reference helper changed')
    # The committed S2C helper is retained as an immutable *known-unsafe* source.
    # It must never supply the S5A ACL operation. S5A-R3 has its own pinned
    # DACL-only .NET SetAccessControl implementation (native acceptance pending).
    prior = original.read_text('utf-8')
    if ('/inheritance:r /T' not in prior or '/grant:r' not in prior):
        raise AcceptanceRefused('reviewed S2C ACL evidence unexpectedly differs')
    safe = helper.read_text('utf-8')
    if ('icacls.exe' in safe or '/inheritance:r' in safe or
            '[IO.Directory]::SetAccessControl($NodePath,$Acl)' not in safe or
            '[IO.File]::SetAccessControl($NodePath,$Acl)' not in safe or
            '[Security.AccessControl.DirectorySecurity]::new()' not in safe or
            '[Security.AccessControl.FileSecurity]::new()' not in safe or
            'Set-Acl -LiteralPath' in safe or
            'SetAccessRuleProtection($true,$false)' not in safe or
            'Assert-SafeAcl $Node.FullName' not in safe):
        raise AcceptanceRefused('native fixture must use pinned DACL-only hardening')
    return helper


def settings_from(args) -> dict:
    return dict(receiver_host=args.receiver_host, receiver_port=args.receiver_port,
                source=args.source, network_adapter=args.network_adapter,
                usb_adapter=args.usb_adapter, gateway_port=args.gateway_port,
                interval=args.interval_seconds)


def preview(bundle: Path, dashboard: Path, settings: dict, *, target=None) -> dict:
    """Native read-only plan; the active installation target must not exist."""
    mod = load_reviewed()
    s4b, base, user, isolation = mod.reviewed_modules()
    root = user.native_user_root()
    target = target or root / ('OnyxCore-v100-Inactive-S5A' + uuid.uuid4().hex)
    plan = mod.preview_user(bundle, dashboard, target, settings, root=root)
    return {'schema_version': 1, 'operation': 'WINDOWS_S5A_USER_PREVIEW',
            'target': str(target), 'file_count_if_installed': plan['file_count_if_installed'],
            'gateway_port': plan['gateway_port'], 'm2_commit': M2_COMMIT,
            'installation_performed': False, 'acl_changed': False,
            'credential_enrolled': False, 'task_or_service_changes': False,
            'requires_separate_persistent_install_authorization': True}


def guard_fixture(root: Path, target: Path, *, require_marker=True) -> None:
    """A *direct* OS Temp child; never accept LocalAppData install directories."""
    tmp = Path(tempfile.gettempdir())
    if (not root.is_absolute() or not root.is_dir() or root.is_symlink() or
            (hasattr(root, 'is_junction') and root.is_junction()) or
            root.parent != tmp or not FIXTURE_RE.fullmatch(root.name) or
            root.resolve(strict=True).parent != tmp.resolve(strict=True) or
            target.parent != root or not TARGET_RE.fullmatch(target.name)):
        raise AcceptanceRefused('path is not a unique direct OS Temp S5A fixture')
    if require_marker and (not (root / '.s5a-fixture.marker').is_file() or
                           (root / '.s5a-fixture.marker').read_bytes() != MARKER):
        raise AcceptanceRefused('OS Temp fixture marker missing')


def _native_acl(helper: Path, mode: str, root: Path, path: Path):
    args = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(helper), '-Mode', mode, '-FixtureRoot', str(root),
            '-ContentPath', str(path), '-ApproveTempFixture']
    try:
        completed = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AcceptanceRefused('native ACL fixture helper could not execute') from exc
    expected = ('PASS: Native Temp fixture DACL restricted and audited.' if mode == 'Harden'
                else 'PASS: Published Temp fixture DACL verified read-only.')
    if completed.returncode != 0 or expected not in completed.stdout:
        # This pinned helper only handles a disposable Temp fixture, not secrets.
        # Keep enough native error context to diagnose a failing Set-Acl node.
        details = (completed.stderr or completed.stdout or '').strip().replace('\r','')
        details = ' '.join(details.split())[-800:]
        raise AcceptanceRefused('native Temp ACL ' + mode + ' failed '
                                + '(exit=' + str(completed.returncode) + '): '
                                + (details or 'no native details returned'))


def native_temp_acl(bundle: Path, dashboard: Path, settings: dict, *,
                    approve_temp: bool, approve_inactive: bool) -> dict:
    """Use Windows DACL-only .NET ACLs on a new Temp install, never an active profile."""
    if not (approve_temp and approve_inactive):
        raise AcceptanceRefused('both explicit Temp-only fixture approvals required')
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 13):
        raise AcceptanceRefused('non-elevated native Windows Python 3.13 required')
    helper = validated_fixture_helper()
    mod = load_reviewed()
    _s4b, _base, user, _isolated = mod.reviewed_modules()
    expected, cfg = mod.expected_user_install(bundle, dashboard, settings)
    if len(expected) != 16 or cfg['gateway']['port'] in (18766, 18767, 18768, 18769):
        raise AcceptanceRefused('unexpected integrated runtime or unsafe port')
    tmp = Path(tempfile.gettempdir())
    if (tmp.is_symlink() or (hasattr(tmp, 'is_junction') and tmp.is_junction())
            or not tmp.is_dir()):
        raise AcceptanceRefused('redirected OS Temp location refused')
    root = tmp / ('OnyxV100-S5A-ACL-' + uuid.uuid4().hex)
    target = root / ('OnyxCore-v100-Inactive-S5A' + uuid.uuid4().hex)
    root.mkdir(mode=0o700, exist_ok=False)
    (root / '.s5a-fixture.marker').write_bytes(MARKER)
    guard_fixture(root, target)
    # No injected fake ACL here: real Windows helper must pass before publish.
    def native_guard(staging: Path):
        guard_fixture(root, target)
        if staging.parent != root or not staging.name.startswith('.OnyxCore-v100-staging-'):
            raise AcceptanceRefused('unexpected native staging directory')
        _native_acl(helper, 'Harden', root, staging)
    try:
        user.install_inactive(target, expected, root=root, native_check=None, acl_guard=native_guard)
        verified = user.verify_inactive(target, expected, root=root)
        _native_acl(helper, 'Audit', root, target)
    except Exception:
        # Deliberately keep fixture for inspection; never delete unknown ACL state.
        raise
    if verified['file_count'] != 17 or not target.is_dir():
        raise AcceptanceRefused('native installed fixture receipt mismatch')
    return {'schema_version': 1, 'operation': 'WINDOWS_S5A_NATIVE_TEMP_ACL_ACCEPTED',
            'm2_commit': M2_COMMIT, 'fixture_root': str(root), 'target': str(target),
            'file_count': 17, 'native_acl_verified': True,
            'persistent_installation_performed': False, 'credential_enrolled': False,
            'runtime_started': False, 'task_or_service_changes': False,
            'production_modified': False, 'fixture_retained_for_review': True}


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
    p.add_argument('--mode', choices=('preview-user', 'native-temp-acl'), default='preview-user')
    p.add_argument('--approve-temp-acl-test', action='store_true')
    p.add_argument('--approve-inactive-fixture', action='store_true')
    args = p.parse_args(argv)
    try:
        if (not args.bundle.is_absolute() or not args.dashboard.is_absolute() or
                args.bundle.is_symlink() or args.dashboard.is_symlink()):
            raise AcceptanceRefused('absolute non-redirected reviewed input paths required')
        settings = settings_from(args)
        flags = (args.approve_temp_acl_test, args.approve_inactive_fixture)
        if args.mode == 'preview-user':
            if any(flags):
                raise AcceptanceRefused('preview refuses unused native ACL approvals')
            report = preview(args.bundle, args.dashboard, settings)
        else:
            report = native_temp_acl(args.bundle, args.dashboard, settings,
                                     approve_temp=args.approve_temp_acl_test,
                                     approve_inactive=args.approve_inactive_fixture)
        print(canonical(report))
        return 0
    except (AcceptanceRefused, ValueError, OSError, KeyError, RuntimeError, TypeError,
            json.JSONDecodeError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(cli())
