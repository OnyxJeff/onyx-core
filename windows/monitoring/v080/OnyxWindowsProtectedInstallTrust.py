#!/usr/bin/env python3
"""Fail-closed Win32 *handle-backed* owner/DACL/reparse check for ONYX v0.8.

Checks an open filesystem object (not an untrusted icacls string), rejecting
non-privileged write ACEs or non-administrator owners. This is a narrow
single-console-user threat model; it does not defend against elevated admins,
DLL injection by elevated code or every Windows ACL inheritance edge case.
No mutation, imports with OS effects, probes or credential access.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import ntpath
import os
from pathlib import Path
import re


class InstallTrustRefused(RuntimeError):
    pass


# SYSTEM, BUILTIN\\Administrators, Windows Modules Installer service.
PRIVILEGED_SIDS = frozenset({
    'S-1-5-18', 'S-1-5-32-544',
    'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464',
})
# FILE_WRITE_DATA, APPEND_DATA, WRITE_EA, DELETE_CHILD,
# WRITE_ATTRIBUTES, DELETE, WRITE_DAC, WRITE_OWNER, GENERIC_WRITE/ALL.
WRITE_MASK = (0x2 | 0x4 | 0x10 | 0x40 | 0x100 | 0x10000 |
              0x40000 | 0x80000 | 0x40000000 | 0x10000000)
ANCHOR = Path(r'C:\Program Files\OnyxCore\v0.8.0-release.sha256')
ROOT = Path(r'C:\Program Files\OnyxCore\v0.8.0')
PYTHON = Path(r'C:\Python313\python.exe')


# An inherit-only ACE grants no access to the *current* object. The inherited
# ACE may become effective on a child, which assert_trusted_install separately
# opens and checks. Do not confuse generic-all on CREATOR OWNER with effective
# write permission on Program Files itself.
INHERIT_ONLY_ACE = 0x08
INHERIT_TARGET_FLAGS = 0x01 | 0x02
KNOWN_DACL_ACE_FLAGS = 0x1F  # OI | CI | NO_PROPAGATE | INHERIT_ONLY | INHERITED


def reject_ace(owner_sid: str, aces: tuple[tuple, ...]) -> None:
    """Reject effective nonprivileged writes; inspect inheritance-only safely.

    Native rules contain (type, SID, mask, flags). Legacy three-field injected
    rules are supported with flags=0 solely for existing pure-test callers;
    the native handle-backed reader always supplies the fourth field.
    """
    if owner_sid not in PRIVILEGED_SIDS:
        raise InstallTrustRefused('trusted file owner is not privileged')
    if not aces:
        raise InstallTrustRefused('trusted file DACL has no inspectable rules')
    for rule in aces:
        if not isinstance(rule, tuple) or len(rule) not in (3, 4):
            raise InstallTrustRefused('malformed trusted ACL entry')
        kind, sid, mask = rule[:3]
        flags = rule[3] if len(rule) == 4 else 0
        if (type(kind) is not int or kind not in (0, 1)
                or not isinstance(sid, str) or not sid
                or type(mask) is not int or mask < 0 or mask > 0xffffffff
                or type(flags) is not int or flags < 0 or flags > 0xff
                or flags & ~KNOWN_DACL_ACE_FLAGS):
            raise InstallTrustRefused('unsupported ACL entry')
        if flags & INHERIT_ONLY_ACE:
            # A valid inherit-only ACE must specify an object or container
            # inheritance target. Ignore its access mask ONLY on this object.
            if not (flags & INHERIT_TARGET_FLAGS):
                raise InstallTrustRefused('invalid inherit-only ACL entry')
            continue
        if kind == 0 and sid not in PRIVILEGED_SIDS and mask & WRITE_MASK:
            raise InstallTrustRefused('nonprivileged write permission in trusted path')


def _decode_basic_ace_header(header: bytes) -> tuple[int, int, int]:
    """Return (ACE type, access mask, ACE flags) from an 8-byte native header."""
    if not isinstance(header, bytes) or len(header) != 8:
        raise InstallTrustRefused('invalid trusted ACL header')
    kind = header[0]
    flags = header[1]
    size = int.from_bytes(header[2:4], 'little')
    mask = int.from_bytes(header[4:8], 'little')
    if size < 12 or size > 65535 or kind not in (0, 1):
        raise InstallTrustRefused('unsupported ACL entry format')
    return kind, mask, flags


def _handle_acl(path: Path):
    """Return (owner SID, tuple(type,SID,mask,flags)) from native handles."""
    if os.name != 'nt':
        raise InstallTrustRefused('Windows handle security required')
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    a = ctypes.WinDLL('advapi32', use_last_error=True)
    INVALID_HANDLE = ctypes.c_void_p(-1).value
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    k.CreateFileW.restype = ctypes.c_void_p
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    k.CloseHandle.restype = wintypes.BOOL
    k.LocalFree.argtypes = [ctypes.c_void_p]
    k.LocalFree.restype = ctypes.c_void_p

    class FileTime(ctypes.Structure):
        _fields_ = [('low',wintypes.DWORD),('high',wintypes.DWORD)]

    class FileInfo(ctypes.Structure):
        _fields_ = [('attributes',wintypes.DWORD),('created',FileTime),('accessed',FileTime),
                    ('written',FileTime),('volume',wintypes.DWORD),('sizehi',wintypes.DWORD),
                    ('sizelo',wintypes.DWORD),('links',wintypes.DWORD),
                    ('indexhi',wintypes.DWORD),('indexlo',wintypes.DWORD)]

    k.GetFileInformationByHandle.argtypes = [ctypes.c_void_p, ctypes.POINTER(FileInfo)]
    k.GetFileInformationByHandle.restype = wintypes.BOOL
    a.GetSecurityInfo.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                  ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                  ctypes.POINTER(ctypes.c_void_p)]
    a.GetSecurityInfo.restype = wintypes.DWORD
    a.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    a.GetAce.restype = wintypes.BOOL
    a.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    a.ConvertSidToStringSidW.restype = wintypes.BOOL

    def sid_string(pointer):
        output = ctypes.c_void_p()
        if not pointer or not a.ConvertSidToStringSidW(pointer, ctypes.byref(output)):
            raise InstallTrustRefused('Windows SID inspection failed')
        try:
            return ctypes.wstring_at(output.value)
        finally:
            k.LocalFree(output)

    # Open reparse point *itself*, not its destination; directories require backup semantics.
    handle = k.CreateFileW(str(path), 0x00020000, 0x1 | 0x2 | 0x4, None, 3,
                           0x02000000 | 0x00200000, None)
    if not handle or handle == INVALID_HANDLE:
        raise InstallTrustRefused('cannot open trusted file handle')
    try:
        info = FileInfo()
        if not k.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise InstallTrustRefused('cannot inspect trusted file handle')
        if info.attributes & 0x00000400:
            raise InstallTrustRefused('redirected path forbidden')
        owner = ctypes.c_void_p()
        dacl = ctypes.c_void_p()
        descriptor = ctypes.c_void_p()
        rc = a.GetSecurityInfo(handle, 1, 0x1 | 0x4, ctypes.byref(owner), None,
                               ctypes.byref(dacl), None, ctypes.byref(descriptor))
        if rc != 0 or not descriptor or not dacl or not owner:
            raise InstallTrustRefused('protected file ACL unavailable')
        try:
            class ACL(ctypes.Structure):
                _fields_ = [('revision',ctypes.c_ubyte),('pad',ctypes.c_ubyte),
                            ('size',wintypes.WORD),('ace_count',wintypes.WORD),
                            ('pad2',wintypes.WORD)]
            acl = ctypes.cast(dacl, ctypes.POINTER(ACL)).contents
            if acl.ace_count > 1024:
                raise InstallTrustRefused('oversized trusted DACL')
            aces = []
            for i in range(acl.ace_count):
                pointer = ctypes.c_void_p()
                if not a.GetAce(dacl, i, ctypes.byref(pointer)):
                    raise InstallTrustRefused('cannot inspect trusted ACL entry')
                # ACCESS_ALLOWED_ACE and ACCESS_DENIED_ACE layouts:
                # [type:BYTE flags:BYTE size:WORD mask:DWORD sid:...]
                header = ctypes.string_at(pointer.value, 8)
                kind, mask, flags = _decode_basic_ace_header(header)
                aces.append((kind, sid_string(pointer.value + 8), mask, flags))
            return sid_string(owner), tuple(aces)
        finally:
            k.LocalFree(descriptor)
    finally:
        k.CloseHandle(handle)


def assert_protected_path(path: Path, *, read_acl=_handle_acl):
    if (not isinstance(path, Path) or not (path.is_absolute() or ntpath.isabs(str(path)))
            or not callable(read_acl)):
        raise InstallTrustRefused('absolute trusted source path required')
    # Strictly avoid arbitrary or relative path spellings.
    if '..' in path.parts or str(path).startswith('\\\\'):
        raise InstallTrustRefused('invalid source path')
    owner, rules = read_acl(path)
    reject_ace(owner, rules)


def assert_trusted_install(root: Path, manifest_paths: tuple[str, ...], *,
                           read_acl=_handle_acl, interpreter: Path = PYTHON):
    if os.name != 'nt' and read_acl is _handle_acl:
        raise InstallTrustRefused('native Windows check required')
    if ntpath.normcase(str(root)) != ntpath.normcase(str(ROOT)):
        raise InstallTrustRefused('unexpected protected installation root')
    if not isinstance(manifest_paths, tuple) or not manifest_paths:
        raise InstallTrustRefused('empty protected source inventory')
    paths = [Path(r'C:\Program Files'), root.parent, root, ANCHOR,
             root / 'release-approval.json', interpreter.parent, interpreter]
    for item in manifest_paths:
        if not re.fullmatch(r'[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)+', item):
            raise InstallTrustRefused('invalid manifest path')
        part = root
        for segment in item.split('/'):
            part = part / segment
            paths.append(part)
    seen = set()
    for path in paths:
        key = ntpath.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        assert_protected_path(path, read_acl=read_acl)
    return len(seen)
