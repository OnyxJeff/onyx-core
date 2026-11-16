"""R6.2B2E offline: same-transaction receipts and fail-closed ambiguity.

All files are in disposable temporary directories; no Windows native or live probe.
"""
from __future__ import annotations

from contextlib import nullcontext, closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import threading
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[3]
MON = ROOT / 'windows' / 'monitoring' / 'v080'
if str(MON) not in sys.path:
    sys.path.insert(0, str(MON))

import OnyxLiveIncidentHistory as m3
import OnyxGuardedRuntimeBridge as bridge
import OnyxV080ReleaseBinding as binding

SID = 'S-1-5-21-123-456-789-1001'


def sample():
    from test_r62b1_transaction_gate import valid_sample
    return valid_sample()


class CommitReceiptTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'OnyxCore-v080-Release' / 'Monitoring' / 'incident-history.sqlite3'
        self.data = sample()
        self.op = str(uuid.uuid4())

    def count(self):
        return m3.history_report(self.path)['recorded_checks']

    def old_v1(self):
        conn = m3._connect(self.path, write=True)
        conn.close()

    def test_new_store_receipt_and_schema_version(self):
        result = m3.record_cycle(self.path, self.data, operation_id=self.op,
                                 authorize_commit=lambda: True)
        self.assertEqual(result['event'], 'Opened')
        self.assertEqual(self.count(), 1)
        self.assertEqual(m3.reconcile_cycle(self.path, self.op, self.data), result)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 1)

    def test_replay_same_key_is_idempotent(self):
        original = m3.record_cycle(self.path, self.data, operation_id=self.op)
        replay = m3.record_cycle(self.path, self.data, operation_id=self.op)
        self.assertEqual(replay, original)
        self.assertEqual(self.count(), 1)
        self.assertEqual(m3.history_report(self.path)['incident_count'], 1)

    def test_replay_same_key_mismatched_observation_refused(self):
        m3.record_cycle(self.path, self.data, operation_id=self.op)
        different = {**self.data, 'duration_ms': self.data['duration_ms'] + 1}
        with self.assertRaisesRegex(m3.HistoryError, 'different observation'):
            m3.record_cycle(self.path, different, operation_id=self.op)
        self.assertEqual(self.count(), 1)

    def test_unknown_receipt_is_read_only(self):
        self.assertIsNone(m3.reconcile_cycle(self.path, self.op))
        self.assertFalse(self.path.exists())

    def test_legacy_v1_schema_upgraded_inside_transaction_only(self):
        self.old_v1()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            table = conn.execute("SELECT count(*) FROM sqlite_master WHERE name='cycle_receipts'").fetchone()[0]
        self.assertEqual(table, 0)
        m3.record_cycle(self.path, self.data, operation_id=self.op,
                        authorize_commit=lambda: True)
        self.assertIsNotNone(m3.reconcile_cycle(self.path, self.op))

    def test_revocation_rolls_back_new_receipt_table_for_v1(self):
        self.old_v1()
        calls = iter((True, True, False))
        with self.assertRaisesRegex(m3.HistoryError, 'authorization denied'):
            m3.record_cycle(self.path, self.data, operation_id=self.op,
                            authorize_commit=lambda: next(calls))
        self.assertEqual(self.count(), 0)
        self.assertIsNone(m3.reconcile_cycle(self.path, self.op))
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM sqlite_master WHERE name='cycle_receipts'").fetchone()[0], 0)

    def test_invalid_operation_ids_rejected_before_storage(self):
        for key in ('bad', str(uuid.uuid1()), str(uuid.uuid4()).upper(), None, 123, False):
            if key is None:
                continue  # None is intentionally allowed for old callers.
            with self.subTest(key=key):
                with self.assertRaises(m3.HistoryError):
                    m3.record_cycle(self.path, self.data, operation_id=key)
        self.assertFalse(self.path.exists())

    def test_read_only_reconciliation_rejects_other_sample(self):
        m3.record_cycle(self.path, self.data, operation_id=self.op)
        other = {**self.data, 'duration_ms': 44}
        with self.assertRaisesRegex(m3.HistoryError, 'different observation'):
            m3.reconcile_cycle(self.path, self.op, other)
        self.assertEqual(self.count(), 1)

    def _simulate_uncertain_commit(self, after_commit):
        self.old_v1()
        original = sqlite3.connect
        armed = {'value': True}
        class Proxy:
            def __init__(self, connection): self._c = connection
            def __setattr__(self, attr, value):
                if attr == '_c': object.__setattr__(self, attr, value)
                else: setattr(self._c, attr, value)
            def __getattr__(self, attr): return getattr(self._c, attr)
            def commit(self):
                if armed['value']:
                    armed['value'] = False
                    if after_commit: self._c.commit()
                    raise sqlite3.OperationalError('synthetic commit acknowledgment lost')
                return self._c.commit()
        def connect(*args, **kw):
            conn = original(*args, **kw)
            if not kw.get('uri'):
                return Proxy(conn)
            return conn
        with patch.object(m3.sqlite3, 'connect', side_effect=connect):
            if after_commit:
                out = m3.record_cycle(self.path, self.data, operation_id=self.op)
                self.assertEqual(out['event'], 'Opened')
            else:
                with self.assertRaisesRegex(m3.CommitOutcomeUnknown, 'receipt absent'):
                    m3.record_cycle(self.path, self.data, operation_id=self.op)
        return armed

    def test_commit_durable_but_exception_reconciles_without_duplicate(self):
        self._simulate_uncertain_commit(True)
        self.assertEqual(self.count(), 1)
        self.assertEqual(m3.record_cycle(self.path, self.data, operation_id=self.op)['event'], 'Opened')
        self.assertEqual(self.count(), 1)

    def test_commit_not_durable_exception_refuses_replay(self):
        self._simulate_uncertain_commit(False)
        self.assertEqual(self.count(), 0)
        self.assertIsNone(m3.reconcile_cycle(self.path, self.op))

    def test_legacy_writer_keeps_compatibility(self):
        self.old_v1()
        self.assertEqual(m3.record_cycle(self.path, self.data)['event'], 'Opened')
        self.assertEqual(self.count(), 1)
        self.assertIsNone(m3.reconcile_cycle(self.path, self.op))

    def test_bridge_requires_transactional_writer_if_receipts_enabled(self):
        with self.assertRaisesRegex(bridge.RuntimeBridgeRefused, 'cycle receipts require'):
            bridge.run_authorized_cycles(bridge.BoundedRuntimePolicy(1),
                                         approved_sid=SID, authorize_cycle=lambda: True,
                                         use_cycle_receipts=True)

    def test_bridge_produces_parent_receipt(self):
        def once(c, *, count, interval_seconds, probe, emit):
            emit(probe(c))
            return 1
        with patch.object(bridge.native, 'validate_sid', return_value=SID):
            out = bridge.run_authorized_cycles(
                bridge.BoundedRuntimePolicy(1), approved_sid=SID,
                authorize_cycle=lambda: True, storage_profile=lambda: 'release',
                history_path=lambda: self.path, load_config=lambda: {},
                verify_context=lambda c: None, global_lock=lambda sid: nullcontext(),
                foreground_lock=lambda: nullcontext(), monitor_loop=once,
                probe=lambda c: self.data,
                transactional_recorder=m3.record_cycle, use_cycle_receipts=True)
        self.assertEqual(out.persisted_cycles, 1)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            key = conn.execute('SELECT operation_id FROM cycle_receipts').fetchone()[0]
        self.assertEqual(str(uuid.UUID(key)), key)
        self.assertEqual(self.count(), 1)

    def test_stable_parent_key_for_identical_observation(self):
        first = m3.cycle_operation_id(self.data)
        replay = m3.cycle_operation_id({**self.data})
        changed = m3.cycle_operation_id({**self.data, 'duration_ms': 99})
        self.assertEqual(first, replay)
        self.assertNotEqual(first, changed)
        self.assertEqual(uuid.UUID(first).version, 5)

    def test_bridge_replay_same_observation_across_sessions(self):
        def once(c, *, count, interval_seconds, probe, emit):
            emit(probe(c))
            return 1
        def run():
            with patch.object(bridge.native, 'validate_sid', return_value=SID):
                return bridge.run_authorized_cycles(
                    bridge.BoundedRuntimePolicy(1), approved_sid=SID,
                    authorize_cycle=lambda: True, storage_profile=lambda: 'release',
                    history_path=lambda: self.path, load_config=lambda: {},
                    verify_context=lambda c: None, global_lock=lambda sid: nullcontext(),
                    foreground_lock=lambda: nullcontext(), monitor_loop=once,
                    probe=lambda c: self.data,
                    transactional_recorder=m3.record_cycle, use_cycle_receipts=True)
        self.assertEqual(run().persisted_cycles, 1)
        self.assertEqual(run().persisted_cycles, 1)
        self.assertEqual(self.count(), 1)

    def test_concurrent_same_key_creates_one_observation(self):
        # BEGIN IMMEDIATE serializes the check/insert; the second writer must
        # see the committed receipt rather than insert another incident event.
        barrier = threading.Barrier(2)
        results = []
        errors = []
        def run():
            try:
                barrier.wait(timeout=3)
                results.append(m3.record_cycle(self.path, self.data,
                    operation_id=self.op, authorize_commit=lambda: True))
            except BaseException as exc:
                errors.append(exc)
        a = threading.Thread(target=run)
        b = threading.Thread(target=run)
        a.start(); b.start()
        a.join(timeout=8); b.join(timeout=8)
        self.assertFalse(a.is_alive() or b.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.count(), 1)

    def test_replay_denied_if_authorization_revoked(self):
        m3.record_cycle(self.path, self.data, operation_id=self.op)
        with self.assertRaisesRegex(m3.HistoryError, 'authorization denied'):
            m3.record_cycle(self.path, self.data, operation_id=self.op,
                            authorize_commit=lambda: False)
        self.assertEqual(self.count(), 1)


if __name__ == '__main__':
    unittest.main()
