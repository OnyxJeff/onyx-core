"""Offline M5 monitor-liveness regression; never sends a real webhook."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'windows'/'monitoring'/'v080'))
sys.path.insert(0, str(ROOT/'windows'/'monitoring'))
import OnyxIncidentNotifications as m5
import OnyxLiveIncidentHistory as m3
import OnyxLiveConnectivity as m1

BASE = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def sample(second):
    w,p = 'WindowsPathReady','PiInternetVerified'
    status,reason = m1.classify({'classification':w},{'classification':p})
    return {'source':'OnyxV080ForegroundMonitor', 'mode':'OptInForegroundReadOnly',
            'cycle':1, 'checked_at_utc':(BASE+timedelta(seconds=second)).isoformat(),
            'status':status,'reason':reason,'windows_classification':w,
            'pi_classification':p,'issues':[],'duration_ms':10,
            'repair_action':'None','incident_history_written':False,
            'scheduler_enabled':False,'notification_sent':False}


class LivenessTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.journal=Path(t.name)/'OnyxCore-v080-Development'/'Monitoring'/'incident-history.sqlite3'
        self.cursor=self.journal.with_name('alert-delivery.sqlite3')
        self.sent=[]
    def poll(self,secs):
        return m5.poll_monitor_liveness(self.journal,self.cursor,self.sent.append,
             now=BASE+timedelta(seconds=secs), stale_after_seconds=420)

    def test_no_data_after_grace_warn_once(self):
        self.assertEqual(self.poll(0),'Waiting')
        self.assertEqual(self.poll(419),'Waiting')
        self.assertEqual(self.poll(420),'Stale')
        self.assertEqual(self.poll(500),'Stale')
        self.assertEqual([e['event_type'] for e in self.sent],['MonitorStale'])

    def test_freshness_loss_and_resume(self):
        m3.record_cycle(self.journal,sample(0))
        self.assertEqual(self.poll(0),'Waiting')
        self.assertEqual(self.poll(100),'Fresh')
        self.assertEqual(self.poll(420),'Fresh')
        self.assertEqual(self.poll(421),'Stale')
        m3.record_cycle(self.journal,sample(500))
        self.assertEqual(self.poll(500),'Fresh')
        self.assertEqual([e['event_type'] for e in self.sent],['MonitorStale','MonitorResumed'])

    def test_delivery_failure_preserves_state_for_retry(self):
        self.poll(0)
        def fail(_): raise m5.NotificationError('synthetic offline failure')
        with self.assertRaises(m5.NotificationError):
            m5.poll_monitor_liveness(self.journal,self.cursor,fail,
                now=BASE+timedelta(seconds=421),stale_after_seconds=420)
        self.assertEqual(self.poll(422),'Stale')
        self.assertEqual(self.sent[0]['event_type'],'MonitorStale')

    def test_liveness_messages_support_original_providers(self):
        for kind,status in [('MonitorStale','Unknown'),('MonitorResumed','Healthy')]:
            e={'id':0,'incident_id':0,'event_type':kind,'status':status,
               'at_utc':BASE.isoformat()}
            for provider in ('ntfy','discord','json'):
                body, headers=m5._payload(e,provider)
                self.assertIn(b'ONYX CORE',body)
                self.assertIn('Content-Type',headers)

    def test_invalid_timestamp_and_threshold_refused(self):
        with self.assertRaises(m5.NotificationError):
            m5.poll_monitor_liveness(self.journal,self.cursor,self.sent.append,
                now=BASE,stale_after_seconds=10)
        with self.assertRaises(m5.NotificationError):
            m5.poll_monitor_liveness(self.journal,self.cursor,self.sent.append,
                now=datetime(2026,1,1),stale_after_seconds=420)
        self.assertFalse(self.cursor.exists())

if __name__=='__main__':unittest.main()
