#!/usr/bin/env python3
"""ONYX CORE v0.8.0 Phase 18G1: detached Windows token/SID + mutex primitives.

NOT an enrollment validator or monitor launcher. No live probes, tasks, network,
SQLite, persistent state or process creation. Native calls require an explicit
function invocation; importing this module is inert. CLI supports --check-inert
only, which makes no Windows API calls. Not integrated with M1/M2/M3.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import re
from typing import Callable, ContextManager, Iterator


class NativeAdmissionRefused(RuntimeError):
    """Denied without exposing Windows identity or object details."""


# Machine-wide mutex name (not Local\, which would permit parallel sessions).
MUTEX_NAME = r'Global\OnyxCoreV080ReleaseIncidentRecorder'
ERROR_ALREADY_EXISTS = 183
ERROR_INSUFFICIENT_BUFFER = 122
TOKEN_QUERY = 0x0008
TOKEN_USER = 1


def validate_sid(sid: str) -> str:
    """Reject malformed identifiers before interpolating any SID into SDDL."""
    if type(sid) is not str or len(sid) > 184:
        raise NativeAdmissionRefused('invalid authorized SID')
    # Canonical decimal Windows SID; validator does not establish its provenance.
    if not re.fullmatch(r'S-1-(?:[0-9]{1,10}-){1,14}[0-9]{1,10}', sid):
        raise NativeAdmissionRefused('invalid authorized SID')
    return sid


def protected_sddl(sid: str) -> str:
    """Protected DACL for SYSTEM and the explicitly approved process user."""
    return 'D:P(A;;GA;;;SY)(A;;GA;;;{})'.format(validate_sid(sid))


def current_process_sid() -> str:
    """Read the Windows *process token* user SID; no external command or network.

    A matching SID alone is not enrollment, session activity, ACL/source trust,
    process ancestry, or signed grant verification.
    """
    if os.name != 'nt':
        raise NativeAdmissionRefused('native identity inspection requires Windows')
    import ctypes
    from ctypes import wintypes

    k = ctypes.WinDLL('kernel32', use_last_error=True)
    a = ctypes.WinDLL('advapi32', use_last_error=True)
    handle_type = ctypes.c_void_p
    k.GetCurrentProcess.argtypes = []
    k.GetCurrentProcess.restype = handle_type
    k.CloseHandle.argtypes = [handle_type]
    k.CloseHandle.restype = wintypes.BOOL
    k.LocalFree.argtypes = [handle_type]
    k.LocalFree.restype = handle_type
    a.OpenProcessToken.argtypes = [handle_type, wintypes.DWORD, ctypes.POINTER(handle_type)]
    a.OpenProcessToken.restype = wintypes.BOOL
    a.GetTokenInformation.argtypes = [handle_type, ctypes.c_int, ctypes.c_void_p,
                                      wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    a.GetTokenInformation.restype = wintypes.BOOL
    a.ConvertSidToStringSidW.argtypes = [handle_type, ctypes.POINTER(handle_type)]
    a.ConvertSidToStringSidW.restype = wintypes.BOOL

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [('Sid', handle_type), ('Attributes', wintypes.DWORD)]

    token = handle_type()
    if not a.OpenProcessToken(k.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
        raise NativeAdmissionRefused('cannot read Windows process token')
    try:
        size = wintypes.DWORD(0)
        ctypes.set_last_error(0)
        a.GetTokenInformation(token, TOKEN_USER, None, 0, ctypes.byref(size))
        if ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER or not 16 <= size.value <= 65536:
            raise NativeAdmissionRefused('cannot size Windows token data')
        data = ctypes.create_string_buffer(size.value)
        if not a.GetTokenInformation(token, TOKEN_USER, data, size, ctypes.byref(size)):
            raise NativeAdmissionRefused('cannot inspect Windows token user')
        user = ctypes.cast(data, ctypes.POINTER(SidAndAttributes)).contents
        if not user.Sid:
            raise NativeAdmissionRefused('Windows token lacks user SID')
        sid_string = handle_type()
        if not a.ConvertSidToStringSidW(user.Sid, ctypes.byref(sid_string)):
            raise NativeAdmissionRefused('cannot convert Windows token SID')
        try:
            return validate_sid(ctypes.wstring_at(sid_string.value))
        finally:
            k.LocalFree(sid_string)
    finally:
        k.CloseHandle(token)


@contextmanager
def _secure_global_mutex(sid: str) -> Iterator[None]:
    """Create, initially own, and release a cross-session Windows mutex.

    Refuse an existing object regardless of its owner/ACL; never open it for
    running. A pre-created object can prevent startup (DoS), not grant access.
    """
    if os.name != 'nt':
        raise NativeAdmissionRefused('global mutex requires Windows')
    import ctypes
    from ctypes import wintypes

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [('nLength', wintypes.DWORD),
                    ('lpSecurityDescriptor', ctypes.c_void_p),
                    ('bInheritHandle', wintypes.BOOL)]

    k = ctypes.WinDLL('kernel32', use_last_error=True)
    a = ctypes.WinDLL('advapi32', use_last_error=True)
    k.LocalFree.argtypes = [ctypes.c_void_p]
    k.LocalFree.restype = ctypes.c_void_p
    k.CreateMutexW.argtypes = [ctypes.POINTER(SecurityAttributes), wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateMutexW.restype = ctypes.c_void_p
    k.ReleaseMutex.argtypes = [ctypes.c_void_p]
    k.ReleaseMutex.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    k.CloseHandle.restype = wintypes.BOOL
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL

    descriptor = ctypes.c_void_p()
    if not a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            protected_sddl(sid), 1, ctypes.byref(descriptor), None):
        raise NativeAdmissionRefused('cannot construct protected mutex ACL')
    try:
        attrs = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
        ctypes.set_last_error(0)
        handle = k.CreateMutexW(ctypes.byref(attrs), True, MUTEX_NAME)
        error = ctypes.get_last_error()
        if not handle:
            raise NativeAdmissionRefused('cannot establish protected global mutex')
        if error == ERROR_ALREADY_EXISTS:
            k.CloseHandle(handle)
            raise NativeAdmissionRefused('another recorder or reserved mutex already exists')
        try:
            yield
        finally:
            # Release on the same thread that acquired ownership.
            released = bool(k.ReleaseMutex(handle))
            k.CloseHandle(handle)
            if not released:
                raise NativeAdmissionRefused('cannot release protected global mutex')
    finally:
        k.LocalFree(descriptor)


@contextmanager
def verified_sid_mutex(
        expected_sid: str,
        *,
        sid_reader: Callable[[], str] = current_process_sid,
        mutex_factory: Callable[[str], ContextManager[None]] = _secure_global_mutex,
) -> Iterator[None]:
    """Compare against a SID obtained from an EXTERNAL trust anchor, then lock.

    This function does NOT validate that the supplied expected_sid came from a
    trusted grant: never use an argument, environment value or user-writable
    file as the authorization source in future production integration.
    """
    expected_sid = validate_sid(expected_sid)
    if not callable(sid_reader) or not callable(mutex_factory):
        raise NativeAdmissionRefused('native admission adapter unavailable')
    actual_sid = validate_sid(sid_reader())
    if actual_sid != expected_sid:
        raise NativeAdmissionRefused('Windows process identity mismatch')
    with mutex_factory(actual_sid):
        yield


def inert_status() -> dict:
    return {
        'phase': '18G1', 'module_import_inert': True,
        'native_adapter_present': True, 'native_adapter_invoked': False,
        'trusted_enrollment_implemented': False,
        'live_runtime_enabled': False, 'scheduled_task_created': False,
        'incident_history_written': False, 'notifications_enabled': False,
        'release_status': 'HOLD',
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-inert', action='store_true', required=True)
    parser.parse_args(argv)
    print(json.dumps(inert_status(), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
