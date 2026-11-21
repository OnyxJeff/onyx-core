#!/usr/bin/env python3
"""M2-S4B: offline, versioned Windows runtime integration.

Only a new OS Temp sandbox may be installed. LocalAppData is preview-only.
The original bundle, production runtime, credentials and Scheduled Tasks are
never altered. All imported installer modules have pinned SHA256 fingerprints.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

BUNDLE_SHA256 = 'b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d'
DASHBOARD_SHA256 = '16cec6731032a444bf944e165b22fdc179cca6ae6d48252520b77a51be6d8a57'
ISOLATION_SHA256 = 'be3cd0e4bb066ca76f00fc6948ca44bcf0834cce5995eb46ff6c2909c49c6d7f'
SOURCE_COMMIT = '8df66f772d5b15464290b7040621e9b03635d49e'
ISOLATION_MANIFEST = 'runtime-isolation-manifest.json'
DEPENDENCIES = {
    'onyx_v100_windows_install.py': 'a6b29d1706f8a1be281daf59c124537f2d97168770e4169854f8793760513e14',
    'onyx_v100_windows_user_install.py': 'd656732795a535c2946390f81e52899f6741f5e4a5c18431f6797c146b8e1a0c',
    'onyx_v100_windows_isolation.py': 'e56daef4fe4c477f930371049278ae579eaca47efa6c98be924e539353c4e0da',
    'Set-OnyxV100UserInstallAcl.ps1': '7e8b1f0b70a99684cfeaab3ad59d369dc1df6b50e6c4e7446eae1789bee5d5d5',
}
ISOLATED_PATHS = (
    'windows/collector/Send-OnyxTelemetry-v100.ps1',
    'windows/gateway/Get-OnyxGatewayToken.ps1',
    'tools/installation/windows/Invoke-OnyxV100WindowsRuntime.ps1',
)


class IntegrationRefused(ValueError):
    pass


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(obj: dict) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


def dependencies() -> tuple[object, object, object]:
    root = Path(__file__).parent
    loaded = {}
    for filename, digest in DEPENDENCIES.items():
        file = root / filename
        if not file.is_file() or file.is_symlink() or sha(file.read_bytes()) != digest:
            raise IntegrationRefused('approved installer dependency missing or changed: ' + filename)
        if filename.endswith('.py'):
            spec = importlib.util.spec_from_file_location('onyx_s4b_' + filename.removesuffix('.py'), file)
            if spec is None or spec.loader is None:
                raise IntegrationRefused('cannot load approved installer module: ' + filename)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            loaded[filename] = module
    return (loaded['onyx_v100_windows_install.py'],
            loaded['onyx_v100_windows_user_install.py'],
            loaded['onyx_v100_windows_isolation.py'])


def integrated_payload(bundle: Path, dashboard: Path, settings: dict, *, loaded=None):
    """Get exact approved files. No file writes, credentials, or processes."""
    base, _user, isolated = loaded if loaded is not None else dependencies()
    payload, dash_bytes, core_manifest = base.inspect_inputs(bundle, dashboard)
    cfg = base.validate_configuration(bundle, **settings)
    derived, isolation_manifest = isolated.expected(bundle)
    if (sha(canonical(isolation_manifest)) != ISOLATION_SHA256 or
            isolated.BUNDLE_SHA256 != BUNDLE_SHA256 or
            base.BUNDLE_SHA256 != BUNDLE_SHA256 or
            base.DASHBOARD_SHA256 != DASHBOARD_SHA256 or
            isolation_manifest.get('credential_enrolled') is not False or
            isolation_manifest.get('installation_performed') is not False):
        raise IntegrationRefused('approved runtime isolation provenance does not match')
    if set(derived) != set(ISOLATED_PATHS) or len(payload) != 12:
        raise IntegrationRefused('approved integrated runtime source inventory changed')
    original_payload = dict(payload)
    for name in ISOLATED_PATHS:
        if name not in payload or derived[name] == payload[name]:
            raise IntegrationRefused('isolated runtime asset missing or unchanged: ' + name)
        payload[name] = derived[name]
    if (b"with_name('Get-OnyxGatewayToken.ps1')" not in payload['windows/gateway/OnyxGateway_v100.py'] or
            b"'OnyxCore-v100\\collector-token.dpapi'" not in payload['windows/gateway/Get-OnyxGatewayToken.ps1'] or
            b"'OnyxCore-v100\\collector-token.dpapi'" not in payload['tools/installation/windows/Invoke-OnyxV100WindowsRuntime.ps1'] or
            b"'Local\\OnyxCoreV100Collector'" not in payload['windows/collector/Send-OnyxTelemetry-v100.ps1']):
        raise IntegrationRefused('gateway/collector isolated runtime contract missing')
    for name in ISOLATED_PATHS:
        if (b'OnyxCore\\collector-token.dpapi' in payload[name] or
                b"'Local\\OnyxCoreCollector'" in payload[name]):
            raise IntegrationRefused('legacy credential or mutex fallback detected')
    if sha(dash_bytes) != DASHBOARD_SHA256:
        raise IntegrationRefused('approved versioned dashboard changed')
    payload[ISOLATION_MANIFEST] = canonical(isolation_manifest)
    if len(payload) != 13 or original_payload['windows/gateway/gateway-dashboard.html'] == dash_bytes:
        raise IntegrationRefused('overlay dashboard and isolated assets not distinct from old bundle')
    return payload, dash_bytes, core_manifest, cfg


def user_preview(bundle: Path, dashboard: Path, target: Path, settings: dict, *, root: Path | None = None) -> dict:
    """No filesystem writes, even when a real LocalAppData root is used."""
    base, user, isolated = dependencies()
    if root is None:
        root = user.native_user_root()
    # Calls the existing S2C target/identity gate, but never its install function.
    user.validate_target(target, root=root)
    payload, dash, manifest, cfg = integrated_payload(bundle, dashboard, settings,
                                                      loaded=(base, user, isolated))
    expected = user._expected_payload({k: v for k, v in payload.items() if k != ISOLATION_MANIFEST},
                                      dash, manifest, cfg)
    expected[ISOLATION_MANIFEST] = payload[ISOLATION_MANIFEST]
    if len(expected) != 16:
        raise IntegrationRefused('integrated user-scope expected inventory incomplete')
    return {
        'schema_version': 1, 'operation': 'WINDOWS_V100_INTEGRATED_USER_PREVIEW',
        'target': str(target), 'source_commit': SOURCE_COMMIT,
        'bundle_sha256': BUNDLE_SHA256, 'dashboard_sha256': DASHBOARD_SHA256,
        'isolation_manifest_sha256': ISOLATION_SHA256,
        'file_count_if_installed': len(expected) + 1,
        'gateway_port': cfg['gateway']['port'],
        'installation_performed': False, 'credential_enrolled': False,
        'acl_changed': False, 'activation_performed': False,
        'network_probe_performed': False, 'runtime_process_started': False,
        'task_or_service_changes': False,
        'requires_separate_user_install_authorization': True,
    }


def sandbox_preview(bundle: Path, dashboard: Path, target: Path, settings: dict) -> dict:
    base, user, isolated = dependencies()
    base.validate_target(target)
    payload, dash, manifest, cfg = integrated_payload(bundle, dashboard, settings,
                                                      loaded=(base, user, isolated))
    return {
        'schema_version': 1, 'operation': 'WINDOWS_V100_INTEGRATED_SANDBOX_PREVIEW',
        'target': str(target), 'source_commit': SOURCE_COMMIT,
        'bundle_sha256': BUNDLE_SHA256, 'dashboard_sha256': DASHBOARD_SHA256,
        'isolation_manifest_sha256': ISOLATION_SHA256,
        'file_count_if_installed': len(payload) + 3 + 1,
        'gateway_port': cfg['gateway']['port'],
        'installation_performed': False, 'credential_enrolled': False,
        'activation_performed': False, 'runtime_process_started': False,
        'task_or_service_changes': False,
    }


def install_sandbox(bundle: Path, dashboard: Path, target: Path, settings: dict,
                    *, native_check=None) -> dict:
    base, user, isolated = dependencies()
    base.validate_target(target)
    payload, dash, manifest, cfg = integrated_payload(bundle, dashboard, settings,
                                                      loaded=(base, user, isolated))
    report = base.write_inactive_install(target, payload, dash, manifest, cfg,
                                         native_check=native_check)
    verified = base.verify_inactive_install(target, payload, dash, manifest, cfg)
    receipt = json.loads((target / base.RECEIPT_PATH).read_bytes())
    expected_rows = {row['path']: row for row in receipt['installed_files']}
    if (sha((target / ISOLATION_MANIFEST).read_bytes()) != ISOLATION_SHA256 or
            expected_rows[ISOLATION_MANIFEST]['sha256'] != ISOLATION_SHA256 or
            verified['file_count'] != report['file_count'] or
            report['file_count'] != 17 or
            receipt['credential_enrolled'] is not False or
            receipt['task_or_service_changes'] is not False or
            receipt['activation_performed'] is not False):
        raise IntegrationRefused('integrated sandbox receipt or activation boundary violated')
    return {'schema_version': 1, 'operation': 'WINDOWS_V100_INTEGRATED_SANDBOX_INSTALLED',
            'target': str(target), 'file_count': report['file_count'],
            'source_commit': SOURCE_COMMIT, 'isolation_manifest_sha256': ISOLATION_SHA256,
            'credential_enrolled': False, 'activation_performed': False,
            'task_or_service_changes': False}


def cli(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--dashboard', type=Path, required=True)
    p.add_argument('--target', type=Path, required=True)
    p.add_argument('--receiver-host', required=True)
    p.add_argument('--receiver-port', type=int, default=8765)
    p.add_argument('--source', required=True)
    p.add_argument('--network-adapter', required=True)
    p.add_argument('--usb-adapter', required=True)
    p.add_argument('--gateway-port', type=int, required=True)
    p.add_argument('--interval-seconds', type=int, default=30)
    p.add_argument('--mode', choices=('preview-sandbox', 'install-sandbox', 'preview-user'),
                   default='preview-sandbox')
    p.add_argument('--approve-inactive-sandbox', action='store_true')
    args = p.parse_args(argv)
    try:
        if not args.bundle.is_absolute() or not args.dashboard.is_absolute():
            raise IntegrationRefused('absolute reviewed input paths required')
        if args.approve_inactive_sandbox != (args.mode == 'install-sandbox'):
            raise IntegrationRefused('sandbox publication requires explicit mode and approval flag')
        settings = dict(receiver_host=args.receiver_host, receiver_port=args.receiver_port,
                        source=args.source, network_adapter=args.network_adapter,
                        usb_adapter=args.usb_adapter, gateway_port=args.gateway_port,
                        interval=args.interval_seconds)
        if args.mode == 'preview-user':
            result = user_preview(args.bundle, args.dashboard, args.target, settings)
        elif args.mode == 'install-sandbox':
            result = install_sandbox(args.bundle, args.dashboard, args.target, settings)
        else:
            result = sandbox_preview(args.bundle, args.dashboard, args.target, settings)
        print(canonical(result).decode('ascii').strip())
        return 0
    except (IntegrationRefused, ValueError, OSError, KeyError, TypeError,
            json.JSONDecodeError, RuntimeError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(cli())
