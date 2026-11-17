"""R6.2B1 offline contract tests: M3 pre-COMMIT fresh authorization.

No live probes, Windows process launching, or protected-state access.
These tests do NOT prove hard process containment or exact-time disk durability.
"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
MON = ROOT / 'windows' / 'monitoring' / 'v080'
if str(MON) not in sys.path:
    sys.path.insert(0, str(MON))

import OnyxLiveIncidentHistory as m3
import OnyxGuardedRuntimeBridge as bridge

SID = 'S-1-5-21-123-456-789-1001'


def valid_sample():
    windows = 'WindowsProbeUnavailable'
    pi = 'PiProbeUnavailable'
    status, reason = m3.m2.m1.classify(
        {'classification': windows}, {'classification': pi})
    return {
        'source': 'OnyxV080ForegroundMonitor',
        'mode': 'OptInForegroundReadOnly',
        'repair_action': 'None', 'incident_history_written': False,
        'notification_sent': False, 'scheduler_enabled': False,
        'status': status, 'reason': reason,
        'windows_classification': windows,
        'pi_classification': pi,
        'issues': ['WindowsDiagnosticUnavailable', 'PiDiagnosticUnavailable'],
        'cycle': 1, 'duration_ms': 0,
        'checked_at_utc': datetime.now(timezone.utc).isoformat(),
    }


class TransactionAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = (Path(self.tmp.name) / 'OnyxCore-v080-Release' /
                     'Monitoring' / 'incident-history.sqlite3')

    def count(self):
        return m3.history_report(self.path)['recorded_checks']

    def prepare_empty_history_fixture(self):
        # These R6.2B1 tests exercise the *incident* transaction on an
        # initialized, empty database. First-use schema authorization has
        # separate R6.2B2 tests and must not consume their callback budget.
        conn = m3._connect(self.path, write=True)
        conn.close()

    def test_permission_denied_before_storage_is_created(self):
        with self.assertRaisesRegex(m3.HistoryError, 'authorization denied'):
            m3.record_cycle(self.path, valid_sample(), authorize_commit=lambda: False)
        self.assertFalse(self.path.exists())

    def test_revoked_before_begin_keeps_zero_checks(self):
        self.prepare_empty_history_fixture()
        calls = iter((True, False))
        with self.assertRaisesRegex(m3.HistoryError, 'authorization denied'):
            m3.record_cycle(self.path, valid_sample(), authorize_commit=lambda: next(calls))
        self.assertEqual(self.count(), 0)

    def test_revoked_immediately_before_commit_rolls_back_every_row(self):
        self.prepare_empty_history_fixture()
        calls = iter((True, True, False))
        with self.assertRaisesRegex(m3.HistoryError, 'authorization denied'):
            m3.record_cycle(self.path, valid_sample(), authorize_commit=lambda: next(calls))
        self.assertEqual(self.count(), 0)
        self.assertEqual(m3.history_report(self.path)['incident_count'], 0)

    def test_allowed_transaction_commits_once(self):
        self.prepare_empty_history_fixture()
        calls = []
        def allow():
            calls.append(True)
            return True
        out = m3.record_cycle(self.path, valid_sample(), authorize_commit=allow)
        self.assertEqual(out['event'], 'Opened')
        self.assertEqual(self.count(), 1)
        self.assertEqual(len(calls), 3)

    def test_nonbool_consent_refused_with_no_storage(self):
        with self.assertRaises(m3.HistoryError):
            m3.record_cycle(self.path, valid_sample(), authorize_commit=lambda: 1)
        self.assertFalse(self.path.exists())

    def test_invalid_callback_refused_with_no_storage(self):
        with self.assertRaises(m3.HistoryError):
            m3.record_cycle(self.path, valid_sample(), authorize_commit='yes')
        self.assertFalse(self.path.exists())

    def test_existing_legacy_writer_still_functions_offline(self):
        m3.record_cycle(self.path, valid_sample())
        self.assertEqual(self.count(), 1)

    def test_bridge_transactional_writer_is_authorized_inside_record(self):
        checks = []
        def allow():
            checks.append('authorization')
            return True
        def once(c, *, count, interval_seconds, probe, emit):
            emit(probe(c))
            return 1
        with patch.object(bridge.native, 'validate_sid', return_value=SID):
            result = bridge.run_authorized_cycles(
                bridge.BoundedRuntimePolicy(1), approved_sid=SID,
                authorize_cycle=allow, storage_profile=lambda: 'release',
                history_path=lambda: self.path, load_config=lambda: {},
                verify_context=lambda c: None,
                global_lock=lambda sid: nullcontext(),
                foreground_lock=lambda: nullcontext(), monitor_loop=once,
                probe=lambda c: valid_sample(),
                recorder=lambda *_: self.fail('fallback recorder reached'),
                transactional_recorder=m3.record_cycle)
        self.assertEqual(result.persisted_cycles, 1)
        self.assertEqual(self.count(), 1)
        self.assertGreaterEqual(len(checks), 7)

    def test_bridge_revokes_during_transaction_without_commit(self):
        self.prepare_empty_history_fixture()
        commit_checks = []
        def transactional(path, value, *, authorize_commit):
            def gate():
                commit_checks.append('check')
                # Explicitly revoke during a transaction, immediately before COMMIT.
                if len(commit_checks) == 3:
                    return False
                return authorize_commit()
            return m3.record_cycle(path, value, authorize_commit=gate)
        def once(c, *, count, interval_seconds, probe, emit):
            emit(probe(c))
            return 1
        with patch.object(bridge.native, 'validate_sid', return_value=SID):
            with self.assertRaisesRegex(m3.HistoryError, 'authorization denied'):
                bridge.run_authorized_cycles(
                    bridge.BoundedRuntimePolicy(1), approved_sid=SID,
                    authorize_cycle=lambda: True, storage_profile=lambda: 'release',
                    history_path=lambda: self.path, load_config=lambda: {},
                    verify_context=lambda c: None,
                    global_lock=lambda sid: nullcontext(),
                    foreground_lock=lambda: nullcontext(), monitor_loop=once,
                    probe=lambda c: valid_sample(),
                    transactional_recorder=transactional)
        self.assertEqual(len(commit_checks), 3)
        self.assertEqual(self.count(), 0)


if __name__ == '__main__':
    unittest.main()
