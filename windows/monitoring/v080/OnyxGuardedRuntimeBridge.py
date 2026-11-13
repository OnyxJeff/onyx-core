#!/usr/bin/env python3
"""ONYX CORE v0.8 Phase 18I1: guarded integration of existing live components.

This is NOT an enrollment implementation or a runnable production supervisor.
The CLI is inert. The Python API requires an independent trusted authorizer,
source/identity attestation and an explicitly approved caller before live use.
No signing key, issuer, task registration, repair or notification transport lives
here. The runtime bridge itself never silently authorizes operation.
"""
from __future__ import annotations

import argparse
from contextlib import AbstractContextManager
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable

import OnyxContinuousMonitor as m2
import OnyxLiveIncidentHistory as m3
import OnyxWindowsNativeAdmission as native


class RuntimeBridgeRefused(RuntimeError):
    """Fail-closed controlled integration boundary."""


@dataclass(frozen=True)
class BoundedRuntimePolicy:
    cycles: int = 1
    interval_seconds: int = 120

    def __post_init__(self) -> None:
        if type(self.cycles) is not int or not 1 <= self.cycles <= 20:
            raise RuntimeBridgeRefused('runtime cycles must be 1..20')
        if type(self.interval_seconds) is not int or not 90 <= self.interval_seconds <= 3600:
            raise RuntimeBridgeRefused('runtime interval must be 90..3600 seconds')


@dataclass(frozen=True)
class BoundedRuntimeResult:
    cycles: int
    persisted_cycles: int
    live_mode: bool
    notifications_sent: bool = False
    repairs_invoked: bool = False
    tasks_created: bool = False


def run_authorized_cycles(
        policy: BoundedRuntimePolicy,
        *,
        approved_sid: str,
        authorize_cycle: Callable[[], bool],
        storage_profile: Callable[[], str] = m3.storage_profile,
        history_path: Callable[[], Path] = m3.history_path,
        load_config: Callable[[], dict] = lambda: m2.m1.cfg.load_config(m2.m1.CONFIG),
        verify_context: Callable[[dict], None] = m2.m1.verify_local_context,
        global_lock: Callable[[str], AbstractContextManager] = native.verified_sid_mutex,
        foreground_lock: Callable[[], AbstractContextManager] = m2.exclusive_monitor,
        monitor_loop: Callable = m2.run_monitor,
        probe: Callable = m2.m1.run_once,
        recorder: Callable = m3.record_cycle,
) -> BoundedRuntimeResult:
    """Wire actual M1→M2→M3 with per-cycle authorization and native mutex.

    WARNING: ``authorize_cycle`` is only an integration seam. An arbitrary
    lambda is NOT trustworthy approval. Real deployment requires an independently
    verified issuer, pinned key, Windows source attestation and revocation.
    No ONYX CORE CLI calls this API, and no scheduler/service is installed.

    On every cycle, re-check authorization immediately before the external
    diagnostic and again before incident persistence. Denial or storage failure
    ends the bounded loop. The global mutex covers all cycles; M2's existing
    same-session lock also prevents collisions with foreground recorders.
    """
    if not isinstance(policy, BoundedRuntimePolicy):
        raise RuntimeBridgeRefused('missing bounded runtime policy')
    if not all(callable(value) for value in (
        authorize_cycle, storage_profile, history_path, load_config,
        verify_context, global_lock, foreground_lock, monitor_loop, probe,
        recorder,
    )):
        raise RuntimeBridgeRefused('missing runtime adapter or authorizer')

    # Even a well-formed SID passed by the caller is not trusted enrollment.
    sid = native.validate_sid(approved_sid)

    def require_authorized() -> None:
        # Propagate verifier failures; never convert them to permission.
        approved = authorize_cycle()
        if approved is not True:
            raise RuntimeBridgeRefused('independent per-cycle authorization denied')

    # Reject an unset/default development profile before entering any lock.
    if storage_profile() != 'release':
        raise RuntimeBridgeRefused('explicit release storage profile required')
    require_authorized()

    persisted = 0
    # Do not instantiate history DB before both locks and config/source guard.
    with global_lock(sid):
        with foreground_lock():
            require_authorized()
            config = load_config()
            verify_context(config)
            require_authorized()
            path = history_path()
            if not isinstance(path, Path) or path.name != 'incident-history.sqlite3':
                raise RuntimeBridgeRefused('unexpected incident journal path')

            def guarded_probe(c: dict) -> dict:
                require_authorized()
                return probe(c)

            def guarded_record(result: dict) -> None:
                nonlocal persisted
                require_authorized()  # Re-check after potential network delay.
                recorder(path, result)
                persisted += 1

            completed = monitor_loop(
                config,
                count=policy.cycles,
                interval_seconds=policy.interval_seconds,
                probe=guarded_probe,
                emit=guarded_record,
            )
    if type(completed) is not int or completed != policy.cycles or persisted != policy.cycles:
        raise RuntimeBridgeRefused('runtime did not complete every bounded cycle')
    return BoundedRuntimeResult(cycles=completed, persisted_cycles=persisted, live_mode=True)


def inert_status() -> dict:
    return {
        'phase': '18I1', 'entrypoint_live_enabled': False,
        'authorization_issuer_integrated': False,
        'trusted_source_attestation_integrated': False,
        'manual_live_execution_authorized': False,
        'runtime_wiring_present': True,
        'scheduling_enabled': False, 'notifications_enabled': False,
        'repairs_enabled': False, 'release_status': 'HOLD',
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check-inert', action='store_true', required=True)
    p.parse_args(argv)
    print(json.dumps(inert_status(), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
