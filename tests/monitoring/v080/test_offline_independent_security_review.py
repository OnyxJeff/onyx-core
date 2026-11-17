"""Independent cross-boundary R6 OFFLINE security review; no live collection.

The tests use the real checked-in R1-R5 modules and synthetic temporary data.
They do not treat any self-reported JSON as Windows/clock/operator proof.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
MODULE_DIR = ROOT / 'windows' / 'monitoring' / 'v080'
sys.path.insert(0, str(MODULE_DIR))
import OnyxOfflineIndependentSecurityReview as r6
import OnyxOfflineWindowsTrustContract as r1
import OnyxOfflineExecutionEvidenceContract as r2
import OnyxOfflineIncidentJournal as r3
import OnyxOfflineOperatorDelivery as r4
import OnyxOfflineLifecycleTiming as r5

REAL_INERT = {'R1': r1.check_inert, 'R2': r2.inert_status,
              'R3': r3.check_inert, 'R4': r4.check_inert,
              'R5': r5.inert_status}


def fixture():
    return r6.example_evidence()


def rejects(change):
    obj = fixture()
    change(obj)
    with unittest.TestCase().assertRaises(r6.OfflineSecurityError):
        r6.assess_offline_evidence(obj)


class R6IndependentTests(unittest.TestCase):
    def test_base_no_go(self):
        report = r6.assess_offline_evidence(fixture())
        self.assertEqual(report['live_release_decision'], 'NO-GO')
        self.assertFalse(report['live_security_evidence_verified'])
        self.assertFalse(report['offline_771_host_attested'])

    def test_source_provenance(self):
        report = r6.assess_offline_evidence(fixture())
        self.assertEqual((report['source'], report['provenance']),
                         (r6.SOURCE, r6.PROVENANCE))

    def test_exact_ten_sec_findings(self):
        report = r6.assess_offline_evidence(fixture())
        self.assertEqual([v['id'] for v in report['findings']],
                         [f'SEC-{i:02d}' for i in range(1, 11)])

    def test_no_sec_closed(self):
        report = r6.assess_offline_evidence(fixture())
        self.assertEqual({v['status'] for v in report['findings']},
                         {'BLOCKED', 'OPEN TEST GAP'})

    def test_one_explicit_symlink_gap(self):
        report = r6.assess_offline_evidence(fixture())
        opened = [v['id'] for v in report['findings'] if v['status'] == 'OPEN TEST GAP']
        self.assertEqual(opened, ['SEC-09'])

    def test_closure_requirements_nonempty(self):
        for v in r6.assess_offline_evidence(fixture())['findings']:
            self.assertTrue(len(v['required_closure']) >= 20)
            self.assertTrue(v['source_scope'])

    def test_real_module_inert_snapshots_exact(self):
        for label, reader in REAL_INERT.items():
            self.assertEqual(reader(), r6.MODULE_INERT[label], label)

    def test_real_module_inert_results_not_authorized(self):
        obj = fixture()
        obj['components'] = {k: get() for k, get in REAL_INERT.items()}
        self.assertEqual(r6.assess_offline_evidence(obj)['live_release_decision'], 'NO-GO')

    def test_real_modules_do_not_claim_runtime(self):
        for label, reader in REAL_INERT.items():
            self.assertIs(reader()['runtime_enabled'], False, label)

    def test_real_modules_do_not_claim_task_creation(self):
        for label, reader in REAL_INERT.items():
            self.assertIs(reader()['task_creation_authorized'], False, label)

    def test_real_modules_do_not_claim_live_probe(self):
        for label, reader in REAL_INERT.items():
            self.assertIs(reader()['live_probe_authorized'], False, label)

    def test_real_modules_do_not_claim_delivery(self):
        for label, reader in REAL_INERT.items():
            self.assertIs(reader()['delivery_permitted'], False, label)

    def test_r5_does_not_claim_authenticated_clock(self):
        self.assertIs(r5.inert_status()['windows_clock_attested'], False)
        self.assertIs(r2.inert_status()['clock_attested'], False)

    def test_r4_r3_do_not_claim_protected_store(self):
        self.assertIs(r3.check_inert()['real_store_authorized'], False)
        self.assertIs(r4.check_inert()['real_store_authorized'], False)

    def test_r1_r4_do_not_claim_operator_auth(self):
        self.assertIs(r1.check_inert()['identity_authenticated_in_windows'], False)
        self.assertIs(r4.check_inert()['identity_authenticated_in_windows'], False)

    def test_r4_r5_never_claim_transport(self):
        self.assertEqual(r4.check_inert()['transport_calls'], 0)
        self.assertEqual(r5.inert_status()['transport_calls'], 0)

    def test_r4_task_created_distinct_from_r5_authorized(self):
        self.assertIs(r4.check_inert()['task_created'], False)
        self.assertNotIn('task_created', r5.inert_status())
        self.assertIs(r5.inert_status()['task_creation_authorized'], False)

    def test_r6_inert_cli_succeeds(self):
        p = subprocess.run([sys.executable, '-I', '-B', str(MODULE_DIR /
                           'OnyxOfflineIndependentSecurityReview.py'), '--check-inert'],
                           capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)['live_release_decision'], 'NO-GO')

    def test_r6_cli_with_live_option_refused(self):
        p = subprocess.run([sys.executable, '-I', '-B', str(MODULE_DIR /
                           'OnyxOfflineIndependentSecurityReview.py'), '--live'],
                           capture_output=True, text=True, timeout=5, check=False)
        self.assertNotEqual(p.returncode, 0)

    def test_r6_cli_with_no_args_refused(self):
        p = subprocess.run([sys.executable, '-I', '-B', str(MODULE_DIR /
                           'OnyxOfflineIndependentSecurityReview.py')],
                           capture_output=True, text=True, timeout=5, check=False)
        self.assertNotEqual(p.returncode, 0)

    def test_audit_module_imports_only_pure_libraries(self):
        module = MODULE_DIR / 'OnyxOfflineIndependentSecurityReview.py'
        tree = ast.parse(module.read_text(encoding='utf-8'))
        names = {alias.name.split('.')[0] for n in ast.walk(tree)
                 if isinstance(n, ast.Import) for alias in n.names}
        names.update(n.module.split('.')[0] for n in ast.walk(tree)
                     if isinstance(n, ast.ImportFrom) and n.module and n.module != '__future__')
        self.assertTrue(names.issubset({'copy', 'json', 're', 'typing', 'sys'}), names)

    def test_no_runtime_launch_functions(self):
        tree = ast.parse((MODULE_DIR / 'OnyxOfflineIndependentSecurityReview.py').read_text())
        names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for forbidden in ('start', 'run_worker', 'notify', 'enroll', 'repair', 'start_service', 'run_scheduler'):
            self.assertNotIn(forbidden, names)

    def test_json_roundtrip(self):
        input_obj = r6.parse_evidence(json.dumps(fixture()).encode('utf-8'))
        self.assertEqual(r6.assess_offline_evidence(input_obj)['live_release_decision'], 'NO-GO')

    def test_json_duplicate_property_refused(self):
        with self.assertRaises(r6.OfflineSecurityError):
            r6.parse_evidence(b'{"a":1,"a":2}')

    def test_json_nonfinite_refused(self):
        with self.assertRaises(r6.OfflineSecurityError):
            r6.parse_evidence(b'{"a":NaN}')

    def test_json_positive_infinity_refused(self):
        with self.assertRaises(r6.OfflineSecurityError):
            r6.parse_evidence(b'{"a":Infinity}')

    def test_json_invalid_utf8_refused(self):
        with self.assertRaises(r6.OfflineSecurityError):
            r6.parse_evidence(b'\xff')

    def test_json_oversize_refused(self):
        with self.assertRaises(r6.OfflineSecurityError):
            r6.parse_evidence(b' ' * (r6.MAX_BYTES+1))

    def test_json_zero_length_refused(self):
        with self.assertRaises(r6.OfflineSecurityError):
            r6.parse_evidence(b'')

    def test_json_string_instead_of_bytes_refused(self):
        with self.assertRaises(r6.OfflineSecurityError):
            r6.parse_evidence('{}')

    def test_json_array_root_refused(self):
        with self.assertRaises(r6.OfflineSecurityError):
            r6.assess_offline_evidence(r6.parse_evidence(b'[]'))

    def test_no_input_mutation(self):
        obj = fixture()
        before = copy.deepcopy(obj)
        r6.assess_offline_evidence(obj)
        self.assertEqual(obj, before)

    def test_result_mutation_does_not_modify_fixture(self):
        obj = fixture()
        first = r6.assess_offline_evidence(obj)
        first['findings'][0]['status'] = 'CLOSED'
        second = r6.assess_offline_evidence(obj)
        self.assertEqual(second['findings'][0]['status'], 'BLOCKED')

    def test_known_skip_status(self):
        obj = fixture()
        self.assertEqual(obj['test_results']['skipped_ids'], [r6.KNOWN_SKIP])
        self.assertEqual(r6.assess_offline_evidence(obj)['offline_claim_consistency'], 'PASS')

    def test_no_skip_is_consistent(self):
        obj = fixture()
        obj['test_results']['skipped_ids'] = []
        obj['test_results']['passed'] = 771
        self.assertEqual(r6.assess_offline_evidence(obj)['live_release_decision'], 'NO-GO')

    def test_forged_positive_go_rejected(self):
        rejects(lambda x: x.__setitem__('requested_verdict', 'GO'))

    def test_forged_operator_approval_rejected(self):
        rejects(lambda x: x.__setitem__('operator_authorization', True))

    def test_forged_external_live_proof_rejected(self):
        rejects(lambda x: x.__setitem__('live_evidence', ['imaginary proof']))

    def test_nonempty_live_proof_objects_rejected(self):
        rejects(lambda x: x.__setitem__('live_evidence', [{'windows_api': 'trusted'}]))

    def test_json_boolean_does_not_equal_test_count(self):
        rejects(lambda x: x['test_results'].__setitem__('discovered', True))

    def test_json_boolean_does_not_equal_pass_count(self):
        rejects(lambda x: x['test_results'].__setitem__('passed', True))

    def test_wrong_commit_rejected(self):
        rejects(lambda x: x.__setitem__('parent_commit', '0' * 40))

    def test_all_ten_findings_have_distinct_ids(self):
        self.assertEqual(len({f[0] for f in r6.FINDINGS}), 10)

    def test_synthetic_success_cannot_be_live_health(self):
        r = r6.assess_offline_evidence(fixture())
        self.assertNotIn('Healthy', str(r))
        self.assertIs(r['live_security_evidence_verified'], False)

    def test_r3_r4_synthetic_storage_no_implicit_delivery(self):
        with tempfile.TemporaryDirectory(prefix='onyx-r3-') as d3, \
             tempfile.TemporaryDirectory(prefix='onyx-r4-') as d4:
            p3, p4 = Path(d3), Path(d4)
            r3.initialize_synthetic_store(p3)
            before = r3.inspect_synthetic_store(p3)
            result = r4.initialize_synthetic_store(p4, p3)
            after = r3.inspect_synthetic_store(p3)
            self.assertEqual(before, after)
            self.assertIs(result['delivery_permitted'], False)
            self.assertIs(result['notification_enabled'], False)
            self.assertEqual(result['transport_calls'], 0)

    def test_r3_r4_r5_simulated_start_does_not_send(self):
        policy = r5.policy_example()
        state = r5.new_state(policy, boot_id='offline-a', mono_ms=0, wall_ms=1_000_000)
        event = {'event_id': 'tick-1', 'kind': 'Tick', 'boot_id': 'offline-a',
                 'mono_ms': policy['interval_ms'], 'wall_ms': 1_000_000+policy['interval_ms']}
        due = r5.transition(policy, state, event)
        self.assertEqual(due['view']['phase'], 'Due')
        self.assertIs(r4.check_inert()['delivery_permitted'], False)
        self.assertIs(r3.check_inert()['notification_enabled'], False)
        self.assertEqual(r5.inert_status()['transport_calls'], 0)

    def test_r5_no_real_clock_from_simulated_timing(self):
        state = r5.new_state(r5.policy_example(), boot_id='offline',
                             mono_ms=0, wall_ms=100000)
        self.assertFalse(r5.inspect(r5.policy_example(), state)['runtime_enabled'])
        self.assertFalse(r5.inert_status()['windows_clock_attested'])

    def test_r1_r2_r3_r4_r5_no_authority_aggregation(self):
        reports = {k: v() for k,v in REAL_INERT.items()}
        self.assertTrue(all(x['runtime_enabled'] is False for x in reports.values()))
        self.assertEqual(r6.assess_offline_evidence(fixture())['live_release_decision'], 'NO-GO')


# Adversarial, separately discoverable test cases, rather than subtests.
def _field_mutation_test(module, field):
    def attempt(self):
        obj = fixture()
        original = obj['components'][module][field]
        if type(original) is bool:
            replacement = not original
        elif type(original) is int:
            replacement = original + 1
        else:
            replacement = 'forged-' + original
        obj['components'][module][field] = replacement
        with self.assertRaises(r6.OfflineSecurityError):
            r6.assess_offline_evidence(obj)
    return attempt


def _field_missing_test(module):
    def attempt(self):
        obj = fixture()
        del obj['components'][module]['source']
        with self.assertRaises(r6.OfflineSecurityError):
            r6.assess_offline_evidence(obj)
    return attempt


def _hash_mutation_test(module):
    def attempt(self):
        obj = fixture()
        obj['component_hash_claims'][module] = '0' * 64
        with self.assertRaises(r6.OfflineSecurityError):
            r6.assess_offline_evidence(obj)
    return attempt


def _top_mutation_test(key, replacement):
    def attempt(self):
        obj = fixture()
        obj[key] = replacement
        with self.assertRaises(r6.OfflineSecurityError):
            r6.assess_offline_evidence(obj)
    return attempt


def _test_mutation_test(key, replacement):
    def attempt(self):
        obj = fixture()
        obj['test_results'][key] = replacement
        with self.assertRaises(r6.OfflineSecurityError):
            r6.assess_offline_evidence(obj)
    return attempt


for label, signature in r6.MODULE_INERT.items():
    for field in signature:
        setattr(R6IndependentTests, f'test_adversarial_{label.lower()}_{field}',
                _field_mutation_test(label, field))
    setattr(R6IndependentTests, f'test_missing_{label.lower()}_source',
            _field_missing_test(label))
    setattr(R6IndependentTests, f'test_bad_{label.lower()}_hash',
            _hash_mutation_test(label))

for name, value in [
    ('schema', 'v2'), ('source', 'Unknown'), ('provenance', 'LiveEvidence'),
    ('simulation_only', False), ('simulation_only', 1),
    ('parent_commit', 'bad'), ('operator_authorization', 1),
    ('requested_verdict', 'PASS'), ('live_evidence', 'none'),
    ('live_evidence', None), ('components', {}), ('component_hash_claims', {}),
    ('test_results', {}),
]:
    setattr(R6IndependentTests, f'test_mutate_top_{name}_{str(value).replace(" ", "_").replace("{", "dict").replace("}", "")}',
            _top_mutation_test(name, value))

for name, value in [
    ('discovered', 770), ('discovered', '771'), ('passed', 769),
    ('passed', 771), ('failures', 1), ('errors', 1),
    ('skipped_ids', ['other']), ('skipped_ids', [r6.KNOWN_SKIP, r6.KNOWN_SKIP]),
    ('skipped_ids', 'none'), ('skipped_ids', [7]),
]:
    setattr(R6IndependentTests, f'test_mutate_test_{name}_{str(value).replace(" ", "_").replace("[", "_").replace("]", "_")[:42]}',
            _test_mutation_test(name, value))

if __name__ == '__main__':
    unittest.main()
