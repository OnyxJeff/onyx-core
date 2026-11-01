# ONYX CORE telemetry wire contract — proposal v1

Status: **DRAFT for review, not implemented**. Related [Issue #5](https://github.com/OnyxJeff/onyx-core/issues/5).

## Transport

HTTP over the dedicated SQUALL ↔ Pi USB RNDIS network only; never bind receiver to all interfaces. Resolve `svr-onyxcore.local`, and confirm the address belongs to the currently connected USB subnet before use. Initial port proposal: **8765/TCP** (matches legacy receiver; no assumption that a listener exists). Never expose via pfSense, port forwarding, reverse proxy, or home LAN.

## Endpoints

- `GET /healthz`: bounded, unauthenticated liveness response. Should reveal no secrets or detailed host information.
- `POST /api/v1/telemetry`: require header `Authorization: Bearer <token>`, compare securely, validate Content-Type `application/json`, body at most **8 KiB**, schema version `1`. Reject unauthorized, malformed, or oversized requests without logging secrets.
- Response success: `202 Accepted`, including short safe acknowledgement. Errors use predictable 400/401/413/415/422 semantics. No user-controlled dynamic routes.

## Example envelope (synthetic, no real machine data)

```json
{
  "schema_version": 1,
  "source": "SQUALL",
  "timestamp_utc": "2026-11-01T21:00:00Z",
  "sequence": 1,
  "metrics": {
    "cpu_percent": 12.5,
    "memory_used_percent": 38.1,
    "uptime_seconds": 3600
  }
}
```

## Validation and semantics

- Enforce exact allowed fields, bounded string lengths and valid UTC timestamps; reject NaN, Infinity, negative uptime or percentages outside 0–100.
- Accept each sequence number once per source where feasible; define monotonic behavior across Windows restarts before coding.
- Define staleness using receiver monotonic time for recent arrivals, and UTC timestamps for source measurements. Clock skew must not silently create valid-looking fresh samples.
- Keep at most the latest valid snapshot on disk (atomic write), plus limited structured service logs. No bulk history in v0.2.0.
- Windows collector uses one in-flight send, bounded timeout, jittered/backoff retries, and no unlimited disk queue. If USB is unavailable, service stays healthy and resumes when transport returns.
- Authentication is a token, not encrypted transport; the USB link is a local trust boundary. Do not claim confidentiality against a compromised Windows host. A compromised Windows host can read its own token.
- Decide actual token distribution, key rotation and filesystem ACLs during security design review; never embed a real token in a repository or public log.

## Open design decisions

1. Which built-in Windows counters accurately expose CPU usage and memory percentage across this machine?
2. Should the initial version use manual foreground collector or a Scheduled Task only after reliability testing?
3. How to bind receiver dynamically to Pi DHCP address at startup, and rebind safely on address changes?
4. How to avoid duplicate samples after Windows reboot without making the implementation heavyweight?

No receiver or collector should be deployed before these decisions are reviewed.
