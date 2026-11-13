#!/usr/bin/env python3
"""ONYX CORE v0.8 M3: explicit live monitoring with durable incident history.

Only this entry point writes v0.8 SQLite incident history in an explicitly
selected isolated store. It reuses M2's real, sequential, read-only checks
and its exclusive Windows mutex.
It never repairs connectivity, creates tasks, or sends notifications.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
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


def _connect(path: Path, *, write: bool) -> sqlite3.Connection | None:
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
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            raise HistoryError('unsupported incident history version')
        if write:
            if version == 0:
                # SQLite executescript commits implicitly, so only initialize
                # an entirely empty database, never migrate arbitrary tables.
                existing = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                if existing:
                    raise HistoryError('existing unversioned database refused')
                conn.executescript(SCHEMA)
                conn.execute('PRAGMA user_version=1')
                conn.commit()
        elif version != SCHEMA_VERSION:
            raise HistoryError('incident history database is not initialized')
    except BaseException:
        conn.close()
        raise
    return conn


def record_cycle(path: Path, result: dict) -> dict:
    """Commit a complete cycle and any incident transition in one transaction."""
    sample = _validated_sample(result)
    conn = _connect(path, write=True)
    assert conn is not None
    try:
        conn.execute('BEGIN IMMEDIATE')
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
        conn.commit()
        return {'event': event, 'incident_id': incident_id, 'status': sample['status'],
                'at': sample['at'], 'reason': sample['reason']}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


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
