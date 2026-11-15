"""R5: real R4 supervisor + release binding composition, fake worker only."""
from __future__ import annotations

from contextlib import contextmanager
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / 'windows' / 'monitoring' / 'v080'
MONITORING = ROOT / 'windows' / 'monitoring'
sys.path.insert(0, str(MONITORING))
sys.path.insert(0, str(RUNTIME))
import OnyxV080SessionIntegration as r5
import OnyxV080SessionSupervisor as r4
import OnyxV080ReleaseBinding as binding
import OnyxWindowsRuntimeAttestation as att
import OnyxGuardedRuntimeBridge as bridge
import OnyxV080ReleaseProfile as profile


class Clock:
    def __init__(self): self.value=0.0; self.slices=[]
    def now(self): return self.value
    def sleep(self, seconds): self.slices.append(seconds); self.value+=seconds


class SessionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        config_dir=self.root/'windows'/'monitoring'
        config_dir.mkdir(parents=True)
        self.config=config_dir/profile.RELEASE_CONFIG_NAME
        self.config.write_bytes((MONITORING/profile.RELEASE_CONFIG_NAME).read_bytes())
        self.manifest=att.ReleaseManifest('2d1d5c9bbb7c17254eb512d9955f8d3b9546c369',
            {key:'a'*64 for key in att.REQUIRED_FILES},'b'*64)
        self.wiring=binding.ReleaseWiring(self.root,self.config,self.manifest,
            'S-1-5-21-123-456-789-1000',cycles=1)
        self.interval=profile.load_release_config(self.config)['monitoring_interval_seconds']
        self.clock=Clock()
        self.calls=[]
        self.env=patch.dict(os.environ,{'ONYXCORE_V080_STORAGE_PROFILE':'release'})
        self.env.start(); self.addCleanup(self.env.stop)

    def run_it(self, *, policy=None, auth=None, console=None, source=None, worker=None,
               wiring=None, clock=None):
        c=clock or self.clock
        def normal_worker(w):
            self.calls.append(w.cycles)
            return bridge.BoundedRuntimeResult(1,1,True)
        return r5.run_reviewed_session(
            wiring=wiring or self.wiring,
            policy=policy or r4.SessionPolicy(2,300,self.interval),
            authorize=auth or (lambda:True),
            active_console=console or (lambda:True),
            attest_source=source or (lambda:True),
            run_release_cycle=worker or normal_worker, clock=c.now, sleep=c.sleep)

    def test_two_cycles_one_at_a_time(self):
        result=self.run_it()
        self.assertEqual((result.attempts,result.completed_cycles,result.persisted_cycles),(2,2,2))
        self.assertEqual(result.state,'Completed')
        self.assertEqual(self.calls,[1,1])
        self.assertTrue(self.clock.slices and max(self.clock.slices)<=2)
        self.assertFalse(result.tasks_created or result.repairs_invoked or result.notifications_sent)

    def test_midwait_revocation(self):
        with self.assertRaisesRegex(r4.SupervisionRefused,'revoked'):
            self.run_it(auth=lambda:self.clock.value<7)
        self.assertEqual(self.calls,[1])

    def test_active_console_loss(self):
        with self.assertRaisesRegex(r4.SupervisionRefused,'console'):
            self.run_it(console=lambda:self.clock.value<6)
        self.assertEqual(self.calls,[1])

    def test_source_change(self):
        with self.assertRaisesRegex(r4.SupervisionRefused,'source'):
            self.run_it(source=lambda:self.clock.value<6)
        self.assertEqual(self.calls,[1])

    def test_denial_before_worker(self):
        with self.assertRaises(r4.SupervisionRefused): self.run_it(auth=lambda:False)
        self.assertEqual(self.calls,[])

    def test_session_expiry(self):
        result=self.run_it(policy=r4.SessionPolicy(2,10,self.interval))
        self.assertEqual((result.state,result.persisted_cycles),('Expired',1))

    def test_invalid_profile_before_worker(self):
        with patch.dict(os.environ,{'ONYXCORE_V080_STORAGE_PROFILE':'development'}):
            with self.assertRaises(binding.ReleaseBindingRefused): self.run_it()
        self.assertEqual(self.calls,[])

    def test_refuse_interval_mismatch(self):
        with self.assertRaisesRegex(r5.SessionIntegrationRefused,'interval'):
            self.run_it(policy=r4.SessionPolicy(2,300,180 if self.interval!=180 else 240))
        self.assertEqual(self.calls,[])

    def test_refuse_multi_cycle_wiring(self):
        other=binding.ReleaseWiring(self.root,self.config,self.manifest,self.wiring.approved_sid,cycles=2)
        with self.assertRaisesRegex(r5.SessionIntegrationRefused,'one-cycle'):
            self.run_it(wiring=other)

    def test_invalid_worker_result_type(self):
        with self.assertRaisesRegex(r5.SessionIntegrationRefused,'unrecognized'):
            self.run_it(worker=lambda w:True)

    def test_invalid_worker_result_persistence(self):
        for result in (bridge.BoundedRuntimeResult(1,0,True),
                       bridge.BoundedRuntimeResult(2,2,True),
                       bridge.BoundedRuntimeResult(1,1,False),
                       bridge.BoundedRuntimeResult(1,1,True,notifications_sent=True),
                       bridge.BoundedRuntimeResult(1,1,True,repairs_invoked=True),
                       bridge.BoundedRuntimeResult(1,1,True,tasks_created=True)):
            with self.subTest(result=result),self.assertRaisesRegex(r5.SessionIntegrationRefused,'safe persisted'):
                self.run_it(worker=lambda w:result)

    def test_exception_propagates_never_fake_retry(self):
        with self.assertRaisesRegex(PermissionError,'revoked'):
            self.run_it(worker=lambda w:(_ for _ in ()).throw(PermissionError('revoked')))

    def test_invalid_runtime_dependency(self):
        with self.assertRaisesRegex(r5.SessionIntegrationRefused,'dependency'):
            r5.run_reviewed_session(wiring=self.wiring,
                policy=r4.SessionPolicy(1,300,self.interval),authorize=lambda:True,
                active_console=lambda:True,attest_source=lambda:True,
                run_release_cycle=None,clock=self.clock.now,sleep=self.clock.sleep)

    def test_cli_inert(self):
        with patch('sys.stdout',new_callable=io.StringIO) as out:
            self.assertEqual(r5.main(['--check-inert']),0)
        self.assertIn('"cli_live_enabled": false',out.getvalue())
        with self.assertRaises(SystemExit):
            with patch('sys.stderr',new_callable=io.StringIO): r5.main(['--live'])

if __name__=='__main__': unittest.main()
