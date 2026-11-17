#!/usr/bin/env python3
"""ONYX CORE v0.8.0 Phase 18C: inert, injected supervisor gate prototype.

No Windows credentials, enrollment, diagnostics, services, network, scheduled
 tasks, SQLite, or production stores. This module deliberately has NO method
 that can turn simulated attestations into live authorization.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, ContextManager, Iterator
import argparse
import json


class SupervisionRefused(RuntimeError):
    """A simulated cycle cannot be admitted or completed safely."""


@dataclass(frozen=True)
class Policy:
    interval_seconds: int = 120
    maximum_cycles: int = 20

    def __post_init__(self) -> None:
        if type(self.interval_seconds) is not int or not 90 <= self.interval_seconds <= 3600:
            raise SupervisionRefused('invalid cycle interval')
        if type(self.maximum_cycles) is not int or not 1 <= self.maximum_cycles <= 20:
            raise SupervisionRefused('invalid bounded cycle count')


@dataclass(frozen=True)
class Admission:
    """Simulation data; never a trusted operator or Windows token."""
    simulation_only: bool
    revision_matches: bool
    identity_matches: bool
    storage_profile_release: bool
    grant_valid: bool
    revoked: bool
    source_trusted: bool

    def allow_fixture_cycle(self) -> None:
        if self.simulation_only is not True:
            raise SupervisionRefused('only synthetic admission may enter this prototype')
        if any(value is not True for value in (
            self.revision_matches, self.identity_matches,
            self.storage_profile_release, self.grant_valid,
            self.source_trusted,
        )) or self.revoked is not False:
            raise SupervisionRefused('synthetic cycle admission refused')


@dataclass(frozen=True)
class Result:
    cycles: int
    ignored_catchup: int
    simulation_only: bool = True
    live_probes: bool = False
    task_created: bool = False
    notifications_sent: bool = False
    production_runtime_enabled: bool = False


@contextmanager
def _inert_mutex() -> Iterator[None]:
    """Used only by pure tests; NOT a cross-session Windows mutex."""
    yield


def simulate_bounded_supervision(
    policy: Policy,
    *,
    admission: Callable[[], Admission],
    fixture_cycle: Callable[[], object],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    exclusive: Callable[[], ContextManager[None]] = _inert_mutex,
) -> Result:
    """Deterministic offline fixture execution; no live probe adapter exists.

    Fail closed on missing or revoked *simulated* admission before every cycle,
    including after a sleep. Overruns never create a catch-up backlog. The
    exclusive adapter is not an operational lock until independently attested.
    """
    if not isinstance(policy, Policy):
        raise SupervisionRefused('invalid supervisor policy')
    if not all(callable(fn) for fn in (admission, fixture_cycle, monotonic, sleep, exclusive)):
        raise SupervisionRefused('missing explicit synthetic adapters')
    ignored_catchup = 0
    with exclusive():
        for index in range(policy.maximum_cycles):
            admission().allow_fixture_cycle()
            started = monotonic()
            if type(started) not in (float, int) or not 0 <= started < float('inf'):
                raise SupervisionRefused('invalid synthetic monotonic clock')
            # A fixture's return value is *never* consumed as live evidence.
            fixture_cycle()
            ended = monotonic()
            if type(ended) not in (float, int) or not started <= ended < float('inf'):
                raise SupervisionRefused('invalid or backward synthetic clock')
            if index + 1 == policy.maximum_cycles:
                break
            gap = policy.interval_seconds - (ended - started)
            if gap <= 0:
                ignored_catchup += 1
            else:
                sleep(gap)
    return Result(cycles=policy.maximum_cycles, ignored_catchup=ignored_catchup)


def inert_status() -> dict:
    return {
        'phase': '18C', 'simulation_only': True,
        'runtime_enabled': False, 'operator_authorized': False,
        'live_probe_authorized': False, 'task_creation_authorized': False,
        'notifications_enabled': False, 'production_release': 'HOLD',
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-inert', action='store_true', required=True)
    args = parser.parse_args(argv)
    if args.check_inert:
        print(json.dumps(inert_status(), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
