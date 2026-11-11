#!/usr/bin/env python3
"""ONYX CORE R5: deterministic SYNTHETIC lifecycle/timing simulator.

No scheduler, real clock, sockets, task APIs, worker, filesystem writes, or
runtime enrollment. Every timestamp, boot ID and operator resume is a test
fixture supplied by the caller; none proves actual execution or authorization.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

SOURCE = 'OnyxV080R5SyntheticLifecycleTiming'
PROVENANCE = 'SyntheticInputOnly'
SCHEMA = 'onyx-r5-offline-v1'
POLICY_SCHEMA = 'onyx-r5-policy-v1'
MAX_EVENTS = 128
MAX_STATE_BYTES = 65536
ZERO = '0' * 64
ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$')
POLICY_FIELDS = frozenset(('schema', 'source', 'simulation_only', 'interval_ms',
    'max_run_ms', 'restart_quarantine_ms', 'max_missed', 'clock_skew_ms'))
EVENT_COMMON = frozenset(('event_id', 'kind', 'boot_id', 'mono_ms', 'wall_ms'))
EVENT_EXTRA = {
    'Tick': frozenset(), 'Start': frozenset(('run_id',)),
    'Finish': frozenset(('run_id', 'outcome')),
    'Shutdown': frozenset(), 'Restart': frozenset(('prior_boot_id',)),
    'Resume': frozenset(),
}
PUBLIC_PHASES = frozenset(('Idle', 'Due', 'Running', 'Quarantined', 'Stopped', 'FailedClosed'))
VIEW_FIELDS = frozenset(('phase', 'boot_id', 'mono_ms', 'wall_ms', 'next_due_ms',
    'pending_due_ms', 'run_id', 'deadline_ms', 'quarantine_until_ms',
    'started', 'completed', 'failed', 'aborted', 'missed', 'restarts',
    'reason', 'simulation_only', 'runtime_enabled', 'task_created',
    'notification_enabled', 'live_probe_authorized'))
STATE_FIELDS = frozenset(('schema', 'source', 'provenance', 'simulation_only',
    'policy_digest', 'genesis', 'events', 'view', 'head_sha256'))
GENESIS_FIELDS = frozenset(('boot_id', 'mono_ms', 'wall_ms'))
RECORD_FIELDS = frozenset(('event', 'prev_sha256', 'sha256'))


class OfflineTimingError(ValueError):
    """Fail-closed invalid synthetic state or action; no side effects."""


def _need(ok: bool, why: str) -> None:
    if not ok:
        raise OfflineTimingError(why)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError, UnicodeError) as ex:
        raise OfflineTimingError('noncanonical JSON') from ex


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _exact_int(value: Any, lo: int, hi: int, field: str) -> None:
    _need(type(value) is int and lo <= value <= hi, 'invalid ' + field)


def _id(value: Any, field: str) -> None:
    _need(type(value) is str and bool(ID_RE.fullmatch(value)), 'invalid ' + field)


def _keys(value: Any, fields: frozenset, label: str) -> None:
    _need(type(value) is dict and frozenset(value) == fields, 'invalid ' + label)


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        _need(key not in result, 'duplicate JSON field')
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise OfflineTimingError('nonfinite JSON')


def _decode(value: Any) -> Any:
    _need(type(value) is str and len(value.encode('utf-8')) <= MAX_STATE_BYTES,
          'serialized input too large')
    try:
        return json.loads(value, object_pairs_hook=_pairs,
                          parse_constant=_invalid_constant)
    except (ValueError, TypeError, UnicodeError) as ex:
        raise OfflineTimingError('invalid serialized input') from ex


def policy_example() -> dict:
    return {'schema': POLICY_SCHEMA, 'source': SOURCE, 'simulation_only': True,
            'interval_ms': 60000, 'max_run_ms': 30000,
            'restart_quarantine_ms': 90000, 'max_missed': 2,
            'clock_skew_ms': 2000}


def _policy(policy: Any) -> str:
    _keys(policy, POLICY_FIELDS, 'policy schema')
    _need(policy['schema'] == POLICY_SCHEMA and policy['source'] == SOURCE and
          policy['simulation_only'] is True, 'only synthetic policy')
    _exact_int(policy['interval_ms'], 30000, 3600000, 'interval')
    _exact_int(policy['max_run_ms'], 1000, 300000, 'run budget')
    _need(policy['max_run_ms'] < policy['interval_ms'], 'run budget must fit interval')
    _exact_int(policy['restart_quarantine_ms'], 30000, 3600000, 'quarantine')
    _exact_int(policy['max_missed'], 0, 8, 'missed-cycle cap')
    _exact_int(policy['clock_skew_ms'], 0, 10000, 'clock skew')
    return _sha(_canonical(policy))


def _event(event: Any) -> None:
    _need(type(event) is dict and type(event.get('kind')) is str and
          event['kind'] in EVENT_EXTRA, 'unknown synthetic event')
    _keys(event, EVENT_COMMON | EVENT_EXTRA[event['kind']], 'event shape')
    _id(event['event_id'], 'event id')
    _id(event['boot_id'], 'boot id')
    _exact_int(event['mono_ms'], 0, 2**53 - 1, 'synthetic monotonic')
    _exact_int(event['wall_ms'], 0, 2**53 - 1, 'synthetic wall clock')
    if event['kind'] in ('Start', 'Finish'):
        _id(event['run_id'], 'run id')
    if event['kind'] == 'Finish':
        _need(type(event['outcome']) is str and
              event['outcome'] in ('Success', 'Failure'), 'outcome')
    if event['kind'] == 'Restart':
        _id(event['prior_boot_id'], 'prior boot id')
        _need(event['boot_id'] != event['prior_boot_id'], 'same boot cannot restart')


def _initial_view(policy: dict, genesis: dict) -> dict:
    return {'phase': 'Idle', 'boot_id': genesis['boot_id'],
            'mono_ms': genesis['mono_ms'], 'wall_ms': genesis['wall_ms'],
            'next_due_ms': genesis['mono_ms'] + policy['interval_ms'],
            'pending_due_ms': None, 'run_id': None, 'deadline_ms': None,
            'quarantine_until_ms': None, 'started': 0, 'completed': 0,
            'failed': 0, 'aborted': 0, 'missed': 0, 'restarts': 0,
            'reason': 'SyntheticOnly', 'simulation_only': True,
            'runtime_enabled': False, 'task_created': False,
            'notification_enabled': False, 'live_probe_authorized': False}


def new_state(policy: dict, *, boot_id: str, mono_ms: int, wall_ms: int) -> dict:
    digest = _policy(policy)
    genesis = {'boot_id': boot_id, 'mono_ms': mono_ms, 'wall_ms': wall_ms}
    _genesis(genesis)
    result = {'schema': SCHEMA, 'source': SOURCE,
              'provenance': PROVENANCE, 'simulation_only': True,
              'policy_digest': digest, 'genesis': genesis,
              'events': [], 'view': _initial_view(policy, genesis),
              'head_sha256': ZERO}
    _validate(policy, result)
    return result


def _genesis(genesis: Any) -> None:
    _keys(genesis, GENESIS_FIELDS, 'genesis')
    _id(genesis['boot_id'], 'genesis boot')
    _exact_int(genesis['mono_ms'], 0, 2**53 - 3600000, 'genesis monotonic')
    _exact_int(genesis['wall_ms'], 0, 2**53 - 3600000, 'genesis wall')


def _compute(policy: dict, prior: dict, event: dict) -> dict:
    """Pure deterministic transition; called only after input validation."""
    out = copy.deepcopy(prior)
    kind = event['kind']
    mono = event['mono_ms']
    wall = event['wall_ms']
    interval = policy['interval_ms']

    if kind == 'Restart':
        _need(event['prior_boot_id'] == prior['boot_id'], 'prior boot mismatch')
        # New boot monotonic origin is not comparable to the previous boot.
        # Restart is never an implicit authorization or recovery.
        _need(wall >= prior['wall_ms'] - policy['clock_skew_ms'],
              'new boot wall clock rollback')
        active = prior['phase'] in ('Running', 'Due')
        failed = prior['phase'] == 'FailedClosed' or active
        if prior['phase'] == 'Running':
            out['aborted'] += 1
        out.update(boot_id=event['boot_id'], mono_ms=mono, wall_ms=wall,
                   next_due_ms=mono + interval, pending_due_ms=None,
                   run_id=None, deadline_ms=None,
                   quarantine_until_ms=mono + policy['restart_quarantine_ms'],
                   restarts=prior['restarts'] + 1,
                   phase='FailedClosed' if failed else 'Quarantined',
                   reason=('AmbiguousRestart' if active else
                           'PriorFailure' if failed else 'RestartQuarantine'))
        return out

    _need(event['boot_id'] == prior['boot_id'], 'boot mismatch')
    _need(mono >= prior['mono_ms'], 'monotonic moved backwards')
    _need(wall >= 0, 'bad clock')
    _need(not (mono == prior['mono_ms'] and wall != prior['wall_ms']),
          'clock mutated without monotonic progress')
    # Clock comparison uses only caller-supplied synthetic evidence.
    skew = abs((wall - prior['wall_ms']) - (mono - prior['mono_ms']))
    out['mono_ms'] = mono
    out['wall_ms'] = wall
    if skew > policy['clock_skew_ms']:
        if prior['phase'] == 'Running':
            out['aborted'] += 1
        out.update(phase='FailedClosed', reason='SyntheticClockAnomaly',
                   pending_due_ms=None, run_id=None, deadline_ms=None,
                   quarantine_until_ms=None)
        return out

    phase = prior['phase']
    if kind == 'Shutdown':
        if phase == 'Running':
            out['aborted'] += 1
        if phase != 'FailedClosed':
            out.update(phase='Stopped', reason='SyntheticShutdown',
                       pending_due_ms=None, run_id=None, deadline_ms=None,
                       quarantine_until_ms=None)
        return out

    if kind == 'Tick':
        if phase == 'Running':
            if mono > prior['deadline_ms']:
                out.update(phase='FailedClosed', reason='RunDeadlineExceeded',
                           aborted=out['aborted'] + 1, run_id=None,
                           deadline_ms=None)
        elif phase == 'Idle' and mono >= prior['next_due_ms']:
            missed = (mono - prior['next_due_ms']) // interval
            if missed > policy['max_missed']:
                out.update(phase='FailedClosed', reason='MissedCycleLimit',
                           missed=out['missed'] + missed)
            else:
                due = prior['next_due_ms'] + missed * interval
                out.update(phase='Due', reason='SyntheticDue',
                           missed=out['missed'] + missed,
                           pending_due_ms=due,
                           next_due_ms=due + interval)
        elif phase == 'Due' and mono >= prior['next_due_ms']:
            out.update(phase='FailedClosed', reason='UnclaimedDueWindow',
                       pending_due_ms=None)
        return out

    if kind == 'Start':
        _need(phase == 'Due' and prior['pending_due_ms'] is not None,
              'cannot start without due slot or while active')
        _need(mono < prior['next_due_ms'], 'due slot expired')
        out.update(phase='Running', reason='SyntheticStarted',
                   run_id=event['run_id'],
                   deadline_ms=min(mono + policy['max_run_ms'], prior['next_due_ms']),
                   pending_due_ms=None, started=out['started'] + 1)
        return out

    if kind == 'Finish':
        _need(phase == 'Running' and event['run_id'] == prior['run_id'],
              'wrong run or no active run')
        if mono > prior['deadline_ms']:
            out.update(phase='FailedClosed', reason='LateSyntheticFinish',
                       aborted=out['aborted'] + 1, run_id=None, deadline_ms=None)
        elif event['outcome'] == 'Success':
            out.update(phase='Idle', reason='SyntheticCompleted',
                       completed=out['completed'] + 1, run_id=None, deadline_ms=None)
        else:
            out.update(phase='FailedClosed', reason='SyntheticWorkerFailure',
                       failed=out['failed'] + 1, run_id=None, deadline_ms=None)
        return out

    if kind == 'Resume':
        _need(phase == 'Quarantined', 'only quarantine can be resumed')
        _need(mono >= prior['quarantine_until_ms'], 'restart quarantine not elapsed')
        # Only a simulated explicit resume, never a scheduler or Windows consent.
        out.update(phase='Idle', reason='SyntheticResumeOnly',
                   quarantine_until_ms=None, next_due_ms=mono + interval)
        return out
    raise OfflineTimingError('unsupported event')


def _validate(policy: dict, state: Any) -> dict:
    expected = _policy(policy)
    _keys(state, STATE_FIELDS, 'state')
    _need(state['schema'] == SCHEMA and state['source'] == SOURCE and
          state['provenance'] == PROVENANCE and state['simulation_only'] is True and
          state['policy_digest'] == expected, 'wrong synthetic snapshot provenance')
    _genesis(state['genesis'])
    _need(type(state['events']) is list and len(state['events']) <= MAX_EVENTS,
          'history capacity')
    view = _initial_view(policy, state['genesis'])
    seen = set()
    prev = ZERO
    for rec in state['events']:
        _keys(rec, RECORD_FIELDS, 'history record')
        _event(rec['event'])
        _need(rec['event']['event_id'] not in seen, 'duplicate historical id')
        seen.add(rec['event']['event_id'])
        _need(rec['prev_sha256'] == prev, 'broken record chain')
        digest = _sha(prev + ':' + _canonical(rec['event']))
        _need(rec['sha256'] == digest, 'tampered record digest')
        view = _compute(policy, view, rec['event'])
        prev = digest
    _keys(state['view'], VIEW_FIELDS, 'state view')
    _need(_canonical(state['view']) == _canonical(view), 'tampered lifecycle projection')
    _need(state['view']['phase'] in PUBLIC_PHASES, 'phase mismatch')
    _need(state['head_sha256'] == prev, 'head checksum mismatch')
    _need(len(_canonical(state).encode('utf-8')) <= MAX_STATE_BYTES,
          'state too large')
    return view


def inspect(policy: dict, state: dict) -> dict:
    _validate(policy, state)
    return copy.deepcopy(state['view'])


def transition(policy: dict, state: dict, event: dict) -> dict:
    view = _validate(policy, state)
    _event(event)
    for record in state['events']:
        old = record['event']
        if old['event_id'] == event['event_id']:
            _need(_canonical(old) == _canonical(event), 'conflicting replay id')
            return copy.deepcopy(state)
    _need(len(state['events']) < MAX_EVENTS, 'history full; no auto prune')
    # Every state change is pure; reject invalid event without modifying caller.
    result = copy.deepcopy(state)
    new_view = _compute(policy, view, event)
    prev = state['head_sha256']
    digest = _sha(prev + ':' + _canonical(event))
    result['events'].append({'event': copy.deepcopy(event),
                             'prev_sha256': prev, 'sha256': digest})
    result['view'] = new_view
    result['head_sha256'] = digest
    _validate(policy, result)
    return result


def dump_state(policy: dict, state: dict) -> str:
    _validate(policy, state)
    return _canonical(state)


def load_state(policy: dict, serialized: str) -> dict:
    obj = _decode(serialized)
    _validate(policy, obj)
    return obj


def inert_status() -> dict:
    return {'source': SOURCE, 'simulation_only': True,
            'provenance': PROVENANCE, 'runtime_enabled': False,
            'live_probe_authorized': False, 'task_creation_authorized': False,
            'store_modified': False, 'notification_enabled': False,
            'delivery_permitted': False, 'real_store_authorized': False,
            'identity_authenticated_in_windows': False,
            'windows_clock_attested': False, 'scheduler_started': False,
            'worker_spawned': False, 'transport_calls': 0, 'repair_action': 'None'}


def _main() -> int:
    import sys
    if sys.argv[1:] != ['--check-inert']:
        print('REFUSED: R5 has no runtime, scheduler, service or live operation.', file=sys.stderr)
        return 2
    print(_canonical(inert_status()))
    return 0


if __name__ == '__main__':
    raise SystemExit(_main())
