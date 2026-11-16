"""R6.2B2-A: release SQLite first-use schema is one revocable transaction.

No protected paths, native launch, network diagnostics or real user consent.
These tests DO NOT prove OS worker isolation, late COMMIT cancellation, or
any entitlement to enroll or release v0.8.0.
"""
from __future__ import annotations
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
MON = ROOT / 'windows' / 'monitoring' / 'v080'
if str(MON) not in sys.path:
    sys.path.insert(0, str(MON))
import OnyxLiveIncidentHistory as journal


def sample():
    windows = 'WindowsProbeUnavailable'
    pi = 'PiProbeUnavailable'
    status, reason = journal.m2.m1.classify(
        {'classification': windows}, {'classification': pi})
    return {
        'source': 'OnyxV080ForegroundMonitor',
        'mode': 'OptInForegroundReadOnly',
        'repair_action': 'None', 'incident_history_written': False,
        'notification_sent': False, 'scheduler_enabled': False,
        'status': status, 'reason': reason,
        'windows_classification': windows, 'pi_classification': pi,
        'issues': ['WindowsDiagnosticUnavailable', 'PiDiagnosticUnavailable'],
        'cycle': 1, 'duration_ms': 0,
        'checked_at_utc': datetime.now(timezone.utc).isoformat(),
    }


class SchemaAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'OnyxCore-v080-Release' / 'Monitoring' / 'incident-history.sqlite3'

    def assert_no_durable_schema(self):
        if not self.path.exists():
            return
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 0)
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            self.assertEqual(tables, [])

    def test_deny_before_file_open_creates_no_file(self):
        with self.assertRaisesRegex(journal.HistoryError, 'authorization denied'):
            journal.record_cycle(self.path, sample(), authorize_commit=lambda: False)
        self.assertFalse(self.path.exists())

    def test_deny_before_schema_begin_rolls_back_without_tables(self):
        calls = iter((True, False))
        with self.assertRaisesRegex(journal.HistoryError, 'authorization denied'):
            journal.record_cycle(self.path, sample(), authorize_commit=lambda: next(calls))
        self.assert_no_durable_schema()

    def test_deny_immediately_before_schema_commit_rolls_back_all_ddl(self):
        calls = iter((True, True, False))
        with self.assertRaisesRegex(journal.HistoryError, 'authorization denied'):
            journal.record_cycle(self.path, sample(), authorize_commit=lambda: next(calls))
        self.assert_no_durable_schema()

    def test_first_use_needs_five_checks_and_commits_one_record(self):
        calls = []
        def allow():
            calls.append('consent')
            return True
        journal.record_cycle(self.path, sample(), authorize_commit=allow)
        self.assertEqual(len(calls), 5)  # initial, schema pre/post, tx start/end
        self.assertEqual(journal.history_report(self.path)['recorded_checks'], 1)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 1)

    def test_schema_sql_error_rolls_back_entire_ddl(self):
        # Fail a pinned DDL statement after earlier statements have executed.
        damaged = journal.SCHEMA + '\nCREATE TABLE (BROKEN);\n'
        with patch.object(journal, 'SCHEMA', damaged):
            with self.assertRaises(sqlite3.OperationalError):
                journal.record_cycle(self.path, sample(), authorize_commit=lambda: True)
        self.assert_no_durable_schema()

    def test_existing_initialized_db_skips_schema_checks(self):
        journal.record_cycle(self.path, sample(), authorize_commit=lambda: True)
        calls = []
        journal.record_cycle(self.path, sample(), authorize_commit=lambda: (calls.append(1) or True))
        self.assertEqual(len(calls), 3)
        self.assertEqual(journal.history_report(self.path)['recorded_checks'], 2)

    def test_unversioned_arbitrary_tables_are_not_migrated(self):
        self.path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('CREATE TABLE stranger (id INTEGER)')
        with self.assertRaisesRegex(journal.HistoryError, 'unversioned database refused'):
            journal.record_cycle(self.path, sample(), authorize_commit=lambda: True)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(names, {'stranger'})


if __name__ == '__main__':
    unittest.main()
