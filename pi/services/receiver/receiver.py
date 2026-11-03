"""ONYX CORE USB telemetry receiver, v0.5.0 development: standard library only."""
import argparse
import hmac
import ipaddress
import json
import math
import os
import sqlite3
import tempfile
import threading
import uuid
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

MAX_BODY = 8192
MAX_SKEW = timedelta(minutes=5)
KEYS = {"schema_version", "source", "session_id", "timestamp_utc", "sequence", "metrics"}
METRICS = {"cpu_percent", "memory_used_percent", "uptime_seconds"}
OPTIONAL_METRICS = {
    "gpu_percent", "gpu_temp_c", "gpu_vram_used_mib", "gpu_vram_total_mib",
    "network_rx_bps", "network_tx_bps", "cpu_temp_c",
}


def validate(payload, now=None, check_freshness=True):
    if type(payload) is not dict or set(payload) != KEYS:
        raise ValueError("invalid envelope fields")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("unsupported schema")
    if payload["source"] != "SQUALL":
        raise ValueError("unsupported source")
    try:
        sid = payload["session_id"]
        if type(sid) is not str or str(uuid.UUID(sid)) != sid:
            raise ValueError("invalid session_id")
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("invalid session_id") from exc
    seq = payload["sequence"]
    if type(seq) is not int or not 1 <= seq <= 2**63 - 1:
        raise ValueError("invalid sequence")
    stamp = payload["timestamp_utc"]
    if type(stamp) is not str or len(stamp) > 40 or not stamp.endswith("Z"):
        raise ValueError("invalid UTC timestamp")
    try:
        parsed = datetime.fromisoformat(stamp[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("invalid UTC timestamp") from exc
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    reference = now or datetime.now(timezone.utc)
    if check_freshness and abs(reference - parsed) > MAX_SKEW:
        raise ValueError("timestamp outside allowed skew")
    metrics = payload["metrics"]
    if type(metrics) is not dict or not METRICS.issubset(metrics) or set(metrics) - (METRICS | OPTIONAL_METRICS):
        raise ValueError("invalid metrics")
    for key in ("cpu_percent", "memory_used_percent"):
        val = metrics[key]
        if type(val) not in (int, float) or not math.isfinite(val) or not 0 <= val <= 100:
            raise ValueError("invalid percentage")
    up = metrics["uptime_seconds"]
    if type(up) is not int or not 0 <= up <= 2**63 - 1:
        raise ValueError("invalid uptime")
    for key in OPTIONAL_METRICS & metrics.keys():
        value = metrics[key]
        if value is None:  # Unavailable sensor is distinct from zero.
            continue
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("invalid optional metric")
        if key == "gpu_percent" and not 0 <= value <= 100:
            raise ValueError("invalid gpu percentage")
        if key in ("gpu_temp_c", "cpu_temp_c") and not -20 <= value <= 150:
            raise ValueError("invalid temperature")
        if key in ("gpu_vram_used_mib", "gpu_vram_total_mib") and not 0 <= value <= 1048576:
            raise ValueError("invalid VRAM amount")
        if key in ("network_rx_bps", "network_tx_bps") and not 0 <= value <= 1e12:
            raise ValueError("invalid network rate")
    used, total = metrics.get("gpu_vram_used_mib"), metrics.get("gpu_vram_total_mib")
    if used is not None and total is not None and used > total:
        raise ValueError("VRAM used exceeds total")
    return payload


class SnapshotStore:
    """Store only latest accepted envelope; atomic replacement; thread safe."""
    def __init__(self, filename):
        self.path = Path(filename)
        self.lock = threading.Lock()
        self.last = None
        if self.path.is_file():
            with self.path.open("r", encoding="utf-8") as f:
                candidate = json.load(f)
            validate(candidate, check_freshness=False)
            self.last = candidate

    def accept(self, sample):
        with self.lock:
            prev = self.last
            if prev is not None:
                if sample["session_id"] == prev["session_id"]:
                    if sample["sequence"] <= prev["sequence"]:
                        return False
                elif datetime.fromisoformat(sample["timestamp_utc"][:-1] + "+00:00") <= datetime.fromisoformat(prev["timestamp_utc"][:-1] + "+00:00"):
                    return False
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".snapshot-", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(sample, f, allow_nan=False, separators=(",", ":"))
                    f.flush()
                    os.fsync(f.fileno())
                os.chmod(tmp, 0o600)
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            self.last = sample
            return True


def handler_factory(token, store=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "OnyxCore/0.5.0-dev"
        sys_version = ""
        timeout = 5

        def log_message(self, fmt, *args):
            # Avoid reflecting client-controlled request paths, headers or payloads.
            print("receiver request completed", flush=True)

        def respond(self, status, data):
            raw = json.dumps(data, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True

        def do_GET(self):
            if self.path == "/healthz":
                return self.respond(200, {"status": "ok"})
            if urlsplit(self.path).path in ("/dashboard", "/dashboard/"):
                target = store or getattr(self.server, "store", None)
                if target is None or not hasattr(target, "recent"):
                    return self.respond(404, {"error": "not_found"})
                try:
                    page = Path(__file__).with_name("dashboard.html").read_bytes()
                except OSError:
                    return self.respond(503, {"error": "dashboard_unavailable"})
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.wfile.write(page)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                self.close_connection = True
                return
            parsed = urlsplit(self.path)
            if parsed.path not in ("/api/v1/history", "/api/v1/latest", "/api/v1/health"):
                return self.respond(404, {"error": "not_found"})
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                return self.respond(401, {"error": "unauthorized"})
            target = store or getattr(self.server, "store", None)
            if target is None or not hasattr(target, "recent"):
                return self.respond(503, {"error": "history_unavailable"})
            try:
                if parsed.path == "/api/v1/health":
                    if parsed.query:
                        return self.respond(400, {"error": "invalid_query"})
                    if not hasattr(target, "health"):
                        return self.respond(503, {"error": "health_unavailable"})
                    return self.respond(200, target.health())
                if parsed.path == "/api/v1/latest":
                    if parsed.query:
                        return self.respond(400, {"error": "invalid_query"})
                    latest = target.recent(limit=1)
                    return self.respond(200, {"sample": latest[-1] if latest else None})
                params = parse_qs(parsed.query, keep_blank_values=True)
                if set(params) - {"limit"} or len(params.get("limit", ["120"])) != 1:
                    return self.respond(400, {"error": "invalid_query"})
                raw_limit = params.get("limit", ["120"])[0]
                if not raw_limit.isascii() or not raw_limit.isdecimal() or len(raw_limit) > 3:
                    return self.respond(400, {"error": "invalid_query"})
                limit = int(raw_limit)
                if not 1 <= limit <= 500:
                    return self.respond(400, {"error": "invalid_query"})
                samples = target.recent(limit=limit)
                return self.respond(200, {"samples": samples, "count": len(samples)})
            except (OSError, sqlite3.Error):
                return self.respond(503, {"error": "history_unavailable"})

        def do_POST(self):
            if self.path != "/api/v1/telemetry":
                return self.respond(404, {"error": "not_found"})
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                return self.respond(401, {"error": "unauthorized"})
            if self.headers.get("Transfer-Encoding") is not None:
                return self.respond(400, {"error": "unsupported_transfer_encoding"})
            if self.headers.get("Content-Type", "").lower() != "application/json":
                return self.respond(415, {"error": "unsupported_media_type"})
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal():
                return self.respond(400, {"error": "invalid_length"})
            n = int(lengths[0]) if len(lengths[0]) <= 5 else MAX_BODY + 1
            if n > MAX_BODY:
                return self.respond(413, {"error": "payload_too_large"})
            raw = self.rfile.read(n)
            if len(raw) != n:
                return self.respond(400, {"error": "truncated_body"})
            try:
                payload = json.loads(raw.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
                validate(payload)
            except (ValueError, UnicodeDecodeError):
                return self.respond(422, {"error": "invalid_payload"})
            target = store or getattr(self.server, "store", None)
            if target is None:
                return self.respond(503, {"error": "store_not_configured"})
            try:
                accepted = target.accept(payload)
            except (OSError, sqlite3.Error):
                return self.respond(503, {"error": "storage_unavailable"})
            if not accepted:
                return self.respond(409, {"error": "out_of_order_or_duplicate"})
            return self.respond(202, {"accepted": True, "sequence": payload["sequence"]})

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", required=True, help="Explicit Pi USB ICS IPv4 address")
    parser.add_argument("--allow-loopback-test", action="store_true", help="Allow localhost bind for isolated testing only")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--history-file", help="Optional SQLite authoritative history; omit for snapshot-only compatibility")
    args = parser.parse_args()
    try:
        address = ipaddress.IPv4Address(args.bind)
        if not (args.allow_loopback_test and address == ipaddress.IPv4Address("127.0.0.1")) and (address not in ipaddress.IPv4Network("192.168.137.0/24") or address in (ipaddress.IPv4Address("192.168.137.0"), ipaddress.IPv4Address("192.168.137.255"), ipaddress.IPv4Address("192.168.137.1"))):
            raise ValueError()
    except ValueError:
        parser.error("bind must be Pi's verified USB ICS IPv4 address")
    token = os.environ.get("ONYXCORE_TOKEN", "")
    if len(token) < 32:
        parser.error("ONYXCORE_TOKEN must be securely provisioned (32+ characters)")
    if args.history_file:
        try:
            from .integrated_store import IntegratedStore
        except ImportError:
            from integrated_store import IntegratedStore
        store = IntegratedStore(args.history_file, args.state_file)
    else:
        store = SnapshotStore(args.state_file)
    server = ThreadingHTTPServer((args.bind, args.port), handler_factory(token, store))
    server.daemon_threads = True
    print("Receiver listening on USB IPv4 only", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if args.history_file:
            store.close()


if __name__ == "__main__":
    main()
