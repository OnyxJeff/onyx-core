#!/usr/bin/env python3
"""ONYX CORE v0.8.0 J1: real Windows Credential Manager user-consent primitive.

This is a Windows user-scoped enrollment store, NOT an independent signer or
OS source attestor. Generic credentials are writable by same-user processes.
The module is inert on import and CLI; no monitoring is launchable from it.
Issuing/deleting a grant requires a separate explicitly authorized API call.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
import re
from typing import Callable

TARGET = 'OnyxJeff/ONYX_CORE/v0.8.0/ReadOnlyMonitoring'
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
MAX_BLOB = 2048
GRANT_FIELDS = frozenset({
    'schema_version', 'grant_id', 'sid', 'source_commit', 'config_sha256',
    'scope', 'issued_utc', 'expires_utc', 'read_only', 'repair_action',
    'storage_profile', 'session_policy', 'notifications_enabled'
})
SID_RE = re.compile(r'S-1-5-21-(?:[0-9]{1,10}-){3}[0-9]{1,10}\Z')
SHA_RE = re.compile(r'[0-9a-f]{64}\Z')
COMMIT_RE = re.compile(r'[0-9a-f]{40}\Z')
GRANT_RE = re.compile(r'[a-f0-9]{32}\Z')
UTC_RE = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z')


class ConsentRefused(RuntimeError):
    """No trustworthy permission was demonstrated in the chosen user scope."""


class FILETIME(ctypes.Structure):
    _fields_ = [('dwLowDateTime', wintypes.DWORD), ('dwHighDateTime', wintypes.DWORD)]


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
        ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
        ('LastWritten', FILETIME), ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.c_void_p), ('Persist', wintypes.DWORD),
        ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR),
    ]


def _windows_api():
    if os.name != 'nt':
        raise ConsentRefused('Windows credential store is unavailable')
    dll = ctypes.WinDLL('advapi32', use_last_error=True)
    dll.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
    dll.CredReadW.restype = wintypes.BOOL
    dll.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
    dll.CredWriteW.restype = wintypes.BOOL
    dll.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    dll.CredDeleteW.restype = wintypes.BOOL
    dll.CredFree.argtypes = [ctypes.c_void_p]
    dll.CredFree.restype = None
    return dll


def read_windows_grant() -> bytes:
    """Read a pinned generic credential; never log or disclose its contents."""
    dll = _windows_api()
    pointer = ctypes.POINTER(CREDENTIALW)()
    if not dll.CredReadW(TARGET, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        raise ConsentRefused('operator enrollment unavailable')
    try:
        value = pointer.contents
        if (value.Type != CRED_TYPE_GENERIC or value.Persist != CRED_PERSIST_LOCAL_MACHINE
                or not value.TargetName or value.TargetName.casefold() != TARGET.casefold()
                or not (1 <= value.CredentialBlobSize <= MAX_BLOB) or not value.CredentialBlob):
            raise ConsentRefused('operator enrollment attributes invalid')
        return ctypes.string_at(value.CredentialBlob, value.CredentialBlobSize)
    finally:
        dll.CredFree(ctypes.cast(pointer, ctypes.c_void_p))


def write_windows_grant(grant_bytes: bytes) -> None:
    """Explicit operator-only API; NOT called on import or from CLI/tests."""
    _windows_api()  # platform refusal before anything else
    _parse(grant_bytes)  # refuse malformed consent before any persistent write
    content = ctypes.create_string_buffer(grant_bytes)
    credential = CREDENTIALW()
    credential.Type = CRED_TYPE_GENERIC
    credential.TargetName = TARGET
    credential.Persist = CRED_PERSIST_LOCAL_MACHINE
    credential.CredentialBlobSize = len(grant_bytes)
    credential.CredentialBlob = ctypes.cast(content, ctypes.c_void_p)
    dll = _windows_api()
    if not dll.CredWriteW(ctypes.byref(credential), 0):
        raise ConsentRefused('Windows could not store operator grant')


def delete_windows_grant() -> None:
    """Explicit operator-only revoke API; absence of credential also means deny."""
    dll = _windows_api()
    if not dll.CredDeleteW(TARGET, CRED_TYPE_GENERIC, 0):
        if ctypes.get_last_error() != ERROR_NOT_FOUND:
            raise ConsentRefused('Windows could not revoke operator grant')


def _no_duplicates(pairs):
    obj = {}
    for key, val in pairs:
        if key in obj:
            raise ConsentRefused('duplicate enrollment field')
        obj[key] = val
    return obj


def _parse(data: bytes) -> dict:
    if type(data) is not bytes or not 1 <= len(data) <= MAX_BLOB:
        raise ConsentRefused('invalid enrollment length')
    try:
        doc = json.loads(data.decode('utf-8', 'strict'), object_pairs_hook=_no_duplicates,
                         parse_constant=lambda _: (_ for _ in ()).throw(ConsentRefused('nonfinite')))
        if type(doc) is not dict or set(doc) != GRANT_FIELDS:
            raise ConsentRefused('enrollment schema mismatch')
        canonical = json.dumps(doc, sort_keys=True, separators=(',', ':'),
                               ensure_ascii=True, allow_nan=False).encode('ascii')
    except (UnicodeError, ValueError, TypeError, OverflowError) as exc:
        raise ConsentRefused('invalid enrollment encoding') from exc
    if canonical != data:
        raise ConsentRefused('enrollment is not canonical')
    return doc


def _utc(value):
    if type(value) is not str or UTC_RE.fullmatch(value) is None:
        raise ConsentRefused('invalid enrollment UTC timestamp')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ConsentRefused('invalid enrollment UTC timestamp') from exc


@dataclass(frozen=True)
class VerifiedContext:
    """External OS/source attestations; caller must NOT supply synthetic evidence in live use."""
    process_sid: str
    source_commit: str
    config_sha256: str
    source_trusted: bool
    active_user_session: bool


def evaluate_grant(raw: bytes, *, context: VerifiedContext, now: datetime) -> bool:
    """Strict fail-closed grant check. No underlying OS privilege is asserted."""
    g = _parse(raw)
    if not isinstance(context, VerifiedContext):
        raise ConsentRefused('missing Windows/source evidence')
    if (type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None
            or context.source_trusted is not True or context.active_user_session is not True):
        raise ConsentRefused('untrusted session, source, or UTC clock')
    if (type(g['schema_version']) is not int or g['schema_version'] != 1
            or type(g['grant_id']) is not str or not GRANT_RE.fullmatch(g['grant_id'])
            or type(g['sid']) is not str or not SID_RE.fullmatch(g['sid'])
            or type(g['source_commit']) is not str or not COMMIT_RE.fullmatch(g['source_commit'])
            or type(g['config_sha256']) is not str or not SHA_RE.fullmatch(g['config_sha256'])):
        raise ConsentRefused('grant identity or provenance invalid')
    if (g['scope'] != 'periodic_read_only_usb_ics'
            or g['read_only'] is not True or g['repair_action'] != 'None'
            or g['storage_profile'] != 'release'
            or g['session_policy'] != 'LoggedOnUserOnly'
            or g['notifications_enabled'] is not False):
        raise ConsentRefused('grant requests unsafe operation')
    start, end = _utc(g['issued_utc']), _utc(g['expires_utc'])
    if not (start <= now.astimezone(timezone.utc) < end
            and timedelta(seconds=1) <= end - start <= timedelta(days=7)):
        raise ConsentRefused('grant expired, premature, or unbounded')
    if (context.process_sid != g['sid'] or context.source_commit != g['source_commit']
            or context.config_sha256 != g['config_sha256']):
        raise ConsentRefused('identity/source/config mismatch')
    return True


def make_reader_authorizer(*, get_context: Callable[[], VerifiedContext],
                           now: Callable[[], datetime],
                           read: Callable[[], bytes] = read_windows_grant) -> Callable[[], bool]:
    """Per-cycle hook for Phase 18I1 bridge; real OS attestor still required.

    A caller-injected context provider is NOT itself trustworthy. The future
    production launcher must own and pin a native source/session attestor.
    """
    if not all(callable(x) for x in (get_context, now, read)):
        raise ConsentRefused('missing trusted enrollment adapters')
    def authorize():
        return evaluate_grant(read(), context=get_context(), now=now())
    return authorize


def inert_status():
    return {
        'phase': '18J1', 'credential_backend': 'Windows Generic Credential',
        'live_runtime_enabled': False, 'source_attestation_integrated': False,
        'independent_signing_authority': False,
        'user_scoped_grant_reader_present': True,
        'auto_enrollment': False, 'auto_revoke': False,
        'task_creation': False, 'release_status': 'HOLD',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-inert', required=True, action='store_true')
    parser.parse_args(argv)
    print(json.dumps(inert_status(), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
