#!/usr/bin/env python3
"""ONYX CORE v0.7.0 M2: atomic, bounded incident snapshot + event journal.

Offline library only. Never executes probes, repairs, scheduled tasks, or SSH.
A single checksummed JSON document contains BOTH state and transition events;
there is no unsafe two-file commit window. Only callers choose a storage path.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import OnyxIncidentState as reducer

SCHEMA = 1
MAX_EVENTS = 128
MAX_RECORD_BYTES = 131072
MAX_READ_BYTES = 131073
MAX_INT = 2**63 - 1
EVENT_TYPES = frozenset(("IncidentOpened", "IncidentEscalated", "IncidentRecovered",
                         "EvidenceIncomplete", "EvidenceRestored"))
HEX64 = re.compile(r"^[a-f0-9]{64}$")
EVENT_ID = re.compile(r"^evt-[a-f0-9]{24}$")
FIELDS = frozenset(("schema_version", "generation", "state", "events", "events_discarded", "integrity_sha256"))
EVENT_FIELDS = frozenset(("schema_version", "event_id", "event_type", "timestamp_utc",
                          "incident_id", "from_phase", "to_phase", "connectivity_decision", "repair_action"))


class IncidentStoreError(RuntimeError):
    """The store could not safely complete an operation."""


class CorruptIncidentStore(IncidentStoreError):
    """Existing persisted data is invalid. NEVER reset or overwrite it."""


class IncidentStoreBusy(IncidentStoreError):
    """A concurrent writer already owns the local OS-level lock."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(body: dict) -> str:
    return hashlib.sha256(_canonical(body)).hexdigest()


def _pairs_unique(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise CorruptIncidentStore("duplicate JSON object field")
        result[key] = value
    return result


def _no_special(value: str) -> None:
    raise CorruptIncidentStore("non-finite JSON value: " + value)


def _path(path: str | Path) -> Path:
    p = Path(path)
    if p.name != "incident-state.json":
        raise IncidentStoreError("only an incident-state.json document is supported")
    if not p.is_absolute():
        raise IncidentStoreError("storage path must be absolute")
    if p.is_symlink():
        raise IncidentStoreError("refusing symbolic link as incident store")
    return p


def _blank() -> dict:
    body = {
        "schema_version": SCHEMA,
        "generation": 0,
        "state": reducer.initial_state(),
        "events": [],
        "events_discarded": 0,
    }
    return {**body, "integrity_sha256": _digest(body)}


def _validate_event(event: Any) -> None:
    if type(event) is not dict or set(event) != EVENT_FIELDS:
        raise CorruptIncidentStore("event fields missing or unexpected")
    if type(event["schema_version"]) is not int or event["schema_version"] != SCHEMA:
        raise CorruptIncidentStore("event schema mismatch")
    if event["event_type"] not in EVENT_TYPES:
        raise CorruptIncidentStore("unknown event type")
    if event["from_phase"] not in reducer.PHASES or event["to_phase"] not in reducer.PHASES:
        raise CorruptIncidentStore("event phase invalid")
    if event["connectivity_decision"] not in reducer.DECISIONS:
        raise CorruptIncidentStore("event connectivity decision invalid")
    if event["repair_action"] != "None":
        raise CorruptIncidentStore("event repair action forbidden")
    if type(event["event_id"]) is not str or not EVENT_ID.fullmatch(event["event_id"]):
        raise CorruptIncidentStore("invalid event id")
    if event["incident_id"] is not None:
        if type(event["incident_id"]) is not str or not event["incident_id"].startswith("inc-") or len(event["incident_id"]) > 64:
            raise CorruptIncidentStore("invalid event incident id")
    try:
        timestamp = reducer._utc(event["timestamp_utc"], "event timestamp")
    except reducer.InvalidIncidentInput as exc:
        raise CorruptIncidentStore("invalid event timestamp") from exc
    basis = "|".join((event["event_type"], event["timestamp_utc"], event["incident_id"] or "none"))
    expected = "evt-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    if event["event_id"] != expected:
        raise CorruptIncidentStore("event id does not match immutable event contents")
    return timestamp


def _validate_record(record: Any) -> None:
    if type(record) is not dict or set(record) != FIELDS:
        raise CorruptIncidentStore("storage schema fields mismatch")
    if type(record["schema_version"]) is not int or record["schema_version"] != SCHEMA:
        raise CorruptIncidentStore("unsupported storage schema")
    if type(record["generation"]) is not int or not 0 <= record["generation"] <= MAX_INT:
        raise CorruptIncidentStore("invalid storage generation")
    if type(record["events_discarded"]) is not int or not 0 <= record["events_discarded"] <= MAX_INT:
        raise CorruptIncidentStore("invalid discarded event count")
    if type(record["integrity_sha256"]) is not str or not HEX64.fullmatch(record["integrity_sha256"]):
        raise CorruptIncidentStore("invalid storage integrity digest")
    body = {key: value for key, value in record.items() if key != "integrity_sha256"}
    try:
        actual = _digest(body)
    except (ValueError, TypeError, OverflowError) as exc:
        raise CorruptIncidentStore("unserializable store") from exc
    if actual != record["integrity_sha256"]:
        raise CorruptIncidentStore("storage integrity checksum mismatch")
    try:
        reducer._check_state(record["state"])
    except reducer.InvalidIncidentInput as exc:
        raise CorruptIncidentStore("invalid incident lifecycle state") from exc
    if record["state"]["processed_cycles"] != record["generation"]:
        raise CorruptIncidentStore("storage generation and state cycle count diverge")
    events = record["events"]
    if type(events) is not list or len(events) > MAX_EVENTS:
        raise CorruptIncidentStore("event journal exceeds bounds or is malformed")
    if record["events_discarded"] + len(events) > 3 * record["generation"]:
        raise CorruptIncidentStore("event count cannot exceed processed cycle bounds")
    prior = None
    ids = set()
    for event in events:
        timestamp = _validate_event(event)
        if prior is not None and timestamp < prior:
            raise CorruptIncidentStore("event journal out of chronological order")
        prior = timestamp
        if event["event_id"] in ids:
            raise CorruptIncidentStore("duplicate event id in journal")
        ids.add(event["event_id"])
    if prior is not None:
        latest = record["state"].get("last_cycle_finished_utc")
        if latest is None or prior > reducer._utc(latest, "last cycle timestamp"):
            raise CorruptIncidentStore("event newer than persisted incident state")


def load_store(path: str | Path) -> dict:
    """Return a deep copy of the on-disk transaction; never mutate or repair it.

    Missing file means new initialization, while *existing* damaged data fails closed.
    The caller must retain operator-level history/backups to detect external deletions.
    """
    p = _path(path)
    try:
        with p.open("rb") as handle:
            raw = handle.read(MAX_READ_BYTES)
    except FileNotFoundError:
        return _blank()
    if len(raw) > MAX_RECORD_BYTES:
        raise CorruptIncidentStore("storage document exceeds byte limit")
    try:
        record = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs_unique,
                            parse_constant=_no_special)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise CorruptIncidentStore("invalid incident store JSON") from exc
    _validate_record(record)
    return copy.deepcopy(record)


@contextmanager
def _writer_lock(path: Path):
    """Cross-process nonblocking OS file lock; released by OS on crash."""
    lock_path = path.with_name(path.name + ".lock")
    handle = lock_path.open("a+b")
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise IncidentStoreBusy("incident writer is already active") from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise IncidentStoreBusy("incident writer is already active") from exc
        acquired = True
        yield
    finally:
        if acquired:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _atomic_replace(path: Path, contents: bytes) -> None:
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".onyx-incident-", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "wb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        # Directory metadata sync on POSIX; unavailable for directory handles on Windows.
        if os.name != "nt":
            try:
                parent_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
            except OSError:
                pass  # Already replaced; leave result idempotently retryable.
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def advance_store(path: str | Path, cycle: dict) -> dict:
    """Atomically apply one M1 cycle to state AND its event journal.

    Returns {'state', 'events', 'replayed', 'generation', 'journal_count', 'events_discarded'}.
    Replay after a crash is a no-op. Never overwrites corrupted persisted data.
    Only incident-state.json is supported; a later guarded adapter selects its directory.
    """
    p = _path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _writer_lock(p):
        existing = load_store(p)
        new_state, new_events = reducer.apply_cycle(existing["state"], cycle)
        if new_state == existing["state"] and not new_events:
            return {"state": copy.deepcopy(existing["state"]), "events": [],
                    "replayed": True, "generation": existing["generation"],
                    "journal_count": len(existing["events"]),
                    "events_discarded": existing["events_discarded"]}
        journal = existing["events"] + new_events
        ids = [event["event_id"] for event in journal]
        if len(ids) != len(set(ids)):
            raise CorruptIncidentStore("journal collision while appending events")
        discarded = existing["events_discarded"] + max(0, len(journal) - MAX_EVENTS)
        journal = journal[-MAX_EVENTS:]
        body = {"schema_version": SCHEMA, "generation": new_state["processed_cycles"],
                "state": new_state, "events": journal, "events_discarded": discarded}
        record = {**body, "integrity_sha256": _digest(body)}
        _validate_record(record)
        data = _canonical(record) + b"\n"
        if len(data) > MAX_RECORD_BYTES:
            raise IncidentStoreError("storage record exceeds maximum size; no changes written")
        _atomic_replace(p, data)
        return {"state": copy.deepcopy(new_state), "events": copy.deepcopy(new_events),
                "replayed": False, "generation": new_state["processed_cycles"],
                "journal_count": len(journal), "events_discarded": discarded}
