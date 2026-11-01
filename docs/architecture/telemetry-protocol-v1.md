# ONYX CORE telemetry protocol v1 — implemented prototype contract

Tracking: [Issue #5](https://github.com/OnyxJeff/onyx-core/issues/5). Status: **prototype tested offline on Pi Zero (14/14 tests); no real host-to-Pi request or persistent service validated yet**.

## Transport and trust boundary

HTTP port 8765 over SQUALL ↔ Pi USB RNDIS. Receiver **must bind to the Pi's actual current USB ICS IPv4 address**, not 0.0.0.0; observed address 192.168.137.167 is a DHCP lease and is **not reserved**. Windows should resolve `svr-onyxcore.local` and confirm that it resolves to the Pi USB address. No LAN exposure, proxy or port forwarding. HTTP bearer tokens are not encrypted; this is a local-link assumption, not confidentiality against host compromise or other USB-link peers.

## API

- `GET /healthz`: 200 `{"status":"ok"}`, no secret required.
- `POST /api/v1/telemetry`: `Authorization: Bearer <secret>`, exact `Content-Type: application/json`, explicit unique decimal `Content-Length` at most 8192 bytes, no Transfer-Encoding.
- Successful new sample: 202 Accepted. Absent/wrong auth: 401. Wrong content type: 415. Missing/malformed length or transfer encoding: 400. Oversize: 413. Schema/clock/JSON violations: 422. Duplicate or out-of-order: 409. Storage failures: 503. Unrecognized path: 404.

## Envelope (synthetic example)

```json
{
  "schema_version": 1,
  "source": "SQUALL",
  "session_id": "6130c58d-9807-4f07-b6fb-5eb5c97247c0",
  "timestamp_utc": "2026-11-01T21:00:00Z",
  "sequence": 1,
  "metrics": {
    "cpu_percent": 12.5,
    "memory_used_percent": 38.1,
    "uptime_seconds": 3600
  }
}
```

**Always generate timestamp dynamically from UTC during real testing.** The static example above will be rejected after the freshness window.

- `schema_version`: integer exactly 1.
- `source`: string exactly `SQUALL` for this milestone.
- `session_id`: canonical lowercase UUID; fresh per collector process session.
- `sequence`: positive integer from 1 through 2^63 − 1, increasing within a session.
- `timestamp_utc`: ISO 8601 UTC with trailing Z; at most 40 characters; within ±5 minutes of receiver's current UTC clock for incoming requests.
- Percentages: finite JSON numbers in 0–100; bools not accepted. Uptime: nonnegative integer. No missing or additional fields.
- Snapshot: latest valid envelope only, stored by atomic file replacement with mode 0600; disk state is read back without applying the live ±5-minute clock filter.

## Replay and restart behavior

Within the same `session_id`, the receiver rejects a sequence <= that of the last accepted snapshot. On a different session, it requires a strictly later sample timestamp than the last accepted snapshot. The new session lets a restarted collector begin at sequence 1. The current receiver only remembers the **latest** snapshot, so it is not full lifetime replay prevention across all historical sessions; do not claim otherwise. The Windows collector must send sequentially, one outstanding sample at a time, and use current UTC timestamps.

## Prototype limitations before operational deployment

- Token supplied through `ONYXCORE_TOKEN` environment variable (>=32 characters). Provision securely and avoid publishing or writing secret-bearing example commands in public logs. Do not use a hardcoded demo token on a live listener.
- HTTP server currently uses `ThreadingHTTPServer`; connection/resource exhaustion and slow-client behavior need additional tests before unattended operation.
- Snapshot writes fsync/replace each accepted sample; measure disk write rate and SD longevity before 5-second continuous collection.
- Binding is fixed at process start; restarting on DHCP address change is not yet implemented.
- No Windows collector or systemd unit exists yet.
- Receiver input / state file should be tested with real USB traffic before automating anything.

## Offline ARMv6 test evidence

On 2026-11-01, the original Pi Zero (Python 3.13.5, ARMv6) passed 14 `unittest` tests in 0.714 seconds. Tests included bad JSON, oversize, unauthorized, valid/duplicate, wrong content type, session ID, boolean percentage, extra fields, NaN, uptime, stale payload, snapshot reload and new session sequence.

Next gate: manually start the receiver on USB with an ephemeral test token, send one authenticated fixture from Windows, inspect HTTP result and saved sample, stop process. **Do not deploy a service or scheduled task yet.**
