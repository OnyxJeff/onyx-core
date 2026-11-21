#!/usr/bin/env python3
"""M2-S4C purely offline integration regression: synthetic ACLs only."""
from __future__ import annotations
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

TOOL = Path(__file__).resolve().parents[2] / 'tools/installation/windows/onyx_v100_windows_user_integrated.py'
BUNDLE = Path(os.environ.get('ONYX_V100_BUNDLE',''))
DASHBOARD = Path(os.environ.get('ONYX_V100_DASHBOARD',''))
spec = importlib.util.spec_from_file_location('onyx_s4c', TOOL)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
SETTINGS = dict(receiver_host='svr-onyxcore.local', receiver_port=8765,
                source='SQUALL', network_adapter='Ethernet', usb_adapter='Ethernet 3',
                gateway_port=18976, interval=30)


class UserIntegratedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BUNDLE.is_file() or not DASHBOARD.is_file():
            raise RuntimeError('Verified ONYX_V100_BUNDLE and ONYX_V100_DASHBOARD required')
        cls.modules = mod.reviewed_modules()
        cls.expected, cls.config = mod.expected_user_install(BUNDLE, DASHBOARD, SETTINGS,
                                                              loaded=cls.modules)

    def setUp(self):
        self.root = Path(tempfile.gettempdir()) / ('OnyxV100-S4C-TestRoot-' + uuid.uuid4().hex)
        self.root.mkdir()
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.target = self.root / ('OnyxCore-v100-Inactive-S4C' + uuid.uuid4().hex)
        self.acl_calls = []

    def fake_acl(self, staging):
        self.assertEqual(staging.parent, self.root)
        self.assertTrue(staging.is_dir())
        self.acl_calls.append(staging)

    def publish(self):
        return mod.synthetic_publish(BUNDLE,DASHBOARD,self.root,self.target,SETTINGS,
                                     simulated_acl=self.fake_acl)

    def cli(self,*args):
        return subprocess.run([sys.executable,'-I','-B',str(TOOL),
             '--bundle',str(BUNDLE),'--dashboard',str(DASHBOARD),
             '--target',str(self.target),'--receiver-host','svr-onyxcore.local',
             '--source','SQUALL','--network-adapter','Ethernet',
             '--usb-adapter','Ethernet 3','--gateway-port','18976',*args],
             capture_output=True,text=True,timeout=30)

    def test_prior_dependencies_pinned(self):
        s4b = self.modules[0]
        self.assertEqual(mod.sha(s4b.__file__ and Path(s4b.__file__).read_bytes()),mod.S4B_SHA256)
        self.assertEqual(mod.sha(BUNDLE.read_bytes()),mod.BUNDLE_SHA256)
        self.assertEqual(mod.sha(DASHBOARD.read_bytes()),mod.DASHBOARD_SHA256)

    def test_expected_exact_17_file_inventory(self):
        self.assertEqual(len(self.expected),16)
        self.assertEqual(self.expected['runtime-isolation-manifest.json'],
                         self.modules[0].integrated_payload(BUNDLE,DASHBOARD,SETTINGS,
                             loaded=self.modules[1:])[0][mod.ISOLATION_MANIFEST])
        self.assertEqual(mod.sha(self.expected['runtime-isolation-manifest.json']),
                         mod.ISOLATION_SHA256)

    def test_config_host_specific(self):
        self.assertEqual(self.config['collector']['source'],'SQUALL')
        self.assertEqual(self.config['gateway']['port'],18976)
        self.assertEqual(self.config['receiver']['host'],'svr-onyxcore.local')

    def test_no_legacy_token_mutex_in_expected_assets(self):
        for name in self.modules[0].ISOLATED_PATHS:
            self.assertNotIn(b'OnyxCore\\collector-token.dpapi',self.expected[name])
            self.assertNotIn(b"'Local\\OnyxCoreCollector'",self.expected[name])
        self.assertIn(b"'Local\\OnyxCoreV100Collector'",
                      self.expected['windows/collector/Send-OnyxTelemetry-v100.ps1'])

    def test_preview_is_read_only_and_complete(self):
        report = mod.preview_user(BUNDLE,DASHBOARD,self.target,SETTINGS,root=self.root)
        self.assertEqual(report['operation'],'WINDOWS_V100_INTEGRATED_USER_PREVIEW_S4C')
        self.assertEqual(report['file_count_if_installed'],17)
        for field in ('installation_performed','acl_changed','credential_read',
                      'credential_enrolled','activation_performed','service_or_task_changes'):
            self.assertFalse(report[field])
        self.assertEqual(list(self.root.iterdir()),[])

    def test_synthetic_install_receipt_exact(self):
        report=self.publish()
        self.assertEqual(report['file_count'],17)
        self.assertTrue(report['synthetic_acl_only'])
        self.assertFalse(report['native_acl_verified'])
        self.assertEqual(len(self.acl_calls),1)
        receipt=json.loads((self.target/'installation-receipt.json').read_bytes())
        self.assertEqual(len(receipt['installed_files']),16)
        self.assertFalse(receipt['credential_enrolled'])
        self.assertFalse(receipt['activation_performed'])
        self.assertTrue(receipt['acl_hardened']) # simulated callback only: see report
        self.assertEqual(len([p for p in self.target.rglob('*') if p.is_file()]),17)

    def test_synthetic_receipt_isolation_and_dashboard(self):
        self.publish()
        rows={r['path']:r['sha256'] for r in json.loads(
            (self.target/'installation-receipt.json').read_bytes())['installed_files']}
        self.assertEqual(rows[mod.ISOLATION_MANIFEST],mod.ISOLATION_SHA256)
        self.assertEqual(rows['windows/gateway/gateway-dashboard.html'],mod.DASHBOARD_SHA256)
        self.assertEqual(rows['windows/gateway/gateway-dashboard-v100.html'],mod.DASHBOARD_SHA256)

    def test_no_overwrite(self):
        self.publish()
        original=(self.target/'installation-receipt.json').read_bytes()
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual((self.target/'installation-receipt.json').read_bytes(),original)

    def test_existing_unrelated_target_untouched(self):
        self.target.mkdir(); (self.target/'keep.txt').write_text('safe')
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual((self.target/'keep.txt').read_text(),'safe')
        self.assertEqual(len(self.acl_calls),0)

    def test_acl_failure_prevents_publication(self):
        def failed(_): raise ValueError('synthetic ACL refused')
        with self.assertRaisesRegex(ValueError,'synthetic ACL refused'):
            mod.synthetic_publish(BUNDLE,DASHBOARD,self.root,self.target,SETTINGS,
                                  simulated_acl=failed)
        self.assertFalse(self.target.exists())

    def test_missing_acl_callback_refused(self):
        with self.assertRaisesRegex(ValueError,'synthetic ACL callback'):
            mod.synthetic_publish(BUNDLE,DASHBOARD,self.root,self.target,SETTINGS,
                                  simulated_acl=None)

    def test_legacy_target_refused(self):
        with self.assertRaises(ValueError):
            mod.preview_user(BUNDLE,DASHBOARD,self.root/'OnyxCore',SETTINGS,root=self.root)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_synthetic_root_cannot_be_arbitrary(self):
        with tempfile.TemporaryDirectory(prefix='unapproved-s4c-') as d:
            with self.assertRaisesRegex(ValueError,'OS Temp S4C'):
                mod.synthetic_publish(BUNDLE,DASHBOARD,Path(d),Path(d)/self.target.name,
                                      SETTINGS,simulated_acl=self.fake_acl)

    def test_synthetic_root_cannot_be_localappdata(self):
        with mock.patch.object(mod.tempfile,'gettempdir',return_value=str(self.root)):
            with self.assertRaises(ValueError):
                mod.synthetic_publish(BUNDLE,DASHBOARD,self.root,self.target,SETTINGS,
                                      simulated_acl=self.fake_acl)

    def test_bad_bundle_refused(self):
        with tempfile.TemporaryDirectory() as d:
            bad=Path(d)/'bad.zip'; bad.write_bytes(BUNDLE.read_bytes()+b'x')
            with self.assertRaises(ValueError):
                mod.preview_user(bad,DASHBOARD,self.target,SETTINGS,root=self.root)
        self.assertFalse(self.target.exists())

    def test_bad_dashboard_refused(self):
        with tempfile.TemporaryDirectory() as d:
            bad=Path(d)/'bad.html';bad.write_bytes(DASHBOARD.read_bytes()+b'x')
            with self.assertRaises(ValueError):
                mod.preview_user(BUNDLE,bad,self.target,SETTINGS,root=self.root)

    def test_port_collision_rejected(self):
        for port in (18766,18767,18768,18769):
            with self.subTest(port=port), self.assertRaises(ValueError):
                mod.preview_user(BUNDLE,DASHBOARD,self.target,{**SETTINGS,'gateway_port':port},root=self.root)

    def test_tampered_synthetic_receipt_refused(self):
        self.publish()
        receipt=self.target/'installation-receipt.json'
        data=json.loads(receipt.read_bytes());data['installed_files'][0]['sha256']='0'*64
        receipt.write_bytes(mod.canonical(data))
        with self.assertRaises(ValueError):
            self.modules[2].verify_inactive(self.target,self.expected,root=self.root)

    def test_tampered_synthetic_runtime_refused(self):
        self.publish()
        p=self.target/'windows/gateway/Get-OnyxGatewayToken.ps1'
        p.write_bytes(p.read_bytes()+b'\ntampered')
        with self.assertRaises(ValueError):
            self.modules[2].verify_inactive(self.target,self.expected,root=self.root)

    def test_cli_has_no_install_switch(self):
        self.assertNotIn('--install-user',TOOL.read_text())
        self.assertNotIn('register-scheduledtask',TOOL.read_text().lower())
        self.assertNotIn('winreg.',TOOL.read_text())
        res=self.cli('--mode','install-user')
        self.assertNotEqual(res.returncode,0)
        self.assertFalse(self.target.exists())

    def test_cli_partial_approval_unrecognized(self):
        for flag in ('--approve-inactive','--approve-user-scope','--approve-enroll'):
            with self.subTest(flag=flag):
                res=self.cli(flag)
                self.assertNotEqual(res.returncode,0)
                self.assertFalse(self.target.exists())

    @unittest.skipUnless(sys.platform=='win32','Windows Known Folder native preview only')
    def test_native_windows_readonly_preview(self):
        s4b,base,user,isolation=self.modules
        native=user.native_user_root()
        target=native/('OnyxCore-v100-Inactive-S4C'+uuid.uuid4().hex)
        report=mod.preview_user(BUNDLE,DASHBOARD,target,SETTINGS)
        self.assertEqual(report['file_count_if_installed'],17)
        self.assertFalse(report['installation_performed'])
        self.assertFalse(target.exists())


if __name__=='__main__':
    unittest.main(verbosity=2)
