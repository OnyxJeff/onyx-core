"""Phase 18I1: live-module wiring, executed with *only* offline adapters."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

MON = Path(__file__).resolve().parents[3] / 'windows' / 'monitoring' / 'v080'
if str(MON) not in sys.path:
    sys.path.insert(0, str(MON))
import OnyxGuardedRuntimeBridge as bridge
import OnyxLiveIncidentHistory as m3

SID = 'S-1-5-21-123-456-789-1001'


@contextmanager
def permit_lock(events, label):
    events.append(label + '-enter')
    try:
        yield
    finally:
        events.append(label + '-exit')


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.permits = [True] * 100
        self.path = Path('C:/synthetic/Monitoring/incident-history.sqlite3')

    def allow(self):
        self.events.append('authorize')
        return self.permits.pop(0)

    def fake_loop(self, config, *, count, interval_seconds, probe, emit):
        self.events.append('loop')
        for _ in range(count):
            sample = probe(config)
            emit(sample)
        return count

    def fake_record(self, path, sample):
        self.assertEqual(path, self.path)
        self.events.append('record')

    def run_bridge(self, **overrides):
        kw = dict(
            approved_sid=SID,
            authorize_cycle=self.allow,
            storage_profile=lambda: 'release',
            history_path=lambda: self.path,
            load_config=lambda: {'fixture': True},
            verify_context=lambda _: self.events.append('verify-source'),
            global_lock=lambda _: permit_lock(self.events, 'global'),
            foreground_lock=lambda: permit_lock(self.events, 'foreground'),
            monitor_loop=self.fake_loop,
            probe=lambda _: {'fixture': True},
            recorder=self.fake_record,
        )
        kw.update(overrides)
        return bridge.run_authorized_cycles(bridge.BoundedRuntimePolicy(cycles=2), **kw)

    def test_import_does_not_run(self):
        self.assertFalse(bridge.inert_status()['entrypoint_live_enabled'])

    def test_cli_inert(self):
        self.assertEqual(bridge.main(['--check-inert']), 0)
        with self.assertRaises(SystemExit):
            bridge.main(['--live'])

    def test_invalid_policy_refused(self):
        for key, value in (('cycles', 0), ('cycles', 21), ('cycles', True),
                           ('interval_seconds', 89), ('interval_seconds', 3601),
                           ('interval_seconds', '120')):
            with self.subTest(key=key, value=value), self.assertRaises(bridge.RuntimeBridgeRefused):
                bridge.BoundedRuntimePolicy(**{key: value})

    def test_policy_count_false(self):
        with self.assertRaises(bridge.RuntimeBridgeRefused):
            bridge.run_authorized_cycles(object(), approved_sid=SID, authorize_cycle=self.allow)

    def test_missing_adapters_fail_before_authorize(self):
        with self.assertRaises(bridge.RuntimeBridgeRefused):
            self.run_bridge(authorize_cycle=None)
        self.assertEqual(self.events, [])

    def test_bad_sid_before_authorization(self):
        with self.assertRaises(Exception):
            self.run_bridge(approved_sid='forged')
        self.assertEqual(self.events, [])

    def test_profile_default_development_refused(self):
        with self.assertRaises(bridge.RuntimeBridgeRefused):
            self.run_bridge(storage_profile=lambda: 'development')
        self.assertEqual(self.events, [])

    def test_initial_denial_before_locks_and_source(self):
        self.permits[0] = False
        with self.assertRaises(bridge.RuntimeBridgeRefused):
            self.run_bridge()
        self.assertEqual(self.events, ['authorize'])

    def test_denial_after_global_lock(self):
        self.permits[1] = False
        with self.assertRaises(bridge.RuntimeBridgeRefused):
            self.run_bridge()
        self.assertEqual(self.events, ['authorize', 'global-enter', 'foreground-enter',
                                       'authorize', 'foreground-exit', 'global-exit'])

    def test_denial_before_first_probe(self):
        self.permits[3] = False
        with self.assertRaises(bridge.RuntimeBridgeRefused):
            self.run_bridge()
        self.assertNotIn('record', self.events)
        self.assertIn('global-exit', self.events)

    def test_revocation_after_probe_prevents_record(self):
        self.permits[4] = False
        with self.assertRaises(bridge.RuntimeBridgeRefused):
            self.run_bridge()
        self.assertNotIn('record', self.events)
        self.assertIn('global-exit', self.events)

    def test_revocation_before_second_probe(self):
        self.permits[5] = False
        with self.assertRaises(bridge.RuntimeBridgeRefused):
            self.run_bridge()
        self.assertEqual(self.events.count('record'), 1)

    def test_authorizer_raises_no_cycle(self):
        def denied():
            raise ValueError('revoked')
        with self.assertRaises(ValueError):
            self.run_bridge(authorize_cycle=denied)
        self.assertNotIn('global-enter', self.events)

    def test_authorizer_nonbool_refused(self):
        for ret in (1, 'yes', None):
            with self.subTest(ret=ret), self.assertRaises(bridge.RuntimeBridgeRefused):
                self.run_bridge(authorize_cycle=lambda: ret)

    def test_lock_failure_prevents_context(self):
        @contextmanager
        def no_lock(_):
            raise RuntimeError('other process')
            yield
        with self.assertRaises(RuntimeError):
            self.run_bridge(global_lock=no_lock)
        self.assertEqual(self.events, ['authorize'])

    def test_verifier_failure_stops_before_probe(self):
        def fail(_):
            raise RuntimeError('invalid source')
        with self.assertRaises(RuntimeError):
            self.run_bridge(verify_context=fail)
        self.assertEqual(self.events.count('record'), 0)
        self.assertIn('global-exit', self.events)

    def test_bad_history_path_before_loop(self):
        with self.assertRaises(bridge.RuntimeBridgeRefused):
            self.run_bridge(history_path=lambda: Path('/other/database.sqlite3'))
        self.assertNotIn('loop', self.events)

    def test_recorder_failure_releases_both_locks(self):
        def broken(path, result):
            raise RuntimeError('disk failure')
        with self.assertRaises(RuntimeError):
            self.run_bridge(recorder=broken)
        self.assertEqual(self.events[-2:], ['foreground-exit', 'global-exit'])

    def test_success_exact_two_cycles(self):
        result = self.run_bridge()
        self.assertEqual(result.cycles, 2)
        self.assertEqual(result.persisted_cycles, 2)
        self.assertEqual(self.events.count('record'), 2)
        self.assertEqual(self.events.count('authorize'), 7)
        self.assertEqual(self.events[1:3], ['global-enter', 'foreground-enter'])
        self.assertEqual(self.events[-2:], ['foreground-exit', 'global-exit'])
        self.assertTrue(result.live_mode)
        self.assertFalse(result.notifications_sent)
        self.assertFalse(result.repairs_invoked)
        self.assertFalse(result.tasks_created)

    def test_incomplete_loop_refused(self):
        with self.assertRaises(bridge.RuntimeBridgeRefused):
            self.run_bridge(monitor_loop=lambda *a, **kw: 0)

    def test_real_m2_m3_offline_sqlite_integration(self):
        """Actual M2 safe-result conversion and M3 transaction, no network."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'OnyxCore-v080-Release' / 'Monitoring'
            path = root / 'incident-history.sqlite3'
            cycle_count = 0
            def read_only_fixture(_):
                nonlocal cycle_count
                cycle_count += 1
                wc = 'ReceiverUnreachable' if cycle_count == 1 else 'WindowsPathReady'
                pc = 'PiInternetVerified'
                reason = 'WindowsReceiverUnreachable' if cycle_count == 1 else 'WindowsUsbAndPiInternetVerified'
                return {
                    'source': 'OnyxV080LiveConnectivity', 'status': 'Degraded' if cycle_count == 1 else 'Healthy',
                    'reason': reason, 'windows': {'classification': wc}, 'pi': {'classification': pc},
                    'issues': [], 'checked_at_utc':
                        (datetime.now(timezone.utc) + timedelta(seconds=cycle_count)).isoformat(),
                    'repair_action': 'None', 'incident_history_written': False,
                    'notification_sent': False, 'scheduler_enabled': False,
                }
            # Use real M2 run_monitor and M3 record_cycle, but zero sleep and
            # only a controlled fixture probe. Native OS locks are simulated.
            def fast_m2(config, *, count, interval_seconds, probe, emit):
                return bridge.m2.run_monitor(config, count=count, interval_seconds=interval_seconds,
                                             probe=probe, emit=emit, clock=lambda: 1., sleeper=lambda _: None)
            result = self.run_bridge(history_path=lambda: path, monitor_loop=fast_m2,
                                     probe=read_only_fixture, recorder=m3.record_cycle)
            self.assertEqual(result.persisted_cycles, 2)
            report = m3.history_report(path)
            self.assertEqual(report['recorded_checks'], 2)
            self.assertEqual(report['incident_count'], 1)
            self.assertIsNone(report['open_incident'])
            self.assertEqual([e['event_type'] for e in report['events']], ['Recovered','Opened'])


if __name__ == '__main__':
    unittest.main()
