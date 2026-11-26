#!/usr/bin/env python3
"""ONYX CORE v1.0.0 M1-S4: observational Raspberry Pi ARMv6 preflight.

No service control, package install, network packet probes, credential reads,
configuration writes, persistent state writes, or receiver launch. Intended for
native Pi Zero inspection after explicit operator approval. Offline tests inject
synthetic observations and do not inspect the test host's system state.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys

# Works with -I -B and a versioned deployment, without site-packages.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from onyx_v100_config import ConfigRefused, load_config  # noqa: E402

OPERATION = 'READ_ONLY_PI_INSTALL_PREFLIGHT'
PYTHON_SERIES = (3, 13)
MAX_IP_OUTPUT = 8192


class ReadinessRefused(ValueError):
    pass


def _os_release(path):
    """Parse only ordinary key=value text; never source the OS file as shell."""
    output = {}
    try:
        raw = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        return output
    if len(raw) > 16384:
        return output
    for line in raw.splitlines():
        match = re.fullmatch(r'([A-Z][A-Z0-9_]*)=(.*)', line)
        if not match:
            continue
        value = match.group(2)
        if value.startswith(('"', "'")) and len(value) >= 2 and value[-1] == value[0]:
            value = value[1:-1]
        if re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', value):
            output[match.group(1)] = value
    return output


def _model(path):
    try:
        return path.read_bytes()[:120].decode('ascii', 'replace').rstrip('\x00\n\r ')
    except OSError:
        return ''


def _not_redirected(path):
    """Refuse symlinked path ancestors; only inspect metadata, not contents."""
    cur = Path(path)
    while True:
        try:
            mode = cur.lstat().st_mode
            if stat.S_ISLNK(mode):
                return False
        except FileNotFoundError:
            pass
        except OSError:
            # A protected parent can prevent even metadata inspection.
            # Unknown is different from a proven symlink/redirect.
            return None
        if cur == cur.parent:
            return True
        cur = cur.parent


def _path_metadata(path, kind, expected_uid=None):
    """Metadata-only check. No credential contents and no SQLite opens."""
    path = Path(path)
    redirects = _not_redirected(path)
    if redirects is None:
        # Do not claim that a root-private credential is absent when
        # the unprivileged inspector cannot traverse its parent.
        return {'present': None, 'safe': False}
    if not redirects:
        return {'present': True, 'safe': False}
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {'present': False, 'safe': False}
    except OSError:
        return {'present': None, 'safe': False}
    acceptable_type = stat.S_ISDIR(info.st_mode) if kind == 'directory' else stat.S_ISREG(info.st_mode)
    if kind == 'credential':
        safe = acceptable_type and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o600
    else:
        safe = (acceptable_type and expected_uid is not None and info.st_uid == expected_uid
                and not (stat.S_IMODE(info.st_mode) & 0o022)
                and (stat.S_IMODE(info.st_mode) & 0o700) == 0o700)
    return {'present': True, 'safe': bool(safe)}


def _addresses_from_ip_json(raw, interface):
    """Accept only usable private/link-local IPv4 addresses on exact interface."""
    doc = json.loads(raw)
    if not isinstance(doc, list):
        raise ReadinessRefused('Invalid interface address inventory')
    addresses = []
    for row in doc:
        if type(row) is not dict or row.get('ifname') != interface:
            continue
        entries = row.get('addr_info', [])
        if type(entries) is not list:
            raise ReadinessRefused('Invalid interface address inventory')
        for entry in entries:
            if type(entry) is not dict or entry.get('family') != 'inet':
                continue
            try:
                address = ipaddress.IPv4Address(entry['local'])
            except (ValueError, KeyError, TypeError) as exc:
                raise ReadinessRefused('Invalid interface IPv4 address') from exc
            if ((address.is_private or address.is_link_local) and not
                    (address.is_loopback or address.is_unspecified or address.is_multicast or
                     address.is_reserved or address == ipaddress.IPv4Address('255.255.255.255'))):
                addresses.append(str(address))
    return sorted(set(addresses))


def collect_observations(config, *, ip_reader=None):
    """Native, local metadata inventory. `ip` queries kernel state, not the network."""
    interface = config['receiver']['interface']
    state_dir = Path(config['storage']['state_dir'])
    try:
        import pwd  # POSIX only; never needed by offline Windows tests
        service_uid = pwd.getpwnam('onyxcore').pw_uid
    except (ImportError, KeyError):
        service_uid = None
    os_info = _os_release(Path('/etc/os-release'))
    model = _model(Path('/proc/device-tree/model'))
    interface_present = (Path('/sys/class/net') / interface).is_dir()
    ip_exe = shutil.which('ip')
    addresses = []
    address_inspection_succeeded = False
    if interface_present and ip_exe:
        try:
            if ip_reader is None:
                result = subprocess.run([ip_exe, '-j', '-4', 'address', 'show', 'dev', interface],
                                        capture_output=True, timeout=3, check=False)
                if result.returncode != 0 or len(result.stdout) > MAX_IP_OUTPUT:
                    raise ReadinessRefused('Interface address metadata unavailable')
                raw = result.stdout
            else:
                raw = ip_reader(interface)
            if isinstance(raw, bytes):
                raw = raw.decode('utf-8')
            if len(raw) > MAX_IP_OUTPUT:
                raise ReadinessRefused('Interface address inventory too large')
            addresses = _addresses_from_ip_json(raw, interface)
            address_inspection_succeeded = True
        except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired):
            pass  # Unknown rather than claim network availability.
    return {
        'architecture': platform.machine(),
        'model': model,
        'os_id': os_info.get('ID', ''),
        'os_codename': os_info.get('VERSION_CODENAME', ''),
        'python_version': '%d.%d.%d' % sys.version_info[:3],
        'python_supported': sys.version_info[:2] == PYTHON_SERIES,
        'systemd_available': bool(shutil.which('systemctl') and Path('/run/systemd/system').is_dir()),
        'networkmanager_tools_present': bool(shutil.which('nmcli')),
        'iproute2_present': bool(ip_exe),
        'interface_present': interface_present,
        'interface_address_inspected': address_inspection_succeeded,
        'interface_ipv4': addresses,
        'service_account_present': service_uid is not None,
        'state_directory': _path_metadata(state_dir, 'directory', service_uid),
        'credential_file': _path_metadata(Path('/etc/onyxcore/receiver.env'), 'credential'),
        'legacy_unit_present': Path('/etc/systemd/system/onyxcore-receiver.service').exists(),
        'candidate_unit_present': Path('/etc/systemd/system/onyxcore-v090-receiver.service').exists(),
    }


def evaluate(config, observed):
    """Pure policy: no effects. Do not confuse metadata readiness with activation."""
    if config.get('platform') != 'pi-armv6':
        raise ReadinessRefused('Pi preflight requires a Pi configuration')
    blockers = []
    actions = []
    if observed['architecture'] != 'armv6l':
        blockers.append('Target CPU architecture is not ARMv6.')
    if observed['model'] != 'Raspberry Pi Zero Rev 1.3':
        blockers.append('Target is not the supported original Raspberry Pi Zero Rev 1.3.')
    if observed['os_id'] not in ('raspbian', 'debian') or observed['os_codename'] != 'trixie':
        blockers.append('Supported Raspberry Pi OS Trixie family not confirmed.')
    if not observed['python_supported']:
        blockers.append('Python 3.13.x is required by the current v1.0.0 candidate.')
    if not observed['systemd_available']:
        blockers.append('Active systemd runtime not detected.')
    if not observed['networkmanager_tools_present']:
        blockers.append('NetworkManager command-line tooling not detected.')
    if not observed['iproute2_present']:
        blockers.append('iproute2 address inspection command not detected.')
    if not observed['service_account_present']:
        actions.append('Provision the dedicated onyxcore system account after approval.')
    directory = observed['state_directory']
    if directory['present'] is None:
        actions.append('State directory metadata could not be verified with current permissions; request separate read-only privileged inspection.')
    elif directory['present'] is False:
        actions.append('Prepare a protected, service-owned state directory after approval.')
    elif not directory['safe']:
        blockers.append('Existing state directory metadata is unsafe or unexpected.')
    credential = observed['credential_file']
    if credential['present'] is None:
        actions.append('Pi credential file metadata could not be verified with current permissions; do not assume it is missing or re-enroll.')
    elif credential['present'] is False:
        actions.append('Enroll protected Pi receiver credential after separate authorization.')
    elif not credential['safe']:
        blockers.append('Existing Pi credential file permissions or ownership are unsafe.')
    preferred_subnet = ipaddress.IPv4Network(config['receiver']['ipv4_subnet'])
    selected_count = sum(1 for candidate in observed['interface_ipv4']
                         if ipaddress.IPv4Address(candidate) in preferred_subnet)
    if not observed['interface_present']:
        actions.append('Configure the supported Pi USB Ethernet gadget interface.')
    elif not observed['interface_address_inspected']:
        actions.append('Verify the selected USB interface address locally; metadata was unavailable.')
    elif selected_count != 1:
        actions.append('Confirm exactly one IPv4 address in the configured USB subnet on the selected interface.')
    if observed['legacy_unit_present'] or observed['candidate_unit_present']:
        actions.append('Existing receiver unit detected: use reviewed upgrade workflow, not clean-host registration.')
    actions.append('Verify Windows USB/ICS peer and receiver authentication in a separately authorized stage.')
    actions.append('Do not enable/start services or modify network settings from this preflight.')
    state = 'BLOCKED' if blockers else 'REQUIRES_CONFIGURATION'
    return {
        'schema_version': 1,
        'operation': OPERATION,
        'observation_only': True,
        'has_network_probes': False,
        'credential_contents_read': False,
        'configuration_written': False,
        'service_or_network_changes': False,
        'installation_accepted': False,
        'configuration_valid': True,
        'target': {
            'armv6': observed['architecture'] == 'armv6l',
            'original_pi_zero_rev_1_3': observed['model'] == 'Raspberry Pi Zero Rev 1.3',
            'trixie_family_detected': (observed['os_id'] in ('raspbian', 'debian') and
                                       observed['os_codename'] == 'trixie'),
            'python_3_13_supported': observed['python_supported'],
            'systemd_present': observed['systemd_available'],
            'networkmanager_tools_present': observed['networkmanager_tools_present'],
        },
        'usb': {
            'configured_interface_found': observed['interface_present'],
            'address_metadata_inspected': observed['interface_address_inspected'],
            'usable_private_ipv4_count': len(observed['interface_ipv4']),
            'configured_subnet_ipv4_count': selected_count,
            'network_peer_verified': False,
        },
        'state': {
            'service_account_present': observed['service_account_present'],
            'state_dir_present': directory['present'],
            'state_dir_metadata_safe': directory['safe'],
            'credential_file_present': credential['present'],
            'credential_file_metadata_inspected': credential['present'] is not None,
            'credential_file_metadata_safe': credential['safe'],
            'legacy_unit_present': observed['legacy_unit_present'],
            'candidate_v090_unit_present': observed['candidate_unit_present'],
            'sqlite_contents_read': False,
        },
        'readiness': {
            'state': state,
            'blockers': blockers,
            'operator_actions': actions,
            'installation_accepted': False,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config, 'pi-armv6')
        observed = collect_observations(config)
        report = evaluate(config, observed)
        print(json.dumps(report, sort_keys=True, separators=(',', ':'), ensure_ascii=True))
        return 0
    except (ConfigRefused, ReadinessRefused, OSError, ValueError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
