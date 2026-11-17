"""Phase 18J1: only offline injected evidence, no OS credential access."""
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
MON = ROOT / 'windows' / 'monitoring' / 'v080'
if str(MON) not in sys.path:
    sys.path.insert(0, str(MON))
import OnyxWindowsUserConsent as consent

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
SID = 'S-1-5-21-123-456-789-1001'
COMMIT = 'a' * 40
CONFIG = 'b' * 64


def grant(**kw):
    data = dict(schema_version=1, grant_id='c'*32, sid=SID, source_commit=COMMIT,
                config_sha256=CONFIG, scope='periodic_read_only_usb_ics',
                issued_utc='2026-11-13T11:00:00Z', expires_utc='2026-11-14T11:00:00Z',
                read_only=True, repair_action='None', storage_profile='release',
                session_policy='LoggedOnUserOnly', notifications_enabled=False)
    data.update(kw)
    return json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()


CTX = consent.VerifiedContext(SID, COMMIT, CONFIG, True, True)
UNSPECIFIED = object()


class UserConsentTests(unittest.TestCase):
    def checked(self, raw=UNSPECIFIED, ctx=CTX, now=NOW):
        return consent.evaluate_grant(grant() if raw is UNSPECIFIED else raw, context=ctx, now=now)

    def test_valid_fixture(self):
        self.assertTrue(self.checked())

    def test_no_windows_reads_on_import(self):
        self.assertFalse(consent.inert_status()['live_runtime_enabled'])

    def test_cli_inert(self):
        self.assertEqual(consent.main(['--check-inert']), 0)
        with self.assertRaises(SystemExit): consent.main(['--live'])
        with self.assertRaises(SystemExit): consent.main(['--issue'])
        with self.assertRaises(SystemExit): consent.main(['--revoke'])

    def test_missing_and_nonbytes(self):
        for bad in (None, {}, '', b'', b' '* (consent.MAX_BLOB + 1)):
            with self.subTest(bad=type(bad).__name__), self.assertRaises(consent.ConsentRefused):
                self.checked(raw=bad)

    def test_duplicate_property(self):
        with self.assertRaises(consent.ConsentRefused):
            self.checked(raw=grant()[:-1] + b',"schema_version":1}')

    def test_noncanonical(self):
        with self.assertRaises(consent.ConsentRefused):
            self.checked(raw=json.dumps(json.loads(grant())).encode())

    def test_extra_missing_property(self):
        for raw in (grant(extra=1), json.dumps({k:v for k,v in json.loads(grant()).items() if k != 'scope'}, sort_keys=True, separators=(',', ':')).encode()):
            with self.subTest(raw=raw[-20:]), self.assertRaises(consent.ConsentRefused):
                self.checked(raw=raw)

    def test_non_utf8(self):
        with self.assertRaises(consent.ConsentRefused): self.checked(raw=b'\xff')

    def test_invalid_semantics(self):
        cases = [
            {'schema_version':True}, {'schema_version':0}, {'grant_id':'bad'},
            {'sid':'S-1-5-18'}, {'source_commit':'bad'}, {'config_sha256':'bad'},
            {'scope':'repair'}, {'read_only':1}, {'read_only':False},
            {'repair_action':'RestartAdapter'}, {'storage_profile':'development'},
            {'session_policy':'AnyUser'}, {'notifications_enabled':True},
            {'notifications_enabled':0},
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(consent.ConsentRefused):
                self.checked(raw=grant(**case))

    def test_expired(self):
        with self.assertRaises(consent.ConsentRefused):
            self.checked(now=NOW + timedelta(days=2))

    def test_future(self):
        with self.assertRaises(consent.ConsentRefused):
            self.checked(raw=grant(issued_utc='2026-11-14T11:00:00Z',
                                   expires_utc='2026-11-15T11:00:00Z'))

    def test_unbounded_expiry(self):
        with self.assertRaises(consent.ConsentRefused):
            self.checked(raw=grant(expires_utc='2026-11-25T11:00:00Z'))

    def test_clock_invalid(self):
        for time in (None, 1, NOW.replace(tzinfo=None)):
            with self.assertRaises(consent.ConsentRefused): self.checked(now=time)

    def test_context_identity_mismatch(self):
        for changed in [dict(process_sid='wrong'), dict(source_commit='0'*40),
                        dict(config_sha256='0'*64), dict(source_trusted=False),
                        dict(active_user_session=False), dict(active_user_session=1)]:
            with self.subTest(changed=changed), self.assertRaises(consent.ConsentRefused):
                self.checked(ctx=replace(CTX, **changed))

    def test_missing_attestation(self):
        with self.assertRaises(consent.ConsentRefused): self.checked(ctx=None)

    def test_non_windows_credread_refused(self):
        if os.name == 'nt': self.skipTest('Only use an isolated Windows host test')
        with self.assertRaises(consent.ConsentRefused): consent.read_windows_grant()

    def test_non_windows_credwrite_refused(self):
        if os.name == 'nt': self.skipTest('Never write actual credentials in tests')
        with self.assertRaises(consent.ConsentRefused): consent.write_windows_grant(grant())

    def test_non_windows_delete_refused(self):
        if os.name == 'nt': self.skipTest('Never delete actual credentials in tests')
        with self.assertRaises(consent.ConsentRefused): consent.delete_windows_grant()

    def test_authorizer_rechecks_every_call(self):
        count = [0]
        def read():
            count[0] += 1
            if count[0] == 2:
                raise consent.ConsentRefused('revoked')
            return grant()
        hook = consent.make_reader_authorizer(get_context=lambda: CTX,
                                               now=lambda: NOW, read=read)
        self.assertTrue(hook())
        with self.assertRaises(consent.ConsentRefused): hook()
        self.assertEqual(count[0], 2)

    def test_authorizer_refuses_nonbool_or_bad_adapters(self):
        with self.assertRaises(consent.ConsentRefused):
            consent.make_reader_authorizer(get_context=None, now=lambda: NOW)
        with self.assertRaises(consent.ConsentRefused):
            consent.make_reader_authorizer(get_context=lambda: CTX, now=None)


if __name__ == '__main__': unittest.main()
