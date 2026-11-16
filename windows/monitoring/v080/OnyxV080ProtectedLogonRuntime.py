#!/usr/bin/env python3
"""ONYX CORE v0.8: protected opt-in logged-on-user foreground startup.

No enrollment, task registration, repair, credential renewal, network request,
or on-disk mutation occurs on import / --check-inert. --run-approved-monitor
and --run-approved-alerts ONLY work from the admin-owned approved install with
an exact source/SID/console attestation. No self-healing of expired consent.
"""
from __future__ import annotations

import argparse
import json
import ntpath
import os
from pathlib import Path
import sys
import time
from typing import Callable

ROOT = Path(r'C:\Program Files\OnyxCore\v0.8.0')
PYTHON = Path(r'C:\Python313\python.exe')
SESSION_CYCLES = 20
SESSION_MINUTES = 60
BETWEEN_SESSIONS_SECONDS = 120
CHECK_SLICE_SECONDS = 2


class LogonRuntimeRefused(RuntimeError):
    pass


def require_fixed_source(*, module_file: Path, executable: str,
                         isolated: bool, no_bytecode: bool) -> None:
    """Perform syntactic fixed-location checks before trusted imports."""
    expected = ROOT / 'windows' / 'monitoring' / 'v080' / 'OnyxV080ProtectedLogonRuntime.py'
    if (os.name != 'nt' or ntpath.normcase(ntpath.normpath(str(module_file))) !=
            ntpath.normcase(ntpath.normpath(str(expected))) or
            ntpath.normcase(ntpath.normpath(executable)) !=
            ntpath.normcase(ntpath.normpath(str(PYTHON))) or
            isolated is not True or no_bytecode is not True):
        raise LogonRuntimeRefused('protected Windows -I -B runtime required')


def _verified_runtime():
    """Use the preexisting independent admin/SID/ACL/manifest gate."""
    require_fixed_source(module_file=Path(__file__).absolute(), executable=sys.executable,
                         isolated=bool(sys.flags.isolated),
                         no_bytecode=bool(sys.dont_write_bytecode))
    sys.path.insert(0, str(ROOT / 'windows' / 'monitoring' / 'v080'))
    import OnyxV080ReleaseOperator as operator
    reviewed, context, att, consent, binding, checker = operator._bootstrap()
    return operator, reviewed, context, att, consent, binding, checker


def run_bounded_logon_loop(*, bootstrap: Callable, run_session: Callable,
                           authorize: Callable, sleep: Callable = time.sleep,
                           max_sessions: int | None = None) -> dict:
    """Pure scheduler for already authorized protected sessions.

    No consent minting or renewal: grant evaluation belongs to `authorize`,
    and a fresh bootstrap precedes every bounded session. No automatic retry
    after refusal or a failed/expired session. Test-only `max_sessions` is
    never exposed by the installed CLI.
    """
    if not all(callable(x) for x in (bootstrap, run_session, authorize, sleep)):
        raise LogonRuntimeRefused('missing reviewed runtime dependency')
    if max_sessions is not None and (type(max_sessions) is not int or max_sessions < 1):
        raise LogonRuntimeRefused('invalid synthetic session cap')
    completed = 0
    while True:
        # Each new session reparses admin approval and rechecks native source/ACL.
        checked = bootstrap()
        if authorize(checked) is not True:
            return {'result': 'CONSENT_REQUIRED', 'completed_sessions': completed}
        result = run_session(checked)
        if (type(result) is not dict or result.get('result') != 'PASS' or
                result.get('session_state') != 'Completed' or
                result.get('cycles') != SESSION_CYCLES or
                result.get('persisted_cycles') != SESSION_CYCLES or
                result.get('repairs_invoked') is not False or
                result.get('notifications_sent') is not False or
                result.get('tasks_created') is not False):
            raise LogonRuntimeRefused('protected bounded session failed or expired')
        completed += 1
        if max_sessions is not None and completed >= max_sessions:
            return {'result': 'STOPPED_TEST', 'completed_sessions': completed}
        # The supervised worker returns after its last cycle. Do not launch an
        # extra cycle immediately at the next session boundary; wait a full
        # configured interval with fresh consent/source/session checks.
        remaining = BETWEEN_SESSIONS_SECONDS
        while remaining > 0:
            if authorize(checked) is not True:
                return {'result': 'CONSENT_REQUIRED', 'completed_sessions': completed}
            pause = min(CHECK_SLICE_SECONDS, remaining)
            sleep(pause)
            if authorize(checked) is not True:
                return {'result': 'CONSENT_REQUIRED', 'completed_sessions': completed}
            remaining -= pause


def run_monitor() -> int:
    def bootstrap():
        return _verified_runtime()
    def authorized(snapshot):
        _op, reviewed, _ctx, att, _consent, _binding, checker = snapshot
        try:
            return att.build_rechecking_authorizer(
                root=reviewed.wiring.source_root,
                manifest=reviewed.wiring.manifest,
                config=reviewed.wiring.config_path,
                approved_sid=reviewed.wiring.approved_sid,
                source_checker=checker)() is True
        except _consent.ConsentRefused:
            # Expired/missing/revoked user grant: stop without a Scheduler
            # crash/restart storm. Source or OS attestation errors still fail.
            return False
    def one_session(snapshot):
        op, reviewed, context, att, _consent, binding, checker = snapshot
        return op._run_protected_session(
            reviewed=reviewed, context=context, att=att,
            binding=binding, checker=checker,
            cycles=SESSION_CYCLES, duration_minutes=SESSION_MINUTES)
    try:
        outcome = run_bounded_logon_loop(bootstrap=bootstrap,
                                         run_session=one_session,
                                         authorize=authorized)
    except KeyboardInterrupt:
        print('ONYX CORE logon monitor stopped by operator.', file=sys.stderr)
        return 0
    except Exception:
        # Fail closed. Never print source paths, credentials, or exception text.
        print('ONYX CORE protected logon monitor refused.', file=sys.stderr)
        return 2
    if outcome['result'] == 'CONSENT_REQUIRED':
        print('ONYX CORE: monitoring paused; explicit enrollment required.',
              file=sys.stderr)
        return 0  # No Scheduler retry loop on ordinary consent expiry.
    return 0


def run_alerts() -> int:
    """Start notification watcher behind the same trusted source gate.

    A separately opted-in task and user-DPAPI wrapper inject the Discord URL.
    The watcher sends nothing until a new incident/stale transition exists.
    """
    try:
        _verified_runtime()
        if (os.environ.get('ONYXCORE_V080_STORAGE_PROFILE') != 'release' or
                os.environ.get('ONYXCORE_V080_ALERT_WEBHOOK_URL') is None or
                os.environ.get('ONYXCORE_V080_ALERT_TOKEN')):
            raise LogonRuntimeRefused('protected Discord context missing')
        from OnyxIncidentNotifications import main as watcher_main
        return watcher_main(['--watch','--provider','discord',
                             '--poll-seconds','15','--monitor-stale-seconds','420'])
    except KeyboardInterrupt:
        return 0
    except Exception:
        print('ONYX CORE protected Discord watcher refused.', file=sys.stderr)
        return 2


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    actions = p.add_mutually_exclusive_group(required=True)
    actions.add_argument('--check-inert', action='store_true')
    actions.add_argument('--run-approved-monitor', action='store_true')
    actions.add_argument('--run-approved-alerts', action='store_true')
    args = p.parse_args(argv)
    if args.check_inert:
        print(json.dumps({'phase':'protected-logon-runtime',
                          'monitoring_enabled_by_default':False,
                          'notifications_enabled_by_default':False,
                          'task_installation_enabled':False,
                          'credential_renewal_enabled':False,
                          'repairs_enabled':False}, sort_keys=True))
        return 0
    if args.run_approved_monitor:
        return run_monitor()
    return run_alerts()


if __name__ == '__main__':
    raise SystemExit(main())
