#!/usr/bin/env python3
"""ONYX CORE v0.8.0: development-only, read-only IPv4 route evidence prototype.

NO production integration, persistent state, SSH, TCP, network traffic, repairs,
notification, scheduler, Windows PowerShell or live CLI. Import and --check-inert
are inert. Only an explicit call to probe_route() can use Windows IP Helper.

The expected interface index MUST originate from a separately trusted, fresh
adapter-name-to-index lookup before any future release integration. The caller
must never supply a cached interface index as proof of routing correctness.
"""
from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
from ipaddress import AddressValueError, NetmaskValueError, IPv4Address, IPv4Network
import json
import os
import sys
from typing import Callable

# Microsoft ipmib.h MIB_IPFORWARDROW: fourteen 32-bit DWORD/IF_INDEX fields.
class MIB_IPFORWARDROW(ctypes.Structure):
    _fields_ = [
        ('dwForwardDest', ctypes.c_uint32),
        ('dwForwardMask', ctypes.c_uint32),
        ('dwForwardPolicy', ctypes.c_uint32),
        ('dwForwardNextHop', ctypes.c_uint32),
        ('dwForwardIfIndex', ctypes.c_uint32),
        ('dwForwardType', ctypes.c_uint32),
        ('dwForwardProto', ctypes.c_uint32),
        ('dwForwardAge', ctypes.c_uint32),
        ('dwForwardNextHopAS', ctypes.c_uint32),
        ('dwForwardMetric1', ctypes.c_uint32),
        ('dwForwardMetric2', ctypes.c_uint32),
        ('dwForwardMetric3', ctypes.c_uint32),
        ('dwForwardMetric4', ctypes.c_uint32),
        ('dwForwardMetric5', ctypes.c_uint32),
    ]

# IP Helper v4 MIB_IPROUTE_TYPE_DIRECT is 3, INDIRECT is 4.
ROUTE_DIRECT = 3
ROUTE_INDIRECT = 4
ALLOWED_CLASSES = frozenset({'ExpectedRoute', 'ConfirmedMismatch', 'Unavailable'})


@dataclass(frozen=True)
class NativeRoute:
    network: str
    if_index: int
    next_hop: str
    route_type: int


@dataclass(frozen=True)
class RouteEvidence:
    classification: str
    reason: str
    interface_index: int | None = None
    # No raw Windows error messages, names, command lines or host secrets.

    def __post_init__(self):
        if self.classification not in ALLOWED_CLASSES:
            raise ValueError('unknown route classification')


def _ip_to_dword(value: str) -> int:
    """IP Helper DWORD IPv4 fields contain network-order bytes in host memory."""
    return int.from_bytes(IPv4Address(value).packed, byteorder='little')


def _dword_to_ip(value: int) -> str:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError('invalid native IPv4 DWORD')
    return str(IPv4Address(value.to_bytes(4, byteorder='little')))


def _row_to_route(row: MIB_IPFORWARDROW) -> NativeRoute:
    # Verify ABI before touching native API; Windows is little-endian.
    if ctypes.sizeof(MIB_IPFORWARDROW) != 56 or sys.byteorder != 'little':
        raise ValueError('unsupported MIB_IPFORWARDROW ABI')
    prefix = IPv4Network((_dword_to_ip(int(row.dwForwardDest)),
                          _dword_to_ip(int(row.dwForwardMask))), strict=True)
    return NativeRoute(
        network=str(prefix),
        if_index=int(row.dwForwardIfIndex),
        next_hop=_dword_to_ip(int(row.dwForwardNextHop)),
        route_type=int(row.dwForwardType),
    )


def evaluate_route(route: NativeRoute, *, destination: str,
                   expected_gateway: str, expected_if_index: int) -> RouteEvidence:
    """Pure, conservative classification; no OS calls."""
    try:
        if type(destination) is not str or type(expected_gateway) is not str:
            raise ValueError('IPv4 strings required')
        target = IPv4Address(destination)
        gateway = IPv4Address(expected_gateway)
        if type(expected_if_index) is not int or not 1 <= expected_if_index <= 0xFFFFFFFF:
            raise ValueError('missing expected interface')
        if not isinstance(route, NativeRoute):
            raise ValueError('missing route object')
        network = IPv4Network(route.network, strict=True)
        hop = IPv4Address(route.next_hop)
        if (type(route.if_index) is not int or not 1 <= route.if_index <= 0xFFFFFFFF or
                type(route.route_type) is not int or route.route_type not in
                (ROUTE_DIRECT, ROUTE_INDIRECT) or target not in network):
            raise ValueError('unusable route data')
        # Direct and indirect route types must agree with the next hop.
        if (route.route_type == ROUTE_DIRECT and int(hop) != 0) or (
                route.route_type == ROUTE_INDIRECT and int(hop) == 0):
            raise ValueError('incoherent route type and next hop')
    except (AddressValueError, NetmaskValueError, ValueError, TypeError, AttributeError):
        return RouteEvidence('Unavailable', 'InvalidNativeEvidence')

    # A direct *default* route on the chosen adapter does not establish the
    # intended USB subnet. Both receiver and ICS gateway must be covered.
    if (route.if_index == expected_if_index and route.route_type == ROUTE_DIRECT
            and int(hop) == 0 and gateway in network and network.prefixlen > 0):
        return RouteEvidence('ExpectedRoute', 'SelectedDirectUsbRoute', route.if_index)
    if (route.if_index == expected_if_index and route.route_type == ROUTE_DIRECT
            and int(hop) == 0):
        return RouteEvidence('Unavailable', 'UsbSubnetNotConfirmed')
    return RouteEvidence('ConfirmedMismatch', 'SelectedAlternateRoute', route.if_index)


def _get_best_route(destination: str, *, loader: Callable | None = None) -> NativeRoute:
    """Explicit read-only API call. Default loads Windows iphlpapi.dll lazily."""
    if ctypes.sizeof(MIB_IPFORWARDROW) != 56 or sys.byteorder != 'little':
        raise ValueError('unsupported Windows ABI')
    # The function is callable for injected offline tests on any platform.
    # Never attempt loading a real Windows DLL off Windows.
    if loader is None:
        if os.name != 'nt':
            raise OSError('Windows required')
        loader = ctypes.WinDLL
    dll = loader('iphlpapi.dll')
    fn = dll.GetBestRoute
    fn.argtypes = (ctypes.c_uint32, ctypes.c_uint32,
                   ctypes.POINTER(MIB_IPFORWARDROW))
    fn.restype = ctypes.c_uint32
    row = MIB_IPFORWARDROW()
    # Source=0 selects the OS default best route; pinning a source could
    # change route selection and produce misleading "good" evidence.
    status = fn(_ip_to_dword(destination), 0, ctypes.byref(row))
    if type(status) is not int or status != 0:
        raise OSError('GetBestRoute failed')
    return _row_to_route(row)


def probe_route(destination: str, expected_gateway: str, expected_if_index: int,
                *, loader: Callable | None = None) -> RouteEvidence:
    """Explicit, read-only route lookup; fail UNKNOWN on any API failure.

    This prototype MUST NOT be called in protected release until source
    attestation and native low-integrity acceptance are separately approved.
    """
    try:
        if type(destination) is not str or type(expected_gateway) is not str:
            raise ValueError('IPv4 strings required')
        IPv4Address(destination)
        IPv4Address(expected_gateway)
        if type(expected_if_index) is not int or not 1 <= expected_if_index <= 0xFFFFFFFF:
            raise ValueError('invalid interface index')
        route = _get_best_route(destination, loader=loader)
    except (ValueError, TypeError, OSError, AttributeError):
        return RouteEvidence('Unavailable', 'NativeRouteQueryUnavailable')
    return evaluate_route(route, destination=destination,
                          expected_gateway=expected_gateway,
                          expected_if_index=expected_if_index)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-inert', required=True, action='store_true')
    parser.parse_args(argv)
    print(json.dumps({'schema_version': 1, 'phase': 'native-route-prototype',
                      'native_api_invoked': False, 'live_cli_enabled': False,
                      'release_integrated': False, 'status': 'DEVELOPMENT_HOLD'},
                     sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
