"""Adversarial R4 synthetic authorization/decision tests; NO real notifications."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
MODULE_DIR = ROOT / 'windows' / 'monitoring' / 'v080'
sys.path.insert(0, str(MODULE_DIR))
import OnyxOfflineOperatorDelivery as r4
r3 = r4.r3

T0 = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
IID = 'inc-' + 'a' * 24
IID2 = 'inc-' + 'b' * 24
ACTOR = 'synthetic:operator-alpha'


def stamp(s: int = 0) -> str:
    return (T0 + timedelta(seconds=s)).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def event(kind='IncidentOpened', t=0, iid=IID, old='Unknown', new='Suspected', decision='WaitAndRetry'):
    at = stamp(t)
    basis = '|'.join((kind, at, iid or 'none'))
    return {'schema_version': 1, 'event_id': 'evt-' + hashlib.sha256(basis.encode()).hexdigest()[:24],
            'event_type': kind, 'timestamp_utc': at, 'incident_id': iid,
            'from_phase': old, 'to_phase': new, 'connectivity_decision': decision,
            'repair_action': 'None'}


def batch(*events, ref=180):
    return json.dumps({'schema_version': 1, 'source': r3.m3.SOURCE,
                       'provenance': r3.m3.PROVENANCE, 'reference_utc': stamp(ref),
                       'events': events}, sort_keys=True, separators=(',', ':')).encode()


def make_request(action='Plan', when=200, key=None, iid=IID, actor=ACTOR,
                 role='Responder', scopes=None, issued=185, expires=500,
                 reason=None, **grant_edits):
    if scopes is None:
        scopes = sorted(r4.ACTIONS)
    if reason is None:
        reason = {'Acknowledge':'OperatorReview', 'Plan':'OperatorReview',
                  'Suppress':'OperatorSuppressed', 'Uncertain':'SimulatedOutcomeUnknown'}.get(action,'OperatorReview')
    grant = {'schema_version': 1, 'source': r4.GRANT_SOURCE, 'simulation_only': True,
             'actor': actor, 'role': role, 'scopes': scopes, 'incident_id': iid,
             'issued_utc': stamp(issued), 'expires_utc': stamp(expires),
             'revocation_generation': 1, 'revoked': False,
             'identity_authenticated_in_windows': False,
             'revocation_authoritative': False, 'delivery_authorized': False}
    grant.update(grant_edits)
    obj = {'schema_version': 1, 'source': r4.SOURCE, 'provenance': r4.PROVENANCE,
           'simulation_only': True, 'request_id': None, 'action': action, 'at_utc': stamp(when),
           'actor': actor, 'incident_id': iid, 'intent_key': key,
           'reason': reason, 'grant': grant}
    obj['request_id'] = 'req-' + r4._sha(r4._json({k:v for k,v in obj.items() if k != 'request_id'}))[:24]
    return obj


def raw(obj):
    return r4._json(obj).encode('utf-8')


class R4OperatorTests(unittest.TestCase):
    def setUp(self):
        self.t3 = tempfile.TemporaryDirectory(prefix='onyx-r3-')
        self.addCleanup(self.t3.cleanup)
        self.r3root = Path(self.t3.name)
        r3.initialize_synthetic_store(self.r3root)
        r3.ingest_synthetic_batch(self.r3root, batch(event()))
        self.t4 = tempfile.TemporaryDirectory(prefix='onyx-r4-')
        self.addCleanup(self.t4.cleanup)
        self.r4root = Path(self.t4.name)
        r4.initialize_synthetic_store(self.r4root, self.r3root)
        self.key = f'{IID}|IncidentOpened'
        self.db = self.r4root / r4.DB_NAME

    def apply(self, action='Plan', **kwargs):
        obj = make_request(action, key=None if action=='Acknowledge' else self.key, **kwargs)
        return r4.apply_synthetic_request(self.r4root, self.r3root, raw(obj))

    def view(self):
        return r4.inspect_synthetic_store(self.r4root, self.r3root)

    def sql(self, query, args=()):
        c = sqlite3.connect(self.db)
        try:
            c.execute(query, args)
            c.commit()
        finally:
            c.close()

    def selfsame(self, bad):
        before = self.db.read_bytes()
        with self.assertRaises((r4.OfflineOperatorError, sqlite3.Error)):
            r4.apply_synthetic_request(self.r4root, self.r3root, raw(bad))
        self.assertEqual(before, self.db.read_bytes())

    def test_inert_cli(self):
        result = subprocess.run([sys.executable,'-I','-B',str(MODULE_DIR/'OnyxOfflineOperatorDelivery.py'),
                                 '--check-inert'], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        value = json.loads(result.stdout)
        self.assertEqual(value['source'], r4.SOURCE)
        self.assertIs(value['simulation_only'], True)
        for name in ('runtime_enabled','notification_enabled','delivery_permitted','store_modified',
                     'identity_authenticated_in_windows','revocation_authoritative','real_store_authorized',
                     'enrollment_authorized','live_probe_authorized','task_creation_authorized'):
            self.assertIs(value[name], False)
        self.assertEqual(value['repair_action'],'None')
        self.assertEqual(value['transport_calls'],0)

    def test_rejects_all_live_cli_flags(self):
        for flag in ('--run','--live','--notify','--deliver','--send','--enroll','--persist',
                     '--repair','--task','--apply','--commit','--fixture','--production'):
            with self.subTest(flag=flag):
                result = subprocess.run([sys.executable,'-I','-B',str(MODULE_DIR/'OnyxOfflineOperatorDelivery.py'),
                                         flag], capture_output=True, timeout=5)
                self.assertNotEqual(result.returncode,0)

    def test_initial_snapshot_imports_only_r3_intents(self):
        view=self.view()
        self.assertEqual(view['state']['decisions'],{self.key:'NotEvaluated'})
        self.assertEqual(view['state']['incident_state']['phase'],'Suspected')
        self.assertEqual(view['synthetic_action_count'],0)
        self.assertFalse(view['store_modified'])

    def test_initial_snapshot_has_no_transport(self):
        self.assertEqual(self.view()['transport_calls'], 0)
        self.assertFalse(self.view()['delivery_permitted'])

    def test_r4_initializes_one_file_only(self):
        self.assertEqual({p.name for p in self.r4root.iterdir()}, {r4.DB_NAME})

    def test_initializing_again_refuses_no_overwrite(self):
        before=self.db.read_bytes()
        with self.assertRaises(r4.OfflineOperatorError):
            r4.initialize_synthetic_store(self.r4root,self.r3root)
        self.assertEqual(before,self.db.read_bytes())

    def test_plan_is_simulated_would_send_never_sent(self):
        out=self.apply()
        self.assertEqual(out['state']['decisions'][self.key], 'SimulatedWouldSend')
        self.assertFalse(out['delivery_permitted'])
        self.assertEqual(out['transport_calls'],0)

    def test_plan_does_not_modify_r3_journal(self):
        before=(self.r3root/r3.DB_NAME).read_bytes()
        self.apply()
        self.assertEqual((self.r3root/r3.DB_NAME).read_bytes(),before)

    def test_uncertain_requires_prior_plan(self):
        with self.assertRaises(r4.OfflineOperatorError): self.apply('Uncertain')
        self.assertEqual(self.view()['synthetic_action_count'],0)

    def test_uncertain_is_terminal_no_automatic_retry(self):
        self.apply('Plan',when=200)
        self.apply('Uncertain',when=210)
        self.assertEqual(self.view()['state']['decisions'][self.key],'SimulatedUncertain')
        with self.assertRaises(r4.OfflineOperatorError): self.apply('Plan',when=220)

    def test_suppress_from_new_is_terminal(self):
        self.apply('Suppress')
        self.assertEqual(self.view()['state']['decisions'][self.key],'SimulatedSuppressed')
        with self.assertRaises(r4.OfflineOperatorError): self.apply('Plan',when=230)

    def test_suppress_from_plan_is_terminal(self):
        self.apply('Plan',when=200)
        self.apply('Suppress',when=210)
        self.assertEqual(self.view()['state']['decisions'][self.key],'SimulatedSuppressed')

    def test_cannot_suppress_uncertain(self):
        self.apply('Plan',when=200)
        self.apply('Uncertain',when=210)
        with self.assertRaises(r4.OfflineOperatorError): self.apply('Suppress',when=220)

    def test_cannot_repeat_plan_with_new_id(self):
        self.apply()
        with self.assertRaises(r4.OfflineOperatorError): self.apply('Plan',when=220)

    def test_duplicate_request_replay_suppressed(self):
        request=make_request('Plan',key=self.key)
        r4.apply_synthetic_request(self.r4root,self.r3root,raw(request))
        out=r4.apply_synthetic_request(self.r4root,self.r3root,raw(request))
        self.assertTrue(out['duplicate_request_suppressed'])
        self.assertFalse(out['store_modified'])
        self.assertEqual(out['synthetic_action_count'],1)

    def test_duplicate_request_does_not_change_bytes(self):
        request=raw(make_request('Plan',key=self.key))
        r4.apply_synthetic_request(self.r4root,self.r3root,request)
        before=self.db.read_bytes()
        r4.apply_synthetic_request(self.r4root,self.r3root,request)
        self.assertEqual(self.db.read_bytes(),before)

    def test_duplicate_after_new_python_process(self):
        request=raw(make_request('Plan',key=self.key))
        r4.apply_synthetic_request(self.r4root,self.r3root,request)
        code=(f'import sys,json;sys.path.insert(0,{str(MODULE_DIR)!r});'
              'from OnyxOfflineOperatorDelivery import apply_synthetic_request as a;'
              'from pathlib import Path;'
              f'r=a(Path({str(self.r4root)!r}),Path({str(self.r3root)!r}),bytes.fromhex({request.hex()!r}));'
              'print(json.dumps(r["duplicate_request_suppressed"]))')
        p=subprocess.run([sys.executable,'-I','-B','-c',code],capture_output=True,timeout=7)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stdout.strip(),b'true')

    def test_ack_uses_existing_m3_validator(self):
        out=self.apply('Acknowledge',when=200)
        state=out['state']['incident_state']
        self.assertEqual(state['acknowledged_by'],ACTOR)
        self.assertEqual(state['acknowledged_at_utc'],stamp(200))
        self.assertEqual(state['phase'],'Suspected')

    def test_ack_does_not_send(self):
        out=self.apply('Acknowledge')
        self.assertFalse(out['delivery_permitted'])
        self.assertEqual(out['state']['decisions'][self.key],'NotEvaluated')

    def test_ack_does_not_change_original_r3(self):
        self.apply('Acknowledge')
        self.assertIsNone(r3.inspect_synthetic_store(self.r3root)['state']['acknowledged_by'])

    def test_duplicate_ack_replay_idempotent(self):
        req=raw(make_request('Acknowledge'))
        r4.apply_synthetic_request(self.r4root,self.r3root,req)
        out=r4.apply_synthetic_request(self.r4root,self.r3root,req)
        self.assertTrue(out['duplicate_request_suppressed'])

    def test_new_ack_must_not_override_existing(self):
        self.apply('Acknowledge',when=200)
        with self.assertRaises(r4.OfflineOperatorError): self.apply('Acknowledge',when=201)

    def test_ack_before_event_refused(self):
        self.selfsame(make_request('Acknowledge',when=-10,issued=-20,expires=50))

    def test_ack_incident_mismatch_refused(self):
        self.selfsame(make_request('Acknowledge',iid=IID2))

    def test_wrong_intent_key_refused(self):
        self.selfsame(make_request('Plan',key='not-real|IncidentOpened'))

    def test_wrong_incident_for_intent_refused(self):
        self.selfsame(make_request('Plan',key=self.key,iid=IID2))

    def test_ack_with_intent_key_refused(self):
        self.selfsame(make_request('Acknowledge',key=self.key))

    def test_plan_without_intent_key_refused(self):
        self.selfsame(make_request('Plan',key=None))

    def test_observer_role_refused(self):
        self.selfsame(make_request('Plan',key=self.key,role='Observer'))

    def test_empty_scopes_refused(self):
        self.selfsame(make_request('Plan',key=self.key,scopes=[]))

    def test_wrong_scope_refused(self):
        self.selfsame(make_request('Plan',key=self.key,scopes=['Acknowledge']))

    def test_duplicate_scopes_refused(self):
        self.selfsame(make_request('Plan',key=self.key,scopes=['Plan','Plan']))

    def test_unsorted_scopes_refused(self):
        self.selfsame(make_request('Plan',key=self.key,scopes=['Plan','Acknowledge']))

    def test_wrong_actor_binding_refused(self):
        bad=make_request('Plan',key=self.key)
        bad['grant']['actor']='synthetic:another'
        self.selfsame(bad)

    def test_non_synthetic_actor_refused(self):
        self.selfsame(make_request('Plan',key=self.key,actor='actualuser'))

    def test_revoked_mock_grant_refused(self):
        self.selfsame(make_request('Plan',key=self.key,revoked=True))

    def test_noninteger_generation_refused(self):
        self.selfsame(make_request('Plan',key=self.key,revocation_generation=True))

    def test_rollback_generation_refused(self):
        self.selfsame(make_request('Plan',key=self.key,revocation_generation=0))

    def test_expired_mock_grant_refused(self):
        self.selfsame(make_request('Plan',key=self.key,expires=200))

    def test_future_mock_grant_refused(self):
        self.selfsame(make_request('Plan',key=self.key,issued=201))

    def test_overlong_mock_grant_refused(self):
        self.selfsame(make_request('Plan',key=self.key,expires=1200))

    def test_fake_windows_authenticated_true_refused(self):
        self.selfsame(make_request('Plan',key=self.key,identity_authenticated_in_windows=True))

    def test_fake_revocation_authoritative_true_refused(self):
        self.selfsame(make_request('Plan',key=self.key,revocation_authoritative=True))

    def test_fake_delivery_authorized_true_refused(self):
        self.selfsame(make_request('Plan',key=self.key,delivery_authorized=True))

    def test_mock_grant_simulation_false_refused(self):
        self.selfsame(make_request('Plan',key=self.key,simulation_only=False))

    def test_wrong_grant_source_refused(self):
        self.selfsame(make_request('Plan',key=self.key,source='LiveWindowsToken'))

    def test_wrong_grant_schema_refused(self):
        self.selfsame(make_request('Plan',key=self.key,schema_version=2))

    def test_grant_unknown_field_refused(self):
        bad=make_request('Plan',key=self.key)
        bad['grant']['extra']='oops'
        self.selfsame(bad)

    def test_request_live_flag_refused(self):
        bad=make_request('Plan',key=self.key)
        bad['simulation_only']=False
        self.selfsame(bad)

    def test_request_fake_source_refused(self):
        bad=make_request('Plan',key=self.key)
        bad['source']='ActualDelivery'
        self.selfsame(bad)

    def test_unknown_action_refused(self):
        self.selfsame(make_request('Execute',key=self.key))

    def test_wrong_reason_for_action_refused(self):
        self.selfsame(make_request('Plan',key=self.key,reason='OperatorSuppressed'))

    def test_bad_reason_refused(self):
        self.selfsame(make_request('Plan',key=self.key,reason='SendEmail'))

    def test_request_unknown_field_refused(self):
        bad=make_request('Plan',key=self.key)
        bad['notification']='Send'
        self.selfsame(bad)

    def test_request_missing_field_refused(self):
        bad=make_request('Plan',key=self.key)
        bad.pop('grant')
        self.selfsame(bad)

    def test_wrong_request_id_refused(self):
        bad=make_request('Plan',key=self.key)
        bad['request_id']='req-'+'f'*24
        self.selfsame(bad)

    def test_bool_schema_refused(self):
        bad=make_request('Plan',key=self.key)
        bad['schema_version']=True
        self.selfsame(bad)

    def test_bad_timestamp_refused(self):
        bad=make_request('Plan',key=self.key)
        bad['at_utc']='2026-11-10T12:03:20+00:00'
        self.selfsame(bad)

    def test_nonmonotonic_new_action_refused(self):
        self.apply('Plan',when=220)
        with self.assertRaises(r4.OfflineOperatorError): self.apply('Uncertain',when=200)

    def test_invalid_utf8_refused(self):
        before=self.db.read_bytes()
        with self.assertRaises(r4.OfflineOperatorError):
            r4.apply_synthetic_request(self.r4root,self.r3root,b'\xff')
        self.assertEqual(self.db.read_bytes(),before)

    def test_duplicate_json_key_refused(self):
        with self.assertRaises(r4.OfflineOperatorError):
            r4.apply_synthetic_request(self.r4root,self.r3root,b'{"a":1,"a":2}')

    def test_nonfinite_json_refused(self):
        with self.assertRaises(r4.OfflineOperatorError):
            r4.apply_synthetic_request(self.r4root,self.r3root,b'{"x":NaN}')

    def test_oversized_request_refused(self):
        with self.assertRaises(r4.OfflineOperatorError):
            r4.apply_synthetic_request(self.r4root,self.r3root,b'X'*(r4.MAX_REQUEST_BYTES+1))

    def test_r3_mutation_after_snapshot_refused(self):
        r3.ingest_synthetic_batch(self.r3root,batch(event('IncidentEscalated',40,old='Suspected',new='Active',decision='PossibleIcsFailure')))
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_r3_mutation_prevents_new_r4_action(self):
        r3.ingest_synthetic_batch(self.r3root,batch(event('IncidentEscalated',40,old='Suspected',new='Active',decision='PossibleIcsFailure')))
        with self.assertRaises(r4.OfflineOperatorError): self.apply()

    def test_r3_tampered_intent_refused(self):
        db=self.r3root/r3.DB_NAME
        c=sqlite3.connect(db)
        c.execute("UPDATE intent_journal SET intent_sha='"+'f'*64+"'")
        c.commit(); c.close()
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_r3_missing_db_refused(self):
        db=self.r3root/r3.DB_NAME
        db.rename(self.r3root/'renamed.sqlite3')
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_action_precommit_fault_atomic(self):
        req=raw(make_request('Plan',key=self.key))
        with self.assertRaises(r4.SyntheticFault):
            r4.apply_synthetic_request(self.r4root,self.r3root,req,inject_fault='before_commit')
        self.assertEqual(self.view()['synthetic_action_count'],0)
        self.assertEqual(self.view()['state']['decisions'][self.key],'NotEvaluated')

    def test_precommit_rollback_can_retry_once(self):
        req=raw(make_request('Plan',key=self.key))
        with self.assertRaises(r4.SyntheticFault):
            r4.apply_synthetic_request(self.r4root,self.r3root,req,inject_fault='before_commit')
        out=r4.apply_synthetic_request(self.r4root,self.r3root,req)
        self.assertEqual(out['synthetic_action_count'],1)

    def test_postcommit_lost_response_retry_suppressed(self):
        req=raw(make_request('Plan',key=self.key))
        with self.assertRaises(r4.SyntheticFault):
            r4.apply_synthetic_request(self.r4root,self.r3root,req,inject_fault='after_commit')
        self.assertEqual(self.view()['synthetic_action_count'],1)
        out=r4.apply_synthetic_request(self.r4root,self.r3root,req)
        self.assertTrue(out['duplicate_request_suppressed'])

    def test_bad_fault_token_refused(self):
        before=self.db.read_bytes()
        with self.assertRaises(r4.OfflineOperatorError):
            r4.apply_synthetic_request(self.r4root,self.r3root,raw(make_request('Plan',key=self.key)),inject_fault='actual-send')
        self.assertEqual(before,self.db.read_bytes())

    def test_action_capacity_fail_closed(self):
        self.apply('Plan')
        with mock.patch.object(r4,'MAX_ACTIONS',1):
            with self.assertRaises(r4.OfflineOperatorError): self.apply('Uncertain',when=210)
        self.assertEqual(self.view()['synthetic_action_count'],1)

    def test_no_autoprune_of_history(self):
        self.apply('Plan')
        self.apply('Uncertain',when=210)
        self.assertEqual(self.view()['synthetic_action_count'],2)
        self.assertEqual(self.view()['state']['decisions'][self.key],'SimulatedUncertain')

    def test_repeated_inspect_readonly(self):
        before=self.db.read_bytes()
        self.view();self.view()
        self.assertEqual(before,self.db.read_bytes())

    def test_readonly_sqlite_reader_denies_insert(self):
        c=r4._open_db(self.r4root,readonly=True)
        try:
            with self.assertRaises(sqlite3.Error):
                c.execute('DELETE FROM meta')
        finally: c.close()

    def test_unexpected_extra_file_refused(self):
        (self.r4root/'other').write_text('test')
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_wrong_folder_prefix_refused(self):
        with tempfile.TemporaryDirectory(prefix='bad-r4-') as td:
            with self.assertRaises(r4.OfflineOperatorError):
                r4.initialize_synthetic_store(Path(td),self.r3root)

    def test_nested_temp_refused(self):
        nested=self.r4root/'subdir'
        nested.mkdir()
        with self.assertRaises(r4.OfflineOperatorError):
            r4.initialize_synthetic_store(nested,self.r3root)

    def test_symlink_root_refused_if_available(self):
        with tempfile.TemporaryDirectory(prefix='onyx-r4-') as temp:
            link=Path(temp).parent/('onyx-r4-link'+Path(temp).name[8:])
            try:
                link.symlink_to(self.r4root,target_is_directory=True)
            except (OSError,NotImplementedError):
                return
            try:
                with self.assertRaises(r4.OfflineOperatorError):
                    r4.inspect_synthetic_store(link,self.r3root)
            finally: link.unlink()

    def test_missing_db_refused_no_automatic_init(self):
        self.db.rename(self.r4root/'moved.db')
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_metadata_tamper_detected(self):
        self.sql("UPDATE meta SET state_sha='"+'f'*64+"'")
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_base_sha_tamper_detected(self):
        self.sql("UPDATE meta SET base_sha='"+'f'*64+"'")
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_state_json_tamper_detected(self):
        self.sql("UPDATE meta SET state_json='{}'")
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_head_sha_tamper_detected(self):
        self.apply()
        self.sql("UPDATE meta SET head_sha='"+'f'*64+"'")
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_action_request_tamper_detected(self):
        self.apply()
        self.sql("UPDATE action_journal SET request_json='{}'")
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_action_digest_tamper_detected(self):
        self.apply()
        self.sql("UPDATE action_journal SET request_sha='"+'f'*64+"'")
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_action_after_state_tamper_detected(self):
        self.apply()
        self.sql("UPDATE action_journal SET after_json='{}'")
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_action_chain_prev_tamper_detected(self):
        self.apply()
        self.sql("UPDATE action_journal SET prev_sha='"+'f'*64+"'")
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_action_record_sha_tamper_detected(self):
        self.apply()
        self.sql("UPDATE action_journal SET record_sha='"+'f'*64+"'")
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_action_row_missing_detected(self):
        self.apply()
        self.sql('DELETE FROM action_journal')
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_action_unexpected_row_detected(self):
        self.apply()
        self.sql("UPDATE meta SET next_seq=1")
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_unknown_schema_detected(self):
        self.sql('PRAGMA user_version=99')
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_unknown_application_id_detected(self):
        self.sql('PRAGMA application_id=42')
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_unexpected_table_detected(self):
        self.sql('CREATE TABLE evil (a INTEGER)')
        with self.assertRaises(r4.OfflineOperatorError): self.view()

    def test_sqlite_corruption_refused(self):
        data=self.db.read_bytes()
        self.db.write_bytes(b'not a sqlite database'+data[21:])
        with self.assertRaises((r4.OfflineOperatorError,sqlite3.Error)): self.view()

    def test_invalid_real_provenance_rejected(self):
        bad=make_request('Plan',key=self.key)
        bad['provenance']='WindowsReal'
        self.selfsame(bad)

    def test_no_network_or_process_imports_in_module(self):
        source=(MODULE_DIR/'OnyxOfflineOperatorDelivery.py').read_text('utf-8')
        import ast
        tree=ast.parse(source)
        forbidden={'requests','urllib','socket','http','subprocess','win32api','win32com','ctypes'}
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                self.assertFalse({x.name.split('.')[0] for x in node.names}&forbidden)
            if isinstance(node,ast.ImportFrom):
                self.assertNotIn((node.module or '').split('.')[0],forbidden)

    def test_no_protected_v070_literal_or_task_write(self):
        source=(MODULE_DIR/'OnyxOfflineOperatorDelivery.py').read_text('utf-8')
        for text in ('OnyxCore-v070-Release','OnyxCore-v070-Development','schtasks',
                     'Register-ScheduledTask','Send-MailMessage','smtp','webhook'):
            self.assertNotIn(text,source)

    def test_observation_never_claims_live_authentication(self):
        self.apply('Acknowledge')
        self.assertFalse(self.view()['identity_authenticated_in_windows'])
        self.assertFalse(self.view()['revocation_authoritative'])

    def test_mock_grants_do_not_confer_real_capability(self):
        self.apply('Plan')
        for field in ('delivery_permitted','notification_enabled','runtime_enabled','live_probe_authorized',
                      'task_creation_authorized','enrollment_authorized','real_store_authorized'):
            self.assertIs(self.view()[field],False)

    def test_decisions_are_not_actual_delivery_status(self):
        self.apply('Plan')
        self.apply('Uncertain',when=210)
        self.assertNotIn('Delivered',set(self.view()['state']['decisions'].values()))

    def test_ack_and_plan_both_persist_restart(self):
        self.apply('Acknowledge',when=200)
        self.apply('Plan',when=210)
        state=self.view()['state']
        self.assertEqual(state['incident_state']['acknowledged_by'],ACTOR)
        self.assertEqual(state['decisions'][self.key],'SimulatedWouldSend')
        self.assertEqual(self.view()['synthetic_action_count'],2)

    def test_only_temp_db_changes_from_actions(self):
        before=(self.r3root/r3.DB_NAME).read_bytes()
        self.apply('Plan')
        self.apply('Uncertain',when=210)
        self.assertEqual((self.r3root/r3.DB_NAME).read_bytes(),before)
        self.assertEqual({x.name for x in self.r4root.iterdir()},{r4.DB_NAME})

    def test_unknown_evidence_refuses_plan(self):
        r3.ingest_synthetic_batch(self.r3root, batch(event('EvidenceIncomplete',60,old='Suspected',new='Suspected',decision='Investigate')))
        with tempfile.TemporaryDirectory(prefix='onyx-r4-') as td:
            root=Path(td)
            r4.initialize_synthetic_store(root,self.r3root)
            with self.assertRaises(r4.OfflineOperatorError):
                r4.apply_synthetic_request(root,self.r3root,raw(make_request('Plan',key=self.key)))

    def test_unknown_evidence_refuses_ack(self):
        r3.ingest_synthetic_batch(self.r3root, batch(event('EvidenceIncomplete',60,old='Suspected',new='Suspected',decision='Investigate')))
        with tempfile.TemporaryDirectory(prefix='onyx-r4-') as td:
            root=Path(td)
            r4.initialize_synthetic_store(root,self.r3root)
            with self.assertRaises(r4.OfflineOperatorError):
                r4.apply_synthetic_request(root,self.r3root,raw(make_request('Acknowledge')))


if __name__ == '__main__':
    unittest.main()
