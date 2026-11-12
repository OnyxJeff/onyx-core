#!/usr/bin/env python3
"""v0.8 M4: sanitized read-only projection of M3 development incident history.

No polling, probes, network access or SQLite writes. Used only by the opt-in
localhost development gateway. The live monitor remains a separate foreground
process; old Healthy evidence is deliberately shown as Stale, not live health.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

MODULES = Path(__file__).resolve().parents[1] / 'monitoring' / 'v080'
if str(MODULES) not in sys.path:
    sys.path.insert(0, str(MODULES))
import OnyxLiveIncidentHistory as m3  # noqa: E402

STALENESS_SECONDS = 300  # M3 foreground defaults to a 120-second interval.
MAX_INCIDENTS = 5


def snapshot(*, now: datetime | None = None, path: Path | None = None) -> dict:
    """Return bounded metadata; never return raw SSH, OS info or API credentials.

    A missing DB is NoData. Read-only SQLite mode never initializes a database.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now must be timezone aware')
    path = m3.history_path() if path is None else path
    result = {
        'schema_version': 1,
        'source': 'OnyxV080MonitoringView',
        'state': 'NoData',
        'stale_after_seconds': STALENESS_SECONDS,
        'latest': None,
        'recorded_checks': 0,
        'incident_count': 0,
        'open_incident': None,
        'incidents': [],
        'read_only': True,
    }
    conn = m3._connect(path, write=False)
    if conn is None:
        return result
    try:
        result['recorded_checks'] = conn.execute('SELECT count(*) FROM checks').fetchone()[0]
        result['incident_count'] = conn.execute('SELECT count(*) FROM incidents').fetchone()[0]
        check = conn.execute('''SELECT observed_at_utc, status, reason,
            windows_classification, pi_classification, duration_ms
            FROM checks ORDER BY id DESC LIMIT 1''').fetchone()
        if check is not None:
            observed = m3._utc(check['observed_at_utc'])
            age = (now.astimezone(timezone.utc) - observed).total_seconds()
            # A significantly future-dated check cannot prove current health.
            clock_unreliable = age < -60
            stale = age > STALENESS_SECONDS
            result['state'] = 'Unknown' if clock_unreliable else (
                'Stale' if stale else check['status'])
            result['latest'] = {
                'checked_at_utc': check['observed_at_utc'],
                'age_seconds': max(0, round(age)),
                'observed_status': check['status'],
                'reason': check['reason'],
                'windows_classification': check['windows_classification'],
                'pi_classification': check['pi_classification'],
                'duration_ms': check['duration_ms'],
            }
        incidents = conn.execute('''SELECT id, started_at_utc, resolved_at_utc,
            last_status, last_reason, check_count FROM incidents
            ORDER BY id DESC LIMIT ?''', (MAX_INCIDENTS,)).fetchall()
        result['incidents'] = [{
            'id': row['id'],
            'started_at_utc': row['started_at_utc'],
            'resolved_at_utc': row['resolved_at_utc'],
            'last_status': row['last_status'],
            'last_reason': row['last_reason'],
            'check_count': row['check_count'],
        } for row in incidents]
        for item in result['incidents']:
            if item['resolved_at_utc'] is None:
                result['open_incident'] = item
                break
        return result
    finally:
        conn.close()
