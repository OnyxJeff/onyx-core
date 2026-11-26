#!/usr/bin/env python3
"""M2-S3A: pure offline Windows/Linux acceptance for inactive Pi sandbox installer."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

SOURCE = Path(__file__).resolve().parents[2] / 'tools' / 'installation' / 'pi' / 'onyx_v100_pi_sandbox_install.py'
spec = importlib.util.spec_from_file_location('onyx_v100_pi_sandbox_install', SOURCE)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
BUNDLE = Path(os.environ['ONYX_V100_BUNDLE']) if 'ONYX_V100_BUNDLE' in os.environ else None


def settings(**changes):
    s = {'interface': 'usb0', 'ipv4_subnet': '192.168.137.0/24', 'source': 'SQUALL',
         'port': 8765, 'state_dir': '/var/lib/onyxcore', 'history_name': 'telemetry.db',
         'snapshot_name': 'latest-snapshot.json'}
    s.update(changes)
    return s


def target():
    return Path(tempfile.gettempdir()) / ('OnyxV100-Pi-test-' + uuid.uuid4().hex)


class PiSandboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if BUNDLE is None or not BUNDLE.is_file():
            raise AssertionError('Set ONYX_V100_BUNDLE to verified M2-S1 candidate before running tests')
        assert hashlib.sha256(BUNDLE.read_bytes()).hexdigest() == installer.BUNDLE_SHA256

    def test_preview_is_readonly_cross_platform(self):
        t = target()
        plan, *_ = installer.prepare(BUNDLE, t, settings())
        self.assertEqual(plan['operation'], 'PI_INACTIVE_SANDBOX_PREVIEW')
        self.assertFalse(plan['installation_performed'])
        self.assertFalse(plan['activation_performed'])
        self.assertFalse(plan['native_armv6_verified'])
        self.assertFalse(plan['credentials_accessed'])
        self.assertFalse(t.exists())

    def test_selected_pi_payload_and_complete_manifest(self):
        payload, manifest = installer.inspect_bundle(BUNDLE)
        self.assertEqual(len(payload), 11)
        self.assertTrue(all(k.startswith(('docs/v1.0.0/examples/', 'tools/installation/', 'pi/')) for k in payload))
        self.assertFalse(any('windows/' in k for k in payload))
        parsed = json.loads(manifest)
        self.assertEqual(parsed['file_count'], 20)
        self.assertIn('pi/services/receiver/receiver_v100.py', payload)
        self.assertIn('pi/services/receiver/integrated_store_v100.py', payload)

    def test_source_and_subnet_are_host_configured(self):
        cfg = installer.validated_config(BUNDLE, **settings(source='MyWindowsPC',
                                                        ipv4_subnet='10.12.194.0/28',
                                                        state_dir='/srv/my-onyx-state'))
        self.assertEqual(cfg['receiver']['source'], 'MyWindowsPC')
        self.assertEqual(cfg['receiver']['ipv4_subnet'], '10.12.194.0/28')

    def test_wrong_source_or_state_path_refused(self):
        for change in ({'source': 'SQUALL extra'}, {'state_dir': '/etc/onyxcore'},
                       {'port': 80}, {'ipv4_subnet': '8.8.8.0/24'}):
            with self.subTest(change=change):
                with self.assertRaises(installer.InstallRefused):
                    installer.validated_config(BUNDLE, **settings(**change))

    def test_refuse_production_or_non_temp_targets(self):
        for t in (Path('/opt/onyxcore/v1.0.0'), Path('/var/lib/onyxcore/new'),
                  Path(tempfile.gettempdir()) / 'OnyxV100-Pi-../bad'):
            with self.subTest(t=str(t)):
                with self.assertRaises(installer.InstallRefused):
                    installer.check_target(t)

    def test_no_overwrite_existing_target(self):
        with tempfile.TemporaryDirectory(prefix='OnyxV100-Pi-test-') as directory:
            with self.assertRaises(installer.InstallRefused):
                installer.check_target(Path(directory))

    def test_refuse_modified_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'fake.zip'
            path.write_bytes(BUNDLE.read_bytes() + b'tampered')
            with self.assertRaisesRegex(installer.InstallRefused, 'SHA256'):
                installer.inspect_bundle(path)

    def test_refuse_symlink_input_when_available(self):
        with tempfile.TemporaryDirectory() as d:
            link = Path(d) / 'bundle.zip'
            try:
                link.symlink_to(BUNDLE)
            except (OSError, NotImplementedError):
                self.skipTest('symlink unavailable on this host')
            with self.assertRaises(installer.InstallRefused):
                installer.inspect_bundle(link)

    def test_two_explicit_approval_flags_required(self):
        for flags in (['--install'], ['--approve-inactive']):
            t = target()
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                result = installer.main(['--bundle', str(BUNDLE), '--target', str(t),
                                         '--source', 'SQUALL'] + flags)
            self.assertEqual(result, 2)
            self.assertFalse(t.exists())
            self.assertIn('BOTH', err.getvalue())

    def test_native_armv6_requirement_without_test_injection(self):
        if installer._native_pi():
            self.skipTest('Native ARMv6 cannot be refused on ARMv6')
        selected, manifest = installer.inspect_bundle(BUNDLE)
        cfg = installer.validated_config(BUNDLE, **settings())
        t = target()
        with self.assertRaises(installer.InstallRefused):
            installer.create_inactive(t, selected, manifest, cfg)
        self.assertFalse(t.exists())

    def test_inactive_install_and_receipt_in_disposable_temp(self):
        import shutil
        selected, manifest = installer.inspect_bundle(BUNDLE)
        cfg = installer.validated_config(BUNDLE, **settings())
        t = target()
        try:
            result = installer.create_inactive(t, selected, manifest, cfg, native_check=lambda: True)
            self.assertEqual(result['file_count'], 14)
            verified = installer.verify_inactive(t, selected, manifest, cfg)
            self.assertEqual(verified['file_count'], 14)
            self.assertFalse(verified['service_registered'])
            receipt = json.loads((t / installer.RECEIPT_PATH).read_text('utf-8'))
            self.assertEqual(len(receipt['installed_files']), 13)
            self.assertNotIn('token', json.dumps(receipt).lower())
            self.assertEqual((t / installer.CONFIG_PATH).read_bytes(), installer.canonical_json(cfg))
        finally:
            if t.exists():
                shutil.rmtree(t)

    def test_refuse_receipt_and_payload_tampering(self):
        import shutil
        selected, manifest = installer.inspect_bundle(BUNDLE)
        cfg = installer.validated_config(BUNDLE, **settings())
        t = target()
        try:
            installer.create_inactive(t, selected, manifest, cfg, native_check=lambda: True)
            file = t / 'pi/services/receiver/receiver_v100.py'
            file.write_bytes(file.read_bytes() + b'\n# altered')
            with self.assertRaises(installer.InstallRefused):
                installer.verify_inactive(t, selected, manifest, cfg)
        finally:
            if t.exists():
                shutil.rmtree(t)

    def test_refuse_extra_file(self):
        import shutil
        selected, manifest = installer.inspect_bundle(BUNDLE)
        cfg = installer.validated_config(BUNDLE, **settings())
        t = target()
        try:
            installer.create_inactive(t, selected, manifest, cfg, native_check=lambda: True)
            (t / 'extra.txt').write_text('surprise')
            with self.assertRaises(installer.InstallRefused):
                installer.verify_inactive(t, selected, manifest, cfg)
        finally:
            if t.exists():
                shutil.rmtree(t)

    def test_install_does_not_touch_real_state_path(self):
        import shutil
        selected, manifest = installer.inspect_bundle(BUNDLE)
        cfg = installer.validated_config(BUNDLE, **settings(state_dir='/var/lib/onyxcore'))
        t = target()
        try:
            installer.create_inactive(t, selected, manifest, cfg, native_check=lambda: True)
            receipt = json.loads((t / installer.RECEIPT_PATH).read_text())
            self.assertTrue(receipt['data_directory_modified'] is False)
            self.assertFalse((t / 'var/lib/onyxcore').exists())
            self.assertFalse((t / 'etc/onyxcore').exists())
        finally:
            if t.exists():
                shutil.rmtree(t)

    def test_source_contains_no_live_service_mutators(self):
        code = SOURCE.read_text('utf-8')
        for token in ('systemctl enable', 'systemctl start', 'nmcli connection modify',
                      'sudo ', 'chmod /var/lib/onyxcore', 'os.execv(', 'subprocess.run('):
            self.assertNotIn(token, code)


if __name__ == '__main__':
    unittest.main(verbosity=2)
