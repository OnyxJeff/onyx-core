"""Offline-only verified multi-sample incident confirmation for v0.8.0."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'windows' / 'monitoring' / 'v080'))
sys.path.insert(0, str(ROOT / 'windows' / 'monitoring'))
import OnyxLiveConnectivity as m1
import OnyxLiveIncidentHistory as m3

BASE = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def observed(status: str, seconds: int, cycle: int = 1) -> dict:
    if status == 'H': w, p = 'WindowsPathReady', 'PiInternetVerified'
    elif status == 'D': w, p = 'AdapterDown', 'PiInternetVerified'
    else: w, p = 'WindowsProbeUnavailable', 'PiInternetVerified'
    health, reason = m1.classify({'classification': w}, {'classification': p})
    return {'schema_version': 1, 'source': 'OnyxV080ForegroundMonitor',
            'mode': 'OptInForegroundReadOnly', 'cycle': cycle,
            'checked_at_utc': (BASE + timedelta(seconds=seconds)).isoformat(),
            'status': health, 'reason': reason, 'windows_classification': w,
            'pi_classification': p,
            'issues': ['WindowsDiagnosticUnavailable'] if status == 'U' else [],
            'duration_ms': 50, 'interval_seconds': 120,
            'cycle_overran_interval': False, 'repair_action': 'None',
            'incident_history_written': False, 'scheduler_enabled': False,
            'notification_sent': False}


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'OnyxCore-v080-Development' / 'Monitoring' / 'incident-history.sqlite3'

    def r(self, sequence):
        return [m3.record_cycle(self.path, observed(status, sec, i + 1),
                                confirmed_incidents=True)
                for i, (status, sec) in enumerate(sequence)]

    def test_three_failures_then_two_recoveries(self):
        events = self.r([('H', 0), ('D', 120), ('U', 240), ('D', 360),
                         ('H', 480), ('H', 600)])
        self.assertEqual([x['event'] for x in events],
                         ['NoIncident', 'NoIncident', 'NoIncident', 'Opened', 'Ongoing', 'Recovered'])
        report = m3.history_report(self.path)
        self.assertEqual(report['incident_count'], 1)
        self.assertIsNone(report['open_incident'])
        self.assertEqual([x['event_type'] for x in report['events']], ['Recovered', 'Opened'])
        self.assertEqual(report['incidents'][0]['started_at_utc'], (BASE + timedelta(seconds=120)).isoformat())

    def test_transient_failure_does_not_alert(self):
        events = self.r([('H', 0), ('D', 120), ('H', 240), ('H', 360)])
        self.assertEqual([x['event'] for x in events], ['NoIncident'] * 4)

    def test_three_not_within_five_minutes(self):
        events = self.r([('D', 0), ('D', 250), ('D', 370)])
        self.assertEqual(events[-1]['event'], 'NoIncident')

    def test_strict_consecutive_required(self):
        events = self.r([('D', 0), ('H', 100), ('D', 200), ('D', 300)])
        self.assertEqual(events[-1]['event'], 'NoIncident')

    def test_recovery_resets_on_another_bad_check(self):
        events = self.r([('D', 0), ('D', 100), ('D', 200), ('H', 300),
                         ('D', 400), ('H', 500), ('H', 600)])
        self.assertEqual([e['event'] for e in events if e['event'] in ('Opened', 'Recovered')],
                         ['Opened', 'Recovered'])

    def test_unknown_counts_as_unhealthy(self):
        events = self.r([('U', 0), ('U', 120), ('U', 240)])
        self.assertEqual(events[-1]['event'], 'Opened')

    def test_duplicate_timestamp_never_counts_twice(self):
        events = self.r([('D', 0), ('D', 120), ('D', 120)])
        self.assertEqual(events[-1]['event'], 'NoIncident')

    def test_default_behavior_preserved(self):
        e = m3.record_cycle(self.path, observed('D', 0))
        self.assertEqual(e['event'], 'Opened')
        e = m3.record_cycle(self.path, observed('H', 120))
        self.assertEqual(e['event'], 'Recovered')

    def test_receipt_idempotency_preserved(self):
        result = observed('D', 0)
        key = m3.cycle_operation_id(result)
        e = m3.record_cycle(self.path, result, operation_id=key, confirmed_incidents=True)
        again = m3.record_cycle(self.path, result, operation_id=key, confirmed_incidents=True)
        self.assertEqual(e, again)
        self.assertEqual(m3.history_report(self.path)['recorded_checks'], 1)


if __name__ == '__main__': unittest.main()
