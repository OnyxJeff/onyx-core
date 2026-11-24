#!/usr/bin/env python3
"""M2-S5E: synthetic contract tests. Native user installation NEVER exercised."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'tools/installation/windows/onyx_v100_windows_one_shot.py'
BUNDLE = Path(os.environ.get('ONYX_V100_BUNDLE', '/mnt/data/ONYX_CORE_v1.0.0_M2S1_CoreRuntime_CANDIDATE.zip'))
DASHBOARD = Path(os.environ.get('ONYX_V100_DASHBOARD', str(ROOT / 'windows/gateway/gateway-dashboard-v100.html')))
spec = importlib.util.spec_from_file_location('onyx_s5e_under_test', SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class OneShotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BUNDLE.is_file() or not DASHBOARD.is_file():
            raise RuntimeError('Exact bundle and dashboard must be staged for tests')
        cls.s5d = mod.reviewed_s5d()
        cls.s5c = cls.s5d.reviewed_s5c()
        cls.s4c, cls.r3, _ = cls.s5c.reviewed()
        cls.user = cls.s4c.reviewed_modules()[2]
        cls.expected, cls.cfg = cls.s5c.expected_install(BUNDLE, DASHBOARD, mod.SETTINGS, s4c=cls.s4c)

    def synthetic(self):
        td = tempfile.TemporaryDirectory(prefix='OnyxV100-S5E-Synthetic-')
        root = Path(td.name)
        plan = self.s5d.target_report(root, self.expected, self.cfg, user=self.user)
        return td, root, plan

    def checked(self, plan, root):
        with mock.patch.object(mod, 'PLAN_SHA256', plan['plan_sha256']):
            return mod.validate_plan(plan, self.expected, self.cfg, root=root, user=self.user)

    def test_reviewed_s5d_source_sha256(self):
        p = SOURCE.with_name('onyx_v100_windows_user_preflight.py')
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), mod.S5D_SHA256)

    def test_frozen_m2_and_target(self):
        self.assertEqual(mod.M2_HEAD, self.s5d.M2_HEAD)
        self.assertEqual(mod.TARGET_NAME, self.s5d.TARGET_NAME)
        self.assertEqual(len(mod.PLAN_SHA256), 64)

    def test_integrated_source_and_helper_pinned(self):
        self.assertEqual(len(self.s5c.reviewed()), 3)
        self.assertEqual(self.s5c.sha(self.s5c.helper_path().read_bytes()), self.s5c.SAFE_HELPER_SHA)

    def test_exact_17_file_inventory(self):
        self.assertEqual(len(self.expected), 16)
        self.assertIn('config/windows.config.json', self.expected)
        self.assertIn('runtime-isolation-manifest.json', self.expected)
        self.assertIn('windows/gateway/gateway-dashboard-v100.html', self.expected)

    def test_plan_matches_payload_in_synthetic_root(self):
        td, root, plan = self.synthetic()
        with td:
            self.assertEqual(self.checked(plan, root), root / mod.TARGET_NAME)
            self.assertFalse((root / mod.TARGET_NAME).exists())

    def test_wrong_plan_digest_refused(self):
        td, root, plan = self.synthetic()
        with td:
            plan['plan_sha256'] = '0' * 64
            with self.assertRaises(mod.OneShotRefused):
                self.checked(plan, root)

    def test_modified_plan_without_rehash_refused(self):
        td, root, plan = self.synthetic()
        with td:
            plan['collector_source'] = 'OTHER'
            with self.assertRaises(mod.OneShotRefused):
                self.checked(plan, root)

    def test_wrong_target_refused(self):
        td, root, plan = self.synthetic()
        with td:
            plan['target'] = str(root / 'OnyxCore-v100-Inactive-Attacker99')
            with self.assertRaises(mod.OneShotRefused):
                self.checked(plan, root)

    def test_existing_target_preserved(self):
        td, root, plan = self.synthetic()
        with td:
            target = root / mod.TARGET_NAME
            target.mkdir()
            (target / 'witness.txt').write_text('KEEP')
            with self.assertRaises(ValueError):
                self.checked(plan, root)
            self.assertEqual((target / 'witness.txt').read_text(), 'KEEP')

    def test_wrong_payload_refused(self):
        td, root, plan = self.synthetic()
        with td:
            altered = dict(self.expected)
            altered['config/windows.config.json'] += b'changed'
            with mock.patch.object(mod, 'PLAN_SHA256', plan['plan_sha256']):
                with self.assertRaises(mod.OneShotRefused):
                    mod.validate_plan(plan, altered, self.cfg, root=root, user=self.user)

    def test_missing_payload_refused(self):
        td, root, plan = self.synthetic()
        with td:
            altered = dict(self.expected)
            del altered['runtime-isolation-manifest.json']
            with mock.patch.object(mod, 'PLAN_SHA256', plan['plan_sha256']):
                with self.assertRaises(mod.OneShotRefused):
                    mod.validate_plan(plan, altered, self.cfg, root=root, user=self.user)

    def test_changed_config_refused(self):
        td, root, plan = self.synthetic()
        with td:
            cfg = copy.deepcopy(self.cfg)
            cfg['gateway']['port'] = 18977
            with mock.patch.object(mod, 'PLAN_SHA256', plan['plan_sha256']):
                with self.assertRaises(mod.OneShotRefused):
                    mod.validate_plan(plan, self.expected, cfg, root=root, user=self.user)

    def test_s5d_plan_must_have_inert_flags(self):
        td, root, plan = self.synthetic()
        with td:
            plan['publication_performed'] = True
            with self.assertRaises(mod.OneShotRefused):
                self.checked(plan, root)

    def test_actual_planned_digest_cannot_be_replaced_without_explicit_test_patch(self):
        td, root, plan = self.synthetic()
        with td:
            with self.assertRaises(mod.OneShotRefused):
                mod.validate_plan(plan, self.expected, self.cfg, root=root, user=self.user)

    def test_cli_has_no_persistent_install_mode(self):
        r = subprocess.run([sys.executable, '-I', '-B', str(SOURCE), '--mode', 'install-user'],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('invalid choice', r.stderr)

    def test_cli_rejects_approval_switches(self):
        r = subprocess.run([sys.executable, '-I', '-B', str(SOURCE),
                            '--bundle', str(BUNDLE), '--dashboard', str(DASHBOARD),
                            '--approve-persistent'], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('unrecognized arguments', r.stderr)

    def test_cli_no_arbitrary_target_switch(self):
        r = subprocess.run([sys.executable, '-I', '-B', str(SOURCE),
                            '--bundle', str(BUNDLE), '--dashboard', str(DASHBOARD),
                            '--target', 'C:\\arbitrary'], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('unrecognized arguments', r.stderr)

    def test_missing_authorization_refuses_before_prepare(self):
        with mock.patch.object(mod, 'prepare', side_effect=AssertionError('read too soon')):
            with self.assertRaises(mod.OneShotRefused):
                mod.execute_only_from_future_authorized_runner(BUNDLE, DASHBOARD)

    def test_wrong_declared_target_refuses_before_prepare(self):
        with mock.patch.object(mod, 'prepare', side_effect=AssertionError('read too soon')):
            with self.assertRaises(mod.OneShotRefused):
                mod.execute_only_from_future_authorized_runner(
                    BUNDLE, DASHBOARD, authorization={'target': 'C:\\wrong'})

    def test_authorization_requires_exact_fields(self):
        target = Path('C:/Synthetic/OnyxCore-v100-Inactive-Stable100')
        valid = {'operation': 'M2_S5E_SEPARATELY_AUTHORIZED_ONE_SHOT',
                 'plan_sha256': mod.PLAN_SHA256, 'target': str(target),
                 'approve_persistent': True, 'approve_inactive': True,
                 'approve_no_replace': True}
        mod._authorization_allowed(valid, target=target)
        for key in valid:
            altered = dict(valid)
            altered.pop(key)
            with self.assertRaises(mod.OneShotRefused):
                mod._authorization_allowed(altered, target=target)
        invalid = dict(valid)
        invalid['approve_persistent'] = 1
        with self.assertRaises(mod.OneShotRefused):
            mod._authorization_allowed(invalid, target=target)

    def test_no_unapproved_native_or_credential_calls_in_public_cli(self):
        text = SOURCE.read_text('utf-8')
        self.assertIn("choices=('preview',)", text)
        for forbidden in ('schtasks', 'reg.exe', 'Enable-ScheduledTask',
                          'Set-OnyxV100UserInstallAcl.ps1', 'ics_startup_recovery',
                          'collector-token.dpapi'):
            self.assertNotIn(forbidden, text)

    def test_source_no_unsafe_fallback_and_retains_evidence(self):
        text = SOURCE.read_text('utf-8')
        self.assertIn('s5c.install_core(', text)
        self.assertIn('approve_no_replace=True', text)
        self.assertNotIn('shutil.rmtree', text)
        self.assertNotIn('os.replace(', text)
        self.assertNotIn('staging.rename(', text)

    def test_wrong_bundle_refused(self):
        with tempfile.TemporaryDirectory() as td:
            wrong = Path(td) / 'wrong.zip'
            wrong.write_bytes(b'wrong')
            with self.assertRaises((ValueError, OSError)):
                self.s5c.expected_install(wrong, DASHBOARD, mod.SETTINGS, s4c=self.s4c)

    @unittest.skipUnless(sys.platform == 'win32', 'native Windows Known Folder preview runs on SQUALL')
    def test_native_user_preview_is_readonly_and_pinned(self):
        target = self.user.native_user_root() / mod.TARGET_NAME
        self.assertFalse(target.exists())
        result = mod.preview(BUNDLE, DASHBOARD)
        self.assertEqual(result['s5d_plan_sha256'], mod.PLAN_SHA256)
        self.assertEqual(result['target'], str(target))
        self.assertFalse(result['persistent_installation_performed'])
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
