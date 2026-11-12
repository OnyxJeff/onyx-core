"""M2 offline focused tests — no Windows, SSH, network or task execution."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import json
import sys
import unittest

MOD = Path(__file__).resolve().parents[3] / 'windows/monitoring/v080'
sys.path.insert(0, str(MOD))
import OnyxContinuousMonitor as m2


def healthy():
    return {
        'source': 'OnyxV080LiveConnectivity',
        'checked_at_utc': '2026-11-12T01:23:26+00:00',
        'status': 'Healthy', 'reason': 'WindowsUsbAndPiInternetVerified',
        'windows': {'classification': 'WindowsPathReady'},
        'pi': {'classification': 'PiInternetVerified'}, 'issues': [],
        'repair_action': 'None', 'incident_history_written': False,
        'scheduler_enabled': False, 'notification_sent': False,
    }


class FakeTime:
    def __init__(self): self.value = 10.0
    def clock(self): return self.value
    def sleep(self, seconds):
        assert seconds >= 0
        self.value += seconds


@contextmanager
def fake_mutex():
    yield


class ContinuousMonitorTests(unittest.TestCase):
    def test_two_cycles_started_120_seconds_apart_without_overlap(self):
        fake = FakeTime()
        seen, starts = [], []
        def probe(_):
            starts.append(fake.clock()); fake.value += 12
            return healthy()
        cycles = m2.run_monitor({}, count=2, interval_seconds=120,
                                probe=probe, clock=fake.clock, sleeper=fake.sleep, emit=seen.append)
        self.assertEqual(cycles, 2)
        self.assertEqual(starts, [10.0, 130.0])
        self.assertEqual([r['duration_ms'] for r in seen], [12000, 12000])
        self.assertEqual([r['cycle'] for r in seen], [1, 2])
        self.assertTrue(all(r['status'] == 'Healthy' for r in seen))

    def test_slow_cycle_does_not_overlap_or_build_backlog(self):
        fake = FakeTime(); starts, seen = [], []
        def probe(_):
            starts.append(fake.clock()); fake.value += 150; return healthy()
        m2.run_monitor({}, count=2, interval_seconds=120, probe=probe,
                       clock=fake.clock, sleeper=fake.sleep, emit=seen.append)
        self.assertEqual(starts, [10.0, 160.0])
        self.assertTrue(all(r['cycle_overran_interval'] for r in seen))

    def test_unknown_is_reported_not_promoted_healthy(self):
        fake = FakeTime(); seen=[]
        data=healthy(); data.update(status='Unknown', reason='DiagnosticEvidenceUnavailable',
                                    windows={'classification':'WindowsProbeUnavailable'},
                                    issues=['WindowsDiagnosticUnavailable'])
        m2.run_monitor({}, count=1, interval_seconds=120, probe=lambda _: data,
                       clock=fake.clock, emit=seen.append)
        self.assertEqual(seen[0]['status'], 'Unknown')
        self.assertEqual(seen[0]['issues'], ['WindowsDiagnosticUnavailable'])

    def test_m1_repairs_or_notifications_refused(self):
        for field, value in [('repair_action','RestartICS'), ('notification_sent',True),
                             ('incident_history_written',True), ('scheduler_enabled',True)]:
            with self.subTest(field=field):
                data=healthy(); data[field]=value
                with self.assertRaises(m2.MonitorError):
                    m2.run_monitor({}, count=1, interval_seconds=120,
                                   probe=lambda _:data)

    def test_claimed_healthy_with_missing_pi_refused(self):
        d=healthy(); d['pi']={'classification':'PiProbeUnavailable'}
        with self.assertRaises(m2.MonitorError):
            m2.run_monitor({},count=1,interval_seconds=120,probe=lambda _:d)

    def test_unexpected_error_labels_refused(self):
        d=healthy(); d['issues']=['secret data']
        with self.assertRaises(m2.MonitorError):
            m2.run_monitor({},count=1,interval_seconds=120,probe=lambda _:d)

    def test_invalid_interval_and_cycle_count_fail_without_probe(self):
        for interval in (0, 60, 89, 3601, '120'):
            with self.subTest(interval=interval):
                with self.assertRaises(m2.MonitorError):
                    m2.run_monitor({},count=1,interval_seconds=interval,
                                   probe=lambda _:self.fail('probe launched'))
        for count in (0, -1, 21, True):
            with self.subTest(count=count):
                with self.assertRaises(m2.MonitorError):
                    m2.run_monitor({},count=count,interval_seconds=120,
                                   probe=lambda _:self.fail('probe launched'))

    def test_inert_cli_validation_never_acquires_mutex_or_probes(self):
        with patch.object(m2.m1, 'verify_local_context',side_effect=AssertionError('NO')):
            with patch.object(m2, 'exclusive_monitor',side_effect=AssertionError('NO')):
                self.assertEqual(m2.main(['--check-config']), 0)

    def test_live_without_explicit_count_or_continuous_is_refused(self):
        with self.assertRaises(SystemExit) as ctx:
            m2.main(['--live-read-only'])
        self.assertEqual(ctx.exception.code, 2)

    def test_no_implicit_run(self):
        with self.assertRaises(SystemExit) as ctx:
            m2.main([])
        self.assertEqual(ctx.exception.code, 2)

    def test_duplicate_monitor_refused_before_probe(self):
        with patch.object(m2.m1,'verify_local_context'):
            with patch.object(m2,'exclusive_monitor',side_effect=m2.MonitorError('already running')):
                with patch.object(m2,'run_monitor',side_effect=AssertionError('NO PROBE')):
                    self.assertEqual(m2.main(['--live-read-only','--count','1']),2)

    def test_bounded_cli_uses_existing_m1_probe_and_json(self):
        outputs=[]
        with patch.object(m2.m1,'verify_local_context'):
            with patch.object(m2,'exclusive_monitor',fake_mutex):
                with patch.object(m2.m1,'run_once',return_value=healthy()):
                    with patch('builtins.print', side_effect=lambda *a,**kw: outputs.append(a[0])):
                        self.assertEqual(m2.main(['--live-read-only','--count','1','--jsonl']),0)
        self.assertEqual(json.loads(outputs[0])['source'],'OnyxV080ForegroundMonitor')
        self.assertEqual(json.loads(outputs[0])['windows_classification'],'WindowsPathReady')

    def test_keyboard_interrupt_is_normal_stop_and_releases_mutex(self):
        entered=[]
        @contextmanager
        def mutex():
            entered.append('start')
            try: yield
            finally: entered.append('end')
        with patch.object(m2.m1,'verify_local_context'):
            with patch.object(m2,'exclusive_monitor',mutex):
                with patch.object(m2,'run_monitor',side_effect=KeyboardInterrupt):
                    self.assertEqual(m2.main(['--live-read-only','--continuous']),0)
        self.assertEqual(entered,['start','end'])

    def test_sanitized_json_does_not_contain_raw_network_or_ssh_output(self):
        fake=FakeTime(); seen=[]
        m2.run_monitor({},count=1,interval_seconds=120,
                       probe=lambda _:healthy(),clock=fake.clock,emit=seen.append)
        self.assertNotIn('ssh',json.dumps(seen[0]).lower())
        self.assertNotIn('token',json.dumps(seen[0]).lower())
        self.assertFalse(seen[0]['notification_sent'])


if __name__=='__main__': unittest.main()
