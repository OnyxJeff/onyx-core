#!/usr/bin/env python3
"""ONYX CORE v1.0.0 M2-S5D: read-only persistent Windows install preflight.

There is NO persistent installation command in this milestone. The operator
must authorize a separate, future one-shot writer before any user-profile
filesystem mutation. This module never creates a directory, reads credentials,
or starts processes except for importing reviewed, pinned Python source.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

S5C_SHA256 = 'e050822e0c51fa99d9c358efb7ea2abf501fd25b46a55768e39ad65ebcff52e6'
M2_HEAD = '00c6ba630a18b054308bb7119b610602790e44be'
BUNDLE_SHA256 = 'b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d'
DASHBOARD_SHA256 = '16cec6731032a444bf944e165b22fdc179cca6ae6d48252520b77a51be6d8a57'
TARGET_NAME = 'OnyxCore-v100-Inactive-Stable100'
FILE_COUNT = 17


class PreflightRefused(ValueError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: dict) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(',', ':')) + '\n').encode('ascii')


def reviewed_s5c():
    path = Path(__file__).with_name('onyx_v100_windows_safe_user_publish.py')
    if not path.is_file() or path.is_symlink() or sha(path.read_bytes()) != S5C_SHA256:
        raise PreflightRefused('accepted S5C publisher source SHA256 mismatch')
    spec = importlib.util.spec_from_file_location('onyx_v100_s5d_pinned_s5c', path)
    if spec is None or spec.loader is None:
        raise PreflightRefused('cannot import reviewed S5C publisher')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.M2_HEAD != M2_HEAD or module.BUNDLE_SHA != BUNDLE_SHA256 or module.DASHBOARD_SHA != DASHBOARD_SHA256:
        raise PreflightRefused('reviewed S5C source identity mismatch')
    module.reviewed()  # verify S4C/R3/S5B pinned inputs
    module.helper_path()  # verify DACL-only helper; never execute it
    return module


def target_report(root: Path, expected: dict, cfg: dict, *, user) -> dict:
    """Purely read-only path and payload gate; root is trusted by its caller."""
    target = root / TARGET_NAME
    if target.name != TARGET_NAME or target.parent != root:
        raise PreflightRefused('unexpected persistent target')
    user.validate_target(target, root=root)  # no redirects or existing target
    if len(expected) != FILE_COUNT - 1 or len(set(expected)) != FILE_COUNT - 1:
        raise PreflightRefused('integrated payload inventory is incomplete')
    entries = []
    for name, data in sorted(expected.items()):
        if (not isinstance(name, str) or not name or name.startswith('/') or '\\' in name or ':' in name or
                any(part in ('', '.', '..') for part in name.split('/')) or not isinstance(data, bytes)):
            raise PreflightRefused('invalid integrated payload path')
        entries.append({'path': name, 'size': len(data), 'sha256': sha(data)})
    if 'windows/gateway/gateway-dashboard-v100.html' not in expected or 'runtime-isolation-manifest.json' not in expected:
        raise PreflightRefused('approved dashboard or isolation manifest missing')
    if 'config/windows.config.json' not in expected:
        raise PreflightRefused('required host config missing')
    report = {
        'schema_version': 1,
        'operation': 'M2_S5D_USER_INSTALL_PREFLIGHT_ONLY',
        'm2_commit': M2_HEAD,
        's5c_publisher_sha256': S5C_SHA256,
        'bundle_sha256': BUNDLE_SHA256,
        'dashboard_sha256': DASHBOARD_SHA256,
        'target': str(target),
        'file_count_if_installed': FILE_COUNT,
        'files': entries,
        'receiver_host': cfg['receiver']['host'],
        'gateway_port': cfg['gateway']['port'],
        'collector_source': cfg['collector']['source'],
        'credential_enrolled': False,
        'credentials_read': False,
        'task_or_service_changed': False,
        'native_acl_changed': False,
        'publication_performed': False,
        'persistent_installation_authorized': False,
        'requires_separate_one_shot_authorization': True,
        'pending_native_user_publication_validation': True,
    }
    report['plan_sha256'] = sha(canonical(report))
    return report


def preview(bundle: Path, dashboard: Path, settings: dict):
    s5c = reviewed_s5c()
    s5c.native_guard()  # Windows 11 user, non-elevated Python 3.13
    s4c, r3, s5b = s5c.reviewed()
    user = s4c.reviewed_modules()[2]
    root = user.native_user_root()  # native Windows Known Folder; no supplied root
    expected, cfg = s5c.expected_install(bundle, dashboard, settings, s4c=s4c)
    return target_report(root, expected, cfg, user=user)


def cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--dashboard', type=Path, required=True)
    parser.add_argument('--receiver-host', required=True)
    parser.add_argument('--receiver-port', type=int, default=8765)
    parser.add_argument('--source', required=True)
    parser.add_argument('--network-adapter', required=True)
    parser.add_argument('--usb-adapter', required=True)
    parser.add_argument('--gateway-port', type=int, required=True)
    parser.add_argument('--interval-seconds', type=int, default=30)
    parser.add_argument('--mode', choices=['preview'], default='preview')
    args = parser.parse_args(argv)
    try:
        if args.mode != 'preview':
            raise PreflightRefused('only read-only preview is implemented')
        settings = dict(receiver_host=args.receiver_host, receiver_port=args.receiver_port,
                        source=args.source, network_adapter=args.network_adapter,
                        usb_adapter=args.usb_adapter, gateway_port=args.gateway_port,
                        interval=args.interval_seconds)
        result = preview(args.bundle, args.dashboard, settings)
        print(canonical(result).decode('ascii').strip())
        return 0
    except (PreflightRefused, ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(cli())
