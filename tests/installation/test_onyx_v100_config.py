"""M1-S3 strictly offline Windows/Pi configuration validator tests."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'tools/installation/common/onyx_v100_config.py'
WIN = ROOT / 'docs/v1.0.0/examples/windows.config.example.json'
PI = ROOT / 'docs/v1.0.0/examples/pi-armv6.config.example.json'
spec = importlib.util.spec_from_file_location('onyx_v100_config', MODULE)
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.win = json.loads(WIN.read_text(encoding='utf-8'))
        self.pi = json.loads(PI.read_text(encoding='utf-8'))

    def rejects(self, doc, platform):
        with self.assertRaises(config.ConfigRefused):
            config.validate_config(doc, platform)

    def test_windows_example_valid(self):
        self.assertEqual(config.validate_config(self.win, 'windows'), self.win)

    def test_pi_example_valid(self):
        self.assertEqual(config.validate_config(self.pi, 'pi-armv6'), self.pi)

    def test_platform_binding(self):
        self.rejects(self.win, 'pi-armv6')
        self.rejects(self.pi, 'windows')

    def test_rejects_wrong_schema_and_bool(self):
        for bad in (0, 2, True, '1'):
            doc = copy.deepcopy(self.win)
            doc['schema_version'] = bad
            with self.subTest(bad=bad):
                self.rejects(doc, 'windows')

    def test_rejects_secret_or_unknown_keys(self):
        for platform, original in (('windows', self.win), ('pi-armv6', self.pi)):
            doc = copy.deepcopy(original)
            doc['token'] = 'THIS_MUST_NOT_BE_A_CONFIG_VALUE'
            self.rejects(doc, platform)
        doc = copy.deepcopy(self.win)
        doc['receiver']['password'] = 'not-allowed'
        self.rejects(doc, 'windows')

    def test_rejects_invalid_gateway_binding(self):
        for value in ('0.0.0.0', '192.168.1.25', 'localhost', '::1'):
            doc = copy.deepcopy(self.win)
            doc['gateway']['listen_host'] = value
            with self.subTest(value=value):
                self.rejects(doc, 'windows')

    def test_port_and_interval_guards(self):
        for bad in (True, '8765', -1, 1, 65536):
            doc = copy.deepcopy(self.win)
            doc['receiver']['port'] = bad
            self.rejects(doc, 'windows')
        for bad in (True, 0, 3601, '30'):
            doc = copy.deepcopy(self.win)
            doc['collector']['interval_seconds'] = bad
            self.rejects(doc, 'windows')

    def test_rejects_bad_receiver_address(self):
        for bad in ('https://x', '8.8.8.8', '127.0.0.1', '0.0.0.0', '255.255.255.255', 'example..local', '-bad.local', '999.999.999.999'):
            doc = copy.deepcopy(self.win)
            doc['receiver']['host'] = bad
            with self.subTest(bad=bad):
                self.rejects(doc, 'windows')

    def test_rejects_unsafe_usb_and_collector_names(self):
        for bad in ('', 'Eth; del all', 'Eth\nInjected', 'x' * 130):
            doc = copy.deepcopy(self.win)
            doc['usb']['adapter_name'] = bad
            self.rejects(doc, 'windows')

    def test_rejects_unsafe_pi_state_path(self):
        for bad in ('/', 'var/lib/onyxcore', '/var/lib/../data', '/etc/onyxcore',
                    '/var//lib/onyxcore', '/var/lib/onyxcore/'):
            doc = copy.deepcopy(self.pi)
            doc['storage']['state_dir'] = bad
            with self.subTest(bad=bad):
                self.rejects(doc, 'pi-armv6')

    def test_pi_filename_and_interface_guards(self):
        for bad in ('', '../evil.db', 'telemetry.sqlite', 'name.db;rm -rf', 'x' * 20):
            doc = copy.deepcopy(self.pi)
            if bad == 'x' * 20:
                doc['receiver']['interface'] = bad
            else:
                doc['storage']['history_name'] = bad
            self.rejects(doc, 'pi-armv6')

    def test_pi_storage_dir_can_vary(self):
        doc = copy.deepcopy(self.pi)
        doc['storage']['state_dir'] = '/srv/onyxdata'
        doc['storage']['history_name'] = 'companion.db'
        self.assertEqual(config.validate_config(doc, 'pi-armv6'), doc)

    def test_pi_source_required_and_validated(self):
        doc = copy.deepcopy(self.pi)
        del doc['receiver']['source']
        self.rejects(doc, 'pi-armv6')
        for bad in ('', 'SQUALL; rm', 'weird\nname', 'a'*65, None, True):
            doc = copy.deepcopy(self.pi)
            doc['receiver']['source'] = bad
            with self.subTest(bad=bad):
                self.rejects(doc, 'pi-armv6')

    def test_pair_must_agree_on_telemetry_source_and_port(self):
        self.assertTrue(config.validate_pair(self.win, self.pi))
        doc = copy.deepcopy(self.pi)
        doc['receiver']['source'] = 'OtherMachine'
        with self.assertRaises(config.ConfigRefused):
            config.validate_pair(self.win, doc)
        doc = copy.deepcopy(self.pi)
        doc['receiver']['port'] = 9000
        with self.assertRaises(config.ConfigRefused):
            config.validate_pair(self.win, doc)

    def test_pi_private_usb_subnet_is_required(self):
        doc = copy.deepcopy(self.pi)
        del doc['receiver']['ipv4_subnet']
        self.rejects(doc, 'pi-armv6')

    def test_pi_private_usb_subnet_rejects_unsafe_cidrs(self):
        for bad in ('8.8.8.0/24', '0.0.0.0/0', '127.0.0.0/24',
                    '192.168.137.167/24', '192.168.137.0/8',
                    '192.168.137.0/15', '192.168.137.0/31',
                    '192.168.137.0/32', '192.0.0.0/24', '192.168.137.0/24;evil',
                    '', 12, None):
            doc = copy.deepcopy(self.pi)
            doc['receiver']['ipv4_subnet'] = bad
            with self.subTest(bad=bad):
                self.rejects(doc, 'pi-armv6')

    def test_pi_alternate_private_subnet_allowed(self):
        doc = copy.deepcopy(self.pi)
        doc['receiver']['ipv4_subnet'] = '10.12.194.0/28'
        self.assertEqual(config.validate_config(doc, 'pi-armv6'), doc)

    def test_sensor_enabled_validation(self):
        doc = copy.deepcopy(self.win)
        doc['cpu_temperature'] = {
            'enabled': True,
            'endpoint': 'http://192.168.137.1:8085/data.json',
            'sensor_path': '/Sensor/ExamplePC/AMD Processor/Temperatures/Core (Tctl/Tdie)',
        }
        config.validate_config(doc, 'windows')
        for bad in ('http://8.8.8.8:8085/data.json',
                    'https://192.168.137.1:8085/data.json',
                    'http://user:password@192.168.137.1:8085/data.json'):
            broken = copy.deepcopy(doc)
            broken['cpu_temperature']['endpoint'] = bad
            self.rejects(broken, 'windows')

    def test_loader_refuses_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'config.json'
            file.write_text('{"schema_version":1,"schema_version":1,"platform":"windows"}', encoding='utf-8')
            with self.assertRaises(config.ConfigRefused):
                config.load_config(file, 'windows')

    def test_loader_refuses_nonfinite_and_oversized(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'config.json'
            file.write_text('{"schema_version": NaN}', encoding='utf-8')
            with self.assertRaises(config.ConfigRefused):
                config.load_config(file, 'windows')
            file.write_bytes(b' ' * (config.MAX_CONFIG_BYTES + 1))
            with self.assertRaises(config.ConfigRefused):
                config.load_config(file, 'windows')

    def test_readonly_summary_is_not_install_acceptance(self):
        for doc in (self.win, self.pi):
            result = config.summary(doc)
            self.assertEqual(result['operation'], 'READ_ONLY_CONFIGURATION_VALIDATION')
            self.assertIs(result['installation_accepted'], False)
            self.assertIs(result['network_scope_verified'], False)
            self.assertIs(result['credential_contents_read'], False)
            self.assertIs(result['configuration_written'], False)
            self.assertIs(result['service_or_task_changes'], False)
            raw = json.dumps(result)
            for key in ('host', 'adapter_name', 'state_dir', 'sensor_path', 'token'):
                self.assertNotIn('"' + key + '"', raw)

    def test_cli_examples_are_read_only_and_no_secrets(self):
        for platform, file in (('windows', WIN), ('pi-armv6', PI)):
            with self.subTest(platform=platform):
                proc = subprocess.run(
                    [sys.executable, '-I', '-B', str(MODULE), '--platform', platform,
                     '--config', str(file)], capture_output=True, text=True, timeout=10)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                report = json.loads(proc.stdout)
                self.assertTrue(report['valid'])
                self.assertFalse(report['installation_accepted'])
                self.assertFalse(report['service_or_task_changes'])
                self.assertFalse(report['credential_contents_read'])

    def test_cli_rejects_invalid_no_input_echo(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text('{"token":"DO_NOT_ECHO_THIS_SECRET"}', encoding='utf-8')
            proc = subprocess.run(
                [sys.executable, '-I', '-B', str(MODULE), '--platform', 'windows',
                 '--config', str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(proc.returncode, 2)
            self.assertNotIn('DO_NOT_ECHO_THIS_SECRET', proc.stdout + proc.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
