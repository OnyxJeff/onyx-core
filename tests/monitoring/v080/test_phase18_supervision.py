"""Phase 18C pure offline tests; no network, Windows APIs or operational stores."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'windows/monitoring/v080/OnyxOfflineProductionSupervisor.py'
spec = importlib.util.spec_from_file_location('onyx18c', SOURCE)
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def permit():
    return module.Admission(True, True, True, True, True, False, True)


class FakeClock:
    def __init__(self, advance=0):
        self.at = 100.0
        self.advance = advance
        self.slept = []

    def time(self):
        result = self.at
        self.at += self.advance
        return result

    def sleep(self, sec):
        self.slept.append(sec)
        self.at += sec


class OfflineSupervisionTests(unittest.TestCase):
    def test_capabilities_fail_closed(self):
        self.assertEqual(module.inert_status()['production_release'], 'HOLD')
        self.assertFalse(module.inert_status()['runtime_enabled'])
        self.assertFalse(module.inert_status()['live_probe_authorized'])

    def test_default_policy(self):
        p = module.Policy()
        self.assertEqual((p.interval_seconds, p.maximum_cycles), (120, 20))

    def test_rejects_invalid_interval_and_count(self):
        for n in (-1, 0, 89, 3601, 120.0, True, '120'):
            with self.subTest(interval=n), self.assertRaises(module.SupervisionRefused):
                module.Policy(interval_seconds=n)
        for n in (0, 21, 1.0, True, '1'):
            with self.subTest(count=n), self.assertRaises(module.SupervisionRefused):
                module.Policy(maximum_cycles=n)

    def test_healthy_fixture_cycles(self):
        clock = FakeClock()
        cycles = []
        result = module.simulate_bounded_supervision(
            module.Policy(maximum_cycles=3), admission=permit,
            fixture_cycle=lambda: cycles.append('fake'),
            monotonic=clock.time, sleep=clock.sleep)
        self.assertEqual(len(cycles), 3)
        self.assertEqual(clock.slept, [120.0, 120.0])
        self.assertEqual(result.cycles, 3)
        self.assertFalse(result.production_runtime_enabled)

    def test_no_catchup_after_overrun(self):
        clock = FakeClock(advance=130.0)
        result = module.simulate_bounded_supervision(
            module.Policy(maximum_cycles=3), admission=permit,
            fixture_cycle=lambda: None, monotonic=clock.time, sleep=clock.sleep)
        self.assertEqual(clock.slept, [])
        self.assertEqual(result.ignored_catchup, 2)

    def test_revocation_checked_each_cycle(self):
        clock = FakeClock()
        admission_calls = [0]
        samples = []
        def gate():
            admission_calls[0] += 1
            return permit() if admission_calls[0] == 1 else replace(permit(), revoked=True)
        with self.assertRaises(module.SupervisionRefused):
            module.simulate_bounded_supervision(module.Policy(maximum_cycles=3),
                admission=gate, fixture_cycle=lambda: samples.append(1),
                monotonic=clock.time, sleep=clock.sleep)
        self.assertEqual(samples, [1])
        self.assertEqual(admission_calls[0], 2)

    def test_admission_negative_matrix(self):
        for field in ('revision_matches', 'identity_matches', 'storage_profile_release',
                      'grant_valid', 'source_trusted'):
            with self.subTest(field=field), self.assertRaises(module.SupervisionRefused):
                replace(permit(), **{field: False}).allow_fixture_cycle()
        with self.assertRaises(module.SupervisionRefused):
            replace(permit(), simulation_only=False).allow_fixture_cycle()

    def test_missing_adapter_refused(self):
        with self.assertRaises(module.SupervisionRefused):
            module.simulate_bounded_supervision(module.Policy(), admission=None,
                fixture_cycle=lambda: None, monotonic=lambda: 0, sleep=lambda _: None)

    def test_backward_clock_refused(self):
        times = iter((20.0, 19.0))
        with self.assertRaises(module.SupervisionRefused):
            module.simulate_bounded_supervision(module.Policy(maximum_cycles=1),
                admission=permit, fixture_cycle=lambda: None,
                monotonic=lambda: next(times), sleep=lambda _: None)

    def test_lock_failure_refuses_before_cycle(self):
        @contextmanager
        def busy():
            raise module.SupervisionRefused('busy')
            yield
        events = []
        with self.assertRaises(module.SupervisionRefused):
            module.simulate_bounded_supervision(module.Policy(maximum_cycles=1),
                admission=permit, fixture_cycle=lambda: events.append('sample'),
                monotonic=lambda: 5., sleep=lambda _: None, exclusive=busy)
        self.assertEqual(events, [])

    def test_fixture_exception_propagates(self):
        def broken():
            raise RuntimeError('synthetic failure')
        with self.assertRaises(RuntimeError):
            module.simulate_bounded_supervision(module.Policy(maximum_cycles=1),
                admission=permit, fixture_cycle=broken,
                monotonic=lambda: 5., sleep=lambda _: None)


if __name__ == '__main__':
    unittest.main()
