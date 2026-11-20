#!/usr/bin/env python3
"""Create a v1 receiver from the pinned legacy source (offline, fail-closed).

Accept LF or consistent CRLF for Git for Windows; output canonical LF bytes.
Never overwrite either original or previously generated file.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys


class PatchRefused(ValueError):
    pass


PINNED_SOURCE_BLOB = '53e4a8a18d443269fb34dde19e5240450b1d232a'

OLD_ARGUMENT = '    parser.add_argument("--bind", required=True, help="Explicit Pi USB ICS IPv4 address")'
NEW_ARGUMENT = (OLD_ARGUMENT + '\n' +
                '    parser.add_argument("--usb-subnet", required=True, help="Configured private USB IPv4 subnet")' +
                '\n    parser.add_argument("--expected-source", required=True, help="Configured telemetry source identity")')
OLD_VALIDATION = '''        if not (args.allow_loopback_test and address == ipaddress.IPv4Address("127.0.0.1")) and (address not in ipaddress.IPv4Network("192.168.137.0/24") or address in (ipaddress.IPv4Address("192.168.137.0"), ipaddress.IPv4Address("192.168.137.255"), ipaddress.IPv4Address("192.168.137.1"))):
            raise ValueError()'''
NEW_VALIDATION = '''        subnet = ipaddress.IPv4Network(args.usb_subnet, strict=True)
        allowed = (ipaddress.IPv4Network("10.0.0.0/8"),
                   ipaddress.IPv4Network("172.16.0.0/12"),
                   ipaddress.IPv4Network("192.168.0.0/16"),
                   ipaddress.IPv4Network("169.254.0.0/16"))
        if not (16 <= subnet.prefixlen <= 30 and any(subnet.subnet_of(base) for base in allowed)):
            raise ValueError()
        if not (args.allow_loopback_test and address == ipaddress.IPv4Address("127.0.0.1")):
            if (address not in subnet or address in (subnet.network_address, subnet.broadcast_address) or
                    address.is_loopback or address.is_multicast or address.is_unspecified or address.is_reserved):
                raise ValueError()'''


def normalized_source(raw: bytes) -> str:
    try:
        src = raw.decode('utf-8')
    except UnicodeError as exc:
        raise PatchRefused('Receiver source encoding invalid') from exc
    if '\ufeff' in src:
        raise PatchRefused('Receiver source BOM refused')
    if '\r\n' in src:
        residue = src.replace('\r\n', '')
        if '\r' in residue or '\n' in residue:
            raise PatchRefused('Mixed source line endings refused')
        src = src.replace('\r\n', '\n')
    elif '\r' in src:
        raise PatchRefused('Unsupported source line endings')
    blob = src.encode('utf-8')
    git_hash = hashlib.sha1(b'blob ' + str(len(blob)).encode('ascii') + b'\x00' + blob).hexdigest()
    if git_hash != PINNED_SOURCE_BLOB:
        raise PatchRefused('Pinned legacy receiver Git blob mismatch')
    return src


def transform(raw: bytes) -> bytes:
    src = normalized_source(raw)
    changes = (
        (OLD_ARGUMENT, NEW_ARGUMENT),
        (OLD_VALIDATION, NEW_VALIDATION),
        ('import math\n', 'import math\nimport re\n'),
        ('KEYS = {', 'SOURCE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\\Z")\nKEYS = {'),
        ('def validate(payload, now=None, check_freshness=True):',
         'def validate(payload, now=None, check_freshness=True, *, expected_source):'),
        ('    if payload["source"] != "SQUALL":\n        raise ValueError("unsupported source")',
         '    if type(expected_source) is not str or not SOURCE_PATTERN.fullmatch(expected_source):\n'
         '        raise ValueError("expected source invalid")\n'
         '    if payload["source"] != expected_source:\n        raise ValueError("unsupported source")'),
        ('    def __init__(self, filename):\n        self.path = Path(filename)',
         '    def __init__(self, filename, *, expected_source):\n        self.path = Path(filename)'),
        ('            validate(candidate, check_freshness=False)',
         '            validate(candidate, check_freshness=False, expected_source=expected_source)'),
        ('def handler_factory(token, store=None):',
         'def handler_factory(token, store=None, *, expected_source):'),
        ('                validate(payload)',
         '                validate(payload, expected_source=expected_source)'),
        ('    token = os.environ.get("ONYXCORE_TOKEN", "")',
         '    if not SOURCE_PATTERN.fullmatch(args.expected_source):\n'
         '        parser.error("invalid configured telemetry source")\n'
         '    token = os.environ.get("ONYXCORE_TOKEN", "")'),
        ('from .integrated_store import IntegratedStore',
         'from .integrated_store_v100 import IntegratedStore'),
        ('from integrated_store import IntegratedStore',
         'from integrated_store_v100 import IntegratedStore'),
        ('        store = IntegratedStore(args.history_file, args.state_file)',
         '        store = IntegratedStore(args.history_file, args.state_file,\n'
         '                                snapshot_validator=lambda candidate: validate(\n'
         '                                    candidate, check_freshness=False, expected_source=args.expected_source))'),
        ('        store = SnapshotStore(args.state_file)',
         '        store = SnapshotStore(args.state_file, expected_source=args.expected_source)'),
        ('handler_factory(token, store))',
         'handler_factory(token, store, expected_source=args.expected_source))'),
    )
    for old, new in changes:
        if src.count(old) != 1:
            raise PatchRefused('Reviewed legacy receiver signature mismatch')
        src = src.replace(old, new)
    compile(src, 'receiver_v100.py', 'exec')
    return src.encode('utf-8')


def build(source: Path, dest: Path):
    if (not source.is_file() or source.is_symlink() or dest.exists() or dest.is_symlink()
            or source.parent != dest.parent or source.name != 'receiver.py'
            or dest.name != 'receiver_v100.py'):
        raise PatchRefused('Adjacent regular source and absent versioned destination required')
    generated = transform(source.read_bytes())
    try:
        with dest.open('xb') as output:
            output.write(generated)
    except FileExistsError as exc:
        raise PatchRefused('Destination already exists') from exc
    if dest.read_bytes() != generated:
        raise PatchRefused('Generated receiver verification failed')
    return hashlib.sha256(generated).hexdigest()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    try:
        print('VERSIONED_RECEIVER_SHA256=' + build(a.source, a.output))
        return 0
    except (OSError, ValueError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
