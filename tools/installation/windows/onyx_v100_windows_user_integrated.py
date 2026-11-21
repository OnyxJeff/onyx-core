#!/usr/bin/env python3
"""M2-S4C: integrate S4B assets with S2C user-scoped inactive installer.

Public CLI is READ-ONLY: native LocalAppData user installation preview ONLY.
Synthetic installation support is constrained to disposable OS Temp roots and
requires an injected ACL simulation: it must never be used as a real installer.
No DPAPI reads, network calls, system services, or task registration.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

S4B_SHA256 = '0eb4fd4e9082e63923fd51dcc7183acb5cdfff13df587c67edb0c8b9772aee6d'
BUNDLE_SHA256 = 'b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d'
DASHBOARD_SHA256 = '16cec6731032a444bf944e165b22fdc179cca6ae6d48252520b77a51be6d8a57'
ISOLATION_SHA256 = 'be3cd0e4bb066ca76f00fc6948ca44bcf0834cce5995eb46ff6c2909c49c6d7f'
SOURCE_COMMIT = '8df66f772d5b15464290b7040621e9b03635d49e'
ISOLATION_MANIFEST = 'runtime-isolation-manifest.json'


class UserIntegrationRefused(ValueError):
    pass


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(obj: dict) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


def reviewed_modules():
    """Load S4B by exact source SHA, then its S2C/S2B/S4A pinned dependencies."""
    module_file = Path(__file__).with_name('onyx_v100_windows_integrated_install.py')
    if not module_file.is_file() or module_file.is_symlink() or sha(module_file.read_bytes()) != S4B_SHA256:
        raise UserIntegrationRefused('M2-S4B source hash does not match approved development checkpoint')
    spec = importlib.util.spec_from_file_location('onyx_s4c_reviewed_s4b', module_file)
    if spec is None or spec.loader is None:
        raise UserIntegrationRefused('cannot load approved M2-S4B source')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    base, user, isolation = module.dependencies()
    if (module.BUNDLE_SHA256 != BUNDLE_SHA256 or module.DASHBOARD_SHA256 != DASHBOARD_SHA256 or
            module.ISOLATION_SHA256 != ISOLATION_SHA256 or
            module.SOURCE_COMMIT != SOURCE_COMMIT):
        raise UserIntegrationRefused('approved integrated source identities changed')
    return module, base, user, isolation


def expected_user_install(bundle: Path, dashboard: Path, settings: dict, *, loaded=None):
    """Produce the exact 16 non-receipt bytes for a future inactive user install."""
    s4b, base, user, isolation = loaded or reviewed_modules()
    payload, dash, manifest, cfg = s4b.integrated_payload(
        bundle, dashboard, settings, loaded=(base, user, isolation))
    if ISOLATION_MANIFEST not in payload or len(payload) != 13:
        raise UserIntegrationRefused('integrated payload inventory mismatch')
    expected = user._expected_payload(
        {k: v for k, v in payload.items() if k != ISOLATION_MANIFEST}, dash, manifest, cfg)
    expected[ISOLATION_MANIFEST] = payload[ISOLATION_MANIFEST]
    if (len(expected) != 16 or sha(expected[ISOLATION_MANIFEST]) != ISOLATION_SHA256 or
            len(set(expected)) != 16 or
            expected['windows/gateway/gateway-dashboard.html'] !=
            expected['windows/gateway/gateway-dashboard-v100.html']):
        raise UserIntegrationRefused('integrated user payload differs from approved 17-file format')
    return expected, cfg


def preview_user(bundle: Path, dashboard: Path, target: Path, settings: dict, *, root=None) -> dict:
    """Read-only target and payload inspection. Never invoke a publisher."""
    s4b, base, user, isolation = reviewed_modules()
    if root is None:
        root = user.native_user_root()
    # Existing S2C no-overwrite and redirection checks.
    user.validate_target(target, root=root)
    expected, cfg = expected_user_install(bundle, dashboard, settings,
                                          loaded=(s4b, base, user, isolation))
    return {
        'schema_version': 1, 'operation': 'WINDOWS_V100_INTEGRATED_USER_PREVIEW_S4C',
        'source_commit': SOURCE_COMMIT, 'target': str(target), 'file_count_if_installed': len(expected) + 1,
        'bundle_sha256': BUNDLE_SHA256, 'dashboard_sha256': DASHBOARD_SHA256,
        'isolation_manifest_sha256': ISOLATION_SHA256,
        'collector_source': cfg['collector']['source'], 'gateway_port': cfg['gateway']['port'],
        'installation_performed': False, 'acl_changed': False, 'acl_verified': False,
        'credential_read': False, 'credential_enrolled': False, 'service_or_task_changes': False,
        'activation_performed': False, 'network_probe_performed': False,
        'native_installation_approved': False, 'requires_separate_authorization': True,
    }


def synthetic_root_guard(root: Path) -> None:
    """Only disposable immediate OS Temp children named for S4C test fixtures."""
    temp = Path(tempfile.gettempdir())
    if (not root.is_absolute() or '..' in root.parts or
            root.name.startswith('OnyxV100-S4C-TestRoot-') is False or
            not root.is_dir() or root.is_symlink() or
            root.parent != temp or root.parent.is_symlink() or
            root.resolve(strict=True).parent != temp.resolve(strict=True)):
        raise UserIntegrationRefused('synthetic installs require new OS Temp S4C test-root fixture')


def synthetic_publish(bundle: Path, dashboard: Path, root: Path, target: Path,
                      settings: dict, *, simulated_acl) -> dict:
    """TEST-ONLY user.install_inactive exercise; never a native ACL operation."""
    if not callable(simulated_acl):
        raise UserIntegrationRefused('synthetic ACL callback required; no real ACL helper is used')
    synthetic_root_guard(root)
    s4b, base, user, isolation = reviewed_modules()
    user.validate_target(target, root=root)
    expected, cfg = expected_user_install(bundle, dashboard, settings,
                                          loaded=(s4b, base, user, isolation))
    result = user.install_inactive(target, expected, root=root,
                                   native_check=lambda: True, acl_guard=simulated_acl)
    verified = user.verify_inactive(target, expected, root=root)
    receipt = json.loads((target / user.RECEIPT_NAME).read_bytes())
    rows = {item['path']: item for item in receipt['installed_files']}
    if (result['file_count'] != 17 or verified['file_count'] != 17 or
            len(rows) != 16 or
            rows[ISOLATION_MANIFEST]['sha256'] != ISOLATION_SHA256 or
            receipt.get('credential_enrolled') is not False or
            receipt.get('activation_performed') is not False or
            receipt.get('service_or_task_changes') is not False):
        raise UserIntegrationRefused('synthetic installed runtime verification failed')
    return {'operation': 'WINDOWS_V100_SYNTHETIC_USER_INSTALL_VERIFIED',
            'file_count': 17, 'synthetic_acl_only': True,
            'native_acl_verified': False, 'credential_enrolled': False,
            'activation_performed': False, 'production_modified': False}


def cli(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', required=True, type=Path)
    p.add_argument('--dashboard', required=True, type=Path)
    p.add_argument('--target', required=True, type=Path)
    p.add_argument('--receiver-host', required=True)
    p.add_argument('--receiver-port', type=int, default=8765)
    p.add_argument('--source', required=True)
    p.add_argument('--network-adapter', required=True)
    p.add_argument('--usb-adapter', required=True)
    p.add_argument('--gateway-port', required=True, type=int)
    p.add_argument('--interval-seconds', type=int, default=30)
    p.add_argument('--mode', choices=('preview-user',), default='preview-user')
    args = p.parse_args(argv)
    try:
        if not args.bundle.is_absolute() or not args.dashboard.is_absolute() or not args.target.is_absolute():
            raise UserIntegrationRefused('absolute reviewed input paths required')
        settings = dict(receiver_host=args.receiver_host, receiver_port=args.receiver_port,
                        source=args.source, network_adapter=args.network_adapter,
                        usb_adapter=args.usb_adapter, gateway_port=args.gateway_port,
                        interval=args.interval_seconds)
        report = preview_user(args.bundle, args.dashboard, args.target, settings)
        print(canonical(report).decode('ascii').strip())
        return 0
    except (UserIntegrationRefused, ValueError, OSError, KeyError, RuntimeError, TypeError) as e:
        print('STOP: ' + str(e), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(cli())
