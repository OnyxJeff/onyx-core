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
import time
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

    def run(self, command, *, capture_output=True, timeout=None, check=False, env=None,
            consent_check=None, low_integrity=False):
        if type(command) is not list or not command or len(command) > 64 or any(
                type(x) is not str or not x or len(x) > 4096 or '\x00' in x or '\r' in x or '\n' in x
                for x in command):
            raise JobRunnerRefused('invalid worker argument vector')
        if _canonical_executable(command[0]) not in self.allowed_executables:
            raise JobRunnerRefused('unapproved diagnostic executable')
        if capture_output is not True or check is not False or env is not None:
            raise JobRunnerRefused('unsupported process execution mode')
        if consent_check is not None and not callable(consent_check):
            raise JobRunnerRefused('invalid live authorization callback')
        if type(low_integrity) is not bool:
            raise JobRunnerRefused('invalid security isolation policy')
        if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
            raise JobRunnerRefused('worker timeout must be 1..90 seconds')
        if len(subprocess.list2cmdline(command)) >= 32700:
            raise JobRunnerRefused('worker argument vector oversized')
        if self._backend is None:
            if os.name != 'nt':
                raise JobRunnerRefused('Windows native Job Object required')
            if consent_check is not None or low_integrity:
                backend = lambda cmd, seconds: _run_windows_native(
                    cmd, seconds, consent_check=consent_check, low_integrity=low_integrity)
            else:
                backend = _run_windows_native
        else:
            if consent_check is not None or low_integrity:
                raise JobRunnerRefused('injected backend cannot attest native isolation')
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


def _retain_current_job_processes(kernel, job) -> list:
    """Pin identity-bound process handles BEFORE issuing job termination.

    Job accounting / PID lists alone are not termination-completion barriers.
    Windows opens SYNCHRONIZE+QUERY_LIMITED handles only for members verified
    against the actual job; inability to audit a current member fails closed.
    """
    from ctypes import wintypes

    pids = None
    for capacity in (16, 32, 64, 128, 256):
        class JOB_PID_LIST(ctypes.Structure):
            _fields_ = [('NumberOfAssignedProcesses', ctypes.c_uint32),
                        ('NumberOfProcessIdsInList', ctypes.c_uint32),
                        ('ProcessIdList', ctypes.c_size_t * capacity)]
        entry = JOB_PID_LIST()
        ok = kernel.QueryInformationJobObject(job, 3, ctypes.byref(entry),
                                               ctypes.sizeof(entry), None)
        if not ok:
            if ctypes.get_last_error() == 234:  # ERROR_MORE_DATA
                continue
            raise JobRunnerRefused('cannot enumerate contained Job members')
        count = int(entry.NumberOfProcessIdsInList)
        assigned = int(entry.NumberOfAssignedProcesses)
        if count > capacity:
            raise JobRunnerRefused('invalid Windows Job PID-list response')
        if assigned > count:
            continue  # Windows requests a larger complete result buffer.
        pids = [int(entry.ProcessIdList[i]) for i in range(count)]
        break
    if pids is None:
        raise JobRunnerRefused('contained Job PID list exceeds audit limit')
    if any(pid <= 0 for pid in pids) or len(pids) != len(set(pids)):
        raise JobRunnerRefused('invalid contained Job process identity list')
    retained = []
    try:
        for pid in pids:
            handle = kernel.OpenProcess(0x00100000 | 0x1000, False, pid)
            if not handle:
                if ctypes.get_last_error() == 87:  # exited before OpenProcess
                    continue
                raise JobRunnerRefused('cannot open contained Job member for audit')
            retained.append(handle)
            member = wintypes.BOOL()
            if (not kernel.IsProcessInJob(handle, job, ctypes.byref(member)) or
                    not member.value):
                raise JobRunnerRefused('Job PID is not a verified member')
        return retained
    except BaseException:
        for handle in retained:
            kernel.CloseHandle(handle)
        raise


def _require_signaled_handles(kernel, handles, *, deadline: float) -> None:
    """A successful per-process wait, not a zero Job count, proves exit."""
    for handle in handles:
        remaining = max(0, int((deadline - time.monotonic()) * 1000))
        if kernel.WaitForSingleObject(handle, remaining) != 0:
            raise JobRunnerRefused('worker process-tree exit not confirmed')


def _run_windows_native(command: list[str], timeout: int, *,
                        consent_check=None, low_integrity=False) -> subprocess.CompletedProcess:
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
    kernel.QueryInformationJobObject.argtypes = [HANDLE, ctypes.c_int, LPVOID, DWORD, ctypes.POINTER(DWORD)]
    kernel.QueryInformationJobObject.restype = wintypes.BOOL
    kernel.GetExitCodeProcess.argtypes = [HANDLE, ctypes.POINTER(DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.TerminateJobObject.argtypes = [HANDLE, ctypes.c_uint]
    kernel.TerminateJobObject.restype = wintypes.BOOL
    kernel.TerminateProcess.argtypes = [HANDLE, ctypes.c_uint]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.OpenProcess.argtypes = [DWORD, wintypes.BOOL, DWORD]
    kernel.OpenProcess.restype = HANDLE
    kernel.IsProcessInJob.argtypes = [HANDLE, HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel.IsProcessInJob.restype = wintypes.BOOL

    # Restrict the entire diagnostic Python worker to LOW Windows integrity.
    # This is mandatory access control (no write-up), not just Python promises.
    # A native host acceptance test MUST prove the release journal is medium+
    # integrity and deny write access to the low-integrity worker.
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = HANDLE
    advapi.OpenProcessToken.argtypes = [HANDLE, DWORD, ctypes.POINTER(HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.CreateRestrictedToken.argtypes = [HANDLE, DWORD, DWORD, LPVOID, DWORD, LPVOID,
                                              DWORD, LPVOID, ctypes.POINTER(HANDLE)]
    advapi.CreateRestrictedToken.restype = wintypes.BOOL
    advapi.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(LPVOID)]
    advapi.ConvertStringSidToSidW.restype = wintypes.BOOL
    advapi.GetLengthSid.argtypes = [LPVOID]
    advapi.GetLengthSid.restype = DWORD
    advapi.SetTokenInformation.argtypes = [HANDLE, ctypes.c_int, LPVOID, DWORD]
    advapi.SetTokenInformation.restype = wintypes.BOOL
    advapi.CreateProcessAsUserW.argtypes = [
        HANDLE, wintypes.LPCWSTR, wintypes.LPWSTR, LPVOID, LPVOID,
        wintypes.BOOL, DWORD, LPVOID, wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESS_INFORMATION),
    ]
    advapi.CreateProcessAsUserW.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [LPVOID]
    kernel.LocalFree.restype = LPVOID

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [('Sid', LPVOID), ('Attributes', DWORD)]

    class TOKEN_MANDATORY_LABEL(ctypes.Structure):
        _fields_ = [('Label', SID_AND_ATTRIBUTES)]

    class JOB_ACCOUNTING(ctypes.Structure):
        _fields_ = [
            ('TotalUserTime', ctypes.c_int64), ('TotalKernelTime', ctypes.c_int64),
            ('ThisPeriodTotalUserTime', ctypes.c_int64), ('ThisPeriodTotalKernelTime', ctypes.c_int64),
            ('TotalPageFaultCount', DWORD), ('TotalProcesses', DWORD),
            ('ActiveProcesses', DWORD), ('TotalTerminatedProcesses', DWORD),
        ]

    def checked(ok, stage):
        if not ok:
            raise JobRunnerRefused('%s refused (Win32=%d)' % (stage, ctypes.get_last_error()))

    def cleanup_tree(job, primary) -> None:
        # TerminateJobObject is asynchronous. Acquire the member handles
        # first; after termination, wait for each independently. Always issue
        # TerminateJobObject even when enumeration itself fails.
        handles = []
        capture_error = None
        try:
            handles = _retain_current_job_processes(kernel, job)
        except BaseException as exc:
            capture_error = exc
        try:
            terminated = kernel.TerminateJobObject(job, 1)
            if capture_error is not None:
                raise JobRunnerRefused('cannot prove all Job member identities') from capture_error
            checked(terminated, 'TerminateJobObject')
            deadline = time.monotonic() + 3
            _require_signaled_handles(kernel, [primary, *handles], deadline=deadline)
            while True:
                accounting = JOB_ACCOUNTING()
                checked(kernel.QueryInformationJobObject(job, 1,
                    ctypes.byref(accounting), ctypes.sizeof(accounting), None),
                    'QueryInformationJobObject')
                if accounting.ActiveProcesses == 0:
                    return
                if time.monotonic() >= deadline:
                    raise JobRunnerRefused('worker job accounting did not drain')
                time.sleep(0.025)
        finally:
            for handle in handles:
                kernel.CloseHandle(handle)

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
        cleanup_confirmed = False
        parent_token = HANDLE()
        child_token = HANDLE()
        integrity_sid = LPVOID()
        try:
            job = kernel.CreateJobObjectW(None, None)
            checked(job, 'CreateJobObjectW')
            limits = EXTENDED_LIMIT()
            limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
            if low_integrity:
                # Bound aggregate worker + PowerShell/SSH memory to 384 MiB.
                limits.BasicLimitInformation.LimitFlags |= 0x00000200  # JOB_MEMORY
                limits.JobMemoryLimit = 384 * 1024 * 1024
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

            if low_integrity:
                # Restricted primary token: caller privilege reduction plus LOW
                # mandatory integrity. No unrestricted fallback is permitted.
                checked(advapi.OpenProcessToken(kernel.GetCurrentProcess(),
                    0x0002 | 0x0008 | 0x0001 | 0x0080, ctypes.byref(parent_token)),
                    'OpenProcessToken')
                checked(advapi.CreateRestrictedToken(parent_token, 0x1, 0, None,
                    0, None, 0, None, ctypes.byref(child_token)), 'CreateRestrictedToken')
                checked(advapi.ConvertStringSidToSidW('S-1-16-4096',
                    ctypes.byref(integrity_sid)), 'ConvertStringSidToSidW')
                mandatory_label = TOKEN_MANDATORY_LABEL(
                    SID_AND_ATTRIBUTES(integrity_sid, 0x20))
                checked(advapi.SetTokenInformation(child_token, 25,
                    ctypes.byref(mandatory_label),
                    ctypes.sizeof(mandatory_label) + advapi.GetLengthSid(integrity_sid)),
                    'SetTokenInformation(LOW)')
            if consent_check is not None and consent_check() is not True:
                raise JobRunnerRefused('worker authorization revoked before creation')

            prior = [os.get_handle_inheritable(h) for h in handles]
            try:
                for h in handles:
                    os.set_handle_inheritable(h, True)
                if low_integrity:
                    created = advapi.CreateProcessAsUserW(
                        child_token, command[0], cmd, None, None, True, flags,
                        None, None, ctypes.byref(sx.StartupInfo), ctypes.byref(child))
                else:
                    created = kernel.CreateProcessW(
                        command[0], cmd, None, None, True, flags,
                        None, None, ctypes.byref(sx.StartupInfo), ctypes.byref(child))
                checked(created, 'CreateProcessW')
                child_created = True
            finally:
                for h, value in zip(handles, prior):
                    os.set_handle_inheritable(h, value)

            checked(kernel.AssignProcessToJobObject(job, child.hProcess), 'AssignProcessToJobObject')
            child_assigned = True
            if kernel.ResumeThread(child.hThread) == 0xFFFFFFFF:
                raise JobRunnerRefused('ResumeThread refused')

            deadline = time.monotonic() + timeout
            while True:
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(command, timeout)
                if consent_check is not None and consent_check() is not True:
                    raise JobRunnerRefused('worker authorization revoked during execution')
                remaining_ms = max(1, min(250, int((deadline - time.monotonic()) * 1000)))
                wait = kernel.WaitForSingleObject(child.hProcess, remaining_ms)
                if wait == 0:  # main process exited
                    break
                if wait != 0x00000102:  # WAIT_TIMEOUT
                    raise JobRunnerRefused('WaitForSingleObject refused')

            # Pin every discoverable member before terminating the Job. A
            # zero accounting count alone can precede process-handle signaling.
            cleanup_tree(job, child.hProcess)
            cleanup_confirmed = True
            if consent_check is not None and consent_check() is not True:
                raise JobRunnerRefused('worker authorization revoked after exit')
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
            # Aborted/success paths must confirm *all* children terminated,
            # including on consent revocation or native API errors.
            cleanup_refused = False
            if job and child_assigned and not cleanup_confirmed:
                try:
                    cleanup_tree(job, child.hProcess)
                except BaseException:
                    cleanup_refused = True
            if integrity_sid:
                kernel.LocalFree(integrity_sid)
            if child_token:
                kernel.CloseHandle(child_token)
            if parent_token:
                kernel.CloseHandle(parent_token)
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
            if cleanup_refused:
                raise JobRunnerRefused('worker process-tree exit not confirmed')


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
