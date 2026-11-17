"""ONYX CORE v0.8.0 — offline mocks for native evidence composition.

No Windows DLLs, route lookups, Pi/SSH/TCP, installed services, journals or tasks.
"""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
MOD = ROOT / 'windows/monitoring/v080'
sys.path.insert(0, str(MOD))
import OnyxNativePathAssessment as m

ALIAS = 'Ethernet 3'
GW = '192.168.137.1'
PI = '192.168.137.167'


def E(classification, index=None):
    return SimpleNamespace(classification=classification, interface_index=index)


class CompositionTests(unittest.TestCase):
    def run_case(self, *, first=E('Resolved', 7), address=E('Preferred', 7),
                 route=E('ExpectedRoute', 7), last=E('Resolved', 7)):
        calls = []
        answers = iter([first, last])
        def adapter(alias):
            calls.append(('adapter', alias))
            return next(answers)
        def gateway(gateway, receiver, index):
            calls.append(('gateway', gateway, receiver, index))
            return address
        def routing(receiver, gateway, index):
            calls.append(('route', receiver, gateway, index))
            return route
        result = m.probe_native_path(ALIAS, GW, PI, adapter_reader=adapter,
                                     gateway_reader=gateway, route_reader=routing)
        return result, calls

    def test_verified_path_with_two_adapter_checks(self):
        result, calls = self.run_case()
        self.assertEqual((result.classification, result.interface_index), ('NativePathVerified', 7))
        self.assertEqual(calls, [('adapter', ALIAS), ('gateway', GW, PI, 7),
                                 ('route', PI, GW, 7), ('adapter', ALIAS)])

    def test_not_full_health_or_windows_ready(self):
        result, _ = self.run_case()
        self.assertNotIn(result.classification, ('Healthy', 'WindowsPathReady'))
        self.assertNotIn('receiver', vars(result))

    def test_fresh_interface_index_not_hardcoded(self):
        result, calls = self.run_case(first=E('Resolved', 20), address=E('Preferred', 20),
                                      route=E('ExpectedRoute', 20), last=E('Resolved', 20))
        self.assertEqual(result.interface_index, 20)
        self.assertIn(('route', PI, GW, 20), calls)

    def test_missing_adapter_blocks_everything(self):
        result, calls = self.run_case(first=E('Unavailable'))
        self.assertEqual(result.classification, 'Unavailable')
        self.assertEqual(len(calls), 1)

    def test_missing_adapter_index_blocks_everything(self):
        result, calls = self.run_case(first=E('Resolved', None))
        self.assertEqual((result.classification, len(calls)), ('Unavailable', 1))

    def test_adapter_bool_index_refused(self):
        result, _ = self.run_case(first=E('Resolved', True))
        self.assertEqual(result.classification, 'Unavailable')

    def test_not_preferred_requires_no_route_query(self):
        result, calls = self.run_case(address=E('NotPreferred'))
        self.assertEqual(result.classification, 'GatewayNotPreferred')
        self.assertEqual([x[0] for x in calls], ['adapter', 'gateway', 'adapter'])

    def test_not_preferred_index_change_fails_unknown(self):
        result, calls = self.run_case(address=E('NotPreferred'),
                                      last=E('Resolved', 8))
        self.assertEqual((result.classification, result.reason),
                         ('Unavailable', 'AdapterIdentityChanged'))
        self.assertNotIn('route', [x[0] for x in calls])

    def test_not_preferred_recheck_unavailable_fails_unknown(self):
        result, calls = self.run_case(address=E('NotPreferred'), last=E('Unavailable'))
        self.assertEqual((result.classification, result.reason),
                         ('Unavailable', 'AdapterIdentityChanged'))
        self.assertEqual([x[0] for x in calls], ['adapter', 'gateway', 'adapter'])

    def test_not_preferred_recheck_exception_fails_unknown(self):
        count = [0]
        def adapter(_):
            count[0] += 1
            if count[0] == 2:
                raise PermissionError('SENSITIVE-DO-NOT-LEAK')
            return E('Resolved', 7)
        result = m.probe_native_path(ALIAS, GW, PI, adapter_reader=adapter,
                                     gateway_reader=lambda *args: E('NotPreferred'),
                                     route_reader=lambda *args: self.fail('route forbidden'))
        self.assertEqual(result.classification, 'Unavailable')
        self.assertEqual(count[0], 2)
        self.assertNotIn('SENSITIVE', str(result))

    def test_unavailable_gateway_not_degraded(self):
        result, _ = self.run_case(address=E('Unavailable'))
        self.assertEqual(result.classification, 'Unavailable')

    def test_wrong_gateway_index_refused(self):
        result, _ = self.run_case(address=E('Preferred', 9))
        self.assertEqual(result.classification, 'Unavailable')

    def test_mismatch_is_confirmed_when_other_route_selected(self):
        result, calls = self.run_case(route=E('ConfirmedMismatch', 9))
        self.assertEqual((result.classification, result.interface_index), ('RouteMismatch', None))
        self.assertEqual(calls[-1], ('adapter', ALIAS))

    def test_mismatch_can_be_wrong_hop_on_expected_interface(self):
        result, _ = self.run_case(route=E('ConfirmedMismatch', 7))
        self.assertEqual(result.classification, 'RouteMismatch')

    def test_mismatch_without_index_not_confirmed(self):
        result, _ = self.run_case(route=E('ConfirmedMismatch', None))
        self.assertEqual(result.classification, 'Unavailable')

    def test_changed_index_rejects_healthy(self):
        result, _ = self.run_case(last=E('Resolved', 8))
        self.assertEqual((result.classification, result.reason),
                         ('Unavailable', 'AdapterIdentityChanged'))

    def test_index_change_rejects_mismatch_too(self):
        result, _ = self.run_case(route=E('ConfirmedMismatch', 9), last=E('Resolved', 8))
        self.assertEqual(result.classification, 'Unavailable')

    def test_second_adapter_query_unavailable(self):
        result, _ = self.run_case(last=E('Unavailable'))
        self.assertEqual(result.classification, 'Unavailable')

    def test_expected_route_index_conflicts(self):
        result, _ = self.run_case(route=E('ExpectedRoute', 9))
        self.assertEqual(result.classification, 'Unavailable')

    def test_absent_route_result_unknown(self):
        result, _ = self.run_case(route=None)
        self.assertEqual(result.classification, 'Unavailable')

    def test_route_query_denied_without_error_text(self):
        def err(*_): raise PermissionError('SENSITIVE-SECRET-NO-PRINT')
        result = m.probe_native_path(ALIAS, GW, PI, adapter_reader=lambda _: E('Resolved', 7),
                                     gateway_reader=lambda *args: E('Preferred', 7),
                                     route_reader=err)
        self.assertEqual(result.classification, 'Unavailable')
        self.assertNotIn('SENSITIVE', str(result))

    def test_invalid_input_prevents_callback(self):
        def fail(*_): self.fail('no reader should be called')
        cases = [('..\\bad', GW, PI), (ALIAS, 'invalid', PI),
                 (ALIAS, GW, GW), (ALIAS, '127.0.0.1', PI),
                 ('', GW, PI), (ALIAS, GW, '224.0.0.1')]
        for alias, gateway, receiver in cases:
            with self.subTest(alias=alias, gateway=gateway, receiver=receiver):
                result = m.probe_native_path(alias, gateway, receiver,
                                             adapter_reader=fail, gateway_reader=fail,
                                             route_reader=fail)
                self.assertEqual(result.classification, 'Unavailable')

    def test_bad_injected_dependency_refused(self):
        result = m.probe_native_path(ALIAS, GW, PI, adapter_reader='bad',
                                     gateway_reader=lambda *args: None,
                                     route_reader=lambda *args: None)
        self.assertEqual(result.classification, 'Unavailable')

    def test_module_import_is_inert(self):
        with patch.object(m, '_resolve_readers', side_effect=AssertionError('native forbidden')):
            self.assertEqual(m.main(['--check-inert']), 0)

    def test_explicit_live_cli_not_available(self):
        with self.assertRaises(SystemExit):
            m.main(['--live-read-only'])

    def test_data_class_invariants(self):
        with self.assertRaises(ValueError): m.NativePathAssessment('Healthy', 'fake')
        with self.assertRaises(ValueError): m.NativePathAssessment('NativePathVerified', 'fake')
        with self.assertRaises(ValueError): m.NativePathAssessment('Unavailable', 'fake', 7)
        with self.assertRaises(ValueError): m.NativePathAssessment('NativePathVerified', 'fake', True)

    def test_callback_returning_malicious_string_never_used(self):
        result, _ = self.run_case(first=E('Bad/Untrusted', 7))
        self.assertEqual(result.reason, 'AdapterIdentityUnavailable')

    def test_no_side_effects_in_cli_subprocess(self):
        p = subprocess.run([sys.executable, '-I', '-B', str(MOD / 'OnyxNativePathAssessment.py'),
                            '--check-inert'], capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(json.loads(p.stdout)['native_api_invoked'])


if __name__ == '__main__':
    unittest.main()
