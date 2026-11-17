"""Offline authorization-gated Discord watcher tests; never makes network requests."""
from __future__ import annotations
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import os
import sys
import unittest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'windows'/'monitoring'/'v080'))
import OnyxIncidentNotifications as m5
import OnyxV080ProtectedLogonRuntime as logon

ARGS=['--watch','--provider','discord','--poll-seconds','15','--monitor-stale-seconds','420']
ENV={'ONYXCORE_V080_ALERT_WEBHOOK_URL':'https://discord.com/api/webhooks/123/placeholder',
     'ONYXCORE_V080_STORAGE_PROFILE':'release'}

class WatchConsentTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,ENV)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_unapproved_does_not_read_or_advance_cursor(self):
        with patch.object(m5.m3,'history_path',return_value=Path('/synthetic/history.sqlite3')), \
             patch.object(m5,'exclusive_watcher',return_value=nullcontext()), \
             patch.object(m5,'poll_once') as poll, \
             patch.object(m5,'poll_monitor_liveness') as liveness, \
             patch.object(m5,'send_webhook') as post:
            self.assertEqual(m5.main(ARGS,watch_authorizer=lambda:False),0)
            poll.assert_not_called()
            liveness.assert_not_called()
            post.assert_not_called()

    def test_revoked_before_opened_event_does_not_send_or_advance(self):
        checks=iter([True,False])
        event={'id':7,'incident_id':3,'event_type':'Opened','status':'Degraded','at_utc':'2026-11-16T14:00:00Z'}
        def deliver_one(_journal,_cursor,deliver):
            deliver(event)
            raise AssertionError('Should stop before returning from delivery')
        with patch.object(m5.m3,'history_path',return_value=Path('/synthetic/history.sqlite3')), \
             patch.object(m5,'exclusive_watcher',return_value=nullcontext()), \
             patch.object(m5,'poll_once',side_effect=deliver_one) as poll, \
             patch.object(m5,'send_webhook') as post:
            self.assertEqual(m5.main(ARGS,watch_authorizer=lambda:next(checks)),0)
            self.assertEqual(poll.call_count,1)
            post.assert_not_called()

    def test_consent_revoked_before_liveness_does_not_alert(self):
        checks=iter([True,False])
        with patch.object(m5.m3,'history_path',return_value=Path('/synthetic/history.sqlite3')), \
             patch.object(m5,'exclusive_watcher',return_value=nullcontext()), \
             patch.object(m5,'poll_once',return_value={'initialized':False,'sent':0}) as poll, \
             patch.object(m5,'poll_monitor_liveness') as live, \
             patch.object(m5,'send_webhook') as post:
            self.assertEqual(m5.main(ARGS,watch_authorizer=lambda:next(checks)),0)
            self.assertEqual(poll.call_count,1)
            live.assert_not_called()
            post.assert_not_called()

    def test_explicit_watcher_without_external_gate_remains_compatible(self):
        with patch.object(m5.m3,'history_path',return_value=Path('/synthetic/history.sqlite3')), \
             patch.object(m5,'exclusive_watcher',return_value=nullcontext()), \
             patch.object(m5,'poll_once',return_value={'initialized':False,'sent':0}) as poll, \
             patch.object(m5,'poll_monitor_liveness') as live, \
             patch.object(m5.time,'sleep',side_effect=KeyboardInterrupt):
            self.assertEqual(m5.main(ARGS),0)
            self.assertEqual(poll.call_count,1)
            self.assertEqual(live.call_count,1)

    def test_protected_runtime_passes_fresh_gate(self):
        consent=SimpleNamespace(ConsentRefused=type('ConsentRefused',(Exception,),{}))
        authorize_state=Mock(return_value=True)
        att=SimpleNamespace(build_rechecking_authorizer=Mock(return_value=authorize_state))
        wiring=SimpleNamespace(source_root=Path('/synthetic/protected'),
                               manifest=object(),config_path=Path('/synthetic/config'),
                               approved_sid='S-1-5-21-1-2-3-1000')
        fake=(object(),SimpleNamespace(wiring=wiring),object(),att,consent,object(),object())
        captured=[]
        def safe_watcher(args,*,watch_authorizer):
            captured.append((args,watch_authorizer()))
            return 0
        with patch.object(logon,'_verified_runtime',return_value=fake), \
             patch.object(m5,'main',side_effect=safe_watcher):
            self.assertEqual(logon.run_alerts(),0)
        self.assertEqual(len(captured),1)
        self.assertEqual(captured[0][0],ARGS)
        self.assertTrue(captured[0][1])
        self.assertEqual(att.build_rechecking_authorizer.call_count,1)
        self.assertIs(att.build_rechecking_authorizer.call_args.kwargs['source_checker'],fake[-1])

    def test_protected_expiry_returns_false_in_watch_auth(self):
        denial=type('ConsentRefused',(Exception,),{})
        att=SimpleNamespace(build_rechecking_authorizer=Mock(return_value=Mock(side_effect=denial())))
        wiring=SimpleNamespace(source_root=Path('/synthetic/protected'),manifest=object(),
                               config_path=Path('/synthetic/config'),approved_sid='SID')
        fake=(object(),SimpleNamespace(wiring=wiring),object(),att,
              SimpleNamespace(ConsentRefused=denial),object(),object())
        with patch.object(logon,'_verified_runtime',return_value=fake), \
             patch.object(m5,'main',side_effect=lambda a,*,watch_authorizer: int(watch_authorizer())):
            self.assertEqual(logon.run_alerts(),0)

if __name__=='__main__':
    unittest.main()
