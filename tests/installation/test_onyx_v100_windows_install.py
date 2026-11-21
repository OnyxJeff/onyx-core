#!/usr/bin/env python3
"""M2-S2B offline inactive Windows installer tests. No host activation."""
import argparse
import importlib.util
import io
import json
import pathlib
import shutil
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout

p = argparse.ArgumentParser()
p.add_argument('--tool', required=True, type=pathlib.Path)
p.add_argument('--bundle', required=True, type=pathlib.Path)
p.add_argument('--dashboard', required=True, type=pathlib.Path)
args, remaining = p.parse_known_args()
spec = importlib.util.spec_from_file_location('onyx_v100_windows_install', args.tool)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.target = pathlib.Path(tempfile.gettempdir()) / ('OnyxV100-Windows-' + uuid.uuid4().hex)
        self.addCleanup(lambda: shutil.rmtree(self.target, ignore_errors=True))
        self.inputs = dict(receiver_host='svr-onyxcore.local', receiver_port=8765,
                           source='SQUALL', network_adapter='Ethernet',
                           usb_adapter='Ethernet 3', gateway_port=18976, interval=30)

    def plan(self):
        return installer.prepare_plan(args.bundle, args.dashboard, self.target, self.inputs)

    def test_preview_is_inert_and_explicit_source(self):
        report, payload, dashboard, manifest, cfg = self.plan()
        self.assertFalse(self.target.exists())
        self.assertEqual(report['selected_runtime_files'], 12)
        self.assertEqual(report['collector_source'], 'SQUALL')
        self.assertEqual(cfg['gateway']['port'], 18976)
        self.assertFalse(report['credential_contents_read'])
        self.assertFalse(report['network_scope_verified'])

    def test_payload_verified_and_has_gateway_dependencies(self):
        _, payload, dashboard, _, _ = self.plan()
        self.assertIn('windows/gateway/Get-OnyxGatewayToken.ps1', payload)
        self.assertIn('tools/installation/windows/Invoke-OnyxV100WindowsRuntime.ps1', payload)
        self.assertIn('windows/gateway/gateway-dashboard.html', payload)
        self.assertNotEqual(payload['windows/gateway/gateway-dashboard.html'], dashboard)
        self.assertNotIn('pi/services/receiver/receiver_v100.py', payload)

    def test_port_refuses_protected_gateways(self):
        for port in sorted(installer.RESERVED_GATEWAY_PORTS):
            self.inputs['gateway_port'] = port
            with self.subTest(port=port), self.assertRaises(installer.InstallRefused):
                self.plan()
        self.assertFalse(self.target.exists())

    def test_unsafe_config_and_credentials_are_refused(self):
        for item in ({'source': '../SQUALL'}, {'source': 'secret token=abc'},
                     {'usb_adapter': ''}, {'receiver_port': 0},
                     {'network_adapter': 'Ethernet;rm'}, {'gateway_port': 777}):
            with self.subTest(item=item), self.assertRaises(installer.InstallRefused):
                self.inputs.update(item)
                self.plan()
            self.inputs = dict(receiver_host='svr-onyxcore.local', receiver_port=8765,
                               source='SQUALL', network_adapter='Ethernet',
                               usb_adapter='Ethernet 3', gateway_port=18976, interval=30)
        self.assertFalse(self.target.exists())

    def test_rejects_wrong_bundle_and_dashboard(self):
        with tempfile.TemporaryDirectory(prefix='OnyxV100-TestInput-') as tmp:
            fake_bundle = pathlib.Path(tmp) / 'wrong.zip'
            fake_bundle.write_bytes(args.bundle.read_bytes() + b'\0')
            with self.assertRaises(installer.InstallRefused):
                installer.inspect_inputs(fake_bundle, args.dashboard)
            fake_page = pathlib.Path(tmp) / 'wrong.html'
            fake_page.write_bytes(args.dashboard.read_bytes() + b'\0')
            with self.assertRaises(installer.InstallRefused):
                installer.inspect_inputs(args.bundle, fake_page)

    def test_refuses_existing_target_and_other_directories(self):
        self.target.mkdir()
        with self.assertRaises(installer.InstallRefused):
            self.plan()
        self.target.rmdir()
        bad = pathlib.Path(tempfile.gettempdir()) / 'OnyxV100-Windows-other' / 'nested'
        with self.assertRaises(installer.InstallRefused):
            installer.validate_target(bad)
        with self.assertRaises(installer.InstallRefused):
            installer.validate_target(pathlib.Path(tempfile.gettempdir()) / 'OnyxCore')

    def test_inactive_install_is_atomic_and_receipt_verified(self):
        _, payload, dashboard, manifest, cfg = self.plan()
        result = installer.write_inactive_install(
            self.target, payload, dashboard, manifest, cfg, native_check=lambda: True)
        self.assertEqual(result['operation'], 'WINDOWS_INACTIVE_SANDBOX_INSTALLED')
        self.assertEqual(result['file_count'], 16)
        self.assertEqual(installer.verify_inactive_install(
            self.target, payload, dashboard, manifest, cfg)['file_count'], 16)
        page = self.target / 'windows/gateway/gateway-dashboard.html'
        self.assertEqual(page.read_bytes(), dashboard)
        self.assertEqual((self.target / 'config/windows.config.json').read_bytes(), installer.canonical_json(cfg))
        self.assertEqual(json.loads((self.target / 'installation-receipt.json').read_text())['credential_enrolled'], False)
        self.assertFalse((self.target / 'pi').exists())
        with self.assertRaises(installer.InstallRefused):
            installer.write_inactive_install(
                self.target, payload, dashboard, manifest, cfg, native_check=lambda: True)

    def test_tampered_file_and_receipt_refused(self):
        _, payload, dashboard, manifest, cfg = self.plan()
        installer.write_inactive_install(
            self.target, payload, dashboard, manifest, cfg, native_check=lambda: True)
        file = self.target / 'windows/gateway/gateway-dashboard.html'
        file.write_bytes(b'tamper')
        with self.assertRaises(installer.InstallRefused):
            installer.verify_inactive_install(self.target, payload, dashboard, manifest, cfg)
        file.write_bytes(dashboard)
        receipt_file = self.target / 'installation-receipt.json'
        receipt = json.loads(receipt_file.read_text())
        receipt['installed_files'][0]['sha256'] = '0' * 64
        receipt_file.write_bytes(installer.canonical_json(receipt))
        with self.assertRaises(installer.InstallRefused):
            installer.verify_inactive_install(self.target, payload, dashboard, manifest, cfg)

    def test_cli_preview_and_one_sided_refusal(self):
        command = [ '--bundle', str(args.bundle), '--dashboard', str(args.dashboard),
                    '--target', str(self.target), '--receiver-host', 'svr-onyxcore.local',
                    '--source', 'SQUALL', '--network-adapter', 'Ethernet',
                    '--usb-adapter', 'Ethernet 3', '--gateway-port', '18976']
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(installer.cli(command), 0)
        self.assertFalse(json.loads(out.getvalue())['installation_performed'])
        self.assertFalse(self.target.exists())
        with redirect_stderr(io.StringIO()):
            self.assertNotEqual(installer.cli(command + ['--install']), 0)
            self.assertNotEqual(installer.cli(command + ['--approve-inactive']), 0)
        self.assertFalse(self.target.exists())

    def test_public_cli_refuses_nonwindows_native_execution(self):
        if installer.sys.platform == 'win32':
            self.skipTest('Native Windows CLI tested with isolated sandbox acceptance')
        command = [ '--bundle', str(args.bundle), '--dashboard', str(args.dashboard),
                    '--target', str(self.target), '--receiver-host', 'svr-onyxcore.local',
                    '--source', 'SQUALL', '--network-adapter', 'Ethernet',
                    '--usb-adapter', 'Ethernet 3', '--gateway-port', '18976',
                    '--install', '--approve-inactive']
        with redirect_stderr(io.StringIO()):
            self.assertNotEqual(installer.cli(command), 0)
        self.assertFalse(self.target.exists())

    def test_receipt_does_not_contain_credentials(self):
        _, payload, dashboard, manifest, cfg = self.plan()
        installer.write_inactive_install(
            self.target, payload, dashboard, manifest, cfg, native_check=lambda: True)
        data = (self.target / installer.RECEIPT_PATH).read_text()
        self.assertNotIn('token=', data)
        self.assertNotIn('DPAPI', data)
        self.assertNotIn('password=', data)

    def test_no_legacy_or_system_paths_in_install_code(self):
        source = args.tool.read_text(encoding='utf-8')
        for word in ('Register-ScheduledTask', 'systemctl', 'netsh', 'sc.exe',
                     'New-NetFirewallRule', 'reg.exe', 'Stop-Service'):
            self.assertNotIn(word, source)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]] + remaining, verbosity=2)
