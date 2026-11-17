#!/usr/bin/env python3
"""ONYX CORE v0.8.0 R3: isolated, TEMPORARY, SYNTHETIC SQLite replay journal.

NO production runtime, real evidence, live monitoring, network, diagnostics,
notification, enrollment, Scheduler access, migrations or repairs.  SQLite writes
are confined to caller-created empty `onyx-r3-*` directories directly below the
Python temp directory. This is a test harness, NOT a real Windows security boundary.

The checked-in M3 synthetic validator and pure in-memory transitions remain the
source for event rules. SQLite FULL synchronous atomic transactions preserve
validated simulated state, all seen event identities, and undelivered intent rows.
On any corruption, conflicting replay, unexpected path, or capacity failure:
refuse the whole operation, never silently evict the replay/deduplication ledger.
"""
from __future__ import annotations

import argparse
import importlib.util
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any, Iterator

_M3 = Path(__file__).resolve().with_name("OnyxOfflineAlertLifecycle.py")
_spec = importlib.util.spec_from_file_location("onyx_r3_pinned_m3", _M3)
if _spec is None or _spec.loader is None:
    raise ImportError("R3 requires reviewed local M3 validator")
m3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m3)

SOURCE = "OnyxV080R3SyntheticIncidentJournal"
PROVENANCE = "SyntheticTemporaryFixtureOnly"
DB_NAME = "synthetic-incident.sqlite3"
SCHEMA_VERSION = 1
APPLICATION_ID = 0x4F4E5938
MAX_EVENTS = 512
MAX_INTENTS = 512
MAX_DB_BYTES = 32 * 1024 * 1024
STATE_WINDOW = 24
ZERO_SHA = "0" * 64
NO_DELIVERY = "NotAttempted"


class OfflineJournalError(ValueError):
    """A fully refused synthetic transaction or invalid fixture state."""


class SyntheticFault(RuntimeError):
    """Only used to inject a controlled rollback/lost-response in offline tests."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise OfflineJournalError(message)


def _json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise OfflineJournalError("noncanonical JSON") from exc


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(_value: str) -> None:
    raise OfflineJournalError("nonfinite JSON")


def _decode(raw: str) -> Any:
    _require(type(raw) is str and len(raw) <= 65536, "invalid journal JSON")
    try:
        value = json.loads(raw, object_pairs_hook=_strict_pairs, parse_constant=_nonfinite)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise OfflineJournalError("invalid journal JSON") from exc
    _require(raw == _json(value), "journal JSON is not canonical")
    return value


def _fingerprint(state: dict) -> str:
    return _sha(_json(state))


def _fixture_db(directory: Path, *, must_exist: bool) -> Path:
    """Narrow **temporary synthetic test** scope; NOT a race-safe ACL check."""
    _require(isinstance(directory, Path),
             "explicit pathlib.Path fixture root required")
    base = Path(tempfile.gettempdir()).resolve(strict=True)
    _require(directory.is_absolute() and directory.parent == base and
             directory.name.startswith("onyx-r3-") and
             len(directory.name) <= 90 and directory.name != "onyx-r3-",
             "only direct onyx-r3-* test temp directories allowed")
    _require(directory.is_dir() and not directory.is_symlink(), "missing/redirected fixture root")
    if hasattr(directory, "is_junction"):
        _require(not directory.is_junction(), "junctioned fixture directory")
    _require(directory.resolve(strict=True) == directory,
             "redirected or noncanonical fixture directory")
    db = directory / DB_NAME
    if must_exist:
        _require(db.is_file() and not db.is_symlink(), "missing/redirected synthetic db")
        _require(not hasattr(db, "is_junction") or not db.is_junction(), "junctioned db")
        _require(db.resolve(strict=True) == db, "redirected database file")
        _require(db.stat().st_size <= MAX_DB_BYTES, "fixture database over budget")
        names = {item.name for item in directory.iterdir()}
        _require(names in ({DB_NAME}, {DB_NAME, DB_NAME + "-journal"}),
                 "unexpected fixture files")
        if DB_NAME + "-journal" in names:
            journal = directory / (DB_NAME + "-journal")
            _require(journal.is_file() and not journal.is_symlink() and
                     512 <= journal.stat().st_size <= MAX_DB_BYTES, "unsafe rollback journal")
            with journal.open("rb") as handle:
                magic = handle.read(8)
            _require(magic in (bytes(8), bytes.fromhex("d9d505f920a163d7")),
                     "invalid rollback journal header")
            _require(not hasattr(journal, "is_junction") or
                     not journal.is_junction(), "redirected rollback journal")
    else:
        _require(not any(directory.iterdir()), "fixture directory must start empty")
    return db


def _connect(db: Path, *, readonly: bool) -> sqlite3.Connection:
    try:
        # URI path is derived only from an already-validated temporary fixture.
        conn = sqlite3.connect(db.as_uri() + ("?mode=ro" if readonly else "?mode=rw"),
                               uri=True, timeout=0.25, isolation_level=None)
        conn.execute("PRAGMA foreign_keys=ON")
        if readonly:
            conn.execute("PRAGMA query_only=ON")
        else:
            conn.execute("PRAGMA synchronous=FULL")
            mode = conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            _require(mode.lower() == "delete", "rollback journal mode refused")
        return conn
    except (sqlite3.Error, OSError) as exc:
        raise OfflineJournalError("unable to open synthetic SQLite journal") from exc


def _schema(conn: sqlite3.Connection) -> None:
    _require(conn.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID,
             "wrong application ID")
    _require(conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION,
             "wrong journal version")
    integrity = conn.execute("PRAGMA integrity_check(1)").fetchone()
    _require(integrity == ("ok",), "SQLite integrity failure")
    objects = conn.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
    # sqlite_* autoindexes are intentionally excluded above.
    _require(objects == [("index", "idx_intents_seq"), ("table", "event_journal"),
                         ("table", "intent_journal"), ("table", "meta")], "unexpected journal schema")


def _new_state(state: dict) -> dict:
    next_state = copy.deepcopy(state)
    next_state["seen_events"] = next_state["seen_events"][-STATE_WINDOW:]
    next_state["intent_keys"] = next_state["intent_keys"][-STATE_WINDOW:]
    next_state["proposal_count"] = len(next_state["intent_keys"])
    m3.validate_state(next_state)
    return next_state


def _single_batch(reference: str, event: dict) -> bytes:
    return _json({"schema_version": 1, "source": m3.SOURCE,
                  "provenance": m3.PROVENANCE, "reference_utc": reference,
                  "events": [event]}).encode("utf-8")


def _step(state: dict, reference: str, event: dict,
          already_intents: set[str]) -> tuple[dict, dict | None]:
    try:
        next_result = m3.ingest_synthetic_batch(state, _single_batch(reference, event))
    except (m3.OfflineAlertError, ValueError) as exc:
        raise OfflineJournalError("M3 synthetic transition refused") from exc
    _require(next_result["processed_new_events"] == 1 and
             next_result["suppressed_duplicate_events"] == 0,
             "unexpected M3 processing result")
    proposals = next_result["proposed_intents"]
    _require(len(proposals) <= 1, "multiple proposals per synthetic event")
    intent = proposals[0] if proposals else None
    if intent is not None:
        _require(intent["simulation_only"] is True and
                 intent["delivery_permitted"] is False, "intent capabilities refused")
        if intent["intent_key"] in already_intents:
            intent = None
    return _new_state(next_result["state"]), intent


def _record_digest(seq: int, reference: str, event_json: str,
                   intent_json: str | None, before_sha: str, after_sha: str,
                   prev_sha: str) -> str:
    return _sha(_json({"seq": seq, "reference": reference,
                       "event_json": event_json, "intent_json": intent_json,
                       "before_sha": before_sha, "after_sha": after_sha,
                       "prev_sha": prev_sha}))


def _verify(conn: sqlite3.Connection) -> tuple[dict, int, str, dict[str, str], dict[str, tuple]]:
    _schema(conn)
    meta = conn.execute("SELECT next_seq, state_json, state_sha, head_sha FROM meta WHERE id=1").fetchall()
    _require(len(meta) == 1, "missing/multiple journal metadata")
    next_seq, state_text, state_digest, head_digest = meta[0]
    _require(type(next_seq) is int and 1 <= next_seq <= MAX_EVENTS + 1,
             "bad journal sequence")
    state = m3.initial_state()
    prev = ZERO_SHA
    seen: dict[str, str] = {}
    intents: dict[str, tuple] = {}
    rows = conn.execute("""SELECT seq, reference_utc, event_id, event_json, event_sha,
                        intent_json, before_sha, after_json, after_sha, prev_sha, record_sha
                        FROM event_journal ORDER BY seq""").fetchall()
    _require(len(rows) == next_seq - 1 and len(rows) <= MAX_EVENTS,
             "journal events/sequence mismatch")
    for expected_seq, row in enumerate(rows, 1):
        (seq, reference, eid, event_text, event_digest, intent_text, before_digest,
         after_text, after_digest, prev_digest, record_digest) = row
        _require(seq == expected_seq and type(reference) is str and
                 prev_digest == prev and before_digest == _fingerprint(state),
                 "discontinuous journal")
        event = _decode(event_text)
        _require(type(event) is dict and event.get("event_id") == eid and
                 eid not in seen and event_digest == _sha(event_text),
                 "invalid or duplicate event record")
        _require(type(reference) is str and len(reference) <= 64, "invalid reference clock")
        try:
            m3._validate_event(event, m3._utc(reference))
        except (m3.OfflineAlertError, ValueError) as exc:
            raise OfflineJournalError("historical event refused") from exc
        new_state, intent = _step(state, reference, event, set(intents))
        intent_expected = _json(intent) if intent is not None else None
        _require(intent_text == intent_expected and
                 after_text == _json(new_state) and
                 after_digest == _fingerprint(new_state) and
                 record_digest == _record_digest(seq, reference, event_text, intent_text,
                                                 before_digest, after_digest, prev_digest),
                 "journal state/intent/hash chain corrupted")
        if intent is not None:
            key = intent["intent_key"]
            intents[key] = (seq, eid, intent_text, _sha(intent_text), NO_DELIVERY)
        seen[eid] = event_digest
        state, prev = new_state, record_digest
    _require(state_text == _json(state) and state_digest == _fingerprint(state) and
             head_digest == prev, "metadata snapshot mismatch")
    journal_intents = conn.execute("""SELECT intent_key, event_seq, event_id, intent_json,
                                 intent_sha, delivery_status FROM intent_journal
                                 ORDER BY intent_key""").fetchall()
    _require(len(journal_intents) == len(intents) <= MAX_INTENTS and
             journal_intents == [(key, *intents[key]) for key in sorted(intents)],
             "intent ledger inconsistent")
    return state, next_seq, prev, seen, intents


@contextmanager
def _database(root: Path, *, readonly: bool) -> Iterator[sqlite3.Connection]:
    db = _fixture_db(root, must_exist=True)
    conn = _connect(db, readonly=readonly)
    try:
        yield conn
    except sqlite3.Error as exc:
        raise OfflineJournalError("SQLite journal operation failed") from exc
    finally:
        conn.close()


def initialize_synthetic_store(directory: Path) -> dict:
    """Initialize a *new empty* test-created temporary directory only."""
    db = _fixture_db(directory, must_exist=False)
    fd = os.open(db, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    conn = _connect(db, readonly=False)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""CREATE TABLE meta (
                    id INTEGER PRIMARY KEY CHECK(id=1), next_seq INTEGER NOT NULL,
                    state_json TEXT NOT NULL, state_sha TEXT NOT NULL, head_sha TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE event_journal (
                    seq INTEGER PRIMARY KEY, reference_utc TEXT NOT NULL,
                    event_id TEXT NOT NULL UNIQUE, event_json TEXT NOT NULL,
                    event_sha TEXT NOT NULL, intent_json TEXT,
                    before_sha TEXT NOT NULL, after_json TEXT NOT NULL,
                    after_sha TEXT NOT NULL, prev_sha TEXT NOT NULL,
                    record_sha TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE intent_journal (
                    intent_key TEXT PRIMARY KEY, event_seq INTEGER NOT NULL,
                    event_id TEXT NOT NULL, intent_json TEXT NOT NULL,
                    intent_sha TEXT NOT NULL,
                    delivery_status TEXT NOT NULL CHECK(delivery_status='NotAttempted'),
                    FOREIGN KEY(event_seq) REFERENCES event_journal(seq))""")
        conn.execute("CREATE INDEX idx_intents_seq ON intent_journal(event_seq)")
        initial = m3.initial_state()
        conn.execute("INSERT INTO meta VALUES (1,?,?,?,?)",
                     (1, _json(initial), _fingerprint(initial), ZERO_SHA))
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        conn.execute(f"PRAGMA application_id={APPLICATION_ID}")
        conn.execute("COMMIT")
    except (sqlite3.Error, Exception):
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        # Deliberately leave incomplete fixture for inspection; never auto-delete.
        raise
    finally:
        conn.close()
    with _database(directory, readonly=True) as verify:
        state, *_ = _verify(verify)
    out = _result(state, 0, 0, [])
    out["store_modified"] = True  # only newly created temporary synthetic fixture
    return out


def _result(state: dict, fresh: int, duplicate: int, intents: list[dict]) -> dict:
    return {"source": SOURCE, "provenance": PROVENANCE,
            "simulation_only": True, "runtime_enabled": False,
            "live_probe_authorized": False, "enrollment_authorized": False,
            "task_creation_authorized": False, "notification_enabled": False,
            "delivery_permitted": False, "store_modified": fresh > 0,
            "repair_action": "None", "writes_confined_to_temp_fixture": True,
            "processed_new_events": fresh, "suppressed_duplicate_events": duplicate,
            "proposed_intents_not_delivered": copy.deepcopy(intents),
            "display_status": "Unknown" if state["evidence_status"] != "Complete" else state["phase"],
            "state": copy.deepcopy(state)}


def recover_test_fixture_after_crash(directory: Path) -> dict:
    """Explicit, test-only SQLite rollback-journal recovery after abrupt worker exit.

    May write ONLY the previously verified temporary fixture SQLite database.
    This is NOT a production backup, history migration, or repair interface.
    """
    db = _fixture_db(directory, must_exist=True)
    _require((directory / (DB_NAME + "-journal")).exists(),
             "no interrupted fixture transaction to recover")
    with _database(directory, readonly=False) as conn:
        # Force a write transaction to make SQLite resolve any hot rollback journal.
        conn.execute("BEGIN IMMEDIATE")
        try:
            state, next_seq, _prev, _seen, intents = _verify(conn)
            conn.execute("UPDATE meta SET head_sha=head_sha WHERE id=1")
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    # A pre-commit crash may leave a *cold* SQLite rollback-journal file with
    # an all-zero magic header. SQLite recovers the transaction atomically but
    # need not unlink that harmless marker until a subsequent write. Never
    # delete or rename the file ourselves; keep the fixture fully isolated.
    out = _result(state, 0, 0, [])
    out["recovered_synthetic_rollback"] = True
    out["durable_event_count"] = next_seq - 1
    out["durable_undelivered_intent_count"] = len(intents)
    out["store_modified"] = True  # fixture-only SQLite rollback/recovery
    return out


def inspect_synthetic_store(directory: Path) -> dict:
    """Read only; verifies EVERY durable simulated transition before displaying."""
    _fixture_db(directory, must_exist=True)
    with _database(directory, readonly=True) as conn:
        state, next_seq, _head, _seen, intents = _verify(conn)
    out = _result(state, 0, 0, [])
    out["durable_event_count"] = next_seq - 1
    out["durable_undelivered_intent_count"] = len(intents)
    out["store_modified"] = False
    return out


def ingest_synthetic_batch(directory: Path, raw: bytes,
                           *, inject_fault: str | None = None) -> dict:
    """Atomic, deduplicated, restart-safe temporary synthetic event application.

    `inject_fault`: three explicit offline test fault sites. `before_commit`
    rolls back all writes; `after_commit` simulates lost confirmation, so retry
    is a duplicate without a new intent. `hard_exit_before_commit` terminates
    ONLY the explicitly spawned test process with code 71, leaving SQLite
    rollback for explicit test fixture recovery. No real delivery is attempted.
    """
    _require(inject_fault in (None, "before_commit", "after_commit",
                              "hard_exit_before_commit"), "invalid test fault")
    try:
        reference, events = m3._parse_batch(raw)
    except (m3.OfflineAlertError, ValueError) as exc:
        raise OfflineJournalError("invalid M3 synthetic batch") from exc
    # Use exact original reference timestamp representation for M3 replay.
    reference_utc = json.loads(raw.decode("utf-8", "strict"),
                               object_pairs_hook=m3._pairs_unique,
                               parse_constant=m3._no_nonfinite)["reference_utc"]
    _require(m3._utc(reference_utc) == reference, "reference mismatch")
    with _database(directory, readonly=False) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            state, next_seq, prev, seen, intents = _verify(conn)
            proposals: list[dict] = []
            duplicate = 0
            fresh = 0
            for event in events:
                event_text = _json(event)
                eid = event["event_id"]
                digest = _sha(event_text)
                if eid in seen:
                    _require(seen[eid] == digest, "conflicting event ID replay")
                    duplicate += 1
                    continue
                _require(next_seq <= MAX_EVENTS, "event retention limit exhausted (no eviction)")
                next_state, proposed = _step(state, reference_utc, event, set(intents))
                before_sha, after_sha = _fingerprint(state), _fingerprint(next_state)
                intent_text = _json(proposed) if proposed is not None else None
                record_sha = _record_digest(next_seq, reference_utc, event_text,
                                            intent_text, before_sha, after_sha, prev)
                conn.execute("INSERT INTO event_journal VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (next_seq, reference_utc, eid, event_text, digest, intent_text,
                              before_sha, _json(next_state), after_sha, prev, record_sha))
                if proposed is not None:
                    _require(len(intents) < MAX_INTENTS, "intent retention limit exhausted")
                    key = proposed["intent_key"]
                    conn.execute("INSERT INTO intent_journal VALUES (?,?,?,?,?,?)",
                                 (key, next_seq, eid, intent_text, _sha(intent_text), NO_DELIVERY))
                    intents[key] = (next_seq, eid, intent_text, _sha(intent_text), NO_DELIVERY)
                    proposals.append(proposed)
                seen[eid] = digest
                state, prev = next_state, record_sha
                fresh += 1
                next_seq += 1
            conn.execute("UPDATE meta SET next_seq=?, state_json=?, state_sha=?, head_sha=? WHERE id=1",
                         (next_seq, _json(state), _fingerprint(state), prev))
            if inject_fault == "hard_exit_before_commit":
                os._exit(71)  # offline fixture subprocess only
            if inject_fault == "before_commit":
                raise SyntheticFault("injected synthetic rollback before COMMIT")
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        if inject_fault == "after_commit":
            raise SyntheticFault("synthetic commit succeeded but response was lost")
    # Verify committed content and all durable IDs after closing writing connection.
    with _database(directory, readonly=True) as conn:
        verified, _, _, _, _ = _verify(conn)
    _require(verified == state, "post-commit verification mismatch")
    return _result(state, fresh, duplicate, proposals)


def check_inert() -> dict:
    return {"source": SOURCE, "provenance": PROVENANCE, "simulation_only": True,
            "runtime_enabled": False, "live_probe_authorized": False,
            "task_creation_authorized": False, "enrollment_authorized": False,
            "notification_enabled": False, "delivery_permitted": False,
            "store_modified": False, "real_store_authorized": False,
            "repair_action": "None", "temp_fixture_only": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-inert", action="store_true", required=True)
    parser.parse_args(argv)
    print(_json(check_inert()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
