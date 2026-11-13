"""Offline Phase 18K1 attestation/consent binding tests; no Windows API calls."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve()
MODULES = HERE.parents[3] / 'windows' / 'monitoring' / 'v080'
# Also accept package-isolated development tests when source location differs.
if not MODULES.is_dir():
    MODULES = HERE.parents[3] / 'windows' / 'monitoring' / 'v080'
sys.path.insert(0, str(MODULES))
import OnyxWindowsRuntimeAttestation as att  # noqa: E402
import OnyxWindowsUserConsent as consent  # noqa: E402

SID = 'S-1-5-21-1-2-3-4'
COMMIT = 'a' * 40
NOW = datetime(2026, 11, 13, 18, tzinfo=timezone.utc)


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'windows' / 'monitoring' / 'monitoring.release.json'
        self.config.parent.mkdir(parents=True)
        self.config.write_bytes(b'{"test":"release-config"}')
        self.hashes = {}
        for rel in att.REQUIRED_FILES:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            content = ('trusted:' + rel).encode()
            path.write_bytes(content)
            self.hashes[rel] = hashlib.sha256(content).hexdigest()
        self.manifest = att.ReleaseManifest(COMMIT, self.hashes, hashlib.sha256(self.config.read_bytes()).hexdigest())
        self.grant = {
            'schema_version': 1, 'grant_id': '1' * 32, 'sid': SID, 'source_commit': COMMIT,
            'config_sha256': self.manifest.config_sha256,
            'scope': 'periodic_read_only_usb_ics', 'issued_utc': '2026-11-13T17:00:00Z',
            'expires_utc': '2026-11-13T19:00:00Z', 'read_only': True,
            'repair_action': 'None', 'storage_profile': 'release',
            'session_policy': 'LoggedOnUserOnly', 'notifications_enabled': False,
        }

    def make_authorizer(self, **kw):
        defaults = dict(root=self.root, manifest=self.manifest, config=self.config,
                        approved_sid=SID, read=lambda: canon(self.grant),
                        sid_provider=lambda: SID, console_provider=lambda: True,
                        now=lambda: NOW)
        defaults.update(kw)
        return att.build_rechecking_authorizer(**defaults)

    def test_end_to_end_offline_consent_source_session(self):
        self.assertIs(self.make_authorizer()(), True)

    def test_mutated_source_refused(self):
        callback = self.make_authorizer()
        self.assertTrue(callback())
        (self.root / att.REQUIRED_FILES[0]).write_bytes(b'UNTRUSTED')
        with self.assertRaises(att.AttestationRefused):
            callback()

    def test_mutated_config_refused(self):
        self.assertTrue(self.make_authorizer()())
        self.config.write_bytes(b'CHANGED')
        with self.assertRaises(att.AttestationRefused):
            self.make_authorizer()()

    def test_wrong_sid_refused_before_manifest(self):
        seen = []
        def check(**kw):
            seen.append(kw)
        cb = self.make_authorizer(sid_provider=lambda: 'S-1-5-21-1-2-3-5', source_checker=check)
        with self.assertRaises(att.AttestationRefused):
            cb()
        self.assertEqual(seen, [])

    def test_wrong_console_refused_before_source(self):
        seen = []
        cb = self.make_authorizer(console_provider=lambda: False,
                                  source_checker=lambda **kw: seen.append(kw))
        with self.assertRaises(att.AttestationRefused):
            cb()
        self.assertEqual(seen, [])

    def test_console_result_nonbool_denied(self):
        with self.assertRaises(att.AttestationRefused):
            self.make_authorizer(console_provider=lambda: 1)()

    def test_missing_credential_fails_closed(self):
        with self.assertRaises(consent.ConsentRefused):
            self.make_authorizer(read=lambda: (_ for _ in ()).throw(consent.ConsentRefused('absent')))()

    def test_revocation_detected_next_call(self):
        state = {'grant': canon(self.grant)}
        def reader():
            if state['grant'] is None:
                raise consent.ConsentRefused('revoked')
            return state['grant']
        cb = self.make_authorizer(read=reader)
        self.assertTrue(cb())
        state['grant'] = None
        with self.assertRaises(consent.ConsentRefused):
            cb()

    def test_expired_grant_denied(self):
        self.grant['expires_utc'] = '2026-11-13T17:30:00Z'
        with self.assertRaises(consent.ConsentRefused):
            self.make_authorizer()()

    def test_grant_source_mismatch_denied(self):
        self.grant['source_commit'] = 'b' * 40
        with self.assertRaises(consent.ConsentRefused):
            self.make_authorizer()()

    def test_grant_config_mismatch_denied(self):
        self.grant['config_sha256'] = 'b' * 64
        with self.assertRaises(consent.ConsentRefused):
            self.make_authorizer()()

    def test_source_link_rejected(self):
        target = self.root / att.REQUIRED_FILES[0]
        replacement = target.with_suffix('.reference')
        target.rename(replacement)
        try:
            target.symlink_to(replacement)
        except (OSError, NotImplementedError):
            self.skipTest('host disallows symlink fixture')
        with self.assertRaises(att.AttestationRefused):
            self.make_authorizer()()

    def test_source_file_deleted(self):
        (self.root / att.REQUIRED_FILES[0]).unlink()
        with self.assertRaises(att.AttestationRefused):
            self.make_authorizer()()

    def test_config_outside_source_rejected(self):
        outside = self.root / 'other.json'
        outside.write_bytes(self.config.read_bytes())
        with self.assertRaises(att.AttestationRefused):
            self.make_authorizer(config=outside)()

    def test_extra_source_manifest_rejected(self):
        hashes = dict(self.hashes)
        hashes['unexpected'] = 'a' * 64
        with self.assertRaises(att.AttestationRefused):
            att.ReleaseManifest(COMMIT, hashes, self.manifest.config_sha256)

    def test_invalid_manifest_digests_rejected(self):
        with self.assertRaises(att.AttestationRefused):
            att.ReleaseManifest('a' * 39, self.hashes, self.manifest.config_sha256)
        with self.assertRaises(att.AttestationRefused):
            att.ReleaseManifest(COMMIT, self.hashes, 'A' * 64)

    def test_invalid_approved_sid_rejected(self):
        with self.assertRaises(Exception):
            self.make_authorizer(approved_sid='env:MY_SID')()

    def test_authorizer_no_read_if_sid_invalid(self):
        calls = []
        cb = self.make_authorizer(read=lambda: calls.append('read') or canon(self.grant),
                                  sid_provider=lambda: 'S-1-5-21-1-2-3-5')
        with self.assertRaises(att.AttestationRefused):
            cb()
        self.assertEqual(calls, [])

    def test_missing_adapter_refused(self):
        with self.assertRaises(att.AttestationRefused):
            self.make_authorizer(console_provider=None)

    def test_non_windows_native_probe_refused(self):
        if sys.platform == 'win32':
            self.skipTest('Windows native probe requires separate authorization')
        with self.assertRaises(att.AttestationRefused):
            att._native_active_console()

    def test_cli_inert(self):
        self.assertEqual(att.main(['--check-inert']), 0)
        with self.assertRaises(SystemExit):
            att.main([])

    def test_source_checker_failure_refuses(self):
        cb = self.make_authorizer(source_checker=lambda **kw: (_ for _ in ()).throw(att.AttestationRefused('ACL denied')))
        with self.assertRaises(att.AttestationRefused):
            cb()


if __name__ == '__main__':
    unittest.main()
