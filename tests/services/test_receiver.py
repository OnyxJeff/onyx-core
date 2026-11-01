"""Offline tests: no Pi installation, network service, or token required."""
import json
import threading
import unittest
from datetime import datetime, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from pi.services.receiver.receiver import handler_factory, validate


def example():
    return {"schema_version": 1, "source": "SQUALL",
            "timestamp_utc": "2026-11-01T21:00:00Z", "sequence": 1,
            "metrics": {"cpu_percent": 12.5,
                        "memory_used_percent": 38.1,
                        "uptime_seconds": 3600}}


class SchemaTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate(example())["sequence"], 1)

    def test_nan_rejected(self):
        data = example()
        data["metrics"]["cpu_percent"] = float("nan")
        with self.assertRaises(ValueError):
            validate(data)

    def test_negative_uptime_rejected(self):
        data = example()
        data["metrics"]["uptime_seconds"] = -1
        with self.assertRaises(ValueError):
            validate(data)

    def test_extra_fields_rejected(self):
        data = example()
        data["private"] = "anything"
        with self.assertRaises(ValueError):
            validate(data)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory("x" * 40))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, body, headers=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        conn.request("POST", path, body, headers or {})
        response = conn.getresponse()
        result = response.status
        response.read()
        conn.close()
        return result

    def test_unauthorized(self):
        self.assertEqual(self.request("/api/v1/telemetry", "{}"), 401)

    def test_oversize(self):
        h = {"Authorization": "Bearer " + "x" * 40, "Content-Type": "application/json"}
        self.assertEqual(self.request("/api/v1/telemetry", "x" * 8193, h), 413)

    def test_valid_post(self):
        h = {"Authorization": "Bearer " + "x" * 40, "Content-Type": "application/json"}
        self.assertEqual(self.request("/api/v1/telemetry", json.dumps(example()), h), 202)


if __name__ == "__main__":
    unittest.main()
