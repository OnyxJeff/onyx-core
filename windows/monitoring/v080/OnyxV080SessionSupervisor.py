#!/usr/bin/env python3
"""ONYX CORE v0.8 R4: offline-first, session-bound supervision policy.

This module deliberately has NO Windows, process, network, credential, task,
filesystem, or notification implementation. Its policy can only be driven by
explicitly injected callbacks. Its CLI refuses any operational start action.

The caller must independently authenticate each consent, session/source and
per-cycle runtime boundary; this module cannot mint, cache or extend grants.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from typing import Callable

POLL_SLICE_SECONDS = 2.0
MAX_CYCLES = 20
MAX_DURATION_SECONDS = 86400
MAX_FAILURES = 3
BACKOFF_SECONDS = (5.0, 15.0, 30.0)


class SupervisionRefused(RuntimeError):
    """A fail-closed supervision policy boundary was violated."""


@dataclass(frozen=True)
class SessionPolicy:
    maximum_cycles: int
    maximum_duration_seconds: int
    interval_seconds: int = 120
    maximum_consecutive_failures: int = MAX_FAILURES

    def __post_init__(self):
        if type(self.maximum_cycles) is not int or not 1 <= self.maximum_cycles <= MAX_CYCLES:
            raise SupervisionRefused('invalid bounded session cycle count')
        if (type(self.maximum_duration_seconds) is not int or
                not 1 <= self.maximum_duration_seconds <= MAX_DURATION_SECONDS):
            raise SupervisionRefused('invalid session duration')
        if type(self.interval_seconds) is not int or not 90 <= self.interval_seconds <= 3600:
            raise SupervisionRefused('invalid interval')
        if (type(self.maximum_consecutive_failures) is not int or
                not 1 <= self.maximum_consecutive_failures <= MAX_FAILURES):
            raise SupervisionRefused('invalid restart budget')


@dataclass(frozen=True)
class SessionOutcome:
    attempts: int
    completed_cycles: int
    worker_failures: int
    state: str
    foreground_only: bool = True
    tasks_created: bool = False
    notifications_sent: bool = False
    repairs_invoked: bool = False


def _finite_time(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SupervisionRefused('invalid monotonic clock')
    return float(value)


def _approved(authorize: Callable[[], bool], session: Callable[[], bool],
              source: Callable[[], bool]) -> None:
    # No memoization: check all three fresh before every worker and wakeup.
    # Failures propagate as denial; no fail-open behavior.
    if session() is not True:
        raise SupervisionRefused('not in the approved active console session')
    if source() is not True:
        raise SupervisionRefused('source attestation refused')
    if authorize() is not True:
        raise SupervisionRefused('authorization expired or revoked')


def _wait_bounded(seconds: float, *, deadline: float, clock: Callable[[], float],
                  sleep: Callable[[float], None], authorize: Callable[[], bool],
                  session: Callable[[], bool], source: Callable[[], bool]) -> bool:
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not math.isfinite(seconds) or seconds < 0:
        raise SupervisionRefused('invalid requested wait')
    # Honor absolute deadline rather than resetting it after a worker failure.
    remaining = float(seconds)
    while remaining > 0:
        _approved(authorize, session, source)
        available = deadline - _finite_time(clock())
        if available <= 0:
            return False
        pause = min(POLL_SLICE_SECONDS, remaining, available)
        if pause <= 0:
            return False
        sleep(pause)
        # Reevaluate immediately after every <= 2s bounded slice.
        _approved(authorize, session, source)
        remaining -= pause
    return deadline > _finite_time(clock())


def supervise_session(policy: SessionPolicy, *,
                      authorize: Callable[[], bool],
                      active_console: Callable[[], bool],
                      attest_source: Callable[[], bool],
                      run_one_cycle: Callable[[], bool],
                      clock: Callable[[], float],
                      sleep: Callable[[float], None]) -> SessionOutcome:
    """Pure dependency-injected foreground orchestration for offline testing.

    run_one_cycle must perform its OWN protected admission, credential rechecks,
    process containment, single-instance locking and journal persistence. An
    injected fake is used for offline acceptance. This function does not retry
    a confirmed diagnostic fault; it retries ONLY a worker execution failure.

    A false worker result is a failure, never a successful persisted check.
    """
    if not isinstance(policy, SessionPolicy) or not all(callable(f) for f in (
            authorize, active_console, attest_source, run_one_cycle, clock, sleep)):
        raise SupervisionRefused('missing bounded supervision dependency')
    started = _finite_time(clock())
    deadline = started + policy.maximum_duration_seconds
    attempts = successes = failures = consecutive = 0
    while successes < policy.maximum_cycles:
        # Check deadline and auth BEFORE spawning or calling the next worker.
        if _finite_time(clock()) >= deadline:
            return SessionOutcome(attempts, successes, failures, 'Expired')
        _approved(authorize, active_console, attest_source)
        # A callback may itself consume time; never start after the deadline.
        if _finite_time(clock()) >= deadline:
            return SessionOutcome(attempts, successes, failures, 'Expired')
        attempts += 1
        # Exceptions are NOT silently classified as retryable: caller must
        # explicitly classify worker faults without losing authorization errors.
        result = run_one_cycle()
        if type(result) is not bool:
            raise SupervisionRefused('worker must report explicit boolean completion')
        if result:
            successes += 1
            consecutive = 0
            if successes == policy.maximum_cycles:
                return SessionOutcome(attempts, successes, failures, 'Completed')
            if not _wait_bounded(policy.interval_seconds, deadline=deadline,
                                 clock=clock, sleep=sleep, authorize=authorize,
                                 session=active_console, source=attest_source):
                return SessionOutcome(attempts, successes, failures, 'Expired')
        else:
            failures += 1
            consecutive += 1
            if consecutive >= policy.maximum_consecutive_failures:
                return SessionOutcome(attempts, successes, failures, 'WorkerFailureLimit')
            backoff = BACKOFF_SECONDS[min(consecutive-1, len(BACKOFF_SECONDS)-1)]
            if not _wait_bounded(backoff, deadline=deadline,
                                 clock=clock, sleep=sleep, authorize=authorize,
                                 session=active_console, source=attest_source):
                return SessionOutcome(attempts, successes, failures, 'Expired')
    raise SupervisionRefused('unreachable supervision exit')


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description='ONYX v0.8 R4 supervision policy - inert CLI')
    p.add_argument('--check-inert', action='store_true', required=True)
    p.parse_args(argv)
    print(json.dumps({'phase': 'R4-session-supervision', 'mode': 'offline-policy',
                      'live_execution_enabled': False, 'task_creation_enabled': False,
                      'notification_delivery_enabled': False, 'production_release': 'HOLD'},
                     sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
