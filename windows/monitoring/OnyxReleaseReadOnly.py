#!/usr/bin/env python3
"""Release-context status/report reader. No cycle execution or state creation.

This is deliberately a separate CLI from development-only operator launchers.
A release view is possible ONLY after a reviewed merge to main and an already
initialized, distinct release incident store. Development CLIs stay unchanged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import OnyxIncidentState as reducer
import OnyxIncidentStore as storage
import OnyxLiveIncident as live
import OnyxOperatorStatus as status_module
import OnyxOperatorReport as report_module
import OnyxReleasePolicy as policy

CONFIG_REL = Path('windows/monitoring/monitoring.release.example.json')
REQUIRED_TRACKED = (
    'windows/monitoring/OnyxReleaseReadOnly.py',
    'windows/monitoring/OnyxReleasePolicy.py',
    'windows/monitoring/OnyxOperatorStatus.py',
    'windows/monitoring/OnyxOperatorReport.py',
    'windows/monitoring/OnyxIncidentStore.py',
    'windows/monitoring/OnyxIncidentState.py',
    'windows/monitoring/OnyxLiveIncident.py',
    'windows/monitoring/monitoring.release.example.json',
)
RELEASE_SUBDIR = 'OnyxCore-v070-Release'


class ReleaseReadError(RuntimeError):
    """Release read-only context rejected; do not attempt fallback or reset."""


def _redirected(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, 'is_junction', lambda: False)())


def _verified_root() -> Path:
    """Verify executable's actual installation path, not an untrusted caller path."""
    if os.name != 'nt':
        raise ReleaseReadError('release CLI requires Windows')
    root = Path(__file__).absolute().parents[2]
    # Checking lexical *and* resolved paths prevents an alias into a fake root.
    if os.path.normcase(str(root)) != os.path.normcase(str(Path(policy.RELEASE_ROOT))):
        raise ReleaseReadError('release CLI is not installed at the approved root')
    if any(_redirected(path) for path in (root, root.parent, root.parent.parent)):
        raise ReleaseReadError('redirected release repository forbidden')
    if os.path.normcase(str(root.resolve())) != os.path.normcase(str(root)):
        raise ReleaseReadError('release repository contains a path redirect')
    return root


def _git(root: Path, *args: str) -> str:
    """Bounded Git verification; never invokes any network action."""
    try:
        result = subprocess.run(
            ['git', '-C', str(root), *args], check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseReadError('local Git verification unavailable') from exc
    if result.returncode:
        raise ReleaseReadError('local Git source verification failed')
    try:
        return result.stdout.decode('utf-8', 'strict').strip()
    except UnicodeError as exc:
        raise ReleaseReadError('invalid local Git output') from exc


def _checked_release_state() -> Path:
    """Derive the only release store location without creating any directory."""
    literal = os.environ.get('LOCALAPPDATA', '')
    if not literal:
        raise ReleaseReadError('LOCALAPPDATA is undefined')
    local_app = Path(literal)
    if not local_app.is_absolute() or _redirected(local_app):
        raise ReleaseReadError('LOCALAPPDATA is invalid or redirected')
    parent = local_app / RELEASE_SUBDIR
    directory = parent / 'Monitoring'
    # Check the entire bounded local path, not just the leaf store directory.
    for path in (local_app, parent, directory):
        if _redirected(path):
            raise ReleaseReadError('release incident location is redirected')
        if path.exists() and not path.is_dir():
            raise ReleaseReadError('release incident location is not a directory')
    if os.path.normcase(str(local_app.resolve())) != os.path.normcase(str(local_app.absolute())):
        raise ReleaseReadError('LOCALAPPDATA resolves through an unexpected path')
    if directory.exists() and os.path.normcase(str(directory.resolve())) != os.path.normcase(str(directory.absolute())):
        raise ReleaseReadError('release incident location resolves through a redirect')
    return directory


def approved_release_view(*, operation: str, require_store: bool = True) -> Path:
    """Runtime context for stored-data operations only; no repair/live consent.

    Git checks are deliberately independent of the old v0.6.0 SHA and
    protected untracked collector backup. No explicit CLI override exists.
    """
    if operation not in ('status', 'report'):
        raise ReleaseReadError('only stored-data status/report are available')
    root = _verified_root()
    branch = _git(root, 'branch', '--show-current')
    config_path = root / CONFIG_REL
    if _redirected(config_path) or not config_path.is_file():
        raise ReleaseReadError('release config is absent or redirected')
    config = policy.load_release_config(config_path)
    policy.validate_release_intent(
        config, root=policy.RELEASE_ROOT, branch=branch, operation=operation,
    )
    # All checked files must belong to the committed candidate. Untracked
    # backups are ignored, but *any* modified tracked content blocks release.
    _git(root, 'ls-files', '--error-unmatch', '--', *REQUIRED_TRACKED)
    if _git(root, 'status', '--porcelain=v1', '--untracked-files=no'):
        raise ReleaseReadError('tracked release worktree is not clean')
    # Allow the legacy *untracked* collector backup elsewhere, but never an
    # unexpected source/config file alongside imported monitoring modules.
    if _git(root, 'status', '--porcelain=v1', '--untracked-files=all', '--',
            'windows/monitoring/'):
        raise ReleaseReadError('unexpected file in release monitoring source directory')
    if os.path.normcase(config['runtime']['python_executable']) != os.path.normcase(sys.executable):
        raise ReleaseReadError('release CLI is using an unapproved Python executable')
    directory = _checked_release_state()
    # Strict literal validated by ReleasePolicy; never derive a path from JSON.
    if config['state_dir'] != policy.RELEASE_STATE:
        raise ReleaseReadError('release incident state profile mismatch')
    if require_store and not directory.is_dir():
        raise ReleaseReadError('release incident store is not initialized; refusing to create it')
    return directory


def read_release_view(*, operation: str, events: int = 10,
                      stale_minutes: int = 30, now_utc: datetime | None = None) -> dict:
    """Return existing stored evidence only. No live probe or state write."""
    directory = approved_release_view(operation=operation)
    snapshot = status_module.read_status(directory, max_events=events)
    if operation == 'status':
        return snapshot
    return report_module.summarize(
        snapshot, now_utc=datetime.now(timezone.utc) if now_utc is None else now_utc,
        stale_minutes=stale_minutes,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--status', action='store_true', help='read an existing release incident snapshot')
    selection.add_argument('--report', action='store_true', help='read an age-aware release incident report')
    parser.add_argument('--json', action='store_true', help='print sanitized JSON')
    parser.add_argument('--events', type=int, default=10, metavar='N', help='last N incident events (0..20)')
    parser.add_argument('--stale-minutes', type=int, default=None, metavar='N',
                        help='report-only freshness threshold (1..1440; default 30)')
    args = parser.parse_args(argv)
    try:
        operation = 'status' if args.status else 'report'
        if operation == 'status' and args.stale_minutes is not None:
            raise ReleaseReadError('--stale-minutes is only valid for --report')
        result = read_release_view(operation=operation, events=args.events,
                                   stale_minutes=(30 if args.stale_minutes is None else args.stale_minutes))
        if args.json:
            print(json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False))
        else:
            # Reuse existing renderers, which label the output as development.
            # Correct the header ONLY, retaining all historical/no-probe warnings.
            display = (status_module.render_text(result) if args.status
                       else report_module.render_text(result))
            print(display.replace('(development)', '(release)', 1))
        return 0
    except (ReleaseReadError, policy.ReleasePolicyError,
            status_module.OperatorStatusError, report_module.OperatorReportError,
            storage.IncidentStoreError, live.LiveIncidentError,
            reducer.InvalidIncidentInput, OSError, ValueError, KeyError, TypeError) as exc:
        print('RELEASE OPERATOR REFUSED: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
