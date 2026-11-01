"""Minimal ONYX CORE telemetry receiver (Python stdlib, ARMv6 compatible).

Development-only until authentication, deployment and restart acceptance tests pass.
"""
import argparse
import hmac
import json
import math
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 8192
KEYS = {"schema_version", "source", "timestamp_utc", "sequence", "metrics"}
METRICS = {"cpu_percent", "memory_used_percent", "uptime_seconds"}


def validate(payload):
    if type(payload) is not dict or set(payload) != KEYS:
        raise ValueError("invalid envelope fields")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("unsupported schema")
    if payload["source"] != "SQUALL":
        raise ValueError("unsupported source")
    seq = payload["sequence"]
    if type(seq) is not int or not (0 <= seq <= 2**63 - 1):
        raise ValueError("invalid sequence")
    stamp = payload["timestamp_utc"]
    if type(stamp) is not str or len(stamp) > 40 or not stamp.endswith("Z"):
        raise ValueError("invalid UTC timestamp")
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ValueError("timestamp must be UTC")
    metrics = payload["metrics"]
    if type(metrics) is not dict or set(metrics) != METRICS:
        raise ValueError("invalid metrics")
    for key in ("cpu_percent", "memory_used_percent"):
        val = metrics[key]
        if type(val) not in (int, float) or not math.isfinite(val) or not 0 <= val <= 100:
            raise ValueError("invalid percentage")
    up = metrics["uptime_seconds"]
    if type(up) is not int or not 0 <= up <= 2**63 - 1:
        raise ValueError("invalid uptime")
    return payload


def handler_factory(token):
    class Handler(BaseHTTPRequestHandler):
        server_version = "OnyxCore/0.2-dev"
        sys_version = ""

        def log_message(self, fmt, *args):
            # No request headers or bodies in service logs.
            print("request from %s: %s" % (self.client_address[0], fmt % args), flush=True)

        def respond(self, status, data):
            raw = json.dumps(data, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/healthz":
                self.respond(200, {"status": "ok"})
            else:
                self.respond(404, {"error": "not_found"})

        def do_POST(self):
            if self.path != "/api/v1/telemetry":
                return self.respond(404, {"error": "not_found"})
            auth = self.headers.get("Authorization", "")
            expected = "Bearer " + token
            if not hmac.compare_digest(auth, expected):
                return self.respond(401, {"error": "unauthorized"})
            if self.headers.get_content_type() != "application/json":
                return self.respond(415, {"error": "unsupported_media_type"})
            raw_len = self.headers.get("Content-Length")
            try:
                n = int(raw_len)
            except (ValueError, TypeError):
                return self.respond(400, {"error": "invalid_length"})
            if n < 0 or n > MAX_BODY:
                return self.respond(413, {"error": "payload_too_large"})
            try:
                payload = json.loads(self.rfile.read(n), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
                validate(payload)
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                return self.respond(422, {"error": "invalid_payload"})
            # Persistence intentionally deferred until storage/sequence semantics are reviewed.
            self.server.last_sample = payload
            self.respond(202, {"accepted": True, "sequence": payload["sequence"]})

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", required=True, help="Explicit Pi USB IPv4 address; never 0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.bind in ("0.0.0.0", "127.0.0.1", "::") or not args.bind.startswith("192.168.137."):
        parser.error("bind address must be Pi's verified USB ICS IPv4 address")
    token = os.environ.get("ONYXCORE_TOKEN", "")
    if len(token) < 32:
        parser.error("ONYXCORE_TOKEN must be provisioned securely (32+ characters)")
    server = ThreadingHTTPServer((args.bind, args.port), handler_factory(token))
    print("Receiver listening on explicit USB interface", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
