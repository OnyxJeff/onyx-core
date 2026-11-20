#!/usr/bin/env python3
"""ONYX CORE v1.0.0 config-driven native receiver launch, inert by default.

Preview reads captured IP metadata or invokes the read-only ip tool. Execution
requires explicit --run --approve-execution; never writes config or credentials.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys

HERE = Path(__file__).resolve().parent
COMMON = HERE.parent / 'common'
if str(COMMON) not in sys.path:
    sys.path.insert(0, str(COMMON))
from onyx_v100_config import load_config, ConfigRefused
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from onyx_v100_usb_binding import selected_ipv4_from_json, UsbBindRefused

class LaunchRefused(ValueError):
    pass

def _no_redirect(path: Path):
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise LaunchRefused('Redirected runtime path refused')

def plan(config: dict, inventory: str, root: Path):
    root = Path(root)
    if not root.is_absolute() or '..' in root.parts:
        raise LaunchRefused('Absolute installed source root required')
    _no_redirect(root)
    script = root / 'pi/services/receiver/receiver_v100.py'
    _no_redirect(script)
    if not script.is_file():
        raise LaunchRefused('Versioned receiver missing')
    data = config['receiver']
    storage = config['storage']
    addr = selected_ipv4_from_json(inventory, data['interface'], data['ipv4_subnet'])
    state = PurePosixPath(storage['state_dir'])
    if os.name == 'posix':
        _no_redirect(Path(storage['state_dir']))
    args = [sys.executable, '-B', str(script), '--bind', addr,
            '--usb-subnet', data['ipv4_subnet'],
            '--expected-source', data['source'], '--port', str(data['port']),
            '--state-file', str(state / storage['snapshot_name']),
            '--history-file', str(state / storage['history_name'])]
    return {'schema_version': 1, 'operation': 'RECEIVER_LAUNCH_PREVIEW',
            'activation_performed': False, 'bind_address': addr,
            'usb_subnet': data['ipv4_subnet'], 'receiver_port': data['port'],
            'receiver_path': str(script), 'history_path': args[-1],
            'snapshot_path': args[-3], 'argv': args}

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--installed-root', type=Path, required=True)
    p.add_argument('--ip-json-file', type=Path, help='Precaptured metadata: preview only')
    p.add_argument('--run', action='store_true', help='Replace this process with receiver')
    p.add_argument('--approve-execution', action='store_true', help='Explicit separate activation approval')
    a = p.parse_args(argv)
    try:
        if a.run != a.approve_execution:
            raise LaunchRefused('Runtime execution requires BOTH --run and --approve-execution')
        if a.run and (a.ip_json_file is not None or os.name != 'posix' or sys.platform != 'linux'):
            raise LaunchRefused('Runtime execution allowed only on native Linux with live interface inventory')
        config = load_config(a.config, 'pi-armv6')
        if a.ip_json_file is not None:
            if a.ip_json_file.is_symlink() or a.ip_json_file.stat().st_size > 8192:
                raise LaunchRefused('Untrusted captured IP metadata')
            raw = a.ip_json_file.read_text(encoding='utf-8')
        else:
            result = subprocess.run(['ip', '-j', '-4', 'address', 'show', 'dev', config['receiver']['interface']],
                                    capture_output=True, text=True, check=False, timeout=5)
            if result.returncode != 0:
                raise LaunchRefused('USB interface inspection failed')
            raw = result.stdout
        result = plan(config, raw, a.installed_root)
        if not a.run:
            print(json.dumps(result, sort_keys=True, separators=(',', ':')))
            return 0
        if os.environ.get('ONYXCORE_TOKEN', '') == '' or len(os.environ['ONYXCORE_TOKEN']) < 32:
            raise LaunchRefused('Receiver credential must already be supplied by protected service environment')
        if not Path(result['history_path']).parent.is_dir():
            raise LaunchRefused('Persistent data directory missing')
        os.execv(sys.executable, result['argv'])
        return 1
    except (OSError, ValueError, subprocess.TimeoutExpired, UnicodeError) as exc:
        print('STOP: '+str(exc), file=sys.stderr)
        return 2
if __name__ == '__main__':
    raise SystemExit(main())
