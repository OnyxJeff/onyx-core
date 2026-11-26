#!/usr/bin/env python3
"""M2-S3B offline tests: pure systemd rendering and metadata-only readiness."""
from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'installation' / 'pi'))
import onyx_v100_pi_system_plan as subject  # noqa: E402

EXAMPLE = ROOT / 'docs/v1.0.0/examples/pi-armv6.system.config.example.json'


def sample_observations():
    return {
        'platform': 'linux', 'machine': 'armv6l', 'python_series': '3.13',
        'tools': {'ip': True, 'systemctl': True, 'nmcli': True},
        'service_uid': 1001, 'service_gid': 1001,
        'state': {'presence': 'present', 'safe_type': True, 'uid': 1001, 'gid': 1001, 'mode': 0o700},
        'credential': {'presence': 'present', 'safe_type': True, 'uid': 0, 'gid': 0, 'mode': 0o600},
        'unit': {'presence': 'missing'},
        'legacy_unit': {'presence': 'present'},
        'activation_marker': {'presence': 'missing'},
    }


class PiSystemPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(EXAMPLE.read_text(encoding='utf-8'))

    def test_versioned_example_strict_schema(self):
        from onyx_v100_config import validate_config
        self.assertEqual(validate_config(self.config, 'pi-armv6'), self.config)
        self.assertNotEqual(self.config['storage']['state_dir'], subject.LEGACY_STATE)

    def test_unit_has_runtime_dependencies_and_exact_versioned_paths(self):
        unit = subject.render_unit(self.config)
        self.assertIn('ExecStart=/usr/bin/python3 -I -B /opt/onyxcore/v1.0.0/tools/installation/pi/onyx_v100_pi_launch.py', unit)
        self.assertIn('--config /etc/onyxcore/v1.0.0/pi-armv6.config.json', unit)
        self.assertIn('--installed-root /opt/onyxcore/v1.0.0 --run --approve-execution', unit)
        self.assertIn('EnvironmentFile=/etc/onyxcore/v1.0.0/receiver.env', unit)
        self.assertIn('ReadWritePaths=/var/lib/onyxcore-v100', unit)
        self.assertNotIn('/var/lib/onyxcore\n', unit)

    def test_unit_has_activation_barriers(self):
        unit = subject.render_unit(self.config)
        self.assertIn('ConditionPathExists=/etc/onyxcore/v1.0.0/activation-approved\n', unit)
        self.assertIn('RefuseManualStart=yes\n', unit)
        self.assertIn('ProtectSystem=strict', unit)
        self.assertIn('NoNewPrivileges=true', unit)
        self.assertIn('UMask=0077', unit)
        self.assertIn('User=onyxcore', unit)
        self.assertNotIn('ExecStartPre=', unit)

    def test_system_unit_deterministic_and_no_hostnames(self):
        a, b = subject.render_unit(self.config), subject.render_unit(copy.deepcopy(self.config))
        self.assertEqual(a, b)
        self.assertNotIn('SQUALL', a)
        self.assertNotIn('svr-onyxcore', a)
        self.assertTrue(a.endswith('\n'))

    def test_preview_has_no_approval_claims_or_secret_contents(self):
        report = subject.plan(self.config)
        self.assertEqual(report['native_readiness'], 'NOT_NATIVELY_INSPECTED')
        for flag in ('credential_contents_read', 'unit_written', 'service_registered',
                     'service_enabled', 'activation_performed', 'network_changes',
                     'persistent_state_changes'):
            self.assertIs(report[flag], False, flag)
        self.assertNotIn('token', json.dumps(report).lower())

    def test_legacy_state_rejected(self):
        cfg = copy.deepcopy(self.config)
        cfg['storage']['state_dir'] = '/var/lib/onyxcore'
        with self.assertRaisesRegex(subject.PlanningRefused, 'legacy'):
            subject.render_unit(cfg)
        cfg['storage']['state_dir'] = '/var/lib/onyxcore/subdir'
        with self.assertRaisesRegex(subject.PlanningRefused, 'legacy'):
            subject.render_unit(cfg)

    def test_arbitrary_system_path_and_injection_rejected(self):
        cfg = copy.deepcopy(self.config)
        for path in ['/etc/onyxcore-v100', '/tmp/onyxcore-v100', '/var/lib/a/b',
                     '/var/lib/../onyxcore-v100', '/var/lib/onyxcore-v100;id']:
            cfg['storage']['state_dir'] = path
            with self.subTest(path=path), self.assertRaises(subject.PlanningRefused):
                subject.render_unit(cfg)

    def test_unsafe_python_binary_path_rejected(self):
        for path in ['/tmp/python3', '/usr/bin/python3;touch',
                     '/usr/bin/../bin/python3', '/usr/bin/python 3', 'python3']:
            with self.subTest(path=path), self.assertRaises(subject.PlanningRefused):
                subject.render_unit(self.config, python_path=path)

    def test_native_observations_clean_reaches_preparation_required_not_installed(self):
        status, blockers, pending = subject.classify_observation(sample_observations())
        self.assertEqual(status, 'PREPARATION_REQUIRED')
        self.assertEqual(blockers, [])
        self.assertIn('usb_link_and_route_not_verified', pending)

    def test_misidentified_hardware_or_python_blocks(self):
        for key, val in [('machine','x86_64'), ('python_series','3.12'), ('platform','windows')]:
            obs = sample_observations()
            obs[key] = val
            with self.subTest(key=key):
                self.assertEqual(subject.classify_observation(obs)[0], 'BLOCKED')

    def test_missing_tools_block(self):
        for name in subject.NEEDED_TOOLS:
            obs = sample_observations()
            obs['tools'][name] = False
            with self.subTest(tool=name):
                self.assertIn('missing_tool_'+name, subject.classify_observation(obs)[1])

    def test_protected_state_directory_wrong_owner_or_mode_blocks(self):
        for key,val in [('uid',0),('gid',0),('mode',0o777),('safe_type',False)]:
            obs = sample_observations()
            obs['state'][key] = val
            with self.subTest(key=key):
                self.assertIn('state_directory_metadata_unsafe', subject.classify_observation(obs)[1])

    def test_credential_missing_is_enrollment_pending(self):
        obs = sample_observations()
        obs['credential'] = {'presence':'unknown', 'safe_type':False}
        status, blockers, pending = subject.classify_observation(obs)
        self.assertEqual(status, 'PREPARATION_REQUIRED')
        self.assertFalse(blockers)
        self.assertTrue(any(x.startswith('credential_requires') for x in pending))

    def test_credential_unsafe_metadata_blocks(self):
        obs = sample_observations()
        obs['credential']['mode'] = 0o644
        self.assertIn('credential_metadata_unsafe', subject.classify_observation(obs)[1])

    def test_existing_unit_or_activation_guard_blocks(self):
        for name in ('unit','activation_marker'):
            obs = sample_observations()
            obs[name] = {'presence': 'present', 'safe_type': True}
            with self.subTest(name=name):
                self.assertEqual(subject.classify_observation(obs)[0], 'BLOCKED')

    def test_redirected_paths_block(self):
        for name in ('state','credential'):
            obs = sample_observations()
            obs[name] = {'presence':'unsafe_redirect', 'safe_type':False}
            with self.subTest(name=name):
                self.assertEqual(subject.classify_observation(obs)[0], 'BLOCKED')

    def test_new_host_missing_account_and_state_needs_preparation(self):
        obs = sample_observations()
        obs['service_uid'] = None
        obs['service_gid'] = None
        obs['state'] = {'presence':'missing','safe_type':False}
        status, blockers, pending = subject.classify_observation(obs)
        self.assertEqual(status,'PREPARATION_REQUIRED')
        self.assertIn('service_account_or_group_missing',pending)
        self.assertIn('state_directory_requires_separate_provisioning',pending)

    def test_cli_preview_is_readonly_json(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code=subject.main(['--config',str(EXAMPLE)])
        self.assertEqual(code,0,stderr.getvalue())
        report=json.loads(stdout.getvalue())
        self.assertEqual(report['operation'],'PI_V100_INACTIVE_SYSTEM_PREPARATION_PREVIEW')
        self.assertFalse(report['unit_written'])
        self.assertEqual(report['receiver_port'],8765)

    def test_cli_print_unit_does_not_write(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            code=subject.main(['--config',str(EXAMPLE),'--print-unit'])
        self.assertEqual(code,0)
        self.assertEqual(out.getvalue(),subject.render_unit(self.config))

    def test_native_inspection_is_rejected_from_non_armv6(self):
        if sys.platform == 'linux' and subject.platform.machine().lower() == 'armv6l':
            self.skipTest('hardware-native read-only inspection exercised separately')
        out=io.StringIO()
        with contextlib.redirect_stderr(out):
            self.assertEqual(subject.main(['--config',str(EXAMPLE),'--native-readonly']),2)
        self.assertIn('native inspection requires',out.getvalue())

    def test_source_has_no_service_or_filesystem_mutators(self):
        script=(ROOT/'tools/installation/pi/onyx_v100_pi_system_plan.py').read_text(encoding='utf-8')
        for token in ('subprocess.run(', 'subprocess.Popen(', '.mkdir(', '.write_bytes(',
                      '.write_text(', 'systemctl start', 'systemctl enable', 'os.execv(',
                      'os.chmod(', 'os.chown(', '.unlink(', '.rename('):
            self.assertNotIn(token,script,token)


if __name__=='__main__':
    unittest.main(verbosity=2)
