#!/usr/bin/env python3
"""Manual, guarded release one-shot cycle. NOT a scheduler or ICS repair tool.

The existing development runner remains development-only. Only this entry point
can use release incident state, and every cycle requires an explicit CLI opt-in.
All network access is confined to a separately reviewed PowerShell reader.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable

import OnyxIncidentAdapter as adapter
import OnyxIncidentState as reducer
import OnyxIncidentStore as storage
import OnyxLiveIncident as live
import OnyxReleasePolicy as policy
import OnyxReleaseReadOnly as release
import OnyxReleaseCyclePreflight as preflight


class ReleaseCycleError(RuntimeError):
    """Release cycle refused without probing, repairing, or resetting the store."""


RUNNER_REL = Path('windows/monitoring/Invoke-OnyxReleaseCycle.ps1')
COLLECTOR_REL = Path('windows/networking/Collect-OnyxReleaseEvidence.ps1')
# This is an accidental-invocation barrier, not an authentication secret.
SUPERVISION_ENV = 'ONYX_CORE_V070_RELEASE_LIVE'


def run_release_evidence(root: Path, *, runner: Callable = subprocess.run) -> dict:
    """One bounded read-only Windows/Pi diagnostic via the release-only runner.

    Must be called only after approved context, store checks, and exclusive lock.
    Arbitrary paths and subprocess arguments are not exposed on the CLI.
    """
    path = root / RUNNER_REL
    if not path.is_file() or path.is_symlink() or not (root / COLLECTOR_REL).is_file():
        raise ReleaseCycleError('reviewed release diagnostic components are unavailable')
    if not live.WINDOWS_PS.is_file():
        raise ReleaseCycleError('reviewed Windows PowerShell runtime unavailable')
    script = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); & '" + (
        str(path).replace("'", "''")
    ) + "' -LiveReadOnly -Json"
    environment = os.environ.copy()
    environment[SUPERVISION_ENV] = 'approved-one-shot'
    try:
        outcome = runner(
            [str(live.WINDOWS_PS), '-NoProfile', '-NonInteractive',
             '-ExecutionPolicy', 'Bypass', '-Command', script],
            capture_output=True, timeout=live.RUNNER_TIMEOUT_SECONDS,
            check=False, env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseCycleError('release read-only diagnostics unavailable or timed out') from exc
    if outcome.returncode:
        # Never echo stderr or detailed network diagnostics in CLI output.
        raise ReleaseCycleError('release read-only diagnostic exited unsuccessfully')
    return live.read_json_strict(outcome.stdout)


def _new_store_post_collection(directory: Path) -> None:
    """No state/marker existed prior to the probe; refuse newly injected files.

    The collector may have written its own bounded observations history. It
    cannot initialize incident-state.json or its sentinel on behalf of us.
    """
    expected = {'incident-cycle.lock', 'recovery-observations.json'}
    present = {entry.name for entry in directory.iterdir()}
    if not {'incident-cycle.lock'}.issubset(present) or not present.issubset(expected):
        raise ReleaseCycleError('first-run release state changed unexpectedly during diagnostic')
    for entry in directory.iterdir():
        if entry.is_symlink() or bool(getattr(entry, 'is_junction', lambda: False)()) or not entry.is_file():
            raise ReleaseCycleError('redirected release incident artifact refused')


def execute_release_cycle(*, explicit_live_read_only: bool,
                          initialize_new: bool = False,
                          collect: Callable[[Path], dict] = run_release_evidence) -> dict:
    """Gate and run exactly one release cycle in a dedicated incident store.

    Preflight is observational. An exclusive cycle lock is then obtained; the
    store is rechecked UNDER that lock before any actual network call. The
    inherited reducer/store logic validates the evidence and atomic commit.
    """
    if type(explicit_live_read_only) is not bool or not explicit_live_read_only:
        raise ReleaseCycleError('explicit --live-read-only authorization required')
    if type(initialize_new) is not bool:
        raise ReleaseCycleError('first-run authorization must be boolean')
    # Before touching the filesystem, verify the release-only code/environment.
    directory = release.approved_release_view(operation='status', require_store=False)
    root = release._verified_root()
    config = policy.load_release_config(root / release.CONFIG_REL)
    policy.validate_release_intent(
        config, root=policy.RELEASE_ROOT, branch=policy.RELEASE_BRANCH,
        operation='one-shot-cycle', explicit_live_read_only=True,
        initialize_new=initialize_new,
    )
    # Fail closed if any old/partial state, marker, or lock already exists on
    # a first run; do not create even a lock before these checks succeed.
    preflight._check_store(directory, initialize_new)
    # Release root may not be an alias of the development store.
    live._ensure_safe_directory(directory)
    with live._single_cycle_lock(directory):
        # owned_cycle_lock only permits the lock *this invocation holds*;
        # a stray lock found at the initial check was already rejected.
        preflight._check_store(directory, initialize_new, owned_cycle_lock=True)
        cycle = collect(root)
        reducer._check_cycle(cycle)
        if initialize_new:
            _new_store_post_collection(directory)
        else:
            preflight._check_store(directory, False, owned_cycle_lock=True)
        result = live.apply_live_cycle(cycle, directory, initialize_new=initialize_new)
    if result.get('repair_action') != 'None':
        raise ReleaseCycleError('incident integration returned prohibited repair action')
    result['source'] = 'ReleaseOneShotIncidentIntegration'
    result['manual_only'] = True
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-read-only', required=True, action='store_true',
                        help='explicit consent for exactly one read-only diagnostic')
    parser.add_argument('--initialize-new', action='store_true',
                        help='additional one-time consent for a genuinely empty release store')
    args = parser.parse_args(argv)
    try:
        outcome = execute_release_cycle(explicit_live_read_only=args.live_read_only,
                                        initialize_new=args.initialize_new)
    except (ReleaseCycleError, release.ReleaseReadError, policy.ReleasePolicyError,
            preflight.ReleaseCyclePreflightError, live.LiveIncidentError,
            reducer.InvalidIncidentInput, adapter.IncidentAdapterError,
            storage.IncidentStoreError, OSError, ValueError, TypeError) as exc:
        # Sanitized error only: never leak SSH stderr or per-host probe details.
        print('RELEASE ONE-SHOT REFUSED: ' + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(outcome, sort_keys=True, separators=(',', ':'), allow_nan=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
