#!/usr/bin/env python3
"""M2-S5B: offline no-replace publication and native Windows Temp acceptance."""
import ast
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'tools/installation/windows/onyx_v100_windows_atomic_publish.py'
R3 = ROOT / 'tools/installation/windows/onyx_v100_windows_native_acl_fixture.py'
HELPER = ROOT / 'tools/installation/windows/Test-OnyxV100NativeAclFixture.ps1'
BUNDLE = Path(__file__).resolve().parent / '__no_bundle__'


def load():
    spec = importlib.util.spec_from_file_location('s5b_under_test', SRC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class NoReplaceTests(unittest.TestCase):
    def test_source_is_syntax_valid(self):
        ast.parse(SRC.read_text('utf-8'))

    def test_accepted_r3_fingerprint_exact(self):
        m = load()
        self.assertEqual(hashlib.sha256(R3.read_bytes()).hexdigest(), m.R3_SOURCE_SHA256)

    def test_reviewed_loads_original_source(self):
        self.assertEqual(load().reviewed_r3().M2_COMMIT, load().M2_HEAD)

    def test_accepted_dacl_only_helper_is_pinned(self):
        m = load()
        self.assertEqual(m.reviewed_r3().validated_fixture_helper(), HELPER)

    def test_unsafe_legacy_helper_not_called(self):
        s = SRC.read_text('utf-8')
        self.assertNotIn('protect_staging(', s)
        self.assertNotIn('Set-OnyxV100UserInstallAcl.ps1', s)
        self.assertIn("r3._native_acl(helper, 'Harden', root, staging)", s)
        self.assertIn("r3._native_acl(helper, 'Audit', root, target)", s)

    def test_win32_only_no_replace(self):
        s = SRC.read_text('utf-8')
        self.assertIn('ctypes.WinDLL(', s)
        self.assertIn('MoveFileExW', s)
        self.assertIn('func(str(staging), str(target), 0)', s)
        self.assertNotIn('os.replace(', s)
        self.assertNotIn('shutil.move(', s)
        self.assertNotIn('MOVEFILE_REPLACE_EXISTING', s.replace('# NEVER use os.replace, MoveFileExW(REPLACE_EXISTING), or a copy fallback.', ''))

    def test_native_only_public_write_mode(self):
        self.assertIn("choices=('preview', 'native-temp')", SRC.read_text('utf-8'))
        self.assertNotIn('install-user', SRC.read_text('utf-8'))
        self.assertNotIn("p.add_argument('--install-user'", SRC.read_text('utf-8'))

    def test_preview_with_flags_rejected_before_bundle(self):
        m = load()
        with patch.object(sys, 'argv', ['prog']):
            code = m.cli(['--bundle', str(BUNDLE.absolute()), '--dashboard',str(BUNDLE.absolute()),
                          '--receiver-host','svr-onyxcore.local', '--source','SQUALL',
                          '--network-adapter','Ethernet', '--usb-adapter','Ethernet 3',
                          '--gateway-port','18976', '--approve-native-temp'])
        self.assertEqual(code, 2)

    def test_native_partial_approval_rejected(self):
        m = load()
        code = m.cli(['--bundle', str(BUNDLE.absolute()), '--dashboard',str(BUNDLE.absolute()),
                      '--receiver-host','svr-onyxcore.local', '--source','SQUALL',
                      '--network-adapter','Ethernet', '--usb-adapter','Ethernet 3',
                      '--gateway-port','18976','--mode','native-temp','--approve-native-temp'])
        self.assertEqual(code, 2)

    def test_native_rejected_on_linux(self):
        if sys.platform == 'win32':
            self.skipTest('native Windows branch checked by live fixture acceptance')
        m = load()
        code = m.cli(['--bundle', str(BUNDLE.absolute()), '--dashboard',str(BUNDLE.absolute()),
                      '--receiver-host','svr-onyxcore.local', '--source','SQUALL',
                      '--network-adapter','Ethernet', '--usb-adapter','Ethernet 3',
                      '--gateway-port','18976','--mode','native-temp','--approve-native-temp',
                      '--approve-no-replace-test'])
        self.assertEqual(code, 2)

    def test_reject_r3_source_tamper(self):
        m = load()
        with patch.object(m.Path, 'with_name', autospec=True, return_value=SRC):
            with self.assertRaises(m.PublicationRefused):
                m.reviewed_r3()

    def test_no_network_or_service_mutators(self):
        s = SRC.read_text('utf-8')
        for phrase in ('schtasks', 'subprocess.run(', 'systemctl', 'TaskScheduler', 'netsh',
                       'Set-Acl', 'icacls', 'credentials_read'):
            self.assertNotIn(phrase, s)

    def test_no_cleanup_or_unapproved_delete(self):
        s = SRC.read_text('utf-8')
        for phrase in ('rmtree(', '.unlink(', 'os.remove(', 'os.replace(', '.rmdir('):
            self.assertNotIn(phrase, s)

    def test_public_cli_does_not_accept_target_path(self):
        src = SRC.read_text('utf-8')
        self.assertNotIn("p.add_argument('--target'", src)
        self.assertNotIn("p.add_argument('--root'", src)

    def test_same_volume_guard_for_publish(self):
        self.assertIn('staging.drive.lower() != target.drive.lower()', SRC.read_text('utf-8'))

    def test_receipt_and_r3_audit_required(self):
        src = SRC.read_text('utf-8')
        self.assertIn('user.verify_inactive(target, expected, root=root)', src)
        self.assertIn('17-file receipt verification', src)

    def test_native_windows_fixture(self):
        if sys.platform != 'win32':
            self.skipTest('run native Windows fixture only through guarded SQUALL acceptance')
        # This unittest must NOT create a native fixture without explicit acceptance flags.
        self.assertIn('--approve-no-replace-test', SRC.read_text('utf-8'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
