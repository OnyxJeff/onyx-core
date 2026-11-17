#!/usr/bin/env python3
"""ONYX CORE v0.8.0 inert Windows IPv4 gateway address evidence prototype.

Development-only. No protected-release binding, live CLI, persistent state,
PowerShell, SSH, network traffic, tasks, notifications, or repairs. Import and
--check-inert are inert. Only explicitly calling verify_gateway_address()
can query Windows GetUnicastIpAddressEntry; even a Preferred result is *not*
proof that the interface is up, the selected route is correct, or ICS forwards.

An expected interface index must be obtained from a fresh, separately verified
adapter alias/LUID lookup. No address/route is inferred from a hardcoded index.
"""
from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
import json
import os
import sys
from typing import Callable

AF_INET = 2
IP_DAD_STATE_PREFERRED = 4
LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x00000800


class SOCKADDR_IN(ctypes.Structure):
    _fields_ = [
        ('sin_family', ctypes.c_uint16),
        ('sin_port', ctypes.c_uint16),
        ('sin_addr', ctypes.c_uint8 * 4),
        ('sin_zero', ctypes.c_uint8 * 8),
    ]


class SOCKADDR_IN6(ctypes.Structure):
    _fields_ = [
        ('sin6_family', ctypes.c_uint16),
        ('sin6_port', ctypes.c_uint16),
        ('sin6_flowinfo', ctypes.c_uint32),
        ('sin6_addr', ctypes.c_uint8 * 16),
        ('sin6_scope_id', ctypes.c_uint32),
    ]


class SOCKADDR_INET(ctypes.Union):
    _fields_ = [
        ('Ipv4', SOCKADDR_IN),
        ('Ipv6', SOCKADDR_IN6),
        ('si_family', ctypes.c_uint16),
    ]


class MIB_UNICASTIPADDRESS_ROW(ctypes.Structure):
    _fields_ = [
        ('Address', SOCKADDR_INET),
        ('InterfaceLuid', ctypes.c_uint64),
        ('InterfaceIndex', ctypes.c_uint32),
        ('PrefixOrigin', ctypes.c_uint32),
        ('SuffixOrigin', ctypes.c_uint32),
        ('ValidLifetime', ctypes.c_uint32),
        ('PreferredLifetime', ctypes.c_uint32),
        ('OnLinkPrefixLength', ctypes.c_uint8),
        ('SkipAsSource', ctypes.c_uint8),
        ('DadState', ctypes.c_uint32),
        ('ScopeId', ctypes.c_uint32),
        ('CreationTimeStamp', ctypes.c_int64),
    ]


@dataclass(frozen=True)
class GatewayAddressEvidence:
    classification: str
    reason: str
    interface_index: int | None = None

    def __post_init__(self):
        if self.classification not in ('Preferred', 'NotPreferred', 'Unavailable'):
            raise ValueError('invalid gateway evidence class')
        if self.classification == 'Preferred':
            if (type(self.interface_index) is not int or
                    not 1 <= self.interface_index < 0xFFFFFFFF):
                raise ValueError('preferred gateway requires valid interface index')
        elif self.interface_index is not None:
            raise ValueError('failed gateway evidence must not carry interface index')


def _check_abi() -> None:
    """Refuse unreviewed Python/Windows ABI layouts before native invocation."""
    fields = {
        'Address': 0, 'InterfaceLuid': 32, 'InterfaceIndex': 40,
        'OnLinkPrefixLength': 60, 'SkipAsSource': 61,
        'DadState': 64, 'CreationTimeStamp': 72,
    }
    if (sys.byteorder != 'little' or ctypes.sizeof(SOCKADDR_IN) != 16 or
            ctypes.sizeof(SOCKADDR_IN6) != 28 or
            ctypes.sizeof(SOCKADDR_INET) != 28 or
            ctypes.sizeof(MIB_UNICASTIPADDRESS_ROW) != 80 or
            any(getattr(MIB_UNICASTIPADDRESS_ROW, name).offset != offset
                for name, offset in fields.items())):
        raise ValueError('unsupported Windows MIB_UNICASTIPADDRESS_ROW ABI')


def _checked_input(value: str) -> IPv4Address:
    if type(value) is not str:
        raise ValueError('IPv4 string required')
    result = IPv4Address(value)
    if (result.is_multicast or result.is_unspecified or result.is_loopback or
            int(result) == 0xFFFFFFFF):
        raise ValueError('invalid gateway or receiver address')
    return result


def _row_for_input(gateway: IPv4Address, if_index: int) -> MIB_UNICASTIPADDRESS_ROW:
    row = MIB_UNICASTIPADDRESS_ROW()
    row.Address.Ipv4.sin_family = AF_INET
    row.Address.Ipv4.sin_addr[:] = gateway.packed
    row.InterfaceIndex = if_index
    return row


def _lookup_gateway(gateway: IPv4Address, if_index: int, *,
                    loader: Callable | None = None, api: Callable | None = None
                    ) -> MIB_UNICASTIPADDRESS_ROW:
    """One read-only GetUnicastIpAddressEntry call; no enumeration or caching."""
    _check_abi()
    if api is None:
        if loader is None:
            if os.name != 'nt':
                raise OSError('Windows required')
            loader = lambda name: ctypes.WinDLL(
                name, winmode=LOAD_LIBRARY_SEARCH_SYSTEM32)
        dll = loader('iphlpapi.dll')
        api = dll.GetUnicastIpAddressEntry
    api.argtypes = (ctypes.POINTER(MIB_UNICASTIPADDRESS_ROW),)
    api.restype = ctypes.c_uint32
    row = _row_for_input(gateway, if_index)
    if api(ctypes.byref(row)) != 0:
        raise OSError('native gateway address query unavailable')
    return row


def _evaluate(row: MIB_UNICASTIPADDRESS_ROW, *, gateway: IPv4Address,
              receiver: IPv4Address, if_index: int) -> GatewayAddressEvidence:
    """Pure conservative evaluation: positive evidence only, never infer Healthy."""
    try:
        if (int(row.Address.si_family) != AF_INET or
                bytes(row.Address.Ipv4.sin_addr) != gateway.packed or
                int(row.InterfaceIndex) != if_index or
                not int(row.InterfaceLuid)):
            raise ValueError('incoherent native gateway identity')
        prefix = int(row.OnLinkPrefixLength)
        if not 1 <= prefix <= 32:
            raise ValueError('invalid gateway prefix')
        subnet = IPv4Network((gateway, prefix), strict=False)
        if receiver not in subnet or receiver == gateway:
            raise ValueError('receiver not in gateway subnet')
        if int(row.SkipAsSource) not in (0, 1):
            raise ValueError('invalid SkipAsSource field')
        if int(row.DadState) not in range(5):
            raise ValueError('invalid DAD state')
        if (int(row.ValidLifetime) == 0 or int(row.PreferredLifetime) == 0 or
                int(row.PreferredLifetime) > int(row.ValidLifetime)):
            raise ValueError('invalid gateway lifetimes')
    except (ValueError, TypeError, AttributeError):
        return GatewayAddressEvidence('Unavailable', 'GatewayEvidenceInvalid')
    if (int(row.DadState) != IP_DAD_STATE_PREFERRED or
            int(row.SkipAsSource) != 0):
        return GatewayAddressEvidence('NotPreferred', 'GatewayNotPreferred')
    return GatewayAddressEvidence('Preferred', 'GatewayIpv4Preferred', if_index)


def verify_gateway_address(gateway: str, receiver: str, expected_if_index: int,
                           *, loader: Callable | None = None,
                           api: Callable | None = None) -> GatewayAddressEvidence:
    """Explicit read-only IPv4 evidence query; fail closed for missing data."""
    try:
        addr = _checked_input(gateway)
        remote = _checked_input(receiver)
        if (type(expected_if_index) is not int or
                not 1 <= expected_if_index < 0xFFFFFFFF or addr == remote):
            raise ValueError('invalid interface or address input')
        row = _lookup_gateway(addr, expected_if_index, loader=loader, api=api)
        return _evaluate(row, gateway=addr, receiver=remote,
                         if_index=expected_if_index)
    except (ValueError, TypeError, OSError, AttributeError, OverflowError):
        return GatewayAddressEvidence('Unavailable', 'GatewayAddressUnavailable')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-inert', required=True, action='store_true')
    parser.parse_args(argv)
    print(json.dumps({'schema_version': 1, 'phase': 'native-gateway-address',
                      'native_api_invoked': False, 'live_cli_enabled': False,
                      'release_integrated': False,
                      'low_integrity_validated': False,
                      'status': 'DEVELOPMENT_HOLD'}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
