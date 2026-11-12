#!/usr/bin/env python3
"""ONYX CORE v0.8.0 M2 — opt-in, foreground Windows/Pi connectivity monitor.

Runs M1's *actual* bounded read-only diagnostic sequentially at a selected
interval. Not a Windows service, scheduled task, incident writer, or alert sender.
No probe on import or --check-config. --live-read-only is mandatory to start.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import sys
import time
from typing import Callable, Iterator

import OnyxLiveConnectivity as m1

MIN_INTERVAL = 90  # At least 90 s between scheduled cycle starts.
MAX_INTERVAL = 3600
MAX_BOUNDED_CYCLES = 20
MUTEX_NAME = r'Local\OnyxCoreV080ForegroundConnectivityMonitor'


class MonitorError(RuntimeError):
    """Monitor refused an unsafe or invalid request."""


@contextmanager
def exclusive_monitor() -> Iterator[None]:
    """Nonpersistent, same-Windows-session mutex; no files or services created.

    Different Windows logon sessions are *not* covered by this Local mutex.
    The monitor also never overlaps checks within a single process.
    """
    if os.name != 'nt':
        raise MonitorError('foreground live monitor requires Windows')
    import ctypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    handle = kernel.CreateMutexW(None, 0, MUTEX_NAME)
    if not handle:
        raise MonitorError('cannot establish exclusive foreground monitor')
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel.CloseHandle(handle)
        raise MonitorError('another foreground M2 monitor exists in this logon session')
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def _safe_result(report: dict, index: int, seconds: int, elapsed: float) -> dict:
    """Expose only M1's sanitized classifications; do not forward raw SSH data."""
    if not isinstance(report, dict) or report.get('source') != 'OnyxV080LiveConnectivity':
        raise MonitorError('M1 returned an unexpected result')
    if (report.get('status') not in ('Healthy', 'Degraded', 'Unknown') or
            report.get('repair_action') != 'None' or
            report.get('incident_history_written') is not False or
            report.get('notification_sent') is not False or
            report.get('scheduler_enabled') is not False):
        raise MonitorError('M1 result violates read-only monitoring policy')
    w, p = report.get('windows'), report.get('pi')
    if not isinstance(w, dict) or not isinstance(p, dict):
        raise MonitorError('M1 source classifications unavailable')
    wc, pc = w.get('classification'), p.get('classification')
    if (wc not in m1.WIN_TYPES | {'WindowsProbeUnavailable'} or
            pc not in m1.PI_TYPES | {'PiProbeUnavailable'}):
        raise MonitorError('M1 source classifications unexpected')
    issues = report.get('issues')
    if (not isinstance(issues, list) or any(
        x not in ('WindowsDiagnosticUnavailable', 'PiDiagnosticUnavailable') for x in issues
    )):
        raise MonitorError('M1 error summary unexpected')
    if not isinstance(report.get('checked_at_utc'), str):
        raise MonitorError('M1 check timestamp missing')
    if not isinstance(report.get('reason'), str):
        raise MonitorError('M1 reason missing')
    if report['status'] == 'Healthy' and (wc != 'WindowsPathReady' or pc != 'PiInternetVerified' or issues):
        raise MonitorError('M1 Healthy result contradicts source classifications')
    return {
        'schema_version': 1,
        'source': 'OnyxV080ForegroundMonitor',
        'mode': 'OptInForegroundReadOnly',
        'cycle': index,
        'checked_at_utc': report['checked_at_utc'],
        'status': report['status'],
        'reason': report['reason'],
        'windows_classification': wc,
        'pi_classification': pc,
        'issues': list(issues),
        'duration_ms': max(0, round(elapsed * 1000)),
        'interval_seconds': seconds,
        'cycle_overran_interval': elapsed > seconds,
        'repair_action': 'None',
        'incident_history_written': False,
        'scheduler_enabled': False,
        'notification_sent': False,
    }


def run_monitor(config: dict, *, count: int | None, interval_seconds: int,
                probe: Callable | None = None,
                clock: Callable[[], float] = time.monotonic,
                sleeper: Callable[[float], None] = time.sleep,
                emit: Callable[[dict], None] | None = None) -> int:
    """Run N cycles, or until Ctrl+C if count=None. Never run checks concurrently."""
    if type(interval_seconds) is not int or not MIN_INTERVAL <= interval_seconds <= MAX_INTERVAL:
        raise MonitorError('interval must be 90–3600 seconds')
    if count is not None and (type(count) is not int or not 1 <= count <= MAX_BOUNDED_CYCLES):
        raise MonitorError('count must be 1–20, or explicitly request --continuous')
    if emit is None:
        emit = lambda _: None
    if probe is None:
        probe = m1.run_once
    index = 0
    while count is None or index < count:
        index += 1
        start = clock()
        report = probe(config)
        elapsed = max(0, clock() - start)
        emit(_safe_result(report, index, interval_seconds, elapsed))
        if count is not None and index == count:
            break
        # Start-to-start pacing. A slow cycle never overlaps another cycle.
        # When a cycle exceeds the interval the next starts without a backlog.
        remaining = max(0.0, interval_seconds - (clock() - start))
        if remaining:
            sleeper(remaining)
    return index


def _print_result(result: dict, *, jsonl: bool) -> None:
    if jsonl:
        print(json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False), flush=True)
    else:
        print('M2 cycle {cycle} | {status} | {checked_at_utc}'.format(**result), flush=True)
        print('  Windows: {windows_classification} | Pi: {pi_classification}'.format(**result), flush=True)
        print('  Reason: {reason} | Duration: {duration_ms}ms'.format(**result), flush=True)
        if result['issues']:
            print('  Incomplete: ' + ', '.join(result['issues']), flush=True)
        if result['cycle_overran_interval']:
            print('  Warning: cycle exceeded configured interval; no checks overlapped.', flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-config', action='store_true', help='inert config validation, no probes')
    mode.add_argument('--live-read-only', action='store_true', help='opt in to repeated REAL read-only checks')
    duration = parser.add_mutually_exclusive_group()
    duration.add_argument('--count', type=int, help='number of live cycles (1–20)')
    duration.add_argument('--continuous', action='store_true', help='run in foreground until Ctrl+C')
    parser.add_argument('--interval-seconds', type=int, default=120, help='90–3600, default 120')
    parser.add_argument('--jsonl', action='store_true', help='one sanitized JSON object per cycle')
    args = parser.parse_args(argv)

    if args.check_config and (args.count is not None or args.continuous or args.jsonl):
        parser.error('offline --check-config cannot request cycles or output')
    if args.live_read_only and args.count is None and not args.continuous:
        parser.error('live mode requires explicit --count N or --continuous')
    try:
        if not MIN_INTERVAL <= args.interval_seconds <= MAX_INTERVAL:
            raise MonitorError('interval must be 90–3600 seconds')
        config = m1.cfg.load_config(m1.CONFIG)
        if args.check_config:
            print('PASS: M2 foreground monitor configuration valid; no probes, task or lock.')
            return 0
        m1.verify_local_context(config)
        with exclusive_monitor():
            run_monitor(config, count=None if args.continuous else args.count,
                        interval_seconds=args.interval_seconds,
                        emit=lambda result: _print_result(result, jsonl=args.jsonl))
    except KeyboardInterrupt:
        print('M2 foreground monitor stopped by operator; no tasks or repairs.', file=sys.stderr)
        return 0
    except (m1.ConnectivityError, m1.cfg.ConfigError, MonitorError, OSError, ValueError) as exc:
        print('M2 MONITOR REFUSED: ' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
