"""v0.4 authenticated health API; localhost and disposable SQLite only."""
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from pi.services.receiver.integrated_store import IntegratedStore
from pi.services.receiver.receiver import handler_factory


class HealthApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = IntegratedStore(root / "samples.db", root / "latest.json")
        self.token = "local-test-token-" + "x" * 32
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), handler_factory(self.token, self.store))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.store.close()
        self.temp.cleanup()

    def get(self, path="/api/v1/health", authorized=True):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            headers = {"Authorization": "Bearer " + self.token} if authorized else {}
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), json.loads(response.read())
        finally:
            conn.close()

    def test_requires_authentication(self):
        status, _, body = self.get(authorized=False)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "unauthorized")

    def test_empty_history(self):
        status, headers, body = self.get()
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(body["status"], "no_data")

    def test_reads_committed_watermark(self):
        timestamp = datetime.now(timezone.utc).replace(microsecond=0)
        sample = {
            "schema_version": 1,
            "source": "SQUALL",
            "session_id": "12345678-1234-4234-8234-123456789abc",
            "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
            "sequence": 10,
            "metrics": {
                "cpu_percent": 20, "memory_used_percent": 40,
                "uptime_seconds": 300,
            },
        }
        self.assertTrue(self.store.accept(sample))
        status, _, body = self.get()
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "healthy")
        self.assertEqual(body["last_sample_utc"], sample["timestamp_utc"])
        self.assertNotIn("session_id", body)
        self.assertNotIn("token", body)

    def test_bad_query(self):
        status, _, body = self.get("/api/v1/health?anything=1")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_query")

    def test_sqlite_failure_fails_closed(self):
        with patch.object(self.store.history, "boundary",
                          side_effect=sqlite3.OperationalError("simulated")):
            status, _, body = self.get()
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "history_unavailable")


if __name__ == "__main__":
    unittest.main()
