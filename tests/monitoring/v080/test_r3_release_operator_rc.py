"""RC launch-control tests: PURE and injected; never invokes Win32 or live telemetry."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'windows' / 'monitoring' / 'v080'))
import OnyxV080ReleaseOperator as op
import OnyxWindowsProtectedInstallTrust as trust
import OnyxWindowsUserConsent as consent
import OnyxWindowsRuntimeAttestation as att

SID = 'S-1-5-21-101-202-303-404'
COMMIT = 'a' * 40
CONFIG = 'b' * 64
TIME = datetime(2026,11,14,12,0,0,tzinfo=timezone.utc)


def args(**kw):
    values = dict(audit_installed=False, revoke_read_only=False,
                  enroll_read_only=False, run_count=None, approve_revocation=False,
                  approve_enrollment=False, approve_live_read_only=False,
                  expires_minutes=60)
    values.update(kw)
    return types.SimpleNamespace(**values)


class OperatorRCTests(unittest.TestCase):
    def context(self):
        return consent.VerifiedContext(SID, COMMIT, CONFIG, True, True)

    def grant(self, minutes=60):
        return op.make_read_only_grant(sid=SID, commit=COMMIT,
                config_digest=CONFIG, now=TIME, minutes=minutes)

    def test_grant_matches_existing_consent_schema(self):
        raw=self.grant()
        self.assertTrue(consent.evaluate_grant(raw, context=self.context(),now=TIME))
        doc=json.loads(raw)
        self.assertFalse(doc['notifications_enabled'])
        self.assertEqual(doc['repair_action'],'None')
        self.assertEqual(doc['storage_profile'],'release')
        self.assertEqual(set(doc), consent.GRANT_FIELDS)

    def test_duration_and_clock_validation(self):
        for minutes in (0,10081,-10,True,1.2):
            with self.subTest(minutes=minutes), self.assertRaises(op.OperatorRefused):
                self.grant(minutes)
        with self.assertRaises(op.OperatorRefused):
            op.make_read_only_grant(sid=SID,commit=COMMIT,config_digest=CONFIG,
                                    now=datetime.now(),minutes=60)

    def test_explicit_week_long_enrollment_is_bounded_and_revocable(self):
        self.assertEqual(op.MAX_ENROLL_MINUTES, 10080)
        raw = self.grant(minutes=10080)
        doc = json.loads(raw)
        self.assertEqual(doc['scope'], 'periodic_read_only_usb_ics')
        self.assertTrue(doc['read_only'])
        self.assertEqual(doc['repair_action'], 'None')
        self.assertFalse(doc['notifications_enabled'])
        self.assertEqual(doc['session_policy'], 'LoggedOnUserOnly')
        self.assertTrue(consent.evaluate_grant(raw, context=self.context(), now=TIME))
        self.assertTrue(consent.evaluate_grant(raw, context=self.context(), now=TIME + timedelta(days=6)))
        with self.assertRaises(consent.ConsentRefused):
            consent.evaluate_grant(raw, context=self.context(), now=TIME + timedelta(days=7))
        with self.assertRaises(op.OperatorRefused):
            self.grant(minutes=10081)
        self.assertEqual(op._parser().parse_args(['--enroll-read-only']).expires_minutes, 60)
        parsed = op._parser().parse_args(['--enroll-read-only', '--approve-enrollment',
                                           '--expires-minutes', '10080'])
        self.assertTrue(parsed.approve_enrollment)
        self.assertTrue(parsed.enroll_read_only)

    def test_consents_unique_and_canonical(self):
        a,b=self.grant(),self.grant()
        self.assertNotEqual(json.loads(a)['grant_id'], json.loads(b)['grant_id'])
        self.assertEqual(a,op.canonical_json(json.loads(a)))

    def test_enrollment_refuses_without_flag(self):
        with self.assertRaises(op.OperatorRefused):
            op._operator_action(args(enroll_read_only=True),loader=lambda: None)

    def test_revocation_refuses_without_flag(self):
        with self.assertRaises(op.OperatorRefused):
            op._operator_action(args(revoke_read_only=True),loader=lambda: None)

    def test_live_refuses_without_flag(self):
        reviewed=types.SimpleNamespace(wiring=None)
        loader=lambda: (reviewed,self.context(),None,None,None,None)
        with self.assertRaises(op.OperatorRefused):
            op._operator_action(args(run_count=1),loader=loader)

    def test_live_refuses_bad_cycles(self):
        reviewed=types.SimpleNamespace(wiring=None)
        loader=lambda: (reviewed,self.context(),None,None,None,None)
        for count in (0,21,-1):
            with self.assertRaises(op.OperatorRefused):
                op._operator_action(args(run_count=count,approve_live_read_only=True),loader=loader)

    def test_main_from_unprotected_checkout_denied(self):
        self.assertEqual(op.main(['--audit-installed']),2)

    def test_digest_anchor_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'anchor'
            p.write_bytes(b'a'*64+b'\n')
            self.assertEqual(op.read_admin_pinned_digest(p),'a'*64)
            for content in (b'a'*64,b'A'*64+b'\n',b'not-a-hash\n',b'a'*64+b'\r\n'):
                p.write_bytes(content)
                with self.assertRaises(op.OperatorRefused):
                    op.read_admin_pinned_digest(p)

    def test_program_fails_closed_to_missing_anchor(self):
        with self.assertRaises(op.OperatorRefused):
            op.read_admin_pinned_digest(Path('/nothing/anchor'))

    def test_unsafe_owner_refused(self):
        for sid in ('S-1-5-32-545',SID,'S-1-1-0'):
            with self.assertRaises(trust.InstallTrustRefused):
                trust.reject_ace(sid, ((0,'S-1-5-32-544',0x1f01ff),))

    def test_broad_or_user_write_refused(self):
        for sid in ('S-1-5-32-545','S-1-5-11','S-1-1-0',SID):
            with self.assertRaises(trust.InstallTrustRefused):
                trust.reject_ace('S-1-5-32-544', ((0,sid,0x2),))

    def test_read_execute_allowed(self):
        trust.reject_ace('S-1-5-32-544', ((0,'S-1-5-32-545',0x1200a9),
                                           (0,'S-1-5-18',0x1f01ff)))

    def test_owner_admin_or_trusted_installer(self):
        for owner in trust.PRIVILEGED_SIDS:
            trust.reject_ace(owner, ((0,owner,0x1f01ff),))

    def test_inherited_unknown_ace_denied(self):
        with self.assertRaises(trust.InstallTrustRefused):
            trust.reject_ace('S-1-5-18',((5,'S-1-5-32-545',0x1),))

    def test_generic_write_masks(self):
        for mask in (0x10000000,0x40000000,0x40000,0x80000,0x10000):
            with self.assertRaises(trust.InstallTrustRefused):
                trust.reject_ace('S-1-5-18',((0,SID,mask),))

    def test_installer_source_inventory_includes_cli_and_trust(self):
        for name in ('OnyxV080ReleaseOperator.py','OnyxWindowsProtectedInstallTrust.py'):
            self.assertIn('windows/monitoring/v080/'+name, att.REQUIRED_FILES)

    def test_default_argument_parser_inert(self):
        with self.assertRaises(SystemExit):
            op._parser().parse_args([])
        for flags in (['--run-count','2'],['--enroll-read-only']):
            self.assertIsNotNone(op._parser().parse_args(flags))

    def test_nongrant_audit_does_not_issue_consent(self):
        admission=types.SimpleNamespace(file_count=16,
            wiring=types.SimpleNamespace(manifest=types.SimpleNamespace(source_commit=COMMIT)))
        result=op._operator_action(args(audit_installed=True),
                    loader=lambda: (admission,self.context(),None,None,None,None))
        self.assertEqual(result['mode'],'audit-only')

    def test_explicit_revoke_deletes_only_credential(self):
        called=[]
        fake=types.SimpleNamespace(delete_windows_grant=lambda:called.append('delete'))
        result=op._operator_action(args(revoke_read_only=True,approve_revocation=True),
                                   loader=lambda:(None,None,None,fake,None,None))
        self.assertEqual(called,['delete'])
        self.assertFalse(result['live_monitor_started'])

    def test_isolated_interpreter_guard(self):
        with self.assertRaises(op.OperatorRefused):
            op.require_installed_interpreter(Path('/tmp/ONYX.py'), 'C:\\Python313\\python.exe',
                                              isolated=True,no_bytecode=True)

    def test_classifier_no_native_windows_call(self):
        with patch.object(trust,'_handle_acl',side_effect=AssertionError('native call')):
            trust.reject_ace('S-1-5-18',((0,'S-1-5-32-545',0x1200a9),))


if __name__=='__main__':
    unittest.main()
