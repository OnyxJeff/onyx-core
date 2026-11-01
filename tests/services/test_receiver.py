"""Offline tests run on Pi with python3 -m unittest discover."""
import json
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timezone, timedelta
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from pi.services.receiver.receiver import handler_factory, validate, SnapshotStore


def example(seq=1, sid=None, timestamp=None):
    return {"schema_version": 1, "source": "SQUALL", "session_id": sid or "12345678-1234-4234-8234-123456789abc",
            "timestamp_utc": timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "sequence": seq, "metrics": {"cpu_percent": 12.5, "memory_used_percent": 38.1, "uptime_seconds": 3600}}


class SchemaTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate(example())["sequence"], 1)

    def test_nan_rejected(self):
        obj = example(); obj["metrics"]["cpu_percent"] = float("nan")
        with self.assertRaises(ValueError): validate(obj)

    def test_negative_uptime_rejected(self):
        obj = example(); obj["metrics"]["uptime_seconds"] = -1
        with self.assertRaises(ValueError): validate(obj)

    def test_extra_fields_rejected(self):
        obj = example(); obj["private"] = "anything"
        with self.assertRaises(ValueError): validate(obj)

    def test_stale_rejected(self):
        obj = example(timestamp=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat().replace("+00:00", "Z"))
        with self.assertRaises(ValueError): validate(obj)

    def test_bad_session_rejected(self):
        obj = example(sid="restart")
        with self.assertRaises(ValueError): validate(obj)

    def test_bool_percentage_rejected(self):
        obj = example(); obj["metrics"]["cpu_percent"] = True
        with self.assertRaises(ValueError): validate(obj)


class StoreTests(unittest.TestCase):
    def test_old_snapshot_loads_after_time_passes(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"snapshot.json"
            old = example(timestamp="2025-01-01T12:00:00Z")
            path.write_text(json.dumps(old), encoding="utf-8")
            s = SnapshotStore(path)
            self.assertEqual(s.last["sequence"], 1)

    def test_restart_duplicate_and_new_session(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"snapshot.json"
            s = SnapshotStore(path)
            first = example()
            self.assertTrue(s.accept(first))
            s = SnapshotStore(path)
            self.assertFalse(s.accept(first))
            self.assertTrue(s.accept(example(seq=2)))
            later = datetime.now(timezone.utc) + timedelta(seconds=2)
            fresh = example(seq=1, sid=str(uuid.uuid4()), timestamp=later.isoformat(timespec="seconds").replace("+00:00", "Z"))
            self.assertTrue(s.accept(fresh))
            self.assertEqual(json.loads(path.read_text())["session_id"], fresh["session_id"])


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory("x"*40, SnapshotStore(Path(cls.temp.name)/"latest.json")))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.temp.cleanup()

    def request(self, body, headers=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        conn.request("POST", "/api/v1/telemetry", body, headers or {})
        response = conn.getresponse(); status = response.status; response.read(); conn.close()
        return status

    def auth(self):
        return {"Authorization":"Bearer "+"x"*40,"Content-Type":"application/json"}

    def test_unauthorized(self):
        self.assertEqual(self.request("{}"), 401)

    def test_oversize(self):
        self.assertEqual(self.request("x"*8193, self.auth()), 413)

    def test_valid_post_and_duplicate(self):
        data = json.dumps(example(seq=8))
        self.assertEqual(self.request(data,self.auth()),202)
        self.assertEqual(self.request(data,self.auth()),409)

    def test_invalid_json(self):
        self.assertEqual(self.request("{",self.auth()),422)

    def test_wrong_content_type(self):
        h=self.auth(); h["Content-Type"]="text/plain"
        self.assertEqual(self.request("{}",h),415)


if __name__ == "__main__":
    unittest.main()
