"""R3 release monitor revocation and bounded stop tests; no native APIs/network."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
MOD = ROOT / 'windows' / 'monitoring' / 'v080'
sys.path.insert(0, str(MOD))
import OnyxV080ReleaseBinding as binding


class R3RevocationTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.calls = []
        self.results = []
        self.authorize = lambda: True
        self.example = json.loads((ROOT/'windows/monitoring/monitoring.v080.release.example.json').read_text())

    def clock(self):
        return self.now

    def sleep(self, n):
        self.calls.append(('sleep', n))
        self.now += n

    def probe(self, cfg):
        self.calls.append(('probe', self.now))
        return {
            'source': 'OnyxV080LiveConnectivity', 'status': 'Unknown',
            'reason': 'DiagnosticEvidenceUnavailable',
            'windows': {'classification':'WindowsProbeUnavailable'},
            'pi': {'classification':'PiProbeUnavailable'},
            'issues': ['WindowsDiagnosticUnavailable'],
            'checked_at_utc': '2026-11-14T00:00:00+00:00',
            'repair_action': 'None', 'incident_history_written': False,
            'notification_sent': False, 'scheduler_enabled': False,
        }

    def run_real_m2(self, *, authorize=None, cycles=2, sleep=None):
        return binding._run_revocation_aware_monitor(
            self.example, count=cycles, interval_seconds=120,
            probe=self.probe, emit=self.results.append,
            authorize=authorize if authorize is not None else self.authorize,
            sleep=sleep if sleep is not None else self.sleep, clock=self.clock)

    def test_no_probe_before_function_invoked(self):
        self.assertEqual(self.calls, [])

    def test_two_cycles_with_chunked_interval(self):
        self.assertEqual(self.run_real_m2(), 2)
        self.assertEqual(len(self.results), 2)
        self.assertEqual(len([x for x in self.calls if x[0]=='probe']), 2)
        self.assertEqual(len([x for x in self.calls if x[0]=='sleep']), 60)
        self.assertTrue(all(x[1] <= 2 for x in self.calls if x[0]=='sleep'))

    def test_revocation_before_first_wait_prevents_second_cycle(self):
        checks = 0
        def authorize():
            nonlocal checks
            checks += 1
            return checks <= 0
        with self.assertRaises(binding.ReleaseBindingRefused):
            self.run_real_m2(authorize=authorize)
        self.assertEqual(len(self.results), 1)
        self.assertEqual(len([x for x in self.calls if x[0]=='probe']), 1)

    def test_revocation_during_sleep_stops_before_next_probe(self):
        def authorize():
            return self.now < 4
        with self.assertRaises(binding.ReleaseBindingRefused):
            self.run_real_m2(authorize=authorize)
        self.assertEqual(len(self.results), 1)
        self.assertLessEqual(self.now, 4)

    def test_authorizer_exception_propagates(self):
        def auth():
            raise RuntimeError('credential unavailable')
        with self.assertRaisesRegex(RuntimeError, 'credential unavailable'):
            self.run_real_m2(authorize=auth)
        self.assertEqual(len(self.results), 1)

    def test_nonbool_authorizer_denied(self):
        for invalid in (1, 'yes', None):
            with self.subTest(invalid=invalid), self.assertRaises(binding.ReleaseBindingRefused):
                self.run_real_m2(authorize=lambda: invalid)

    def test_keyboard_interrupt_propagates_for_lock_cleanup(self):
        def stop(n):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_real_m2(sleep=stop)
        self.assertEqual(len(self.results), 1)

    def test_no_sleep_for_single_cycle(self):
        self.assertEqual(self.run_real_m2(cycles=1), 1)
        self.assertFalse(any(t=='sleep' for t, _ in self.calls))

    def test_validation_before_probe(self):
        for key in ('authorize','sleep','clock','emit','probe'):
            kw = dict(count=2, interval_seconds=120, probe=self.probe,
                      emit=self.results.append, authorize=lambda: True,
                      sleep=self.sleep, clock=self.clock)
            kw[key]=None
            with self.subTest(key=key), self.assertRaises(binding.ReleaseBindingRefused):
                binding._run_revocation_aware_monitor(self.example, **kw)
        self.assertEqual(self.results, [])

    def test_invalid_wait_refused_without_sleep(self):
        # Run the helper with a stub M2 scheduler issuing a corrupt wait.
        def corrupt(config, **kwargs):
            kwargs['sleeper'](float('nan'))
        with patch.object(binding.m2, 'run_monitor', side_effect=corrupt):
            with self.assertRaises(binding.ReleaseBindingRefused):
                self.run_real_m2()
        self.assertEqual(self.calls, [])

    def test_m2_errors_not_translated_to_connectivity(self):
        with patch.object(binding.m2, 'run_monitor', side_effect=RuntimeError('unexpected scheduler failure')):
            with self.assertRaisesRegex(RuntimeError, 'unexpected scheduler failure'):
                self.run_real_m2()

    def test_release_binding_remains_inert_cli(self):
        with self.assertRaises(SystemExit):
            binding.main(['--run'])
        self.assertEqual(binding.main(['--check-inert']),0)

if __name__=='__main__':
    unittest.main()
