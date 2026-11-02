"""Isolated migration and authenticated history API tests."""
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import sqlite3

from pi.services.receiver.integrated_store import IntegratedStore
from pi.services.receiver.receiver import handler_factory


def envelope(seq=1, when=None):
    return {"schema_version": 1, "source": "SQUALL",
            "session_id": "12345678-1234-4234-8234-123456789abc",
            "timestamp_utc": (when or datetime.now(timezone.utc)).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "sequence": seq,
            "metrics": {"cpu_percent": 11, "memory_used_percent": 22, "uptime_seconds": 33}}


class MigrationAndApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.db = base / "samples.db"
        self.snapshot = base / "latest.json"
        self.token = "T" * 40

    def tearDown(self):
        self.temp.cleanup()

    def request(self, server, path, authenticated=True):
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=4)
        headers = {"Authorization": "Bearer " + self.token} if authenticated else {}
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_migrate_snapshot_and_preserve_replay_boundary(self):
        prior = envelope(seq=7)
        self.snapshot.write_text(json.dumps(prior), encoding="utf-8")
        store = IntegratedStore(self.db, self.snapshot)
        try:
            self.assertEqual(store.history.count(), 1)
            self.assertFalse(store.accept(prior))
            self.assertTrue(store.accept(envelope(seq=8)))
        finally:
            store.close()

    def test_invalid_legacy_snapshot_fails_closed(self):
        self.snapshot.write_text('{"invalid":true}', encoding="utf-8")
        with self.assertRaises(ValueError):
            IntegratedStore(self.db, self.snapshot)

    def test_empty_and_authorized_readonly_api(self):
        store = IntegratedStore(self.db, self.snapshot)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(self.token, store))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            self.assertEqual(self.request(server, "/healthz", authenticated=False)[0], 200)
            self.assertEqual(self.request(server, "/api/v1/history", authenticated=False)[0], 401)
            self.assertEqual(self.request(server, "/api/v1/latest", authenticated=False)[0], 401)
            self.assertEqual(self.request(server, "/api/v1/history")[1]["samples"], [])
            self.assertIsNone(self.request(server, "/api/v1/latest")[1]["sample"])
            self.assertTrue(store.accept(envelope()))
            status, result = self.request(server, "/api/v1/history?limit=1")
            self.assertEqual(status, 200)
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["samples"][0]["sequence"], 1)
            self.assertEqual(self.request(server, "/api/v1/latest")[1]["sample"]["sequence"], 1)
            for path in ("/api/v1/history?limit=0", "/api/v1/history?limit=501",
                         "/api/v1/history?limit=abc", "/api/v1/history?bad=1",
                         "/api/v1/history?limit=1&limit=2", "/api/v1/latest?a=1"):
                with self.subTest(path=path):
                    self.assertEqual(self.request(server, path)[0], 400)
            with patch.object(store, "recent", side_effect=sqlite3.OperationalError("no storage")):
                self.assertEqual(self.request(server, "/api/v1/history")[0], 503)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
            store.close()


if __name__ == "__main__":
    unittest.main()
