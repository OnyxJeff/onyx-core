#!/usr/bin/env python3
"""ONYX CORE v0.8.0: inert native Windows adapter alias/index evidence.

Development-only; no live CLI, source trust, protected release integration,
network activity, journal writes, scheduling, notifications or repairs.
Only explicit resolve_adapter() loads iphlpapi.dll, and only on Windows unless
an injected test loader is supplied. The result by itself does NOT establish
that the ICS IPv4 address is present/preferred or that the route is correct.
"""
from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import json
import os
import re
from typing import Callable

_ALIAS = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}\Z')
_CLASSES = frozenset({'Resolved', 'Unavailable'})
# Windows NET_LUID union is eight bytes. NET_IFINDEX and NETIO_STATUS are DWORDs.
LUID = ctypes.c_uint64
IFINDEX = ctypes.c_uint32
NETSTATUS = ctypes.c_uint32
_ALIAS_BUFFER_CHARS = 512


@dataclass(frozen=True)
class AdapterIdentity:
    classification: str
    reason: str
    interface_index: int | None = None

    def __post_init__(self):
        if self.classification not in _CLASSES:
            raise ValueError('invalid classification')
        if self.classification == 'Resolved':
            if (type(self.interface_index) is not int or
                    not 1 <= self.interface_index < 0xFFFFFFFF):
                raise ValueError('invalid resolved interface index')
        elif self.interface_index is not None:
            raise ValueError('unavailable evidence must not include index')


def _normalize_alias(value: str) -> str:
    if type(value) is not str or not _ALIAS.fullmatch(value):
        raise ValueError('invalid adapter alias')
    return value


def _lookup_alias(alias: str, *, loader: Callable | None = None) -> int:
    """Explicit native query: three checked DLL calls, no network traffic.

    ConvertInterfaceAliasToLuid -> ConvertInterfaceLuidToIndex ->
    ConvertInterfaceLuidToAlias (identity round trip). Return index or raise.
    Injection exists ONLY for deterministic offline API tests.
    """
    alias = _normalize_alias(alias)
    if ctypes.sizeof(LUID) != 8 or ctypes.sizeof(IFINDEX) != 4:
        raise ValueError('unsupported native interface ABI')
    if loader is None:
        if os.name != 'nt':
            raise OSError('Windows required')
        # Never resolve DLL dependencies from a user-writable search directory.
        loader = lambda name: ctypes.WinDLL(name, winmode=0x00000800)  # LOAD_LIBRARY_SEARCH_SYSTEM32
    dll = loader('iphlpapi.dll')

    to_luid = dll.ConvertInterfaceAliasToLuid
    to_luid.argtypes = (ctypes.c_wchar_p, ctypes.POINTER(LUID))
    to_luid.restype = NETSTATUS

    to_index = dll.ConvertInterfaceLuidToIndex
    to_index.argtypes = (ctypes.POINTER(LUID), ctypes.POINTER(IFINDEX))
    to_index.restype = NETSTATUS

    to_alias = dll.ConvertInterfaceLuidToAlias
    to_alias.argtypes = (ctypes.POINTER(LUID), ctypes.POINTER(ctypes.c_wchar), ctypes.c_size_t)
    to_alias.restype = NETSTATUS

    luid = LUID(0)
    if to_luid(alias, ctypes.byref(luid)) != 0 or luid.value == 0:
        raise OSError('adapter alias lookup failed')
    index = IFINDEX(0)
    if to_index(ctypes.byref(luid), ctypes.byref(index)) != 0:
        raise OSError('adapter index lookup failed')
    if not 1 <= index.value < 0xFFFFFFFF:
        raise ValueError('invalid Windows adapter index')
    verified_alias = ctypes.create_unicode_buffer(_ALIAS_BUFFER_CHARS)
    if to_alias(ctypes.byref(luid), verified_alias, _ALIAS_BUFFER_CHARS) != 0:
        raise OSError('adapter reverse alias lookup failed')
    if verified_alias.value.casefold() != alias.casefold():
        raise ValueError('adapter alias changed during lookup')
    return int(index.value)


def resolve_adapter(alias: str, *, loader: Callable | None = None) -> AdapterIdentity:
    """Read-only, fail-closed alias-to-interface-index resolution.

    An index is only usable for *subsequent* fresh address and route evidence.
    Never infer healthy connectivity from this result alone.
    """
    try:
        index = _lookup_alias(alias, loader=loader)
    except (ValueError, TypeError, OSError, AttributeError, OverflowError):
        return AdapterIdentity('Unavailable', 'AdapterIdentityUnavailable')
    return AdapterIdentity('Resolved', 'AdapterAliasIndexVerified', index)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-inert', required=True, action='store_true')
    parser.parse_args(argv)
    print(json.dumps({'schema_version': 1, 'phase': 'native-adapter-identity',
                      'native_api_invoked': False, 'live_cli_enabled': False,
                      'release_integrated': False, 'gateway_address_verified': False,
                      'status': 'DEVELOPMENT_HOLD'}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
