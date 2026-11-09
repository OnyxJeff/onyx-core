#!/usr/bin/env python3
"""ONYX CORE v0.7.0 M2: pure, fail-closed incident lifecycle reducer.

NO side effects: no files, networking, subprocesses, repair or scheduling.
Persistence, serialization and operational supervision are separate milestones.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

SCHEMA = 1
DECISIONS = frozenset(("Healthy", "WaitAndRetry", "Investigate", "PossibleIcsFailure"))
PHASES = frozenset(("Unknown", "Healthy", "Suspected", "Active", "Recovered"))
EVIDENCE = frozenset(("Unknown", "Complete", "Incomplete"))
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RECOVERY_SPACING_SECONDS = 30
RECOVERY_MAX_SPACING_SECONDS = 300


class InvalidIncidentInput(ValueError):
    """Malformed, contradictory, stale, or unsafe data; never overwrite state."""


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise InvalidIncidentInput(field + " must be an offset-aware ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidIncidentInput(field + " is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidIncidentInput(field + " must include UTC offset")
    return parsed.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _int(value: Any, field: str, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise InvalidIncidentInput(field + " is outside permitted integer bounds")


def _is_string(value: Any, field: str, maxlen: int = 256) -> None:
    if not isinstance(value, str) or not value or len(value) > maxlen:
        raise InvalidIncidentInput(field + " must be a bounded, nonempty string")


def _check_cycle(cycle: Any) -> tuple[datetime, str]:
    if type(cycle) is not dict:
        raise InvalidIncidentInput("cycle must be an object")
    if cycle.get("schema_version") != SCHEMA or type(cycle.get("schema_version")) is not int:
        raise InvalidIncidentInput("unexpected cycle schema")
    if cycle.get("source") != "LiveRestrictedDiagnostic":
        raise InvalidIncidentInput("unapproved cycle source")
    if cycle.get("repair_action") != "None":
        raise InvalidIncidentInput("any repair action is forbidden")
    started = _utc(cycle.get("cycle_started_utc"), "cycle_started_utc")
    ended = _utc(cycle.get("cycle_finished_utc"), "cycle_finished_utc")
    if ended < started:
        raise InvalidIncidentInput("cycle clock went backward")
    _int(cycle.get("duration_ms"), "duration_ms", 0, 600000)
    if abs((ended - started).total_seconds() * 1000 - cycle["duration_ms"]) > 2:
        raise InvalidIncidentInput("cycle duration disagrees with timestamps")
    if cycle.get("cycle_status") not in ("Complete", "EvidenceIncomplete"):
        raise InvalidIncidentInput("unknown cycle status")
    if cycle.get("connectivity_decision") not in DECISIONS:
        raise InvalidIncidentInput("unknown connectivity decision")
    for field in ("decision_reason", "windows_classification", "pi_classification"):
        _is_string(cycle.get(field), field, 512)
    _int(cycle.get("observation_count"), "observation_count", 1, 12)
    _int(cycle.get("consecutive_suspected"), "consecutive_suspected", 0, 12)
    for field in ("history_error_present", "windows_error_present", "pi_error_present"):
        if type(cycle.get(field)) is not bool:
            raise InvalidIncidentInput(field + " must be boolean")
    partial = any(cycle[f] for f in ("history_error_present", "windows_error_present", "pi_error_present"))
    if partial != (cycle["cycle_status"] == "EvidenceIncomplete"):
        raise InvalidIncidentInput("cycle completeness conflicts with error flags")
    decision = cycle["connectivity_decision"]
    if partial and decision != "Investigate":
        raise InvalidIncidentInput("missing evidence cannot imply healthy or corroborated failure")
    if decision == "Healthy":
        if (cycle["windows_classification"] != "WindowsPathReady" or
                cycle["pi_classification"] != "PiInternetVerified" or
                cycle["consecutive_suspected"] != 0):
            raise InvalidIncidentInput("healthy requires consistent Windows and Pi evidence")
    if cycle["consecutive_suspected"] > cycle["observation_count"]:
        raise InvalidIncidentInput("suspect count exceeds observation count")
    if decision == "PossibleIcsFailure":
        if (cycle["consecutive_suspected"] < 3 or
                cycle["windows_classification"] != "WindowsPathReady" or
                cycle["pi_classification"] != "ExternalTcpUnverified"):
            raise InvalidIncidentInput("corroborated failure requires three suspects and expected endpoints")
    # All fields in the M1 summary are JSON primitives; refuse nonserializable extras.
    try:
        encoded = json.dumps(cycle, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise InvalidIncidentInput("cycle contains non-JSON data") from exc
    if len(encoded.encode("utf-8")) > 16384:
        raise InvalidIncidentInput("cycle summary is oversized")
    return ended, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def initial_state() -> dict:
    return {
        "schema_version": SCHEMA,
        "phase": "Unknown",
        "evidence_status": "Unknown",
        "incident": None,
        "last_cycle_finished_utc": None,
        "last_cycle_digest": None,
        "processed_cycles": 0,
        "last_recovered_utc": None,
    }


def _check_state(state: Any) -> None:
    if type(state) is not dict or state.get("schema_version") != SCHEMA or type(state.get("schema_version")) is not int:
        raise InvalidIncidentInput("invalid persisted state schema")
    if set(state) != set(initial_state()):
        raise InvalidIncidentInput("unknown or missing persisted state fields")
    if state.get("phase") not in PHASES or state.get("evidence_status") not in EVIDENCE:
        raise InvalidIncidentInput("invalid persisted state phase or evidence status")
    _int(state.get("processed_cycles"), "processed_cycles", 0, 2**63 - 1)
    last = state.get("last_cycle_finished_utc")
    if (last is None) != (state.get("last_cycle_digest") is None):
        raise InvalidIncidentInput("persisted cycle identity is incomplete")
    if last is not None:
        _utc(last, "last_cycle_finished_utc")
        if not isinstance(state["last_cycle_digest"], str) or not HEX64.fullmatch(state["last_cycle_digest"]):
            raise InvalidIncidentInput("invalid cycle digest")
        if state["processed_cycles"] == 0:
            raise InvalidIncidentInput("nonempty history has zero cycles")
    elif state["processed_cycles"] != 0 or state["phase"] != "Unknown" or state["evidence_status"] != "Unknown":
        raise InvalidIncidentInput("empty state is inconsistent")
    if state.get("last_recovered_utc") is not None:
        _utc(state["last_recovered_utc"], "last_recovered_utc")
    incident = state.get("incident")
    if incident is None:
        if state["phase"] in ("Suspected", "Active"):
            raise InvalidIncidentInput("missing open incident")
    else:
        if type(incident) is not dict or state["phase"] not in ("Suspected", "Active"):
            raise InvalidIncidentInput("open incident must match phase")
        if set(incident) != {"id", "status", "opened_utc", "last_problem_utc", "activated_utc", "recovery_candidate_utc"}:
            raise InvalidIncidentInput("unknown or missing incident fields")
        if incident.get("status") != state["phase"]:
            raise InvalidIncidentInput("incident status mismatch")
        _is_string(incident.get("id"), "incident.id", 64)
        for key in ("opened_utc", "last_problem_utc"):
            _utc(incident.get(key), "incident." + key)
        if _utc(incident["last_problem_utc"], "last_problem_utc") < _utc(incident["opened_utc"], "opened_utc"):
            raise InvalidIncidentInput("incident time order invalid")
        activated = incident.get("activated_utc")
        candidate = incident.get("recovery_candidate_utc")
        if state["phase"] == "Active" and activated is None:
            raise InvalidIncidentInput("active incident lacks activation time")
        if state["phase"] == "Suspected" and (activated is not None or candidate is not None):
            raise InvalidIncidentInput("suspected incident has active-only fields")
        if activated is not None:
            _utc(activated, "incident.activated_utc")
        if candidate is not None:
            _utc(candidate, "incident.recovery_candidate_utc")
        if last is not None and _utc(incident["opened_utc"], "incident.opened_utc") > _utc(last, "last_cycle_finished_utc"):
            raise InvalidIncidentInput("incident opened after last cycle")


def _event(kind: str, when: str, incident_id: str | None, old: str, new: str, decision: str) -> dict:
    basis = "|".join((kind, when, incident_id or "none"))
    return {
        "schema_version": SCHEMA,
        "event_id": "evt-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24],
        "event_type": kind,
        "timestamp_utc": when,
        "incident_id": incident_id,
        "from_phase": old,
        "to_phase": new,
        "connectivity_decision": decision,
        "repair_action": "None",
    }


def display_status(state: dict) -> str:
    """Presentation status: never claim Healthy while current evidence is missing."""
    _check_state(state)
    if state["evidence_status"] != "Complete":
        return "Unknown"
    return state["phase"]


def apply_cycle(state: dict, cycle: dict) -> tuple[dict, list[dict]]:
    """Deterministically reduce one M1 cycle into a new state and transition events.

    Replay is idempotent, stale/conflicting cycles fail closed, input is never mutated.
    An Active incident needs two independent Healthy cycles separated 30..300s.
    """
    _check_state(state)
    finished, digest = _check_cycle(cycle)
    previous_time = state.get("last_cycle_finished_utc")
    if previous_time is not None:
        old = _utc(previous_time, "last_cycle_finished_utc")
        if finished < old:
            raise InvalidIncidentInput("out-of-order cycle; state left untouched")
        if finished == old:
            if digest == state["last_cycle_digest"]:
                return copy.deepcopy(state), []
            raise InvalidIncidentInput("conflicting replay timestamp")

    result = copy.deepcopy(state)
    timestamp = _iso(finished)
    result["last_cycle_finished_utc"] = timestamp
    result["last_cycle_digest"] = digest
    result["processed_cycles"] += 1
    events: list[dict] = []
    decision = cycle["connectivity_decision"]
    original_evidence = result["evidence_status"]

    if cycle["cycle_status"] == "EvidenceIncomplete":
        if original_evidence != "Incomplete":
            events.append(_event("EvidenceIncomplete", timestamp,
                                 result["incident"]["id"] if result["incident"] else None,
                                 result["phase"], result["phase"], decision))
        result["evidence_status"] = "Incomplete"
        # Never satisfy an ongoing recovery across missing evidence.
        if result["incident"] is not None:
            result["incident"]["recovery_candidate_utc"] = None
        return result, events

    result["evidence_status"] = "Complete"
    if original_evidence == "Incomplete":
        events.append(_event("EvidenceRestored", timestamp,
                             result["incident"]["id"] if result["incident"] else None,
                             result["phase"], result["phase"], decision))

    prior = result["phase"]
    incident = result["incident"]
    if decision == "Healthy":
        if incident is None:
            result["phase"] = "Healthy"
        elif incident["status"] == "Suspected":
            result["incident"] = None
            result["phase"] = "Recovered"
            result["last_recovered_utc"] = timestamp
            events.append(_event("IncidentRecovered", timestamp, incident["id"], prior, "Recovered", decision))
        else:
            candidate = incident["recovery_candidate_utc"]
            if candidate is None:
                incident["recovery_candidate_utc"] = timestamp
            else:
                spacing = (finished - _utc(candidate, "recovery_candidate_utc")).total_seconds()
                if RECOVERY_SPACING_SECONDS <= spacing <= RECOVERY_MAX_SPACING_SECONDS:
                    result["incident"] = None
                    result["phase"] = "Recovered"
                    result["last_recovered_utc"] = timestamp
                    events.append(_event("IncidentRecovered", timestamp, incident["id"], prior, "Recovered", decision))
                elif spacing > RECOVERY_MAX_SPACING_SECONDS:
                    incident["recovery_candidate_utc"] = timestamp
        return result, events

    # Complete, but not healthy. An ICS suspicion is a diagnosis, not proven root cause.
    corroborated = decision == "PossibleIcsFailure"
    if incident is None:
        incident_id = "inc-" + hashlib.sha256(("onyx-v070|" + timestamp).encode("utf-8")).hexdigest()[:24]
        phase = "Active" if corroborated else "Suspected"
        result["incident"] = {
            "id": incident_id,
            "status": phase,
            "opened_utc": timestamp,
            "last_problem_utc": timestamp,
            "activated_utc": timestamp if corroborated else None,
            "recovery_candidate_utc": None,
        }
        result["phase"] = phase
        events.append(_event("IncidentOpened", timestamp, incident_id, prior, phase, decision))
    else:
        incident["last_problem_utc"] = timestamp
        incident["recovery_candidate_utc"] = None
        if corroborated and incident["status"] == "Suspected":
            incident["status"] = "Active"
            incident["activated_utc"] = timestamp
            result["phase"] = "Active"
            events.append(_event("IncidentEscalated", timestamp, incident["id"], prior, "Active", decision))
    return result, events
