#!/usr/bin/env python3
"""ONYX CORE v0.8 M5 — optional foreground incident notification watcher.

Watches saved M3 incident events without running diagnostics or changing M1-M4.
Network POSTs occur ONLY with --watch and an explicit env URL/provider.
No Scheduled Tasks, repairs or automatic startup are installed.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import ipaddress
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

import OnyxLiveIncidentHistory as m3

URL_VARIABLE = 'ONYXCORE_V080_ALERT_WEBHOOK_URL'
TOKEN_VARIABLE = 'ONYXCORE_V080_ALERT_TOKEN'
CURSOR_DB_NAME = 'alert-delivery.sqlite3'
SCHEMA_VERSION = 1
MAX_EVENTS_PER_POLL = 64
POLL_MIN = 5
POLL_MAX = 300
MUTEX_NAME = r'Local\OnyxCoreV080IncidentNotificationWatcher'


class NotificationError(RuntimeError):
    """Safe-to-print notification error (never includes a webhook URL)."""


class WatchConsentEnded(Exception):
    """Stop the watcher quietly after protected read-only consent ends."""


def state_path(journal_path: Path | None = None) -> Path:
    """Keep cursor and journal in the same selected profile."""
    journal = m3.history_path() if journal_path is None else journal_path
    return journal.with_name(CURSOR_DB_NAME)


def _check_state_path(path: Path, *, create: bool) -> None:
    if (not path.is_absolute() or path.name != CURSOR_DB_NAME or
            path.parent.name != 'Monitoring'):
        raise NotificationError('unexpected notification state path')
    for part in (path.parent.parent, path.parent, path):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise NotificationError('redirected notification state path refused')
    if path.exists() and not path.is_file():
        raise NotificationError('notification state path is not a file')
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)


def _state_connection(path: Path, *, create: bool) -> sqlite3.Connection | None:
    _check_state_path(path, create=create)
    if not create and not path.exists():
        return None
    conn = (sqlite3.connect(str(path), timeout=5) if create else
            sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA busy_timeout=5000')
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            raise NotificationError('unsupported notification state version')
        if create and version == 0:
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if tables:
                raise NotificationError('unversioned notification state refused')
            conn.execute('''CREATE TABLE notification_cursor (
                id INTEGER PRIMARY KEY CHECK(id=1),
                last_event_id INTEGER NOT NULL CHECK(last_event_id >= 0)
            )''')
            conn.execute('PRAGMA user_version=1')
            conn.commit()
        elif version == 0:
            raise NotificationError('notification state is not initialized')
        # Verify expected table exists before claiming initialized.
        conn.execute('SELECT last_event_id FROM notification_cursor WHERE id=1')
        return conn
    except BaseException:
        conn.close()
        raise


def _read_events(path: Path, after: int | None) -> tuple[int, list[dict]]:
    """Read M3 journal in read-only mode, never creating its database."""
    conn = m3._connect(path, write=False)
    if conn is None:
        return 0, []
    try:
        max_event = int(conn.execute('SELECT coalesce(max(id),0) FROM incident_events').fetchone()[0])
        if after is None:
            return max_event, []
        rows = conn.execute('''SELECT id, incident_id, event_type, at_utc, status
            FROM incident_events WHERE id>? ORDER BY id ASC LIMIT ?''',
            (after, MAX_EVENTS_PER_POLL)).fetchall()
        return max_event, [dict(row) for row in rows]
    finally:
        conn.close()


def _message(event: dict) -> str:
    """No free-form reason, hostnames, network output, tokens or PII."""
    if event.get('event_type') in ('MonitorStale', 'MonitorResumed'):
        # Status notices are distinct from incident events; no fictitious
        # incident number is generated for a monitor-liveness warning.
        expected = ('Unknown' if event['event_type'] == 'MonitorStale' else 'Healthy')
        if (event.get('status') != expected or event.get('id') != 0 or
                event.get('incident_id') != 0):
            raise NotificationError('invalid monitor-liveness notification')
        return ('ONYX CORE: monitoring is STALE; Windows/Pi checks have stopped '
                'arriving. Last known connectivity state is not current.'
                if event['event_type'] == 'MonitorStale' else
                'ONYX CORE: monitoring has resumed reporting fresh Windows/Pi checks.')
    if (type(event.get('id')) is not int or event['id'] < 1 or
            type(event.get('incident_id')) is not int or event['incident_id'] < 1 or
            event.get('event_type') not in ('Opened', 'Recovered') or
            event.get('status') not in ('Degraded', 'Unknown', 'Healthy')):
        raise NotificationError('invalid incident notification event')
    if (event['event_type'] == 'Recovered' and event['status'] != 'Healthy') or (event['event_type'] == 'Opened' and event['status'] == 'Healthy'):
        raise NotificationError('contradictory incident event')
    at = event.get('at_utc')
    if not isinstance(at, str) or len(at) > 48:
        raise NotificationError('invalid incident timestamp')
    try:
        timestamp = datetime.fromisoformat(at.replace('Z', '+00:00'))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError('naive timestamp')
    except (ValueError, OverflowError):
        raise NotificationError('invalid incident timestamp') from None
    if event['event_type'] == 'Opened':
        return f"ONYX CORE: connectivity incident #{event['incident_id']} opened ({event['status']}). Check the ONYX CORE dashboard."
    return f"ONYX CORE: connectivity incident #{event['incident_id']} recovered (Healthy)."


def _validate_url(url: str, *, allow_private_http: bool) -> str:
    if type(url) is not str or not url or len(url) > 2048 or any(ord(c) <= 32 for c in url):
        raise NotificationError('invalid notification destination')
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        raise NotificationError('invalid notification destination') from None
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise NotificationError('notification URL must have a host and no credentials, query or fragment')
    if parts.scheme == 'https':
        if port == 0:
            raise NotificationError('invalid HTTPS notification port')
        return url
    if parts.scheme != 'http':
        raise NotificationError('notification destination requires HTTPS (or explicitly permitted private HTTP)')
    name = parts.hostname.lower()
    if name == 'localhost':
        return url
    try:
        host_ip = ipaddress.ip_address(name)
    except ValueError:
        raise NotificationError('plain HTTP requires numeric loopback/private address') from None
    private_networks = (
        ipaddress.ip_network('10.0.0.0/8'), ipaddress.ip_network('172.16.0.0/12'),
        ipaddress.ip_network('192.168.0.0/16'), ipaddress.ip_network('fc00::/7'),
    )
    if host_ip.is_loopback or (allow_private_http and any(host_ip in net for net in private_networks)):
        return url
    raise NotificationError('plain HTTP destination not permitted')


def _payload(event: dict, provider: str) -> tuple[bytes, dict[str, str]]:
    msg = _message(event)
    if provider == 'ntfy':
        return msg.encode('utf-8'), {
            'Content-Type': 'text/plain; charset=utf-8',
            'Title': 'ONYX CORE connectivity',
            'Tags': 'warning' if event['event_type'] in ('Opened', 'MonitorStale') else 'white_check_mark',
        }
    if provider == 'discord':
        body = {'content': msg}
    elif provider == 'json':
        body = {'source': 'OnyxCoreV080', 'event_id': event['id'],
                'incident_id': event['incident_id'], 'event': event['event_type'],
                'status': event['status'], 'observed_at_utc': event['at_utc'],
                'message': msg}
    else:
        raise NotificationError('unsupported notification provider')
    return json.dumps(body, separators=(',', ':'), allow_nan=False).encode('utf-8'), {
        'Content-Type': 'application/json',
    }


def send_webhook(event: dict, *, url: str, provider: str,
                 allow_private_http: bool = False, token: str | None = None,
                 transport: Callable | None = None) -> None:
    _validate_url(url, allow_private_http=allow_private_http)
    body, headers = _payload(event, provider)
    if provider == 'discord':
        # Discord's HTTP API requires an identified User-Agent; the default
        # urllib User-Agent can be denied by its edge filter with HTTP 403.
        headers['User-Agent'] = 'DiscordBot (https://github.com/OnyxJeff/onyx-core, 0.8.0)'
    if token:
        if not isinstance(token, str) or len(token) > 1024 or any(ord(c) in (10,13) for c in token):
            raise NotificationError('invalid optional alert token')
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(url, data=body, method='POST', headers=headers)
    if transport is None:
        # No system proxy or redirect: never forward webhook paths/tokens to another host.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        transport = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()).open
    try:
        with transport(request, timeout=6) as response:
            status = response.status
            if type(status) is not int or not (200 <= status < 300):
                raise NotificationError('notification endpoint returned unsuccessful HTTP status')
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        # Exceptions may embed secret webhook paths. NEVER print their strings.
        if isinstance(exc, urllib.error.HTTPError):
            raise NotificationError('notification HTTP failure (status {})'.format(exc.code)) from None
        raise NotificationError('notification delivery failed; will retry') from None


def poll_once(journal_path: Path, cursor_path: Path, deliver: Callable[[dict], None]) -> dict:
    """Persist cursor after each successfully delivered event (at-least-once)."""
    conn = _state_connection(cursor_path, create=True)
    assert conn is not None
    try:
        row = conn.execute('SELECT last_event_id FROM notification_cursor WHERE id=1').fetchone()
        if row is None:
            max_event, _ = _read_events(journal_path, None)
            conn.execute('INSERT INTO notification_cursor (id,last_event_id) VALUES (1,?)', (max_event,))
            conn.commit()
            return {'initialized': True, 'last_event_id': max_event, 'sent': 0, 'skipped': 0}
        cursor = int(row[0])
        latest, events = _read_events(journal_path, cursor)
        if latest < cursor:
            raise NotificationError('incident journal is behind saved notification cursor; operator recovery required')
        sent = skipped = 0
        for event in events:
            if event['event_type'] in ('Opened', 'Recovered'):
                deliver(event)  # Network send; if it fails, cursor stays BEFORE this event.
                sent += 1
            elif event['event_type'] == 'Changed':
                skipped += 1
            else:
                raise NotificationError('unexpected incident event type')
            conn.execute('UPDATE notification_cursor SET last_event_id=? WHERE id=1', (event['id'],))
            conn.commit()
            cursor = event['id']
        return {'initialized': False, 'last_event_id': cursor, 'sent': sent, 'skipped': skipped}
    finally:
        conn.close()



def _latest_check_time(journal_path: Path) -> datetime | None:
    conn = m3._connect(journal_path, write=False)
    if conn is None:
        return None
    try:
        row = conn.execute('SELECT observed_at_utc FROM checks ORDER BY id DESC LIMIT 1').fetchone()
        return None if row is None else m3._utc(row[0])
    finally:
        conn.close()


def poll_monitor_liveness(journal_path: Path, cursor_path: Path,
                          deliver: Callable[[dict], None], *,
                          now: datetime | None = None,
                          stale_after_seconds: int = 420,
                          silence_until: datetime | None = None) -> str:
    """Durable status notice if no checks arrive while the watcher is alive.

    A first-time watcher establishes a grace baseline; repeat stale alerts are
    suppressed across watcher restarts. Network delivery precedes state commit
    (at-least-once semantics). Does NOT detect a powered-off host.
    """
    if type(stale_after_seconds) is not int or not 180 <= stale_after_seconds <= 3600:
        raise NotificationError('monitor-stale threshold must be 180–3600 seconds')
    clock = datetime.now(timezone.utc) if now is None else now
    if not isinstance(clock, datetime) or clock.tzinfo is None or clock.utcoffset() is None:
        raise NotificationError('monitor-liveness clock must be aware')
    clock = clock.astimezone(timezone.utc)
    if silence_until is not None:
        if (not isinstance(silence_until, datetime) or silence_until.tzinfo is None
                or silence_until.utcoffset() is None):
            raise NotificationError('monitor startup grace must be an aware timestamp')
        silence_until = silence_until.astimezone(timezone.utc)
    latest = _latest_check_time(journal_path)
    conn = _state_connection(cursor_path, create=True)
    assert conn is not None
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS monitor_liveness (
            id INTEGER PRIMARY KEY CHECK(id=1),
            state TEXT NOT NULL CHECK(state IN ('Waiting','Fresh','Stale')),
            first_seen_utc TEXT NOT NULL
        )""")
        row = conn.execute('SELECT state,first_seen_utc FROM monitor_liveness WHERE id=1').fetchone()
        if row is None:
            conn.execute('INSERT INTO monitor_liveness(id,state,first_seen_utc) VALUES(1,?,?)',
                         ('Waiting', clock.isoformat()))
            conn.commit()
            return 'Waiting'
        state = row['state']
        if state not in ('Waiting', 'Fresh', 'Stale'):
            raise NotificationError('unrecognized monitor-liveness state')
        first_seen = m3._utc(row['first_seen_utc'])
        fresh = (latest is not None and latest <= clock + timedelta(seconds=60) and
                 latest >= clock - timedelta(seconds=stale_after_seconds))
        # A normal boot can revive an old Fresh cursor before the first new
        # monitor cycle. During the start-up grace period, do not emit either
        # Stale or Resumed. Silently rebase a fresh observation to Fresh; a
        # missing observation becomes eligible for exactly one Stale later.
        if silence_until is not None and clock < silence_until:
            if fresh and state != 'Fresh':
                conn.execute("UPDATE monitor_liveness SET state='Fresh' WHERE id=1")
                conn.commit()
            return 'Fresh' if fresh else 'Waiting'
        if state == 'Waiting':
            if fresh:
                conn.execute("UPDATE monitor_liveness SET state='Fresh' WHERE id=1")
                conn.commit()
                return 'Fresh'
            if clock < first_seen + timedelta(seconds=stale_after_seconds):
                return 'Waiting'
        new_state = 'Fresh' if fresh else 'Stale'
        if new_state != state:
            if new_state == 'Stale' or state == 'Stale':
                event_type = 'MonitorStale' if new_state == 'Stale' else 'MonitorResumed'
                deliver({'id':0, 'incident_id':0, 'event_type':event_type,
                         'status':'Unknown' if new_state == 'Stale' else 'Healthy',
                         'at_utc':clock.isoformat()})
            conn.execute('UPDATE monitor_liveness SET state=? WHERE id=1', (new_state,))
            conn.commit()
        return new_state
    finally:
        conn.close()

def state_status(journal_path: Path, cursor_path: Path) -> dict:
    """Read-only status: no DB creation and no network traffic."""
    conn = _state_connection(cursor_path, create=False)
    cursor = None
    if conn is not None:
        try:
            row = conn.execute('SELECT last_event_id FROM notification_cursor WHERE id=1').fetchone()
            if row is not None:
                cursor = int(row[0])
        finally:
            conn.close()
    latest, _ = _read_events(journal_path, None)
    if cursor is not None and latest < cursor:
        raise NotificationError('incident journal is behind saved notification cursor; operator recovery required')
    return {'enabled': False, 'last_delivered_event_id': cursor,
            'latest_recorded_event_id': latest, 'pending_events': max(0, latest - cursor) if cursor is not None else None}


@contextmanager
def exclusive_watcher():
    if os.name != 'nt':
        raise NotificationError('live alert watcher requires Windows')
    import ctypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    handle = kernel.CreateMutexW(None, 0, MUTEX_NAME)
    if not handle:
        raise NotificationError('cannot acquire notification watcher mutex')
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        raise NotificationError('another alert watcher is running in this Windows logon session')
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def main(argv: list[str] | None = None, *,
         watch_authorizer: Callable[[], bool] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-config', action='store_true', help='no writes, network or events')
    mode.add_argument('--status', action='store_true', help='read journal/cursor only')
    mode.add_argument('--watch', action='store_true', help='explicitly opt in to webhook delivery')
    parser.add_argument('--provider', choices=('ntfy', 'discord', 'json'), default='ntfy')
    parser.add_argument('--poll-seconds', type=int, default=15)
    parser.add_argument('--monitor-stale-seconds', type=int, default=0,
                        help='opt in to durable monitor-liveness alerts, 180-3600 seconds; 0 disables')
    parser.add_argument('--allow-private-http', action='store_true', help='explicitly allow RFC1918 HTTP destination')
    args = parser.parse_args(argv)
    try:
        if type(args.poll_seconds) is not int or not POLL_MIN <= args.poll_seconds <= POLL_MAX:
            raise NotificationError('poll interval must be 5–300 seconds')
        if args.monitor_stale_seconds != 0 and not 180 <= args.monitor_stale_seconds <= 3600:
            raise NotificationError('monitor-stale threshold must be 180–3600 seconds')
        journal = m3.history_path()
        cursor = state_path(journal)
        if args.check_config:
            print('PASS: M5 notification watcher valid; no writes, probes or webhook delivery.')
            return 0
        if args.status:
            print(json.dumps(state_status(journal, cursor), sort_keys=True))
            return 0
        url = _validate_url(os.environ.get(URL_VARIABLE, ''), allow_private_http=args.allow_private_http)
        token = os.environ.get(TOKEN_VARIABLE)
        # Ensure no token is sent to Discord endpoints using URL secret paths.
        if args.provider == 'discord' and token:
            raise NotificationError('Discord uses URL token; optional bearer token must be unset')
        if watch_authorizer is not None and not callable(watch_authorizer):
            raise NotificationError('watcher authorization callback invalid')
        def require_watch_consent():
            if watch_authorizer is not None and watch_authorizer() is not True:
                raise WatchConsentEnded()
        def deliver_checked(event):
            # In addition to polling authorization, recheck immediately before
            # every individual POST (incidents and liveness).
            require_watch_consent()
            send_webhook(event, url=url, provider=args.provider,
                         allow_private_http=args.allow_private_http, token=token)
        print('M5: opt-in watcher enabled, provider {}. No previous events will be backfilled on first start.'.format(args.provider), flush=True)
        # The watcher may start before the monitor's first post-login cycle.
        # Delay liveness notices, not incident events, for one threshold window.
        startup_silence_until = (datetime.now(timezone.utc) +
            timedelta(seconds=args.monitor_stale_seconds) if args.monitor_stale_seconds else None)
        with exclusive_watcher():
            failures = 0
            while True:
                try:
                    # Do not read/advance notification cursors or emit a stale
                    # alert while the protected monitor is deliberately paused.
                    require_watch_consent()
                    report = poll_once(journal, cursor, deliver_checked)
                    failures = 0
                    if report['initialized']:
                        print('M5: existing journal events acknowledged as baseline; watching for new incidents.', flush=True)
                    if report['sent']:
                        print('M5: {} incident notification(s) delivered.'.format(report['sent']), flush=True)
                    if args.monitor_stale_seconds:
                        require_watch_consent()
                        poll_monitor_liveness(journal, cursor, deliver_checked,
                            stale_after_seconds=args.monitor_stale_seconds,
                            silence_until=startup_silence_until)
                    time.sleep(args.poll_seconds)
                except WatchConsentEnded:
                    print('M5: protected monitoring consent ended; watcher paused.',
                          file=sys.stderr, flush=True)
                    return 0
                except (NotificationError, sqlite3.Error, m3.HistoryError, OSError) as exc:
                    failures += 1
                    # Only safe error objects from our controlled wrappers are printed.
                    label = str(exc) if isinstance(exc, NotificationError) else 'local notification journal unavailable'
                    print('M5: {}. Delivery will be retried.'.format(label), file=sys.stderr, flush=True)
                    time.sleep(min(300, args.poll_seconds * (2 ** min(failures, 4))))
    except KeyboardInterrupt:
        print('M5 watcher stopped by operator.', file=sys.stderr)
        return 0
    except (NotificationError, m3.HistoryError, sqlite3.Error, OSError) as exc:
        label = str(exc) if isinstance(exc, NotificationError) else 'local notification state unavailable'
        print('M5 REFUSED: ' + label, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
