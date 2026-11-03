"""Pure, read-only telemetry freshness evaluation for ONYX CORE v0.4.0.

No background scheduler, database writes, network calls or extra dependencies.
Receiver integration and HTTP status mapping are separate development steps.
"""
from datetime import datetime, timezone

WARNING_AFTER_SECONDS = 90
CRITICAL_AFTER_SECONDS = 180


def evaluate_health(last_sample_utc, *, now=None):
    """Return a health summary based on the last committed sample timestamp.

    last_sample_utc: UTC RFC3339 timestamp ending in Z, or None for no data.
    now: injectable timezone-aware datetime for deterministic tests.
    """
    current = datetime.now(timezone.utc) if now is None else now
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ValueError("now must be timezone aware")
    current = current.astimezone(timezone.utc)
    result = {
        "status": "unknown",
        "reason": "invalid_timestamp",
        "last_sample_utc": last_sample_utc,
        "age_seconds": None,
        "warning_after_seconds": WARNING_AFTER_SECONDS,
        "critical_after_seconds": CRITICAL_AFTER_SECONDS,
    }
    if last_sample_utc is None:
        result.update(status="no_data", reason="no_accepted_samples")
        return result
    if not isinstance(last_sample_utc, str) or not last_sample_utc.endswith("Z"):
        return result
    try:
        timestamp = datetime.fromisoformat(last_sample_utc[:-1] + "+00:00")
    except ValueError:
        return result
    if timestamp.utcoffset() is None:
        return result
    age = (current - timestamp).total_seconds()
    if age < 0:
        result.update(reason="sample_in_future")
        return result
    # Truncate to integer seconds for a stable, compact API response.
    result["age_seconds"] = int(age)
    if age <= WARNING_AFTER_SECONDS:
        result.update(status="healthy", reason="telemetry_fresh")
    elif age <= CRITICAL_AFTER_SECONDS:
        result.update(status="warning", reason="telemetry_stale")
    else:
        result.update(status="critical", reason="telemetry_stale")
    return result
