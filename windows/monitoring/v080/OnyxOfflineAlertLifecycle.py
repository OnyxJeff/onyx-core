#!/usr/bin/env python3
"""ONYX CORE v0.8.0 M3: in-memory SYNTHETIC alert proposals only.

No production event intake, real authentication, notifications, network operations,
incident persistence, enrollment, Task Scheduler operations, or repair.
This module validates the v0.7.0 pure reducer event *shape* and sequencing;
it does NOT attest that a synthetic event came from a real diagnostic/reducer.
All alert objects are proposals, never delivered notifications.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import sys
from typing import Any

SOURCE = "OnyxV080M3SyntheticAlerts"
PROVENANCE = "SyntheticFixtureOnly"
SCHEMA = 1
MAX_RAW_BYTES = 65536
MAX_EVENTS_BATCH = 32
MAX_TRACKED = 256  # Refuse on capacity rather than forget and resend.
MAX_AGE_SECONDS = 300
MAX_FUTURE_SECONDS = 5
HEX64 = re.compile(r"^[0-9a-f]{64}$")
EVENT_ID = re.compile(r"^evt-[0-9a-f]{24}$")
INCIDENT_ID = re.compile(r"^inc-[0-9a-f]{24}$")
EVENT_FIELDS = frozenset(("schema_version", "event_id", "event_type", "timestamp_utc",
                          "incident_id", "from_phase", "to_phase", "connectivity_decision", "repair_action"))
BATCH_FIELDS = frozenset(("schema_version", "source", "provenance", "reference_utc", "events"))
STATE_FIELDS = frozenset(("schema_version", "source", "provenance", "phase", "evidence_status",
                          "incident_id", "acknowledged_by", "acknowledged_at_utc", "last_timestamp_utc",
                          "seen_events", "intent_keys", "proposal_count"))
PHASES = frozenset(("Unknown", "Healthy", "Suspected", "Active", "Recovered"))
EVIDENCE = frozenset(("Unknown", "Complete", "Incomplete"))
EVENTS = frozenset(("IncidentOpened", "IncidentEscalated", "IncidentRecovered", "EvidenceIncomplete", "EvidenceRestored"))
DECISIONS = frozenset(("Healthy", "WaitAndRetry", "Investigate", "PossibleIcsFailure"))
INTENTS = {"IncidentOpened": "Investigate", "IncidentEscalated": "Escalated",
           "IncidentRecovered": "RecoveryCandidate", "EvidenceIncomplete": "EvidenceMissing"}


class OfflineAlertError(ValueError):
    """Refused simulated state or event without mutating inputs or external state."""


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise OfflineAlertError(reason)


def _utc(value: Any) -> datetime:
    _require(type(value) is str and 20 <= len(value) <= 64, "offset-aware timestamp required")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OfflineAlertError("bad timestamp") from exc
    _require(stamp.tzinfo is not None and stamp.utcoffset() is not None,
             "timestamp offset required")
    return stamp.astimezone(timezone.utc)


def _iso(stamp: datetime) -> str:
    return stamp.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _pairs_unique(pairs: list[tuple[str, Any]]) -> dict:
    out: dict = {}
    for k, v in pairs:
        _require(k not in out, "duplicate JSON property")
        out[k] = v
    return out


def _no_nonfinite(value: str) -> None:
    raise OfflineAlertError("nonfinite value refused")


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise OfflineAlertError("invalid JSON value") from exc


def initial_state() -> dict:
    return {"schema_version": SCHEMA, "source": SOURCE, "provenance": PROVENANCE,
            "phase": "Unknown", "evidence_status": "Unknown", "incident_id": None,
            "acknowledged_by": None, "acknowledged_at_utc": None,
            "last_timestamp_utc": None, "seen_events": [], "intent_keys": [], "proposal_count": 0}


def validate_state(state: Any) -> None:
    _require(type(state) is dict and set(state) == STATE_FIELDS, "alert state fields invalid")
    _require(type(state["schema_version"]) is int and state["schema_version"] == 1 and
             state["source"] == SOURCE and state["provenance"] == PROVENANCE,
             "alert state provenance invalid")
    _require(state["phase"] in PHASES and state["evidence_status"] in EVIDENCE,
             "alert state phase/evidence invalid")
    iid = state["incident_id"]
    _require(iid is None or (type(iid) is str and INCIDENT_ID.fullmatch(iid) is not None),
             "alert state incident id invalid")
    _require((iid is None) == (state["phase"] not in ("Suspected", "Active")),
             "alert state incident/phase mismatch")
    actor = state["acknowledged_by"]
    at = state["acknowledged_at_utc"]
    _require((actor is None) == (at is None), "partial acknowledgement")
    if actor is not None:
        _require(iid is not None and type(actor) is str and actor.startswith("synthetic:") and
                 11 <= len(actor) <= 64, "bad synthetic acknowledgement")
        _utc(at)
    stamp = state["last_timestamp_utc"]
    _require(stamp is None or type(stamp) is str, "last timestamp invalid")
    if stamp is not None:
        _utc(stamp)
    _require(type(state["proposal_count"]) is int and 0 <= state["proposal_count"] <= MAX_TRACKED,
             "proposal count invalid")
    seen = state["seen_events"]
    keys = state["intent_keys"]
    _require(type(seen) is list and len(seen) <= MAX_TRACKED and
             type(keys) is list and len(keys) <= MAX_TRACKED, "history limit exceeded")
    event_ids = set()
    for entry in seen:
        _require(type(entry) is dict and set(entry) == {"event_id", "sha256"},
                 "seen event format invalid")
        eid, digest = entry["event_id"], entry["sha256"]
        _require(type(eid) is str and EVENT_ID.fullmatch(eid) is not None and
                 type(digest) is str and HEX64.fullmatch(digest) is not None and
                 eid not in event_ids, "seen event digest/identity invalid")
        event_ids.add(eid)
    _require(len(set(map(str, keys))) == len(keys), "duplicate intent keys")
    for key in keys:
        _require(type(key) is str and 1 <= len(key) <= 128 and
                 key.count("|") == 1 and key.split("|")[1] in INTENTS and
                 (key.split("|")[0] == "none" or INCIDENT_ID.fullmatch(key.split("|")[0]) is not None),
                 "invalid intent dedup key")
    _require(state["proposal_count"] == len(keys), "proposal/key count diverge")
    _require(not seen or stamp is not None, "seen event without last timestamp")
    # An acknowledgement can predate later observed events without becoming invalid.
    _require(len(_canonical(state)) <= MAX_RAW_BYTES, "alert state too large")


def _validate_event(event: Any, reference: datetime) -> tuple[datetime, str]:
    _require(type(event) is dict and set(event) == EVENT_FIELDS, "event fields invalid")
    _require(type(event["schema_version"]) is int and event["schema_version"] == SCHEMA,
             "event schema invalid")
    kind = event["event_type"]
    _require(type(kind) is str and kind in EVENTS, "unsupported event type")
    _require(event["repair_action"] == "None", "repair claim refused")
    _require(type(event["connectivity_decision"]) is str and
             event["connectivity_decision"] in DECISIONS, "invalid connectivity decision")
    _require(type(event["from_phase"]) is str and event["from_phase"] in PHASES and
             type(event["to_phase"]) is str and event["to_phase"] in PHASES, "bad event phases")
    iid = event["incident_id"]
    _require(iid is None or (type(iid) is str and INCIDENT_ID.fullmatch(iid) is not None),
             "bad event incident ID")
    at = _utc(event["timestamp_utc"])
    _require(reference - timedelta(seconds=MAX_AGE_SECONDS) <= at <=
             reference + timedelta(seconds=MAX_FUTURE_SECONDS), "stale/future synthetic event")
    eid = event["event_id"]
    basis = "|".join((kind, event["timestamp_utc"], iid or "none"))
    expected = "evt-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    _require(type(eid) is str and eid == expected, "event ID does not match v0.7 deterministic identity")
    if kind == "IncidentOpened":
        _require(iid is not None and event["from_phase"] in ("Unknown", "Healthy", "Recovered") and
                 event["to_phase"] in ("Suspected", "Active") and
                 event["connectivity_decision"] != "Healthy", "opened event inconsistent")
        if event["to_phase"] == "Active":
            _require(event["connectivity_decision"] == "PossibleIcsFailure", "active opening uncorroborated")
    elif kind == "IncidentEscalated":
        _require(iid is not None and event["from_phase"] == "Suspected" and
                 event["to_phase"] == "Active" and
                 event["connectivity_decision"] == "PossibleIcsFailure", "escalation inconsistent")
    elif kind == "IncidentRecovered":
        _require(iid is not None and event["from_phase"] in ("Suspected", "Active") and
                 event["to_phase"] == "Recovered" and
                 event["connectivity_decision"] == "Healthy", "recovery inconsistent")
    else:
        _require(event["from_phase"] == event["to_phase"] and
                 ((kind == "EvidenceIncomplete" and event["connectivity_decision"] == "Investigate") or
                  kind == "EvidenceRestored"), "evidence transition inconsistent")
    return at, hashlib.sha256(_canonical(event)).hexdigest()


def _parse_batch(raw: bytes) -> tuple[datetime, list[dict]]:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_RAW_BYTES, "empty/oversized synthetic batch")
    try:
        data = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_pairs_unique,
                          parse_constant=_no_nonfinite)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise OfflineAlertError("invalid synthetic batch JSON") from exc
    _require(type(data) is dict and set(data) == BATCH_FIELDS, "batch fields invalid")
    _require(type(data["schema_version"]) is int and data["schema_version"] == SCHEMA and
             data["source"] == SOURCE and data["provenance"] == PROVENANCE,
             "batch provenance/schema invalid")
    ref = _utc(data["reference_utc"])
    _require(type(data["events"]) is list and 1 <= len(data["events"]) <= MAX_EVENTS_BATCH,
             "batch event count invalid")
    prev: datetime | None = None
    for event in data["events"]:
        at, _ = _validate_event(event, ref)
        _require(prev is None or at >= prev, "batch events out of order")
        prev = at
    return ref, data["events"]


def _apply(state: dict, event: dict) -> tuple[dict | None, bool]:
    """Apply a previously verified event; output simulated proposal (never delivery)."""
    kind, iid = event["event_type"], event["incident_id"]
    phase = state["phase"]
    if kind == "IncidentOpened":
        _require(state["incident_id"] is None and state["evidence_status"] != "Incomplete" and
                 phase in ("Unknown", "Healthy", "Recovered") and
                 (phase == "Unknown" or event["from_phase"] in (phase, "Healthy") and
                  (phase != "Healthy" or event["from_phase"] == "Healthy")),
                 "conflicting incident opened")
        state["incident_id"] = iid
        state["phase"] = event["to_phase"]
        state["evidence_status"] = "Complete"
        state["acknowledged_by"] = None
        state["acknowledged_at_utc"] = None
    elif kind == "IncidentEscalated":
        _require(phase == "Suspected" and state["incident_id"] == iid and
                 state["evidence_status"] == "Complete",
                 "escalation without matching suspected incident")
        state["phase"] = "Active"
        state["evidence_status"] = "Complete"
        # acknowledgement remains scoped to the incident; escalation is distinct.
    elif kind == "IncidentRecovered":
        _require(phase in ("Suspected", "Active") and state["incident_id"] == iid and
                 state["evidence_status"] == "Complete", "recovery without complete matching incident")
        state["phase"] = "Recovered"
        state["incident_id"] = None
        state["acknowledged_by"] = None
        state["acknowledged_at_utc"] = None
    elif kind == "EvidenceIncomplete":
        _require(event["from_phase"] == phase and (iid == state["incident_id"]),
                 "missing evidence wrong phase/incident")
        _require(state["evidence_status"] != "Incomplete", "duplicated evidence incomplete transition")
        state["evidence_status"] = "Incomplete"
    elif kind == "EvidenceRestored":
        _require(event["from_phase"] == phase and iid == state["incident_id"] and
                 state["evidence_status"] == "Incomplete", "evidence restored without missing evidence")
        state["evidence_status"] = "Complete"

    proposal = None
    if kind in INTENTS:
        key = f"{iid or 'none'}|{kind}"
        if key not in state["intent_keys"]:
            _require(len(state["intent_keys"]) < MAX_TRACKED, "intent dedup capacity exceeded")
            state["intent_keys"].append(key)
            state["proposal_count"] += 1
            proposal = {"source": SOURCE, "provenance": PROVENANCE,
                        "intent_key": key, "event_id": event["event_id"],
                        "incident_id": iid, "kind": INTENTS[kind],
                        "timestamp_utc": event["timestamp_utc"],
                        "simulation_only": True, "delivery_permitted": False}
    return proposal, kind == "EvidenceIncomplete"


def ingest_synthetic_batch(state: dict, raw: bytes) -> dict:
    """Pure all-or-nothing reducer of a bounded simulated v0.7 event batch.

    An event ID with matching content is a replay (no second proposal), while
    same ID/different content and unknown older events are rejected. In-memory
    fixed 256-record ceiling fails closed instead of silently forgetting IDs.
    """
    validate_state(state)
    reference, events = _parse_batch(raw)
    next_state = copy.deepcopy(state)
    seen = {x["event_id"]: x["sha256"] for x in next_state["seen_events"]}
    proposals = []
    duplicate = 0
    for event in events:
        stamp, digest = _validate_event(event, reference)
        eid = event["event_id"]
        if eid in seen:
            _require(seen[eid] == digest, "conflicting event ID replay")
            duplicate += 1
            continue
        last = next_state["last_timestamp_utc"]
        _require(last is None or stamp >= _utc(last), "out-of-order unseen event")
        _require(len(next_state["seen_events"]) < MAX_TRACKED, "event dedup capacity exceeded")
        proposal, _ = _apply(next_state, event)
        next_state["seen_events"].append({"event_id": eid, "sha256": digest})
        seen[eid] = digest
        next_state["last_timestamp_utc"] = _iso(stamp)
        if proposal is not None:
            proposals.append(proposal)
    validate_state(next_state)
    return {"source": SOURCE, "provenance": PROVENANCE, "simulation_only": True,
            "runtime_enabled": False, "live_probe_authorized": False,
            "task_creation_authorized": False, "notification_enabled": False,
            "delivery_permitted": False, "store_modified": False,
            "repair_action": "None", "processed_new_events": len(events) - duplicate,
            "suppressed_duplicate_events": duplicate, "proposed_intents": proposals,
            "state": next_state, "display_status": "Unknown" if next_state["evidence_status"] != "Complete" else next_state["phase"]}


def acknowledge_synthetic(state: dict, incident_id: str, actor: str, at_utc: str) -> dict:
    """Pure fake acknowledgement, never authenticates the operator or sends anything."""
    validate_state(state)
    _require(type(incident_id) is str and state["incident_id"] == incident_id and
             state["phase"] in ("Suspected", "Active"), "acknowledgement needs open matching incident")
    _require(type(actor) is str and actor.startswith("synthetic:") and
             11 <= len(actor) <= 64 and all(32 < ord(c) < 127 for c in actor),
             "operator must have bounded fake identity")
    at = _utc(at_utc)
    _require(state["last_timestamp_utc"] is not None and
             at >= _utc(state["last_timestamp_utc"]), "ack before observed event")
    previous = state["acknowledged_by"]
    _require(previous is None or
             (previous == actor and state["acknowledged_at_utc"] == _iso(at)),
             "conflicting acknowledgement")
    next_state = copy.deepcopy(state)
    changed = previous is None
    if changed:
        next_state["acknowledged_by"] = actor
        next_state["acknowledged_at_utc"] = _iso(at)
    validate_state(next_state)
    return {"source": SOURCE, "provenance": PROVENANCE, "simulation_only": True,
            "notification_enabled": False, "delivery_permitted": False,
            "runtime_enabled": False, "live_probe_authorized": False,
            "task_creation_authorized": False, "store_modified": False,
            "repair_action": "None", "changed": changed, "state": next_state}


def check_inert() -> dict:
    return {"source": SOURCE, "simulation_only": True,
            "runtime_enabled": False, "live_probe_authorized": False,
            "task_creation_authorized": False, "notification_enabled": False,
            "delivery_permitted": False, "store_modified": False,
            "repair_action": "None"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-inert", required=True, action="store_true")
    parser.parse_args(argv)
    print(json.dumps(check_inert(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
