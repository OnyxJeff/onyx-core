"""ONYX CORE v0.8 release config / real-component wiring, offline only."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
MODULES = ROOT / 'windows' / 'monitoring' / 'v080'
if str(MODULES) not in sys.path:
    sys.path.insert(0, str(MODULES))
import OnyxV080ReleaseProfile as profile
import OnyxV080ReleaseBinding as binding
import OnyxWindowsRuntimeAttestation as att

SOURCE_CONFIG = ROOT / 'windows' / 'monitoring' / profile.RELEASE_CONFIG_NAME
SID = 'S-1-5-21-1-2-3-4'


class ReleaseIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = json.loads(SOURCE_CONFIG.read_text(encoding='utf-8'))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.path = self.root / 'windows' / 'monitoring' / profile.RELEASE_CONFIG_NAME
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps(self.base), encoding='utf-8')
        self.manifest = att.ReleaseManifest(
            source_commit='a' * 40,
            file_sha256={key: 'a' * 64 for key in att.REQUIRED_FILES},
            config_sha256='b' * 64,
        )
        self.wiring = binding.ReleaseWiring(self.root, self.path, self.manifest, SID, 2)

    def test_release_example_valid(self):
        parsed = profile.load_release_config(SOURCE_CONFIG)
        self.assertEqual(parsed['profile'], 'release')
        self.assertEqual(parsed['monitoring_interval_seconds'], 120)
        self.assertEqual(parsed['state_dir'], profile.RELEASE_STATE)

    def test_v070_release_profile_rejected(self):
        data = copy.deepcopy(self.base)
        data['state_dir'] = r'%LOCALAPPDATA%\OnyxCore-v070-Release\Monitoring'
        with self.assertRaises(profile.ReleaseProfileRefused):
            profile.validate_release_config(data)

    def test_dev_profile_refused(self):
        data = copy.deepcopy(self.base)
        data['profile'] = 'development'
        with self.assertRaises(profile.ReleaseProfileRefused):
            profile.validate_release_config(data)

    def test_no_mutation_of_original_config(self):
        data = copy.deepcopy(self.base)
        original = copy.deepcopy(data)
        profile.validate_release_config(data)
        self.assertEqual(data, original)

    def test_live_repair_and_bad_interval_refused(self):
        for key, val in [('repair_action', 'RestartICS'), ('read_only', False),
                         ('monitoring_interval_seconds', 60), ('monitoring_interval_seconds', 601),
                         ('monitoring_interval_seconds', True)]:
            with self.subTest(key=key, val=val):
                data = copy.deepcopy(self.base)
                data[key] = val
                with self.assertRaises(profile.ReleaseProfileRefused):
                    profile.validate_release_config(data)

    def test_unknown_json_field_refused(self):
        data = copy.deepcopy(self.base)
        data['surprise'] = True
        with self.assertRaises(profile.ReleaseProfileRefused):
            profile.validate_release_config(data)

    def test_bad_executable_refused(self):
        data = copy.deepcopy(self.base)
        data['runtime']['ssh_executable'] = r'C:\bad\shim.cmd'
        with self.assertRaises(profile.ReleaseProfileRefused):
            profile.validate_release_config(data)

    def test_duplicate_keys_refused(self):
        self.path.write_bytes(b'{"profile":"release","profile":"release"}')
        with self.assertRaises(profile.ReleaseProfileRefused):
            profile.load_release_config(self.path)

    def test_oversize_refused(self):
        self.path.write_bytes(b' ' * (profile.MAX_CONFIG_BYTES + 1))
        with self.assertRaises(profile.ReleaseProfileRefused):
            profile.load_release_config(self.path)

    def test_unexpected_path_refused(self):
        with self.assertRaises(profile.ReleaseProfileRefused):
            profile.load_release_config(self.path.with_name('monitoring.release.example.json'))

    def test_invalid_wiring_rejected(self):
        with self.assertRaises(binding.ReleaseBindingRefused):
            binding.ReleaseWiring(self.root, self.path.parent/'fake.json', self.manifest, SID)
        with self.assertRaises(Exception):
            binding.ReleaseWiring(self.root, self.path, self.manifest, 'bogus')

    def test_inert_clis(self):
        self.assertEqual(profile.main(['--check-inert']), 0)
        self.assertEqual(binding.main(['--check-inert']), 0)
        with self.assertRaises(SystemExit):
            binding.main(['--live'])
        with self.assertRaises(SystemExit):
            profile.main([])

    def test_binds_real_m1_probe_and_M2_M3_adapters_without_running(self):
        captures = []
        auths = []
        def build(**kwargs):
            auths.append(kwargs)
            return lambda: True
        def observe(policy, **kwargs):
            captures.append((policy, kwargs))
            return 'offline-only'
        self.assertEqual(binding.run_explicitly_approved_api(
            self.wiring, build_authorizer=build, run_bridge=observe), 'offline-only')
        self.assertEqual(len(captures), 1)
        policy, kw = captures[0]
        self.assertEqual((policy.cycles, policy.interval_seconds), (2, 120))
        self.assertEqual(kw['approved_sid'], SID)
        self.assertIs(kw['probe'], binding.m1.run_once)
        self.assertIs(kw['history_path'], binding.release_history_path)
        self.assertIs(kw['storage_profile'], binding.require_release_storage_profile)
        self.assertTrue(kw['authorize_cycle']())
        self.assertEqual(kw['load_config']()['profile'], 'release')
        kw['verify_context'](self.base)
        self.assertEqual(auths[0]['config'], self.path)

    def test_fail_closed_on_config_change_before_bridge(self):
        called = []
        self.path.write_text(json.dumps({**self.base, 'read_only': False}), encoding='utf-8')
        with self.assertRaises(profile.ReleaseProfileRefused):
            binding.run_explicitly_approved_api(
                self.wiring, build_authorizer=lambda **kw: (lambda: True),
                run_bridge=lambda *a, **kw: called.append(True))
        self.assertEqual(called, [])

    def test_fail_closed_on_invalid_bridge(self):
        with self.assertRaises(binding.ReleaseBindingRefused):
            binding.run_explicitly_approved_api(
                self.wiring, build_authorizer=lambda **kw: (lambda: True),
                run_bridge=None)

    def test_runtime_config_verify_refuses_mutation(self):
        ctx = []
        def observe(policy, **kwargs):
            ctx.append(kwargs)
        binding.run_explicitly_approved_api(self.wiring,
            build_authorizer=lambda **kw: lambda: True, run_bridge=observe)
        changed = copy.deepcopy(self.base)
        changed['monitoring_interval_seconds'] = 180
        with self.assertRaises(binding.ReleaseBindingRefused):
            ctx[0]['verify_context'](changed)

    def test_release_storage_fails_closed_on_unset(self):
        with patch.dict(os.environ, {'ONYXCORE_V080_STORAGE_PROFILE': 'development'}):
            with self.assertRaises(binding.ReleaseBindingRefused):
                binding.require_release_storage_profile()

    def test_release_storage_uses_exclusive_v080_directory(self):
        with patch.dict(os.environ, {
                'ONYXCORE_V080_STORAGE_PROFILE': 'release',
                'LOCALAPPDATA': str(self.root)}):
            path = binding.release_history_path()
            self.assertEqual(path.parent.parent.name, 'OnyxCore-v080-Release')
            self.assertEqual(path.name, 'incident-history.sqlite3')

    def test_test_does_not_call_native_windows_or_probe(self):
        # This is a guard on the test suite itself; no Windows API, SSH or DB.
        with patch.object(binding.m1, 'run_once', side_effect=AssertionError('probe used')):
            binding.run_explicitly_approved_api(
                self.wiring, build_authorizer=lambda **kw: lambda: True,
                run_bridge=lambda *a, **kw: None)


if __name__ == '__main__':
    unittest.main()
