"""Offline-only protected release confirmation and quiet startup acceptance."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import json

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'windows'/'monitoring'/'v080'))
sys.path.insert(0, str(ROOT/'windows'/'monitoring'))
import OnyxV080ReleaseBinding as binding
import OnyxLiveIncidentHistory as m3
import OnyxIncidentNotifications as m5
import OnyxLiveConnectivity as m1
import OnyxWindowsRuntimeAttestation as att
import OnyxV080ReleaseProfile as profile

BASE = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def sample(status: str, secs: int) -> dict:
    w = 'WindowsPathReady' if status == 'Healthy' else 'AdapterDown'
    p = 'PiInternetVerified'
    observed, reason = m1.classify({'classification': w}, {'classification': p})
    assert observed == status
    return {'source':'OnyxV080ForegroundMonitor',
            'mode':'OptInForegroundReadOnly','cycle':1,
            'checked_at_utc':(BASE+timedelta(seconds=secs)).isoformat(),
            'status':observed,'reason':reason,'windows_classification':w,
            'pi_classification':p,'issues':[], 'duration_ms':10,
            'repair_action':'None','incident_history_written':False,
            'scheduler_enabled':False,'notification_sent':False}


class ProtectedStartupIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.journal = root / 'OnyxCore-v080-Release' / 'Monitoring' / 'incident-history.sqlite3'
        self.cursor = self.journal.with_name('alert-delivery.sqlite3')
        self.events = []

    def test_protected_writer_requires_authorization(self):
        with self.assertRaises(binding.ReleaseBindingRefused):
            binding._record_confirmed_release_cycle(self.journal, sample('Healthy',0),
                                                  authorize_commit=None)
        self.assertFalse(self.journal.exists())
        with self.assertRaises(m3.HistoryError):
            binding._record_confirmed_release_cycle(self.journal, sample('Healthy',0),
                                                  authorize_commit=lambda: False)
        self.assertFalse(self.journal.exists())

    def test_release_writer_confirmed_sequence_and_receipts(self):
        statuses = [('Degraded',0), ('Degraded',120),('Degraded',240),
                    ('Healthy',360), ('Healthy',480)]
        output = []
        for idx,(status,t) in enumerate(statuses):
            entry = sample(status,t)
            outcome = binding._record_confirmed_release_cycle(
                self.journal, entry, authorize_commit=lambda:True,
                operation_id=m3.cycle_operation_id(entry))
            output.append(outcome['event'])
        self.assertEqual(output,['NoIncident','NoIncident','Opened','Ongoing','Recovered'])
        r = m3.history_report(self.journal)
        self.assertEqual(r['recorded_checks'],5)
        self.assertEqual(r['incident_count'],1)
        self.assertIsNone(r['open_incident'])
        # A replay is not an additional check or notification.
        entry=sample('Healthy',480)
        replay = binding._record_confirmed_release_cycle(
            self.journal, entry, authorize_commit=lambda:True,
            operation_id=m3.cycle_operation_id(entry))
        self.assertEqual(replay['event'],'Recovered')
        self.assertEqual(m3.history_report(self.journal)['recorded_checks'],5)

    def test_release_binding_uses_confirmed_writer(self):
        root=Path(self.temp.name)
        config=root/'windows'/'monitoring'/profile.RELEASE_CONFIG_NAME
        config.parent.mkdir(parents=True)
        source_config=ROOT/'windows'/'monitoring'/profile.RELEASE_CONFIG_NAME
        config.write_bytes(source_config.read_bytes())
        manifest=att.ReleaseManifest('a'*40,{p:'a'*64 for p in att.REQUIRED_FILES},'b'*64)
        wiring=binding.ReleaseWiring(root,config,manifest,'S-1-5-21-1-2-3-4',1)
        observed=[]
        binding.run_explicitly_approved_api(wiring,
            build_authorizer=lambda **_: lambda:True,
            run_bridge=lambda policy,**kwargs: observed.append(kwargs))
        self.assertEqual(len(observed),1)
        self.assertIs(observed[0]['transactional_recorder'],
                      binding._record_confirmed_release_cycle)
        self.assertTrue(observed[0]['use_cycle_receipts'])

    def test_existing_fresh_cursor_boot_does_not_spam(self):
        m3.record_cycle(self.journal,sample('Healthy',0))
        self.assertEqual(m5.poll_monitor_liveness(self.journal,self.cursor,self.events.append,
            now=BASE+timedelta(seconds=10)), 'Waiting')
        self.assertEqual(m5.poll_monitor_liveness(self.journal,self.cursor,self.events.append,
            now=BASE+timedelta(seconds=60)), 'Fresh')
        self.assertEqual(m5.poll_monitor_liveness(self.journal,self.cursor,self.events.append,
            now=BASE+timedelta(seconds=500),silence_until=BASE+timedelta(seconds=900)),'Waiting')
        self.assertEqual(self.events,[])
        m3.record_cycle(self.journal,sample('Healthy',600))
        self.assertEqual(m5.poll_monitor_liveness(self.journal,self.cursor,self.events.append,
            now=BASE+timedelta(seconds=650),silence_until=BASE+timedelta(seconds=900)),'Fresh')
        self.assertEqual(m5.poll_monitor_liveness(self.journal,self.cursor,self.events.append,
            now=BASE+timedelta(seconds=950),silence_until=BASE+timedelta(seconds=900)),'Fresh')
        self.assertEqual(self.events,[])

    def test_stale_after_startup_grace_emits_once(self):
        m3.record_cycle(self.journal,sample('Healthy',0))
        self.assertEqual(m5.poll_monitor_liveness(self.journal,self.cursor,self.events.append,
            now=BASE), 'Waiting')
        self.assertEqual(m5.poll_monitor_liveness(self.journal,self.cursor,self.events.append,
            now=BASE+timedelta(seconds=1)), 'Fresh')
        for t in (600,700,899):
            self.assertEqual(m5.poll_monitor_liveness(self.journal,self.cursor,self.events.append,
                now=BASE+timedelta(seconds=t),
                silence_until=BASE+timedelta(seconds=900)), 'Waiting')
        self.assertEqual(len(self.events),0)
        self.assertEqual(m5.poll_monitor_liveness(self.journal,self.cursor,self.events.append,
            now=BASE+timedelta(seconds=901),
            silence_until=BASE+timedelta(seconds=900)), 'Stale')
        self.assertEqual(m5.poll_monitor_liveness(self.journal,self.cursor,self.events.append,
            now=BASE+timedelta(seconds=902)), 'Stale')
        self.assertEqual([e['event_type'] for e in self.events], ['MonitorStale'])

    def test_previous_stale_cursor_rebases_silently_on_boot(self):
        m3.record_cycle(self.journal,sample('Healthy',0))
        m5.poll_monitor_liveness(self.journal,self.cursor,self.events.append,now=BASE)
        m5.poll_monitor_liveness(self.journal,self.cursor,self.events.append,now=BASE+timedelta(seconds=421))
        self.assertEqual([e['event_type'] for e in self.events],['MonitorStale'])
        self.events.clear()
        m3.record_cycle(self.journal,sample('Healthy',600))
        self.assertEqual(m5.poll_monitor_liveness(self.journal,self.cursor,self.events.append,
            now=BASE+timedelta(seconds=610),
            silence_until=BASE+timedelta(seconds=900)), 'Fresh')
        self.assertEqual(self.events,[])

    def test_invalid_grace_does_not_create_cursor(self):
        with self.assertRaises(m5.NotificationError):
            m5.poll_monitor_liveness(self.journal,self.cursor,self.events.append,
                now=BASE,silence_until=datetime(2026,11,16))
        self.assertFalse(self.cursor.exists())

if __name__=='__main__': unittest.main()
