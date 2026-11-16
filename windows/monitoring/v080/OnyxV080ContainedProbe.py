#!/usr/bin/env python3
"""Protected ONYX CORE v0.8 foreground diagnostic process boundary.

The parent owns SID/consent/source checks, mutexes and the SQLite journal.
The contained child runs only one M1 read-only diagnostic and emits a single
schema-validated report. No live entrypoint exists from a development checkout.

RELEASE HOLD until independent native Windows low-integrity/ACL acceptance.
"""
from __future__ import annotations

from datetime import datetime, timezone
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
from typing import Callable

INSTALL_ROOT = Path(r'C:\Program Files\OnyxCore\v0.8.0')
PYTHON = Path(r'C:\Python313\python.exe')
MAX_CHILD_OUTPUT = 16384
WORKER_NAME = 'OnyxV080ContainedProbe.py'

class ContainmentRefused(RuntimeError):
    pass


def _assert_low_integrity() -> None:
    """Check the actual native process token integrity RID, not environment."""
    if os.name != 'nt':
        raise ContainmentRefused('native Windows token required')
    from ctypes import wintypes
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    HANDLE, DWORD = wintypes.HANDLE, wintypes.DWORD
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = HANDLE
    advapi.OpenProcessToken.argtypes = [HANDLE, DWORD, ctypes.POINTER(HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [HANDLE, ctypes.c_int, ctypes.c_void_p,
                                          DWORD, ctypes.POINTER(DWORD)]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    advapi.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    advapi.GetSidSubAuthority.argtypes = [ctypes.c_void_p, DWORD]
    advapi.GetSidSubAuthority.restype = ctypes.POINTER(DWORD)
    kernel.CloseHandle.argtypes = [HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008,
                                  ctypes.byref(handle)):
        raise ContainmentRefused('child token unavailable')
    try:
        needed = DWORD()
        advapi.GetTokenInformation(handle, 25, None, 0, ctypes.byref(needed))
        if not 16 <= needed.value <= 2048:
            raise ContainmentRefused('unexpected token label size')
        data = ctypes.create_string_buffer(needed.value)
        if not advapi.GetTokenInformation(handle, 25, data, needed,
                                          ctypes.byref(needed)):
            raise ContainmentRefused('child integrity query unavailable')
        sid = ctypes.c_void_p.from_buffer(data).value
        if not sid:
            raise ContainmentRefused('child mandatory integrity missing')
        count = advapi.GetSidSubAuthorityCount(sid)[0]
        if not 1 <= count <= 15:
            raise ContainmentRefused('invalid child integrity SID')
        rid = advapi.GetSidSubAuthority(sid, count - 1)[0]
        if rid != 0x1000:  # LOW IL. Never accept medium/high impersonation.
            raise ContainmentRefused('child token is not low-integrity')
    finally:
        kernel.CloseHandle(handle)


def _decode_checked(raw: bytes) -> dict:
    """Strict report screening in trusted parent; no raw child evidence leaves."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_CHILD_OUTPUT:
        raise ContainmentRefused('empty/oversized child report')
    import OnyxLiveConnectivity as m1
    try:
        data = m1._decode(raw)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ContainmentRefused('invalid child JSON') from exc
    required = {'schema_version', 'source', 'mode', 'checked_at_utc', 'status',
                'reason', 'windows', 'pi', 'issues', 'repair_action',
                'incident_history_written', 'scheduler_enabled', 'notification_sent'}
    if set(data) != required or type(data['schema_version']) is not int or data['schema_version'] != 1:
        raise ContainmentRefused('unexpected child report fields')
    if data['source'] != 'OnyxV080LiveConnectivity' or data['mode'] != 'ManualReadOnly':
        raise ContainmentRefused('untrusted child report provenance')
    if (data['repair_action'] != 'None' or data['incident_history_written'] is not False or
            data['scheduler_enabled'] is not False or data['notification_sent'] is not False):
        raise ContainmentRefused('child claims side effects')
    if type(data['windows']) is not dict or type(data['pi']) is not dict:
        raise ContainmentRefused('malformed child classification')
    w, pi = data['windows'], data['pi']
    allowed_w = {'classification', 'adapter_up', 'gateway_preferred', 'route_via_usb',
                 'ics_service_status', 'receiver_tcp_reachable'}
    allowed_pi = {'classification', 'interface_ready', 'route_via_usb', 'gateway_reachable',
                  'external_tcp_443', 'dns_resolves', 'https_works'}
    if (not {'classification'} <= set(w) <= allowed_w or
            not {'classification'} <= set(pi) <= allowed_pi or
            w['classification'] not in m1.WIN_TYPES | {'WindowsProbeUnavailable'} or
            pi['classification'] not in m1.PI_TYPES | {'PiProbeUnavailable'}):
        raise ContainmentRefused('invalid child classification')
    if w['classification'] == 'WindowsProbeUnavailable':
        if set(w) != {'classification'}:
            raise ContainmentRefused('unknown Windows evidence contains extras')
    elif (set(w) != allowed_w or any(type(w[key]) is not bool for key in
             ('adapter_up', 'gateway_preferred', 'route_via_usb', 'receiver_tcp_reachable')) or
          w['ics_service_status'] not in ('Running', 'Stopped', 'StartPending',
              'StopPending', 'ContinuePending', 'PausePending', 'Paused', 'NotFound')):
        raise ContainmentRefused('invalid Windows evidence shape')
    if pi['classification'] == 'PiProbeUnavailable':
        if set(pi) != {'classification'}:
            raise ContainmentRefused('unknown Pi evidence contains extras')
    elif set(pi) != allowed_pi or any(type(pi[key]) is not bool for key in
            ('interface_ready', 'route_via_usb', 'gateway_reachable',
             'external_tcp_443', 'dns_resolves', 'https_works')):
        raise ContainmentRefused('invalid Pi evidence shape')
    expected_status, expected_reason = m1.classify(w, pi)
    if data['status'] != expected_status or data['reason'] != expected_reason:
        raise ContainmentRefused('contradictory child health result')
    if (type(data['issues']) is not list or len(data['issues']) > 2 or
            any(type(x) is not str or x not in
                ('WindowsDiagnosticUnavailable', 'PiDiagnosticUnavailable') for x in data['issues']) or
            len(set(data['issues'])) != len(data['issues']) or
            ('WindowsDiagnosticUnavailable' in data['issues']) !=
                (w['classification'] == 'WindowsProbeUnavailable') or
            ('PiDiagnosticUnavailable' in data['issues']) !=
                (pi['classification'] == 'PiProbeUnavailable')):
        raise ContainmentRefused('invalid child evidence completeness')
    try:
        dt = datetime.fromisoformat(data['checked_at_utc'])
        if dt.tzinfo is None or abs((datetime.now(timezone.utc) - dt).total_seconds()) > 120:
            raise ValueError('stale child timestamp')
    except (ValueError, TypeError, OverflowError) as exc:
        raise ContainmentRefused('invalid child timestamp') from exc
    return data


def run_protected_probe(config: dict, *, source_root: Path,
                        authorize: Callable[[], bool]) -> dict:
    """Production parent-only interface: no user-controlled child args or DB path."""
    if not callable(authorize) or authorize() is not True:
        raise ContainmentRefused('missing explicit live approval')
    if os.name != 'nt' or source_root != INSTALL_ROOT or type(config) is not dict:
        raise ContainmentRefused('protected Windows installation required')
    import OnyxV080ReleaseProfile as profile
    profile.validate_release_config(config)
    from OnyxWindowsJobRunner import WindowsJobRunner
    command = [str(PYTHON), '-I', '-B', str(INSTALL_ROOT / 'windows' / 'monitoring' /
                                            'v080' / WORKER_NAME), '--run-contained-probe']
    result = WindowsJobRunner((str(PYTHON),)).run(
        command, capture_output=True, timeout=90, check=False,
        consent_check=authorize, low_integrity=True)
    if result.returncode != 0:
        raise ContainmentRefused('contained diagnostic failed')
    if authorize() is not True:
        raise ContainmentRefused('approval revoked after worker exit')
    report = _decode_checked(result.stdout)
    if authorize() is not True:
        raise ContainmentRefused('approval revoked before accepting report')
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check-inert', action='store_true')
    modes.add_argument('--run-contained-probe', action='store_true')
    args = parser.parse_args(argv)
    if args.check_inert:
        print(json.dumps({'contained_child_ready_for_host_acceptance': False,
                          'release_authorized': False, 'runs_live_by_default': False}))
        return 0
    if (os.name != 'nt' or Path(__file__).absolute() !=
            (INSTALL_ROOT / 'windows' / 'monitoring' / 'v080' / WORKER_NAME) or
            Path(sys.executable) != PYTHON or
            not sys.flags.isolated or not sys.dont_write_bytecode):
        raise ContainmentRefused('untrusted or nonisolated diagnostic child')
    _assert_low_integrity()
    mon = INSTALL_ROOT / 'windows' / 'monitoring' / 'v080'
    sys.path.insert(0, str(mon))
    import OnyxV080ReleaseProfile as profile
    import OnyxLiveConnectivity as m1
    config = profile.load_release_config(
        INSTALL_ROOT / 'windows' / 'monitoring' / profile.RELEASE_CONFIG_NAME)
    import subprocess
    result = m1._run_once_from_bounded_workers(config, runner=subprocess.run)
    # The child owns no incident history capability; pure diagnostic output.
    print(json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ContainmentRefused, ValueError, OSError):
        print('CONTAINED DIAGNOSTIC REFUSED', file=sys.stderr)
        raise SystemExit(2)
