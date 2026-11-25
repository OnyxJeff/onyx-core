"""Explicit, time-bounded, same-user foreground journal acceptance.

No unattended grant, scheduler, notification or repair. Native Windows only.
The supervising user controls this worktree and its own journal; this is not
an independent administrator-issued authorization boundary.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'windows/monitoring/v100'),
                str(ROOT / 'windows/gateway'), str(ROOT / 'windows/monitoring/v080')]
import OnyxV100RecoveryAssessment as assessment
import OnyxV100MonitoringJournal as binding
import OnyxV100MonitoringView as view
import OnyxWindowsNativeAdmission as admission

ACL_HELPER = Path(__file__).with_name('Test-OnyxV100JournalStorage.ps1')


def supervised_cycle(*, authorize, exclusive, prepare, attest, observe):
    """Keep the native lock across preparation, probe, commit and projection."""
    if authorize() is not True:
        raise binding.JournalRefused('foreground authorization denied')
    with exclusive():
        if authorize() is not True:
            raise binding.JournalRefused('foreground authorization denied')
        path = view.history_path()
        if prepare(path) is not True or attest(path) is not True:
            raise binding.JournalRefused('storage admission failed')
        if authorize() is not True:
            raise binding.JournalRefused('foreground authorization denied')
        result = observe()
        if result.get('repair_performed') is not False or result.get('journal_written') is not False:
            raise binding.JournalRefused('invalid assessment side effects')
        @contextmanager
        def held_lock():
            # Called synchronously by binding while the outer native lock is held.
            yield
        outcome = binding.record_observation(result['observation'], authorize=authorize,
            attest_storage=attest, exclusive=held_lock)
        if attest(path) is not True:
            raise binding.JournalRefused('post-commit storage attestation failed; preserve evidence')
        projection = view.snapshot()
        return {'observation': result['observation'], 'recommendation': result['recommendation'],
                'journal_outcome': outcome, 'projection': projection,
                'repair_performed': False, 'notification_sent': False,
                'scheduler_enabled': False}


def native_storage(path, sid, *, initialize=False):
    if view.history_path() != path:
        return False
    assessment.check_regular(ACL_HELPER)
    assessment.check_system_executable(assessment.SYSTEM_PS5)
    cmd = [str(assessment.SYSTEM_PS5), '-NoProfile', '-NonInteractive',
           '-ExecutionPolicy', 'Bypass', '-File', str(ACL_HELPER),
           '-ExpectedSid', sid]
    if initialize:
        cmd.append('-Initialize')
    proc = subprocess.run(cmd, capture_output=True, timeout=25, check=False)
    if proc.returncode != 0:
        # The ACL helper only inspects metadata; its errors do not contain
        # credential contents or raw diagnostic payloads.
        print('Storage helper refused: ' + proc.stderr.decode('utf-8', errors='replace')[-2000:],
              file=sys.stderr)
        return False
    return proc.stdout.strip() == b'ONYX_V100_STORAGE_OK' and view.history_path() == path


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--record-once', action='store_true', required=True)
    p.add_argument('--approve-v100-history', action='store_true', required=True)
    p.add_argument('--initialize', action='store_true')
    p.add_argument('--adapter', required=True)
    p.add_argument('--gateway', required=True)
    p.add_argument('--receiver', required=True)
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--pi-host', required=True)
    p.add_argument('--pi-user', required=True)
    args = p.parse_args(argv)
    if os.name != 'nt':
        p.error('native Windows required')
    stage = 'ADMISSION'
    try:
        sid = admission.current_process_sid()
        deadline = time.monotonic() + 240
        key = Path(os.environ['USERPROFILE']) / '.ssh/onyxcore_monitor_ed25519'
        for path in (key, assessment.connectivity.WINDOWS_READER,
                     assessment.connectivity.WINDOWS_DIAGNOSTIC, ACL_HELPER):
            assessment.check_regular(path)
        for path in (assessment.SYSTEM_SSH, assessment.connectivity.PS5):
            assessment.check_system_executable(path)
        cfg = assessment.make_config(args.adapter, args.gateway, args.receiver,
                                     args.port, args.pi_host, args.pi_user, key,
                                     assessment.SYSTEM_SSH)
        def authorized():
            return (args.record_once and args.approve_v100_history and
                    time.monotonic() < deadline and admission.current_process_sid() == sid)
        def observe():
            start = time.monotonic()
            return assessment.summarize(assessment.connectivity.run_once(cfg),
                                        time.monotonic()-start)
        stage = 'SUPERVISED_CYCLE'
        result = supervised_cycle(authorize=authorized,
            exclusive=lambda: admission.verified_sid_mutex(sid),
            prepare=lambda path: native_storage(path, sid, initialize=args.initialize),
            attest=lambda path: native_storage(path, sid), observe=observe)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.TimeoutExpired) as exc:
        p.exit(2, 'Recorder stopped at ' + stage + ': ' + type(exc).__name__ +
               '; preserve evidence, do not blindly retry.\n')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
