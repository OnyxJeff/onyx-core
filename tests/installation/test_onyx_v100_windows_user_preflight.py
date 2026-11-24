#!/usr/bin/env python3
"""M2-S5D: offline installation preflight tests, no live user-scope writes."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'tools/installation/windows/onyx_v100_windows_user_preflight.py'
BUNDLE = Path(os.environ.get('ONYX_V100_BUNDLE', '/mnt/data/ONYX_CORE_v1.0.0_M2S1_CoreRuntime_CANDIDATE.zip'))
DASH = Path(os.environ.get('ONYX_V100_DASHBOARD', str(ROOT / 'windows/gateway/gateway-dashboard-v100.html')))
SETTINGS = dict(receiver_host='svr-onyxcore.local', receiver_port=8765, source='SQUALL',
                network_adapter='Ethernet', usb_adapter='Ethernet 3', gateway_port=18976, interval=30)
spec = importlib.util.spec_from_file_location('onyx_s5d_test_subject', SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class PreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BUNDLE.is_file() or not DASH.is_file():
            raise RuntimeError('exact accepted bundle and dashboard must be staged')
        cls.s5c = mod.reviewed_s5c()
        cls.s4c = cls.s5c.reviewed()[0]
        cls.user = cls.s4c.reviewed_modules()[2]
        cls.expected, cls.cfg = cls.s5c.expected_install(BUNDLE, DASH, SETTINGS, s4c=cls.s4c)

    def make_report(self):
        with tempfile.TemporaryDirectory(prefix='OnyxV100-S5D-Test-') as root:
            return mod.target_report(Path(root), self.expected, self.cfg, user=self.user)

    def test_s5c_source_sha_and_provenance(self):
        src = SOURCE.with_name('onyx_v100_windows_safe_user_publish.py')
        self.assertEqual(mod.sha(src.read_bytes()), mod.S5C_SHA256)
        self.assertEqual(self.s5c.M2_HEAD, mod.M2_HEAD)

    def test_all_three_reviewed_dependencies_and_safe_helper(self):
        self.assertEqual(len(self.s5c.reviewed()), 3)
        self.assertEqual(mod.sha(self.s5c.helper_path().read_bytes()), self.s5c.SAFE_HELPER_SHA)

    def test_no_alternate_target_or_persistent_cli_option(self):
        text = SOURCE.read_text('utf-8')
        self.assertIn("choices=['preview']", text)
        self.assertNotIn("add_argument('--target'", text)
        self.assertNotIn("add_argument('--approve", text)

    def test_persistent_writer_is_absent(self):
        for name in ('install_core', 'safe_dacl', 'native_move_new', 'install_user', 'install_inactive'):
            self.assertFalse(hasattr(mod, name), name)

    def test_complete_17_file_inventory(self):
        self.assertEqual(len(self.expected), 16)
        report = self.make_report()
        self.assertEqual(len(report['files']), 16)
        self.assertEqual(report['file_count_if_installed'], 17)

    def test_preview_target_exact_and_versioned(self):
        report = self.make_report()
        self.assertEqual(Path(report['target']).name, 'OnyxCore-v100-Inactive-Stable100')
        self.assertNotIn('OnyxCore\\', report['target'])

    def test_plan_digest_is_stable(self):
        with tempfile.TemporaryDirectory(prefix='OnyxV100-S5D-') as root:
            p1 = mod.target_report(Path(root), self.expected, self.cfg, user=self.user)
            p2 = mod.target_report(Path(root), self.expected, self.cfg, user=self.user)
        self.assertEqual(p1, p2)
        digest = p1.pop('plan_sha256')
        self.assertEqual(digest, mod.sha(mod.canonical(p1)))

    def test_input_hashes_are_recorded(self):
        report = self.make_report()
        for row in report['files']:
            self.assertEqual(row['sha256'], mod.sha(self.expected[row['path']]))
            self.assertEqual(row['size'], len(self.expected[row['path']]))

    def test_inactive_flags_are_explicit(self):
        report = self.make_report()
        for key in ('credential_enrolled', 'credentials_read', 'task_or_service_changed',
                    'native_acl_changed', 'publication_performed', 'persistent_installation_authorized'):
            self.assertIs(report[key], False, key)
        self.assertIs(report['requires_separate_one_shot_authorization'], True)
        self.assertIs(report['pending_native_user_publication_validation'], True)

    def test_machine_config_is_preserved(self):
        report = self.make_report()
        self.assertEqual(report['collector_source'], 'SQUALL')
        self.assertEqual(report['receiver_host'], 'svr-onyxcore.local')
        self.assertEqual(report['gateway_port'], 18976)

    def test_rejected_existing_target_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix='OnyxV100-S5D-') as root:
            dest = Path(root) / mod.TARGET_NAME
            dest.mkdir()
            (dest / 'KEEP').write_text('witness')
            with self.assertRaises(ValueError):
                mod.target_report(Path(root), self.expected, self.cfg, user=self.user)
            self.assertEqual((dest / 'KEEP').read_text(), 'witness')

    def test_symlink_target_refused_if_available(self):
        with tempfile.TemporaryDirectory(prefix='OnyxV100-S5D-') as root:
            witness = Path(root) / 'witness'
            witness.mkdir()
            target = Path(root) / mod.TARGET_NAME
            try:
                target.symlink_to(witness, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('symlink creation unavailable')
            with self.assertRaises(ValueError):
                mod.target_report(Path(root), self.expected, self.cfg, user=self.user)

    def test_missing_dashboard_refused(self):
        payload = dict(self.expected)
        del payload['windows/gateway/gateway-dashboard-v100.html']
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(mod.PreflightRefused):
                mod.target_report(Path(root), payload, self.cfg, user=self.user)

    def test_missing_isolation_manifest_refused(self):
        payload = dict(self.expected)
        del payload['runtime-isolation-manifest.json']
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(mod.PreflightRefused):
                mod.target_report(Path(root), payload, self.cfg, user=self.user)

    def test_missing_host_config_refused(self):
        payload = dict(self.expected)
        del payload['config/windows.config.json']
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(mod.PreflightRefused):
                mod.target_report(Path(root), payload, self.cfg, user=self.user)

    def test_extra_payload_refused(self):
        payload = dict(self.expected)
        payload['extra.bin'] = b'x'
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(mod.PreflightRefused):
                mod.target_report(Path(root), payload, self.cfg, user=self.user)

    def test_malicious_relative_payload_refused(self):
        payload = dict(self.expected)
        last = next(iter(payload))
        payload['../unsafe'] = payload.pop(last)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(mod.PreflightRefused):
                mod.target_report(Path(root), payload, self.cfg, user=self.user)

    def test_wrong_bundle_refused(self):
        with tempfile.TemporaryDirectory() as root:
            changed = Path(root) / 'bad.zip'
            changed.write_bytes(b'corrupt')
            with self.assertRaises((ValueError, OSError)):
                self.s5c.expected_install(changed, DASH, SETTINGS, s4c=self.s4c)

    def test_wrong_dashboard_refused(self):
        with tempfile.TemporaryDirectory() as root:
            changed = Path(root) / 'bad.html'
            changed.write_bytes(b'wrong')
            with self.assertRaises((ValueError, OSError)):
                self.s5c.expected_install(BUNDLE, changed, SETTINGS, s4c=self.s4c)

    def test_cli_rejects_install_mode(self):
        r = subprocess.run([sys.executable, '-I', '-B', str(SOURCE), '--mode', 'install-user'],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('invalid choice', r.stderr)

    def test_cli_rejects_target_switch(self):
        r = subprocess.run([sys.executable, '-I', '-B', str(SOURCE),
                            '--bundle', str(BUNDLE), '--dashboard', str(DASH),
                            '--receiver-host', 'svr-onyxcore.local', '--source', 'SQUALL',
                            '--network-adapter', 'Ethernet', '--usb-adapter', 'Ethernet 3',
                            '--gateway-port', '18976', '--target', 'C:\\unexpected'],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('unrecognized arguments', r.stderr)

    @unittest.skipUnless(sys.platform == 'win32', 'native Windows Known Folder acceptance on SQUALL')
    def test_native_windows_preview_is_readonly(self):
        root = self.user.native_user_root()
        target = root / mod.TARGET_NAME
        self.assertFalse(target.exists())
        result = mod.preview(BUNDLE, DASH, SETTINGS)
        self.assertEqual(result['operation'], 'M2_S5D_USER_INSTALL_PREFLIGHT_ONLY')
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
