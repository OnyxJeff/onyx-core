#!/usr/bin/env python3
"""ONYX CORE v1.0.0 M2-S2B: verified, INACTIVE Windows runtime sandbox install.

Preview is default. Installation is limited to a NEW direct child of OS TEMP,
with two explicit approval flags and native Windows. No credentials, network,
tasks, registry, firewall, system installation, or live runtime activation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
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
DASHBOARD_SHA256 = '16cec6731032a444bf944e165b22fdc179cca6ae6d48252520b77a51be6d8a57'
RESERVED_GATEWAY_PORTS = {18766, 18767, 18768, 18769}
MANIFEST_NAME = 'bundle-manifest.json'
DASHBOARD_PATH = 'windows/gateway/gateway-dashboard.html'
DASHBOARD_VERSIONED_PATH = 'windows/gateway/gateway-dashboard-v100.html'
CONFIG_PATH = 'config/windows.config.json'
RECEIPT_PATH = 'installation-receipt.json'
TARGET_NAME = re.compile(r'OnyxV100-Windows-[A-Za-z0-9_-]{1,48}\Z')


class InstallRefused(ValueError):
    pass


def canonical_json(data):
    return (json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(',', ':')) + '\n').encode('ascii')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def reject_redirects(path):
    current = path
    while True:
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise InstallRefused('redirected installation path refused')
        if current.parent == current:
            break
        current = current.parent


def validate_target(target):
    if not target.is_absolute() or '..' in target.parts or not TARGET_NAME.fullmatch(target.name):
        raise InstallRefused('target must be a new OnyxV100-Windows-* direct child of OS temp')
    reject_redirects(target)
    parent = Path(tempfile.gettempdir()).resolve(strict=True)
    if target.parent.resolve(strict=True) != parent:
        raise InstallRefused('installation target is not a direct child of OS temp')
    if target.exists() or target.is_symlink():
        raise InstallRefused('installation target already exists; refusing overwrite')
    return target


def read_regular(path, *, maximum):
    reject_redirects(path)
    if not path.is_file() or path.stat().st_size > maximum:
        raise InstallRefused('expected regular bounded input file')
    return path.read_bytes()


def inspect_inputs(bundle_path, dashboard_path):
    bundle = read_regular(bundle_path, maximum=8_000_000)
    if sha256(bundle) != BUNDLE_SHA256:
        raise InstallRefused('core bundle SHA256 does not match approved M2-S1 candidate')
    dashboard = read_regular(dashboard_path, maximum=150_000)
    if sha256(dashboard) != DASHBOARD_SHA256:
        raise InstallRefused('versioned dashboard SHA256 does not match approved M2-S2A')
    if b'gatewayMode' not in dashboard or b'ONYX CORE' not in dashboard:
        raise InstallRefused('versioned dashboard does not contain required gateway UI')

    try:
        with zipfile.ZipFile(bundle_path, 'r') as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)) or names.count(MANIFEST_NAME) != 1 or len(names) != 21:
                raise InstallRefused('duplicate or unexpected core bundle members')
            if archive.testzip() is not None:
                raise InstallRefused('corrupt ZIP member')
            raw_manifest = archive.read(MANIFEST_NAME)
            manifest = json.loads(raw_manifest)
            if (manifest.get('schema_version') != 1 or
                    manifest.get('release_version') != '1.0.0' or
                    manifest.get('source_commit') != SOURCE_COMMIT or
                    manifest.get('package_kind') != 'onyxcore-v100-core-runtime-candidate' or
                    manifest.get('file_count') != 20 or
                    manifest.get('activation_performed') is not False or
                    manifest.get('credential_files_included') is not False):
                raise InstallRefused('unexpected core bundle manifest identity')
            rows = manifest.get('files')
            if not isinstance(rows, list) or len(rows) != 20:
                raise InstallRefused('incorrect manifest file inventory')
            declared = [r.get('path') for r in rows]
            if len(set(declared)) != 20 or set(names) != set(declared) | {MANIFEST_NAME}:
                raise InstallRefused('manifest/ZIP member mismatch')
            roles = manifest.get('roles')
            if not isinstance(roles, dict) or set(roles) != {'common', 'windows', 'pi-armv6'}:
                raise InstallRefused('invalid platform role inventory')
            selected = roles['common'] + roles['windows']
            if (len(selected) != 12 or len(set(selected)) != 12 or
                    set(selected) & set(roles['pi-armv6']) or
                    set(selected) | set(roles['pi-armv6']) != set(declared)):
                raise InstallRefused('inconsistent Windows/common bundle roles')
            payload = {}
            for row in rows:
                path = row['path']
                if (not isinstance(path, str) or path.startswith('/') or '\\' in path or
                        ':' in path or '..' in path.split('/') or path.endswith('/') or
                        any(not component or component == '.' for component in path.split('/'))):
                    raise InstallRefused('unsafe ZIP path')
                entry = archive.getinfo(path)
                if (entry.date_time != (1980, 1, 1, 0, 0, 0) or entry.extra or entry.comment or
                        entry.create_system != 3 or stat.S_IFMT(entry.external_attr >> 16) != stat.S_IFREG):
                    raise InstallRefused('unexpected ZIP metadata or nonregular file')
                data = archive.read(path)
                if (row['sha256'] != sha256(data) or row['size'] != len(data) or
                        row.get('mode') != '0644' or len(data) > 400_000):
                    raise InstallRefused('bundle manifest digest/size/mode mismatch')
                if path in selected:
                    payload[path] = data
            if len(payload) != 12 or DASHBOARD_PATH not in payload:
                raise InstallRefused('Windows runtime payload incomplete')
    except (OSError, zipfile.BadZipFile, KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, InstallRefused):
            raise
        raise InstallRefused('cannot verify approved core runtime archive') from exc
    return payload, dashboard, raw_manifest


def validate_configuration(bundle_path, *, receiver_host, receiver_port, source,
                           network_adapter, usb_adapter, gateway_port, interval):
    # Read the exact validator from the already SHA256-pinned ZIP. ZIP imports do
    # not extract code, create pycache, or require a working Git checkout.
    try:
        importer = zipimport.zipimporter(str(bundle_path) + '/tools/installation/common')
        code = importer.get_code('onyx_v100_config')
        if code is None:
            raise InstallRefused('bundle configuration validator unavailable')
        module = types.ModuleType('onyx_v100_config')
        exec(code, module.__dict__)
        cfg = {
            'schema_version': 1, 'platform': 'windows',
            'receiver': {'host': receiver_host, 'port': receiver_port},
            'collector': {'source': source, 'network_adapter': network_adapter,
                          'interval_seconds': interval},
            'usb': {'adapter_name': usb_adapter},
            'gateway': {'listen_host': '127.0.0.1', 'port': gateway_port},
            'cpu_temperature': {'enabled': False},
        }
        module.validate_config(cfg, 'windows')
    except (OSError, ValueError, TypeError, ImportError, KeyError, zipimport.ZipImportError) as exc:
        raise InstallRefused('invalid Windows configuration inputs') from exc
    if gateway_port in RESERVED_GATEWAY_PORTS:
        raise InstallRefused('gateway port reserved for an existing ONYX CORE runtime')
    return cfg


def prepare_plan(bundle_path, dashboard_path, target, settings):
    validate_target(target)
    payload, dashboard, manifest = inspect_inputs(bundle_path, dashboard_path)
    cfg = validate_configuration(bundle_path, **settings)
    # Everything needed is in checked source, no receiver contact or DPAPI.
    return {
        'schema_version': 1,
        'operation': 'WINDOWS_INACTIVE_INSTALL_PREVIEW',
        'version': '1.0.0', 'source_commit': SOURCE_COMMIT,
        'bundle_sha256': BUNDLE_SHA256, 'dashboard_sha256': DASHBOARD_SHA256,
        'target': str(target), 'receiver_host': cfg['receiver']['host'],
        'receiver_port': cfg['receiver']['port'],
        'collector_source': cfg['collector']['source'],
        'gateway_port': cfg['gateway']['port'],
        'selected_runtime_files': len(payload),
        'network_scope_verified': False, 'port_available_verified': False,
        'credential_contents_read': False, 'task_or_service_changes': False,
        'activation_performed': False, 'installation_performed': False,
    }, payload, dashboard, manifest, cfg


def write_inactive_install(target, payload, dashboard, manifest, cfg, *, native_check=None):
    if native_check is None:
        native_check = lambda: sys.platform == 'win32' and sys.version_info[:2] == (3, 13)
    if not native_check():
        raise InstallRefused('native Windows with Python 3.13 required for inactive install')
    validate_target(target)
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    staging = Path(tempfile.mkdtemp(prefix='.OnyxV100-Windows-staging-', dir=str(temp_root)))
    try:
        installed = dict(payload)
        installed[DASHBOARD_PATH] = dashboard
        installed[DASHBOARD_VERSIONED_PATH] = dashboard
        installed['bundle-manifest.json'] = manifest
        installed[CONFIG_PATH] = canonical_json(cfg)
        digest_rows = []
        for name, data in sorted(installed.items()):
            if name.startswith('/') or '..' in name.split('/') or '\\' in name or ':' in name:
                raise InstallRefused('unsafe staged output path')
            out = staging.joinpath(*name.split('/'))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            digest_rows.append({'path': name, 'size': len(data), 'sha256': sha256(data)})
        receipt = {
            'schema_version': 1, 'operation': 'INACTIVE_WINDOWS_SANDBOX_INSTALL',
            'release_version': '1.0.0', 'source_commit': SOURCE_COMMIT,
            'bundle_sha256': BUNDLE_SHA256, 'dashboard_sha256': DASHBOARD_SHA256,
            'installed_files': digest_rows,
            'credential_enrolled': False, 'task_or_service_changes': False,
            'activation_performed': False, 'network_scope_verified': False,
        }
        (staging / RECEIPT_PATH).write_bytes(canonical_json(receipt))
        # Atomic publish of one new target. Never remove/replace a pre-existing tree.
        validate_target(target)
        staging.rename(target)
        staging = None
        return {'schema_version': 1, 'operation': 'WINDOWS_INACTIVE_SANDBOX_INSTALLED',
                'target': str(target), 'file_count': len(digest_rows) + 1,
                'source_commit': SOURCE_COMMIT, 'bundle_sha256': BUNDLE_SHA256,
                'dashboard_sha256': DASHBOARD_SHA256, 'task_or_service_changes': False,
                'activation_performed': False, 'credential_enrolled': False}
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def verify_inactive_install(target, payload, dashboard, manifest, cfg):
    reject_redirects(target)
    receipt_file = target / RECEIPT_PATH
    if not target.is_dir() or not receipt_file.is_file():
        raise InstallRefused('inactive install receipt missing')
    receipt = json.loads(read_regular(receipt_file, maximum=100_000))
    if (receipt.get('source_commit') != SOURCE_COMMIT or
            receipt.get('bundle_sha256') != BUNDLE_SHA256 or
            receipt.get('dashboard_sha256') != DASHBOARD_SHA256 or
            receipt.get('operation') != 'INACTIVE_WINDOWS_SANDBOX_INSTALL'):
        raise InstallRefused('receipt provenance mismatch')
    expected = dict(payload)
    expected[DASHBOARD_PATH] = dashboard
    expected[DASHBOARD_VERSIONED_PATH] = dashboard
    expected[MANIFEST_NAME] = manifest
    expected[CONFIG_PATH] = canonical_json(cfg)
    rows = receipt.get('installed_files')
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise InstallRefused('receipt inventory incomplete')
    names = [r.get('path') for r in rows]
    if len(set(names)) != len(expected) or set(names) != set(expected):
        raise InstallRefused('incorrect receipt paths')
    names.append(RECEIPT_PATH)
    current = set()
    for path in target.rglob('*'):
        reject_redirects(path)
        if path.is_file():
            current.add(path.relative_to(target).as_posix())
    if current != set(names):
        raise InstallRefused('installed filesystem differs from receipt')
    for row in rows:
        item = target.joinpath(*row['path'].split('/'))
        data = read_regular(item, maximum=500_000)
        if (sha256(data) != row.get('sha256') or len(data) != row.get('size') or
                data != expected[row['path']]):
            raise InstallRefused('installed file differs from approved source')
    if (sha256((target / DASHBOARD_PATH).read_bytes()) != DASHBOARD_SHA256 or
            sha256((target / DASHBOARD_VERSIONED_PATH).read_bytes()) != DASHBOARD_SHA256):
        raise InstallRefused('versioned dashboard overlay mismatch')
    return {'schema_version': 1, 'operation': 'WINDOWS_INACTIVE_SANDBOX_VERIFIED',
            'file_count': len(names), 'source_commit': SOURCE_COMMIT,
            'activation_performed': False, 'credential_enrolled': False}


def cli(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', required=True, type=Path)
    p.add_argument('--dashboard', required=True, type=Path)
    p.add_argument('--target', required=True, type=Path)
    p.add_argument('--receiver-host', required=True)
    p.add_argument('--receiver-port', type=int, default=8765)
    p.add_argument('--source', required=True)
    p.add_argument('--network-adapter', required=True)
    p.add_argument('--usb-adapter', required=True)
    p.add_argument('--gateway-port', type=int, required=True)
    p.add_argument('--interval-seconds', type=int, default=30)
    p.add_argument('--install', action='store_true')
    p.add_argument('--approve-inactive', action='store_true')
    args = p.parse_args(argv)
    try:
        if args.approve_inactive and not args.install:
            raise InstallRefused('approval without --install refused')
        if args.install and not args.approve_inactive:
            raise InstallRefused('install requires --install and --approve-inactive')
        if not args.bundle.is_absolute() or not args.dashboard.is_absolute():
            raise InstallRefused('absolute input file paths required')
        settings = {'receiver_host': args.receiver_host, 'receiver_port': args.receiver_port,
                    'source': args.source, 'network_adapter': args.network_adapter,
                    'usb_adapter': args.usb_adapter, 'gateway_port': args.gateway_port,
                    'interval': args.interval_seconds}
        plan, payload, dashboard, manifest, cfg = prepare_plan(
            args.bundle, args.dashboard, args.target, settings)
        if not args.install:
            print(canonical_json(plan).decode('ascii').strip())
            return 0
        result = write_inactive_install(args.target, payload, dashboard, manifest, cfg)
        verify_inactive_install(args.target, payload, dashboard, manifest, cfg)
        print(canonical_json(result).decode('ascii').strip())
        return 0
    except (InstallRefused, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(cli())
