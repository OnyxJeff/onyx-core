#!/usr/bin/env python3
"""M2-S2C offline tests: user-scoped installation in disposable synthetic roots only."""
import argparse
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr

p = argparse.ArgumentParser()
p.add_argument('--tool', type=Path, required=True)
p.add_argument('--bundle', type=Path, required=True)
p.add_argument('--dashboard', type=Path, required=True)
p.add_argument('--acl-helper', type=Path, required=True)
args, remainder = p.parse_known_args()
spec = importlib.util.spec_from_file_location('onyx_v100_windows_user_install', args.tool)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class UserScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='onyx-v100-user-install-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.target = self.root / 'OnyxCore-v100-Inactive-test123456'
        self.settings = dict(receiver_host='svr-onyxcore.local', receiver_port=8765,
                             source='SQUALL', network_adapter='Ethernet',
                             usb_adapter='Ethernet 3', gateway_port=18976, interval=30)
        self.calls = []

    def plan(self):
        return module.prepare_plan(args.bundle, args.dashboard, self.target,
                                   self.settings, root=self.root)

    def install(self):
        plan, expected, cfg = self.plan()
        result = module.install_inactive(self.target, expected, root=self.root,
                                         native_check=lambda: True,
                                         acl_guard=lambda path: self.calls.append(path))
        return result, expected, cfg

    def test_readonly_preview_describes_user_scope(self):
        plan, expected, cfg = self.plan()
        self.assertEqual(plan['operation'], 'WINDOWS_USER_INSTALL_PREVIEW')
        self.assertEqual(plan['file_count'], 16)
        self.assertEqual(plan['gateway_port'], 18976)
        self.assertEqual(plan['collector_source'], 'SQUALL')
        self.assertFalse(plan['installation_performed'])
        self.assertFalse(plan['acl_verified'])
        self.assertFalse(plan['credentials_read'])
        self.assertFalse(plan['activation_performed'])
        self.assertFalse(self.target.exists())
        self.assertFalse(self.calls)

    def test_accepted_bundle_config_and_versioned_gateway_assets(self):
        _, expected, cfg = self.plan()
        self.assertEqual(cfg['receiver']['host'], 'svr-onyxcore.local')
        self.assertIn('windows/collector/Send-OnyxTelemetry-v100.ps1', expected)
        self.assertIn('tools/installation/windows/Invoke-OnyxV100WindowsRuntime.ps1', expected)
        self.assertIn('windows/gateway/Get-OnyxGatewayToken.ps1', expected)
        self.assertEqual(expected['windows/gateway/gateway-dashboard.html'],
                         expected['windows/gateway/gateway-dashboard-v100.html'])
        self.assertNotIn('pi/services/receiver/receiver_v100.py', expected)
        self.assertEqual(json.loads(expected[module.CONFIG_NAME])['collector']['source'], 'SQUALL')

    def test_pinned_dependency_hash(self):
        self.assertEqual(module.sha256(args.tool.with_name('onyx_v100_windows_install.py').read_bytes()),
                         module.S2B_SOURCE_SHA256)
        self.assertEqual(module.sha256(args.acl_helper.read_bytes()), module.ACL_HELPER_SHA256)
        self.assertIn('Set-OnyxV100UserInstallAcl.ps1', args.acl_helper.name)

    def test_user_directory_is_new_direct_child_only(self):
        bad = [self.root / 'OnyxCore',
               self.root / 'OnyxCore-v070-Release',
               self.root / 'OnyxCore-v100-Inactive-abc' / 'nested',
               self.root.parent / 'OnyxCore-v100-Inactive-test123456']
        for path in bad:
            with self.subTest(path=str(path)), self.assertRaises(module.UserInstallRefused):
                module.validate_target(path, root=self.root)
        self.target.mkdir()
        with self.assertRaises(module.UserInstallRefused):
            module.validate_target(self.target, root=self.root)

    def test_no_os_temp_sandbox_reuse(self):
        self.assertFalse(self.target.name.startswith('OnyxV100-Windows-'))
        with self.assertRaises(module.UserInstallRefused):
            module.validate_target(self.root / 'OnyxV100-Windows-test123456', root=self.root)

    def test_inactive_install_and_receipt_accepted(self):
        result, expected, _ = self.install()
        self.assertEqual(result['operation'], 'WINDOWS_USER_INACTIVE_INSTALLED')
        self.assertEqual(result['file_count'], 16)
        self.assertFalse(result['activation_performed'])
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.calls[0].exists())
        verified = module.verify_inactive(self.target, expected, root=self.root)
        self.assertEqual(verified['file_count'], 16)
        self.assertFalse((self.target / 'pi').exists())
        receipt = json.loads((self.target / module.RECEIPT_NAME).read_text())
        self.assertTrue(receipt['acl_hardened'])
        self.assertFalse(receipt['credential_enrolled'])
        self.assertFalse(receipt['service_or_task_changes'])
        self.assertEqual(receipt['source_commit'], module.SOURCE_COMMIT)

    def test_no_overwrite_of_existing_install(self):
        _, expected, _ = self.install()
        with self.assertRaises(module.UserInstallRefused):
            module.install_inactive(self.target, expected, root=self.root,
                                    native_check=lambda: True, acl_guard=lambda _: None)

    def test_acl_failure_refuses_publish(self):
        _, expected, _ = self.plan()
        def fail(_):
            raise module.UserInstallRefused('synthetic ACL refusal')
        with self.assertRaisesRegex(module.UserInstallRefused, 'ACL refusal'):
            module.install_inactive(self.target, expected, root=self.root,
                                    native_check=lambda: True, acl_guard=fail)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_acl_callback_runs_before_publish(self):
        _, expected, _ = self.plan()
        def check_stage(path):
            self.assertTrue(path.is_dir())
            self.assertEqual(path.parent, self.root)
            self.assertFalse(self.target.exists())
            self.assertTrue((path / module.RECEIPT_NAME).exists())
            self.assertEqual(len(list(path.rglob('*.ps1'))), 5)
        module.install_inactive(self.target, expected, root=self.root,
                                native_check=lambda: True, acl_guard=check_stage)
        self.assertTrue(self.target.exists())

    def test_existing_target_refused_before_acl(self):
        self.target.mkdir()
        with self.assertRaises(module.UserInstallRefused):
            self.plan()
        self.assertFalse(self.calls)

    def test_non_native_install_refused(self):
        _, expected, _ = self.plan()
        with self.assertRaises(module.UserInstallRefused):
            module.install_inactive(self.target, expected, root=self.root,
                                    native_check=lambda: False, acl_guard=lambda _: None)
        self.assertFalse(self.target.exists())

    def test_wrong_gateway_port_and_source_refused(self):
        self.settings['gateway_port'] = 18766
        with self.assertRaises(ValueError):
            self.plan()
        self.settings['gateway_port'] = 18976
        self.settings['source'] = '../unsafe'
        with self.assertRaises(ValueError):
            self.plan()
        self.assertFalse(self.target.exists())

    def test_tampered_receipt_refused(self):
        _, expected, _ = self.install()
        receipt = self.target / module.RECEIPT_NAME
        data = json.loads(receipt.read_text())
        data['source_commit'] = '0' * 40
        receipt.write_bytes(module.canonical_json(data))
        with self.assertRaises(module.UserInstallRefused):
            module.verify_inactive(self.target, expected, root=self.root)

    def test_tampered_runtime_refused(self):
        _, expected, _ = self.install()
        file = self.target / 'windows/gateway/gateway-dashboard.html'
        file.write_text('changed')
        with self.assertRaises(module.UserInstallRefused):
            module.verify_inactive(self.target, expected, root=self.root)

    def test_added_unreviewed_file_refused(self):
        _, expected, _ = self.install()
        (self.target / 'extra.txt').write_text('extra')
        with self.assertRaises(module.UserInstallRefused):
            module.verify_inactive(self.target, expected, root=self.root)

    def test_versioned_receipt_does_not_contain_secrets(self):
        self.install()
        text = (self.target / module.RECEIPT_NAME).read_text()
        for forbidden in ('password=', 'token=', 'DPAPI'):
            self.assertNotIn(forbidden, text)

    def test_m2s2c_has_no_task_or_network_mutations(self):
        source = args.tool.read_text()
        for forbidden in ('Register-ScheduledTask', 'netsh', 'sc.exe', 'systemctl',
                          'New-NetFirewallRule', 'Stop-Service'):
            self.assertNotIn(forbidden, source)

    def test_source_rejects_redirected_target(self):
        link = self.root / 'OnyxCore-v100-Inactive-link123456'
        try:
            link.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('symlink creation unavailable')
        with self.assertRaises(module.UserInstallRefused):
            module.validate_target(link, root=self.root)

    def test_public_cli_refuses_partial_approval_without_writing(self):
        import subprocess
        common = ['--bundle', str(args.bundle), '--dashboard', str(args.dashboard),
                  '--target', str(self.target), '--receiver-host', 'svr-onyxcore.local',
                  '--source', 'SQUALL', '--network-adapter', 'Ethernet',
                  '--usb-adapter', 'Ethernet 3', '--gateway-port', '18976']
        for flags in (['--install'], ['--approve-inactive'], ['--approve-user-scope'],
                      ['--install', '--approve-inactive'],
                      ['--install', '--approve-user-scope']):
            result = subprocess.run([sys.executable, '-I', '-B', str(args.tool), *common, *flags],
                                    capture_output=True, text=True, timeout=10)
            with self.subTest(flags=flags):
                self.assertEqual(result.returncode, 2)
                self.assertIn('all three explicit flags', result.stderr)
                self.assertFalse(self.target.exists())

    def test_bad_acl_helper_fails_closed_before_running_powershell(self):
        with tempfile.TemporaryDirectory(prefix='onyx-acl-probe-') as tmp:
            import unittest.mock as mock
            helper = args.acl_helper
            target = Path(tmp)
            with mock.patch.object(module, 'sha256', return_value='0' * 64):
                with self.assertRaisesRegex(module.UserInstallRefused, 'fingerprint'):
                    module.protect_staging(target, root=target)

    def test_live_user_scope_flags_are_never_test_executed(self):
        source = args.tool.read_text()
        self.assertIn('--approve-user-scope', source)
        self.assertIn('--approve-inactive', source)
        self.assertIn('native_user_root()', source)
        # CLI can only resolve real LocalAppData; test roots cannot be passed as CLI flags.
        self.assertNotIn("parser.add_argument('--root'", source)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]] + remainder, verbosity=2)
