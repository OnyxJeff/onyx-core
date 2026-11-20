"""M1-S4 offline-only Pi preflight tests; no host probing or service actions."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'tools' / 'installation' / 'pi' / 'onyx_v100_pi_readiness.py'
CONFIG = ROOT / 'tools' / 'installation' / 'common' / 'onyx_v100_config.py'

spec = importlib.util.spec_from_file_location('onyx_v100_pi_readiness', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

PI_CONFIG = {
    'schema_version': 1, 'platform': 'pi-armv6',
    'receiver': {'interface': 'usb0', 'port': 8765, 'ipv4_subnet': '192.168.137.0/24'},
    'storage': {'state_dir': '/var/lib/onyxcore', 'history_name': 'telemetry.db',
                'snapshot_name': 'latest-snapshot.json'},
}


def observation():
    return {
        'architecture': 'armv6l', 'model': 'Raspberry Pi Zero Rev 1.3',
        'os_id': 'raspbian', 'os_codename': 'trixie', 'python_version': '3.13.5',
        'python_supported': True, 'systemd_available': True,
        'networkmanager_tools_present': True, 'iproute2_present': True,
        'interface_present': True, 'interface_address_inspected': True,
        'interface_ipv4': ['192.168.137.167'],
        'service_account_present': True,
        'state_directory': {'present': True, 'safe': True},
        'credential_file': {'present': True, 'safe': True},
        'legacy_unit_present': False, 'candidate_unit_present': False,
    }


class PiReadinessTests(unittest.TestCase):
    def test_script_present_and_config_same_source_tree(self):
        self.assertTrue(SCRIPT.is_file())
        self.assertTrue(CONFIG.is_file())
        self.assertEqual(module.OPERATION, 'READ_ONLY_PI_INSTALL_PREFLIGHT')

    def test_ready_host_is_never_installed_or_accepted(self):
        out = module.evaluate(PI_CONFIG, observation())
        self.assertEqual(out['readiness']['state'], 'REQUIRES_CONFIGURATION')
        self.assertFalse(out['readiness']['installation_accepted'])
        self.assertFalse(out['installation_accepted'])
        self.assertTrue(out['observation_only'])
        self.assertFalse(out['has_network_probes'])
        self.assertFalse(out['configuration_written'])
        self.assertFalse(out['service_or_network_changes'])
        self.assertFalse(out['credential_contents_read'])

    def test_original_pi_zero_is_supported_without_squall_name(self):
        out = module.evaluate(PI_CONFIG, observation())
        self.assertTrue(out['target']['original_pi_zero_rev_1_3'])
        self.assertTrue(out['usb']['configured_interface_found'])
        self.assertTrue(out['target']['trixie_family_detected'])
        self.assertEqual(out['usb']['usable_private_ipv4_count'], 1)
        self.assertFalse(out['usb']['network_peer_verified'])
        self.assertNotIn('192.168.137.167', json.dumps(out))

    def test_debian_trixie_family_is_not_hardware_proof(self):
        obs = observation()
        obs['os_id'] = 'debian'
        obs['model'] = 'Raspberry Pi Zero 2 W Rev 1.0'
        out = module.evaluate(PI_CONFIG, obs)
        self.assertEqual(out['readiness']['state'], 'BLOCKED')
        self.assertFalse(out['target']['original_pi_zero_rev_1_3'])

    def test_wrong_arch_is_blocking(self):
        obs = observation()
        obs['architecture'] = 'aarch64'
        self.assertIn('ARMv6', ' '.join(module.evaluate(PI_CONFIG, obs)['readiness']['blockers']))

    def test_wrong_os_is_blocking(self):
        obs = observation()
        obs['os_codename'] = 'bookworm'
        self.assertEqual(module.evaluate(PI_CONFIG, obs)['readiness']['state'], 'BLOCKED')

    def test_wrong_python_is_blocking(self):
        obs = observation()
        obs['python_supported'] = False
        self.assertEqual(module.evaluate(PI_CONFIG, obs)['readiness']['state'], 'BLOCKED')

    def test_missing_systemd_and_nmcli_are_blockers(self):
        obs = observation()
        obs['systemd_available'] = False
        obs['networkmanager_tools_present'] = False
        self.assertEqual(len(module.evaluate(PI_CONFIG, obs)['readiness']['blockers']), 2)

    def test_missing_iproute2_is_blocker(self):
        obs = observation()
        obs['iproute2_present'] = False
        self.assertEqual(module.evaluate(PI_CONFIG, obs)['readiness']['state'], 'BLOCKED')

    def test_missing_user_and_state_are_pending_actions(self):
        obs = observation()
        obs['service_account_present'] = False
        obs['state_directory'] = {'present': False, 'safe': False}
        obs['credential_file'] = {'present': False, 'safe': False}
        report = module.evaluate(PI_CONFIG, obs)
        self.assertEqual(report['readiness']['state'], 'REQUIRES_CONFIGURATION')
        self.assertGreaterEqual(len(report['readiness']['operator_actions']), 4)

    def test_unsafe_existing_state_is_blocker(self):
        obs = observation()
        obs['state_directory'] = {'present': True, 'safe': False}
        self.assertEqual(module.evaluate(PI_CONFIG, obs)['readiness']['state'], 'BLOCKED')

    def test_unsafe_existing_credential_is_blocker(self):
        obs = observation()
        obs['credential_file'] = {'present': True, 'safe': False}
        self.assertEqual(module.evaluate(PI_CONFIG, obs)['readiness']['state'], 'BLOCKED')

    def test_credential_permission_denied_is_not_reported_missing(self):
        # Model /etc/onyxcore mode 0700 as seen by a normal Pi user.
        with mock.patch.object(Path, 'lstat', side_effect=PermissionError('denied')):
            result = module._path_metadata(Path('/etc/onyxcore/receiver.env'), 'credential')
        self.assertIsNone(result['present'])
        self.assertFalse(result['safe'])

    def test_credential_unknown_requires_metadata_review_not_enrollment(self):
        obs = observation()
        obs['credential_file'] = {'present': None, 'safe': False}
        report = module.evaluate(PI_CONFIG, obs)
        actions = ' '.join(report['readiness']['operator_actions'])
        self.assertEqual(report['readiness']['state'], 'REQUIRES_CONFIGURATION')
        self.assertIsNone(report['state']['credential_file_present'])
        self.assertFalse(report['state']['credential_file_metadata_inspected'])
        self.assertIn('could not be verified', actions)
        self.assertNotIn('Enroll protected Pi receiver credential', actions)
        self.assertFalse(report['installation_accepted'])

    def test_state_directory_permission_denied_not_reported_missing(self):
        obs = observation()
        obs['state_directory'] = {'present': None, 'safe': False}
        report = module.evaluate(PI_CONFIG, obs)
        actions = ' '.join(report['readiness']['operator_actions'])
        self.assertIn('State directory metadata could not be verified', actions)
        self.assertNotIn('Prepare a protected, service-owned state directory', actions)
        self.assertFalse(report['state']['state_dir_metadata_safe'])

    def test_existing_legacy_unit_requires_upgrade_workflow(self):
        obs = observation()
        obs['legacy_unit_present'] = True
        output = module.evaluate(PI_CONFIG, obs)
        self.assertTrue(any('upgrade workflow' in action for action in output['readiness']['operator_actions']))

    def test_usb_not_connected_does_not_block_architecture(self):
        obs = observation()
        obs['interface_present'] = False
        obs['interface_address_inspected'] = False
        obs['interface_ipv4'] = []
        output = module.evaluate(PI_CONFIG, obs)
        self.assertEqual(output['readiness']['state'], 'REQUIRES_CONFIGURATION')
        self.assertFalse(output['usb']['network_peer_verified'])

    def test_multiple_usb_addresses_require_operator_confirmation(self):
        obs = observation()
        obs['interface_ipv4'] = ['192.168.137.167', '192.168.137.168']
        output = module.evaluate(PI_CONFIG, obs)
        self.assertTrue(any('configured USB subnet' in action for action in output['readiness']['operator_actions']))

    def test_dual_usb_address_other_subnet_is_not_ambiguous(self):
        obs = observation()
        obs['interface_ipv4'] = ['10.12.194.1', '192.168.137.167']
        out = module.evaluate(PI_CONFIG, obs)
        self.assertEqual(out['usb']['usable_private_ipv4_count'], 2)
        self.assertEqual(out['usb']['configured_subnet_ipv4_count'], 1)
        self.assertFalse(any('configured USB subnet' in message
                             for message in out['readiness']['operator_actions']))

    def test_dual_usb_address_in_selected_subnet_remains_ambiguous(self):
        obs = observation()
        obs['interface_ipv4'] = ['192.168.137.167', '192.168.137.168']
        out = module.evaluate(PI_CONFIG, obs)
        self.assertEqual(out['usb']['configured_subnet_ipv4_count'], 2)
        self.assertTrue(any('configured USB subnet' in message
                            for message in out['readiness']['operator_actions']))

    def test_windows_config_is_refused(self):
        with self.assertRaises(module.ReadinessRefused):
            module.evaluate({'platform': 'windows'}, observation())

    def test_ip_json_selects_only_matching_interface_private_ipv4(self):
        payload = json.dumps([
            {'ifname': 'lo', 'addr_info': [{'family': 'inet', 'local': '127.0.0.1'}]},
            {'ifname': 'usb0', 'addr_info': [
                {'family': 'inet6', 'local': 'fe80::1'},
                {'family': 'inet', 'local': '8.8.8.8'},
                {'family': 'inet', 'local': '192.168.137.167'},
                {'family': 'inet', 'local': '192.168.137.167'},
            ]}
        ])
        self.assertEqual(module._addresses_from_ip_json(payload, 'usb0'), ['192.168.137.167'])

    def test_ip_json_refuses_malformed(self):
        for payload in ('{}', '[{"ifname":"usb0","addr_info":{}}]',
                        '[{"ifname":"usb0","addr_info":[{"family":"inet","local":"invalid"}]}]'):
            with self.subTest(payload=payload), self.assertRaises((ValueError, module.ReadinessRefused)):
                module._addresses_from_ip_json(payload, 'usb0')

    def test_os_release_is_never_executed_and_parsed_conservatively(self):
        with tempfile.TemporaryDirectory() as temp:
            os_file = Path(temp) / 'os-release'
            os_file.write_text('ID=raspbian\nVERSION_CODENAME="trixie"\nMALICIOUS=$(touch /tmp/no)\n', encoding='utf-8')
            doc = module._os_release(os_file)
            self.assertEqual(doc, {'ID': 'raspbian', 'VERSION_CODENAME': 'trixie'})

    def test_symlinked_state_path_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'target'
            target.mkdir()
            alias = Path(temp) / 'alias'
            try:
                alias.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('Symlink privileges not available')
            result = module._path_metadata(alias, 'directory', expected_uid=0)
            self.assertFalse(result['safe'])

    def test_readonly_state_dir_requires_owner_rwx_on_posix(self):
        if sys.platform == 'win32':
            self.skipTest('POSIX mode ownership check')
        import os
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'state'
            folder.mkdir(mode=0o700)
            folder.chmod(0o500)
            self.assertFalse(module._path_metadata(folder, 'directory', os.getuid())['safe'])
            folder.chmod(0o700)
            self.assertTrue(module._path_metadata(folder, 'directory', os.getuid())['safe'])

    def test_code_cannot_start_or_modify_os(self):
        source = SCRIPT.read_text(encoding='utf-8')
        for bad in ('systemctl start', 'systemctl restart', 'systemctl enable',
                    'apt install', 'os.system(', 'shell=True', 'iptables',
                    'receiver.env).read_', "'--apply'", 'requests.get('):
            self.assertNotIn(bad, source)

    def test_cli_invalid_config_refuses_without_echoing_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            bad = Path(temp) / 'invalid.json'
            data = copy.deepcopy(PI_CONFIG)
            data['SECRET_TOKEN'] = 'TOPSECRET_DO_NOT_PRINT'
            bad.write_text(json.dumps(data), encoding='utf-8')
            child = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), '--config', str(bad)],
                                   capture_output=True, text=True, timeout=10)
            self.assertEqual(child.returncode, 2)
            self.assertNotIn('TOPSECRET_DO_NOT_PRINT', child.stderr + child.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
