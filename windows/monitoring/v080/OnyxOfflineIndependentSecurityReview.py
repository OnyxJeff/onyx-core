"""ONYX CORE R6: deterministic, OFFLINE independent security disposition.

This is an evidence *classification* model, not a verification of Windows,
physical clocks, protected files, identity, release state or a live service.
Neither the input records nor the output confer operational authorization.
No file, network, process, notification, clock, scheduler or OS access.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

SOURCE = 'OnyxV080R6OfflineIndependentSecurityReview'
SCHEMA = 'onyx-r6-offline-review-v1'
PROVENANCE = 'SyntheticEvidenceOnly'
PARENT_COMMIT = '7f22513e82c2a27dcbddad9a8e1d3203ae75e2d4'
MAX_BYTES = 65536
KNOWN_SKIP = ('test_offline_supervisor.SyntheticSupervisorTests.'
              'test_rejects_symlinked_fixture_directory')
COMPONENT_FILES = {
    'R1': 'windows/monitoring/v080/OnyxOfflineWindowsTrustContract.py',
    'R2': 'windows/monitoring/v080/OnyxOfflineExecutionEvidenceContract.py',
    'R3': 'windows/monitoring/v080/OnyxOfflineIncidentJournal.py',
    'R4': 'windows/monitoring/v080/OnyxOfflineOperatorDelivery.py',
    'R5': 'windows/monitoring/v080/OnyxOfflineLifecycleTiming.py',
}
COMPONENT_SHA256 = {
    'R1': 'BA2680AA5ADC6BD50C706CEB48D449E383B54622099FCA4B6E41547528C16346',
    'R2': '1F3E2E821CB85EBC7A40248F891244FB7713D7204C0DE512B50184F3BE2DFAED',
    'R3': '34DF68AB39F44C821B697CF2425D7C1718C784DD41FFDAFE80BBDBA610BCD3A9',
    'R4': 'D4883EEF3D518A97DCBB19A6707C81384C6F97863A0FC9AA7A517AE694A7BFA3',
    'R5': '66CB5A974985248396E8D4F6392FC0FDE71F2A75BAE52B3066E32536C9FA19F6',
}

# Independent expected *negative capability* signatures. These are exact
# schema contracts, not trusted proof that the underlying source never does IO.
COMMON = {'simulation_only': True, 'runtime_enabled': False,
          'live_probe_authorized': False, 'task_creation_authorized': False,
          'store_modified': False, 'repair_action': 'None'}
MODULE_INERT = {
    'R1': dict(COMMON, source='OnyxV080R1SyntheticWindowsTrust',
               identity_authenticated_in_windows=False,
               windows_acls_verified=False, revocation_authoritative=False,
               enrollment_authorized=False, notification_enabled=False,
               delivery_permitted=False),
    'R2': dict(COMMON, source='OnyxV080R2SyntheticExecutionEvidence',
               notification_enabled=False, delivery_permitted=False,
               read_only=True, windows_job_attested=False, clock_attested=False,
               evidence_authentic=False),
    'R3': dict(COMMON, source='OnyxV080R3SyntheticIncidentJournal',
               provenance='SyntheticTemporaryFixtureOnly',
               enrollment_authorized=False, notification_enabled=False,
               delivery_permitted=False, real_store_authorized=False,
               temp_fixture_only=True),
    'R4': dict(COMMON, source='OnyxV080R4SyntheticOperatorDelivery',
               provenance='SyntheticTemporaryFixtureOnly',
               enrollment_authorized=False, notification_enabled=False,
               delivery_permitted=False, real_store_authorized=False,
               identity_authenticated_in_windows=False,
               revocation_authoritative=False, task_created=False,
               transport_calls=0, temp_fixture_only=True),
    'R5': dict(COMMON, source='OnyxV080R5SyntheticLifecycleTiming',
               provenance='SyntheticInputOnly', notification_enabled=False,
               delivery_permitted=False, real_store_authorized=False,
               identity_authenticated_in_windows=False,
               windows_clock_attested=False, scheduler_started=False,
               worker_spawned=False, transport_calls=0),
}

# Source-traceable risks from M5_SECURITY_AUDIT and R1-R5 contracts. R3-R5
# reduce synthetic-design risk, but do not close real Windows release gates.
FINDINGS = (
    ('SEC-01', 'BLOCKED', 'R1', 'Authenticated and independently revocable per-cycle operator consent'),
    ('SEC-02', 'BLOCKED', 'R1', 'Verified Windows token, real ancestor DACL and race-safe source binding'),
    ('SEC-03', 'BLOCKED', 'R2', 'Real Windows worker containment and descendant termination evidence'),
    ('SEC-04', 'BLOCKED', 'R2', 'Trusted read-only v0.8 evidence adapter isolated from both v0.7 histories'),
    ('SEC-05', 'BLOCKED', 'R2,R5', 'Authenticated live observation and host/monotonic clock evidence'),
    ('SEC-06', 'BLOCKED', 'R3,R4', 'Tamper-resistant crash-safe v0.8 incident/intent state and authentic provenance'),
    ('SEC-07', 'BLOCKED', 'R1,R4', 'Authenticated operator actions and safe live view authorization'),
    ('SEC-08', 'BLOCKED', 'R4,R5', 'Opt-in authentic delivery provider, delivery ledger and consent'),
    ('SEC-09', 'OPEN TEST GAP', 'M2A', 'Independently exercise skipped Windows symlink attack test'),
    ('SEC-10', 'BLOCKED', 'R5', 'Independently measured scheduler overlap, deadline, restart and real jitter'),
)

class OfflineSecurityError(ValueError):
    """Invalid or misleading offline evidence; no positive release inference."""


def _need(condition: bool, reason: str) -> None:
    if not condition:
        raise OfflineSecurityError(reason)


def _keys(obj: Any, required: set[str], label: str) -> dict:
    _need(type(obj) is dict and set(obj) == required, f'{label}: exact keys required')
    return obj


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        _need(key not in result, 'duplicate JSON property')
        result[key] = value
    return result


def _no_constant(_token: str) -> None:
    raise OfflineSecurityError('nonfinite JSON not permitted')


def parse_evidence(raw: bytes) -> dict:
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES,
          'offline JSON input size or type invalid')
    try:
        return json.loads(raw.decode('utf-8', errors='strict'),
                          object_pairs_hook=_strict_pairs, parse_constant=_no_constant)
    except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
        raise OfflineSecurityError('malformed offline evidence JSON') from exc


def example_evidence() -> dict:
    """A TEST FIXTURE. These constants are NOT a measured host observation."""
    return {'schema': SCHEMA, 'source': SOURCE, 'provenance': PROVENANCE,
            'simulation_only': True, 'parent_commit': PARENT_COMMIT,
            'components': copy.deepcopy(MODULE_INERT),
            'component_hash_claims': dict(COMPONENT_SHA256),
            'test_results': {'discovered': 771, 'passed': 770, 'failures': 0,
                             'errors': 0, 'skipped_ids': [KNOWN_SKIP]},
            'live_evidence': [], 'operator_authorization': False,
            'requested_verdict': 'NO-GO'}


def assess_offline_evidence(evidence: dict) -> dict:
    """Verify synthetic claim consistency; ALWAYS return live-release NO-GO.

    Do not treat hash strings, test counts or status JSON supplied by a caller
    as independently verified Windows/source evidence. The SQUALL installer
    independently hashes files and executes the tests before accepting R6.
    """
    _keys(evidence, {'schema', 'source', 'provenance', 'simulation_only',
                     'parent_commit', 'components', 'component_hash_claims',
                     'test_results', 'live_evidence', 'operator_authorization',
                     'requested_verdict'}, 'audit evidence')
    for key, expected in (('schema', SCHEMA), ('source', SOURCE),
                          ('provenance', PROVENANCE), ('simulation_only', True),
                          ('parent_commit', PARENT_COMMIT),
                          ('operator_authorization', False),
                          ('requested_verdict', 'NO-GO')):
        _need(type(evidence[key]) is type(expected) and evidence[key] == expected,
              f'forged/mismatched {key}')
    _need(type(evidence['live_evidence']) is list and
          len(evidence['live_evidence']) == 0, 'live proof/enrollment is forbidden')
    digest_claims = _keys(evidence['component_hash_claims'], set(COMPONENT_SHA256),
                          'component hash claims')
    for name, expected in COMPONENT_SHA256.items():
        _need(type(digest_claims[name]) is str and digest_claims[name] == expected,
              f'{name}: unreviewed component digest claim')
    statuses = _keys(evidence['components'], set(MODULE_INERT), 'component reports')
    for name, expected in MODULE_INERT.items():
        got = _keys(statuses[name], set(expected), f'{name} inert report')
        for key, value in expected.items():
            _need(type(got[key]) is type(value) and got[key] == value,
                  f'{name}: forbidden capability or schema drift at {key}')
    tests = _keys(evidence['test_results'],
                  {'discovered', 'passed', 'failures', 'errors', 'skipped_ids'},
                  'offline tests')
    for name, value in [('discovered', 771), ('failures', 0), ('errors', 0)]:
        _need(type(tests[name]) is int and tests[name] == value,
              f'offline test {name} mismatch')
    _need(type(tests['skipped_ids']) is list and
          tests['skipped_ids'] in ([], [KNOWN_SKIP]), 'unknown skipped test')
    _need(type(tests['passed']) is int and
          tests['passed'] == 771-len(tests['skipped_ids']),
          'offline pass count mismatch')
    findings = [{'id': num, 'status': status,
                 'source_scope': scope, 'required_closure': closure}
                for num, status, scope, closure in FINDINGS]
    return {'source': SOURCE, 'schema': SCHEMA, 'provenance': PROVENANCE,
            'simulation_only': True, 'offline_claim_consistency': 'PASS',
            'offline_771_host_attested': False,
            'live_security_evidence_verified': False,
            'live_release_decision': 'NO-GO',
            'runtime_enabled': False, 'task_creation_authorized': False,
            'notification_enabled': False, 'delivery_permitted': False,
            'enrollment_authorized': False, 'real_store_authorized': False,
            'repair_action': 'None', 'findings': findings}


def inert_status() -> dict:
    return {'source': SOURCE, 'provenance': PROVENANCE, 'simulation_only': True,
            'runtime_enabled': False, 'live_probe_authorized': False,
            'task_creation_authorized': False, 'notification_enabled': False,
            'delivery_permitted': False, 'enrollment_authorized': False,
            'real_store_authorized': False, 'store_modified': False,
            'repair_action': 'None', 'live_security_evidence_verified': False,
            'live_release_decision': 'NO-GO'}


def _main() -> int:
    import sys
    if sys.argv[1:] != ['--check-inert']:
        print('R6 is offline audit ONLY; --check-inert is the sole CLI action.',
              file=sys.stderr)
        return 2
    print(json.dumps(inert_status(), sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(_main())
