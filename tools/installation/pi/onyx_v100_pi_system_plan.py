#!/usr/bin/env python3
"""ONYX CORE M2-S3B: read-only ARMv6 system preflight and inert unit renderer.

No installation, account creation, credential contents, service commands, network
probes, or persistent writes. The generated unit is NOT installed or enabled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import sys

COMMON = Path(__file__).resolve().parents[1] / 'common'
if str(COMMON) not in sys.path:
    sys.path.insert(0, str(COMMON))
from onyx_v100_config import load_config  # noqa: E402

RELEASE_ROOT = '/opt/onyxcore/v1.0.0'
CONFIG_PATH = '/etc/onyxcore/v1.0.0/pi-armv6.config.json'
CREDENTIAL_PATH = '/etc/onyxcore/v1.0.0/receiver.env'
ACTIVATION_MARKER = '/etc/onyxcore/v1.0.0/activation-approved'
UNIT_PATH = '/etc/systemd/system/onyxcore-v100-receiver.service'
LEGACY_STATE = '/var/lib/onyxcore'
LEGACY_UNIT = '/etc/systemd/system/onyxcore-receiver.service'
NEEDED_TOOLS = ('ip', 'systemctl', 'nmcli')
PATH_PATTERN = re.compile(r'/[A-Za-z0-9_./-]{1,190}\Z')


class PlanningRefused(ValueError):
    pass


def _safe_posix(value: str) -> str:
    if (type(value) is not str or not PATH_PATTERN.fullmatch(value) or
            '//' in value or any(p in ('', '.', '..') for p in value[1:].split('/')) or
            str(PurePosixPath(value)) != value):
        raise PlanningRefused('unsafe POSIX unit path')
    return value


def _validate_system_config(config: dict) -> dict:
    if config.get('platform') != 'pi-armv6':
        raise PlanningRefused('Pi configuration required')
    state = _safe_posix(config['storage']['state_dir'])
    if state == LEGACY_STATE or state.startswith(LEGACY_STATE + '/'):
        raise PlanningRefused('v1 state must be isolated from legacy /var/lib/onyxcore')
    if not state.startswith('/var/lib/') or len(PurePosixPath(state).parts) != 4:
        raise PlanningRefused('v1 state must be a dedicated /var/lib/<name> directory')
    # Do not permit the state directory to overlap a broader reserved ONYX root.
    if PurePosixPath(state).name in ('.', '..', 'onyxcore', 'onyxcore-v090'):
        raise PlanningRefused('state directory is not a dedicated v1 directory')
    return config


def render_unit(config: dict, *, python_path: str = '/usr/bin/python3') -> str:
    """Render a stable *uninstalled* systemd candidate; no shell expansion."""
    _validate_system_config(config)
    interpreter = _safe_posix(python_path)
    if not interpreter.startswith(('/usr/bin/', '/usr/local/bin/', '/opt/')):
        raise PlanningRefused('Python executable must use a reviewed executable prefix')
    state = config['storage']['state_dir']
    return '\n'.join((
        '[Unit]',
        'Description=ONYX CORE v1.0.0 USB receiver (INACTIVE CANDIDATE)',
        'Wants=network-online.target',
        'After=NetworkManager.service network-online.target',
        'ConditionPathExists=' + ACTIVATION_MARKER,
        'RefuseManualStart=yes',
        '',
        '[Service]',
        'Type=simple',
        'User=onyxcore',
        'Group=onyxcore',
        'EnvironmentFile=' + CREDENTIAL_PATH,
        'WorkingDirectory=' + state,
        'ExecStart=' + interpreter + ' -I -B ' + RELEASE_ROOT +
        '/tools/installation/pi/onyx_v100_pi_launch.py --config ' +
        CONFIG_PATH + ' --installed-root ' + RELEASE_ROOT +
        ' --run --approve-execution',
        'Restart=on-failure',
        'RestartSec=15',
        'UMask=0077',
        'NoNewPrivileges=true',
        'PrivateTmp=true',
        'ProtectSystem=strict',
        'ProtectHome=true',
        'ReadWritePaths=' + state,
        'CapabilityBoundingSet=',
        'AmbientCapabilities=',
        '',
        '[Install]',
        'WantedBy=multi-user.target',
        '',
    ))


def _metadata(path: str, *, kind: str) -> dict:
    """Inspect metadata ONLY; permission-denied is never reported as absent."""
    node = Path(path)
    try:
        ancestors = list(reversed((node, *node.parents)))
        for ancestor in ancestors:
            try:
                st = ancestor.lstat()
            except FileNotFoundError:
                return {'presence': 'missing', 'safe_type': False}
            if stat.S_ISLNK(st.st_mode):
                return {'presence': 'unsafe_redirect', 'safe_type': False}
        mode = st.st_mode
        acceptable = (stat.S_ISDIR(mode) if kind == 'directory' else stat.S_ISREG(mode))
        return {'presence': 'present', 'safe_type': acceptable,
                'uid': st.st_uid, 'gid': st.st_gid, 'mode': stat.S_IMODE(mode)}
    except (PermissionError, OSError):
        return {'presence': 'unknown', 'safe_type': False}


def observe_native(config: dict) -> dict:
    """Optional native metadata inspection; never run this implicitly on Windows."""
    if sys.platform != 'linux' or platform.machine().lower() != 'armv6l' or sys.version_info[:2] != (3, 13):
        raise PlanningRefused('native inspection requires Linux ARMv6 and Python 3.13')
    import pwd
    import grp
    try:
        passwd = pwd.getpwnam('onyxcore')
    except KeyError:
        passwd = None
    try:
        group = grp.getgrnam('onyxcore')
    except KeyError:
        group = None
    return {'platform': 'linux', 'machine': 'armv6l', 'python_series': '3.13',
            'tools': {name: shutil.which(name) is not None for name in NEEDED_TOOLS},
            'service_uid': passwd.pw_uid if passwd else None,
            'service_gid': group.gr_gid if group else None,
            'state': _metadata(config['storage']['state_dir'], kind='directory'),
            'credential': _metadata(CREDENTIAL_PATH, kind='credential'),
            'unit': _metadata(UNIT_PATH, kind='file'),
            'legacy_unit': _metadata(LEGACY_UNIT, kind='file'),
            'activation_marker': _metadata(ACTIVATION_MARKER, kind='file')}


def classify_observation(obs: dict) -> tuple[str, list[str], list[str]]:
    """Never mark a host installable on the strength of static config alone."""
    blockers = []
    pending = []
    if (obs.get('platform'), obs.get('machine'), obs.get('python_series')) != ('linux', 'armv6l', '3.13'):
        blockers.append('unsupported_native_os_arch_or_python')
    commands = obs.get('tools', {})
    for name in NEEDED_TOOLS:
        if commands.get(name) is not True:
            blockers.append('missing_tool_' + name)
    uid, gid = obs.get('service_uid'), obs.get('service_gid')
    if type(uid) is not int or type(gid) is not int or uid <= 0 or gid <= 0:
        pending.append('service_account_or_group_missing')
    state = obs.get('state') or {}
    if state.get('presence') == 'unsafe_redirect':
        blockers.append('redirected_state_directory')
    elif state.get('presence') == 'present':
        if (state.get('safe_type') is not True or state.get('uid') != uid or
                state.get('gid') != gid or state.get('mode') != 0o700):
            blockers.append('state_directory_metadata_unsafe')
    else:
        pending.append('state_directory_requires_separate_provisioning')
    cred = obs.get('credential') or {}
    if cred.get('presence') == 'unsafe_redirect':
        blockers.append('redirected_credential')
    elif cred.get('presence') == 'present':
        if (cred.get('safe_type') is not True or cred.get('uid') != 0 or
                cred.get('mode') != 0o600):
            blockers.append('credential_metadata_unsafe')
    else:
        pending.append('credential_requires_separate_enrollment_or_metadata_review')
    unit = obs.get('unit') or {}
    if unit.get('presence') != 'missing':
        blockers.append('v1_unit_target_not_proven_absent')
    guard = obs.get('activation_marker') or {}
    if guard.get('presence') != 'missing':
        blockers.append('activation_marker_not_proven_absent')
    # The legacy unit may exist; it must not be changed by this phase.
    pending.append('legacy_receiver_isolation_must_be_reviewed')
    pending.append('usb_link_and_route_not_verified')
    if blockers:
        return 'BLOCKED', blockers, pending
    return 'PREPARATION_REQUIRED', blockers, pending


def plan(config: dict, *, python_path='/usr/bin/python3', observations=None) -> dict:
    content = render_unit(config, python_path=python_path)
    if observations is None:
        status = 'NOT_NATIVELY_INSPECTED'
        blockers = []
        pending = ['run_separately_authorized_native_readonly_preflight',
                   'provision_new_v1_state_and_credentials_separately',
                   'verify_usb_route_and_legacy_service_isolation']
    else:
        status, blockers, pending = classify_observation(observations)
    return {
        'schema_version': 1,
        'operation': 'PI_V100_INACTIVE_SYSTEM_PREPARATION_PREVIEW',
        'release_version': '1.0.0',
        'unit_target': UNIT_PATH,
        'release_root': RELEASE_ROOT,
        'config_target': CONFIG_PATH,
        'credential_target': CREDENTIAL_PATH,
        'activation_marker': ACTIVATION_MARKER,
        'state_dir': config['storage']['state_dir'],
        'receiver_port': config['receiver']['port'],
        'receiver_source': config['receiver']['source'],
        'unit_sha256': hashlib.sha256(content.encode('utf-8')).hexdigest(),
        'native_readiness': status,
        'blockers': blockers,
        'pending_actions': pending,
        'credential_contents_read': False,
        'unit_written': False,
        'service_registered': False,
        'service_enabled': False,
        'activation_performed': False,
        'network_changes': False,
        'persistent_state_changes': False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--python-path', default='/usr/bin/python3')
    parser.add_argument('--native-readonly', action='store_true',
                        help='Optional actual ARMv6 metadata preflight (no writes)')
    parser.add_argument('--print-unit', action='store_true', help='Print unit candidate; do not write')
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config, 'pi-armv6')
        _validate_system_config(cfg)
        if args.print_unit and args.native_readonly:
            raise PlanningRefused('unit text preview and native inspection must be separate')
        if args.print_unit:
            sys.stdout.write(render_unit(cfg, python_path=args.python_path))
            return 0
        obs = observe_native(cfg) if args.native_readonly else None
        report = plan(cfg, python_path=args.python_path, observations=obs)
        sys.stdout.write(json.dumps(report, sort_keys=True, separators=(',', ':')) + '\n')
        return 0
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
