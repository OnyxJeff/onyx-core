#!/usr/bin/env python3
"""ONYX CORE v0.8.0 M2C: strictly offline, in-memory synthetic evidence integration.

This is not a launcher, monitoring agent, enrollment tool or state writer.
Never emits a schema-compatible v0.7 diagnostic cycle outside the internal
reducer call: its 'LiveRestrictedDiagnostic' schema discriminator is required
by v0.7's PURE reducer and does NOT describe the synthetic input's provenance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

# Python -I omits adjacent imports: load only the fixed sibling modules.
_FIXED_MODULE_DIR = str(Path(__file__).resolve().parent)
if _FIXED_MODULE_DIR not in sys.path:
    sys.path.insert(0, _FIXED_MODULE_DIR)
import OnyxOfflineAuthorization as auth
import OnyxOfflineSupervisor as supervisor

SCHEMA = 1
MAX_EVIDENCE_BYTES = 32768
MAX_SAMPLES = 12
MAX_AGE_SECONDS = 300
WINDOWS = frozenset(("WindowsPathReady", "WindowsPathUnverified"))
PI = frozenset(("PiInternetVerified", "ExternalTcpUnverified", "PiUnreachable"))
FLAGS = ("history_error_present", "windows_error_present", "pi_error_present")
SAMPLE_KEYS = frozenset(("finished_utc", "windows_classification", "pi_classification", *FLAGS))
EVIDENCE_KEYS = frozenset(("schema_version", "provenance", "reference_utc", "samples"))


class OfflineEvidenceError(ValueError):
    """Untrusted or inconsistent mock evidence refused without state changes."""


def _require(ok: bool, why: str) -> None:
    if not ok:
        raise OfflineEvidenceError(why)


def _pair_unique(pairs: list[tuple[str, Any]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        _require(key not in out, "duplicate JSON property")
        out[key] = value
    return out


def _reject_nonfinite(_: str):
    raise OfflineEvidenceError("nonfinite JSON refused")


def _utc(value: Any) -> datetime:
    _require(type(value) is str and 20 <= len(value) <= 40,
             "synthetic timestamp must be bounded offset-aware ISO 8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OfflineEvidenceError("invalid synthetic timestamp") from exc
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None,
             "timezone required")
    return parsed.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_evidence(raw: bytes) -> tuple[datetime, list[dict]]:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_EVIDENCE_BYTES,
             "missing or oversized mock evidence")
    try:
        data = json.loads(raw.decode("utf-8", "strict"),
                          object_pairs_hook=_pair_unique, parse_constant=_reject_nonfinite)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise OfflineEvidenceError("invalid mock evidence JSON") from exc
    _require(type(data) is dict and set(data) == EVIDENCE_KEYS,
             "unexpected mock evidence schema")
    _require(type(data["schema_version"]) is int and data["schema_version"] == SCHEMA,
             "unsupported mock schema")
    _require(data["provenance"] == "SyntheticFixtureOnly",
             "live or unidentified provenance refused")
    samples = data["samples"]
    _require(type(samples) is list and 1 <= len(samples) <= MAX_SAMPLES,
             "mock sample count out of bounds")
    reference = _utc(data["reference_utc"])
    before: datetime | None = None
    checked = []
    for sample in samples:
        _require(type(sample) is dict and set(sample) == SAMPLE_KEYS,
                 "missing or extra mock sample fields")
        at = _utc(sample["finished_utc"])
        _require(reference - timedelta(seconds=MAX_AGE_SECONDS) <= at <=
                 reference + timedelta(seconds=5), "stale or future mock evidence")
        _require(before is None or at > before, "duplicate or unordered mock timestamp")
        before = at
        _require(type(sample["windows_classification"]) is str and
                 sample["windows_classification"] in WINDOWS, "bad synthetic Windows class")
        _require(type(sample["pi_classification"]) is str and
                 sample["pi_classification"] in PI, "bad synthetic Pi class")
        for key in FLAGS:
            _require(type(sample[key]) is bool, "mock error flags must be boolean")
        checked.append({**sample, "_when": at})
    return reference, checked


def _load_v070_reducer():
    """Load only the existing pure in-repository v0.7 reducer; no store module."""
    path = Path(__file__).resolve().parent.parent / "OnyxIncidentState.py"
    _require(path.is_file() and not path.is_symlink() and
             not bool(getattr(path, "is_junction", lambda: False)()),
             "fixed v0.7 pure reducer unavailable or redirected")
    spec = importlib.util.spec_from_file_location("onyx_m2c_v070_pure_reducer", path)
    _require(spec is not None and spec.loader is not None,
             "pure reducer cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("initial_state", "apply_cycle", "display_status", "_check_cycle"):
        _require(callable(getattr(module, name, None)), "pure reducer contract missing")
    return module


def _cycle(sample: dict, suspect_count: int, observation_count: int) -> dict:
    at: datetime = sample["_when"]
    incomplete = any(sample[key] for key in FLAGS)
    if incomplete:
        decision = "Investigate"
    elif sample["windows_classification"] == "WindowsPathReady" and sample["pi_classification"] == "PiInternetVerified":
        decision = "Healthy"
    elif sample["windows_classification"] == "WindowsPathReady" and sample["pi_classification"] == "ExternalTcpUnverified":
        decision = "PossibleIcsFailure" if suspect_count >= 3 else "WaitAndRetry"
    else:
        decision = "Investigate"
    return {
        "schema_version": 1,
        # Pure v0.7 reducer's required schema literal, NOT actual source provenance.
        # Never exposed in an M2C result or written to a live incident store.
        "source": "LiveRestrictedDiagnostic",
        "cycle_started_utc": _iso(at - timedelta(seconds=1)),
        "cycle_finished_utc": _iso(at),
        "duration_ms": 1000,
        "cycle_status": "EvidenceIncomplete" if incomplete else "Complete",
        "connectivity_decision": decision,
        "decision_reason": "synthetic-v080-m2c-data-only",
        "windows_classification": sample["windows_classification"],
        "pi_classification": sample["pi_classification"],
        "observation_count": observation_count,
        "consecutive_suspected": suspect_count,
        "history_error_present": sample["history_error_present"],
        "windows_error_present": sample["windows_error_present"],
        "pi_error_present": sample["pi_error_present"],
        "repair_action": "None",
    }


def run_offline_evidence(auth_fixture: Path, supervisor_fixture: Path,
                         evidence_raw: bytes, *, worker_mode: str = "ok") -> dict:
    """Read synthetic authorization, run fixed mock worker, reduce *in memory*.

    No cycle store, collector, network, SSH, Task Scheduler, enrollment or repair.
    The result is never evidence of real Windows/Pi health or real consent.
    """
    # Validate ALL untrusted data before starting even an inert child fixture.
    _, samples = _parse_evidence(evidence_raw)
    decision = auth.assess_temporary_fixture(auth_fixture)
    _require(decision.get("source") == "OnyxV080M2BOfflineAuthorization" and
             decision.get("simulation_only") is True and
             decision.get("simulated_preflight") == "EligibleDataOnly" and
             decision.get("identity_authenticated_in_windows") is False and
             decision.get("windows_acls_verified") is False and
             decision.get("revocation_authoritative") is False and
             decision.get("runtime_enabled") is False and
             decision.get("live_probe_authorized") is False and
             decision.get("task_creation_authorized") is False and
             decision.get("store_modified") is False and
             decision.get("repair_action") == "None",
             "simulated authorization boundary refused")
    # Do not import any v0.7 release runner or state-writing code.
    reducer = _load_v070_reducer()
    result = supervisor.run_synthetic_cycle(supervisor_fixture, worker_mode, 1.5)
    _require(result.get("source") == "OnyxV080M2SyntheticSupervisor" and
             result.get("synthetic_only") is True and
             result.get("connectivity_assessed") is False and
             result.get("runtime_enabled") is False and
             result.get("live_probe_authorized") is False and
             result.get("task_creation_authorized") is False and
             result.get("store_modified") is False and
             result.get("repair_action") == "None", "mock supervision contract failed")
    base = {
        "source": "OnyxV080M2COfflineEvidence",
        "provenance": "SyntheticFixtureOnly",
        "simulation_only": True,
        "authorization_status": "EligibleDataOnly",
        "supervision_status": result["supervision_status"],
        "connectivity_assessed": False,
        "real_incident_confirmed": False,
        "runtime_enabled": False,
        "live_probe_authorized": False,
        "task_creation_authorized": False,
        "store_modified": False,
        "repair_action": "None",
    }
    # A failed/timeout fixture invalidates ALL evidence in this attempted run.
    if result["supervision_status"] != "Completed":
        return {**base, "evidence_status": "Unavailable",
                "display_status": "Unknown", "simulated_phase": "Unknown",
                "processed_cycles": 0, "event_types": []}
    state = reducer.initial_state()
    events: list[str] = []
    suspect_count = 0
    last_suspect: datetime | None = None
    for index, sample in enumerate(samples, 1):
        if (not any(sample[key] for key in FLAGS) and
            sample["windows_classification"] == "WindowsPathReady" and
            sample["pi_classification"] == "ExternalTcpUnverified"):
            when = sample["_when"]
            if last_suspect is None or (when - last_suspect).total_seconds() <= MAX_AGE_SECONDS:
                suspect_count += 1
            else:
                suspect_count = 1
            last_suspect = when
        else:
            suspect_count = 0
            last_suspect = None
        cycle = _cycle(sample, suspect_count, index)
        try:
            state, transition = reducer.apply_cycle(state, cycle)
        except Exception as exc:
            # Never return a partially advanced state on malformed/rejected cycle.
            raise OfflineEvidenceError("pure v0.7 reducer rejected synthetic cycle") from exc
        events.extend(event["event_type"] for event in transition)
    return {**base, "evidence_status": state["evidence_status"],
            "display_status": reducer.display_status(state),
            "simulated_phase": state["phase"],
            "processed_cycles": state["processed_cycles"],
            "event_types": events}


def check_inert() -> dict:
    return {"source": "OnyxV080M2COfflineEvidence", "simulation_only": True,
            "runtime_enabled": False, "live_probe_authorized": False,
            "task_creation_authorized": False, "store_modified": False,
            "repair_action": "None"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-inert", action="store_true", required=True)
    parser.parse_args(argv)
    print(json.dumps(check_inert(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
