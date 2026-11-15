"""R5: consent-bound M5 journal adapter with injected fake send, no HTTP."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
RUNTIME=ROOT/'windows'/'monitoring'/'v080'
MONITORING=ROOT/'windows'/'monitoring'
sys.path.insert(0,str(MONITORING));sys.path.insert(0,str(RUNTIME))
import OnyxV080NotificationIntegration as r5
import OnyxV080AlertAuthorization as auth
import OnyxIncidentNotifications as watcher
import OnyxLiveIncidentHistory as m3

NOW=datetime(2026,11,15,2,0,tzinfo=timezone.utc)
DEST=b'https://alerts.example.test/secret'
COMMIT='2d1d5c9bbb7c17254eb512d9955f8d3b9546c369'
SID='S-1-5-21-123-456-789-1000'

def valid_grant():
    return dict(schema_version=1,approved=True,scope='foreground_incident_notifications',
        source_commit=COMMIT,sid=SID,provider='ntfy',destination_sha256=auth.destination_digest(DEST),
        issued_utc='2026-11-15T01:00:00Z',expires_utc='2026-11-15T04:00:00Z',
        event_types=['Opened','Recovered'],storage_profile='release',notifications_enabled=True)

def good_context():
    return auth.AlertContext(COMMIT,SID,True,True,True)


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        folder=Path(self.temp.name)/'OnyxCore-v080-Release'/'Monitoring'
        folder.mkdir(parents=True)
        self.journal=folder/'incident-history.sqlite3'
        self.cursor=folder/'alert-delivery.sqlite3'
        self.delivered=[]
        self.consent=valid_grant()
        self.context=good_context()
        self.load_calls=0

    def run_it(self,*,poll=None,delivery=None,provider='ntfy',destination=DEST,
               journal=None,cursor=None):
        def load():
            self.load_calls+=1
            return self.consent.copy()
        return r5.poll_authorized_events(
            journal=journal or self.journal,cursor=cursor or self.cursor,
            provider=provider,destination=destination,load_grant=load,
            context=lambda:self.context,deliver=delivery or self.delivered.append,
            now=lambda:NOW,poll=poll or watcher.poll_once)

    def test_reject_unapproved_before_cursor(self):
        self.consent['approved']=False
        with self.assertRaises(auth.AlertConsentRefused): self.run_it()
        self.assertFalse(self.cursor.exists())

    def test_reject_expired_before_cursor(self):
        self.consent['expires_utc']='2026-11-15T01:59:59Z'
        with self.assertRaises(auth.AlertConsentRefused): self.run_it()
        self.assertFalse(self.cursor.exists())

    def test_reject_wrong_destination_before_cursor(self):
        with self.assertRaises(auth.AlertConsentRefused): self.run_it(destination=b'https://elsewhere.example/secret')
        self.assertFalse(self.cursor.exists())

    def test_reject_untrusted_source_before_cursor(self):
        self.context=auth.AlertContext(COMMIT,SID,False,True,True)
        with self.assertRaises(auth.AlertConsentRefused): self.run_it()
        self.assertFalse(self.cursor.exists())

    def test_reject_missing_active_console(self):
        self.context=auth.AlertContext(COMMIT,SID,True,False,True)
        with self.assertRaises(auth.AlertConsentRefused): self.run_it()
        self.assertFalse(self.cursor.exists())

    def test_reject_mismatched_release_profile(self):
        self.context=auth.AlertContext(COMMIT,SID,True,True,False)
        with self.assertRaises(auth.AlertConsentRefused): self.run_it()
        self.assertFalse(self.cursor.exists())

    def test_no_event_first_poll_initializes_cursor_no_send(self):
        # A missing journal uses M5's existing initialization behavior.
        v=self.run_it()
        self.assertTrue(v['initialized'])
        self.assertEqual(v['sent'],0)
        self.assertEqual(self.delivered,[])
        self.assertTrue(self.cursor.exists())

    def test_revalidate_each_delivered_event(self):
        def scripted(journal,cursor,deliver):
            deliver({'event_type':'Opened'})
            deliver({'event_type':'Recovered'})
            return dict(initialized=False,last_event_id=2,sent=2,skipped=0)
        out=self.run_it(poll=scripted)
        self.assertEqual(out['sent'],2)
        self.assertEqual(self.load_calls,3)
        self.assertEqual(len(self.delivered),2)

    def test_revocation_mid_batch_blocks_second(self):
        def send(event):
            self.delivered.append(event)
            self.consent['approved']=False
        def scripted(journal,cursor,deliver):
            deliver({'event_type':'Opened'})
            deliver({'event_type':'Recovered'})
        with self.assertRaises(auth.AlertConsentRefused): self.run_it(poll=scripted,delivery=send)
        self.assertEqual(len(self.delivered),1)

    def test_changed_event_not_deliverable(self):
        def scripted(journal,cursor,deliver):
            deliver({'event_type':'Changed'})
        with self.assertRaisesRegex(r5.NotificationIntegrationRefused,'unexpected'):
            self.run_it(poll=scripted)

    def test_malformed_poller_response(self):
        with self.assertRaises(r5.NotificationIntegrationRefused):
            self.run_it(poll=lambda a,b,c:{'sent':0})

    def test_reject_invalid_paths(self):
        with self.assertRaises(r5.NotificationIntegrationRefused):
            self.run_it(journal=Path('relative.sqlite3'))
        with self.assertRaises(r5.NotificationIntegrationRefused):
            self.run_it(cursor=self.journal)

    def test_real_m5_journal_baseline_and_at_least_once(self):
        """Record two synthetic incidents and validate M5's real cursor semantics."""
        # First authorized poll initializes the cursor before historical events.
        self.assertTrue(self.run_it()['initialized'])
        start=NOW-timedelta(seconds=35)
        def sample(cycle,when,win,pi):
            status,reason=m3.m2.m1.classify({'classification':win},{'classification':pi})
            return dict(source='OnyxV080ForegroundMonitor',mode='OptInForegroundReadOnly',
                checked_at_utc=when.isoformat(),cycle=cycle,duration_ms=40,status=status,reason=reason,
                windows_classification=win,pi_classification=pi,issues=[],
                incident_history_written=False,repair_action='None',notification_sent=False,
                scheduler_enabled=False)
        m3.record_cycle(self.journal,sample(1,start,'AdapterDown','PiInternetVerified'))
        m3.record_cycle(self.journal,sample(2,start+timedelta(seconds=4),'WindowsPathReady','PiInternetVerified'))
        def reject_delivery(event): raise RuntimeError('synthetic delivery refused')
        with self.assertRaisesRegex(RuntimeError,'refused'):
            self.run_it(delivery=reject_delivery)
        self.assertEqual(self.delivered,[])
        result=self.run_it()
        self.assertEqual(result['sent'],2)
        self.assertEqual([e['event_type'] for e in self.delivered],['Opened','Recovered'])
        self.assertEqual(self.run_it()['sent'],0)

    def test_cli_inert(self):
        with patch('sys.stdout',new_callable=io.StringIO) as out:
            self.assertEqual(r5.main(['--check-inert']),0)
        self.assertIn('"outbound_delivery_enabled": false',out.getvalue())
        with self.assertRaises(SystemExit):
            with patch('sys.stderr',new_callable=io.StringIO):r5.main(['--watch'])

if __name__=='__main__':unittest.main()
