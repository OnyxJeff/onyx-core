"""Failure and restart tests for opt-in SQLite-authoritative telemetry."""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from pi.services.receiver.integrated_store import IntegratedStore
from pi.services.receiver.receiver import validate


def sample(sequence=1, session="12345678-1234-4234-8234-123456789abc", when=None):
    timestamp = (when or datetime.now(timezone.utc)).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {"schema_version": 1, "source": "SQUALL", "session_id": session,
            "sequence": sequence, "timestamp_utc": timestamp,
            "metrics": {"cpu_percent": 22, "memory_used_percent": 44.2, "uptime_seconds": 1234}}


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "telemetry.db"
        self.jsonfile = Path(self.temp.name) / "latest.json"
        self.store = IntegratedStore(self.db, self.jsonfile)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_database_and_snapshot(self):
        first = sample()
        validate(first)
        self.assertTrue(self.store.accept(first))
        self.assertEqual(self.store.recent(1)[0]["sequence"], 1)
        self.assertEqual(json.loads(self.jsonfile.read_text())["sequence"], 1)
        self.assertEqual(self.jsonfile.stat().st_mode & 0o777, 0o600)

    def test_duplicate_and_new_session_ordering(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        first = sample(1, when=now)
        self.assertTrue(self.store.accept(first))
        self.assertFalse(self.store.accept(first))
        self.assertFalse(self.store.accept(sample(1, "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa", when=now)))
        self.assertTrue(self.store.accept(sample(2, when=now + timedelta(seconds=1))))

    def test_database_failure_does_not_acknowledge(self):
        with patch.object(self.store.history, "append", side_effect=sqlite3.OperationalError("disk failure")):
            with self.assertRaises(sqlite3.OperationalError):
                self.store.accept(sample())
        self.assertEqual(self.store.history.count(), 0)
        self.assertFalse(self.jsonfile.exists())

    def test_snapshot_failure_does_not_lose_committed_sample(self):
        with patch.object(self.store, "_repair_cache", side_effect=OSError("cache write failed")):
            self.assertTrue(self.store.accept(sample()))
            self.assertTrue(self.store.last_cache_error)
        self.assertEqual(self.store.history.count(), 1)
        self.assertFalse(self.jsonfile.exists())
        self.store.close()
        self.store = IntegratedStore(self.db, self.jsonfile)
        self.assertEqual(json.loads(self.jsonfile.read_text())["sequence"], 1)

    def test_restart_preserves_ordering(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        first = sample(1, when=now)
        self.assertTrue(self.store.accept(first))
        self.store.close()
        self.store = IntegratedStore(self.db, self.jsonfile)
        self.assertFalse(self.store.accept(first))
        self.assertTrue(self.store.accept(sample(2, when=now + timedelta(seconds=1))))


if __name__ == "__main__":
    unittest.main()
