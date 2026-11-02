"""Acceptance boundary remains durable even when all history rows are pruned."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pi.services.receiver.integrated_store import IntegratedStore


SESSION = "12345678-1234-4234-8234-123456789abc"


def sample(seq, stamp, session=SESSION):
    return {
        "schema_version": 1, "source": "SQUALL",
        "session_id": session, "sequence": seq,
        "timestamp_utc": stamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "metrics": {"cpu_percent": 30, "memory_used_percent": 50,
                    "uptime_seconds": seq * 30},
    }


class WatermarkTests(unittest.TestCase):
    def test_pruned_history_cannot_reset_replay_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db, cache = root / "history.db", root / "latest.json"
            t = datetime.now(timezone.utc).replace(microsecond=0)
            store = IntegratedStore(db, cache)
            first = sample(5, t)
            self.assertTrue(store.accept(first))
            # Emulate full retention deletion while preserving authoritative
            # acceptance state. Never manipulate any live database.
            with store.history.conn:
                store.history.conn.execute("DELETE FROM samples")
            self.assertEqual(store.history.count(), 0)
            self.assertFalse(store.accept(first))
            store.close()
            store = IntegratedStore(db, cache)
            try:
                self.assertEqual(store.history.count(), 0)
                self.assertFalse(store.accept(first))
                self.assertFalse(store.accept(sample(1, t, "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa")))
                self.assertTrue(store.accept(sample(6, t + timedelta(seconds=1))))
                self.assertEqual(store.history.boundary()["sequence"], 6)
            finally:
                store.close()

    def test_replay_boundary_survives_retention_rollover(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            history = IntegratedStore(root / "samples.db", root / "latest.json")
            try:
                base = datetime.now(timezone.utc).replace(microsecond=0)
                self.assertTrue(history.accept(sample(1, base - timedelta(days=8))))
                self.assertTrue(history.accept(sample(2, base)))
                self.assertEqual(history.history.count(), 1)
                self.assertFalse(history.accept(sample(1, base - timedelta(days=8))))
                self.assertEqual(history.history.boundary()["sequence"], 2)
            finally:
                history.close()


if __name__ == "__main__":
    unittest.main()
