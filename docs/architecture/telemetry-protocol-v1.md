# ONYX CORE telemetry protocol v1 — implemented prototype contract

Tracking: [Issue #5](https://github.com/OnyxJeff/onyx-core/issues/5). Status: **implemented and field-validated on Pi Zero and Windows SQUALL (14/14 offline tests, live receiver, collector, reboot and USB outage recovery).**

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

## Operational deployment and limitations

- Token read via `ONYXCORE_TOKEN` from the root-protected `/etc/onyxcore/receiver.env` and used by the dedicated `onyxcore` service; Windows CurrentUser DPAPI token stays outside Git.
- `ThreadingHTTPServer` is bound only to the currently assigned Pi USB IPv4. `launch-receiver.sh` retries on absent DHCP through systemd; NetworkManager dispatcher `90-onyxcore-receiver` restarts an active receiver when the USB address differs. **An actual live DHCP readdress has not been tested.**
- The receiver atomically replaces one latest-sample JSON with mode 0600. There is no historical database. SD endurance under prolonged duty cycles has not been benchmarked.
- Client is Windows PowerShell 5.1 under `SQUALL\\jmay2`, with Scheduled Task Interactive logon trigger. `wscript.exe` starts the collector invisibly and forwards its exit code. The task does not run before Windows user sign-in.
- A bounded USB RNDIS interruption produced two logged collection failures and then resumed accepted sequences without collector restart. No TLS: bearer token travels over the local USB HTTP path; this is not protection against a compromised Windows host.
- Full security review and reproducible-install audit remain release gates; see [installation](../installation/v0.2.0-install.md) and [validation](../testing/v0.2.0-validation.md).

## Offline ARMv6 test evidence

On 2026-11-01, the original Pi Zero (Python 3.13.5, ARMv6) passed 14 `unittest` tests in 0.714 seconds. Tests included bad JSON, oversize, unauthorized, valid/duplicate, wrong content type, session ID, boolean percentage, extra fields, NaN, uptime, stale payload, snapshot reload and new session sequence.

Subsequent live USB, persistent receiver, Windows collector, Task Scheduler, outage and reboot validation **passed**. See the evidence log in the validation guide.
