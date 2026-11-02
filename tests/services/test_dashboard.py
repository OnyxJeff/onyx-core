"""Dashboard and migration edge-case tests: isolated localhost only."""
import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from pi.services.receiver.integrated_store import IntegratedStore
from pi.services.receiver.receiver import handler_factory


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "history.db"
        self.snapshot = root / "latest.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_existing_empty_database_does_not_reimport_json(self):
        original = IntegratedStore(self.db, self.snapshot)
        original.close()
        legacy = {
            "schema_version": 1, "source": "SQUALL",
            "session_id": "12345678-1234-4234-8234-123456789abc",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "sequence": 7,
            "metrics": {"cpu_percent": 10, "memory_used_percent": 20, "uptime_seconds": 30},
        }
        self.snapshot.write_text(json.dumps(legacy), encoding="utf-8")
        reopened = IntegratedStore(self.db, self.snapshot)
        try:
            self.assertEqual(reopened.history.count(), 0)
        finally:
            reopened.close()

    def test_dashboard_is_opt_in_and_local_page(self):
        store = IntegratedStore(self.db, self.snapshot)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory("t" * 40, store))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_port)
            try:
                connection.request("GET", "/dashboard")
                response = connection.getresponse()
                html = response.read()
                self.assertEqual(response.status, 200)
                self.assertIn(b"ONYX CORE", html)
                self.assertIn(b"/api/v1/history", html)
                self.assertEqual(response.getheader("Cache-Control"), "no-store")
            finally:
                connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            store.close()


if __name__ == "__main__":
    unittest.main()
