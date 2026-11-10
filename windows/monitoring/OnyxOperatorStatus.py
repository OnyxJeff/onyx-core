#!/usr/bin/env python3
"""ONYX CORE v0.7.0 M4: read existing development incident state without probes.

The only CLI path is approved by OnyxLiveIncident.approved_context().  No
initialize, repair, schedule, network probe, custom store path or write action
is exposed.  Read-only library functions accept an explicit temporary path for
offline tests and do not create directories or state files.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import OnyxIncidentState as reducer
import OnyxIncidentStore as storage
import OnyxLiveIncident as live

SCHEMA = 1
MAX_SHOWN_EVENTS = 20
CHECKPOINT_I = "5e3afef004505eca8ae79b32535b5cc711865fd2"


class OperatorStatusError(RuntimeError):
    """Refusal to present possibly incomplete or unauthorized stored state."""


def _safe_file(path: Path) -> None:
    if (path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
            or not path.is_file()):
        raise OperatorStatusError("incident data file absent or redirected")


def _safe_directory(directory: Path) -> None:
    if not directory.is_absolute():
        raise OperatorStatusError("incident directory must be absolute")
    for path in (directory.parent, directory):
        if (path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
                or not path.is_dir()):
            raise OperatorStatusError("incident directory missing or redirected")
    if directory.resolve() != directory.absolute():
        raise OperatorStatusError("incident directory path redirects")


def read_status(directory: Path, *, max_events: int = 10) -> dict:
    """Inspect one existing, validated incident snapshot; no writes or probes."""
    if type(max_events) is not int or not 0 <= max_events <= MAX_SHOWN_EVENTS:
        raise OperatorStatusError("event limit must be between 0 and 20")
    directory = Path(directory)
    _safe_directory(directory)
    state_file = directory / "incident-state.json"
    marker_file = directory / live.MARKER_NAME
    _safe_file(state_file)
    _safe_file(marker_file)
    if marker_file.read_bytes() != live.MARKER_BYTES:
        raise OperatorStatusError("incident initialization marker invalid")
    # Do NOT call load_store for a missing path: it returns a blank first-run
    # snapshot; this operator always requires an already initialized store.
    snapshot = storage.load_store(state_file)
    if snapshot["generation"] < 1 or snapshot["state"]["processed_cycles"] < 1:
        raise OperatorStatusError("incident store has no persisted observations")
    state = snapshot["state"]
    incident = state["incident"]
    events = snapshot["events"][-max_events:] if max_events else []
    return {
        "schema_version": SCHEMA,
        "source": "StoredIncidentSnapshot",
        "live_probed": False,
        "phase": state["phase"],
        "display_status": reducer.display_status(state),
        "evidence_status": state["evidence_status"],
        "incident_id": incident["id"] if incident else None,
        "incident_opened_utc": incident["opened_utc"] if incident else None,
        "last_cycle_finished_utc": state["last_cycle_finished_utc"],
        "last_recovered_utc": state["last_recovered_utc"],
        "generation": snapshot["generation"],
        "processed_cycles": state["processed_cycles"],
        "journal_count": len(snapshot["events"]),
        "events_discarded": snapshot["events_discarded"],
        "events_shown": [{
            "event_id": event["event_id"],
            "event_type": event["event_type"],
            "timestamp_utc": event["timestamp_utc"],
            "incident_id": event["incident_id"],
            "from_phase": event["from_phase"],
            "to_phase": event["to_phase"],
        } for event in events],
        "repair_action": "None",
    }


def render_text(status: dict) -> str:
    """Readable human output from a validated, sanitized status dictionary."""
    lines = [
        "ONYX CORE v0.7.0 | Stored incident status (development)",
        "NOTE: Historical snapshot only; NO new USB/ICS probe was run.",
        "Displayed status : " + status["display_status"],
        "Incident phase   : " + status["phase"],
        "Evidence         : " + status["evidence_status"],
        "Last observation : " + str(status["last_cycle_finished_utc"]),
        "Open incident    : " + (status["incident_id"] or "None"),
        "Incident opened  : " + (status["incident_opened_utc"] or "None"),
        "Last recovered   : " + (status["last_recovered_utc"] or "None"),
        "Stored cycles    : " + str(status["processed_cycles"]),
        "Store generation : " + str(status["generation"]),
        "Journal entries  : " + str(status["journal_count"]),
        "Older discarded  : " + str(status["events_discarded"]),
        "Repair action    : None",
        "Recent transitions:",
    ]
    if not status["events_shown"]:
        lines.append("  (no recorded transitions in selected range)")
    for event in status["events_shown"]:
        lines.append("  " + event["timestamp_utc"] + "  " + event["event_type"] +
                     "  " + event["from_phase"] + " -> " + event["to_phase"] +
                     "  " + (event["incident_id"] or "None"))
    return "\n".join(lines)


def approved_status(*, max_events: int = 10) -> dict:
    """CLI boundary: enforce all M2 worktree, config and production safeguards."""
    root, directory = live.approved_context()
    # M4 can only be invoked after validated M3 Checkpoint I is on HEAD.
    live._git(root, "merge-base", "--is-ancestor", CHECKPOINT_I, "HEAD")
    return read_status(directory, max_events=max_events)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", required=True,
                        help="explicitly inspect existing stored incident data")
    parser.add_argument("--json", action="store_true",
                        help="emit sanitized JSON instead of readable text")
    parser.add_argument("--events", type=int, default=10, metavar="N",
                        help="show last N journal entries (0..20; default 10)")
    args = parser.parse_args(argv)
    try:
        status = approved_status(max_events=args.events)
        print(json.dumps(status, sort_keys=True, separators=(",", ":"),
                         allow_nan=False) if args.json else render_text(status))
        return 0
    except (OperatorStatusError, storage.IncidentStoreError,
            live.LiveIncidentError, reducer.InvalidIncidentInput,
            OSError, ValueError) as exc:
        print("OPERATOR STATUS REFUSED: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
