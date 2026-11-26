#!/usr/bin/env python3
"""Offline M2-S4B acceptance; no user-profile installs, networks or live services."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest import mock

TOOL = Path(__file__).resolve().parents[2] / 'tools/installation/windows/onyx_v100_windows_integrated_install.py'
BUNDLE = Path(os.environ.get('ONYX_V100_BUNDLE', ''))
DASHBOARD = Path(os.environ.get('ONYX_V100_DASHBOARD', ''))
spec = importlib.util.spec_from_file_location('onyx_s4b_integrated', TOOL)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
SETTINGS = {'receiver_host': 'svr-onyxcore.local', 'receiver_port': 8765,
            'source': 'SQUALL', 'network_adapter': 'Ethernet',
            'usb_adapter': 'Ethernet 3', 'gateway_port': 18976, 'interval': 30}


class IntegratedWindowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BUNDLE.is_file() or not DASHBOARD.is_file():
            raise RuntimeError('set ONYX_V100_BUNDLE and ONYX_V100_DASHBOARD to verified sources')
        cls.base, cls.user, cls.isolate = mod.dependencies()
        cls.payload, cls.dashboard, cls.manifest, cls.config = mod.integrated_payload(
            BUNDLE, DASHBOARD, SETTINGS, loaded=(cls.base, cls.user, cls.isolate))

    def setUp(self):
        self.target = Path(tempfile.gettempdir()) / ('OnyxV100-Windows-S4B' + uuid.uuid4().hex)
        self.addCleanup(lambda: shutil.rmtree(self.target, ignore_errors=True))

    def cli(self, *modeargs, target=None):
        target = self.target if target is None else target
        return subprocess.run([sys.executable, '-I', '-B', str(TOOL),
            '--bundle', str(BUNDLE), '--dashboard', str(DASHBOARD),
            '--target', str(target), '--receiver-host', SETTINGS['receiver_host'],
            '--source', SETTINGS['source'], '--network-adapter', SETTINGS['network_adapter'],
            '--usb-adapter', SETTINGS['usb_adapter'], '--gateway-port', '18976', *modeargs],
            capture_output=True, text=True, timeout=30)

    def test_source_hashes_of_exact_prior_dependencies(self):
        self.assertEqual(mod.sha(BUNDLE.read_bytes()), mod.BUNDLE_SHA256)
        self.assertEqual(mod.sha(DASHBOARD.read_bytes()), mod.DASHBOARD_SHA256)
        for filename, expected in mod.DEPENDENCIES.items():
            self.assertEqual(mod.sha(TOOL.with_name(filename).read_bytes()), expected)

    def test_isolated_three_file_inventory(self):
        originals, _, _ = self.base.inspect_inputs(BUNDLE, DASHBOARD)
        self.assertEqual(len(self.payload), 13)
        for path in mod.ISOLATED_PATHS:
            with self.subTest(path=path):
                self.assertNotEqual(self.payload[path], originals[path])
                self.assertEqual(self.payload[path], self.isolate.expected(BUNDLE)[0][path])

    def test_no_legacy_credential_mutex_or_logging_fallback(self):
        for path in mod.ISOLATED_PATHS:
            data = self.payload[path]
            self.assertNotIn(b'OnyxCore\\collector-token.dpapi', data)
            self.assertNotIn(b"'Local\\OnyxCoreCollector'", data)
        collector = self.payload['windows/collector/Send-OnyxTelemetry-v100.ps1']
        self.assertIn(b"$logDir = Join-Path $env:LOCALAPPDATA 'OnyxCore-v100'", collector)
        self.assertIn(b"'Local\\OnyxCoreV100Collector'", collector)

    def test_manifest_pinned_and_inert(self):
        data = self.payload[mod.ISOLATION_MANIFEST]
        self.assertEqual(mod.sha(data), mod.ISOLATION_SHA256)
        manifest = json.loads(data)
        self.assertEqual(manifest['file_count'], 3)
        for key in ('installation_performed','activation_performed','credential_enrolled','production_modified'):
            self.assertIs(manifest[key], False)

    def test_dashboard_is_versioned_and_gateway_helper_is_same_dir(self):
        self.assertEqual(mod.sha(self.dashboard), mod.DASHBOARD_SHA256)
        self.assertIn(b"with_name('Get-OnyxGatewayToken.ps1')",
                      self.payload['windows/gateway/OnyxGateway_v100.py'])
        self.assertNotEqual(self.payload['windows/gateway/gateway-dashboard.html'], self.dashboard)

    def test_preview_sandbox_is_readonly_and_receipt_inventory(self):
        p = mod.sandbox_preview(BUNDLE, DASHBOARD, self.target, SETTINGS)
        self.assertEqual(p['operation'], 'WINDOWS_V100_INTEGRATED_SANDBOX_PREVIEW')
        self.assertEqual(p['file_count_if_installed'], 17)
        self.assertEqual(p['gateway_port'], 18976)
        self.assertFalse(p['installation_performed'])
        self.assertFalse(self.target.exists())

    def test_user_scope_preview_is_readonly(self):
        with tempfile.TemporaryDirectory(prefix='onyx-v100-s4b-user-root-') as d:
            root = Path(d)
            user_target = root / ('OnyxCore-v100-Inactive-S4B' + uuid.uuid4().hex)
            preview = mod.user_preview(BUNDLE, DASHBOARD, user_target, SETTINGS, root=root)
            self.assertEqual(preview['operation'], 'WINDOWS_V100_INTEGRATED_USER_PREVIEW')
            self.assertEqual(preview['file_count_if_installed'], 17)
            self.assertFalse(preview['acl_changed'])
            self.assertTrue(preview['requires_separate_user_install_authorization'])
            self.assertFalse(user_target.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_user_preview_refuses_legacy_and_redirected_targets(self):
        with tempfile.TemporaryDirectory(prefix='onyx-v100-s4b-user-root-') as d:
            root = Path(d)
            with self.assertRaises(ValueError):
                mod.user_preview(BUNDLE, DASHBOARD, root / 'OnyxCore', SETTINGS, root=root)
            with self.assertRaises(ValueError):
                mod.user_preview(BUNDLE, DASHBOARD, root / ('OnyxCore-v100-Inactive-' + 'A'*8) / 'sub', SETTINGS, root=root)

    def test_sandbox_inactive_publication_and_full_receipt(self):
        result = mod.install_sandbox(BUNDLE, DASHBOARD, self.target, SETTINGS,
                                      native_check=lambda: True)
        self.assertEqual(result['operation'], 'WINDOWS_V100_INTEGRATED_SANDBOX_INSTALLED')
        self.assertEqual(result['file_count'], 17)
        receipt = json.loads((self.target / 'installation-receipt.json').read_bytes())
        rows = {row['path']: row for row in receipt['installed_files']}
        self.assertEqual(len(rows), 16)
        self.assertEqual(rows[mod.ISOLATION_MANIFEST]['sha256'], mod.ISOLATION_SHA256)
        self.assertEqual(rows['windows/gateway/gateway-dashboard.html']['sha256'], mod.DASHBOARD_SHA256)
        self.assertEqual(rows['windows/gateway/gateway-dashboard-v100.html']['sha256'], mod.DASHBOARD_SHA256)
        self.assertEqual((self.target / mod.ISOLATION_MANIFEST).read_bytes(), self.payload[mod.ISOLATION_MANIFEST])
        for path in mod.ISOLATED_PATHS:
            self.assertEqual(rows[path]['sha256'], mod.sha(self.payload[path]))
        self.assertFalse(receipt['credential_enrolled'])
        self.assertFalse(receipt['task_or_service_changes'])

    def test_repeat_sandbox_install_refuses_overwrite(self):
        mod.install_sandbox(BUNDLE, DASHBOARD, self.target, SETTINGS, native_check=lambda: True)
        before = (self.target / 'installation-receipt.json').read_bytes()
        with self.assertRaises(ValueError):
            mod.install_sandbox(BUNDLE, DASHBOARD, self.target, SETTINGS, native_check=lambda: True)
        self.assertEqual((self.target / 'installation-receipt.json').read_bytes(), before)

    def test_tampered_derived_runtime_fails_receipt_validation(self):
        mod.install_sandbox(BUNDLE, DASHBOARD, self.target, SETTINGS, native_check=lambda: True)
        path = self.target / 'windows/gateway/Get-OnyxGatewayToken.ps1'
        path.write_bytes(path.read_bytes() + b'\nTAMPER')
        with self.assertRaises(ValueError):
            self.base.verify_inactive_install(self.target, self.payload, self.dashboard, self.manifest, self.config)

    def test_tampered_provenance_manifest_fails_validation(self):
        mod.install_sandbox(BUNDLE, DASHBOARD, self.target, SETTINGS, native_check=lambda: True)
        (self.target / mod.ISOLATION_MANIFEST).write_bytes(b'{}')
        with self.assertRaises(ValueError):
            self.base.verify_inactive_install(self.target, self.payload, self.dashboard, self.manifest, self.config)

    def test_tampered_receipt_fails_validation(self):
        mod.install_sandbox(BUNDLE, DASHBOARD, self.target, SETTINGS, native_check=lambda: True)
        receipt = self.target / 'installation-receipt.json'
        data = json.loads(receipt.read_bytes())
        data['bundle_sha256'] = '0'*64
        receipt.write_bytes(mod.canonical(data))
        with self.assertRaises(ValueError):
            self.base.verify_inactive_install(self.target, self.payload, self.dashboard, self.manifest, self.config)

    def test_extra_installed_file_fails_receipt_validation(self):
        mod.install_sandbox(BUNDLE, DASHBOARD, self.target, SETTINGS, native_check=lambda: True)
        (self.target / 'unexpected.data').write_text('changed')
        with self.assertRaises(ValueError):
            self.base.verify_inactive_install(self.target, self.payload, self.dashboard, self.manifest, self.config)

    def test_reserved_ports_refused(self):
        for port in (18766, 18767, 18768, 18769):
            with self.subTest(port=port), self.assertRaises(ValueError):
                mod.sandbox_preview(BUNDLE, DASHBOARD, self.target, {**SETTINGS, 'gateway_port': port})

    def test_bundle_sha_mismatch_fails_before_install(self):
        with tempfile.TemporaryDirectory(prefix='onyx-v100-s4b-bad-bundle-') as d:
            bad = Path(d)/'bad.zip'
            bad.write_bytes(BUNDLE.read_bytes() + b'bad')
            with self.assertRaises(ValueError):
                mod.sandbox_preview(bad, DASHBOARD, self.target, SETTINGS)
        self.assertFalse(self.target.exists())

    def test_dashboard_sha_mismatch_fails_before_install(self):
        with tempfile.TemporaryDirectory(prefix='onyx-v100-s4b-bad-dash-') as d:
            bad = Path(d)/'gateway-dashboard-v100.html'
            bad.write_bytes(DASHBOARD.read_bytes() + b'bad')
            with self.assertRaises(ValueError):
                mod.sandbox_preview(BUNDLE, bad, self.target, SETTINGS)
        self.assertFalse(self.target.exists())

    def test_dependency_tamper_blocks_before_install(self):
        with mock.patch.object(mod, 'sha', return_value='0'*64):
            with self.assertRaisesRegex(mod.IntegrationRefused, 'dependency'):
                mod.dependencies()

    def test_native_nonwindows_install_refused(self):
        with self.assertRaises(ValueError):
            mod.install_sandbox(BUNDLE, DASHBOARD, self.target, SETTINGS,
                                native_check=lambda: False)
        self.assertFalse(self.target.exists())

    def test_cli_sandbox_preview_default_is_readonly(self):
        p = self.cli()
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        self.assertEqual(data['operation'], 'WINDOWS_V100_INTEGRATED_SANDBOX_PREVIEW')
        self.assertFalse(self.target.exists())

    def test_cli_partial_approval_refused_without_writes(self):
        for flags in (('--mode', 'install-sandbox'), ('--approve-inactive-sandbox',),
                      ('--mode', 'preview-user', '--approve-inactive-sandbox')):
            with self.subTest(flags=flags):
                p = self.cli(*flags)
                self.assertEqual(p.returncode, 2)
                self.assertIn('approval', p.stderr)
                self.assertFalse(self.target.exists())

    def test_cli_cannot_install_user_profile(self):
        p = self.cli('--mode', 'install-user')
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(self.target.exists())
        self.assertNotIn('install-user', TOOL.read_text())

    def test_no_live_side_effect_entrypoints(self):
        source = TOOL.read_text()
        for forbidden in ('Register-ScheduledTask', 'netsh ', 'subprocess.run', 'systemctl',
                          'socket.', 'winreg.', 'requests.', '--install-user'):
            self.assertNotIn(forbidden, source)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows Known Folder native preview only')
    def test_native_windows_known_folder_preview(self):
        from pathlib import Path
        root = self.user.native_user_root()
        target = root / ('OnyxCore-v100-Inactive-S4B' + uuid.uuid4().hex)
        preview = mod.user_preview(BUNDLE, DASHBOARD, target, SETTINGS)
        self.assertFalse(preview['installation_performed'])
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
