#!/usr/bin/env python3
"""ONYX CORE v0.7.0 M4: read-only, age-aware incident operator report.

No live probe, repair, scheduling, state mutation, or arbitrary CLI store path.
CLI access remains restricted to the established development worktree and
validated production baseline. Library functions are deterministic for tests.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import sys

import OnyxIncidentStore as storage
import OnyxIncidentState as reducer
import OnyxLiveIncident as live
import OnyxOperatorStatus as operator

SCHEMA = 1
CHECKPOINT_J = "3c2a1dd99ef928caa56a8ae13e4b690eaefb5e6b"
DEFAULT_STALE_MINUTES = 30
MAX_STALE_MINUTES = 1440
FUTURE_TOLERANCE_SECONDS = 120


class OperatorReportError(RuntimeError):
    """Reject invalid report input rather than giving optimistic status."""


def _utc_string(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 48:
        raise OperatorReportError("stored observation time invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OperatorReportError("stored observation time invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OperatorReportError("stored observation time lacks timezone")
    return parsed.astimezone(timezone.utc)


def summarize(status: dict, *, now_utc: datetime, stale_minutes: int = DEFAULT_STALE_MINUTES) -> dict:
    """Enrich a validated stored snapshot without making a fresh health claim."""
    if type(stale_minutes) is not int or not 1 <= stale_minutes <= MAX_STALE_MINUTES:
        raise OperatorReportError("stale threshold must be 1..1440 minutes")
    if not isinstance(now_utc, datetime) or now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise OperatorReportError("reference time must be timezone-aware")
    if (type(status) is not dict or status.get("source") != "StoredIncidentSnapshot"
            or status.get("live_probed") is not False or status.get("repair_action") != "None"):
        raise OperatorReportError("untrusted or live-probed operator snapshot")
    if status.get("phase") not in reducer.PHASES:
        raise OperatorReportError("unexpected incident phase")
    if status.get("display_status") not in reducer.PHASES:
        raise OperatorReportError("unexpected display status")
    if status.get("evidence_status") not in ("Complete", "Incomplete"):
        raise OperatorReportError("unexpected evidence status")
    if (type(status.get("generation")) is not int or status["generation"] < 1
            or type(status.get("processed_cycles")) is not int
            or status["processed_cycles"] < 1):
        raise OperatorReportError("invalid persisted observation count")
    if type(status.get("events_shown")) is not list:
        raise OperatorReportError("invalid selected journal events")
    if (type(status.get("journal_count")) is not int or status["journal_count"] < 0
            or type(status.get("events_discarded")) is not int or status["events_discarded"] < 0):
        raise OperatorReportError("invalid journal summary")
    if len(status["events_shown"]) > operator.MAX_SHOWN_EVENTS or len(status["events_shown"]) > status["journal_count"]:
        raise OperatorReportError("invalid journal event selection")

    observed_at = _parse_utc(status.get("last_cycle_finished_utc"))
    reference = now_utc.astimezone(timezone.utc)
    age_seconds = (reference - observed_at).total_seconds()
    cutoff = stale_minutes * 60
    if age_seconds < -FUTURE_TOLERANCE_SECONDS:
        freshness = "FutureClockSkew"
        report_age = None
    elif age_seconds > cutoff:
        freshness = "Stale"
        report_age = int(age_seconds)
    else:
        freshness = "Recent"
        report_age = max(0, int(age_seconds))

    events = status["events_shown"]
    counts: Counter[str] = Counter()
    sanitized_events = []
    for event in events:
        if type(event) is not dict or event.get("event_type") not in storage.EVENT_TYPES:
            raise OperatorReportError("unexpected event selection")
        counts[event["event_type"]] += 1
        sanitized_events.append({key: event[key] for key in (
            "event_id", "event_type", "timestamp_utc", "incident_id",
            "from_phase", "to_phase")})

    active = status["incident_id"] is not None
    if freshness == "FutureClockSkew":
        assessment = "Timestamp is ahead of this computer; check clock synchronization before trusting recency."
    elif freshness == "Stale":
        assessment = "Historical observation is stale; use a new explicitly authorized read-only cycle to reassess."
    elif status["evidence_status"] == "Incomplete" or status["display_status"] == "Unknown":
        assessment = "Evidence was incomplete; do not infer the connection is healthy."
    elif active:
        assessment = "An incident remained open at the last observation; investigate before relying on connectivity."
    elif status["phase"] == "Recovered":
        assessment = "The most recently recorded incident recovered; this is not a current connectivity guarantee."
    else:
        assessment = "Last recorded evidence was complete; no fresh probe was made by this report."

    return {
        "schema_version": SCHEMA,
        "source": "StoredIncidentOperatorReport",
        "live_probed": False,
        "as_of_utc": _utc_string(reference),
        "last_observation_utc": _utc_string(observed_at),
        "age_seconds": report_age,
        "freshness": freshness,
        "stale_after_minutes": stale_minutes,
        "display_status_at_observation": status["display_status"],
        "phase": status["phase"],
        "evidence_status": status["evidence_status"],
        "incident_open": active,
        "incident_id": status["incident_id"],
        "incident_opened_utc": status["incident_opened_utc"],
        "last_recovered_utc": status["last_recovered_utc"],
        "generation": status["generation"],
        "processed_cycles": status["processed_cycles"],
        "journal_count": status["journal_count"],
        "events_discarded": status["events_discarded"],
        "selected_event_count": len(sanitized_events),
        "selected_event_counts": dict(sorted(counts.items())),
        "history_is_partial": (len(sanitized_events) < status["journal_count"]
                               or status["events_discarded"] > 0),
        "events_shown": sanitized_events,
        "assessment": assessment,
        "repair_action": "None",
    }


def render_text(report: dict) -> str:
    """Print sanitized, explicitly historical information only."""
    lines = [
        "ONYX CORE v0.7.0 | Read-only operator report (development)",
        "NOTE: Historical stored data. No live USB/ICS probe or repair was run.",
        "Observed status  : " + report["display_status_at_observation"],
        "Incident phase   : " + report["phase"],
        "Evidence         : " + report["evidence_status"],
        "Observed UTC     : " + report["last_observation_utc"],
        "Report as of UTC : " + report["as_of_utc"],
        "Freshness        : " + report["freshness"],
        "Age seconds      : " + (str(report["age_seconds"]) if report["age_seconds"] is not None else "Unavailable (future clock skew)"),
        "Stale after      : " + str(report["stale_after_minutes"]) + " minutes",
        "Open incident    : " + (report["incident_id"] or "None"),
        "Stored cycles    : " + str(report["processed_cycles"]),
        "Store generation : " + str(report["generation"]),
        "Journal retained : " + str(report["journal_count"]),
        "Older discarded  : " + str(report["events_discarded"]),
        "Events selected  : " + str(report["selected_event_count"]),
        "History partial  : " + ("Yes" if report["history_is_partial"] else "No"),
        "Repair action    : None",
        "Assessment       : " + report["assessment"],
        "Recent incident transitions:",
    ]
    if not report["events_shown"]:
        lines.append("  (no recorded transitions in selected range)")
    for event in report["events_shown"]:
        lines.append("  " + event["timestamp_utc"] + "  " + event["event_type"] +
                     "  " + event["from_phase"] + " -> " + event["to_phase"])
    return "\n".join(lines)


def approved_report(*, events: int = 10, stale_minutes: int = DEFAULT_STALE_MINUTES) -> dict:
    """Production CLI must pass all fixed development and ancestry guards."""
    root, directory = live.approved_context()
    live._git(root, "merge-base", "--is-ancestor", CHECKPOINT_J, "HEAD")
    snapshot = operator.read_status(directory, max_events=events)
    return summarize(snapshot, now_utc=datetime.now(timezone.utc), stale_minutes=stale_minutes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", required=True,
                        help="explicitly inspect the existing persisted incident snapshot")
    parser.add_argument("--json", action="store_true", help="output sanitized JSON")
    parser.add_argument("--events", type=int, default=10, metavar="N",
                        help="last N transition events (0..20; default 10)")
    parser.add_argument("--stale-minutes", type=int, default=DEFAULT_STALE_MINUTES, metavar="N",
                        help="stale threshold in minutes (1..1440; default 30)")
    args = parser.parse_args(argv)
    try:
        result = approved_report(events=args.events, stale_minutes=args.stale_minutes)
        print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
              if args.json else render_text(result))
        return 0
    except (OperatorReportError, operator.OperatorStatusError,
            storage.IncidentStoreError, live.LiveIncidentError,
            reducer.InvalidIncidentInput, OSError, ValueError, KeyError, TypeError) as exc:
        print("OPERATOR REPORT REFUSED: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
