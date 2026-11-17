"""v0.8 M1 real diagnostic ADAPTER tests. All subprocesses are mocked.

No real Pi, Windows networking, SSH, Task Scheduler or release history is touched.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

MODULE_DIR = Path(__file__).resolve().parents[3] / 'windows/monitoring/v080'
sys.path.insert(0, str(MODULE_DIR))
import OnyxLiveConnectivity as m1


WINDOWS_OK = {
    'schema_version': 1, 'source': 'OnyxV080WindowsUsbReadiness',
    'classification': 'WindowsPathReady', 'adapter_present': True,
    'adapter_up': True, 'gateway_preferred': True, 'route_via_usb': True,
    'ics_service_status': 'Running', 'receiver_tcp_reachable': True,
    'repair_action': 'None',
}
PI_OK = {
    'classification': 'PiInternetVerified', 'interface_ready': True,
    'route_via_usb': True, 'gateway_reachable': True,
    'external_tcp_443': True, 'dns_resolves': True,
    'https_works': True, 'repair_action': 'None',
}


def fake_config():
    return {
        'windows': {'adapter_name': 'Ethernet 3', 'gateway_ip': '192.168.137.1',
                    'receiver_ip': '192.168.137.167', 'receiver_port': 8765},
        'pi': {'hostname': 'svr-onyxcore.local', 'user': 'onyxpi',
               'monitor_key_path': r'%USERPROFILE%\.ssh\onyxcore_monitor_ed25519'},
        'runtime': {'ssh_executable': r'C:\Windows\System32\OpenSSH\ssh.exe'},
        'timeouts': {'receiver_tcp_ms': 2000, 'ssh_seconds': 45},
    }


class FakeRunner:
    def __init__(self, windows=WINDOWS_OK, pi=PI_OK, fail_at=None):
        self.windows, self.pi, self.fail_at = windows, pi, fail_at
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        assert isinstance(argv, list)
        assert kwargs['capture_output'] is True
        assert kwargs['check'] is False
        assert 'shell' not in kwargs
        side = 'windows' if '-File' in argv else 'pi'
        if self.fail_at == side:
            return SimpleNamespace(returncode=22, stdout=b'', stderr=b'NO SECRET LEAK')
        data = self.windows if side == 'windows' else self.pi
        return SimpleNamespace(returncode=0, stdout=json.dumps(data).encode(), stderr=b'')


class LiveConnectivityTests(unittest.TestCase):
    def test_healthy_manual_one_shot_and_command_bounds(self):
        r = FakeRunner()
        result = m1.run_once(fake_config(), runner=r,
                             now=lambda: datetime(2026, 11, 11, 16, 0, tzinfo=timezone.utc))
        self.assertEqual(result['status'], 'Healthy')
        self.assertEqual(result['windows']['classification'], 'WindowsPathReady')
        self.assertEqual(result['pi']['classification'], 'PiInternetVerified')
        self.assertEqual(result['repair_action'], 'None')
        self.assertFalse(result['incident_history_written'])
        self.assertFalse(result['scheduler_enabled'])
        self.assertFalse(result['notification_sent'])
        self.assertEqual(len(r.calls), 2)
        self.assertEqual(r.calls[0][1]['timeout'], 25)
        self.assertEqual(r.calls[1][1]['timeout'], 45)
        self.assertIn('-LiveReadOnly', r.calls[0][0])
        self.assertIn('-Json', r.calls[0][0])
        self.assertIn('StrictHostKeyChecking=yes', r.calls[1][0])
        self.assertIn('BatchMode=yes', r.calls[1][0])
        self.assertIn('onyxcore-monitor', r.calls[1][0])

    def test_windows_failure_is_unknown_not_healthy(self):
        r = FakeRunner(fail_at='windows')
        report = m1.run_once(fake_config(), runner=r)
        self.assertEqual(report['status'], 'Unknown')
        self.assertEqual(report['issues'], ['WindowsDiagnosticUnavailable'])
        self.assertNotIn('NO SECRET LEAK', json.dumps(report))

    def test_pi_failure_is_unknown_not_healthy(self):
        r = FakeRunner(fail_at='pi')
        report = m1.run_once(fake_config(), runner=r)
        self.assertEqual(report['status'], 'Unknown')
        self.assertEqual(report['issues'], ['PiDiagnosticUnavailable'])
        self.assertNotIn('NO SECRET LEAK', json.dumps(report))

    def test_windows_classified_failure_is_degraded(self):
        w = {**WINDOWS_OK, 'classification': 'ReceiverUnreachable',
             'receiver_tcp_reachable': False}
        report = m1.run_once(fake_config(), runner=FakeRunner(windows=w))
        self.assertEqual(report['status'], 'Degraded')
        self.assertIn('ReceiverUnreachable', report['reason'])

    def test_verified_windows_problem_stays_degraded_when_pi_unavailable(self):
        w = {**WINDOWS_OK, 'classification': 'ReceiverUnreachable',
             'receiver_tcp_reachable': False}
        report = m1.run_once(fake_config(), runner=FakeRunner(windows=w, fail_at='pi'))
        self.assertEqual(report['status'], 'Degraded')
        self.assertEqual(report['reason'], 'WindowsReceiverUnreachable')
        self.assertEqual(report['issues'], ['PiDiagnosticUnavailable'])

    def test_pi_dns_problem_is_degraded(self):
        p = {**PI_OK, 'classification': 'DnsUnverified',
             'dns_resolves': False, 'https_works': False}
        report = m1.run_once(fake_config(), runner=FakeRunner(pi=p))
        self.assertEqual(report['status'], 'Degraded')
        self.assertEqual(report['reason'], 'PiDnsUnverified')

    def test_claimed_healthy_with_invalid_windows_data_is_unknown(self):
        w = {**WINDOWS_OK, 'route_via_usb': False}
        report = m1.run_once(fake_config(), runner=FakeRunner(windows=w))
        self.assertEqual(report['status'], 'Unknown')
        self.assertEqual(report['windows']['classification'], 'WindowsProbeUnavailable')

    def test_claimed_healthy_with_invalid_pi_data_is_unknown(self):
        p = {**PI_OK, 'gateway_reachable': False}
        report = m1.run_once(fake_config(), runner=FakeRunner(pi=p))
        self.assertEqual(report['status'], 'Unknown')
        self.assertEqual(report['pi']['classification'], 'PiProbeUnavailable')

    def test_repair_action_rejected(self):
        w = {**WINDOWS_OK, 'repair_action': 'RestartICS'}
        p = {**PI_OK, 'repair_action': 'RestartICS'}
        report = m1.run_once(fake_config(), runner=FakeRunner(windows=w, pi=p))
        self.assertEqual(report['status'], 'Unknown')
        self.assertEqual(len(report['issues']), 2)

    def test_duplicate_and_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            m1._decode(b'{"a":1,"a":2}')
        with self.assertRaises(ValueError):
            m1._decode(b'{"a": NaN}')

    def test_oversized_payload_rejected(self):
        with self.assertRaises(ValueError):
            m1._decode(b'x' * (m1.MAX_JSON_BYTES + 1))

    def test_offline_cli_config_check_is_inert(self):
        with patch.object(m1, 'run_once', side_effect=AssertionError('MUST NOT PROBE')):
            self.assertEqual(m1.main(['--check-config']), 0)

    def test_live_cli_refuses_when_context_not_authorized(self):
        with patch.object(m1, 'verify_local_context', side_effect=m1.ConnectivityError('no approval')):
            with patch.object(m1, 'run_once', side_effect=AssertionError('MUST NOT PROBE')):
                self.assertEqual(m1.main(['--live-read-only']), 2)

    def test_no_implicit_live_cli_default(self):
        with self.assertRaises(SystemExit) as error:
            m1.main([])
        self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
