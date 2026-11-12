"""M3 incident history tests: tempfile SQLite and fake M2 probes, no live network."""
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import sqlite3
import sys
import unittest

MOD = Path(__file__).resolve().parents[3] / 'windows/monitoring/v080'
sys.path.insert(0, str(MOD))
import OnyxLiveIncidentHistory as m3


def sample(status='Healthy', *, timestamp='2026-11-12T01:23:26+00:00',
           windows='WindowsPathReady', pi='PiInternetVerified', cycle=1):
    result_status, reason = m3.m2.m1.classify(
        {'classification': windows}, {'classification': pi})
    if status != result_status:
        raise AssertionError('sample status and classifications differ')
    issues = []
    if windows == 'WindowsProbeUnavailable':
        issues.append('WindowsDiagnosticUnavailable')
    if pi == 'PiProbeUnavailable':
        issues.append('PiDiagnosticUnavailable')
    return {
        'source': 'OnyxV080ForegroundMonitor', 'mode': 'OptInForegroundReadOnly',
        'checked_at_utc': timestamp, 'cycle': cycle, 'duration_ms': 8200,
        'status': status, 'reason': reason, 'windows_classification': windows,
        'pi_classification': pi, 'issues': issues,
        'incident_history_written': False, 'repair_action': 'None',
        'notification_sent': False, 'scheduler_enabled': False,
    }


@contextmanager
def fake_mutex():
    yield


class IncidentHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / 'incident-history.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def history(self):
        return m3.history_report(self.path)

    def test_uninitialized_history_is_read_only_and_does_not_create_file(self):
        report = self.history()
        self.assertEqual(report['recorded_checks'], 0)
        self.assertEqual(report['incident_count'], 0)
        self.assertFalse(self.path.exists())

    def test_healthy_cycles_do_not_create_an_incident(self):
        self.assertEqual(m3.record_cycle(self.path, sample())['event'], 'NoIncident')
        second = sample(timestamp='2026-11-12T01:25:26+00:00', cycle=2)
        self.assertEqual(m3.record_cycle(self.path, second)['event'], 'NoIncident')
        report = self.history()
        self.assertEqual(report['recorded_checks'], 2)
        self.assertEqual(report['incident_count'], 0)
        self.assertEqual(report['events'], [])

    def test_degraded_opens_once_then_deduplicates(self):
        failure = sample('Degraded', windows='AdapterDown')
        first = m3.record_cycle(self.path, failure)
        failure['checked_at_utc'] = '2026-11-12T01:25:26+00:00'
        second = m3.record_cycle(self.path, failure)
        self.assertEqual(first['event'], 'Opened')
        self.assertEqual(second['event'], 'Ongoing')
        self.assertEqual(first['incident_id'], second['incident_id'])
        report = self.history()
        self.assertEqual(report['incident_count'], 1)
        self.assertEqual(report['open_incident']['check_count'], 2)
        self.assertEqual([e['event_type'] for e in report['events']], ['Opened'])

    def test_unknown_does_not_mark_degraded_as_recovered(self):
        m3.record_cycle(self.path, sample('Degraded', windows='AdapterDown'))
        unknown = sample('Unknown', timestamp='2026-11-12T01:25:26+00:00',
                         windows='WindowsProbeUnavailable', pi='PiProbeUnavailable')
        result = m3.record_cycle(self.path, unknown)
        self.assertEqual(result['event'], 'Changed')
        report = self.history()
        self.assertEqual(report['incident_count'], 1)
        self.assertEqual(report['open_incident']['last_status'], 'Unknown')
        self.assertIsNone(report['open_incident']['resolved_at_utc'])
        self.assertEqual([e['event_type'] for e in report['events']], ['Changed', 'Opened'])

    def test_first_verified_healthy_closes_incident(self):
        m3.record_cycle(self.path, sample('Unknown', windows='WindowsProbeUnavailable',
                                          pi='PiProbeUnavailable'))
        recovery = sample(timestamp='2026-11-12T01:25:26+00:00')
        result = m3.record_cycle(self.path, recovery)
        self.assertEqual(result['event'], 'Recovered')
        report = self.history()
        self.assertIsNone(report['open_incident'])
        self.assertEqual(report['incidents'][0]['resolved_at_utc'], recovery['checked_at_utc'])
        self.assertEqual([e['event_type'] for e in report['events']], ['Recovered', 'Opened'])
        self.assertEqual(report['recorded_checks'], 2)

    def test_after_recovery_new_failure_is_new_incident(self):
        m3.record_cycle(self.path, sample('Degraded', windows='AdapterDown'))
        m3.record_cycle(self.path, sample(timestamp='2026-11-12T01:25:26+00:00'))
        result = m3.record_cycle(self.path, sample('Degraded',
            timestamp='2026-11-12T01:27:26+00:00', pi='DnsUnverified'))
        self.assertEqual(result['event'], 'Opened')
        self.assertEqual(result['incident_id'], 2)
        self.assertEqual(self.history()['incident_count'], 2)

    def test_persists_across_independent_connections(self):
        m3.record_cycle(self.path, sample('Degraded', windows='AdapterDown'))
        # Each call opens a new connection (simulates stopping/restarting M3).
        snap = self.history()
        self.assertEqual(snap['open_incident']['id'], 1)
        m3.record_cycle(self.path, sample(timestamp='2026-11-12T01:25:26+00:00'))
        self.assertIsNone(self.history()['open_incident'])

    def test_changed_diagnostic_cause_is_one_incident_and_a_change_event(self):
        m3.record_cycle(self.path, sample('Degraded', windows='AdapterDown'))
        m3.record_cycle(self.path, sample('Degraded',
            timestamp='2026-11-12T01:25:26+00:00', pi='DnsUnverified'))
        report = self.history()
        self.assertEqual(report['incident_count'], 1)
        self.assertEqual([e['event_type'] for e in report['events']], ['Changed', 'Opened'])

    def test_repair_or_notification_forgery_is_rejected_without_disk_write(self):
        for field, value in [('repair_action', 'RestartICS'),
                             ('notification_sent', True),
                             ('incident_history_written', True),
                             ('scheduler_enabled', True)]:
            with self.subTest(field=field):
                result = sample()
                result[field] = value
                with self.assertRaises(m3.HistoryError):
                    m3.record_cycle(self.path, result)
                self.assertFalse(self.path.exists())

    def test_contradictory_status_or_reason_rejected(self):
        result = sample()
        result['reason'] = 'WindowsAdapterDown'
        with self.assertRaises(m3.HistoryError):
            m3.record_cycle(self.path, result)
        self.assertFalse(self.path.exists())

    def test_missing_evidence_contradiction_rejected(self):
        result = sample('Unknown', windows='WindowsProbeUnavailable', pi='PiProbeUnavailable')
        result['issues'] = []
        with self.assertRaises(m3.HistoryError):
            m3.record_cycle(self.path, result)
        self.assertFalse(self.path.exists())

    def test_malformed_timestamp_rejected(self):
        result = sample(timestamp='2026-11-12T01:23:26')
        with self.assertRaises(m3.HistoryError):
            m3.record_cycle(self.path, result)
        self.assertFalse(self.path.exists())

    def test_rejects_unsupported_existing_database_without_overwrite(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('CREATE TABLE unrelated (id INTEGER)')
            conn.execute('INSERT INTO unrelated VALUES (99)')
        with self.assertRaises(m3.HistoryError):
            m3.record_cycle(self.path, sample())
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.assertEqual(conn.execute('SELECT id FROM unrelated').fetchone()[0], 99)

    def test_history_json_contains_only_classifications_and_no_raw_output(self):
        m3.record_cycle(self.path, sample('Degraded', windows='AdapterDown'))
        text = json.dumps(self.history())
        self.assertNotIn('ssh_executable', text)
        self.assertNotIn('token', text.lower())
        self.assertIn('AdapterDown', text)

    def test_live_cli_requires_explicit_number_of_checks(self):
        with self.assertRaises(SystemExit) as ctx:
            m3.main(['--record-live'])
        self.assertEqual(ctx.exception.code, 2)
        with self.assertRaises(SystemExit) as ctx:
            m3.main([])
        self.assertEqual(ctx.exception.code, 2)

    def test_check_config_is_inert(self):
        with patch.object(m3, 'history_path', side_effect=AssertionError('should not touch disk')):
            with patch.object(m3.m2.m1, 'verify_local_context', side_effect=AssertionError('no live probes')):
                self.assertEqual(m3.main(['--check-config']), 0)

    def test_cli_reads_history_without_probe_or_write(self):
        with patch.object(m3, 'history_path', return_value=self.path):
            with patch.object(m3.m2, 'run_monitor', side_effect=AssertionError('no probe')):
                self.assertEqual(m3.main(['--history']), 0)
                self.assertFalse(self.path.exists())

    def test_live_cli_reuses_m2_loop_mutex_and_persists_one_cycle(self):
        output = []
        with patch.object(m3, 'history_path', return_value=self.path):
            with patch.object(m3.m2.m1, 'verify_local_context'):
                with patch.object(m3.m2, 'exclusive_monitor', fake_mutex):
                    with patch.object(m3.m2, 'run_monitor',
                                      side_effect=lambda config, count, interval_seconds, emit:
                                      emit(sample())) as mock_monitor:
                        with patch('builtins.print', side_effect=lambda *args, **kwargs: output.append(args[0])):
                            self.assertEqual(m3.main(['--record-live', '--count', '1', '--json']), 0)
        self.assertEqual(mock_monitor.call_args.kwargs['count'], 1)
        self.assertEqual(self.history()['recorded_checks'], 1)
        self.assertEqual(json.loads(output[0])['incident']['event'], 'NoIncident')

    def test_history_read_does_not_mutate_database(self):
        m3.record_cycle(self.path, sample())
        before = self.path.read_bytes()
        self.assertEqual(self.history()['recorded_checks'], 1)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
