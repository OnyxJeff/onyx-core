"""M5 alert watcher tests: offline, no network probes or real HTTP sends."""
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / 'windows' / 'monitoring' / 'v080' / 'OnyxIncidentNotifications.py'
sys.path.insert(0, str(MODULE_PATH.parent))
spec = importlib.util.spec_from_file_location('OnyxIncidentNotifications', MODULE_PATH)
notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notify)

STAMP = '2026-11-12T01:23:26+00:00'


class DummyResponse:
    def __init__(self, status=204):
        self.status = status
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name) / 'OnyxCore-v080-Development' / 'Monitoring'
        base.mkdir(parents=True)
        self.journal = base / 'incident-history.sqlite3'
        self.cursor = base / notify.CURSOR_DB_NAME

    def tearDown(self):
        self.temp.cleanup()

    def add_event(self, kind='Opened', *, incident_id=None, status=None):
        if status is None:
            status = 'Healthy' if kind == 'Recovered' else 'Degraded'
        conn = notify.m3._connect(self.journal, write=True)
        try:
            if incident_id is None:
                row = conn.execute('''INSERT INTO incidents (
                    started_at_utc, last_observed_at_utc, initial_status, last_status,
                    initial_reason, last_reason, windows_classification,
                    pi_classification, check_count)
                    VALUES (?,?,?,?,?,?,?,?,?)''',
                    (STAMP, STAMP, 'Degraded', 'Degraded', 'WindowsUsbNotReady',
                    'WindowsUsbNotReady', 'WindowsUsbNotReady', 'PiInternetVerified', 1))
                incident_id = row.lastrowid
            event_id = conn.execute('''INSERT INTO incident_events
                (incident_id, at_utc, event_type, status, reason)
                VALUES (?, ?, ?, ?, ?)''',
                (incident_id, STAMP, kind, status, 'WindowsUsbNotReady')).lastrowid
            conn.commit()
            return event_id, incident_id
        finally:
            conn.close()

    def test_offline_config_does_not_touch_disk_or_transport(self):
        with mock.patch.object(notify.m3, 'history_path', return_value=self.journal):
            with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
                self.assertEqual(notify.main(['--check-config']), 0)
        self.assertIn('no writes', out.getvalue())
        self.assertFalse(self.cursor.exists())
        self.assertFalse(self.journal.exists())

    def test_status_readonly_uninitialized(self):
        result = notify.state_status(self.journal, self.cursor)
        self.assertEqual(result['latest_recorded_event_id'], 0)
        self.assertIsNone(result['last_delivered_event_id'])
        self.assertFalse(self.cursor.exists())
        self.assertFalse(self.journal.exists())

    def test_first_poll_baselines_old_incident_without_sending(self):
        event_id, _ = self.add_event()
        sent = []
        result = notify.poll_once(self.journal, self.cursor, sent.append)
        self.assertTrue(result['initialized'])
        self.assertEqual(result['last_event_id'], event_id)
        self.assertEqual(sent, [])
        self.assertEqual(notify.poll_once(self.journal, self.cursor, sent.append)['sent'], 0)

    def test_new_incident_notified_once(self):
        notify.poll_once(self.journal, self.cursor, lambda e: self.fail('bootstrap delivered'))
        eid, _ = self.add_event()
        sent = []
        result = notify.poll_once(self.journal, self.cursor, sent.append)
        self.assertEqual(result['sent'], 1)
        self.assertEqual(sent[0]['id'], eid)
        self.assertEqual(notify.poll_once(self.journal, self.cursor, sent.append)['sent'], 0)
        self.assertEqual(len(sent), 1)

    def test_recovery_delivered_after_open(self):
        notify.poll_once(self.journal, self.cursor, lambda _: None)
        _, incident_id = self.add_event()
        self.assertEqual(notify.poll_once(self.journal, self.cursor, lambda _: None)['sent'], 1)
        self.add_event('Recovered', incident_id=incident_id)
        events = []
        self.assertEqual(notify.poll_once(self.journal, self.cursor, events.append)['sent'], 1)
        self.assertEqual(events[0]['event_type'], 'Recovered')
        self.assertIn('recovered', notify._message(events[0]))

    def test_cause_changes_are_not_notifications(self):
        notify.poll_once(self.journal, self.cursor, lambda _: None)
        _, incident = self.add_event()
        self.add_event('Changed', incident_id=incident)
        seen = []
        r = notify.poll_once(self.journal, self.cursor, seen.append)
        self.assertEqual(r['sent'], 1)
        self.assertEqual(r['skipped'], 1)
        self.assertEqual(len(seen), 1)

    def test_delivery_failure_retries_without_moving_cursor(self):
        notify.poll_once(self.journal, self.cursor, lambda _: None)
        eid, _ = self.add_event()
        def fail(_):
            raise notify.NotificationError('temporary issue')
        with self.assertRaises(notify.NotificationError):
            notify.poll_once(self.journal, self.cursor, fail)
        self.assertEqual(notify.state_status(self.journal, self.cursor)['last_delivered_event_id'], 0)
        delivered = []
        self.assertEqual(notify.poll_once(self.journal, self.cursor, delivered.append)['last_event_id'], eid)
        self.assertEqual(len(delivered), 1)

    def test_restart_preserves_cursor(self):
        notify.poll_once(self.journal, self.cursor, lambda _: None)
        _, incident_id = self.add_event()
        notify.poll_once(self.journal, self.cursor, lambda _: None)
        self.assertEqual(notify.poll_once(self.journal, self.cursor, lambda _: None)['sent'], 0)
        eid, _ = self.add_event('Recovered', incident_id=incident_id)
        self.assertEqual(notify.state_status(self.journal, self.cursor)['pending_events'], 1)
        r = notify.poll_once(self.journal, self.cursor, lambda _: None)
        self.assertEqual(r['last_event_id'], eid)

    def test_reset_journal_refuses_without_delivery_or_cursor_rewind(self):
        _, incident_id = self.add_event()
        self.add_event('Changed', incident_id=incident_id)
        notify.poll_once(self.journal, self.cursor, lambda _: self.fail('baseline sent'))
        prior = notify.state_status(self.journal, self.cursor)['last_delivered_event_id']
        self.assertEqual(prior, 2)
        self.journal.unlink()
        self.add_event()  # Fresh journal starts at id 1, behind cursor 2.
        attempted = []
        with self.assertRaisesRegex(notify.NotificationError, 'operator recovery required'):
            notify.poll_once(self.journal, self.cursor, attempted.append)
        self.assertEqual(attempted, [])
        conn = sqlite3.connect(self.cursor)
        try:
            saved = conn.execute('SELECT last_event_id FROM notification_cursor WHERE id=1').fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(saved, prior)

    def test_missing_journal_after_prior_events_fails_closed(self):
        self.add_event()
        notify.poll_once(self.journal, self.cursor, lambda _: None)
        self.journal.unlink()
        attempted = []
        with self.assertRaisesRegex(notify.NotificationError, 'operator recovery required'):
            notify.poll_once(self.journal, self.cursor, attempted.append)
        self.assertFalse(self.journal.exists())
        self.assertEqual(attempted, [])

    def test_status_refuses_reset_journal_without_creating_files(self):
        _, incident_id = self.add_event()
        self.add_event('Changed', incident_id=incident_id)
        notify.poll_once(self.journal, self.cursor, lambda _: None)
        self.journal.unlink()
        self.add_event()
        before = self.cursor.read_bytes()
        with self.assertRaisesRegex(notify.NotificationError, 'operator recovery required'):
            notify.state_status(self.journal, self.cursor)
        self.assertEqual(self.cursor.read_bytes(), before)
        with mock.patch.object(notify.m3, 'history_path', return_value=self.journal):
            with mock.patch('sys.stderr', new_callable=io.StringIO) as err:
                self.assertEqual(notify.main(['--status']), 2)
                self.assertIn('operator recovery required', err.getvalue())

    def test_equal_journal_high_watermark_remains_valid(self):
        self.add_event()
        notify.poll_once(self.journal, self.cursor, lambda _: None)
        delivered = []
        self.assertEqual(notify.poll_once(self.journal, self.cursor, delivered.append)['sent'], 0)
        self.assertEqual(delivered, [])
        self.assertEqual(notify.state_status(self.journal, self.cursor)['pending_events'], 0)

    def test_invalid_event_not_delivered(self):
        event = {'id': 2, 'incident_id': 4, 'event_type': 'Opened', 'status': 'Healthy', 'at_utc': STAMP}
        with self.assertRaises(notify.NotificationError):
            notify._message(event)
        event['status'] = 'Degraded'
        self.assertNotIn('username', notify._message(event))
        self.assertNotIn('secret', notify._message(event))

    def test_url_policy(self):
        for url in ('https://ntfy.sh/mytopic', 'https://example.org:443/x', 'http://127.0.0.1:8080/events'):
            self.assertEqual(notify._validate_url(url, allow_private_http=False), url)
        for url in ('http://192.168.137.167:80/', 'http://10.100.0.3/alert',
                    'http://example.com/', 'https://a.com/?key=token', 'https://user:pass@a.com/',
                    'file:///etc/passwd', 'https://a.com/#fragment'):
            with self.assertRaises(notify.NotificationError):
                notify._validate_url(url, allow_private_http=False)
        self.assertEqual(notify._validate_url('http://10.100.0.3/alert', allow_private_http=True),
                         'http://10.100.0.3/alert')

    def test_payloads_have_no_raw_diagnostics_or_tokens(self):
        event = {'id': 3, 'incident_id': 8, 'event_type': 'Opened', 'status': 'Unknown', 'at_utc': STAMP,
                 'reason': 'sensitive raw command output ssh key'}
        for provider in ('ntfy', 'discord', 'json'):
            body, headers = notify._payload(event, provider)
            self.assertIn(b'ONYX CORE', body)
            self.assertNotIn(b'ssh key', body)
            self.assertNotIn(b'sensitive', body)
            self.assertIn('Content-Type', headers)

    def test_send_webhook_is_bounded_and_explicit(self):
        event = {'id': 1, 'incident_id': 1, 'event_type': 'Opened', 'status': 'Degraded', 'at_utc': STAMP}
        sent = []
        def transport(req, timeout):
            sent.append((req, timeout))
            return DummyResponse()
        notify.send_webhook(event, url='https://example.org/secretpath', provider='json',
                            token='secret-key', transport=transport)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1], 6)
        self.assertEqual(sent[0][0].get_method(), 'POST')
        self.assertEqual(sent[0][0].get_header('Authorization'), 'Bearer secret-key')
        self.assertNotIn('secret', str(notify._payload(event, 'json')))

    def test_http_error_redacts_target(self):
        event = {'id': 1, 'incident_id': 1, 'event_type': 'Opened', 'status': 'Degraded', 'at_utc': STAMP}
        def fail(req, timeout):
            raise urllib_error.HTTPError('https://example.org/secret/path', 500, 'bad', {}, None)
        with self.assertRaises(notify.NotificationError) as ctx:
            notify.send_webhook(event, url='https://example.org/secret/path', provider='discord', transport=fail)
        self.assertNotIn('secret', str(ctx.exception))

    def test_watch_refuses_missing_destination_without_writes(self):
        with mock.patch.dict(os.environ, {notify.URL_VARIABLE: ''}):
            with mock.patch.object(notify.m3, 'history_path', return_value=self.journal):
                with mock.patch('sys.stderr', new_callable=io.StringIO) as err:
                    self.assertEqual(notify.main(['--watch']), 2)
                    self.assertIn('REFUSED', err.getvalue())
        self.assertFalse(self.cursor.exists())
        self.assertFalse(self.journal.exists())

    def test_unsupported_state_version_not_overwritten(self):
        conn = sqlite3.connect(self.cursor)
        try:
            conn.execute('PRAGMA user_version=50')
            conn.commit()
        finally:
            conn.close()
        before = self.cursor.read_bytes()
        with self.assertRaises(notify.NotificationError):
            notify.poll_once(self.journal, self.cursor, lambda _: None)
        self.assertEqual(before, self.cursor.read_bytes())

    def test_no_database_created_by_status_cli(self):
        with mock.patch.object(notify.m3, 'history_path', return_value=self.journal):
            with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
                self.assertEqual(notify.main(['--status']), 0)
        self.assertIn('"enabled": false', out.getvalue())
        self.assertFalse(self.journal.exists())
        self.assertFalse(self.cursor.exists())


# Avoid a global network import outside tested functions.
from urllib import error as urllib_error

if __name__ == '__main__':
    unittest.main()
