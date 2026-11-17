#!/usr/bin/env python3
"""ONYX CORE v0.8.0 Phase 18H1: simulation-only signed-enrollment gate.

No runtime trust anchor, grant issuer, enrollment reader, native token inspection,
mutex, processes, telemetry, network, tasks, notifications, or persistent IO.
Only an explicitly injected OFFLINE signature verifier can evaluate fixtures.
Passing this gate grants absolutely no Windows or production privileges.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import json
import re
from typing import Callable, ContextManager

import OnyxOfflineProductionSupervisor as m18c


class EnrollmentRefused(ValueError):
    """Fixture enrollment missing, malformed, untrusted or revoked."""


GRANT_FIELDS = frozenset({
    'schema_version', 'simulation_only', 'grant_id', 'scope', 'authorized_sid',
    'source_commit', 'config_sha256', 'generation', 'issued_utc', 'expires_utc',
    'storage_profile', 'session_policy', 'read_only', 'repair_action',
    'notifications_enabled',
})
SHA256 = re.compile(r'[0-9a-f]{64}\Z')
SHA40 = re.compile(r'[0-9a-f]{40}\Z')
GRANT_ID = re.compile(r'[a-z0-9][a-z0-9-]{7,63}\Z')
SID = re.compile(r'S-1-5-21-(?:[0-9]{1,10}-){3}[0-9]{1,10}\Z')
MAX_BYTES = 8192
MAX_SIGNATURE_BYTES = 8192


@dataclass(frozen=True)
class FixtureSnapshot:
    """Untrusted synthetic inputs, NOT an attested OS security snapshot."""
    grant_bytes: bytes
    signature_bytes: bytes
    revocation_floor: int
    revoked_grant_ids: frozenset[str]
    observed_sid: str
    observed_source_commit: str
    observed_config_sha256: str
    source_trusted: bool
    interactive_session: bool


def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EnrollmentRefused('duplicate grant field')
        result[key] = value
    return result


def _reject_nonfinite(_):
    raise EnrollmentRefused('nonfinite grant value')


def _canonical_grant(raw: bytes) -> dict:
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES:
        raise EnrollmentRefused('invalid grant size')
    try:
        grant = json.loads(raw.decode('utf-8', 'strict'),
                           object_pairs_hook=_reject_duplicates,
                           parse_constant=_reject_nonfinite)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise EnrollmentRefused('grant JSON invalid') from exc
    if type(grant) is not dict or set(grant) != GRANT_FIELDS:
        raise EnrollmentRefused('grant schema mismatch')
    if raw != json.dumps(grant, sort_keys=True, ensure_ascii=True,
                         separators=(',', ':'), allow_nan=False).encode('ascii'):
        raise EnrollmentRefused('grant is not canonical signed bytes')
    return grant


def _utc(text: str) -> datetime:
    if type(text) is not str or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', text):
        raise EnrollmentRefused('invalid UTC timestamp')
    try:
        value = datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise EnrollmentRefused('invalid UTC timestamp') from exc
    return value


def evaluate_fixture(snapshot: FixtureSnapshot,
                     *, signature_verifier: Callable[[bytes, bytes], bool],
                     now: datetime) -> m18c.Admission:
    """Check strict fixture data every cycle, using INJECTED fake signature trust.

    The signature_verifier is intentionally NOT provided in this module. A
    caller-controlled verifier is not a real production trust anchor.
    """
    if not isinstance(snapshot, FixtureSnapshot) or not callable(signature_verifier):
        raise EnrollmentRefused('missing synthetic evidence or verifier')
    if type(snapshot.signature_bytes) is not bytes or not (1 <= len(snapshot.signature_bytes) <= MAX_SIGNATURE_BYTES):
        raise EnrollmentRefused('invalid signature fixture')
    grant = _canonical_grant(snapshot.grant_bytes)
    if (type(grant['schema_version']) is not int or grant['schema_version'] != 1
            or grant['simulation_only'] is not True):
        raise EnrollmentRefused('live grants are not supported')
    if (type(grant['grant_id']) is not str or not GRANT_ID.fullmatch(grant['grant_id'])
            or grant['scope'] != 'periodic_read_only_usb_ics'):
        raise EnrollmentRefused('grant scope/id invalid')
    if (type(grant['authorized_sid']) is not str or not SID.fullmatch(grant['authorized_sid'])
            or type(grant['source_commit']) is not str or not SHA40.fullmatch(grant['source_commit'])
            or type(grant['config_sha256']) is not str or not SHA256.fullmatch(grant['config_sha256'])):
        raise EnrollmentRefused('grant identifiers invalid')
    if (grant['storage_profile'] != 'release' or
            grant['session_policy'] != 'LoggedOnUserOnly' or
            grant['read_only'] is not True or grant['repair_action'] != 'None' or
            grant['notifications_enabled'] is not False):
        raise EnrollmentRefused('unsafe grant capabilities')
    if type(grant['generation']) is not int or not 1 <= grant['generation'] < 2**31:
        raise EnrollmentRefused('invalid grant generation')
    if (type(snapshot.revocation_floor) is not int or
            not 1 <= snapshot.revocation_floor < 2**31 or
            type(snapshot.revoked_grant_ids) is not frozenset or
            any(type(x) is not str for x in snapshot.revoked_grant_ids)):
        raise EnrollmentRefused('invalid revocation evidence')
    if not (type(snapshot.observed_sid) is str and SID.fullmatch(snapshot.observed_sid) and
            type(snapshot.observed_source_commit) is str and SHA40.fullmatch(snapshot.observed_source_commit) and
            type(snapshot.observed_config_sha256) is str and SHA256.fullmatch(snapshot.observed_config_sha256) and
            snapshot.source_trusted is True and snapshot.interactive_session is True):
        raise EnrollmentRefused('synthetic attestation invalid')
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
        raise EnrollmentRefused('missing aware clock')
    now = now.astimezone(timezone.utc)
    issued, expires = _utc(grant['issued_utc']), _utc(grant['expires_utc'])
    if not (issued <= now < expires and timedelta(seconds=1) <= expires - issued <= timedelta(days=7)):
        raise EnrollmentRefused('grant not valid at synthetic clock')
    try:
        signature_ok = signature_verifier(snapshot.grant_bytes, snapshot.signature_bytes)
    except Exception as exc:
        raise EnrollmentRefused('signature-verifier failure') from exc
    if signature_ok is not True:
        raise EnrollmentRefused('invalid synthetic detached signature')
    if grant['generation'] < snapshot.revocation_floor or grant['grant_id'] in snapshot.revoked_grant_ids:
        raise EnrollmentRefused('grant revoked')
    if grant['authorized_sid'] != snapshot.observed_sid:
        raise EnrollmentRefused('synthetic Windows identity mismatch')
    if grant['source_commit'] != snapshot.observed_source_commit or grant['config_sha256'] != snapshot.observed_config_sha256:
        raise EnrollmentRefused('synthetic code/config provenance mismatch')
    return m18c.Admission(simulation_only=True, revision_matches=True,
                          identity_matches=True, storage_profile_release=True,
                          grant_valid=True, revoked=False, source_trusted=True)


def simulate_enrollment_supervision(policy: m18c.Policy, *,
        snapshot_reader: Callable[[], FixtureSnapshot],
        signature_verifier: Callable[[bytes, bytes], bool],
        utc_clock: Callable[[], datetime],
        fixture_cycle: Callable[[], object],
        monotonic: Callable[[], float],
        sleep: Callable[[float], None],
        exclusive: Callable[[], ContextManager[None]]) -> m18c.Result:
    """Reevaluate signature, revocation, and source identity on EVERY fixture cycle.

    This calls ONLY the simulation loop, never OnyxLiveConnectivity or the
    Windows-native mutex. A real authorizer/attestor/launcher does not exist.
    """
    if not all(callable(x) for x in (snapshot_reader, signature_verifier, utc_clock,
                                     fixture_cycle, monotonic, sleep, exclusive)):
        raise EnrollmentRefused('synthetic adapters required')
    def admission() -> m18c.Admission:
        return evaluate_fixture(snapshot_reader(), signature_verifier=signature_verifier,
                                now=utc_clock())
    return m18c.simulate_bounded_supervision(
        policy, admission=admission, fixture_cycle=fixture_cycle,
        monotonic=monotonic, sleep=sleep, exclusive=exclusive)


def inert_status() -> dict:
    return {'phase': '18H1', 'simulation_only': True,
            'real_signing_anchor': False, 'real_enrollment_issuer': False,
            'os_source_attestor': False, 'production_runtime_enabled': False,
            'live_probes': False, 'tasks_created': False,
            'notifications_enabled': False, 'release_status': 'HOLD'}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check-inert', required=True, action='store_true')
    p.parse_args(argv)
    print(json.dumps(inert_status(), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
