"""ONYX CORE v0.8.0: mock-only LOW-integrity acceptance contract tests."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

SOURCE = (Path(__file__).resolve().parents[3] / 'windows' / 'monitoring' /
          'v080' / 'OnyxNativeLowIntegrityAcceptance.py')
spec = importlib.util.spec_from_file_location('onyx_low_offline_contract', SOURCE)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def facts(**override):
    base = dict.fromkeys(mod._REQUIRED, True)
    base.update(override)
    return mod.OfflineBoundary(**base)


class NativeLowIntegrityContractTests(unittest.TestCase):
    def test_verified_path_only_simulated_eligible(self):
        result = mod.simulate_acceptance(facts(), 'NativePathVerified')
        self.assertEqual(result.decision, 'SimulatedEligible')
        self.assertFalse(result.windows_health_claimed)
        self.assertFalse(result.live_authorized)
        self.assertFalse(result.native_api_invoked)
        self.assertEqual(result.release_status, 'HOLD')

    def test_confirmed_alternate_route_does_not_claim_health(self):
        result = mod.simulate_acceptance(facts(), 'RouteMismatch')
        self.assertEqual(result.decision, 'SimulatedEligible')
        self.assertEqual(result.simulated_native_classification, 'RouteMismatch')
        self.assertFalse(result.windows_health_claimed)

    def test_gateway_not_preferred_remains_synthetic(self):
        result = mod.simulate_acceptance(facts(), 'GatewayNotPreferred')
        self.assertEqual(result.decision, 'SimulatedEligible')
        self.assertEqual(result.simulated_native_classification, 'GatewayNotPreferred')

    def test_unavailable_always_hold(self):
        result = mod.simulate_acceptance(facts(), 'Unavailable')
        self.assertEqual(result.decision, 'SimulatedHold')
        self.assertEqual(result.reason, 'NativeEvidenceUnavailable')

    def test_every_missing_boundary_fact_holds(self):
        for key in mod._REQUIRED:
            with self.subTest(missing=key):
                result = mod.simulate_acceptance(facts(**{key: False}), 'NativePathVerified')
                self.assertEqual(result.decision, 'SimulatedHold')
                self.assertEqual(result.reason, 'MissingBoundaryEvidence')
                self.assertFalse(result.live_authorized)

    def test_invalid_mock_boolean_rejected(self):
        for value in (1, 0, None, 'True', [], object()):
            with self.subTest(value=str(type(value))):
                with self.assertRaises(ValueError):
                    facts(job_member_verified=value)

    def test_missing_or_extra_fact_rejected(self):
        with self.assertRaises(TypeError):
            mod.OfflineBoundary(**dict.fromkeys(mod._REQUIRED[:-1], True))
        with self.assertRaises(TypeError):
            facts(extraneous=True)

    def test_untrusted_boundary_result_refused(self):
        for bad in ({}, True, None, 'mock', object()):
            with self.subTest(bad=type(bad).__name__):
                self.assertEqual(mod.simulate_acceptance(bad, 'NativePathVerified').decision,
                                 'SimulatedHold')

    def test_unknown_and_escalated_native_states_refused(self):
        for state in ('Healthy', 'WindowsPathReady', 'PiInternetVerified',
                      '', 'confirmed', None, True, 3, 'NativePathVerified\nERROR'):
            with self.subTest(state=str(state)):
                self.assertEqual(mod.simulate_acceptance(facts(), state).decision,
                                 'SimulatedHold')

    def test_no_raw_error_text_in_receipt(self):
        sensitive = 'SECRET_TOKEN_HERE'
        r = mod.simulate_acceptance(facts(), sensitive).as_dict()
        self.assertNotIn(sensitive, json.dumps(r))
        self.assertEqual(set(r), {'decision', 'reason', 'simulated_native_classification',
                                  'schema_version', 'phase', 'simulation_only',
                                  'release_status', 'live_authorized', 'native_api_invoked',
                                  'windows_health_claimed'})

    def test_receipt_is_immutable(self):
        receipt = mod.simulate_acceptance(facts(), 'NativePathVerified')
        with self.assertRaises(FrozenInstanceError):
            receipt.release_status = 'GO'
        with self.assertRaises(ValueError):
            replace(receipt, live_authorized=True)
        with self.assertRaises(ValueError):
            replace(receipt, windows_health_claimed=True)
        with self.assertRaises(ValueError):
            replace(receipt, native_api_invoked=True)
        with self.assertRaises(ValueError):
            replace(receipt, simulation_only=False)

    def test_boundary_is_immutable(self):
        receipt = facts()
        with self.assertRaises(FrozenInstanceError):
            receipt.job_member_verified = False

    def test_no_import_of_native_or_containment_modules(self):
        source = SOURCE.read_text(encoding='utf-8')
        forbidden = ('ctypes', 'OnyxNativePathAssessment', 'OnyxWindowsJobRunner',
                     'subprocess', 'socket', 'ssh.exe', 'powershell.exe')
        for word in forbidden:
            with self.subTest(word=word):
                self.assertNotIn('import ' + word, source)

    def test_inert_cli_prints_no_host_claims(self):
        p = subprocess.run([sys.executable, '-I', '-B', str(SOURCE), '--check-inert'],
                           capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        result = json.loads(p.stdout)
        self.assertTrue(result['simulation_only'])
        self.assertEqual(result['decision'], 'SimulatedHold')
        self.assertFalse(result['native_api_invoked'])

    def test_live_cli_is_not_implemented(self):
        for command in ('--live-read-only', '--run-native', '--run-contained-probe'):
            with self.subTest(command=command):
                p = subprocess.run([sys.executable, '-I', '-B', str(SOURCE), command],
                                   capture_output=True, text=True, timeout=10, check=False)
                self.assertNotEqual(p.returncode, 0)
                self.assertNotIn('SECRET_TOKEN_HERE', p.stdout + p.stderr)

    def test_no_result_can_authorize_release(self):
        for native in ('NativePathVerified', 'RouteMismatch',
                       'GatewayNotPreferred', 'Unavailable'):
            with self.subTest(native=native):
                receipt = mod.simulate_acceptance(facts(), native).as_dict()
                self.assertEqual(receipt['release_status'], 'HOLD')
                self.assertFalse(receipt['live_authorized'])
                self.assertFalse(receipt['windows_health_claimed'])

    def test_import_does_not_call_native_loader(self):
        with patch('ctypes.CDLL', side_effect=AssertionError('native load attempted')):
            with patch('ctypes.WinDLL', create=True,
                       side_effect=AssertionError('native load attempted')):
                replacement = importlib.util.spec_from_file_location(
                    'onyx_low_import_test', SOURCE)
                candidate = importlib.util.module_from_spec(replacement)
                sys.modules[replacement.name] = candidate
                try:
                    replacement.loader.exec_module(candidate)
                finally:
                    sys.modules.pop(replacement.name, None)

    def test_receipt_does_not_expose_interface_index_or_network_details(self):
        receipt = mod.simulate_acceptance(facts(), 'NativePathVerified').as_dict()
        body = json.dumps(receipt)
        for forbidden in ('192.168.', 'Ethernet 3', 'interface_index', 'user_sid',
                          'source_path', 'token', 'host_name'):
            self.assertNotIn(forbidden, body)

    def test_low_integrity_value_is_exact(self):
        self.assertEqual(mod.LOW_INTEGRITY_RID, 0x1000)
        self.assertNotEqual(mod.LOW_INTEGRITY_RID, 0x2000)

    def test_invalid_receipt_constructor_rejected(self):
        with self.assertRaises(ValueError):
            mod.OfflineAcceptance('Healthy', 'SimulatedAcceptancePlanOnly', 'NativePathVerified')
        with self.assertRaises(ValueError):
            mod.OfflineAcceptance('SimulatedEligible', 'fake raw source error',
                                  'NativePathVerified')
        with self.assertRaises(ValueError):
            mod.OfflineAcceptance('SimulatedEligible', 'SimulatedAcceptancePlanOnly',
                                  'WindowsPathReady')

    def test_receipt_decision_reason_classification_matrix(self):
        # Exhaust all 2 x 4 x 4 allow-listed combinations, not just normal calls.
        native_results = ('NativePathVerified', 'RouteMismatch',
                          'GatewayNotPreferred', 'Unavailable')
        eligible_results = native_results[:-1]
        valid = {
            ('SimulatedEligible', 'SimulatedAcceptancePlanOnly', native)
            for native in eligible_results
        }
        valid.update({
            ('SimulatedHold', 'MissingBoundaryEvidence', native)
            for native in native_results
        })
        valid.update({
            ('SimulatedHold', 'InvalidBoundaryEvidence', 'Unavailable'),
            ('SimulatedHold', 'NativeEvidenceUnavailable', 'Unavailable'),
        })

        for decision in ('SimulatedEligible', 'SimulatedHold'):
            for reason in sorted(mod._REASONS):
                for native in native_results:
                    triple = (decision, reason, native)
                    with self.subTest(triple=triple):
                        if triple in valid:
                            receipt = mod.OfflineAcceptance(*triple)
                            self.assertEqual(
                                (receipt.decision, receipt.reason,
                                 receipt.simulated_native_classification), triple)
                            self.assertFalse(receipt.live_authorized)
                            self.assertEqual(receipt.release_status, 'HOLD')
                        else:
                            with self.assertRaises(ValueError):
                                mod.OfflineAcceptance(*triple)

    def test_replace_cannot_forge_inconsistent_receipt(self):
        eligible = mod.simulate_acceptance(facts(), 'NativePathVerified')
        held = mod.simulate_acceptance(facts(), 'Unavailable')
        for receipt, changes in (
            (eligible, {'reason': 'MissingBoundaryEvidence'}),
            (eligible, {'simulated_native_classification': 'Unavailable'}),
            (held, {'decision': 'SimulatedEligible'}),
            (held, {'reason': 'SimulatedAcceptancePlanOnly'}),
            (held, {'simulated_native_classification': 'NativePathVerified'}),
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    replace(receipt, **changes)

    def test_missing_boundary_with_unavailable_preserves_reason_precedence(self):
        receipt = mod.simulate_acceptance(
            facts(job_member_verified=False), 'Unavailable')
        self.assertEqual(receipt.decision, 'SimulatedHold')
        self.assertEqual(receipt.reason, 'MissingBoundaryEvidence')
        self.assertEqual(receipt.simulated_native_classification, 'Unavailable')
        self.assertFalse(receipt.live_authorized)

    def test_no_network_file_or_process_invocation_in_simulator(self):
        with patch('subprocess.run', side_effect=AssertionError('process invoked')):
            with patch('pathlib.Path.open', side_effect=AssertionError('file opened')):
                result = mod.simulate_acceptance(facts(), 'NativePathVerified')
                self.assertEqual(result.decision, 'SimulatedEligible')


if __name__ == '__main__':
    unittest.main()
