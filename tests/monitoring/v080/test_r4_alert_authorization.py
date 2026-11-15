"""Pure R4 alert-consent validation tests; NO network, filesystem or credentials."""
import importlib.util
from pathlib import Path
import sys, unittest
from datetime import datetime,timezone,timedelta

MODULE = Path(__file__).resolve().parents[3] / 'windows'/'monitoring'/'v080'/'OnyxV080AlertAuthorization.py'
spec=importlib.util.spec_from_file_location('OnyxV080AlertAuthorization',MODULE)
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)

NOW=datetime(2026,11,14,21,0,0,tzinfo=timezone.utc)
COMMIT='a'*40
SID='S-1-5-21-123-456-789-1000'
ENDPOINT=b'https://example.test/private/secret'


def grant(**changes):
    value=dict(schema_version=1,approved=True,scope='foreground_incident_notifications',
        source_commit=COMMIT,sid=SID,provider='ntfy',destination_sha256=m.destination_digest(ENDPOINT),
        issued_utc='2026-11-14T20:00:00Z',expires_utc='2026-11-14T22:00:00Z',
        event_types=['Opened','Recovered'],storage_profile='release',notifications_enabled=True)
    value.update(changes)
    return value


def context(**changes):
    val=dict(source_commit=COMMIT,process_sid=SID,source_trusted=True,
             active_console=True,release_storage=True)
    val.update(changes)
    return m.AlertContext(**val)


class R4AlertTests(unittest.TestCase):
    def call(self,g=None,c=None,evt='Opened',provider='ntfy',endpoint=ENDPOINT,now=NOW):
        return m.permit_event(grant=g if g is not None else grant(),
                              context=c if c is not None else context(),
                              event_type=evt,provider=provider,endpoint=endpoint,now=now)
    def test_opened(self): self.assertIs(self.call(),True)
    def test_recovered(self): self.assertIs(self.call(evt='Recovered'),True)
    def test_reject_not_issued(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(g=grant(approved=False))
    def test_reject_disabled(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(g=grant(notifications_enabled=False))
    def test_reject_bogus_schema(self):
        for a in (0,True,2,'1'):
            with self.subTest(value=a), self.assertRaises(m.AlertConsentRefused): self.call(g=grant(schema_version=a))
    def test_reject_extra_fields(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(g=grant(debug=True))
    def test_reject_storage_mismatch(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(g=grant(storage_profile='development'))
    def test_reject_scope_mismatch(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(g=grant(scope='monitor'))
    def test_reject_sid_change(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(g=grant(sid='S-1-5-18'))
    def test_reject_source_change(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(g=grant(source_commit='b'*40))
    def test_reject_missing_attestation(self):
        for attr in ('source_trusted','active_console','release_storage'):
            with self.subTest(attr=attr), self.assertRaises(m.AlertConsentRefused): self.call(c=context(**{attr:False}))
    def test_reject_nonbool_attestation(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(c=context(active_console=1))
    def test_reject_provider_change(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(provider='json')
    def test_reject_destination_change(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(endpoint=b'https://example.test/attacker')
    def test_reject_changed_event(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(evt='Changed')
    def test_reject_changed_event_list(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(g=grant(event_types=['Opened']))
    def test_reject_expired(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(now=NOW+timedelta(hours=2))
    def test_reject_not_yet_valid(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(now=NOW-timedelta(hours=3))
    def test_reject_long_grant(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(g=grant(expires_utc='2026-11-16T00:00:00Z'))
    def test_reject_naive_now(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(now=NOW.replace(tzinfo=None))
    def test_reject_invalid_time(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(g=grant(expires_utc='2026-11-14T22:00:00+00:00'))
    def test_reject_wrong_type_destination(self):
        with self.assertRaises(m.AlertConsentRefused): self.call(endpoint='https://example.test/secret')
    def test_cli_inert(self):
        import contextlib,io
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream): self.assertEqual(m.main(['--check-inert']),0)
        self.assertIn('"live_webhooks_enabled": false',stream.getvalue())
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            m.main(['--watch'])


if __name__=='__main__': unittest.main()
