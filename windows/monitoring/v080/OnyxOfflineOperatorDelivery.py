#!/usr/bin/env python3
"""R4 synthetic operator approval and delivery-decision ledger; NEVER live.

R3 is opened read-only and verified before every R4 operation.  R4's only
writes are its own caller-created empty onyx-r4-* temporary test directory.
Mock grants are test fixtures, NOT authenticated Windows identity, user consent
or actual delivery authorization. No notifications, transports, scheduler,
production history, enrollment, network probes or repairs exist here.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from typing import Any

_R3 = Path(__file__).resolve().with_name('OnyxOfflineIncidentJournal.py')
_spec = importlib.util.spec_from_file_location('onyx_r4_reviewed_r3', _R3)
if _spec is None or _spec.loader is None:
    raise ImportError('R4 requires reviewed local R3 synthetic journal')
r3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(r3)
m3 = r3.m3

SOURCE = 'OnyxV080R4SyntheticOperatorDelivery'
PROVENANCE = 'SyntheticTemporaryFixtureOnly'
GRANT_SOURCE = 'SyntheticGrantFixtureOnly'
DB_NAME = 'synthetic-operator.sqlite3'
SCHEMA_VERSION = 1
APPLICATION_ID = 0x4F4E5939
MAX_ACTIONS = 128
MAX_INTENTS = 128
MAX_BYTES = 16 * 1024 * 1024
MAX_REQUEST_BYTES = 16384
ZERO = '0' * 64
ACTIONS = frozenset(('Acknowledge', 'Plan', 'Suppress', 'Uncertain'))
DECISIONS = frozenset(('NotEvaluated', 'SimulatedWouldSend',
                       'SimulatedSuppressed', 'SimulatedUncertain'))
HEX24 = re.compile(r'^[0-9a-f]{24}$')
HEX64 = re.compile(r'^[0-9a-f]{64}$')
FIELDS = frozenset(('schema_version', 'source', 'provenance', 'simulation_only',
                    'request_id', 'action', 'at_utc', 'actor', 'incident_id',
                    'intent_key', 'reason', 'grant'))
GRANT_FIELDS = frozenset(('schema_version', 'source', 'simulation_only',
                          'actor', 'role', 'scopes', 'incident_id',
                          'issued_utc', 'expires_utc', 'revocation_generation',
                          'revoked', 'identity_authenticated_in_windows',
                          'revocation_authoritative', 'delivery_authorized'))


class OfflineOperatorError(ValueError):
    """Fail closed: no synthetic R4 state change is authorized."""


class SyntheticFault(RuntimeError):
    """Explicit test-only failure around transaction COMMIT."""


def _need(ok: bool, msg: str) -> None:
    if not ok:
        raise OfflineOperatorError(msg)


def _json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, OverflowError) as exc:
        raise OfflineOperatorError('not canonical JSON') from exc


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    obj = {}
    for key, value in pairs:
        _need(key not in obj, 'duplicate JSON key')
        obj[key] = value
    return obj


def _constant(_token: str) -> None:
    raise OfflineOperatorError('nonfinite JSON')


def _decode(text: str) -> Any:
    _need(type(text) is str and len(text.encode('utf-8')) <= MAX_REQUEST_BYTES,
          'bad input size')
    try:
        obj = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise OfflineOperatorError('invalid JSON') from exc
    return obj


def _iso(value: Any) -> datetime:
    _need(type(value) is str and len(value) == 27 and
          value.endswith('Z') and value[19] == '.', 'canonical UTC required')
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise OfflineOperatorError('invalid timestamp') from exc
    _need(dt.utcoffset() == timedelta(0) and
          dt.isoformat(timespec='microseconds').replace('+00:00', 'Z') == value,
          'noncanonical timestamp')
    return dt


def _dbpath(root: Path, *, exists: bool) -> Path:
    _need(isinstance(root, Path), 'test Path required')
    base = Path(tempfile.gettempdir()).resolve(strict=True)
    _need(root.is_absolute() and root.parent == base and
          root.name.startswith('onyx-r4-') and len(root.name) <= 90 and
          len(root.name) > len('onyx-r4-'), 'not an approved synthetic root')
    _need(root.is_dir() and not root.is_symlink() and
          (not hasattr(root, 'is_junction') or not root.is_junction()) and
          root.resolve(strict=True) == root, 'redirected temporary directory')
    db = root / DB_NAME
    if not exists:
        _need(not any(root.iterdir()), 'test fixture must be empty')
    else:
        _need(db.is_file() and not db.is_symlink() and
              (not hasattr(db, 'is_junction') or not db.is_junction()) and
              db.resolve(strict=True) == db and
              db.stat().st_size <= MAX_BYTES, 'invalid synthetic DB')
        _need({entry.name for entry in root.iterdir()} == {DB_NAME},
              'unexpected synthetic fixture file')
    return db


def _connect(db: Path, *, read_only: bool) -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(db.as_uri() + ('?mode=ro' if read_only else '?mode=rw'),
                               uri=True, isolation_level=None, timeout=0.25)
        if read_only:
            conn.execute('PRAGMA query_only=ON')
        else:
            conn.execute('PRAGMA synchronous=FULL')
            _need(conn.execute('PRAGMA journal_mode=DELETE').fetchone()[0] == 'delete',
                  'refuse other journal mode')
        return conn
    except sqlite3.Error as exc:
        raise OfflineOperatorError('SQLite connection refused') from exc


def _r3_snapshot(r3_root: Path) -> dict:
    """Read-only R3 verification. Never updates the R3 journal."""
    try:
        with r3._database(r3_root, readonly=True) as conn:
            state, seq, head, _events, intents = r3._verify(conn)
    except (r3.OfflineJournalError, sqlite3.Error, OSError) as exc:
        raise OfflineOperatorError('R3 synthetic fixture not verified') from exc
    _need(len(intents) <= MAX_INTENTS, 'too many R3 intents for R4 simulation')
    _need(type(head) is str and HEX64.fullmatch(head) is not None, 'bad R3 head')
    proposals = {}
    for key, record in intents.items():
        seq_intent, event_id, body_text, digest, status = record
        _need(status == r3.NO_DELIVERY and digest == _sha(body_text),
              'R3 intent may not claim delivery')
        proposal = r3._decode(body_text)
        _need(proposal['intent_key'] == key and
              proposal['delivery_permitted'] is False and
              proposal['simulation_only'] is True, 'R3 intent mismatch')
        proposals[key] = proposal
    return {'r3_head_sha': head, 'r3_event_count': seq - 1,
            'incident_state': state, 'intents': proposals}


def _initial(base: dict) -> dict:
    return {'schema_version': SCHEMA_VERSION, 'source': SOURCE,
            'provenance': PROVENANCE, 'r3_head_sha': base['r3_head_sha'],
            'r3_event_count': base['r3_event_count'],
            'incident_state': copy.deepcopy(base['incident_state']),
            'decisions': {key: 'NotEvaluated' for key in base['intents']},
            'last_request_utc': None}


def _request(raw: bytes) -> dict:
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_REQUEST_BYTES,
          'invalid raw synthetic request')
    try:
        obj = _decode(raw.decode('utf-8', 'strict'))
    except UnicodeError as exc:
        raise OfflineOperatorError('invalid UTF-8 request') from exc
    _need(type(obj) is dict and set(obj) == FIELDS, 'unknown request fields')
    rid = obj['request_id']
    _need(type(rid) is str and rid.startswith('req-') and
          HEX24.fullmatch(rid[4:]) is not None, 'bad synthetic request id')
    basis = {k: v for k, v in obj.items() if k != 'request_id'}
    _need(rid == 'req-' + _sha(_json(basis))[:24], 'request ID/binding mismatch')
    return obj


def _validate_grant(grant: dict, req: dict, at: datetime) -> None:
    _need(type(grant) is dict and set(grant) == GRANT_FIELDS, 'grant field mismatch')
    _need(type(grant['schema_version']) is int and grant['schema_version'] == 1 and
          grant['source'] == GRANT_SOURCE and grant['simulation_only'] is True and
          grant['identity_authenticated_in_windows'] is False and
          grant['revocation_authoritative'] is False and
          grant['delivery_authorized'] is False and
          grant['revoked'] is False, 'only mock grants without live authority')
    actor = req['actor']
    _need(type(actor) is str and actor.startswith('synthetic:') and
          11 <= len(actor) <= 64 and all(32 < ord(c) < 127 for c in actor) and
          grant['actor'] == actor, 'synthetic actor binding failed')
    _need(grant['role'] == 'Responder' and
          type(grant['scopes']) is list and
          all(type(x) is str and x in ACTIONS for x in grant['scopes']) and
          grant['scopes'] == sorted(set(grant['scopes'])) and
          req['action'] in grant['scopes'], 'synthetic role/scope denied')
    _need(grant['incident_id'] == req['incident_id'], 'grant incident mismatch')
    _need(type(grant['revocation_generation']) is int and
          1 <= grant['revocation_generation'] <= 1000000, 'bad simulated revocation generation')
    issued, expires = _iso(grant['issued_utc']), _iso(grant['expires_utc'])
    _need(issued <= at < expires and timedelta(0) < expires - issued <= timedelta(minutes=15),
          'expired/future synthetic grant')


def _apply(state: dict, base: dict, req: dict) -> dict:
    _need(type(req['schema_version']) is int and req['schema_version'] == 1 and
          req['source'] == SOURCE and req['provenance'] == PROVENANCE and
          req['simulation_only'] is True, 'live provenance forbidden')
    action = req['action']
    _need(type(action) is str and action in ACTIONS, 'unknown action')
    at = _iso(req['at_utc'])
    last = state['last_request_utc']
    _need(last is None or at >= _iso(last), 'new backdated synthetic action')
    _need(req['reason'] in ('OperatorReview', 'SimulatedOutcomeUnknown',
                             'OperatorSuppressed'), 'unknown synthetic reason')
    if action in ('Acknowledge', 'Plan'):
        _need(req['reason'] == 'OperatorReview', 'reason/action mismatch')
    elif action == 'Uncertain':
        _need(req['reason'] == 'SimulatedOutcomeUnknown', 'reason/action mismatch')
    else:
        _need(req['reason'] == 'OperatorSuppressed', 'reason/action mismatch')
    _need(type(req['incident_id']) is str and
          m3.INCIDENT_ID.fullmatch(req['incident_id']) is not None,
          'bad incident id')
    _validate_grant(req['grant'], req, at)
    next_state = copy.deepcopy(state)
    if action == 'Acknowledge':
        _need(req['intent_key'] is None, 'ack cannot specify intent')
        _need(state['incident_state']['evidence_status'] == 'Complete',
              'cannot acknowledge unknown/incomplete evidence')
        try:
            result = m3.acknowledge_synthetic(state['incident_state'], req['incident_id'],
                                              req['actor'], req['at_utc'])
        except m3.OfflineAlertError as exc:
            raise OfflineOperatorError('M3 acknowledgement refused') from exc
        _need(result['changed'] is True, 'duplicate ack requires original request replay')
        next_state['incident_state'] = result['state']
    else:
        key = req['intent_key']
        _need(type(key) is str and key in base['intents'] and
              base['intents'][key]['incident_id'] == req['incident_id'],
              'synthetic intent not in verified R3 ledger')
        prior = state['decisions'][key]
        if action == 'Plan':
            _need(prior == 'NotEvaluated', 'intent already decided')
            _need(state['incident_state']['evidence_status'] == 'Complete',
                  'incomplete evidence prevents planning')
            after = 'SimulatedWouldSend'
        elif action == 'Suppress':
            _need(prior in ('NotEvaluated', 'SimulatedWouldSend'),
                  'cannot overwrite terminal delivery uncertainty/suppression')
            after = 'SimulatedSuppressed'
        else:  # Uncertain: record simulated ambiguous outcome, never a real attempt
            _need(prior == 'SimulatedWouldSend', 'uncertain requires prior synthetic plan')
            after = 'SimulatedUncertain'
        next_state['decisions'][key] = after
    next_state['last_request_utc'] = req['at_utc']
    return next_state


def _record(seq: int, request_text: str, before: str, after: str, prev: str) -> str:
    return _sha(_json({'seq': seq, 'request': request_text,
                       'before': before, 'after': after, 'prev': prev}))


def _verify(conn: sqlite3.Connection, expected_base: dict) -> tuple[dict, int, str, dict[str, str]]:
    _need(conn.execute('PRAGMA application_id').fetchone()[0] == APPLICATION_ID and
          conn.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION,
          'R4 schema/application mismatch')
    _need(conn.execute('PRAGMA integrity_check(1)').fetchone() == ('ok',),
          'SQLite integrity refused')
    tables = conn.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
    _need(tables == [('table', 'action_journal'), ('table', 'meta')],
          'unexpected R4 journal schema')
    meta = conn.execute('SELECT next_seq,base_json,base_sha,state_json,state_sha,head_sha FROM meta WHERE id=1').fetchall()
    _need(len(meta) == 1, 'missing R4 metadata')
    seq_next, base_text, base_sha, state_text, state_sha, head_sha = meta[0]
    _need(type(seq_next) is int and 1 <= seq_next <= MAX_ACTIONS + 1 and
          base_text == _json(expected_base) and base_sha == _sha(base_text),
          'R3 baseline changed or R4 metadata corrupted')
    state = _initial(expected_base)
    head, seen = ZERO, {}
    rows = conn.execute('SELECT seq,request_id,request_json,request_sha,before_sha,after_json,after_sha,prev_sha,record_sha FROM action_journal ORDER BY seq').fetchall()
    _need(len(rows) == seq_next - 1, 'action record count mismatch')
    for i, row in enumerate(rows, 1):
        seq, rid, text, digest, before_sha, after_text, after_sha, prev, record_sha = row
        _need(seq == i and before_sha == _sha(_json(state)) and prev == head and
              text == _json(_decode(text)) and digest == _sha(text),
              'broken R4 chain')
        req = _request(text.encode('utf-8'))
        _need(req['request_id'] == rid and rid not in seen, 'duplicate/bad request')
        next_state = _apply(state, expected_base, req)
        _need(after_text == _json(next_state) and after_sha == _sha(after_text) and
              record_sha == _record(i, text, before_sha, after_sha, head),
              'R4 replay/state integrity mismatch')
        state, head = next_state, record_sha
        seen[rid] = digest
    _need(state_text == _json(state) and state_sha == _sha(state_text) and
          head_sha == head, 'R4 state snapshot tampered')
    return state, seq_next, head, seen


def _open_db(root: Path, *, readonly: bool) -> sqlite3.Connection:
    db = _dbpath(root, exists=True)
    return _connect(db, read_only=readonly)


def initialize_synthetic_store(root: Path, r3_root: Path) -> dict:
    """Explicitly create ONE new R4 temporary DB, snapshot verified R3 read-only."""
    base = _r3_snapshot(r3_root)
    db = _dbpath(root, exists=False)
    fd = os.open(db, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    conn = _connect(db, read_only=False)
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('CREATE TABLE meta (id INTEGER PRIMARY KEY CHECK(id=1), next_seq INTEGER NOT NULL, base_json TEXT NOT NULL, base_sha TEXT NOT NULL, state_json TEXT NOT NULL, state_sha TEXT NOT NULL, head_sha TEXT NOT NULL)')
        conn.execute('CREATE TABLE action_journal (seq INTEGER PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, request_json TEXT NOT NULL, request_sha TEXT NOT NULL, before_sha TEXT NOT NULL, after_json TEXT NOT NULL, after_sha TEXT NOT NULL, prev_sha TEXT NOT NULL, record_sha TEXT NOT NULL)')
        initial = _initial(base)
        conn.execute('INSERT INTO meta VALUES (1,?,?,?,?,?,?)',
                     (1, _json(base), _sha(_json(base)), _json(initial), _sha(_json(initial)), ZERO))
        conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        conn.execute(f'PRAGMA application_id={APPLICATION_ID}')
        conn.execute('COMMIT')
    except BaseException:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        raise
    finally:
        conn.close()
    return inspect_synthetic_store(root, r3_root)


def _output(state: dict, count: int, duplicate: bool, updated: bool) -> dict:
    return {'source': SOURCE, 'provenance': PROVENANCE, 'simulation_only': True,
            'runtime_enabled': False, 'live_probe_authorized': False,
            'enrollment_authorized': False, 'task_creation_authorized': False,
            'notification_enabled': False, 'delivery_permitted': False,
            'real_store_authorized': False, 'identity_authenticated_in_windows': False,
            'revocation_authoritative': False, 'store_modified': updated,
            'repair_action': 'None', 'synthetic_action_count': count,
            'duplicate_request_suppressed': duplicate,
            'state': copy.deepcopy(state), 'transport_calls': 0}


def inspect_synthetic_store(root: Path, r3_root: Path) -> dict:
    base = _r3_snapshot(r3_root)
    conn = _open_db(root, readonly=True)
    try:
        state, seq, head, seen = _verify(conn, base)
    except sqlite3.Error as exc:
        raise OfflineOperatorError('R4 inspection refused') from exc
    finally:
        conn.close()
    return _output(state, seq-1, False, False)


def apply_synthetic_request(root: Path, r3_root: Path, raw: bytes,
                            *, inject_fault: str | None = None) -> dict:
    """Atomic fake decision; never calls transports or modifies R3/production."""
    _need(inject_fault in (None, 'before_commit', 'after_commit'), 'bad synthetic fault')
    req = _request(raw)
    base = _r3_snapshot(r3_root)
    conn = _open_db(root, readonly=False)
    duplicate = False
    updated = False
    try:
        conn.execute('BEGIN IMMEDIATE')
        state, next_seq, head, seen = _verify(conn, base)
        text = _json(req)
        rid, digest = req['request_id'], _sha(text)
        if rid in seen:
            _need(seen[rid] == digest, 'request identity conflict')
            duplicate = True
        else:
            _need(next_seq <= MAX_ACTIONS, 'action retention exhausted: no eviction')
            new_state = _apply(state, base, req)
            before_sha = _sha(_json(state))
            after_text, after_sha = _json(new_state), _sha(_json(new_state))
            record_sha = _record(next_seq, text, before_sha, after_sha, head)
            conn.execute('INSERT INTO action_journal VALUES (?,?,?,?,?,?,?,?,?)',
                         (next_seq, rid, text, digest, before_sha, after_text,
                          after_sha, head, record_sha))
            conn.execute('UPDATE meta SET next_seq=?,state_json=?,state_sha=?,head_sha=? WHERE id=1',
                         (next_seq+1, after_text, after_sha, record_sha))
            state = new_state
            updated = True
        if inject_fault == 'before_commit':
            raise SyntheticFault('synthetic precommit rollback')
        conn.execute('COMMIT')
        if inject_fault == 'after_commit':
            raise SyntheticFault('synthetic postcommit response lost')
    except BaseException:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        raise
    finally:
        conn.close()
    verified = inspect_synthetic_store(root, r3_root)
    _need(verified['state'] == state, 'post-commit state discrepancy')
    verified['duplicate_request_suppressed'] = duplicate
    verified['store_modified'] = updated
    return verified


def check_inert() -> dict:
    return {'source': SOURCE, 'provenance': PROVENANCE, 'simulation_only': True,
            'runtime_enabled': False, 'live_probe_authorized': False,
            'enrollment_authorized': False, 'task_creation_authorized': False,
            'notification_enabled': False, 'delivery_permitted': False,
            'real_store_authorized': False, 'identity_authenticated_in_windows': False,
            'revocation_authoritative': False, 'store_modified': False,
            'task_created': False, 'transport_calls': 0, 'repair_action': 'None',
            'temp_fixture_only': True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-inert', action='store_true', required=True)
    parser.parse_args(argv)
    print(_json(check_inert()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
