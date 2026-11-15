#!/usr/bin/env python3
"""ONYX CORE v0.8 R5: inert foreground session-to-release-binding adapter.

NO operational CLI. Not a trusted entry point. The eventual admin-pinned
release operator must supply fresh protected-source/native-session consent
checks AND the real release binding. A developer-injected callback is NOT
independent authorization. Only one bounded cycle is requested per worker;
the R4 supervisor supplies between-cycle waits and fail-closed rechecks.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from typing import Callable

import OnyxGuardedRuntimeBridge as bridge
import OnyxV080ReleaseBinding as binding
import OnyxV080SessionSupervisor as supervisor


class SessionIntegrationRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class IntegrationResult:
    attempts: int
    completed_cycles: int
    worker_failures: int
    state: str
    persisted_cycles: int
    foreground_only: bool = True
    notifications_sent: bool = False
    repairs_invoked: bool = False
    tasks_created: bool = False


def run_reviewed_session(*, wiring: binding.ReleaseWiring,
                         policy: supervisor.SessionPolicy,
                         authorize: Callable[[], bool],
                         active_console: Callable[[], bool],
                         attest_source: Callable[[], bool],
                         run_release_cycle: Callable[[binding.ReleaseWiring], bridge.BoundedRuntimeResult],
                         clock: Callable[[], float],
                         sleep: Callable[[float], None]) -> IntegrationResult:
    """Composition-only API. No default worker, consent, or clock.

    ``run_release_cycle`` must be bound by the protected operator to
    ``binding.run_explicitly_approved_api`` with its real rechecking authorizer;
    that code owns the global/foreground lock, Job containment, probe/write
    consent checks and M3 persistence. Only a fully persisted single-cycle
    bridge result counts as success. Unexpected worker exceptions propagate
    (never silently become retryable faults).
    """
    if not isinstance(wiring, binding.ReleaseWiring) or not isinstance(policy, supervisor.SessionPolicy):
        raise SessionIntegrationRefused('reviewed release wiring and policy required')
    if not all(callable(x) for x in (authorize, active_console, attest_source,
                                     run_release_cycle, clock, sleep)):
        raise SessionIntegrationRefused('missing trusted runtime integration dependency')
    if wiring.cycles != 1:
        raise SessionIntegrationRefused('only a one-cycle reviewed wiring is permitted')
    config = binding.read_reviewed_release_config(wiring)
    if policy.interval_seconds != config['monitoring_interval_seconds']:
        raise SessionIntegrationRefused('supervisor interval differs from approved release configuration')
    binding.require_release_storage_profile()
    persisted = 0

    def worker() -> bool:
        nonlocal persisted
        # Admission is the responsibility of run_release_cycle and its real
        # protected binding; this adapter refuses unverifiable completion.
        outcome = run_release_cycle(wiring)
        if not isinstance(outcome, bridge.BoundedRuntimeResult):
            raise SessionIntegrationRefused('unrecognized protected worker result')
        if (outcome.live_mode is not True or outcome.cycles != 1 or
                outcome.persisted_cycles != 1 or outcome.notifications_sent is not False or
                outcome.repairs_invoked is not False or outcome.tasks_created is not False):
            raise SessionIntegrationRefused('worker did not complete one safe persisted cycle')
        persisted += 1
        return True

    outcome = supervisor.supervise_session(
        policy, authorize=authorize, active_console=active_console,
        attest_source=attest_source, run_one_cycle=worker,
        clock=clock, sleep=sleep,
    )
    if persisted != outcome.completed_cycles:
        raise SessionIntegrationRefused('supervisor/journal completion mismatch')
    return IntegrationResult(outcome.attempts, outcome.completed_cycles,
                             outcome.worker_failures, outcome.state, persisted)


def main(argv=None):
    parser = argparse.ArgumentParser(description='R5 inert release-supervision composition')
    parser.add_argument('--check-inert', required=True, action='store_true')
    parser.parse_args(argv)
    print(json.dumps({'phase': 'R5-supervision-integration', 'cli_live_enabled': False,
                      'trusted_operator_wired': False, 'notifications_enabled': False,
                      'task_creation_enabled': False, 'release_status': 'HOLD'},
                     sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
