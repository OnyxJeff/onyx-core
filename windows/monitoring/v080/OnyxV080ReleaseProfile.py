#!/usr/bin/env python3
"""ONYX CORE v0.8 release-profile parser, separate from M1's dev-only guard.

This module has NO operational CLI, probe, store writer, or task registration.
It validates release configuration for an independently approved release runner.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import OnyxLiveConnectivity as m1


class ReleaseProfileRefused(ValueError):
    """Release configuration violates the v0.8 read-only contract."""


RELEASE_CONFIG_NAME = 'monitoring.v080.release.example.json'
RELEASE_STATE = r'%LOCALAPPDATA%\OnyxCore-v080-Release\Monitoring'
DEVELOPMENT_STATE = m1.cfg.DEV_STATE
MAX_CONFIG_BYTES = 16 * 1024


def validate_release_config(config: Any) -> dict:
    """Reuse M1's strict shared fields without weakening its live dev guard.

    The substituted development values exist ONLY in an isolated deep copy
    passed to the old validator, NEVER to any probe or released config.
    """
    if type(config) is not dict:
        raise ReleaseProfileRefused('release config must be an object')
    if config.get('profile') != 'release' or config.get('state_dir') != RELEASE_STATE:
        raise ReleaseProfileRefused('v0.8 release profile/store mismatch')
    if config.get('read_only') is not True or config.get('repair_action') != 'None':
        raise ReleaseProfileRefused('read-only and no repair mandatory')
    checked = copy.deepcopy(config)
    checked['profile'] = 'development'
    checked['state_dir'] = DEVELOPMENT_STATE
    try:
        m1.cfg.validate_config(checked)
    except (m1.cfg.ConfigError, ValueError, TypeError) as exc:
        raise ReleaseProfileRefused('release shared config schema invalid') from exc
    interval = config.get('monitoring_interval_seconds')
    if type(interval) is not int or not 90 <= interval <= 600:
        raise ReleaseProfileRefused('release interval must be 90..600 seconds')
    return copy.deepcopy(config)


def _duplicates(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ReleaseProfileRefused('duplicate config key')
        result[name] = value
    return result


def _bad_constant(_: str):
    raise ReleaseProfileRefused('nonfinite JSON constant refused')


def load_release_config(path: Path) -> dict:
    """Pure file read and schema validation; never creates a store or probes."""
    if not isinstance(path, Path) or path.name != RELEASE_CONFIG_NAME:
        raise ReleaseProfileRefused('unexpected v0.8 release config path')
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
        raise ReleaseProfileRefused('redirected config refused')
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_CONFIG_BYTES + 1)
        if not raw or len(raw) > MAX_CONFIG_BYTES:
            raise ReleaseProfileRefused('release config empty or too large')
        config = json.loads(raw.decode('utf-8-sig', 'strict'),
                            object_pairs_hook=_duplicates, parse_constant=_bad_constant)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise ReleaseProfileRefused('unreadable or invalid release config') from exc
    return validate_release_config(config)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-inert', action='store_true', required=True)
    parser.parse_args(argv)
    print(json.dumps({'phase': 'release-profile', 'live_runtime_enabled': False,
                      'production_enrollment_enabled': False, 'release_status': 'HOLD'}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
