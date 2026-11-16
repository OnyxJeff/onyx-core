#!/usr/bin/env python3
"""ONYX CORE v0.8 M3: explicit live monitoring with durable incident history.

Only this entry point writes v0.8 SQLite incident history in an explicitly
selected isolated store. It reuses M2's real, sequential, read-only checks
and its exclusive Windows mutex.
It never repairs connectivity, creates tasks, or sends notifications.
"""
from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
import json
import os
import uuid
from pathlib import Path
import sqlite3
import sys
from typing import Any, Callable

import OnyxContinuousMonitor as m2

SCHEMA_VERSION = 1
MAX_HISTORY_RESULTS = 20
CHECK_RETENTION = 30  # Days of individual checks; incident records are retained.
VALID_STATUSES = frozenset(('Healthy', 'Degraded', 'Unknown'))
VALID_ISSUES = frozenset(('WindowsDiagnosticUnavailable', 'PiDiagnosticUnavailable'))
STORAGE_PROFILE_ENV = 'ONYXCORE_V080_STORAGE_PROFILE'
STORAGE_DIRS = {
    'development': 'OnyxCore-v080-Development',
    'release': 'OnyxCore-v080-Release',
}


class HistoryError(RuntimeError):
    """A requested journal operation cannot be safely completed."""


class CommitOutcomeUnknown(HistoryError):
    """A write may have committed; do not retry with a fresh operation ID."""


# Additive schema object: created only inside the already-authorized incident
# transaction. Both new and pre-existing v1 stores use the same contract.
RECEIPT_DDL = """CREATE TABLE IF NOT EXISTS cycle_receipts (
    operation_id TEXT PRIMARY KEY NOT NULL,
    sample_sha256 TEXT NOT NULL,
    outcome_json TEXT NOT NULL
)"""


def _operation_id(value: str) -> str:
    if type(value) is not str or len(value) != 36:
        raise HistoryError('invalid cycle operation ID')
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise HistoryError('invalid cycle operation ID') from exc
    if parsed.version not in (4, 5) or str(parsed) != value:
        raise HistoryError('invalid cycle operation ID')
    return value


def _sample_sha256(sample: dict) -> str:
    return hashlib.sha256(json.dumps(sample, sort_keys=True,
        separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()


# Stable, namespace-scoped identity for an already validated observation.
# This is an idempotency key, NOT a consent credential or unpredictability token.
_OBSERVATION_NAMESPACE = uuid.UUID('d19f29eb-25a0-4328-b531-a623bf74e50e')


def cycle_operation_id(result: dict) -> str:
    """Reproducible parent-only ID for an identical validated observation.

    A new M1 probe has a fresh checked_at_utc timestamp. Replaying exactly the
    same observation, including after process restart, has the same ID.
    """
    return str(uuid.uuid5(_OBSERVATION_NAMESPACE,
                          _sample_sha256(_validated_sample(result))))


def _decode_receipt(row, sample: dict | None = None) -> dict:
    if sample is not None and row['sample_sha256'] != _sample_sha256(sample):
        raise HistoryError('operation ID reused with different observation')
    try:
        outcome = json.loads(row['outcome_json'])
    except (TypeError, ValueError) as exc:
        raise HistoryError('invalid durable cycle receipt') from exc
    if (type(outcome) is not dict or
            set(outcome) != {'event', 'incident_id', 'status', 'at', 'reason'} or
            outcome['event'] not in {'NoIncident','Opened','Recovered','Changed','Ongoing'} or
            (outcome['incident_id'] is not None and
             (type(outcome['incident_id']) is not int or outcome['incident_id'] <= 0)) or
            outcome['status'] not in VALID_STATUSES or
            type(outcome['at']) is not str or type(outcome['reason']) is not str):
        raise HistoryError('invalid durable cycle receipt')
    if sample is not None and (outcome['at'] != sample['at'] or
            outcome['status'] != sample['status'] or
            outcome['reason'] != sample['reason']):
        raise HistoryError('contradictory durable cycle receipt')
    return outcome


def _lookup_receipt(conn: sqlite3.Connection, operation_id: str,
                    sample: dict | None = None) -> dict | None:
    present = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cycle_receipts'").fetchone()
    if present is None:
        return None
    row = conn.execute('SELECT sample_sha256, outcome_json FROM cycle_receipts WHERE operation_id=?',
                       (operation_id,)).fetchone()
    return None if row is None else _decode_receipt(row, sample)


def reconcile_cycle(path: Path, operation_id: str, result: dict | None = None) -> dict | None:
    """Read-only, non-mutating verification of an explicitly identified attempt.

    An absent receipt is not permission to retry while another writer may still
    be active. The caller must hold the existing exclusive parent lock and reuse
    the SAME operation_id and observation for any permitted replay.
    """
    key = _operation_id(operation_id)
    sample = None if result is None else _validated_sample(result)
    conn = _connect(path, write=False)
    if conn is None:
        return None
    try:
        return _lookup_receipt(conn, key, sample)
    except (sqlite3.Error, OSError) as exc:
        raise HistoryError('cycle receipt verification unavailable') from exc
    finally:
        conn.close()


def storage_profile() -> str:
    """Fail closed on an invalid explicit selection; no filesystem access."""
    profile = os.environ.get(STORAGE_PROFILE_ENV, 'development')
    if profile not in STORAGE_DIRS:
        raise HistoryError('invalid v0.8 storage profile')
    return profile


def history_path() -> Path:
    """Shared, profile-scoped M3/M4/M5 journal path; never creates files.

    The release profile opts in to a *storage path only*. M1's independent
    development-only live-execution guard remains in force.
    """
    profile = storage_profile()
    root = os.environ.get('LOCALAPPDATA')
    if not root or not Path(root).is_absolute():
        raise HistoryError('LOCALAPPDATA unavailable for incident history')
    base = Path(root)
    if base.is_symlink() or (hasattr(base, 'is_junction') and base.is_junction()):
        raise HistoryError('redirected LOCALAPPDATA path refused')
    return base / STORAGE_DIRS[profile] / 'Monitoring' / 'incident-history.sqlite3'


def _check_storage_path(path: Path, *, create: bool) -> None:
    if not path.is_absolute() or path.name != 'incident-history.sqlite3':
        raise HistoryError('unexpected incident history path')
    for part in (path.parent.parent, path.parent, path):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise HistoryError('redirected incident history path refused')
    if path.exists() and not path.is_file():
        raise HistoryError('incident history path is not a regular file')
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)


def _utc(value: str) -> datetime:
    if type(value) is not str or len(value) > 48:
        raise HistoryError('invalid UTC timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError('timestamp is naive')
        result = parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError) as exc:
        raise HistoryError('invalid UTC timestamp') from exc
    return result


def _validated_sample(result: dict) -> dict:
    """Write allowlisted M2 classifications only, not probe output or secrets."""
    if type(result) is not dict or result.get('source') != 'OnyxV080ForegroundMonitor':
        raise HistoryError('unexpected monitoring source')
    if (result.get('mode') != 'OptInForegroundReadOnly' or
            result.get('repair_action') != 'None' or
            result.get('incident_history_written') is not False or
            result.get('notification_sent') is not False or
            result.get('scheduler_enabled') is not False):
        raise HistoryError('monitor result does not meet read-only policy')
    status = result.get('status')
    if status not in VALID_STATUSES:
        raise HistoryError('invalid monitoring status')
    windows = result.get('windows_classification')
    pi = result.get('pi_classification')
    if windows not in m2.m1.WIN_TYPES | {'WindowsProbeUnavailable'}:
        raise HistoryError('invalid Windows classification')
    if pi not in m2.m1.PI_TYPES | {'PiProbeUnavailable'}:
        raise HistoryError('invalid Pi classification')
    expected_status, expected_reason = m2.m1.classify(
        {'classification': windows}, {'classification': pi})
    if status != expected_status or result.get('reason') != expected_reason:
        raise HistoryError('contradictory diagnostic status or reason')
    issues = result.get('issues')
    if (type(issues) is not list or len(issues) > 2 or
            any(x not in VALID_ISSUES for x in issues) or len(set(issues)) != len(issues)):
        raise HistoryError('invalid missing-evidence summary')
    expected_issues = set()
    if windows == 'WindowsProbeUnavailable':
        expected_issues.add('WindowsDiagnosticUnavailable')
    if pi == 'PiProbeUnavailable':
        expected_issues.add('PiDiagnosticUnavailable')
    if set(issues) != expected_issues:
        raise HistoryError('missing-evidence flags contradict probe classifications')
    if type(result.get('cycle')) is not int or result['cycle'] <= 0:
        raise HistoryError('invalid cycle number')
    if type(result.get('duration_ms')) is not int or result['duration_ms'] < 0:
        raise HistoryError('invalid check duration')
    at = _utc(result.get('checked_at_utc'))
    return {
        'at': at.isoformat(), 'status': status, 'reason': expected_reason,
        'windows': windows, 'pi': pi, 'issues': ','.join(sorted(issues)),
        'duration_ms': result['duration_ms'], 'cycle': result['cycle'],
    }


SCHEMA = '''
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at_utc TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('Healthy', 'Degraded', 'Unknown')),
    reason TEXT NOT NULL,
    windows_classification TEXT NOT NULL,
    pi_classification TEXT NOT NULL,
    missing_evidence TEXT NOT NULL,
    duration_ms INTEGER NOT NULL CHECK(duration_ms >= 0)
);
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at_utc TEXT NOT NULL,
    last_observed_at_utc TEXT NOT NULL,
    resolved_at_utc TEXT,
    initial_status TEXT NOT NULL CHECK(initial_status IN ('Degraded', 'Unknown')),
    last_status TEXT NOT NULL CHECK(last_status IN ('Degraded', 'Unknown')),
    initial_reason TEXT NOT NULL,
    last_reason TEXT NOT NULL,
    windows_classification TEXT NOT NULL,
    pi_classification TEXT NOT NULL,
    check_count INTEGER NOT NULL CHECK(check_count >= 1),
    CHECK(resolved_at_utc IS NULL OR resolved_at_utc >= started_at_utc)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_incident
    ON incidents ((1)) WHERE resolved_at_utc IS NULL;
CREATE TABLE IF NOT EXISTS incident_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER NOT NULL REFERENCES incidents(id),
    at_utc TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('Opened', 'Changed', 'Recovered')),
    status TEXT NOT NULL,
    reason TEXT NOT NULL
);
'''


def _connect(path: Path, *, write: bool,
             authorize_schema: Callable[[], bool] | None = None) -> sqlite3.Connection | None:
    _check_storage_path(path, create=write)
    if not write and not path.is_file():
        return None
    if write:
        conn = sqlite3.connect(str(path), timeout=5)
    else:
        conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA busy_timeout=5000')
        conn.execute('PRAGMA foreign_keys=ON')
        if write:
            # Acquire the writer lock BEFORE deciding whether this is a first-
            # use schema. Otherwise simultaneous writers can both observe v0,
            # then race through initialization and refuse a valid v1 store.
            conn.execute('BEGIN IMMEDIATE')
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            raise HistoryError('unsupported incident history version')
        if write:
            if version == 0:
                # SQLite executescript() performs an implicit commit and would
                # bypass a release consent check at the schema's durability edge.
                # Use one explicitly guarded, rollbackable DDL transaction.
                existing = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                if existing:
                    raise HistoryError('existing unversioned database refused')
                if authorize_schema is not None and authorize_schema() is not True:
                    raise HistoryError('incident schema authorization denied')
                try:
                    # SQLite's parser, not a split-on-semicolon approximation,
                    # determines complete statements in the pinned static schema.
                    statement = ''
                    for line in SCHEMA.splitlines(keepends=True):
                        statement += line
                        if sqlite3.complete_statement(statement):
                            conn.execute(statement.strip())
                            statement = ''
                    if statement.strip():
                        raise HistoryError('incomplete pinned incident schema')
                    conn.execute('PRAGMA user_version=1')
                    # Fresh authorization must precede this schema COMMIT, not
                    # merely the subsequent incident-record COMMIT.
                    if authorize_schema is not None and authorize_schema() is not True:
                        raise HistoryError('incident schema authorization denied')
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    raise
            else:
                # No changes were needed; release the initializer's writer
                # lock before handing the handle to the incident transaction.
                conn.rollback()
        elif version != SCHEMA_VERSION:
            raise HistoryError('incident history database is not initialized')
    except BaseException:
        conn.close()
        raise
    return conn


def record_cycle(path: Path, result: dict, *,
                 authorize_commit: Callable[[], bool] | None = None,
                 operation_id: str | None = None) -> dict:
    """Commit one cycle; optional release-only authorization inside transaction.

    This gate is a PRE-COMMIT check. It cannot prove that a disk flush which
    started before revocation finishes before the deadline. A full hard-worker
    containment and bounded-writer acceptance gate remain separately required.
    """
    if operation_id is not None:
        operation_id = _operation_id(operation_id)
    if authorize_commit is not None and not callable(authorize_commit):
        raise HistoryError('invalid transaction authorization callback')

    def require_commit_authorization() -> bool:
        if authorize_commit is not None and authorize_commit() is not True:
            raise HistoryError('incident transaction authorization denied')
        return True

    # Refuse before even opening / initializing storage when possible.
    require_commit_authorization()
    sample = _validated_sample(result)
    conn = _connect(path, write=True, authorize_schema=
                    require_commit_authorization if authorize_commit is not None else None)
    assert conn is not None
    try:
        require_commit_authorization()
        conn.execute('BEGIN IMMEDIATE')
        if operation_id is not None:
            # Serialize lookup with other writers and create the receipt table
            # only inside this pending transaction (also for preexisting v1 DBs).
            conn.execute(RECEIPT_DDL)
            previous = _lookup_receipt(conn, operation_id, sample)
            if previous is not None:
                # No new row or incident transition. Authorization is checked
                # again and the empty transaction is rolled back.
                require_commit_authorization()
                conn.rollback()
                return previous
        conn.execute('''INSERT INTO checks
            (observed_at_utc, status, reason, windows_classification,
             pi_classification, missing_evidence, duration_ms)
             VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (sample['at'], sample['status'], sample['reason'], sample['windows'],
             sample['pi'], sample['issues'], sample['duration_ms']))
        open_row = conn.execute('''SELECT * FROM incidents
            WHERE resolved_at_utc IS NULL''').fetchone()
        event = 'NoIncident'
        incident_id = None
        if sample['status'] == 'Healthy':
            if open_row is not None:
                incident_id = open_row['id']
                # Backward clock corrections should not fabricate negative durations.
                resolved = max(sample['at'], open_row['started_at_utc'])
                conn.execute('''UPDATE incidents SET resolved_at_utc=?,
                    last_observed_at_utc=? WHERE id=?''',
                    (resolved, sample['at'], incident_id))
                conn.execute('''INSERT INTO incident_events
                    (incident_id, at_utc, event_type, status, reason)
                    VALUES (?, ?, ?, ?, ?)''',
                    (incident_id, sample['at'], 'Recovered', sample['status'], sample['reason']))
                event = 'Recovered'
        elif open_row is None:
            cur = conn.execute('''INSERT INTO incidents
                (started_at_utc, last_observed_at_utc, initial_status, last_status,
                 initial_reason, last_reason, windows_classification, pi_classification, check_count)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)''',
                (sample['at'], sample['at'], sample['status'], sample['status'],
                 sample['reason'], sample['reason'], sample['windows'], sample['pi']))
            incident_id = cur.lastrowid
            conn.execute('''INSERT INTO incident_events
                (incident_id, at_utc, event_type, status, reason)
                VALUES (?, ?, ?, ?, ?)''',
                (incident_id, sample['at'], 'Opened', sample['status'], sample['reason']))
            event = 'Opened'
        else:
            incident_id = open_row['id']
            changed = (sample['status'] != open_row['last_status'] or
                       sample['reason'] != open_row['last_reason'] or
                       sample['windows'] != open_row['windows_classification'] or
                       sample['pi'] != open_row['pi_classification'])
            conn.execute('''UPDATE incidents SET last_observed_at_utc=?, last_status=?,
                last_reason=?, windows_classification=?, pi_classification=?,
                check_count=check_count+1 WHERE id=?''',
                (sample['at'], sample['status'], sample['reason'], sample['windows'],
                 sample['pi'], incident_id))
            if changed:
                conn.execute('''INSERT INTO incident_events
                    (incident_id, at_utc, event_type, status, reason)
                    VALUES (?, ?, ?, ?, ?)''',
                    (incident_id, sample['at'], 'Changed', sample['status'], sample['reason']))
                event = 'Changed'
            else:
                event = 'Ongoing'
        # Bound individual-check retention while retaining incident timelines.
        # Keep time comparisons in UTC-normalized ISO form.
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=CHECK_RETENTION)).isoformat()
        conn.execute('DELETE FROM checks WHERE observed_at_utc < ?', (cutoff,))
        outcome = {'event': event, 'incident_id': incident_id, 'status': sample['status'],
                   'at': sample['at'], 'reason': sample['reason']}
        if operation_id is not None:
            conn.execute('INSERT INTO cycle_receipts (operation_id, sample_sha256, outcome_json) VALUES (?,?,?)',
                         (operation_id, _sample_sha256(sample),
                          json.dumps(outcome, sort_keys=True, separators=(',', ':'))))
        # An expired/revoked grant must roll back the still-uncommitted cycle.
        require_commit_authorization()
        try:
            conn.commit()
        except Exception as exc:
            # A COMMIT exception may occur after durable persistence. No retry
            # is allowed until this connection closes and the receipt is checked.
            commit_error = exc
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
        else:
            return outcome
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()
    # A COMMIT exception is handled only after the writer connection is closed.
    # The caller holds the exclusive parent lock, preventing concurrent replay.
    if operation_id is None:
        raise CommitOutcomeUnknown('unverified journal commit: no operation ID') from commit_error
    try:
        verified = reconcile_cycle(path, operation_id, result)
    except Exception as check_exc:
        raise CommitOutcomeUnknown('unverified journal commit: receipt read failed') from check_exc
    if verified is None:
        raise CommitOutcomeUnknown('unverified journal commit: receipt absent') from commit_error
    return verified


def history_report(path: Path, limit: int = 10) -> dict:
    if type(limit) is not int or not 1 <= limit <= MAX_HISTORY_RESULTS:
        raise HistoryError('invalid incident history result limit')
    conn = _connect(path, write=False)
    if conn is None:
        return {'schema_version': 1, 'source': 'OnyxV080IncidentHistory',
                'recorded_checks': 0, 'incident_count': 0, 'open_incident': None,
                'incidents': [], 'events': []}
    try:
        checks = conn.execute('SELECT count(*) FROM checks').fetchone()[0]
        incidents_count = conn.execute('SELECT count(*) FROM incidents').fetchone()[0]
        incident_rows = conn.execute('''SELECT * FROM incidents
            ORDER BY id DESC LIMIT ?''', (limit,)).fetchall()
        events = conn.execute('''SELECT event_type, incident_id, at_utc, status, reason
            FROM incident_events ORDER BY id DESC LIMIT ?''', (limit,)).fetchall()
        open_row = conn.execute('''SELECT * FROM incidents WHERE resolved_at_utc IS NULL''').fetchone()
        return {
            'schema_version': 1, 'source': 'OnyxV080IncidentHistory',
            'recorded_checks': checks, 'incident_count': incidents_count,
            'open_incident': dict(open_row) if open_row else None,
            'incidents': [dict(x) for x in incident_rows],
            'events': [dict(x) for x in events],
        }
    finally:
        conn.close()


def _display_report(report: dict) -> None:
    print('M3 history: {} retained checks | {} incidents'.format(
        report['recorded_checks'], report['incident_count']))
    open_incident = report['open_incident']
    if open_incident:
        print('  OPEN #{} | {} | since {} | {} observed checks'.format(
            open_incident['id'], open_incident['last_status'],
            open_incident['started_at_utc'], open_incident['check_count']))
    else:
        print('  No currently open incident.')
    for incident in report['incidents']:
        print('  #{} | {} | {} to {} | {} checks | {}'.format(
            incident['id'], 'OPEN' if not incident['resolved_at_utc'] else 'RECOVERED',
            incident['started_at_utc'], incident['resolved_at_utc'] or 'ongoing',
            incident['check_count'], incident['last_reason']))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-config', action='store_true', help='no checks and no store write')
    mode.add_argument('--record-live', action='store_true', help='real read-only probes + local incident history writes')
    mode.add_argument('--history', action='store_true', help='read selected isolated history, no probes')
    duration = parser.add_mutually_exclusive_group()
    duration.add_argument('--count', type=int, help='live cycles (1-20)')
    duration.add_argument('--continuous', action='store_true', help='live foreground until Ctrl+C')
    parser.add_argument('--interval-seconds', type=int, default=120)
    parser.add_argument('--json', action='store_true', help='machine-readable history/report output')
    args = parser.parse_args(argv)
    if not args.record_live and (args.count is not None or args.continuous):
        parser.error('count/continuous may only be used with --record-live')
    if args.record_live and args.count is None and not args.continuous:
        parser.error('live recording requires --count N or --continuous')
    try:
        if args.check_config:
            storage_profile()  # Validate opt-in without accessing history storage.
            config = m2.m1.cfg.load_config(m2.m1.CONFIG)
            if not m2.MIN_INTERVAL <= args.interval_seconds <= m2.MAX_INTERVAL:
                raise HistoryError('interval must be 90-3600 seconds')
            print('PASS: M3 configuration valid; no probes or incident store writes.')
            return 0
        path = history_path()
        if args.history:
            report = history_report(path)
            if args.json:
                print(json.dumps(report, sort_keys=True, separators=(',', ':'), allow_nan=False))
            else:
                _display_report(report)
            return 0
        config = m2.m1.cfg.load_config(m2.m1.CONFIG)
        m2.m1.verify_local_context(config)
        # Use M2's same-session mutex and sequential probe loop. If journal
        # storage fails, stop rather than run unrecorded cycles.
        def on_cycle(result: dict) -> None:
            incident = record_cycle(path, result)
            if args.json:
                print(json.dumps({**result, 'incident': incident},
                                 sort_keys=True, separators=(',', ':'), allow_nan=False), flush=True)
            else:
                m2._print_result(result, jsonl=False)
                print('  M3 incident: {}{}'.format(
                    incident['event'], ' #{}'.format(incident['incident_id'])
                    if incident['incident_id'] is not None else ''), flush=True)
        with m2.exclusive_monitor():
            m2.run_monitor(config, count=None if args.continuous else args.count,
                           interval_seconds=args.interval_seconds, emit=on_cycle)
    except KeyboardInterrupt:
        print('M3 foreground recording stopped by operator.', file=sys.stderr)
        return 0
    except (HistoryError, m2.MonitorError, m2.m1.ConnectivityError,
            m2.m1.cfg.ConfigError, sqlite3.Error, OSError, ValueError) as exc:
        print('M3 MONITOR REFUSED: {}'.format(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
