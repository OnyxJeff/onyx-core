#!/usr/bin/env python3
"""ONYX CORE v0.7.0: offline-only preflight for a future release one-shot cycle.

This is a PLAN checker, not a diagnostic launcher. It never calls PowerShell,
SSH, a network API, a cycle runner, or a function that writes incident state.
The release live runner is not integrated and always remains disabled here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import OnyxIncidentStore as store
import OnyxLiveIncident as live
import OnyxReleasePolicy as policy
import OnyxReleaseReadOnly as release


class ReleaseCyclePreflightError(RuntimeError):
    """The proposed one-shot release cycle must not proceed."""


KNOWN_FILES = frozenset({
    'incident-state.json', live.MARKER_NAME,
    'incident-cycle.lock', 'recovery-observations.json',
    'incident-state.json.lock',
})


def _non_redirected_file(path: Path) -> bool:
    if path.is_symlink() or bool(getattr(path, 'is_junction', lambda: False)()):
        raise ReleaseCyclePreflightError('redirected incident artifact refused')
    if path.exists() and not path.is_file():
        raise ReleaseCyclePreflightError('incident artifact is not a regular file')
    return path.is_file()


def _check_store(directory: Path, initialize_new: bool) -> tuple[str, int, int]:
    """Inspect existing release artifacts without locking, creating or rewriting.

    IMPORTANT: This is not a concurrency guarantee. The eventual runner must
    independently revalidate the state *under its exclusive cycle lock*.
    """
    if not directory.is_absolute():
        raise ReleaseCyclePreflightError('release state directory must be absolute')
    if directory.is_symlink() or bool(getattr(directory, 'is_junction', lambda: False)()):
        raise ReleaseCyclePreflightError('redirected release directory refused')
    if directory.exists() and not directory.is_dir():
        raise ReleaseCyclePreflightError('release state directory is not a directory')

    state_path = directory / 'incident-state.json'
    marker_path = directory / live.MARKER_NAME
    lock_path = directory / 'incident-cycle.lock'
    history_path = directory / 'recovery-observations.json'
    writer_lock = directory / 'incident-state.json.lock'

    for path in (state_path, marker_path, lock_path, history_path, writer_lock):
        _non_redirected_file(path)

    if directory.is_dir():
        # Unexpected files can indicate interrupted writes or unreviewed content.
        # Fail closed, do not clean them up and never silently reset history.
        try:
            entries = tuple(directory.iterdir())
        except OSError as exc:
            raise ReleaseCyclePreflightError('release directory cannot be listed') from exc
        if any(entry.name not in KNOWN_FILES for entry in entries):
            raise ReleaseCyclePreflightError('unexpected release incident artifacts')

    state_present = state_path.is_file()
    marker_present = marker_path.is_file()
    if state_present != marker_present:
        raise ReleaseCyclePreflightError('partial release initialization; manual recovery required')

    if not state_present:
        # No file, lock or observation may pre-exist for an initial run.
        if directory.is_dir() and tuple(directory.iterdir()):
            raise ReleaseCyclePreflightError('nonempty release directory without initialized store')
        if not initialize_new:
            raise ReleaseCyclePreflightError('no release incident store; separate first-run authorization required')
        return 'NewStoreCandidate', 0, 0

    if initialize_new:
        raise ReleaseCyclePreflightError('existing release incident history must never be reinitialized')

    try:
        if marker_path.read_bytes() != live.MARKER_BYTES:
            raise ReleaseCyclePreflightError('invalid release initialization marker')
        validated = store.load_store(state_path)
        current = validated['state']
        generation = validated['generation']
        cycles = current['processed_cycles']
        if type(generation) is not int or type(cycles) is not int or generation < 1 or cycles < 1:
            raise ReleaseCyclePreflightError('release history lacks valid completed observations')
    except (OSError, KeyError, ValueError, TypeError, store.IncidentStoreError) as exc:
        raise ReleaseCyclePreflightError('release incident store failed integrity validation') from exc
    return 'ExistingValidated', generation, cycles


def plan_release_cycle(*, intended_live_read_only: bool, initialize_new: bool = False) -> dict:
    """Review a future intent. No authorization or capability to execute a probe.

    The only supported caller is the fixed release repository on main.
    Existing development launchers are not modified or bypassed.
    """
    if type(intended_live_read_only) is not bool or not intended_live_read_only:
        raise ReleaseCyclePreflightError('explicit intended read-only cycle flag required')
    if type(initialize_new) is not bool:
        raise ReleaseCyclePreflightError('initialization selection must be boolean')

    # Reuse the reviewed release context verification. require_store=False is
    # necessary only to inspect *whether* a first-run initialization is possible.
    directory = release.approved_release_view(operation='status', require_store=False)
    root = release._verified_root()
    config = policy.load_release_config(root / release.CONFIG_REL)
    policy.validate_release_intent(
        config, root=policy.RELEASE_ROOT, branch=policy.RELEASE_BRANCH,
        operation='one-shot-cycle', explicit_live_read_only=intended_live_read_only,
        initialize_new=initialize_new,
    )

    condition, generation, cycles = _check_store(directory, initialize_new)
    return {
        'source': 'ReleaseOneShotOfflinePreflight',
        'operation': 'one-shot-cycle',
        'store_condition': condition,
        'existing_generation': generation,
        'existing_processed_cycles': cycles,
        'first_run_requested': initialize_new,
        'future_live_consent_required': True,
        'future_first_run_approval_required': initialize_new,
        'exclusive_lock_recheck_required': True,
        'runtime_enabled': False,
        'probe_performed': False,
        'store_modified': False,
        'schedule_requested': False,
        'repair_action': 'None',
        'assessment': 'PLAN ONLY: release one-shot runner not yet integrated; no probe or state change authorized.',
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan-one-shot', action='store_true', required=True,
                        help='inspect the release context; NEVER execute a diagnostic')
    parser.add_argument('--intended-live-read-only', action='store_true', required=True,
                        help='acknowledge the planned future manual read-only cycle (not runtime consent)')
    parser.add_argument('--initialize-new', action='store_true',
                        help='inspect whether a genuinely new release store could be initialized later')
    parser.add_argument('--json', action='store_true', help='structured, non-sensitive offline report')
    args = parser.parse_args(argv)
    try:
        result = plan_release_cycle(
            intended_live_read_only=args.intended_live_read_only,
            initialize_new=args.initialize_new,
        )
    except (ReleaseCyclePreflightError, release.ReleaseReadError,
            policy.ReleasePolicyError, OSError, ValueError, TypeError) as exc:
        print('RELEASE CYCLE PREFLIGHT REFUSED: ' + str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False))
    else:
        print('ONYX CORE v0.7.0 | Release one-shot preflight (OFFLINE ONLY)')
        print('Store condition: ' + result['store_condition'])
        print('Existing generation: ' + str(result['existing_generation']))
        print('Existing cycles: ' + str(result['existing_processed_cycles']))
        print('Future first-run approval required: ' + str(result['future_first_run_approval_required']))
        print('RUNTIME BLOCKED: no live probe, repair, scheduling, or state change')
    return 0


if __name__ == '__main__':
    sys.exit(main())
