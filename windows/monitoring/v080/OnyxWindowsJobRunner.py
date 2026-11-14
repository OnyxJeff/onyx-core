#!/usr/bin/env python3
"""ONYX CORE v0.8 release-only diagnostic worker containment.

No process is launched at import or through this module's CLI. Actual Win32
CreateProcess calls are possible ONLY when the separately authorized release
probe invokes ``WindowsJobRunner.run``. Never use as authorization itself.

The child is created SUSPENDED and assigned to an unnamed Job Object with
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE before the primary thread is resumed.
Only stdin/stdout/stderr handles are inherited, via STARTUPINFOEX HANDLE_LIST.
Closing the job terminates surviving descendants. No repairs, task changes,
credential access, or network access is performed by this module itself.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import ntpath
import os
import subprocess
import sys
import tempfile
import threading
from typing import Callable

# On non-Windows msvcrt does not exist; the test environment injects an inert
# backend and MUST NOT invoke native handle APIs.

MAX_OUTPUT_BYTES = 65536
MAX_TIMEOUT_SECONDS = 90
_SPAWN_LOCK = threading.Lock()


class JobRunnerRefused(RuntimeError):
    """Refuse unsafe worker launch, or native Job Object failure."""


def _canonical_executable(value: str) -> str:
    if (type(value) is not str or not value or '\x00' in value or '\r' in value or '\n' in value):
        raise JobRunnerRefused('invalid worker executable')
    drive, _tail = ntpath.splitdrive(value)
    if (len(drive) != 2 or drive[1] != ':' or not drive[0].isalpha() or
            not ntpath.isabs(value) or ntpath.splitext(value)[1].lower() != '.exe'):
        raise JobRunnerRefused('absolute Windows .exe path required')
    if any(piece in ('', '.', '..') for piece in value.replace('/', '\\').split('\\')[1:]):
        raise JobRunnerRefused('worker executable path contains unsafe segments')
    return ntpath.normcase(ntpath.normpath(value))


class WindowsJobRunner:
    """Allow-listed subprocess.run-compatible adapter for M1 diagnostics.

    The optional injected backend is test-only. The live release binding builds
    the default native backend and must independently verify its source/consent.
    """

    def __init__(self, allowed_executables: tuple[str, ...], *, _backend: Callable | None = None):
        if type(allowed_executables) is not tuple or not allowed_executables:
            raise JobRunnerRefused('explicit worker allowlist required')
        normalized = tuple(_canonical_executable(x) for x in allowed_executables)
        if len(set(normalized)) != len(normalized):
            raise JobRunnerRefused('duplicate worker executables')
        self.allowed_executables = frozenset(normalized)
        self._backend = _backend

    def run(self, command, *, capture_output=True, timeout=None, check=False, env=None):
        if type(command) is not list or not command or len(command) > 64 or any(
                type(x) is not str or not x or len(x) > 4096 or '\x00' in x or '\r' in x or '\n' in x
                for x in command):
            raise JobRunnerRefused('invalid worker argument vector')
        if _canonical_executable(command[0]) not in self.allowed_executables:
            raise JobRunnerRefused('unapproved diagnostic executable')
        if capture_output is not True or check is not False or env is not None:
            raise JobRunnerRefused('unsupported process execution mode')
        if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
            raise JobRunnerRefused('worker timeout must be 1..90 seconds')
        if len(subprocess.list2cmdline(command)) >= 32700:
            raise JobRunnerRefused('worker argument vector oversized')
        if self._backend is None:
            if os.name != 'nt':
                raise JobRunnerRefused('Windows native Job Object required')
            backend = _run_windows_native
        else:
            backend = self._backend
        try:
            result = backend(command, timeout)
        except OSError as exc:
            raise JobRunnerRefused('worker containment unavailable') from exc
        if not isinstance(result, subprocess.CompletedProcess):
            raise JobRunnerRefused('invalid native runner result')
        if type(result.returncode) is not int or not isinstance(result.stdout, bytes):
            raise JobRunnerRefused('invalid native runner output')
        if len(result.stdout) > MAX_OUTPUT_BYTES:
            raise JobRunnerRefused('diagnostic stdout too large')
        return result


def _run_windows_native(command: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Native Windows worker: suspended -> job assign -> resume -> bounded wait.

    This path cannot be exercised on Linux; Windows host smoke tests are a
    separate release gate. API failures fail closed; no ordinary Popen fallback.
    """
    if os.name != 'nt':
        raise JobRunnerRefused('native runner requires Windows')
    import msvcrt
    from ctypes import wintypes

    HANDLE = wintypes.HANDLE
    DWORD = wintypes.DWORD
    SIZE_T = ctypes.c_size_t
    LPVOID = ctypes.c_void_p

    class BASIC_LIMIT(ctypes.Structure):
        _fields_ = [
            ('PerProcessUserTimeLimit', ctypes.c_int64),
            ('PerJobUserTimeLimit', ctypes.c_int64),
            ('LimitFlags', DWORD),
            ('MinimumWorkingSetSize', SIZE_T),
            ('MaximumWorkingSetSize', SIZE_T),
            ('ActiveProcessLimit', DWORD),
            ('Affinity', SIZE_T),
            ('PriorityClass', DWORD),
            ('SchedulingClass', DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in (
            'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
            'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

    class EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [
            ('BasicLimitInformation', BASIC_LIMIT),
            ('IoInfo', IO_COUNTERS),
            ('ProcessMemoryLimit', SIZE_T),
            ('JobMemoryLimit', SIZE_T),
            ('PeakProcessMemoryUsed', SIZE_T),
            ('PeakJobMemoryUsed', SIZE_T),
        ]

    class STARTUPINFO(ctypes.Structure):
        _fields_ = [
            ('cb', DWORD), ('lpReserved', wintypes.LPWSTR),
            ('lpDesktop', wintypes.LPWSTR), ('lpTitle', wintypes.LPWSTR),
            ('dwX', DWORD), ('dwY', DWORD), ('dwXSize', DWORD), ('dwYSize', DWORD),
            ('dwXCountChars', DWORD), ('dwYCountChars', DWORD),
            ('dwFillAttribute', DWORD), ('dwFlags', DWORD),
            ('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD),
            ('lpReserved2', ctypes.POINTER(ctypes.c_byte)),
            ('hStdInput', HANDLE), ('hStdOutput', HANDLE), ('hStdError', HANDLE),
        ]

    class STARTUPINFOEX(ctypes.Structure):
        _fields_ = [('StartupInfo', STARTUPINFO), ('lpAttributeList', LPVOID)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ('hProcess', HANDLE), ('hThread', HANDLE),
            ('dwProcessId', DWORD), ('dwThreadId', DWORD),
        ]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [LPVOID, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = HANDLE
    kernel.SetInformationJobObject.argtypes = [HANDLE, ctypes.c_int, LPVOID, DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.InitializeProcThreadAttributeList.argtypes = [LPVOID, DWORD, DWORD, ctypes.POINTER(SIZE_T)]
    kernel.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    kernel.UpdateProcThreadAttribute.argtypes = [LPVOID, DWORD, SIZE_T, LPVOID, SIZE_T, LPVOID, LPVOID]
    kernel.UpdateProcThreadAttribute.restype = wintypes.BOOL
    kernel.DeleteProcThreadAttributeList.argtypes = [LPVOID]
    kernel.DeleteProcThreadAttributeList.restype = None
    kernel.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, LPVOID, LPVOID,
        wintypes.BOOL, DWORD, LPVOID, wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESS_INFORMATION),
    ]
    kernel.CreateProcessW.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [HANDLE, HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.ResumeThread.argtypes = [HANDLE]
    kernel.ResumeThread.restype = DWORD
    kernel.WaitForSingleObject.argtypes = [HANDLE, DWORD]
    kernel.WaitForSingleObject.restype = DWORD
    kernel.GetExitCodeProcess.argtypes = [HANDLE, ctypes.POINTER(DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.TerminateJobObject.argtypes = [HANDLE, ctypes.c_uint]
    kernel.TerminateJobObject.restype = wintypes.BOOL
    kernel.TerminateProcess.argtypes = [HANDLE, ctypes.c_uint]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL

    def checked(ok, stage):
        if not ok:
            raise JobRunnerRefused('%s refused (Win32=%d)' % (stage, ctypes.get_last_error()))

    # Real worker creation is serialized because inheritable std handles must
    # briefly exist while CreateProcessW uses an explicit HANDLE_LIST.
    with _SPAWN_LOCK, open(os.devnull, 'rb') as stdin, \
            tempfile.TemporaryFile(mode='w+b') as stdout, \
            tempfile.TemporaryFile(mode='w+b') as stderr:
        handles = tuple(msvcrt.get_osfhandle(f.fileno()) for f in (stdin, stdout, stderr))
        job = None
        attr_buffer = None
        attr_ready = False
        child = PROCESS_INFORMATION()
        child_created = False
        child_assigned = False
        try:
            job = kernel.CreateJobObjectW(None, None)
            checked(job, 'CreateJobObjectW')
            limits = EXTENDED_LIMIT()
            limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
            checked(kernel.SetInformationJobObject(job, 9, ctypes.byref(limits),
                                                   ctypes.sizeof(limits)), 'SetInformationJobObject')

            size = SIZE_T(0)
            kernel.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
            if size.value <= 0 or size.value > 65536:
                raise JobRunnerRefused('unexpected attribute list size')
            attr_buffer = ctypes.create_string_buffer(size.value)
            checked(kernel.InitializeProcThreadAttributeList(attr_buffer, 1, 0,
                                                             ctypes.byref(size)), 'InitializeProcThreadAttributeList')
            attr_ready = True
            inherit_list = (HANDLE * 3)(*handles)
            checked(kernel.UpdateProcThreadAttribute(attr_buffer, 0, 0x00020002,
                                                     ctypes.cast(inherit_list, LPVOID),
                                                     ctypes.sizeof(inherit_list), None, None),
                    'UpdateProcThreadAttribute(HANDLE_LIST)')

            sx = STARTUPINFOEX()
            sx.StartupInfo.cb = ctypes.sizeof(sx)
            sx.StartupInfo.dwFlags = 0x00000100  # STARTF_USESTDHANDLES
            sx.StartupInfo.hStdInput, sx.StartupInfo.hStdOutput, sx.StartupInfo.hStdError = handles
            sx.lpAttributeList = ctypes.cast(attr_buffer, LPVOID)
            cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
            flags = 0x00000004 | 0x00080000 | 0x08000000  # SUSPENDED, EXTENDED, NO_WINDOW

            prior = [os.get_handle_inheritable(h) for h in handles]
            try:
                for h in handles:
                    os.set_handle_inheritable(h, True)
                created = kernel.CreateProcessW(
                    command[0], cmd, None, None, True, flags,
                    None, None, ctypes.byref(sx.StartupInfo), ctypes.byref(child),
                )
                checked(created, 'CreateProcessW')
                child_created = True
            finally:
                for h, value in zip(handles, prior):
                    os.set_handle_inheritable(h, value)

            checked(kernel.AssignProcessToJobObject(job, child.hProcess), 'AssignProcessToJobObject')
            child_assigned = True
            if kernel.ResumeThread(child.hThread) == 0xFFFFFFFF:
                raise JobRunnerRefused('ResumeThread refused')

            wait = kernel.WaitForSingleObject(child.hProcess, timeout * 1000)
            if wait == 0x00000102:  # WAIT_TIMEOUT
                kernel.TerminateJobObject(job, 1)
                kernel.WaitForSingleObject(child.hProcess, 3000)
                raise subprocess.TimeoutExpired(command, timeout)
            if wait != 0:  # WAIT_OBJECT_0
                raise JobRunnerRefused('WaitForSingleObject refused')
            code = DWORD(0)
            checked(kernel.GetExitCodeProcess(child.hProcess, ctypes.byref(code)), 'GetExitCodeProcess')
            stdout.flush()
            stdout.seek(0)
            captured = stdout.read(MAX_OUTPUT_BYTES + 1)
            if len(captured) > MAX_OUTPUT_BYTES:
                raise JobRunnerRefused('diagnostic stdout exceeds bounded capture')
            return subprocess.CompletedProcess(command, ctypes.c_int32(code.value).value,
                                               stdout=captured, stderr=b'')
        finally:
            # Fail-closed: if assignment failed, the suspended child must be
            # explicitly terminated; job closing alone cannot kill an unassigned child.
            if child_created and not child_assigned:
                kernel.TerminateProcess(child.hProcess, 1)
            if child.hThread:
                kernel.CloseHandle(child.hThread)
            if job:
                kernel.CloseHandle(job)  # KILL_ON_JOB_CLOSE terminates surviving descendants.
            if child.hProcess:
                kernel.CloseHandle(child.hProcess)
            if attr_ready:
                kernel.DeleteProcThreadAttributeList(attr_buffer)


def inert_status() -> dict:
    return {
        'phase': 'R2-worker-containment', 'cli_live_enabled': False,
        'worker_job_object_native_implementation': True,
        'windows_host_validated': False, 'start_or_enrollment_enabled': False,
        'tasks_created': False, 'repairs_enabled': False,
        'release_status': 'HOLD',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-inert', required=True, action='store_true')
    parser.parse_args(argv)
    print(json.dumps(inert_status(), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
