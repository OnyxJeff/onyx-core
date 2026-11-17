#!/usr/bin/env python3
"""ONYX CORE v0.8.0: offline-first native USB route evidence composition.

DEVELOPMENT HOLD. No protected binding, service, scheduler, journal, network
packet, live CLI or side effects. Import and --check-inert are inert. Explicit
probe_native_path() performs *read-only* native OS queries in the caller token;
it is NOT authorization for a Low Integrity or protected release test.

Only 'NativePathVerified' means adapter identity, gateway IPv4 and selected
route agree within one bounded observation. It is NOT 'WindowsPathReady' or
'Healthy': link state, ICS service, TCP and Pi evidence are outside this module.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from ipaddress import IPv4Address
import json
import re
from typing import Callable

_ALIAS = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}\Z')
_STATES = frozenset({'NativePathVerified', 'RouteMismatch',
                     'GatewayNotPreferred', 'Unavailable'})


@dataclass(frozen=True)
class NativePathAssessment:
    classification: str
    reason: str
    interface_index: int | None = None

    def __post_init__(self):
        if self.classification not in _STATES:
            raise ValueError('unexpected path classification')
        if self.classification == 'NativePathVerified':
            if type(self.interface_index) is not int or not 1 <= self.interface_index < 0xFFFFFFFF:
                raise ValueError('verified evidence requires current interface index')
        elif self.interface_index is not None:
            raise ValueError('nonverified evidence must not expose interface index')
        if type(self.reason) is not str or not self.reason or len(self.reason) > 80:
            raise ValueError('invalid sanitized reason')


def _validate(alias: str, gateway: str, receiver: str) -> None:
    # Validation always precedes imports, Windows DLL loading and callbacks.
    if type(alias) is not str or not _ALIAS.fullmatch(alias):
        raise ValueError('invalid interface alias')
    if type(gateway) is not str or type(receiver) is not str:
        raise ValueError('addresses must be IPv4 strings')
    g = IPv4Address(gateway)
    r = IPv4Address(receiver)
    if (g == r or any(x.is_unspecified or x.is_loopback or x.is_multicast or
                      int(x) == 0xFFFFFFFF for x in (g, r))):
        raise ValueError('invalid local IP pair')


def _resolve_readers(adapter_reader, gateway_reader, route_reader):
    # These imports do not load native libraries; APIs only run when the returned
    # callable is explicitly invoked. Keep in the reviewed source tree.
    if adapter_reader is None:
        from OnyxNativeAdapterIdentity import resolve_adapter
        adapter_reader = resolve_adapter
    if gateway_reader is None:
        from OnyxNativeGatewayAddress import verify_gateway_address
        gateway_reader = verify_gateway_address
    if route_reader is None:
        from OnyxNativeRouteEvidence import probe_route
        route_reader = probe_route
    if not all(callable(x) for x in (adapter_reader, gateway_reader, route_reader)):
        raise ValueError('reader dependency invalid')
    return adapter_reader, gateway_reader, route_reader


def _int_index(result, expected_classification: str) -> int | None:
    if getattr(result, 'classification', None) != expected_classification:
        return None
    value = getattr(result, 'interface_index', None)
    if type(value) is not int or not 1 <= value < 0xFFFFFFFF:
        return None
    return value


def probe_native_path(alias: str, gateway: str, receiver: str, *,
                      adapter_reader: Callable | None = None,
                      gateway_reader: Callable | None = None,
                      route_reader: Callable | None = None) -> NativePathAssessment:
    """Explicit read-only composition. No caching, writes or health escalation.

    Reader injection exists for OFFLINE deterministic tests only; this module is
    not release-bound or approved for a live run. An unexpected reader error or
    absent/inconsistent data cannot be evidence of a confirmed outage.
    """
    try:
        _validate(alias, gateway, receiver)
        a, g, r = _resolve_readers(adapter_reader, gateway_reader, route_reader)
        first = a(alias)
        index = _int_index(first, 'Resolved')
        if index is None:
            return NativePathAssessment('Unavailable', 'AdapterIdentityUnavailable')
        address = g(gateway, receiver, index)
        if getattr(address, 'classification', None) == 'NotPreferred':
            # An address observation can race an adapter rebind. Confirm that
            # the alias still identifies the same interface before emitting a
            # *confirmed* nonpreferred state; otherwise evidence is Unknown.
            last = a(alias)
            if _int_index(last, 'Resolved') != index:
                return NativePathAssessment('Unavailable', 'AdapterIdentityChanged')
            return NativePathAssessment('GatewayNotPreferred', 'GatewayAddressNotPreferred')
        if _int_index(address, 'Preferred') != index:
            return NativePathAssessment('Unavailable', 'GatewayEvidenceUnavailable')
        route = r(receiver, gateway, index)
        route_class = getattr(route, 'classification', None)
        if route_class not in ('ExpectedRoute', 'ConfirmedMismatch'):
            return NativePathAssessment('Unavailable', 'RouteEvidenceUnavailable')
        # Re-resolve the name *after* route query; a changed alias/index means
        # the three observations may have referred to different interfaces.
        last = a(alias)
        if _int_index(last, 'Resolved') != index:
            return NativePathAssessment('Unavailable', 'AdapterIdentityChanged')
        if route_class == 'ConfirmedMismatch':
            # Confirm the evidence refers to a coherent, *selected* route. The
            # route module must return a classification plus an actual index.
            route_index = getattr(route, 'interface_index', None)
            if type(route_index) is not int or not 1 <= route_index < 0xFFFFFFFF:
                return NativePathAssessment('Unavailable', 'RouteEvidenceUnavailable')
            return NativePathAssessment('RouteMismatch', 'ConfirmedAlternateRoute')
        if _int_index(route, 'ExpectedRoute') != index:
            return NativePathAssessment('Unavailable', 'RouteEvidenceContradictory')
        return NativePathAssessment('NativePathVerified', 'NativeUsbEvidenceConsistent', index)
    except (ValueError, TypeError, AttributeError, OSError, OverflowError,
            ImportError, RuntimeError):
        return NativePathAssessment('Unavailable', 'NativeEvidenceUnavailable')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-inert', required=True, action='store_true')
    parser.parse_args(argv)
    print(json.dumps({'schema_version': 1, 'phase': 'native-path-composition',
                      'native_api_invoked': False, 'live_cli_enabled': False,
                      'release_integrated': False, 'low_integrity_validated': False,
                      'windows_health_claimed': False, 'status': 'DEVELOPMENT_HOLD'},
                     sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
