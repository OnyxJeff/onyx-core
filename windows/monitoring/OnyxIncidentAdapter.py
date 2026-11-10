#!/usr/bin/env python3
"""ONYX CORE v0.7.0 M2: synthetic-only cycle -> durable incident adapter.

This module has NO live/probe/repair entry point. The CLI runs in a throwaway
TemporaryDirectory and NEVER writes the configured development incident store.
The small apply_cycle_to_store library is tested against isolated temp paths.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

import OnyxIncidentState as reducer
import OnyxIncidentStore as storage

SCHEMA = 1
MAX_SEQUENCE_BYTES = 262144
MAX_CYCLES = 64
APPROVED_ROOT = Path(r"D:\github_repos\onyx-core-v070")
CHECKPOINT_E = "88eec87391d078215046687a51131a4cc248cb7f"


class IncidentAdapterError(ValueError):
    """Invalid simulation inputs or an unauthorized launch context."""


def apply_cycle_to_store(cycle: dict, store_file: str | Path) -> dict:
    """Integrate the existing reducer + atomic store for one supplied cycle.

    The caller chooses a sandboxed path. No probes or implicit defaults exist.
    On invalid input, the existing store refuses the transaction unchanged.
    """
    outcome = storage.advance_store(store_file, cycle)
    state = outcome["state"]
    return {
        "schema_version": SCHEMA,
        "source": "SyntheticIncidentIntegration",
        "cycle_finished_utc": state["last_cycle_finished_utc"],
        "phase": state["phase"],
        "display_status": reducer.display_status(state),
        "evidence_status": state["evidence_status"],
        "incident_id": state["incident"]["id"] if state["incident"] else None,
        "generation": outcome["generation"],
        "journal_count": outcome["journal_count"],
        "events_discarded": outcome["events_discarded"],
        "replayed": outcome["replayed"],
        "transition_events": [
            {"event_id": event["event_id"], "event_type": event["event_type"]}
            for event in outcome["events"]
        ],
        "repair_action": "None",
    }


def simulate_cycles(cycles: list[dict], temporary_store: str | Path) -> dict:
    """Apply a synthetic sequence to an explicit *test* path, no clock or I/O probes.

    This is an importable test helper. Callers MUST supply a temporary path; the
    CLI never exposes this argument or allows a permanent state-file selection.
    """
    if type(cycles) is not list or not 1 <= len(cycles) <= MAX_CYCLES:
        raise IncidentAdapterError("expected 1..64 synthetic cycles")
    if not all(type(cycle) is dict for cycle in cycles):
        raise IncidentAdapterError("each synthetic cycle must be an object")

    results = []
    for cycle in cycles:
        results.append(apply_cycle_to_store(cycle, temporary_store))
    journal = storage.load_store(temporary_store)
    if journal["generation"] != results[-1]["generation"]:
        raise IncidentAdapterError("persistent generation differs from last cycle")
    return {
        "schema_version": SCHEMA,
        "source": "SyntheticIncidentIntegration",
        "cycle_count_supplied": len(cycles),
        "cycles_committed": journal["generation"],
        "cycles_replayed": sum(bool(result["replayed"]) for result in results),
        "transition_events_emitted": sum(len(result["transition_events"]) for result in results),
        "final": results[-1],
        "journal_count": len(journal["events"]),
        "repair_action": "None",
    }


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise IncidentAdapterError("duplicate JSON property")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise IncidentAdapterError("non-finite JSON value is forbidden")


def read_sequence(file: str | Path) -> list[dict]:
    """Parse bounded JSON from disk without evaluating or echoing input fields."""
    source = Path(file)
    with source.open("rb") as stream:
        raw = stream.read(MAX_SEQUENCE_BYTES + 1)
    if len(raw) > MAX_SEQUENCE_BYTES:
        raise IncidentAdapterError("synthetic fixture exceeds 256 KiB")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
                              parse_constant=_reject_constant)
    except (UnicodeError, ValueError) as exc:
        raise IncidentAdapterError("invalid simulation JSON") from exc
    if (type(document) is not dict or set(document) != {"schema_version", "cycles"}
            or type(document["schema_version"]) is not int
            or document["schema_version"] != SCHEMA):
        raise IncidentAdapterError("invalid synthetic sequence schema")
    if type(document["cycles"]) is not list or not 1 <= len(document["cycles"]) <= MAX_CYCLES:
        raise IncidentAdapterError("synthetic sequence must contain 1..64 cycles")
    if any(type(cycle) is not dict for cycle in document["cycles"]):
        raise IncidentAdapterError("synthetic cycles must be JSON objects")
    return document["cycles"]


def _git(root: Path, *args: str) -> None:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            text=True, timeout=8, check=False)
    if result.returncode != 0:
        raise IncidentAdapterError("development lineage verification failed")


def assert_approved_development_cli() -> None:
    """No code at CLI entry point runs outside the pinned isolated dev worktree."""
    if os.name != "nt":
        raise IncidentAdapterError("command-line simulation requires Windows SQUALL")
    root = Path(__file__).resolve().parents[2]
    if str(root).casefold() != str(APPROVED_ROOT).casefold():
        raise IncidentAdapterError("adapter must run inside onyx-core-v070 worktree")
    result = subprocess.run(["git", "-C", str(root), "branch", "--show-current"],
                            capture_output=True, text=True, timeout=8, check=False)
    if result.returncode != 0 or result.stdout.strip() != "feature/v0.7.0-monitoring":
        raise IncidentAdapterError("wrong development branch")
    _git(root, "merge-base", "--is-ancestor", CHECKPOINT_E, "HEAD")

    # The only approved config points at the isolated development state, which
    # the simulation STILL does not write. Validate to detect changed profiles.
    from OnyxMonitorConfig import ConfigError, load_config
    try:
        config = load_config(root / "windows" / "monitoring" / "monitoring.development.example.json")
    except (ConfigError, ValueError, UnicodeError) as exc:
        raise IncidentAdapterError("unsafe monitoring configuration") from exc
    if config["profile"] != "development" or config["repair_action"] != "None":
        raise IncidentAdapterError("unsafe monitoring configuration")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulate", metavar="SEQUENCE_JSON", type=Path, required=True,
                        help="Synthetic cycle sequence; never starts live monitoring")
    args = parser.parse_args(argv)
    try:
        assert_approved_development_cli()
        cycles = read_sequence(args.simulate)
        with tempfile.TemporaryDirectory(prefix="onyx-v070-m2-sim-") as scratch:
            outcome = simulate_cycles(cycles, Path(scratch) / "incident-state.json")
        print(json.dumps(outcome, sort_keys=True, separators=(",", ":")))
        return 0
    except (IncidentAdapterError, reducer.InvalidIncidentInput,
            storage.IncidentStoreError, OSError, subprocess.TimeoutExpired) as exc:
        print("SIMULATION REFUSED: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
