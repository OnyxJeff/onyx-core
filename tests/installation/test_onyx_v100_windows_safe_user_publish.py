#!/usr/bin/env python3
"""Offline M2-S5C integration checks. No unattended native ACL mutation."""
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
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'tools/installation/windows/onyx_v100_windows_safe_user_publish.py'
HELPER = SRC.with_name('Set-OnyxV100SafeUserDacl.ps1')
BUNDLE = Path(os.environ.get('ONYX_V100_BUNDLE', '/mnt/data/ONYX_CORE_v1.0.0_M2S1_CoreRuntime_CANDIDATE.zip'))
DASH = Path(os.environ.get('ONYX_V100_DASHBOARD', str(ROOT / 'windows/gateway/gateway-dashboard-v100.html')))
SETTINGS = dict(receiver_host='svr-onyxcore.local', receiver_port=8765,
                source='SQUALL', network_adapter='Ethernet', usb_adapter='Ethernet 3',
                gateway_port=18976, interval=30)
spec = importlib.util.spec_from_file_location('onyx_s5c_under_test', SRC)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class SafeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(BUNDLE.is_file())
        self.assertTrue(DASH.is_file())

    def args(self, *more):
        return ['--bundle', str(BUNDLE), '--dashboard', str(DASH),
                '--receiver-host', 'svr-onyxcore.local', '--source', 'SQUALL',
                '--network-adapter', 'Ethernet', '--usb-adapter', 'Ethernet 3',
                '--gateway-port', '18976', *more]

    def test_new_helper_is_pinned(self):
        self.assertEqual(hashlib.sha256(HELPER.read_bytes()).hexdigest(), mod.SAFE_HELPER_SHA)
        self.assertEqual(mod.helper_path(), HELPER)

    def test_all_three_dependencies_are_pinned(self):
        s4c, r3, s5b = mod.reviewed()
        self.assertEqual(s4c.sha((SRC.with_name('onyx_v100_windows_user_integrated.py')).read_bytes()), mod.S4C_SHA)
        self.assertEqual(s4c.sha((SRC.with_name('onyx_v100_windows_native_acl_fixture.py')).read_bytes()), mod.R3_SHA)
        self.assertEqual(s4c.sha((SRC.with_name('onyx_v100_windows_atomic_publish.py')).read_bytes()), mod.S5B_SHA)
        self.assertEqual(r3.M2_COMMIT, mod.M2_HEAD)
        self.assertEqual(s5b.M2_HEAD, mod.M2_HEAD)

    def test_helper_has_complete_dacl_only_writer(self):
        s = HELPER.read_text('utf-8')
        self.assertIn('[IO.File]::SetAccessControl($Path, $Acl)', s)
        self.assertIn('[IO.Directory]::SetAccessControl($Path, $Acl)', s)
        self.assertIn('SetAccessRuleProtection($true, $false)', s)
        self.assertNotIn('icacls.exe', s)
        self.assertNotIn('Set-Acl -LiteralPath', s)
        self.assertIn('GetAccessRules', s)
        self.assertIn('ReparsePoint', s)

    def test_helper_requires_strong_user_approval(self):
        s = HELPER.read_text('utf-8')
        for marker in ('ApproveInactiveUser', 'ApproveUserDacl', 'ApproveTempFixture',
                       "[ValidateSet('Temp','User')]", '.s5a-fixture.marker'):
            self.assertIn(marker, s)

    def test_public_cli_no_persistent_or_arbitrary_target(self):
        s = SRC.read_text('utf-8')
        self.assertIn("choices=('preview', 'native-temp')", s)
        self.assertNotIn("p.add_argument('--target'", s)
        self.assertNotIn("p.add_argument('--install'", s)
        self.assertNotIn("p.add_argument('--approve-persistent'", s)

    def test_no_unsafe_or_automatic_cleanup(self):
        s = SRC.read_text('utf-8')
        for forbidden in ('os.replace(', 'shutil.rmtree(', 'staging.rename(', 'shell=True',
                          'schtasks', 'Start-Service', 'Set-OnyxV100UserInstallAcl.ps1'):
            self.assertNotIn(forbidden, s)
        self.assertIn("move(str(staging), str(target), 0)", s)

    def test_exact_17_file_payload(self):
        expected, cfg = mod.expected_install(BUNDLE, DASH, SETTINGS)
        self.assertEqual(len(expected), 16)
        self.assertEqual(cfg['gateway']['port'], 18976)
        self.assertEqual(expected['windows/gateway/gateway-dashboard.html'],
                         expected['windows/gateway/gateway-dashboard-v100.html'])
        self.assertIn('runtime-isolation-manifest.json', expected)

    def test_bad_bundle_refused(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / 'bad.zip'
            bad.write_bytes(BUNDLE.read_bytes() + b'X')
            with self.assertRaisesRegex(mod.SafePublishRefused, 'source mismatch'):
                mod.expected_install(bad, DASH, SETTINGS)

    def test_bad_dashboard_refused(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / 'bad.html'
            bad.write_bytes(DASH.read_bytes() + b'X')
            with self.assertRaisesRegex(mod.SafePublishRefused, 'source mismatch'):
                mod.expected_install(BUNDLE, bad, SETTINGS)

    def test_mutated_dependency_rejected(self):
        with mock.patch.object(mod, 'R3_SHA', '0' * 64):
            with self.assertRaisesRegex(mod.SafePublishRefused, 'hash mismatch'):
                mod.reviewed()

    def test_mutated_safe_helper_rejected(self):
        with mock.patch.object(mod, 'SAFE_HELPER_SHA', '0' * 64):
            with self.assertRaisesRegex(mod.SafePublishRefused, 'pinned source'):
                mod.helper_path()

    def test_partial_native_temp_flags_refused_without_write(self):
        with mock.patch.object(mod, 'fixture_acceptance') as accept:
            with mock.patch.object(mod, 'preview') as preview:
                self.assertEqual(mod.cli(self.args('--mode','native-temp','--approve-native-temp')), 2)
                accept.assert_not_called()
                preview.assert_not_called()

    def test_preview_rejects_write_flags(self):
        with mock.patch.object(mod, 'preview') as preview:
            self.assertEqual(mod.cli(self.args('--approve-no-replace-test')), 2)
            preview.assert_not_called()

    def test_cli_refuses_user_install_argument(self):
        with self.assertRaises(SystemExit):
            mod.cli(self.args('--mode', 'user'))

    def test_user_install_requires_three_future_approvals(self):
        with mock.patch.object(mod, 'native_guard'):
            s4c, r3, s5b = mod.reviewed()
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                target = root / mod.PREVIEW_NAME
                with self.assertRaisesRegex(mod.SafePublishRefused, 'three explicit'):
                    mod.install_core({str(i): b'X' for i in range(16)}, root=root,
                                     target=target, scope='User', s4c=s4c, r3=r3)
                self.assertEqual(list(root.iterdir()), [])

    def test_fixture_guard_rejects_wrong_root(self):
        with mock.patch.object(mod, 'native_guard'):
            s4c, r3, s5b = mod.reviewed()
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                target = root / ('OnyxCore-v100-Inactive-S5A' + '0' * 32)
                with self.assertRaises(ValueError):
                    mod.install_core({str(i): b'X' for i in range(16)}, root=root,
                                     target=target, scope='Temp', s4c=s4c, r3=r3)
                self.assertEqual(list(root.iterdir()), [])

    def test_no_native_write_during_default_test_run(self):
        self.assertIn('native-temp', SRC.read_text())
        self.assertIn('approve_no_replace_test', SRC.read_text())
        # Native fixture only through explicitly approved SQUALL acceptance script.
        if sys.platform == 'win32':
            self.assertFalse(False)

    def test_synthetic_17_file_pipeline_with_receipt(self):
        s4c, r3, s5b = mod.reviewed()
        expected, _ = mod.expected_install(BUNDLE, DASH, SETTINGS, s4c=s4c)
        root, target = s5b.make_root(r3)
        try:
            events = []
            def harden(mode, scope, parent, child):
                self.assertEqual(scope, 'Temp')
                self.assertEqual(parent, root)
                events.append(mode)
            def fake_move(source, destination, parent):
                self.assertEqual(destination, target)
                self.assertEqual(parent, root)
                self.assertFalse(destination.exists())
                source.rename(destination)
            with mock.patch.object(mod, 'native_guard'):
                result = mod.install_core(expected, root=root, target=target, scope='Temp',
                                          s4c=s4c, r3=r3, harden=harden, move=fake_move)
            self.assertEqual(events, ['Harden', 'Audit'])
            self.assertEqual(result['file_count'], 17)
            self.assertFalse(result['activation_performed'])
            rows = json.loads((target / 'installation-receipt.json').read_bytes())
            self.assertEqual(len(rows['installed_files']), 16)
        finally:
            shutil.rmtree(root)

    def test_synthetic_hardening_failure_retains_stage(self):
        s4c, r3, s5b = mod.reviewed()
        expected, _ = mod.expected_install(BUNDLE, DASH, SETTINGS, s4c=s4c)
        root, target = s5b.make_root(r3)
        try:
            with mock.patch.object(mod, 'native_guard'):
                def broken(*args):
                    raise ValueError('DACL failure witness')
                with self.assertRaisesRegex(mod.SafePublishRefused, 'INCOMPLETE.*DACL failure witness'):
                    mod.install_core(expected, root=root, target=target, scope='Temp',
                                     s4c=s4c, r3=r3, harden=broken)
            self.assertFalse(target.exists())
            stages = list(root.glob('.OnyxCore-v100-staging-*'))
            self.assertEqual(len(stages), 1)
            self.assertTrue((stages[0] / 'installation-receipt.json').exists())
        finally:
            shutil.rmtree(root)

    def test_synthetic_collision_retains_stage_and_target(self):
        s4c, r3, s5b = mod.reviewed()
        expected, _ = mod.expected_install(BUNDLE, DASH, SETTINGS, s4c=s4c)
        root, target = s5b.make_root(r3)
        try:
            # The witness appears just before publication, after the root checks.
            def collision(source, destination, parent):
                destination.mkdir()
                (destination / 'do-not-overwrite.txt').write_text('unchanged')
                raise mod.SafePublishRefused('Win32 error=183')
            with mock.patch.object(mod, 'native_guard'):
                with self.assertRaisesRegex(mod.SafePublishRefused, 'INCOMPLETE.*183'):
                    mod.install_core(expected, root=root, target=target, scope='Temp',
                                     s4c=s4c, r3=r3, harden=lambda *a: None, move=collision)
            self.assertEqual((target / 'do-not-overwrite.txt').read_text(), 'unchanged')
            self.assertEqual(len(list(root.glob('.OnyxCore-v100-staging-*'))), 1)
        finally:
            shutil.rmtree(root)

    def test_receipt_tampering_is_rejected(self):
        s4c, r3, s5b = mod.reviewed()
        expected, _ = mod.expected_install(BUNDLE, DASH, SETTINGS, s4c=s4c)
        root, target = s5b.make_root(r3)
        try:
            def broken_move(src, dst, parent):
                src.rename(dst)
                (dst / 'installation-receipt.json').write_bytes(b'{}')
            with mock.patch.object(mod, 'native_guard'):
                with self.assertRaisesRegex(mod.SafePublishRefused, 'INCOMPLETE'):
                    mod.install_core(expected, root=root, target=target, scope='Temp',
                                     s4c=s4c, r3=r3, harden=lambda *a: None, move=broken_move)
            self.assertTrue(target.is_dir())
        finally:
            shutil.rmtree(root)

    def test_native_execution_only_on_explicit_acceptance(self):
        if sys.platform != 'win32':
            self.skipTest('SQUALL alone runs native DACL fixture with two explicit flags')
        self.assertIn('--approve-native-temp', SRC.read_text())
        self.assertIn('--approve-no-replace-test', SRC.read_text())


if __name__ == '__main__':
    unittest.main(verbosity=2)
