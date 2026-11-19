#!/usr/bin/env python3
"""RC2: deterministic Pi USB listener readiness tests, no live service/DB changes."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'tools/installation/pi/onyx_pi_rehearsal.py'
spec = importlib.util.spec_from_file_location('onyx_pi_rc2', SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
GOOD = ['192.168.137.167:8765']


class PiReadinessTest(unittest.TestCase):
    def units(self, unit):
        return {'active': 'active' if unit == mod.CANDIDATE else 'inactive'}

    def test_candidate_ready_immediately_no_sleep(self):
        with patch.object(mod, 'state', side_effect=self.units), \
             patch.object(mod, 'listeners', return_value=GOOD), \
             patch.object(mod.time, 'sleep') as sleeper:
            mod.wait_receiver_ready('Candidate', mod.CANDIDATE, mod.LEGACY)
            sleeper.assert_not_called()

    def test_candidate_delayed_socket_waits_boundedly(self):
        with patch.object(mod, 'state', side_effect=self.units), \
             patch.object(mod, 'listeners', side_effect=[[], [], GOOD]), \
             patch.object(mod.time, 'sleep') as sleeper:
            mod.wait_receiver_ready('Candidate', mod.CANDIDATE, mod.LEGACY)
            self.assertEqual(2, sleeper.call_count)

    def test_legacy_delayed_socket_waits_boundedly(self):
        def restored(unit):
            return {'active': 'active' if unit == mod.LEGACY else 'inactive'}
        with patch.object(mod, 'state', side_effect=restored), \
             patch.object(mod, 'listeners', side_effect=[[], GOOD]), \
             patch.object(mod.time, 'sleep') as sleeper:
            mod.wait_receiver_ready('Legacy', mod.LEGACY, mod.CANDIDATE)
            self.assertEqual(1, sleeper.call_count)

    def test_refuses_concurrent_receiver_without_waiting(self):
        with patch.object(mod, 'state', return_value={'active': 'active'}), \
             patch.object(mod, 'listeners') as get_sockets, \
             patch.object(mod.time, 'sleep') as sleeper:
            with self.assertRaisesRegex(mod.Refused, 'conflicting receiver active'):
                mod.wait_receiver_ready('Candidate', mod.CANDIDATE, mod.LEGACY)
            get_sockets.assert_not_called()
            sleeper.assert_not_called()

    def test_refuses_wildcard_binding_immediately(self):
        with patch.object(mod, 'state', side_effect=self.units), \
             patch.object(mod, 'listeners', return_value=['0.0.0.0:8765']), \
             patch.object(mod.time, 'sleep') as sleeper:
            with self.assertRaisesRegex(mod.Refused, 'unexpected/multiple'):
                mod.wait_receiver_ready('Candidate', mod.CANDIDATE, mod.LEGACY)
            sleeper.assert_not_called()

    def test_refuses_duplicate_binding_immediately(self):
        with patch.object(mod, 'state', side_effect=self.units), \
             patch.object(mod, 'listeners', return_value=GOOD + GOOD), \
             patch.object(mod.time, 'sleep') as sleeper:
            with self.assertRaisesRegex(mod.Refused, 'unexpected/multiple'):
                mod.wait_receiver_ready('Candidate', mod.CANDIDATE, mod.LEGACY)
            sleeper.assert_not_called()

    def test_missing_socket_times_out_without_service_mutation(self):
        with patch.object(mod, 'state', side_effect=self.units), \
             patch.object(mod, 'listeners', return_value=[]), \
             patch.object(mod.time, 'sleep') as sleeper, \
             patch.object(mod, 'run') as runner, \
             patch.object(mod, 'set_phase') as journal:
            with self.assertRaisesRegex(mod.Refused, 'not ready after 3 checks'):
                mod.wait_receiver_ready('Candidate', mod.CANDIDATE, mod.LEGACY,
                                        attempts=3, pause_seconds=0)
            self.assertEqual(2, sleeper.call_count)
            runner.assert_not_called()
            journal.assert_not_called()

    def test_invalid_readiness_configuration_refused(self):
        for attempts, pause in ((0, 1), (31, 1), (4, -1), (4, 3)):
            with self.assertRaises(ValueError):
                mod.wait_receiver_ready('Candidate', mod.CANDIDATE, mod.LEGACY,
                                        attempts=attempts, pause_seconds=pause)

    def test_activation_and_rollback_use_waiter(self):
        import inspect
        self.assertIn("wait_receiver_ready('Candidate', CANDIDATE, LEGACY)",
                      inspect.getsource(mod.activate))
        self.assertIn("wait_receiver_ready('Legacy', LEGACY, CANDIDATE)",
                      inspect.getsource(mod.rollback))


if __name__ == '__main__':
    unittest.main(verbosity=2)
