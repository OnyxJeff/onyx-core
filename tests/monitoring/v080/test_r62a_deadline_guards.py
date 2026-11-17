"""R6.2A offline regression: deadline guards (NOT whole-worker containment)."""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'windows' / 'monitoring' / 'v080'))

import OnyxV080SessionSupervisor as supervisor
import OnyxV080ReleaseOperator as operator
import OnyxGuardedRuntimeBridge as bridge


class FakeClock:
    def __init__(self, start=0):
        self.t = start

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class R62ADeadlineGuards(unittest.TestCase):
    def test_slow_worker_is_not_success(self):
        clock = FakeClock()

        def worker():
            clock.t = 90
            return True

        outcome = supervisor.supervise_session(
            supervisor.SessionPolicy(1, 60),
            authorize=lambda: True,
            active_console=lambda: True,
            attest_source=lambda: True,
            run_one_cycle=worker,
            clock=clock.now, sleep=clock.sleep)
        self.assertEqual((outcome.state, outcome.completed_cycles, outcome.attempts),
                         ('Expired', 0, 1))

    def test_natural_expiration_takes_precedence_over_grant_cutoff(self):
        clock = FakeClock()
        outcome = supervisor.supervise_session(
            supervisor.SessionPolicy(2, 60),
            authorize=lambda: clock.t < 60,
            active_console=lambda: True,
            attest_source=lambda: True,
            run_one_cycle=lambda: True,
            clock=clock.now, sleep=clock.sleep)
        self.assertEqual((outcome.state, outcome.completed_cycles), ('Expired', 1))

    def test_runtime_bridge_refuses_late_record_completion(self):
        clock = FakeClock(59)
        records = []

        def recorder(_path, value):
            records.append(value)
            clock.t = 64

        def monitor_loop(config, *, count, interval_seconds, probe, emit):
            emit({'synthetic': True})
            return 1

        with patch.object(bridge.native, 'validate_sid', return_value='S-1-5-21-123-456-789-1000'):
            with self.assertRaises(bridge.RuntimeBridgeRefused):
                bridge.run_authorized_cycles(
                    bridge.BoundedRuntimePolicy(1),
                    approved_sid='S-1-5-21-123-456-789-1000',
                    authorize_cycle=lambda: clock.t < 60,
                    storage_profile=lambda: 'release',
                    history_path=lambda: Path('/synthetic/incident-history.sqlite3'),
                    load_config=lambda: {}, verify_context=lambda c: None,
                    global_lock=lambda sid: nullcontext(),
                    foreground_lock=lambda: nullcontext(),
                    monitor_loop=monitor_loop,
                    probe=lambda c: {}, recorder=recorder)
        # A record may already have been written. Containment is NOT proved.
        self.assertEqual(len(records), 1)

    def test_bridge_authorizer_inherits_foreground_deadline(self):
        clock = FakeClock()

        class DummyWiring:
            def __init__(self, source_root, config_path, manifest, approved_sid, cycles=1):
                self.source_root = source_root
                self.config_path = config_path
                self.manifest = manifest
                self.approved_sid = approved_sid
                self.cycles = cycles

        reviewed = types.SimpleNamespace(wiring=DummyWiring(
            Path('/synthetic'), Path('/synthetic/config.json'), None,
            'S-1-5-21-123-456-789-1000'))

        class Att:
            def build_rechecking_authorizer(self, **kw):
                return lambda: True

            def _native_active_console(self):
                return True

        class Binding:
            @staticmethod
            def read_reviewed_release_config(wiring):
                return {'monitoring_interval_seconds': 120}

            @staticmethod
            def run_explicitly_approved_api(wiring, *, build_authorizer):
                check = build_authorizer(root=wiring.source_root, manifest=wiring.manifest,
                    config=wiring.config_path, approved_sid=wiring.approved_sid)
                clock.t = 90
                return check()

        class Integration:
            @staticmethod
            def run_reviewed_session(*, wiring, run_release_cycle, **kw):
                self_check = run_release_cycle(wiring)
                if self_check is not False:
                    raise AssertionError('bridge authorizer did not expire')
                return types.SimpleNamespace(state='Expired', attempts=1,
                    completed_cycles=0, persisted_cycles=0)

        result = operator._run_protected_session(
            reviewed=reviewed, context=None, att=Att(), binding=Binding,
            checker=lambda **kw: None, cycles=1, duration_minutes=1,
            integration=Integration, supervision=supervisor,
            clock=clock.now, sleep=clock.sleep)
        self.assertEqual((result['result'], result['persisted_cycles']), ('EXPIRED', 0))

    def test_worker_false_retry_budget_unchanged(self):
        clock = FakeClock()
        attempts = iter([False, False, False])
        outcome = supervisor.supervise_session(
            supervisor.SessionPolicy(1, 300, 90),
            authorize=lambda: True, active_console=lambda: True,
            attest_source=lambda: True, run_one_cycle=lambda: next(attempts),
            clock=clock.now, sleep=clock.sleep)
        self.assertEqual((outcome.state, outcome.attempts, outcome.worker_failures),
                         ('WorkerFailureLimit', 3, 3))

    def test_worker_exception_still_propagates(self):
        clock = FakeClock()
        def broken():
            raise PermissionError('synthetic denial')
        with self.assertRaisesRegex(PermissionError, 'synthetic denial'):
            supervisor.supervise_session(supervisor.SessionPolicy(1, 60),
                authorize=lambda: True, active_console=lambda: True,
                attest_source=lambda: True, run_one_cycle=broken,
                clock=clock.now, sleep=clock.sleep)


if __name__ == '__main__':
    unittest.main()
