#!/usr/bin/env python3
"""ONYX CORE v1.0.0 M1-S3: strict, read-only installation config validator.

No services, network probes, secrets, directories or files are modified.
The schema is a candidate foundation, not yet consumed by live launchers.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import urlsplit

MAX_CONFIG_BYTES = 65536
SCHEMA_VERSION = 1
_PLATFORMS = ('windows', 'pi-armv6')
_IFACE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,14}\Z')
_WIN_ADAPTER = re.compile(r'[A-Za-z0-9][A-Za-z0-9 _().#-]{0,127}\Z')
_SOURCE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z')
_DNS = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\Z')
_FILENAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
_SENSOR_PATH = re.compile(r'/Sensor/[A-Za-z0-9 _./()#-]{1,490}\Z')


class ConfigRefused(ValueError):
    """Untrusted or unsupported installation configuration."""


def _reject_constant(_value):
    raise ConfigRefused('Non-finite JSON numbers are not supported')


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigRefused('Duplicate JSON configuration key')
        result[key] = value
    return result


def _object(value, required, optional=(), *, name='configuration'):
    if type(value) is not dict:
        raise ConfigRefused(name + ' must be an object')
    missing = set(required) - set(value)
    extras = set(value) - set(required) - set(optional)
    if missing or extras:
        # Do not echo potentially secret keys supplied by mistake.
        raise ConfigRefused(name + ' has missing or unsupported fields')
    return value


def _string(value, pattern, name):
    if type(value) is not str or not pattern.fullmatch(value):
        raise ConfigRefused(name + ' has an invalid value')
    return value


def _port(value, name):
    if type(value) is not int or not 1024 <= value <= 65535:
        raise ConfigRefused(name + ' must be a nonprivileged TCP port')
    return value


def _hostname(value):
    _string(value, _DNS, 'receiver.host')
    if len(value) > 253 or '..' in value or value.startswith('-') or value.endswith('-'):
        raise ConfigRefused('receiver.host is malformed')
    if re.fullmatch(r'[0-9.]+', value):
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise ConfigRefused('receiver.host is not a valid IPv4 address') from exc
        if (address.version != 4 or not (address.is_private or address.is_link_local) or
                address.is_loopback or address.is_unspecified or address.is_multicast or
                int(address) == 0xffffffff):
            raise ConfigRefused('receiver.host must be usable private or link-local IPv4')
    return value


def _sensor_endpoint(value):
    if type(value) is not str or len(value) > 300:
        raise ConfigRefused('cpu_temperature.endpoint is invalid')
    try:
        url = urlsplit(value)
        host = url.hostname
        port = url.port
    except ValueError as exc:
        raise ConfigRefused('cpu_temperature.endpoint is malformed') from exc
    if (url.scheme != 'http' or not host or url.username is not None or
            url.password is not None or url.path != '/data.json' or
            url.query or url.fragment or not port or not 1 <= port <= 65535):
        raise ConfigRefused('cpu_temperature.endpoint must be a local HTTP data.json endpoint')
    allowed = host.lower() == 'localhost' or host.lower().endswith('.local')
    if not allowed:
        try:
            ip = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ConfigRefused('cpu_temperature.endpoint host must be local/private') from exc
        allowed = ip.version == 4 and (ip.is_private or ip.is_link_local or ip.is_loopback)
    if not allowed:
        raise ConfigRefused('cpu_temperature.endpoint host must be local/private')
    return value


def _usb_subnet(value):
    if type(value) is not str or len(value) > 32:
        raise ConfigRefused('receiver.ipv4_subnet is invalid')
    try:
        network = ipaddress.IPv4Network(value, strict=True)
    except ValueError as exc:
        raise ConfigRefused('receiver.ipv4_subnet requires a canonical IPv4 CIDR') from exc
    accepted = (ipaddress.IPv4Network('10.0.0.0/8'),
                ipaddress.IPv4Network('172.16.0.0/12'),
                ipaddress.IPv4Network('192.168.0.0/16'),
                ipaddress.IPv4Network('169.254.0.0/16'))
    if (str(network) != value or not any(network.subnet_of(base) for base in accepted) or
            not 16 <= network.prefixlen <= 30):
        raise ConfigRefused('receiver.ipv4_subnet requires a private subnet (/16 to /30)')
    return value


def _state_dir(value):
    if type(value) is not str or not 2 <= len(value) <= 240:
        raise ConfigRefused('storage.state_dir is invalid')
    path = PurePosixPath(value)
    if (not path.is_absolute() or value.endswith('/') or '//' in value or
            path.as_posix() != value or any(p in ('.', '..') for p in value.split('/')) or
            len(path.parts) < 3):
        raise ConfigRefused('storage.state_dir must be a normalized absolute directory')
    if path.parts[1] in ('etc', 'proc', 'sys', 'dev', 'run', 'root', 'boot', 'usr', 'bin', 'sbin'):
        raise ConfigRefused('storage.state_dir is in a reserved OS directory')
    return value


def validate_config(doc, expected_platform):
    """Validate without filesystem/network effects; return unchanged validated mapping.

    OS permissions, network scope, actual devices, account ownership and credentials
    are intentionally outside this STATIC validation step.
    """
    if expected_platform not in _PLATFORMS:
        raise ConfigRefused('Unsupported expected platform')
    _object(doc, ('schema_version', 'platform'),
            ('receiver', 'collector', 'usb', 'gateway', 'cpu_temperature', 'storage'), name='root')
    if type(doc['schema_version']) is not int or doc['schema_version'] != SCHEMA_VERSION:
        raise ConfigRefused('Unsupported configuration schema version')
    if doc['platform'] != expected_platform:
        raise ConfigRefused('Configuration platform mismatch')

    if expected_platform == 'windows':
        _object(doc, ('schema_version', 'platform', 'receiver', 'collector', 'usb', 'gateway'),
                ('cpu_temperature',), name='Windows root')
        receiver = _object(doc['receiver'], ('host', 'port'), name='Windows receiver')
        _hostname(receiver['host'])
        _port(receiver['port'], 'receiver.port')
        collector = _object(doc['collector'], ('source', 'network_adapter', 'interval_seconds'),
                            name='Windows collector')
        _string(collector['source'], _SOURCE, 'collector.source')
        _string(collector['network_adapter'], _WIN_ADAPTER, 'collector.network_adapter')
        if (type(collector['interval_seconds']) is not int or
                not 5 <= collector['interval_seconds'] <= 3600):
            raise ConfigRefused('collector.interval_seconds must be between 5 and 3600')
        usb = _object(doc['usb'], ('adapter_name',), name='Windows USB')
        _string(usb['adapter_name'], _WIN_ADAPTER, 'usb.adapter_name')
        gateway = _object(doc['gateway'], ('listen_host', 'port'), name='Windows gateway')
        if gateway['listen_host'] != '127.0.0.1':
            raise ConfigRefused('gateway.listen_host must be loopback-only')
        _port(gateway['port'], 'gateway.port')
        sensor = doc.get('cpu_temperature', {'enabled': False})
        if type(sensor) is not dict or type(sensor.get('enabled')) is not bool:
            raise ConfigRefused('cpu_temperature.enabled must be boolean')
        if sensor['enabled']:
            _object(sensor, ('enabled', 'endpoint', 'sensor_path'), name='CPU temperature')
            _sensor_endpoint(sensor['endpoint'])
            _string(sensor['sensor_path'], _SENSOR_PATH, 'cpu_temperature.sensor_path')
        else:
            _object(sensor, ('enabled',), name='CPU temperature')
    else:
        _object(doc, ('schema_version', 'platform', 'receiver', 'storage'), name='Pi root')
        receiver = _object(doc['receiver'], ('interface', 'port', 'ipv4_subnet', 'source'), name='Pi receiver')
        _string(receiver['interface'], _IFACE, 'receiver.interface')
        _string(receiver['source'], _SOURCE, 'receiver.source')
        _port(receiver['port'], 'receiver.port')
        _usb_subnet(receiver['ipv4_subnet'])
        storage = _object(doc['storage'], ('state_dir', 'history_name', 'snapshot_name'),
                          name='Pi storage')
        _state_dir(storage['state_dir'])
        history = _string(storage['history_name'], _FILENAME, 'storage.history_name')
        snapshot = _string(storage['snapshot_name'], _FILENAME, 'storage.snapshot_name')
        if not history.endswith('.db') or not snapshot.endswith('.json') or history == snapshot:
            raise ConfigRefused('Storage filenames need .db and .json extensions')
    return doc


def validate_pair(windows, pi):
    """Static cross-host contract only; never proves DNS/ICS reachability or authentication."""
    validate_config(windows, 'windows')
    validate_config(pi, 'pi-armv6')
    if windows['receiver']['port'] != pi['receiver']['port']:
        raise ConfigRefused('Windows/Pi receiver port mismatch')
    if windows['collector']['source'] != pi['receiver']['source']:
        raise ConfigRefused('Windows/Pi telemetry source mismatch')
    return True


def load_config(path, expected_platform):
    path = Path(path)
    if (path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()) or
            not path.is_file()):
        raise ConfigRefused('Configuration must be an existing regular file')
    if path.stat().st_size > MAX_CONFIG_BYTES:
        raise ConfigRefused('Configuration file exceeds size limit')
    try:
        contents = path.read_bytes()
        if len(contents) > MAX_CONFIG_BYTES:
            raise ConfigRefused('Configuration file exceeds size limit')
        doc = json.loads(contents.decode('utf-8-sig'),
                         object_pairs_hook=_unique_keys, parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigRefused('Configuration is not valid UTF-8 JSON') from exc
    return validate_config(doc, expected_platform)


def summary(doc):
    platform = doc['platform']
    common = {
        'schema_version': 1,
        'operation': 'READ_ONLY_CONFIGURATION_VALIDATION',
        'valid': True,
        'platform': platform,
        'configuration_written': False,
        'credential_contents_read': False,
        'network_scope_verified': False,
        'service_or_task_changes': False,
        'installation_accepted': False,
    }
    if platform == 'windows':
        common['settings'] = {
            'receiver_port': doc['receiver']['port'],
            'gateway_port': doc['gateway']['port'],
            'gateway_loopback_only': True,
            'usb_adapter_selected': True,
            'network_metric_adapter_selected': True,
            'cpu_temperature_enabled': doc.get('cpu_temperature', {}).get('enabled', False),
        }
        common['operator_actions'] = [
            'Verify selected adapters and receiver address on this host.',
            'Verify configured receiver and sensor endpoints use only the intended private link.',
            'Enroll user-scoped DPAPI credential in a separately approved step.',
        ]
    else:
        common['settings'] = {
            'receiver_port': doc['receiver']['port'],
            'usb_interface_selected': True,
            'usb_subnet_selected': True,
            'state_directory_selected': True,
            'history_filename_selected': True,
        }
        common['operator_actions'] = [
            'Verify ARMv6 OS, gadget interface and receiver bind address natively.',
            'Verify writable state ownership and path safety before installation.',
            'Enroll receiver credential in a separately approved step.',
        ]
    return common


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--platform', required=True, choices=_PLATFORMS)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config, args.platform)
        print(json.dumps(summary(config), sort_keys=True, separators=(',', ':')))
        return 0
    except (ConfigRefused, OSError, ValueError) as exc:
        # Field-only validator messages avoid echoing secret-looking input values.
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
