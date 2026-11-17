"""R4 pure policy tests. No Windows IO, live telemetry, credentials or scheduling."""
import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[3] / 'windows' / 'monitoring' / 'v080' / 'OnyxV080SessionSupervisor.py'
# tests/monitoring/v080 -> repo root via parents[3]
import sys
spec = importlib.util.spec_from_file_location('OnyxV080SessionSupervisor', MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class FakeClock:
    def __init__(self): self.t = 0.0; self.slices = []
    def now(self): return self.t
    def sleep(self, seconds):
        self.slices.append(seconds)
        self.t += seconds


class R4SessionTests(unittest.TestCase):
    def test_constructor_limits(self):
        for bad in (0, -1, 21, True, 2.5, '2'):
            with self.subTest(bad=bad), self.assertRaises(m.SupervisionRefused):
                m.SessionPolicy(bad, 120)
        for bad in (0, -1, 86401, True, 2.1, '1'):
            with self.subTest(bad=bad), self.assertRaises(m.SupervisionRefused):
                m.SessionPolicy(2, bad)
        for bad in (0, 89, 3601, True, 120.1):
            with self.subTest(bad=bad), self.assertRaises(m.SupervisionRefused):
                m.SessionPolicy(2, 900, bad)
        for bad in (0, 4, True, 2.0):
            with self.subTest(bad=bad), self.assertRaises(m.SupervisionRefused):
                m.SessionPolicy(2, 900, 120, bad)

    def runner(self, policy=None, *, results=(True,), clock=None, authorize=None,
               session=None, source=None, worker=None):
        c = clock or FakeClock()
        results = iter(results)
        events = []
        def r():
            events.append('worker')
            return next(results)
        kw = dict(authorize=authorize or (lambda: True),
                  active_console=session or (lambda: True),
                  attest_source=source or (lambda: True),
                  run_one_cycle=worker or r, clock=c.now, sleep=c.sleep)
        return m.supervise_session(policy or m.SessionPolicy(1, 300), **kw), c, events

    def test_single_cycle(self):
        value, clock, ev = self.runner()
        self.assertEqual(value.state, 'Completed')
        self.assertEqual((value.attempts, value.completed_cycles, value.worker_failures), (1,1,0))
        self.assertEqual(ev, ['worker'])
        self.assertFalse(value.tasks_created or value.notifications_sent or value.repairs_invoked)

    def test_multi_cycle_wait_sliced(self):
        value, c, ev = self.runner(m.SessionPolicy(2, 300, 90), results=(True,True))
        self.assertEqual(value.state, 'Completed')
        self.assertEqual(c.t, 90)
        self.assertEqual(max(c.slices), 2)
        self.assertEqual(len(ev), 2)

    def test_expiry_blocks_next_cycle(self):
        v, c, ev = self.runner(m.SessionPolicy(2, 20, 90), results=(True,True))
        self.assertEqual(v.state, 'Expired')
        self.assertEqual(len(ev), 1)
        self.assertEqual(c.t, 20)

    def test_expired_before_worker(self):
        c = FakeClock()
        def auth(): c.t = 1000; return True
        # Deadline must be checked again after slow authorization.
        outcome, _clock, events = self.runner(
            m.SessionPolicy(2, 120), results=(True,), clock=c, authorize=auth)
        self.assertEqual(outcome.state, 'Expired')
        self.assertEqual(events, [])

    def test_revocation_during_wait(self):
        c = FakeClock()
        with self.assertRaisesRegex(m.SupervisionRefused,'revoked'):
            self.runner(m.SessionPolicy(2, 300, 90), results=(True, True), clock=c,
                        authorize=lambda: c.t < 7)
        self.assertLessEqual(c.t, 8)

    def test_session_lost_during_wait(self):
        c = FakeClock()
        with self.assertRaisesRegex(m.SupervisionRefused,'console'):
            self.runner(m.SessionPolicy(2, 300, 90), results=(True, True), clock=c,
                        session=lambda: c.t < 5)

    def test_source_changed_during_wait(self):
        c = FakeClock()
        with self.assertRaisesRegex(m.SupervisionRefused,'attestation'):
            self.runner(m.SessionPolicy(2, 300, 90), results=(True, True), clock=c,
                        source=lambda: c.t < 5)

    def test_initial_denial_calls_no_worker(self):
        for selector in ('authorize','session','source'):
            def reject(): return False
            kwargs={selector: reject}
            with self.subTest(selector=selector), self.assertRaises(m.SupervisionRefused):
                self.runner(**kwargs)

    def test_nonboolean_callback_denied(self):
        for selector in ('authorize','session','source'):
            kwargs={selector: lambda: 1}
            with self.subTest(selector=selector), self.assertRaises(m.SupervisionRefused):
                self.runner(**kwargs)

    def test_worker_failure_retry(self):
        v, c, ev = self.runner(m.SessionPolicy(1, 300, 90), results=(False, True))
        self.assertEqual((v.attempts, v.completed_cycles, v.worker_failures), (2,1,1))
        self.assertEqual(c.t, 5)

    def test_worker_failure_limit(self):
        v, c, ev = self.runner(m.SessionPolicy(2, 300, 90), results=(False,False,False))
        self.assertEqual(v.state,'WorkerFailureLimit')
        self.assertEqual((v.attempts, v.worker_failures, v.completed_cycles), (3,3,0))
        self.assertEqual(c.t,20)

    def test_failure_counter_reset_after_success(self):
        v,c,ev=self.runner(m.SessionPolicy(2, 700, 90), results=(False,True,False,True))
        self.assertEqual(v.state,'Completed')
        self.assertEqual((v.attempts,v.completed_cycles,v.worker_failures),(4,2,2))

    def test_bad_worker_result_denied(self):
        for value in (None,0,1,'ok',{},(True,)):
            with self.subTest(value=value),self.assertRaisesRegex(m.SupervisionRefused,'boolean'):
                self.runner(worker=lambda: value)

    def test_worker_exception_propagates(self):
        def worker(): raise ValueError('synthetic worker exception')
        with self.assertRaisesRegex(ValueError,'synthetic'):
            self.runner(worker=worker)

    def test_invalid_clock_rejected(self):
        for bad in (float('inf'),float('nan'), True, 'x'):
            with self.subTest(bad=bad), self.assertRaises(m.SupervisionRefused):
                m.supervise_session(m.SessionPolicy(1,300),authorize=lambda:True,
                    active_console=lambda:True,attest_source=lambda:True,
                    run_one_cycle=lambda:True,clock=lambda:bad,sleep=lambda _:None)

    def test_missing_dependency_denied(self):
        for bad in (None,1,False):
            with self.subTest(bad=bad), self.assertRaises(m.SupervisionRefused):
                m.supervise_session(m.SessionPolicy(1,300),authorize=bad,
                    active_console=lambda:True,attest_source=lambda:True,
                    run_one_cycle=lambda:True,clock=lambda:0,sleep=lambda _:None)

    def test_no_unbounded_run_policy(self):
        with self.assertRaises(m.SupervisionRefused):
            m.SessionPolicy(1000000,86400)

    def test_cli_inert(self):
        import contextlib,io
        buf=io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(m.main(['--check-inert']),0)
        self.assertIn('"live_execution_enabled": false',buf.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            m.main(['--start'])


if __name__=='__main__': unittest.main()
