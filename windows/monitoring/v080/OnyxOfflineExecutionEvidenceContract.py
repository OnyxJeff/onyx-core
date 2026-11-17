#!/usr/bin/env python3
"""R2 offline-only synthetic containment and evidence contract.

No subprocess, Win32 APIs, sockets, shell commands, file I/O, or scheduling.
Caller-provided fixtures cannot attest a real Windows Job Object, operating
system clock, source provenance, evidence integrity, or authorization.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

SCHEMA = 1
MAX_JSON_BYTES = 65536
CHANNELS = ("pc_usb_network", "pi_receiver", "gateway", "data_freshness")
PHASES = ("created_suspended", "job_attached", "resumed", "worker_ended", "tree_drained", "job_closed")
STATUSES = {"Healthy": "fixture_ok", "Suspect": "fixture_suspect", "Unknown": "fixture_unknown"}
STATUS_SOURCE = "OnyxV080R2SyntheticExecutionEvidence"


class OfflineEvidenceError(ValueError):
    """Invalid untrusted simulation input; never grants a capability."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise OfflineEvidenceError(reason)


def fields(value: Any, required: tuple[str, ...], label: str) -> dict:
    require(type(value) is dict and set(value) == set(required), f"{label}: unexpected/missing fields")
    return value


def integer(value: Any, low: int, high: int, label: str) -> int:
    require(type(value) is int and low <= value <= high, f"{label}: invalid integer")
    return value


def flag(value: Any, expected: bool, label: str) -> None:
    require(type(value) is bool and value is expected, f"{label}: unsafe flag")


def parse(raw: bytes) -> dict:
    require(type(raw) is bytes and 0 < len(raw) <= MAX_JSON_BYTES, "invalid JSON byte count")

    def unique(pairs: list[tuple[str, Any]]) -> dict:
        out: dict = {}
        for key, val in pairs:
            require(key not in out, "duplicate JSON key")
            out[key] = val
        return out

    def nonfinite(_: str) -> None:
        raise OfflineEvidenceError("nonfinite number")

    try:
        result = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique,
                            parse_constant=nonfinite)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise OfflineEvidenceError("invalid JSON payload") from exc
    require(type(result) is dict, "JSON root must be an object")
    return result


def utc(text: Any) -> datetime:
    require(type(text) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", text) is not None,
            "noncanonical UTC timestamp")
    try:
        result = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise OfflineEvidenceError("invalid UTC timestamp") from exc
    require(result.strftime("%Y-%m-%dT%H:%M:%SZ") == text, "noncanonical UTC encoding")
    return result


def check_policy(p: dict) -> None:
    fields(p, ("schema_version", "simulation_only", "fixture_provider", "worker_id",
               "deadline_ms", "max_stdout_bytes", "max_samples", "required_channels",
               "clock_skew_tolerance_ms", "live_probe_authorized", "task_creation_authorized",
               "repair_authorized", "notification_authorized"), "policy")
    integer(p["schema_version"], SCHEMA, SCHEMA, "schema_version")
    flag(p["simulation_only"], True, "policy.simulation_only")
    require(p["fixture_provider"] == "R2InMemoryFixtures", "untrusted fixture provider")
    require(p["worker_id"] == "r2-synthetic-observer-v1", "worker not allowlisted")
    integer(p["deadline_ms"], 90000, 90000, "deadline_ms")
    integer(p["max_stdout_bytes"], 8192, 8192, "max_stdout_bytes")
    integer(p["max_samples"], 4, 4, "max_samples")
    require(type(p["required_channels"]) is list and p["required_channels"] == list(CHANNELS),
            "channels differ from fixed synthetic contract")
    integer(p["clock_skew_tolerance_ms"], 2000, 2000, "clock_skew_tolerance_ms")
    for key in ("live_probe_authorized", "task_creation_authorized", "repair_authorized",
                "notification_authorized"):
        flag(p[key], False, "policy." + key)


def check_containment(p: dict, c: dict) -> tuple[int, int, str, datetime]:
    fields(c, ("schema_version", "simulation_only", "fixture_provider", "worker_id",
               "job", "phases", "outcome", "anchor_utc"), "containment")
    integer(c["schema_version"], SCHEMA, SCHEMA, "containment.schema_version")
    flag(c["simulation_only"], True, "containment.simulation_only")
    require(c["fixture_provider"] == "R2InMemoryFixtures" and c["worker_id"] == p["worker_id"],
            "containment fixture identity mismatch")
    anchor = utc(c["anchor_utc"])
    job = fields(c["job"], ("created_suspended", "assigned_before_resume", "kill_on_close",
                             "breakaway_allowed", "nested_processes_allowed",
                             "windows_job_attested", "live_process_started"), "job")
    for key in ("created_suspended", "assigned_before_resume", "kill_on_close"):
        flag(job[key], True, "job." + key)
    for key in ("breakaway_allowed", "nested_processes_allowed", "windows_job_attested",
                "live_process_started"):
        flag(job[key], False, "job." + key)
    phases = c["phases"]
    require(type(phases) is list and len(phases) == len(PHASES), "invalid containment timeline length")
    ticks = []
    for idx, phase in enumerate(phases):
        fields(phase, ("phase", "tick_ms"), "phase")
        require(phase["phase"] == PHASES[idx], "containment ordering violated")
        ticks.append(integer(phase["tick_ms"], 0, 1_000_000, "phase.tick_ms"))
    require(ticks[0] == 0 and all(a < b for a, b in zip(ticks, ticks[1:])),
            "monotonic process timeline invalid")
    # A synthetic record is not proof of actual Job Object assignment or cleanup.
    out = fields(c["outcome"], ("kind", "exit_code", "stdout_bytes", "stderr_bytes",
                                "descendants_remaining", "cleanup_completed", "job_closed"), "outcome")
    require(type(out["kind"]) is str and out["kind"] in ("success", "timed_out", "worker_failed"),
            "unrecognized outcome")
    integer(out["stdout_bytes"], 0, p["max_stdout_bytes"], "stdout_bytes")
    integer(out["stderr_bytes"], 0, p["max_stdout_bytes"], "stderr_bytes")
    integer(out["descendants_remaining"], 0, 0, "descendants_remaining")
    flag(out["cleanup_completed"], True, "cleanup_completed")
    flag(out["job_closed"], True, "job_closed")
    require(ticks[5] <= p["deadline_ms"] + 5000, "cleanup budget exceeded")
    if out["kind"] == "success":
        integer(out["exit_code"], 0, 0, "exit_code")
        require(ticks[3] < p["deadline_ms"], "success after deadline")
    elif out["kind"] == "timed_out":
        require(out["exit_code"] is None and ticks[3] == p["deadline_ms"],
                "timeout not enforced at deadline")
    else:
        require(type(out["exit_code"]) is int and 1 <= out["exit_code"] <= 255,
                "failed worker needs nonzero exit")
        require(ticks[3] < p["deadline_ms"], "failed worker beyond deadline")
    return ticks[3], ticks[5], out["kind"], anchor


def digest_sample(sample: dict) -> str:
    content = {key: sample[key] for key in ("channel", "status", "detail_code",
                                               "observed_at_utc", "tick_ms")}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("utf-8")).hexdigest()


def check_evidence(p: dict, e: dict, worker_end: int, close_tick: int,
                   outcome: str, anchor: datetime) -> str:
    fields(e, ("schema_version", "simulation_only", "fixture_provider", "origin", "read_only",
               "attempted_writes", "protected_store_accesses", "external_calls",
               "clock_confidence", "captured_at_utc", "captured_tick_ms", "samples"), "evidence")
    integer(e["schema_version"], SCHEMA, SCHEMA, "evidence.schema_version")
    flag(e["simulation_only"], True, "evidence.simulation_only")
    flag(e["read_only"], True, "evidence.read_only")
    require(e["fixture_provider"] == "R2InMemoryFixtures" and
            e["origin"] == "SyntheticFixtureOnly", "untrusted evidence origin")
    for key in ("attempted_writes", "protected_store_accesses", "external_calls"):
        integer(e[key], 0, 0, "evidence." + key)
    require(e["clock_confidence"] == "SyntheticUnattested", "fake host-clock attestation")
    captured = utc(e["captured_at_utc"])
    captured_tick = integer(e["captured_tick_ms"], 0, 1_000_000, "captured_tick_ms")
    require(worker_end <= captured_tick <= close_tick, "capture outside worker lifecycle")
    observed_elapsed_ms = int((captured - anchor).total_seconds() * 1000)
    require(abs(observed_elapsed_ms - captured_tick) <= p["clock_skew_tolerance_ms"],
            "synthetic wall/monotonic clock divergence")
    samples = e["samples"]
    require(type(samples) is list and len(samples) <= p["max_samples"], "sample count invalid")
    if outcome != "success":
        require(samples == [], "failed/timeout worker cannot claim evidence")
        return "Unknown"
    require(len(samples) == p["max_samples"], "missing channel: result Unknown/refused")
    verdicts: list[str] = []
    previous_tick = -1
    for index, sample in enumerate(samples):
        fields(sample, ("channel", "status", "detail_code", "observed_at_utc", "tick_ms",
                        "read_only", "provenance", "sha256"), "sample")
        require(sample["channel"] == CHANNELS[index], "duplicate/missing/reordered channel")
        require(type(sample["status"]) is str and sample["status"] in STATUSES,
                "invalid classification")
        require(sample["detail_code"] == STATUSES[sample["status"]], "detail contradicts status")
        flag(sample["read_only"], True, "sample.read_only")
        require(sample["provenance"] == "SyntheticFixtureOnly", "untrusted sample provenance")
        t = integer(sample["tick_ms"], 0, worker_end, "sample.tick_ms")
        require(previous_tick < t, "nonmonotonic or replayed sample")
        previous_tick = t
        wall = utc(sample["observed_at_utc"])
        wall_ms = int((wall - anchor).total_seconds() * 1000)
        require(abs(wall_ms - t) <= p["clock_skew_tolerance_ms"], "sample clock disagreement")
        require(0 <= captured_tick - t <= 120000, "sample future/stale")
        require(type(sample["sha256"]) is str and
                re.fullmatch(r"[0-9a-f]{64}", sample["sha256"]) is not None and
                sample["sha256"] == digest_sample(sample), "sample digest mismatch")
        verdicts.append(sample["status"])
    if "Unknown" in verdicts:
        return "Unknown"
    if "Suspect" in verdicts:
        return "SyntheticSuspect"
    return "SyntheticHealthy"


def assess_synthetic_cycle(policy_raw: bytes, containment_raw: bytes, evidence_raw: bytes) -> dict:
    """Pure JSON -> outcome. No true/false 'authorized' capability is returned."""
    p, c, e = parse(policy_raw), parse(containment_raw), parse(evidence_raw)
    check_policy(p)
    worker_end, close_tick, outcome, anchor = check_containment(p, c)
    classification = check_evidence(p, e, worker_end, close_tick, outcome, anchor)
    return {"schema_version": SCHEMA, "simulation_only": True, "classification": classification,
            "read_only": True, "runtime_enabled": False, "live_probe_authorized": False,
            "windows_job_attested": False, "clock_attested": False,
            "evidence_authentic": False, "task_creation_authorized": False,
            "notification_enabled": False, "delivery_permitted": False,
            "repair_action": "None", "store_modified": False}


def inert_status() -> dict:
    return {"source": STATUS_SOURCE, "simulation_only": True, "runtime_enabled": False,
            "live_probe_authorized": False, "task_creation_authorized": False,
            "notification_enabled": False, "delivery_permitted": False,
            "repair_action": "None", "store_modified": False, "read_only": True,
            "windows_job_attested": False, "clock_attested": False, "evidence_authentic": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="R2 inert-only synthetic containment contract")
    parser.add_argument("--check-inert", action="store_true")
    args = parser.parse_args()
    if not args.check_inert:
        parser.error("only --check-inert is supported; no fixture execution or live probe")
    print(json.dumps(inert_status(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
