#!/usr/bin/env python3
"""ONYX CORE v0.8.0 M1 — ONE explicitly requested real Windows/Pi health check.

Uses the existing v0.6/v0.7 read-only Windows diagnostic and the previously
installed, forced-command Pi SSH identity. This module is not a scheduler, a
repair agent, a notification sender, or an incident-store writer.

--check-config is inert/offline. --live-read-only performs real bounded probes.
No probe, network call or state write occurs on import or absent explicit opt-in.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable

# Import the existing v0.7 config validator without changing its semantics.
MONITORING_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MONITORING_DIR))
import OnyxMonitorConfig as cfg  # noqa: E402

ROOT = Path(__file__).absolute().parents[3]
CONFIG = ROOT / 'windows/monitoring/monitoring.development.example.json'
WINDOWS_READER = ROOT / 'windows/monitoring/v080/Invoke-OnyxV080WindowsReadiness.ps1'
WINDOWS_DIAGNOSTIC = ROOT / 'windows/networking/Test-OnyxUsbIcsReadiness.ps1'
PS5 = Path(r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe')
DEV_BRANCH = 'feature/v0.8.0-continuous-monitoring'
PHASE_C = 'b4ebf8883023ac8130e5c7aceca2e0aef0d26ea2'
MAX_JSON_BYTES = 65536
WINDOWS_TIMEOUT_SECONDS = 25

WIN_TYPES = frozenset({
    'WindowsPathReady', 'AdapterMissing', 'AdapterDown',
    'GatewayAddressMissing', 'RouteNotViaUsb', 'IcsServiceStopped',
    'ReceiverUnreachable',
})
PI_TYPES = frozenset({
    'PiInternetVerified', 'UsbInterfaceNotReady', 'RouteNotViaUsb',
    'GatewayUnreachable', 'ExternalTcpUnverified', 'DnsUnverified',
    'HttpsUnverified',
})


class ConnectivityError(RuntimeError):
    """Invalid local context/config, not evidence of network failure."""


def _no_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('duplicate JSON field')
        out[key] = value
    return out


def _decode(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_JSON_BYTES:
        raise ValueError('empty or oversized diagnostic output')
    data = json.loads(
        raw.decode('utf-8-sig', 'strict'),
        object_pairs_hook=_no_duplicate_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')),
    )
    if type(data) is not dict:
        raise ValueError('diagnostic output must be an object')
    return data


def _redirected(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, 'is_junction', lambda: False)())


def _checked_source(path: Path) -> None:
    if not path.is_file() or _redirected(path):
        raise ConnectivityError('missing or redirected diagnostic component')


def _git(*args: str, runner: Callable = subprocess.run) -> str:
    try:
        p = runner(['git', '-C', str(ROOT), *args], capture_output=True,
                   timeout=8, check=False, env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConnectivityError('development Git context unavailable') from exc
    if p.returncode:
        raise ConnectivityError('development Git context invalid')
    try:
        return p.stdout.decode('utf-8', 'strict').strip()
    except UnicodeError as exc:
        raise ConnectivityError('invalid Git output') from exc


def verify_local_context(config: dict, *, git_runner: Callable = subprocess.run) -> None:
    """Restricted M1 development runner; no source, Git or runtime writes."""
    if os.name != 'nt':
        raise ConnectivityError('real diagnostics require Windows')
    if ROOT.as_posix().casefold() != 'd:/github_repos/onyx-core-v080':
        raise ConnectivityError('M1 is restricted to the reviewed v0.8.0 development worktree')
    for path in (ROOT, ROOT.parent, WINDOWS_READER, WINDOWS_DIAGNOSTIC, CONFIG):
        if _redirected(path):
            raise ConnectivityError('redirected code or config path refused')
    for path in (PS5, WINDOWS_READER, WINDOWS_DIAGNOSTIC, CONFIG):
        _checked_source(path)
    _checked_source(Path(config['runtime']['ssh_executable']))
    if _git('branch', '--show-current', runner=git_runner) != DEV_BRANCH:
        raise ConnectivityError('wrong v0.8.0 development branch')
    # A passing ancestor result permits ordinary feature-development commits.
    _git('merge-base', '--is-ancestor', PHASE_C, 'HEAD', runner=git_runner)
    if str(Path(sys.executable)).casefold() != config['runtime']['python_executable'].casefold():
        raise ConnectivityError('unexpected Python executable')
    key = Path(os.path.expandvars(config['pi']['monitor_key_path']))
    _checked_source(key)


def _run_process(command: list[str], timeout: int, runner: Callable) -> dict:
    try:
        p = runner(command, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('diagnostic process unavailable') from exc
    if p.returncode != 0:
        # No stderr is propagated: SSH can include details we do not want in reports.
        raise ValueError('diagnostic process returned an error')
    return _decode(p.stdout)


def _windows(config: dict, runner: Callable) -> dict:
    w = config['windows']
    cmd = [
        str(PS5), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', str(WINDOWS_READER), '-LiveReadOnly', '-Json',
        '-AdapterName', w['adapter_name'], '-GatewayIP', w['gateway_ip'],
        '-ReceiverIP', w['receiver_ip'], '-ReceiverPort', str(w['receiver_port']),
        '-TimeoutMs', str(config['timeouts']['receiver_tcp_ms']),
    ]
    data = _run_process(cmd, WINDOWS_TIMEOUT_SECONDS, runner)
    if (data.get('schema_version') != 1 or data.get('source') != 'OnyxV080WindowsUsbReadiness'
            or data.get('repair_action') != 'None' or data.get('classification') not in WIN_TYPES):
        raise ValueError('Windows evidence schema or classification invalid')
    for field in ('adapter_present', 'adapter_up', 'gateway_preferred',
                  'route_via_usb', 'receiver_tcp_reachable'):
        if type(data.get(field)) is not bool:
            raise ValueError('Windows evidence boolean invalid')
    if data.get('ics_service_status') not in ('Running', 'Stopped', 'StartPending',
                                              'StopPending', 'ContinuePending', 'PausePending', 'Paused', 'NotFound'):
        raise ValueError('Windows ICS service state invalid')
    if data['classification'] == 'WindowsPathReady' and not (
        data['adapter_present'] and data['adapter_up'] and data['gateway_preferred']
        and data['route_via_usb'] and data['receiver_tcp_reachable']
        and data['ics_service_status'] == 'Running'
    ):
        raise ValueError('Windows healthy status contradicts observed evidence')
    return {
        'classification': data['classification'],
        'adapter_up': data['adapter_up'],
        'gateway_preferred': data['gateway_preferred'],
        'route_via_usb': data['route_via_usb'],
        'ics_service_status': data['ics_service_status'],
        'receiver_tcp_reachable': data['receiver_tcp_reachable'],
    }


def _pi(config: dict, runner: Callable) -> dict:
    pi = config['pi']
    ssh = config['runtime']['ssh_executable']
    key = os.path.expandvars(pi['monitor_key_path'])
    command = [
        ssh, '-T', '-n', '-i', key,
        '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
        '-o', 'PreferredAuthentications=publickey', '-o', 'PasswordAuthentication=no',
        '-o', 'KbdInteractiveAuthentication=no', '-o', 'NumberOfPasswordPrompts=0',
        '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=8',
        '-o', 'ConnectionAttempts=1', '-o', 'ServerAliveInterval=5',
        '-o', 'ServerAliveCountMax=1',
        '{}@{}'.format(pi['user'], pi['hostname']), 'onyxcore-monitor',
    ]
    data = _run_process(command, config['timeouts']['ssh_seconds'], runner)
    if (data.get('repair_action') != 'None' or data.get('classification') not in PI_TYPES):
        raise ValueError('Pi evidence schema or classification invalid')
    for field in ('interface_ready', 'route_via_usb', 'gateway_reachable',
                  'external_tcp_443', 'dns_resolves', 'https_works'):
        if type(data.get(field)) is not bool:
            raise ValueError('Pi evidence boolean invalid')
    if data['classification'] == 'PiInternetVerified' and not all(
        data[field] for field in ('interface_ready', 'route_via_usb', 'gateway_reachable',
                                  'external_tcp_443', 'dns_resolves', 'https_works')
    ):
        raise ValueError('Pi healthy status contradicts observed evidence')
    return {
        'classification': data['classification'],
        'interface_ready': data['interface_ready'],
        'route_via_usb': data['route_via_usb'],
        'gateway_reachable': data['gateway_reachable'],
        'external_tcp_443': data['external_tcp_443'],
        'dns_resolves': data['dns_resolves'],
        'https_works': data['https_works'],
    }


def classify(windows: dict, pi: dict) -> tuple[str, str]:
    """Never interpret inaccessible evidence as Healthy or certain ICS failure."""
    wc, pc = windows['classification'], pi['classification']
    if wc == 'WindowsPathReady' and pc == 'PiInternetVerified':
        return 'Healthy', 'WindowsUsbAndPiInternetVerified'
    # A verified local failure is still useful even when the Pi cannot answer.
    # Do not claim the cause is ICS; report only the confirmed classification.
    if wc not in ('WindowsPathReady', 'WindowsProbeUnavailable'):
        return 'Degraded', 'Windows' + wc
    if wc == 'WindowsPathReady' and pc not in ('PiInternetVerified', 'PiProbeUnavailable'):
        return 'Degraded', 'Pi' + pc
    return 'Unknown', 'DiagnosticEvidenceUnavailable'


def run_once(config: dict, *, runner: Callable = subprocess.run,
             now: Callable = lambda: datetime.now(timezone.utc)) -> dict:
    """One manual, bounded Windows + SSH diagnostic; no persistence or scheduling."""
    windows = {'classification': 'WindowsProbeUnavailable'}
    pi = {'classification': 'PiProbeUnavailable'}
    issues = []
    try:
        windows = _windows(config, runner)
    except ValueError:
        issues.append('WindowsDiagnosticUnavailable')
    try:
        pi = _pi(config, runner)
    except ValueError:
        issues.append('PiDiagnosticUnavailable')
    status, reason = classify(windows, pi)
    return {
        'schema_version': 1,
        'source': 'OnyxV080LiveConnectivity',
        'mode': 'ManualReadOnly',
        'checked_at_utc': now().astimezone(timezone.utc).isoformat(),
        'status': status,
        'reason': reason,
        'windows': windows,
        'pi': pi,
        'issues': issues,
        'repair_action': 'None',
        'incident_history_written': False,
        'scheduler_enabled': False,
        'notification_sent': False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--check-config', action='store_true', help='offline config validation, no probes')
    choice.add_argument('--live-read-only', action='store_true', help='explicitly run one REAL Windows + Pi diagnostic')
    parser.add_argument('--json', action='store_true', help='emit structured JSON report')
    args = parser.parse_args(argv)
    try:
        config = cfg.load_config(CONFIG)
        if args.check_config:
            print('PASS: v0.8 M1 development configuration valid; no probes run.')
            return 0
        verify_local_context(config)
        report = run_once(config)
    except (ConnectivityError, cfg.ConfigError, OSError, ValueError, UnicodeError) as exc:
        print('M1 CONNECTIVITY REFUSED: ' + str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, sort_keys=True, separators=(',', ':'), allow_nan=False))
    else:
        print('ONYX CORE v0.8 M1 | {} | {}'.format(report['status'], report['checked_at_utc']))
        print('Windows: {}'.format(report['windows']['classification']))
        print('Pi: {}'.format(report['pi']['classification']))
        print('Reason: {}'.format(report['reason']))
        if report['issues']:
            print('Missing evidence: {}'.format(', '.join(report['issues'])))
        print('Manual read-only check. No incident history, notifications or repair.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
