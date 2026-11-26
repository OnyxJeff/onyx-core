#!/usr/bin/env python3
"""ONYX CORE v1.0.0 M2-S5B: native Windows TEMP-ONLY no-replace proof.

No persistent installation capability. Public CLI defaults to read-only preview.
The only write mode creates fresh OS Temp fixtures for two checks:
(1) full 17-file R3 DACL-hardened no-replace publish and receipt verification;
(2) existing-target race refusal by Windows MoveFileExW without replace flags.
Never touches a LocalAppData installation, credentials, tasks or services.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import uuid

R3_SOURCE_SHA256 = '9c8fe4fae2a7422ae927fbe2adcbea9b539735e8a4916379a84f943ab4c54a03'
M2_HEAD = '00c6ba630a18b054308bb7119b610602790e44be'
MARKER = b'ONYX-V100-S5A-NATIVE-ACL-FIXTURE'
# All native publication occurs under brand-new, direct OS Temp children.


class PublicationRefused(ValueError):
    pass


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(obj: dict) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(',', ':')) + '\n').encode('ascii')


def reviewed_r3():
    source = Path(__file__).with_name('onyx_v100_windows_native_acl_fixture.py')
    if (not source.is_file() or source.is_symlink() or
            sha(source.read_bytes()) != R3_SOURCE_SHA256):
        raise PublicationRefused('accepted M2-S5A-R3 Python source hash mismatch')
    spec = importlib.util.spec_from_file_location('onyx_v100_s5b_pinned_r3', source)
    if spec is None or spec.loader is None:
        raise PublicationRefused('failed to load pinned R3 source')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if mod.M2_COMMIT != M2_HEAD:
        raise PublicationRefused('pinned R3 M2 Git identity mismatch')
    return mod


def guard_move(root: Path, staging: Path, target: Path, r3) -> None:
    """No redirections, no cross-parent moves, and valid S5A Temp marker."""
    r3.guard_fixture(root, target)
    if (staging.parent != root or staging.name.startswith('.OnyxCore-v100-staging-') is False or
            len(staging.name) > 80 or not staging.is_dir() or staging.is_symlink() or
            (hasattr(staging, 'is_junction') and staging.is_junction()) or
            target.is_symlink() or (hasattr(target, 'is_junction') and target.is_junction())):
        raise PublicationRefused('invalid/redirected staging or destination path')
    if (root.is_symlink() or root.parent != Path(tempfile.gettempdir()) or
            staging.drive.lower() != target.drive.lower() or
            staging.resolve(strict=True).parent != root.resolve(strict=True)):
        raise PublicationRefused('staging/destination not on same Temp fixture volume')


def win32_no_replace(staging: Path, target: Path, *, root: Path, r3=None) -> None:
    """A single Windows directory rename with no REPLACE/COPY/DELAY flags."""
    r3 = r3 or reviewed_r3()
    if sys.platform != 'win32':
        raise PublicationRefused('Win32 no-replace publish requires native Windows')
    guard_move(root, staging, target, r3)
    # NEVER use os.replace, MoveFileExW(REPLACE_EXISTING), or a copy fallback.
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    func = kernel.MoveFileExW
    func.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    func.restype = ctypes.c_int
    if not func(str(staging), str(target), 0):
        code = ctypes.get_last_error()
        raise PublicationRefused('atomic Windows directory move refused (Win32 error=' + str(code) + ')')


def make_root(r3) -> tuple[Path, Path]:
    temp = Path(tempfile.gettempdir())
    if (not temp.is_dir() or temp.is_symlink() or
            (hasattr(temp, 'is_junction') and temp.is_junction())):
        raise PublicationRefused('redirected Windows OS Temp directory')
    root = temp / ('OnyxV100-S5A-ACL-' + uuid.uuid4().hex)
    target = root / ('OnyxCore-v100-Inactive-S5A' + uuid.uuid4().hex)
    root.mkdir(exist_ok=False)
    (root / '.s5a-fixture.marker').write_bytes(MARKER)
    r3.guard_fixture(root, target)
    return root, target


def full_fixture(bundle: Path, dashboard: Path, settings: dict, r3) -> dict:
    helper = r3.validated_fixture_helper()
    source = r3.load_reviewed()
    _s4b, _base, user, _isolation = source.reviewed_modules()
    expected, config = source.expected_user_install(bundle, dashboard, settings)
    if len(expected) != 16 or config['gateway']['port'] in (18766, 18767, 18768, 18769):
        raise PublicationRefused('integrated runtime inventory/port contract mismatch')
    root, target = make_root(r3)
    # Failure deliberately retains evidence; no permission cleanup on an unknown state.
    staging = Path(tempfile.mkdtemp(prefix='.OnyxCore-v100-staging-', dir=str(root)))
    guard_move(root, staging, target, r3)
    records = []
    for rel, contents in sorted(expected.items()):
        if (not isinstance(rel, str) or rel.startswith('/') or '\\' in rel or ':' in rel or
                '..' in rel.split('/') or not isinstance(contents, bytes)):
            raise PublicationRefused('unsafe installer payload path or contents')
        path = staging.joinpath(*rel.split('/'))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        records.append({'path': rel, 'size': len(contents), 'sha256': sha(contents)})
    receipt = {'schema_version': 1, 'operation': 'INACTIVE_WINDOWS_USER_INSTALL',
               'release_version': '1.0.0', 'source_commit': user.SOURCE_COMMIT,
               'bundle_sha256': user.sandbox_module().BUNDLE_SHA256,
               'dashboard_sha256': user.sandbox_module().DASHBOARD_SHA256,
               'installed_files': records, 'credential_enrolled': False,
               'service_or_task_changes': False, 'activation_performed': False,
               'network_scope_verified': False, 'acl_hardened': True}
    (staging / user.RECEIPT_NAME).write_bytes(user.canonical_json(receipt))
    r3._native_acl(helper, 'Harden', root, staging)
    # One no-replace Win32 system call, no fallback and no pre-delete.
    win32_no_replace(staging, target, root=root, r3=r3)
    result = user.verify_inactive(target, expected, root=root)
    r3._native_acl(helper, 'Audit', root, target)
    if result['file_count'] != 17:
        raise PublicationRefused('published native runtime failed 17-file receipt verification')
    return {'root': str(root), 'target': str(target), 'file_count': 17}


def collision_fixture(r3) -> dict:
    """Native race witness: target exists at the exact moment Win32 rename runs."""
    root, target = make_root(r3)
    staging = root / ('.OnyxCore-v100-staging-' + uuid.uuid4().hex)
    staging.mkdir(exist_ok=False)
    (staging / 'source-witness.txt').write_bytes(b'ONYX-S5B-SOURCE-UNCHANGED\n')
    target.mkdir(exist_ok=False)
    witness = target / 'target-witness.txt'
    witness.write_bytes(b'ONYX-S5B-TARGET-PRESERVED\n')
    rejected = False
    try:
        win32_no_replace(staging, target, root=root, r3=r3)
    except PublicationRefused as exc:
        if 'Win32 error=' not in str(exc):
            raise
        rejected = True
    if (not rejected or not staging.is_dir() or not target.is_dir() or
            (staging / 'source-witness.txt').read_bytes() != b'ONYX-S5B-SOURCE-UNCHANGED\n' or
            witness.read_bytes() != b'ONYX-S5B-TARGET-PRESERVED\n'):
        raise PublicationRefused('existing destination was replaced or modified: STOP')
    return {'root': str(root), 'existing_target_preserved': True,
            'source_retained': True, 'no_replace_refusal': True}


def settings_from(args) -> dict:
    return {'receiver_host': args.receiver_host, 'receiver_port': args.receiver_port,
            'source': args.source, 'network_adapter': args.network_adapter,
            'usb_adapter': args.usb_adapter, 'gateway_port': args.gateway_port,
            'interval': args.interval_seconds}


def cli(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--dashboard', type=Path, required=True)
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
        if (not a.bundle.is_absolute() or not a.dashboard.is_absolute() or
                a.bundle.is_symlink() or a.dashboard.is_symlink()):
            raise PublicationRefused('reviewed input paths must be absolute non-symlinks')
        r3 = reviewed_r3()
        flags = a.approve_native_temp, a.approve_no_replace_test
        if a.mode == 'preview':
            if any(flags):
                raise PublicationRefused('preview cannot accept native write flags')
            report = r3.preview(a.bundle, a.dashboard, settings_from(a))
            report['operation'] = 'M2_S5B_WINDOWS_USER_PREVIEW_ONLY'
        else:
            if not all(flags):
                raise PublicationRefused('two explicit Temp-only approvals required')
            if (sys.platform != 'win32' or sys.version_info[:2] != (3, 13) or
                    ctypes.windll.shell32.IsUserAnAdmin() != 0):
                raise PublicationRefused('non-elevated Windows Python 3.13 required')
            full = full_fixture(a.bundle, a.dashboard, settings_from(a), r3)
            race = collision_fixture(r3)
            report = {'operation': 'M2_S5B_NATIVE_TEMP_NO_REPLACE_ACCEPTED',
                      'schema_version': 1, 'm2_commit': M2_HEAD,
                      'installed_fixture': full, 'collision_fixture': race,
                      'persistent_installation': False, 'credential_enrolled': False,
                      'tasks_or_services_modified': False, 'production_modified': False,
                      'native_temp_approval_only': True}
        print(canonical(report).decode('ascii').strip())
        return 0
    except (PublicationRefused, ValueError, KeyError, OSError, RuntimeError, TypeError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(cli())
