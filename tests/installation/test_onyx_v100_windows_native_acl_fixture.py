#!/usr/bin/env python3
"""Offline M2-S5A tests. Never automatically run the native ACL mutator."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TOOL = ROOT / 'tools/installation/windows/onyx_v100_windows_native_acl_fixture.py'
HELPER = TOOL.with_name('Test-OnyxV100NativeAclFixture.ps1')
PREVIOUS = TOOL.with_name('onyx_v100_windows_user_integrated.py')
REFERENCE_ACL = TOOL.with_name('Set-OnyxV100UserInstallAcl.ps1')
BUNDLE = Path(os.environ.get('ONYX_V100_BUNDLE', '/mnt/data/ONYX_CORE_v1.0.0_M2S1_CoreRuntime_CANDIDATE.zip'))
DASHBOARD = Path(os.environ.get('ONYX_V100_DASHBOARD', str(ROOT / 'windows/gateway/gateway-dashboard-v100.html')))
SETTINGS = dict(receiver_host='svr-onyxcore.local', receiver_port=8765, source='SQUALL',
                network_adapter='Ethernet', usb_adapter='Ethernet 3',
                gateway_port=18976, interval=30)
spec = importlib.util.spec_from_file_location('onyx_s5a_fixture_test', TOOL)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class NativeAclFixtureTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(BUNDLE.is_file(), f'missing test bundle: {BUNDLE}')
        self.assertTrue(DASHBOARD.is_file(), f'missing test dashboard: {DASHBOARD}')

    def run_cli(self, *additional):
        args = [sys.executable, '-I', '-B', str(TOOL), '--bundle', str(BUNDLE),
                '--dashboard', str(DASHBOARD), '--receiver-host', 'svr-onyxcore.local',
                '--source', 'SQUALL', '--network-adapter', 'Ethernet',
                '--usb-adapter', 'Ethernet 3', '--gateway-port', '18976', *additional]
        return subprocess.run(args, text=True, capture_output=True, timeout=25)

    def test_committed_s4c_source_is_pinned(self):
        self.assertEqual(mod.digest(PREVIOUS.read_bytes()), mod.S4C_SHA256)
        s4c = mod.load_reviewed()
        self.assertEqual(s4c.SOURCE_COMMIT, '8df66f772d5b15464290b7040621e9b03635d49e')

    def test_accepted_original_helper_is_pinned(self):
        self.assertEqual(mod.digest(REFERENCE_ACL.read_bytes()), mod.REVIEWED_ACL_SHA256)
        self.assertEqual(mod.validated_fixture_helper(), HELPER)

    def test_original_unsafe_acl_sequence_never_used_by_dacl_only_helper(self):
        original = REFERENCE_ACL.read_text('utf-8')
        safe = HELPER.read_text('utf-8')
        self.assertIn('/inheritance:r /T', original)
        self.assertIn('/grant:r', original)
        self.assertNotIn('icacls.exe', safe)
        self.assertNotIn('/inheritance:r', safe)
        self.assertIn('[IO.Directory]::SetAccessControl($NodePath,$Acl)', safe)
        self.assertIn('[IO.File]::SetAccessControl($NodePath,$Acl)', safe)
        self.assertNotIn('Set-Acl -LiteralPath', safe)
        self.assertEqual(mod.validated_fixture_helper(), HELPER)

    def test_each_node_receives_complete_dacl_before_publication(self):
        source = HELPER.read_text('utf-8')
        self.assertIn('SetAccessRuleProtection($true,$false)', source)
        self.assertIn('[Security.AccessControl.DirectorySecurity]::new()', source)
        self.assertIn('[Security.AccessControl.FileSecurity]::new()', source)
        self.assertIn('[IO.Directory]::SetAccessControl($NodePath,$Acl)', source)
        self.assertIn('[IO.File]::SetAccessControl($NodePath,$Acl)', source)
        self.assertIn('$Acl.AddAccessRule($Rule)', source)
        self.assertIn('Sort-Object @{ Expression = { $_.FullName.Length }; Descending = $true }', source)
        self.assertIn('Assert-SafeAcl $Node.FullName', source)
        self.assertIn('Get-ChildItem -LiteralPath $Path -Recurse', source)
        self.assertNotIn('icacls.exe', source)
        self.assertNotIn('Set-Acl -LiteralPath', source)

    def test_writer_does_not_roundtrip_existing_security_descriptor(self):
        source = HELPER.read_text('utf-8')
        writer = source.split('function Set-SafeAcl', 1)[1].split("if ($Mode -ceq 'Harden')", 1)[0]
        self.assertNotIn('Get-Acl -LiteralPath', writer)
        self.assertNotIn('Set-Acl -LiteralPath', writer)
        self.assertIn('[IO.Directory]::SetAccessControl($NodePath,$Acl)', writer)
        self.assertIn('[IO.File]::SetAccessControl($NodePath,$Acl)', writer)

    def test_pinned_helper_rejects_old_unsafe_version(self):
        with mock.patch.object(mod, 'ACL_FIXTURE_SHA256',
                               mod.digest(REFERENCE_ACL.read_bytes())):
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                mod.validated_fixture_helper()

    def test_native_helper_errors_preserve_exit_information(self):
        with mock.patch.object(mod, 'validated_fixture_helper', return_value=HELPER), \
             mock.patch.object(mod.subprocess, 'run') as runner:
            runner.return_value.returncode = 1
            runner.return_value.stdout = ''
            runner.return_value.stderr = 'DACL-only SetAccessControl: Access denied at Temp fixture'
            with self.assertRaisesRegex(ValueError, 'exit=1.*Access denied'):
                mod._native_acl(HELPER, 'Harden', Path('fixture'), Path('fixture/staging'))

    def test_helper_is_temp_only_and_not_persistent(self):
        source = HELPER.read_text('utf-8')
        self.assertIn('GetTempPath()', source)
        self.assertIn('OnyxV100-S5A-ACL-', source)
        self.assertIn('.s5a-fixture.marker', source)
        self.assertNotIn('GetFolderPath(\'LocalApplicationData\')', source)
        for mutation in ('register-scheduledtask', 'new-service', 'set-service', 'start-service', 'winreg'):
            self.assertNotIn(mutation, source.lower())

    def test_full_integrated_runtime_file_count(self):
        s4c = mod.load_reviewed()
        expected, cfg = s4c.expected_user_install(BUNDLE, DASHBOARD, SETTINGS)
        self.assertEqual(len(expected), 16)
        self.assertEqual(cfg['gateway']['port'], 18976)
        self.assertEqual(mod.digest(expected['runtime-isolation-manifest.json']),
                         s4c.ISOLATION_SHA256)
        self.assertEqual(expected['windows/gateway/gateway-dashboard.html'],
                         expected['windows/gateway/gateway-dashboard-v100.html'])

    def test_actual_runtime_is_separate_from_legacy_store(self):
        expected, _ = mod.load_reviewed().expected_user_install(BUNDLE, DASHBOARD, SETTINGS)
        collector = expected['windows/collector/Send-OnyxTelemetry-v100.ps1']
        self.assertIn(b'OnyxCore-v100', collector)
        self.assertNotIn(b'Local\\OnyxCoreCollector', collector)
        launcher = expected['tools/installation/windows/Invoke-OnyxV100WindowsRuntime.ps1']
        self.assertIn(b'OnyxCore-v100', launcher)
        self.assertNotIn(b'OnyxCore\\collector-token.dpapi', launcher)

    def test_gateway_reserved_ports_refused(self):
        s4c = mod.load_reviewed()
        for port in (18766, 18767, 18768, 18769):
            with self.subTest(port=port), self.assertRaises(ValueError):
                s4c.expected_user_install(BUNDLE, DASHBOARD, {**SETTINGS, 'gateway_port':port})

    def test_bad_bundle_refused(self):
        with tempfile.TemporaryDirectory() as root:
            bad=Path(root)/'wrong.zip'; bad.write_bytes(BUNDLE.read_bytes()+b'x')
            with self.assertRaises(ValueError):
                mod.load_reviewed().expected_user_install(bad, DASHBOARD, SETTINGS)

    def test_bad_dashboard_refused(self):
        with tempfile.TemporaryDirectory() as root:
            bad=Path(root)/'wrong.html'; bad.write_bytes(DASHBOARD.read_bytes()+b'x')
            with self.assertRaises(ValueError):
                mod.load_reviewed().expected_user_install(BUNDLE, bad, SETTINGS)

    def test_modified_prior_dependency_refused(self):
        with mock.patch.object(mod, 'S4C_SHA256', '0'*64):
            with self.assertRaisesRegex(ValueError, 'differs from committed source'):
                mod.load_reviewed()

    def test_modified_native_helper_refused(self):
        with mock.patch.object(mod, 'ACL_FIXTURE_SHA256', '0'*64):
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                mod.validated_fixture_helper()

    def test_no_native_acl_writes_behind_default_cli(self):
        if sys.platform != 'win32':
            res=self.run_cli()
            self.assertNotEqual(res.returncode,0)
            self.assertIn('STOP:',res.stderr)
        else:
            res=self.run_cli()
            self.assertEqual(res.returncode,0,res.stderr)
            report=json.loads(res.stdout)
            self.assertEqual(report['operation'],'WINDOWS_S5A_USER_PREVIEW')
            self.assertEqual(report['file_count_if_installed'],17)
            self.assertFalse(report['installation_performed'])
            self.assertFalse(report['acl_changed'])
            self.assertFalse(Path(report['target']).exists())

    def test_native_fixture_two_approvals_required(self):
        for flags in ((), ('--approve-temp-acl-test',), ('--approve-inactive-fixture',)):
            with self.subTest(flags=flags):
                res=self.run_cli('--mode', 'native-temp-acl', *flags)
                self.assertEqual(res.returncode,2)
                self.assertIn('STOP:',res.stderr)

    def test_nonwindows_native_fixture_refused(self):
        if sys.platform != 'win32':
            res=self.run_cli('--mode','native-temp-acl', '--approve-temp-acl-test',
                             '--approve-inactive-fixture')
            self.assertEqual(res.returncode,2)
            self.assertIn('native Windows',res.stderr)

    def test_public_cli_has_no_persistent_install_mode(self):
        res=self.run_cli('--mode', 'install-user')
        self.assertNotEqual(res.returncode,0)
        self.assertNotIn('native-temp-acl',res.stdout)
        self.assertNotIn('install-user',TOOL.read_text('utf-8').split("choices=('preview-user', 'native-temp-acl')")[0])

    def test_previewer_refuses_approval_flags(self):
        res=self.run_cli('--approve-temp-acl-test')
        self.assertEqual(res.returncode,2)
        self.assertIn('STOP:',res.stderr)

    def test_arbitrary_user_target_is_not_cli_argument(self):
        res=self.run_cli('--target', str(Path(tempfile.gettempdir())/'abc'))
        self.assertNotEqual(res.returncode,0)

    def test_temp_fixture_guard_rejects_unrelated_root(self):
        with tempfile.TemporaryDirectory(prefix='unrelated-S5A-') as temp:
            root=Path(temp)
            with self.assertRaisesRegex(ValueError, 'direct OS Temp'):
                mod.guard_fixture(root,root/('OnyxCore-v100-Inactive-S5A'+uuid.uuid4().hex))

    def test_fixture_guard_rejects_invalid_marker(self):
        root=Path(tempfile.gettempdir())/('OnyxV100-S5A-ACL-'+uuid.uuid4().hex)
        root.mkdir()
        try:
            target=root/('OnyxCore-v100-Inactive-S5A'+uuid.uuid4().hex)
            with self.assertRaisesRegex(ValueError,'marker missing'):
                mod.guard_fixture(root,target)
            (root/'.s5a-fixture.marker').write_bytes(b'not approved')
            with self.assertRaisesRegex(ValueError,'marker missing'):
                mod.guard_fixture(root,target)
        finally:
            (root/'.s5a-fixture.marker').unlink(missing_ok=True)
            root.rmdir()

    def test_fixture_guard_accepts_only_signed_temp_root(self):
        root=Path(tempfile.gettempdir())/('OnyxV100-S5A-ACL-'+uuid.uuid4().hex)
        root.mkdir()
        try:
            target=root/('OnyxCore-v100-Inactive-S5A'+uuid.uuid4().hex)
            (root/'.s5a-fixture.marker').write_bytes(mod.MARKER)
            mod.guard_fixture(root,target)
            with self.assertRaises(ValueError):
                mod.guard_fixture(root,root/'OnyxCore-v100-Inactive-ZERO')
        finally:
            (root/'.s5a-fixture.marker').unlink()
            root.rmdir()

    def test_native_helper_not_invoked_by_offline_test(self):
        with mock.patch.object(mod, '_native_acl', side_effect=AssertionError('native ACL called')):
            self.test_full_integrated_runtime_file_count()
            self.test_no_native_acl_writes_behind_default_cli()

    @unittest.skipUnless(sys.platform == 'win32','Windows native LocalAppData preview')
    def test_native_preview_is_no_write(self):
        plan=mod.preview(BUNDLE,DASHBOARD,SETTINGS)
        self.assertEqual(plan['file_count_if_installed'],17)
        self.assertFalse(Path(plan['target']).exists())
        self.assertFalse(plan['credential_enrolled'])


if __name__=='__main__':
    unittest.main(verbosity=2)
