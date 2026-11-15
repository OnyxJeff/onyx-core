"""R6 protected foreground entrypoint: all Windows operations injected/offline."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import io
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / 'windows' / 'monitoring' / 'v080'
sys.path.insert(0, str(RUNTIME))
import OnyxV080ReleaseOperator as op
import OnyxV080SessionSupervisor as supervisor
import OnyxV080SessionIntegration as integration
import OnyxV080ReleaseBinding as binding
import OnyxV080ReleaseProfile as profile
import OnyxWindowsRuntimeAttestation as att
import OnyxGuardedRuntimeBridge as bridge


class Clock:
    def __init__(self): self.now_value = 0; self.slices = []
    def now(self): return self.now_value
    def sleep(self, secs): self.slices.append(secs); self.now_value += secs


class R6OfflineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config_dir = self.root / 'windows' / 'monitoring'
        config_dir.mkdir(parents=True)
        config = config_dir / profile.RELEASE_CONFIG_NAME
        config.write_bytes((ROOT / 'windows' / 'monitoring' / profile.RELEASE_CONFIG_NAME).read_bytes())
        manifest = att.ReleaseManifest('a'*40, {k:'b'*64 for k in att.REQUIRED_FILES}, 'c'*64)
        self.wiring = binding.ReleaseWiring(self.root, config, manifest,
                            'S-1-5-21-123-456-789-1000', cycles=1)
        self.reviewed = types.SimpleNamespace(wiring=self.wiring)
        self.clock = Clock()
        self.calls = []
        self.audit_calls = []
        self.grant_valid = True
        self.console_valid = True
        self.source_valid = True
        self.fakeatt = types.SimpleNamespace(
            build_rechecking_authorizer=self.build_authorizer,
            _native_active_console=lambda:self.console_valid)
        self.source = self.source_check
        self.env = patch.dict(os.environ,{'ONYXCORE_V080_STORAGE_PROFILE':'release'})
        self.env.start(); self.addCleanup(self.env.stop)

    def build_authorizer(self, **kw):
        self.audit_calls.append(('make_authorizer', kw.get('approved_sid')))
        return lambda:self.grant_valid

    def source_check(self, **kw):
        self.audit_calls.append(('source', kw.get('root')))
        if not self.source_valid:
            raise PermissionError('source refused')

    def fake_cycle(self, wiring, **kw):
        self.calls.append(wiring.cycles)
        return bridge.BoundedRuntimeResult(1,1,True)

    def run_session(self, *, cycles=2, duration=15):
        with patch.object(binding,'run_explicitly_approved_api',side_effect=self.fake_cycle):
            return op._run_protected_session(
                reviewed=self.reviewed, context=None, att=self.fakeatt,
                binding=binding, checker=self.source, cycles=cycles,
                duration_minutes=duration, integration=integration,
                supervision=supervisor, clock=self.clock.now, sleep=self.clock.sleep)

    def test_two_real_bound_api_calls_one_cycle_each(self):
        result = self.run_session()
        self.assertEqual(result['result'],'PASS')
        self.assertEqual((result['cycles'],result['persisted_cycles'],result['attempts']),(2,2,2))
        self.assertEqual(self.calls,[1,1])
        self.assertTrue(self.audit_calls)
        self.assertTrue(self.clock.slices and max(self.clock.slices)<=2)
        self.assertFalse(result['notifications_sent'] or result['repairs_invoked'] or result['tasks_created'])

    def test_denial_before_first_cycle(self):
        self.grant_valid=False
        with self.assertRaises(supervisor.SupervisionRefused):self.run_session()
        self.assertEqual(self.calls,[])

    def test_midwait_revocation_prevents_second_cycle(self):
        original=self.build_authorizer
        self.fakeatt.build_rechecking_authorizer=lambda **kw:(lambda:self.clock.now_value < 5)
        with self.assertRaisesRegex(supervisor.SupervisionRefused,'revoked'):
            self.run_session()
        self.assertEqual(self.calls,[1])

    def test_source_change_during_wait(self):
        self.fakeatt._native_active_console=lambda:True
        def changed(**kw):
            if self.clock.now_value>=5:raise PermissionError('source changed')
        self.source=changed
        with self.assertRaisesRegex(PermissionError,'source changed'):
            self.run_session()
        self.assertEqual(self.calls,[1])

    def test_console_loss_during_wait(self):
        self.fakeatt._native_active_console=lambda:self.clock.now_value < 5
        with self.assertRaisesRegex(supervisor.SupervisionRefused,'console'):
            self.run_session()
        self.assertEqual(self.calls,[1])

    def test_deadline_reports_expired_not_pass(self):
        result=self.run_session(duration=1)
        self.assertEqual(result['result'],'EXPIRED')
        self.assertEqual(result['cycles'],1)
        self.assertEqual(self.calls,[1])

    def test_invalid_duration_and_count_fail_before_any_worker(self):
        for count,duration in ((0,15),(21,15),(-1,15),(True,15),(1,0),(1,61),(1,True)):
            with self.subTest(count=count,duration=duration),self.assertRaises(op.OperatorRefused):
                self.run_session(cycles=count,duration=duration)
        self.assertEqual(self.calls,[])

    def test_wrong_storage_profile_refused(self):
        with patch.dict(os.environ,{'ONYXCORE_V080_STORAGE_PROFILE':'development'}):
            with self.assertRaises(binding.ReleaseBindingRefused):self.run_session(cycles=1)
        self.assertEqual(self.calls,[])

    def test_actual_bridge_worker_error_not_reclassified(self):
        with patch.object(binding,'run_explicitly_approved_api',side_effect=PermissionError('denied')):
            with self.assertRaisesRegex(PermissionError,'denied'):
                op._run_protected_session(reviewed=self.reviewed, context=None,att=self.fakeatt,
                    binding=binding,checker=self.source,cycles=2,duration_minutes=15,
                    integration=integration,supervision=supervisor,
                    clock=self.clock.now,sleep=self.clock.sleep)

    def test_cli_explicit_flags_required(self):
        parser=op._parser()
        with patch('sys.stderr',new_callable=io.StringIO):
            for arg in ([],['--run-session-count','2','--run-count','1']):
                with self.assertRaises(SystemExit):parser.parse_args(arg)
        self.assertEqual(op.main(['--run-session-count','2']),2)
        self.assertEqual(op.main(['--audit-installed','--approve-session-read-only']),2)
        self.assertEqual(op.main(['--audit-installed','--session-duration-minutes','20']),2)

    def test_operator_action_refuses_session_missing_approval_before_bootstrap(self):
        args=types.SimpleNamespace(audit_installed=False,revoke_read_only=False,
            approve_revocation=False,enroll_read_only=False,approve_enrollment=False,
            run_count=None,approve_live_read_only=False,run_session_count=2,
            approve_session_read_only=False)
        with self.assertRaises(op.OperatorRefused):
            op._operator_action(args,loader=lambda:(_ for _ in ()).throw(AssertionError('bootstrap ran')))

    def test_operator_action_release_profile_restored_on_failure(self):
        args=types.SimpleNamespace(audit_installed=False,revoke_read_only=False,
            approve_revocation=False,enroll_read_only=False,approve_enrollment=False,
            run_count=None,approve_live_read_only=False,run_session_count=2,
            approve_session_read_only=True,session_duration_minutes=15)
        loader=lambda:(self.reviewed,None,self.fakeatt,None,binding,self.source)
        with patch.object(op,'_run_protected_session',side_effect=PermissionError('refused')):
            with self.assertRaises(PermissionError):op._operator_action(args,loader=loader)
        self.assertEqual(os.environ['ONYXCORE_V080_STORAGE_PROFILE'],'release')
        with patch.dict(os.environ,{'ONYXCORE_V080_STORAGE_PROFILE':'development'}):
            with self.assertRaises(op.OperatorRefused):op._operator_action(args,loader=loader)

    def test_manifest_pins_new_runtime_imports(self):
        self.assertIn('windows/monitoring/v080/OnyxV080SessionIntegration.py',att.REQUIRED_FILES)
        self.assertIn('windows/monitoring/v080/OnyxV080SessionSupervisor.py',att.REQUIRED_FILES)
        self.assertEqual(len(att.REQUIRED_FILES),len(set(att.REQUIRED_FILES)))

    def test_old_run_count_cli_still_available(self):
        a=op._parser().parse_args(['--run-count','1','--approve-live-read-only'])
        self.assertEqual(a.run_count,1)
        self.assertIsNone(a.run_session_count)


if __name__=='__main__':unittest.main()
