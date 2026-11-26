#!/usr/bin/env python3
"""M1-S10: offline Windows->Pi contract, HTTP acceptance, safe SQLite bootstrap.

No network sockets, production databases, secrets, services, or host mutations.
All database changes happen exclusively in TemporaryDirectory fixtures.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from email.message import Message
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
RECEIVER_DIR = ROOT / 'pi/services/receiver'
COMMON_DIR = ROOT / 'tools/installation/common'
for directory in (RECEIVER_DIR, COMMON_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import receiver_v100 as receiver
from integrated_store_v100 import IntegratedStore
from onyx_v100_config import load_config, validate_pair, ConfigRefused

WINDOWS = ROOT / 'docs/v1.0.0/examples/windows.config.example.json'
PI = ROOT / 'docs/v1.0.0/examples/pi-armv6.config.example.json'


def sample(source, session=None, second_offset=0):
    stamp = datetime.now(timezone.utc) + timedelta(seconds=second_offset)
    return {
        'schema_version': 1,
        'source': source,
        'session_id': session or str(uuid.uuid4()),
        'sequence': 1,
        'timestamp_utc': stamp.isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'metrics': {'cpu_percent': 13, 'memory_used_percent': 41.8,
                    'uptime_seconds': 23480, 'gpu_percent': 0, 'gpu_temp_c': 42},
    }


def validator(source):
    return lambda value: receiver.validate(value, check_freshness=False, expected_source=source)


class CaptureStore:
    def __init__(self):
        self.accepted = []

    def accept(self, value):
        self.accepted.append(value)
        return True


def dispatch_payload(body, expected_source, store):
    raw = json.dumps(body, separators=(',', ':')).encode('utf-8')
    Handler = receiver.handler_factory('T'*40, store, expected_source=expected_source)
    request = Handler.__new__(Handler)
    request.path = '/api/v1/telemetry'
    request.headers = Message()
    request.headers.add_header('Authorization', 'Bearer ' + 'T'*40)
    request.headers.add_header('Content-Type', 'application/json')
    request.headers.add_header('Content-Length', str(len(raw)))
    request.rfile = io.BytesIO(raw)
    response = []
    request.respond = lambda status, obj: response.append((status, obj))
    request.do_POST()
    return response[0]


class CrossComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.windows = load_config(WINDOWS, 'windows')
        cls.pi = load_config(PI, 'pi-armv6')

    def test_source_and_port_match(self):
        self.assertTrue(validate_pair(self.windows, self.pi))
        self.assertEqual(self.windows['collector']['source'], self.pi['receiver']['source'])

    def test_mismatched_source_config_refused_even_if_both_individually_valid(self):
        other = copy.deepcopy(self.pi)
        other['receiver']['source'] = 'AnotherPC'
        with self.assertRaises(ConfigRefused):
            validate_pair(self.windows, other)

    def test_windows_sample_reaches_pi_receiver_validator(self):
        payload = sample(self.windows['collector']['source'])
        self.assertIs(receiver.validate(payload, expected_source=self.pi['receiver']['source']), payload)

    def test_unexpected_source_refused(self):
        payload = sample('WrongPC')
        with self.assertRaisesRegex(ValueError, 'unsupported source'):
            receiver.validate(payload, expected_source=self.pi['receiver']['source'])

    def test_validate_has_no_implicit_legacy_squall_default(self):
        with self.assertRaises(TypeError):
            receiver.validate(sample('SQUALL'))
        with self.assertRaises(ValueError):
            receiver.validate(sample('SQUALL'), expected_source='bad value')

    def test_http_handler_accepts_configured_source_no_socket(self):
        store = CaptureStore()
        payload = sample(self.windows['collector']['source'])
        status, response = dispatch_payload(payload, self.pi['receiver']['source'], store)
        self.assertEqual((status, response['sequence']), (202, 1))
        self.assertEqual(len(store.accepted), 1)
        self.assertEqual(store.accepted[0]['source'], 'MyWindowsPC')

    def test_http_handler_rejects_wrong_source_without_store_write(self):
        store = CaptureStore()
        status, response = dispatch_payload(sample('WrongPC'), self.pi['receiver']['source'], store)
        self.assertEqual((status, response['error']), (422, 'invalid_payload'))
        self.assertEqual(store.accepted, [])

    def test_snapshot_store_enforces_configured_source(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot = Path(folder)/'latest.json'
            snapshot.write_text(json.dumps(sample('SQUALL')), encoding='utf-8')
            before = snapshot.read_bytes()
            with self.assertRaisesRegex(ValueError, 'unsupported source'):
                receiver.SnapshotStore(snapshot, expected_source='MyWindowsPC')
            self.assertEqual(snapshot.read_bytes(), before)

    def test_sqlite_bootstrap_rejects_mismatch_before_database_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder)/'history.db'
            snapshot = Path(folder)/'latest.json'
            snapshot.write_text(json.dumps(sample('SQUALL')), encoding='utf-8')
            old = snapshot.read_bytes()
            with self.assertRaisesRegex(ValueError, 'unsupported source'):
                IntegratedStore(db, snapshot, snapshot_validator=validator('MyWindowsPC'))
            self.assertFalse(db.exists())
            self.assertEqual(snapshot.read_bytes(), old)

    def test_sqlite_bootstrap_accepts_matching_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder)/'history.db'
            snapshot = Path(folder)/'latest.json'
            envelope = sample('MyWindowsPC')
            snapshot.write_text(json.dumps(envelope), encoding='utf-8')
            store = IntegratedStore(db, snapshot, snapshot_validator=validator('MyWindowsPC'))
            try:
                self.assertTrue(db.is_file())
                rows = store.recent()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['source'], 'MyWindowsPC')
            finally:
                store.close()

    def test_existing_sqlite_history_preserved_across_source_identity_change(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder)/'history.db'
            snapshot = Path(folder)/'latest.json'
            initial = IntegratedStore(db, snapshot, snapshot_validator=validator('SQUALL'))
            old = sample('SQUALL', second_offset=-3)
            try:
                self.assertTrue(initial.accept(old))
            finally:
                initial.close()
            upgraded = IntegratedStore(db, snapshot, snapshot_validator=validator('MyWindowsPC'))
            try:
                earlier = upgraded.recent()
                self.assertEqual(len(earlier), 1)
                self.assertEqual(earlier[0]['source'], 'SQUALL')
                newer = sample('MyWindowsPC', second_offset=0)
                receiver.validate(newer, expected_source='MyWindowsPC')
                self.assertTrue(upgraded.accept(newer))
                self.assertEqual([s['source'] for s in upgraded.recent()], ['SQUALL', 'MyWindowsPC'])
            finally:
                upgraded.close()

    def test_store_requires_explicit_snapshot_validator(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(TypeError):
                IntegratedStore(Path(folder)/'history.db', Path(folder)/'snapshot.json')


if __name__ == '__main__':
    unittest.main(verbosity=2)
