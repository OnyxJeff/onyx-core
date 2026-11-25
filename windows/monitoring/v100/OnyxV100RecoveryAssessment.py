"""Manual v100 connectivity assessment; no journal, service or task mutations.

The command reuses the reviewed v080 read-only worker and native Job Object
containment, not the old development CLI or its authorization boundary.
It is not an unattended supervisor or privileged repair implementation.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'windows/monitoring/v080'))
import OnyxLiveConnectivity as connectivity
import OnyxContinuousMonitor as foreground


def recovery_recommendation(report: dict) -> str:
    """Conservative operator guidance, never permission to mutate networking."""
    windows, pi = report['windows'], report['pi']
    wc, pc = windows['classification'], pi['classification']
    status, reason = connectivity.classify(windows, pi)
    if (report.get('status'), report.get('reason')) != (status, reason):
        raise ValueError('contradictory observation')
    if report.get('repair_action') != 'None':
        raise ValueError('not a read-only observation')
    if status == 'Healthy':
        if not (all(windows.get(x) is True for x in
                    ('adapter_up', 'gateway_preferred', 'route_via_usb', 'receiver_tcp_reachable'))
                and windows.get('ics_service_status') == 'Running'
                and all(pi.get(x) is True for x in ('interface_ready', 'route_via_usb',
                    'gateway_reachable', 'external_tcp_443', 'dns_resolves', 'https_works'))):
            raise ValueError('healthy evidence incomplete')
        return 'NoRepairNeeded'
    if wc in ('WindowsProbeUnavailable', 'AdapterMissing', 'AdapterDown',
              'GatewayAddressMissing', 'RouteNotViaUsb'):
        return 'InvestigateUsbOrWindowsEvidence'
    if wc == 'IcsServiceStopped':
        if (all(windows.get(x) is True for x in ('adapter_up', 'gateway_preferred', 'route_via_usb'))
                and windows.get('ics_service_status') == 'Stopped'):
            return 'OperatorMayConsiderStartingICS'
        return 'InvestigateICSServiceState'
    if wc == 'ReceiverUnreachable':
        return 'InvestigateReceiverOrUsb'
    if pc in ('PiProbeUnavailable', 'UsbInterfaceNotReady', 'RouteNotViaUsb', 'GatewayUnreachable'):
        return 'InvestigatePiOrMissingEvidence'
    if pc in ('ExternalTcpUnverified', 'DnsUnverified', 'HttpsUnverified'):
        return 'InvestigateForwardingOrUpstream'
    return 'InvestigateUnknown'


def make_config(adapter, gateway, receiver, port, hostname, user, key, ssh):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}', adapter):
        raise ValueError('invalid adapter')
    addresses = [ipaddress.IPv4Address(x) for x in (gateway, receiver)]
    if any(not a.is_private or a.is_loopback or a.is_link_local or a.is_unspecified or a.is_multicast
           for a in addresses) or addresses[0] == addresses[1]:
        raise ValueError('distinct private USB IPv4 addresses required')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('invalid receiver port')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', hostname):
        raise ValueError('invalid Pi hostname')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,31}', user):
        raise ValueError('invalid Pi user')
    return {'profile': 'release',  # selects existing native Job Object runner, not legacy CLI
            'windows': {'adapter_name': adapter, 'gateway_ip': str(addresses[0]),
                        'receiver_ip': str(addresses[1]), 'receiver_port': port},
            'pi': {'hostname': hostname, 'user': user, 'monitor_key_path': str(key)},
            'runtime': {'ssh_executable': str(ssh)},
            'timeouts': {'receiver_tcp_ms': 2000, 'ssh_seconds': 30}}


SYSTEM_SSH = Path(r'C:\Windows\System32\OpenSSH\ssh.exe')
SYSTEM_PS5 = Path(r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe')


def _check_file(path: Path, *, system_executable: bool):
    for p in (*reversed(path.parents), path):
        info = p.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('redirected diagnostic path refused')
        if p == path and (not stat.S_ISREG(info.st_mode) or
                          info.st_nlink < 1 or
                          (not system_executable and info.st_nlink != 1)):
            raise ValueError('nonregular or linked diagnostic file refused')


def check_regular(path: Path):
    _check_file(path, system_executable=False)


def check_system_executable(path: Path):
    # Windows servicing may hardlink these OS-managed binaries.
    # The manual operator checks their Authenticode signatures before launch.
    # This is not an unattended trust attestation.
    if path not in (SYSTEM_SSH, SYSTEM_PS5):
        raise ValueError('unapproved system executable path')
    _check_file(path, system_executable=True)


def summarize(report: dict, elapsed: float) -> dict:
    # Preserve the existing journal-compatible sanitized result, but do not write it.
    summary = foreground._safe_result(report, 1, 90, elapsed)
    return {'schema_version': 1, 'source': 'OnyxV100RecoveryAssessment',
            'observation': summary, 'recommendation': recovery_recommendation(report),
            'repair_performed': False, 'journal_written': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--observe-once', action='store_true', required=True)
    parser.add_argument('--adapter', required=True)
    parser.add_argument('--gateway', required=True)
    parser.add_argument('--receiver', required=True)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--pi-host', required=True)
    parser.add_argument('--pi-user', required=True)
    args = parser.parse_args(argv)
    if os.name != 'nt':
        parser.error('native Windows required')
    stage = 'FILE_ADMISSION'
    try:
        key = Path(os.environ['USERPROFILE']) / '.ssh/onyxcore_monitor_ed25519'
        ssh = SYSTEM_SSH
        for label, path, checker in (
                ('SSH_KEY', key, check_regular),
                ('SSH_EXE', ssh, check_system_executable),
                ('POWERSHELL_EXE', connectivity.PS5, check_system_executable),
                ('WINDOWS_READER', connectivity.WINDOWS_READER, check_regular),
                ('WINDOWS_DIAGNOSTIC', connectivity.WINDOWS_DIAGNOSTIC, check_regular)):
            stage = 'FILE_ADMISSION:' + label
            checker(path)
        stage = 'CONFIGURATION'
        config = make_config(args.adapter, args.gateway, args.receiver, args.port,
                             args.pi_host, args.pi_user, key, ssh)
        stage = 'NATIVE_WORKERS'
        start = time.monotonic()
        report = connectivity.run_once(config)
        stage = 'RESULT_VALIDATION'
        print(json.dumps(summarize(report, time.monotonic() - start),
                         sort_keys=True, allow_nan=False))
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        parser.exit(2, 'Assessment refused at ' + stage + ': ' + type(exc).__name__ + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
