"""HTTP integration regression tests for SQLite-authoritative v0.3.0 receiver.

Runs on localhost and temporary files; does not touch the live service.
"""
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from pi.services.receiver.integrated_store import IntegratedStore
from pi.services.receiver.receiver import handler_factory


class HttpHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.store = IntegratedStore(base / "history.db", base / "latest.json")
        self.token = "test-token-" + "x" * 40
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(self.token, self.store))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.store.close()
        self.temp.cleanup()

    def send(self, sequence=1):
        payload = {
            "schema_version": 1,
            "source": "SQUALL",
            "session_id": "12345678-1234-4234-8234-123456789abc",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "sequence": sequence,
            "metrics": {
                "cpu_percent": 20,
                "memory_used_percent": 40,
                "uptime_seconds": 100,
            },
        }
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(
                "POST", "/api/v1/telemetry",
                body=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": "Bearer " + self.token,
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            result = response.status
            response.read()
            return result
        finally:
            connection.close()

    def test_success_and_duplicate(self):
        self.assertEqual(self.send(1), 202)
        self.assertEqual(self.send(1), 409)
        self.assertEqual(self.store.history.count(), 1)

    def test_database_failure(self):
        with patch.object(
            self.store.history, "append",
            side_effect=sqlite3.OperationalError("simulated database failure"),
        ):
            self.assertEqual(self.send(1), 503)
        self.assertEqual(self.store.history.count(), 0)

    def test_snapshot_cache_failure(self):
        with patch.object(
            self.store, "_repair_cache",
            side_effect=OSError("simulated cache write failure"),
        ):
            self.assertEqual(self.send(1), 202)
        self.assertEqual(self.store.history.count(), 1)
        self.assertTrue(self.store.last_cache_error)


if __name__ == "__main__":
    unittest.main()
