"""Phase 18H1 offline-only enrollment fixture contract tests."""
import dataclasses
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
import unittest

MON = Path(__file__).resolve().parents[3] / 'windows' / 'monitoring' / 'v080'
if str(MON) not in sys.path:
    sys.path.insert(0, str(MON))
import OnyxOfflineProductionSupervisor as core
import OnyxOfflineEnrollmentGate as gate

SID = 'S-1-5-21-123-456-789-1001'
NOW = datetime(2026, 11, 13, 16, 0, tzinfo=timezone.utc)


def grant(**updates):
    obj = dict(schema_version=1, simulation_only=True,
               grant_id='grant-20261113-abc', scope='periodic_read_only_usb_ics',
               authorized_sid=SID, source_commit='a' * 40,
               config_sha256='b' * 64, generation=7,
               issued_utc='2026-11-13T15:00:00Z',
               expires_utc='2026-11-14T15:00:00Z',
               storage_profile='release', session_policy='LoggedOnUserOnly',
               read_only=True, repair_action='None', notifications_enabled=False)
    obj.update(updates)
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def sign_fixture(b):
    return hashlib.sha256(b'TEST-ONLY-NOT-A-TRUST-ANCHOR:' + b).digest()


def verify_fixture(b, sig):
    return sig == sign_fixture(b)


def snapshot(**changes):
    b = grant()
    obj = gate.FixtureSnapshot(
        grant_bytes=b, signature_bytes=sign_fixture(b), revocation_floor=7,
        revoked_grant_ids=frozenset(), observed_sid=SID,
        observed_source_commit='a' * 40, observed_config_sha256='b' * 64,
        source_trusted=True, interactive_session=True)
    return dataclasses.replace(obj, **changes)


def for_grant(**updates):
    b = grant(**updates)
    return snapshot(grant_bytes=b, signature_bytes=sign_fixture(b))


class EnrollmentFixtureTests(unittest.TestCase):
    def valid(self, s=None, *, verifier=verify_fixture, now=NOW):
        return gate.evaluate_fixture(s if s is not None else snapshot(),
                                     signature_verifier=verifier, now=now)

    def refused(self, s=None, *, verifier=verify_fixture, now=NOW):
        with self.assertRaises(gate.EnrollmentRefused):
            self.valid(s, verifier=verifier, now=now)

    def test_valid_fixture_no_runtime(self):
        a = self.valid()
        self.assertTrue(a.simulation_only)
        self.assertTrue(a.grant_valid)
    def test_invalid_signature(self): self.refused(snapshot(signature_bytes=b'bad'))
    def test_missing_signature(self): self.refused(snapshot(signature_bytes=b''))
    def test_oversized_signature(self): self.refused(snapshot(signature_bytes=b'X' * 8193))
    def test_verifier_returns_nonbool(self): self.refused(verifier=lambda *args: 1)
    def test_verifier_raises(self): self.refused(verifier=lambda *args: 1/0)
    def test_noncanonical_json(self):
        b = json.dumps(json.loads(grant())).encode()
        self.refused(snapshot(grant_bytes=b, signature_bytes=sign_fixture(b)))
    def test_duplicate_json_property(self):
        b = grant()[:-1] + b',"grant_id":"grant-duplicates"}'
        self.refused(snapshot(grant_bytes=b, signature_bytes=sign_fixture(b)))
    def test_extra_property(self): self.refused(for_grant(unknown='value'))
    def test_missing_property(self):
        b = json.loads(grant()); del b['generation']
        raw = json.dumps(b, sort_keys=True, separators=(',', ':')).encode()
        self.refused(snapshot(grant_bytes=raw, signature_bytes=sign_fixture(raw)))
    def test_oversized_grant(self): self.refused(snapshot(grant_bytes=b'A' * 8193))
    def test_non_utf8(self): self.refused(snapshot(grant_bytes=b'\xff'))
    def test_not_simulation(self): self.refused(for_grant(simulation_only=False))
    def test_invalid_scope(self): self.refused(for_grant(scope='repair'))
    def test_invalid_sid_format(self): self.refused(for_grant(authorized_sid='user'))
    def test_invalid_source_commit(self): self.refused(for_grant(source_commit='bad'))
    def test_invalid_config_digest(self): self.refused(for_grant(config_sha256='bad'))
    def test_disabled_read_only(self): self.refused(for_grant(read_only=False))
    def test_automated_repairs(self): self.refused(for_grant(repair_action='Restart'))
    def test_notifications_enabled(self): self.refused(for_grant(notifications_enabled=True))
    def test_dev_storage(self): self.refused(for_grant(storage_profile='development'))
    def test_signed_out_policy(self): self.refused(for_grant(session_policy='Always'))
    def test_revocation_floor(self): self.refused(snapshot(revocation_floor=8))
    def test_revocation_id(self): self.refused(snapshot(revoked_grant_ids=frozenset({'grant-20261113-abc'})))
    def test_bad_revocation_type(self): self.refused(snapshot(revocation_floor=True))
    def test_wrong_identity(self): self.refused(snapshot(observed_sid='S-1-5-21-1-2-3-4'))
    def test_wrong_source(self): self.refused(snapshot(observed_source_commit='c'*40))
    def test_wrong_config(self): self.refused(snapshot(observed_config_sha256='c'*64))
    def test_untrusted_source(self): self.refused(snapshot(source_trusted=False))
    def test_noninteractive(self): self.refused(snapshot(interactive_session=False))
    def test_expired(self): self.refused(now=datetime(2026,11,15,tzinfo=timezone.utc))
    def test_future_grant(self): self.refused(now=datetime(2026,11,12,tzinfo=timezone.utc))
    def test_unauthenticated_clock(self): self.refused(now=datetime(2026,11,13))
    def test_too_long_expiry(self): self.refused(for_grant(expires_utc='2026-12-01T15:00:00Z'))
    def test_invalid_grant_generation_bool(self): self.refused(for_grant(generation=True))
    def test_invalid_revoked_ids(self): self.refused(snapshot(revoked_grant_ids={'x'}))
    def test_missing_verifier(self): self.refused(verifier=None)

    def test_revocation_rechecked_before_each_cycle(self):
        calls = {'snap': 0, 'work': 0}
        def get_snap():
            calls['snap'] += 1
            if calls['snap'] == 2:
                return snapshot(revocation_floor=8)
            return snapshot()
        def work(): calls['work'] += 1
        times = iter([0, 1, 120, 121])
        @contextmanager
        def lock(): yield
        with self.assertRaises(gate.EnrollmentRefused):
            gate.simulate_enrollment_supervision(
                core.Policy(maximum_cycles=3), snapshot_reader=get_snap,
                signature_verifier=verify_fixture, utc_clock=lambda: NOW,
                fixture_cycle=work, monotonic=lambda: next(times),
                sleep=lambda _: None, exclusive=lock)
        self.assertEqual(calls['work'], 1)
        self.assertEqual(calls['snap'], 2)

    def test_two_bounded_fixture_cycles(self):
        calls = []
        times = iter([0, 1, 120, 121])
        @contextmanager
        def lock():
            calls.append('entered')
            try: yield
            finally: calls.append('released')
        result = gate.simulate_enrollment_supervision(
            core.Policy(maximum_cycles=2), snapshot_reader=snapshot,
            signature_verifier=verify_fixture, utc_clock=lambda: NOW,
            fixture_cycle=lambda: calls.append('cycle'),
            monotonic=lambda: next(times), sleep=lambda x: calls.append('sleep'),
            exclusive=lock)
        self.assertEqual(result.cycles, 2)
        self.assertEqual(calls, ['entered', 'cycle', 'sleep', 'cycle', 'released'])
        self.assertTrue(result.simulation_only)
        self.assertFalse(result.live_probes)

    def test_missing_lock_refused(self):
        with self.assertRaises(gate.EnrollmentRefused):
            gate.simulate_enrollment_supervision(
                core.Policy(), snapshot_reader=snapshot, signature_verifier=verify_fixture,
                utc_clock=lambda: NOW, fixture_cycle=lambda:None,
                monotonic=lambda:0., sleep=lambda _:None, exclusive=None)

    def test_inert_status_no_authorization(self):
        info=gate.inert_status()
        self.assertFalse(info['real_signing_anchor'])
        self.assertFalse(info['production_runtime_enabled'])
        self.assertEqual(info['release_status'], 'HOLD')

    def test_cli_inert(self):
        from unittest.mock import patch
        with patch('sys.argv', ['module', '--check-inert']):
            self.assertEqual(gate.main(), 0)
        with patch('sys.argv', ['module']):
            with self.assertRaises(SystemExit): gate.main()

if __name__ == '__main__': unittest.main()
