"""Standalone history tests; safe to run without touching live receiver."""
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from pi.services.receiver.history import HistoryStore


def sample(n, timestamp, session="12345678-1234-4234-8234-123456789abc"):
    return {
        "schema_version": 1,
        "source": "SQUALL",
        "session_id": session,
        "sequence": n,
        "timestamp_utc": timestamp,
        "metrics": {"cpu_percent": 12.5, "memory_used_percent": 42.25,
                    "uptime_seconds": 3600 + n},
    }


def iso(dt):
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "telemetry.db"
        self.store = HistoryStore(self.path)

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def test_empty(self):
        self.assertEqual(self.store.count(), 0)
        self.assertEqual(self.store.recent(), [])

    def test_insert_reload_and_order(self):
        now = datetime.now(timezone.utc)
        self.assertTrue(self.store.append(sample(1, iso(now)), now=now))
        self.assertTrue(self.store.append(sample(2, iso(now + timedelta(seconds=30))), now=now))
        self.assertEqual([r["sequence"] for r in self.store.recent()], [1, 2])
        self.store.close()
        self.store = HistoryStore(self.path)
        self.assertEqual(self.store.count(), 2)
        self.assertEqual(self.store.recent(limit=1)[0]["sequence"], 2)

    def test_duplicate_idempotent(self):
        now = datetime.now(timezone.utc)
        s = sample(1, iso(now))
        self.assertTrue(self.store.append(s, now=now))
        self.assertFalse(self.store.append(s, now=now))
        self.assertEqual(self.store.count(), 1)

    def test_retention(self):
        now = datetime.now(timezone.utc)
        self.store.append(sample(1, iso(now - timedelta(days=6))), now=now)
        self.store.append(sample(2, iso(now)), now=now)
        self.store.append(sample(3, iso(now + timedelta(days=8))), now=now + timedelta(days=8))
        self.assertEqual([r["sequence"] for r in self.store.recent()], [3])

    def test_query_limit(self):
        for value in (0, -1, 501, True, "100"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.recent(limit=value)


if __name__ == "__main__":
    unittest.main()
