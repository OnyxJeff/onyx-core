"""R5 adversarial offline lifecycle & timing tests. No live tasks or probes."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

MODULE = (Path(__file__).resolve().parents[3] /
          'windows/monitoring/v080/OnyxOfflineLifecycleTiming.py')
SPEC = importlib.util.spec_from_file_location('onyx_r5_lifecycle_under_test', MODULE)
assert SPEC and SPEC.loader
r5 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r5)


class R5TimingTests(unittest.TestCase):
    def setUp(self):
        self.policy = r5.policy_example()
        self.state = r5.new_state(self.policy, boot_id='boot-a', mono_ms=0, wall_ms=1_000_000)
        self.sequence = 0

    def ev(self, kind, mono, **kw):
        self.sequence += 1
        e = {'event_id': f'e{self.sequence}', 'kind': kind,
             'boot_id': kw.pop('boot_id', 'boot-a'), 'mono_ms': mono,
             'wall_ms': kw.pop('wall_ms', 1_000_000 + mono)}
        e.update(kw)
        return e

    def change(self, kind, mono, **kw):
        event = self.ev(kind, mono, **kw)
        self.state = r5.transition(self.policy, self.state, event)
        return event

    def due(self):
        self.change('Tick', 60000)
        return self.state

    def running(self):
        self.due()
        self.change('Start', 60100, run_id='run-1')
        return self.state

    def finished(self):
        self.running()
        self.change('Finish', 62000, run_id='run-1', outcome='Success')
        return self.state

    def reject(self, event, policy=None, state=None):
        target = self.state if state is None else state
        original = copy.deepcopy(target)
        with self.assertRaises(r5.OfflineTimingError):
            r5.transition(self.policy if policy is None else policy, target, event)
        self.assertEqual(target, original)

    def test_inert_cli(self):
        p = subprocess.run([sys.executable, '-I', '-B', str(MODULE), '--check-inert'],
                           capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(p.stdout)['scheduler_started'], False)

    def test_cli_refuses_live(self):
        for option in ['--run', '--live', '--deploy', '--task', '--repair', '--start']:
            p = subprocess.run([sys.executable, '-I', '-B', str(MODULE), option],
                               capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)

    def test_inert_flags(self):
        s = r5.inert_status()
        for name in ('runtime_enabled', 'live_probe_authorized', 'task_creation_authorized',
                     'store_modified', 'notification_enabled', 'delivery_permitted',
                     'real_store_authorized', 'identity_authenticated_in_windows',
                     'windows_clock_attested', 'scheduler_started', 'worker_spawned'):
            self.assertIs(s[name], False)
        self.assertEqual(s['transport_calls'], 0)

    def test_no_fs_network_scheduler_imports(self):
        source = MODULE.read_text(encoding='utf-8')
        import ast
        names = set()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split('.')[0] for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split('.')[0])
        self.assertFalse(names & {'os', 'pathlib', 'socket', 'subprocess', 'sqlite3',
                                  'requests', 'urllib', 'winreg', 'ctypes', 'win32com',
                                  'time', 'datetime', 'threading', 'multiprocessing'})

    def test_initial_idle(self):
        self.assertEqual(r5.inspect(self.policy, self.state)['phase'], 'Idle')

    def test_no_work_before_due(self):
        self.change('Tick', 59999)
        self.assertEqual(self.state['view']['started'], 0)
        self.assertEqual(self.state['view']['phase'], 'Idle')

    def test_due_on_exact_boundary(self):
        self.due()
        self.assertEqual(self.state['view']['phase'], 'Due')
        self.assertEqual(self.state['view']['pending_due_ms'], 60000)

    def test_running_sets_budget(self):
        self.running()
        self.assertEqual(self.state['view']['deadline_ms'], 90100)

    def test_success_returns_idle(self):
        self.finished()
        self.assertEqual(self.state['view']['phase'], 'Idle')
        self.assertEqual(self.state['view']['completed'], 1)

    def test_next_due_stays_aligned(self):
        self.finished()
        self.assertEqual(self.state['view']['next_due_ms'], 120000)

    def test_second_cycle_possible(self):
        self.finished()
        self.change('Tick', 120000)
        self.change('Start', 120001, run_id='run-2')
        self.change('Finish', 120003, run_id='run-2', outcome='Success')
        self.assertEqual(self.state['view']['completed'], 2)

    def test_success_never_implies_health(self):
        self.finished()
        self.assertFalse(self.state['view']['runtime_enabled'])
        self.assertEqual(self.state['view']['reason'], 'SyntheticCompleted')

    def test_start_before_due_refused(self):
        self.reject(self.ev('Start', 1, run_id='run-1'))

    def test_overlapping_start_refused(self):
        self.running()
        self.reject(self.ev('Start', 60150, run_id='run-2'))

    def test_duplicate_start_different_event_id_refused(self):
        self.running()
        self.reject(self.ev('Start', 60100, run_id='run-1'))

    def test_wrong_run_finish_refused(self):
        self.running()
        self.reject(self.ev('Finish', 61000, run_id='wrong', outcome='Success'))

    def test_finish_before_start_refused(self):
        self.due()
        self.reject(self.ev('Finish', 60100, run_id='run-1', outcome='Success'))

    def test_double_finish_refused(self):
        self.finished()
        self.reject(self.ev('Finish', 62000, run_id='run-1', outcome='Success'))

    def test_finish_outcome_failure_failclosed(self):
        self.running()
        self.change('Finish', 61000, run_id='run-1', outcome='Failure')
        self.assertEqual(self.state['view']['reason'], 'SyntheticWorkerFailure')
        self.assertEqual(self.state['view']['failed'], 1)

    def test_failure_no_restart_recovery(self):
        self.running()
        self.change('Finish', 61000, run_id='run-1', outcome='Failure')
        self.change('Restart', 0, boot_id='boot-b', prior_boot_id='boot-a', wall_ms=1_080_000)
        self.assertEqual(self.state['view']['phase'], 'FailedClosed')

    def test_run_timeout_failclosed(self):
        self.running()
        self.change('Tick', 90101)
        self.assertEqual(self.state['view']['phase'], 'FailedClosed')
        self.assertEqual(self.state['view']['aborted'], 1)

    def test_timeout_equal_deadline_is_not_late(self):
        self.running()
        self.change('Finish', 90100, run_id='run-1', outcome='Success')
        self.assertEqual(self.state['view']['phase'], 'Idle')

    def test_late_finish_failclosed(self):
        self.running()
        self.change('Finish', 90101, run_id='run-1', outcome='Success')
        self.assertEqual(self.state['view']['reason'], 'LateSyntheticFinish')

    def test_due_window_expires(self):
        self.due()
        self.change('Tick', 120000)
        self.assertEqual(self.state['view']['phase'], 'FailedClosed')

    def test_cannot_start_after_due_expired(self):
        self.due()
        self.reject(self.ev('Start', 120000, run_id='run-1'))

    def test_missed_one_cycle_no_catchup(self):
        self.change('Tick', 120000)
        self.assertEqual(self.state['view']['missed'], 1)
        self.assertEqual(self.state['view']['pending_due_ms'], 120000)

    def test_missed_two_cycles_within_limit(self):
        self.change('Tick', 180000)
        self.assertEqual(self.state['view']['phase'], 'Due')
        self.assertEqual(self.state['view']['missed'], 2)

    def test_missed_over_limit_failclosed(self):
        self.change('Tick', 240000)
        self.assertEqual(self.state['view']['phase'], 'FailedClosed')
        self.assertEqual(self.state['view']['reason'], 'MissedCycleLimit')

    def test_missed_cycle_no_burst_runs(self):
        self.change('Tick', 180000)
        self.change('Start', 180001, run_id='run-1')
        self.assertEqual(self.state['view']['started'], 1)
        self.reject(self.ev('Start', 180002, run_id='run-2'))

    def test_policy_zero_missed_refuses_late(self):
        policy = r5.policy_example()
        policy['max_missed'] = 0
        state = r5.new_state(policy, boot_id='boot-a', mono_ms=0, wall_ms=1000000)
        result = r5.transition(policy, state, self.ev('Tick', 120000))
        self.assertEqual(result['view']['phase'], 'FailedClosed')

    def test_restart_idle_quarantines(self):
        self.change('Restart', 0, boot_id='boot-b', prior_boot_id='boot-a', wall_ms=1_050_000)
        self.assertEqual(self.state['view']['phase'], 'Quarantined')

    def test_restart_running_failsclosed(self):
        self.running()
        self.change('Restart', 0, boot_id='boot-b', prior_boot_id='boot-a', wall_ms=1_080_000)
        self.assertEqual(self.state['view']['reason'], 'AmbiguousRestart')
        self.assertEqual(self.state['view']['aborted'], 1)

    def test_restart_due_failsclosed(self):
        self.due()
        self.change('Restart', 0, boot_id='boot-b', prior_boot_id='boot-a', wall_ms=1_080_000)
        self.assertEqual(self.state['view']['phase'], 'FailedClosed')

    def test_restart_stopped_quarantines(self):
        self.change('Shutdown', 1000)
        self.change('Restart', 0, boot_id='boot-b', prior_boot_id='boot-a', wall_ms=1_050_000)
        self.assertEqual(self.state['view']['phase'], 'Quarantined')

    def test_resume_without_restart_refused(self):
        self.reject(self.ev('Resume', 1000))

    def test_resume_before_quarantine_refused(self):
        self.change('Restart', 0, boot_id='boot-b', prior_boot_id='boot-a', wall_ms=1_050_000)
        self.reject(self.ev('Resume', 89999, boot_id='boot-b', wall_ms=1_139_999))

    def test_explicit_resume_at_quarantine(self):
        self.change('Restart', 0, boot_id='boot-b', prior_boot_id='boot-a', wall_ms=1_050_000)
        self.change('Resume', 90000, boot_id='boot-b', wall_ms=1_140_000)
        self.assertEqual(self.state['view']['phase'], 'Idle')
        self.assertEqual(self.state['view']['next_due_ms'], 150000)

    def test_no_run_while_quarantined(self):
        self.change('Restart', 0, boot_id='boot-b', prior_boot_id='boot-a', wall_ms=1_050_000)
        self.change('Tick', 120000, boot_id='boot-b', wall_ms=1_170_000)
        self.assertEqual(self.state['view']['started'], 0)
        self.assertEqual(self.state['view']['phase'], 'Quarantined')

    def test_failedclosed_cannot_resume(self):
        self.running()
        self.change('Restart', 0, boot_id='boot-b', prior_boot_id='boot-a', wall_ms=1_080_000)
        self.reject(self.ev('Resume', 90000, boot_id='boot-b', wall_ms=1_170_000))

    def test_restart_wrong_prior_refused(self):
        self.reject(self.ev('Restart', 0, boot_id='boot-b', prior_boot_id='wrong', wall_ms=1_030_000))

    def test_restart_same_boot_refused(self):
        self.reject(self.ev('Restart', 0, boot_id='boot-a', prior_boot_id='boot-a'))

    def test_restart_wall_rollback_refused(self):
        self.reject(self.ev('Restart', 0, boot_id='boot-b', prior_boot_id='boot-a', wall_ms=997999))

    def test_reset_monotonic_without_restart_refused(self):
        self.change('Tick', 5000)
        self.reject(self.ev('Tick', 0))

    def test_old_boot_rejected_after_restart(self):
        self.change('Restart', 0, boot_id='boot-b', prior_boot_id='boot-a', wall_ms=1_050_000)
        self.reject(self.ev('Tick', 1000, wall_ms=1_051_000))

    def test_clock_jump_failclosed(self):
        self.change('Tick', 1000, wall_ms=1_008_000)
        self.assertEqual(self.state['view']['reason'], 'SyntheticClockAnomaly')

    def test_clock_backward_failclosed(self):
        self.change('Tick', 1000, wall_ms=998000)
        self.assertEqual(self.state['view']['phase'], 'FailedClosed')

    def test_clock_skew_boundary_accepted(self):
        self.change('Tick', 1000, wall_ms=1_003_000)
        self.assertEqual(self.state['view']['phase'], 'Idle')

    def test_wall_changed_same_monotonic_refused(self):
        self.reject(self.ev('Tick', 0, wall_ms=1_000_001))

    def test_running_clock_fault_aborts(self):
        self.running()
        self.change('Tick', 60200, wall_ms=1_100_000)
        self.assertEqual(self.state['view']['aborted'], 1)

    def test_shutdown_idle_stops(self):
        self.change('Shutdown', 1000)
        self.assertEqual(self.state['view']['phase'], 'Stopped')

    def test_shutdown_active_aborts(self):
        self.running()
        self.change('Shutdown', 60500)
        self.assertEqual(self.state['view']['aborted'], 1)
        self.assertEqual(self.state['view']['phase'], 'Stopped')

    def test_shutdown_no_implicit_restart(self):
        self.change('Shutdown', 1000)
        self.change('Tick', 120000)
        self.assertEqual(self.state['view']['started'], 0)

    def test_shutdown_does_not_unfailclosed(self):
        self.change('Tick', 1000, wall_ms=1_010_000)
        self.change('Shutdown', 2000, wall_ms=1_011_000)
        self.assertEqual(self.state['view']['phase'], 'FailedClosed')

    def test_replay_identical_event_is_immutable(self):
        e = self.change('Tick', 1000)
        prior = r5.dump_state(self.policy, self.state)
        self.assertEqual(r5.dump_state(self.policy, r5.transition(self.policy, self.state, e)), prior)

    def test_replay_conflicting_event_refused(self):
        e = self.change('Tick', 1000)
        changed = {**e, 'wall_ms': e['wall_ms'] + 1}
        self.reject(changed)

    def test_roundtrip_replay_resume(self):
        self.finished()
        encoded = r5.dump_state(self.policy, self.state)
        restored = r5.load_state(self.policy, encoded)
        event = self.ev('Tick', 120000)
        a = r5.transition(self.policy, self.state, event)
        b = r5.transition(self.policy, restored, event)
        self.assertEqual(a, b)

    def test_restart_roundtrip_persists_quarantine(self):
        self.change('Restart', 0, boot_id='boot-b', prior_boot_id='boot-a', wall_ms=1_050_000)
        restore = r5.load_state(self.policy, r5.dump_state(self.policy, self.state))
        self.assertEqual(restore['view']['quarantine_until_ms'], 90000)

    def test_snapshot_detached_from_original(self):
        snapshot = r5.inspect(self.policy, self.state)
        snapshot['started'] = 888
        self.assertEqual(self.state['view']['started'], 0)

    def test_transition_does_not_mutate_input(self):
        old = copy.deepcopy(self.state)
        r5.transition(self.policy, self.state, self.ev('Tick', 1000))
        self.assertEqual(self.state, old)

    def test_genesis_invalid_id(self):
        with self.assertRaises(r5.OfflineTimingError):
            r5.new_state(self.policy, boot_id='../escape', mono_ms=0, wall_ms=1_000_000)

    def test_genesis_negative_mono(self):
        with self.assertRaises(r5.OfflineTimingError):
            r5.new_state(self.policy, boot_id='boot-a', mono_ms=-1, wall_ms=1_000_000)

    def test_event_bad_kind(self):
        self.reject(self.ev('LiveProbe', 100))

    def test_event_wrong_shape(self):
        self.reject({**self.ev('Tick', 100), 'repair': True})

    def test_event_bad_id(self):
        self.reject({**self.ev('Tick', 100), 'event_id': '../evil'})

    def test_event_boolean_time(self):
        self.reject({**self.ev('Tick', 100), 'mono_ms': True})

    def test_event_negative_wall(self):
        self.reject({**self.ev('Tick', 100), 'wall_ms': -1})

    def test_event_live_provenance_refused(self):
        self.reject({**self.ev('Tick', 100), 'source': 'Live'})

    def test_event_bad_finish_outcome(self):
        self.reject(self.ev('Finish', 100, run_id='run-1', outcome='Delivered'))

    def test_event_extra_run_id_on_tick(self):
        self.reject(self.ev('Tick', 100, run_id='run-1'))

    def test_event_missing_boot(self):
        e = self.ev('Tick', 100); del e['boot_id']
        self.reject(e)

    def test_empty_history_initial_hash(self):
        self.assertEqual(self.state['head_sha256'], '0' * 64)

    def test_record_chain_consistent(self):
        self.finished()
        self.assertEqual(self.state['events'][-1]['sha256'], self.state['head_sha256'])

    def test_detect_bad_record_hash(self):
        self.change('Tick', 100)
        tampered = copy.deepcopy(self.state)
        tampered['events'][0]['sha256'] = 'f' * 64
        with self.assertRaises(r5.OfflineTimingError): r5.inspect(self.policy, tampered)

    def test_detect_bad_record_previous_hash(self):
        self.change('Tick', 100)
        tampered = copy.deepcopy(self.state)
        tampered['events'][0]['prev_sha256'] = 'a' * 64
        with self.assertRaises(r5.OfflineTimingError): r5.inspect(self.policy, tampered)

    def test_detect_projection_tamper(self):
        tampered = copy.deepcopy(self.state)
        tampered['view']['started'] = 20
        with self.assertRaises(r5.OfflineTimingError): r5.inspect(self.policy, tampered)

    def test_detect_head_tamper(self):
        tampered = copy.deepcopy(self.state)
        tampered['head_sha256'] = 'a' * 64
        with self.assertRaises(r5.OfflineTimingError): r5.inspect(self.policy, tampered)

    def test_detect_wrong_policy(self):
        other = r5.policy_example(); other['interval_ms'] += 1000
        with self.assertRaises(r5.OfflineTimingError): r5.inspect(other, self.state)

    def test_detect_changed_genesis(self):
        tampered = copy.deepcopy(self.state)
        tampered['genesis']['boot_id'] = 'boot-other'
        with self.assertRaises(r5.OfflineTimingError): r5.inspect(self.policy, tampered)

    def test_detect_changed_provenance(self):
        tampered = copy.deepcopy(self.state)
        tampered['provenance'] = 'RealService'
        with self.assertRaises(r5.OfflineTimingError): r5.inspect(self.policy, tampered)

    def test_detect_extra_root_property(self):
        tampered = copy.deepcopy(self.state)
        tampered['secret'] = True
        with self.assertRaises(r5.OfflineTimingError): r5.inspect(self.policy, tampered)

    def test_corrupted_serialized_refused(self):
        with self.assertRaises(r5.OfflineTimingError): r5.load_state(self.policy, '{broken')

    def test_duplicate_json_key_refused(self):
        with self.assertRaises(r5.OfflineTimingError): r5.load_state(self.policy, '{"a":1,"a":2}')

    def test_nonfinite_json_refused(self):
        with self.assertRaises(r5.OfflineTimingError): r5.load_state(self.policy, '{"n":NaN}')

    def test_serialized_oversize_refused(self):
        with self.assertRaises(r5.OfflineTimingError): r5.load_state(self.policy, ' ' * 70000)

    def test_capacity_fail_closed_no_prune(self):
        state = self.state
        for tick in range(1, r5.MAX_EVENTS + 1):
            e = {'event_id': f'ev-{tick}', 'kind':'Tick','boot_id':'boot-a',
                 'mono_ms':tick,'wall_ms':1000000 + tick}
            state = r5.transition(self.policy, state, e)
        with self.assertRaises(r5.OfflineTimingError):
            r5.transition(self.policy, state, {'event_id':'ev-over','kind':'Tick',
                'boot_id':'boot-a','mono_ms':129,'wall_ms':1000129})
        self.assertEqual(len(state['events']), r5.MAX_EVENTS)

    def test_duplicate_replay_allowed_at_capacity(self):
        state = self.state
        initial_event = None
        for tick in range(1, r5.MAX_EVENTS + 1):
            e = {'event_id': f'ev-{tick}', 'kind':'Tick','boot_id':'boot-a',
                 'mono_ms':tick,'wall_ms':1000000 + tick}
            if tick == 1: initial_event = e
            state = r5.transition(self.policy, state, e)
        self.assertEqual(state, r5.transition(self.policy, state, initial_event))

    def test_no_automatic_polling_in_module(self):
        src = MODULE.read_text(encoding='utf-8')
        for token in ('Get-ScheduledTask', 'Register-ScheduledTask',
                      'subprocess.run(', 'socket.connect(', 'time.sleep(',
                      'requests.post(', 'Repair-ICS.ps1'):
            self.assertNotIn(token, src)

    def test_no_live_store_literals(self):
        src = MODULE.read_text(encoding='utf-8')
        self.assertNotIn('OnyxCore-v070-Release', src)
        self.assertNotIn('OnyxCore-v070-Development', src)

    def test_no_notification_or_repair_capability(self):
        self.finished()
        self.assertFalse(self.state['view']['notification_enabled'])
        self.assertFalse(r5.inert_status()['delivery_permitted'])
        self.assertEqual(r5.inert_status()['repair_action'], 'None')

    def test_restart_is_never_implicit_task_creation(self):
        self.change('Restart', 0, boot_id='boot-b', prior_boot_id='boot-a', wall_ms=1_050_000)
        self.assertFalse(self.state['view']['task_created'])

    def test_policy_not_mutated(self):
        old = copy.deepcopy(self.policy)
        self.change('Tick', 100)
        self.assertEqual(self.policy, old)

    def test_state_json_deterministic(self):
        self.finished()
        a = r5.dump_state(self.policy, self.state)
        b = r5.dump_state(self.policy, self.state)
        self.assertEqual(a, b)

    def test_clock_evidence_not_authenticated(self):
        self.change('Tick', 100)
        self.assertFalse(r5.inert_status()['windows_clock_attested'])

    def test_invalid_resume_from_stopped(self):
        self.change('Shutdown', 1000)
        self.reject(self.ev('Resume', 2000))

    def test_stopped_does_not_accept_start(self):
        self.change('Shutdown', 1000)
        self.reject(self.ev('Start', 60000, run_id='run-1'))

    def test_failed_closed_does_not_accept_start(self):
        self.change('Tick', 240000)
        self.reject(self.ev('Start', 240010, run_id='run-1'))

    def test_restarted_boot_id_serializes(self):
        self.change('Restart', 0, boot_id='boot-b', prior_boot_id='boot-a', wall_ms=1_050_000)
        s = r5.load_state(self.policy, r5.dump_state(self.policy, self.state))
        self.assertEqual(s['view']['boot_id'], 'boot-b')


# Each generated method is an individually discoverable, genuine negative test.
BAD_POLICY_CASES = (
    ('schema', 'v2'), ('source', 'Other'), ('simulation_only', False),
    ('simulation_only', 'true'), ('interval_ms', 29999), ('interval_ms', 3600001),
    ('interval_ms', True), ('max_run_ms', 999), ('max_run_ms', 300001),
    ('max_run_ms', 60000), ('max_run_ms', 1.0),
    ('restart_quarantine_ms', 29999), ('restart_quarantine_ms', 3600001),
    ('max_missed', -1), ('max_missed', 9), ('max_missed', True),
    ('clock_skew_ms', -1), ('clock_skew_ms', 10001),
    ('clock_skew_ms', 3.5),
)


def _make_bad_policy_test(key, invalid):
    def test(self):
        policy = r5.policy_example()
        policy[key] = invalid
        with self.assertRaises(r5.OfflineTimingError):
            r5.new_state(policy, boot_id='boot-a', mono_ms=0, wall_ms=1_000_000)
    return test


for _index, (_key, _invalid) in enumerate(BAD_POLICY_CASES, start=1):
    setattr(R5TimingTests, f'test_bad_policy_{_index:02d}_{_key}',
            _make_bad_policy_test(_key, _invalid))


if __name__ == '__main__':
    unittest.main()
