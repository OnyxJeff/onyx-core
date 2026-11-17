#!/usr/bin/env python3
"""ONYX CORE v0.8.0 M2A: synthetic-only supervised process harness.

NO network diagnostic, SSH, ICS, Task Scheduler, enrollment, incident state,
or real telemetry capability exists here. The only executable worker is an
embedded Python fixture with fixed modes. The CLI can only report inert status.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

WORKER_MODES = frozenset({"ok", "hang", "nonzero", "invalid", "oversize", "repair", "tree"})
MAX_STDOUT = 8192
MAX_STDERR = 8192
_TEST_ROOT = Path(tempfile.gettempdir()).resolve()
_TEST_PREFIX = "onyx-v080-m2-"
_FIXTURE_SOURCE = r'''
import json,subprocess,sys,time
mode=sys.argv[1]
if sys.stdin.buffer.readline()!=b"GO\n":
    sys.exit(41)
if mode=="ok":
    print(json.dumps({"schema_version":1,"fixture":"synthetic-only","result":"ok","repair_action":"None"}))
elif mode=="nonzero":
    print("fixture failed", file=sys.stderr)
    sys.exit(7)
elif mode=="hang":
    time.sleep(60)
elif mode=="invalid":
    print("{invalid-json")
elif mode=="oversize":
    print("X" * 10000)
elif mode=="repair":
    print(json.dumps({"schema_version":1,"fixture":"synthetic-only","result":"ok","repair_action":"RestartICS"}))
elif mode=="tree":
    child=subprocess.Popen([sys.executable,"-I","-B","-u","-c","import time;time.sleep(60)"],
                           stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    print("TREE_CHILD_PID=" + str(child.pid),flush=True)
    time.sleep(60)
else:
    sys.exit(42)
'''


class OfflineSupervisorError(RuntimeError):
    """Refuse unsafe mock execution or a failed teardown."""


class OfflineCycleBusy(OfflineSupervisorError):
    """The synthetic cycle lock is held by another invocation."""


def _checked_fixture_directory(directory: Path) -> Path:
    """No arbitrary root, production state, or redirected lock locations."""
    if not isinstance(directory, Path) or not directory.is_absolute():
        raise OfflineSupervisorError("absolute temporary fixture directory required")
    if directory.name.startswith(_TEST_PREFIX) is False:
        raise OfflineSupervisorError("only a named M2 temporary fixture directory is allowed")
    if directory.parent.resolve() != _TEST_ROOT:
        raise OfflineSupervisorError("mock lock must be directly below OS temporary root")
    if (directory.is_symlink() or bool(getattr(directory, "is_junction", lambda: False)())
            or not directory.is_dir()):
        raise OfflineSupervisorError("missing or redirected fixture directory")
    lock = directory / "fixture-cycle.lock"
    if lock.is_symlink() or bool(getattr(lock, "is_junction", lambda: False)()):
        raise OfflineSupervisorError("redirected fixture lock refused")
    return lock


@contextmanager
def _exclusive_lock(lock_path: Path):
    """Nonblocking cross-process advisory lock; file is fixture-only."""
    with lock_path.open("a+b") as handle:
        held = False
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise OfflineCycleBusy("synthetic cycle already running") from exc
            else:
                import fcntl
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise OfflineCycleBusy("synthetic cycle already running") from exc
            held = True
            yield
        finally:
            if held:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class _WindowsJob:
    """Assign an inert, stdin-gated mock before allowing descendants to spawn.

    Production launch needs additional atomic-create safeguards; this is NOT
    a reviewed network-process execution mechanism. Explicit job termination
    handles child-process teardown for tests and normal scope exit.
    """
    def __init__(self):
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k32 = k32
        k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k32.TerminateJobObject.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        k32.CloseHandle.restype = wintypes.BOOL
        self.handle = k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OfflineSupervisorError("Windows mock Job Object creation failed")

    def attach(self, proc: subprocess.Popen) -> None:
        if not self.k32.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(proc._handle))):
            raise OfflineSupervisorError("Windows mock Job Object assignment failed")

    def terminate(self) -> None:
        if self.handle and not self.k32.TerminateJobObject(self.handle, 1):
            raise OfflineSupervisorError("Windows mock process-tree termination failed")

    def close(self) -> None:
        if self.handle:
            self.k32.CloseHandle(self.handle)
            self.handle = None


def _stop_tree(proc: subprocess.Popen, job: _WindowsJob | None) -> tuple[bytes, bytes]:
    """Stop descendants, wait for parent; never report success on failed cleanup."""
    if os.name == "nt":
        if job is not None:
            job.terminate()
        elif proc.poll() is None:
            proc.kill()
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        return proc.communicate(timeout=3)
    except subprocess.TimeoutExpired as exc:
        raise OfflineSupervisorError("mock child did not exit after termination") from exc


def _result(outcome: str, duration: float, *, child_pid: int | None = None) -> dict:
    return {
        "source": "OnyxV080M2SyntheticSupervisor",
        "synthetic_only": True,
        "supervision_status": outcome,
        "duration_seconds": round(duration, 3),
        "connectivity_assessed": False,
        "runtime_enabled": False,
        "live_probe_authorized": False,
        "task_creation_authorized": False,
        "store_modified": False,
        "repair_action": "None",
        "fixture_descendant_pid": child_pid,
    }


def run_synthetic_cycle(directory: Path, mode: str, timeout_seconds: float = 1.0) -> dict:
    """Run ONLY a fixed Python fixture under a temporary filesystem lock.

    This function is intentionally not exposed from the CLI. The fixture's
    stdin gate prevents any descendants from starting prior to job assignment.
    Network/PowerShell/SSH paths and arbitrary commands are never accepted.
    """
    if mode not in WORKER_MODES or type(mode) is not str:
        raise OfflineSupervisorError("unsupported synthetic worker mode")
    if type(timeout_seconds) not in (float, int) or type(timeout_seconds) is bool or not 0.05 <= timeout_seconds <= 5.0:
        raise OfflineSupervisorError("synthetic timeout must be 0.05 to 5.0 seconds")
    lock_path = _checked_fixture_directory(directory)
    with _exclusive_lock(lock_path):
        started = time.monotonic()
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(
            [sys.executable, "-I", "-B", "-u", "-c", _FIXTURE_SOURCE, mode],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=flags, start_new_session=(os.name != "nt"),
            shell=False,
        )
        job = None
        cleaned = False
        child_pid = None
        try:
            if os.name == "nt":
                job = _WindowsJob()
                job.attach(proc)
            try:
                output, errors = proc.communicate(input=b"GO\n", timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                # On Windows the timeout exception may contain no partial stdout.
                # Read the complete marker after terminating the process tree.
                final_output, _ = _stop_tree(proc, job)
                cleaned = True
                if mode == "tree":
                    match = re.search(rb"TREE_CHILD_PID=(\d+)", final_output)
                    if match:
                        child_pid = int(match.group(1))
                return _result("TimedOut", time.monotonic() - started, child_pid=child_pid)
            if len(output) > MAX_STDOUT or len(errors) > MAX_STDERR:
                return _result("InvalidFixtureOutput", time.monotonic() - started)
            if proc.returncode != 0:
                return _result("WorkerFailed", time.monotonic() - started)
            try:
                obj = json.loads(output.decode("utf-8", "strict"))
            except (UnicodeError, ValueError):
                return _result("InvalidFixtureOutput", time.monotonic() - started)
            if (type(obj) is not dict or set(obj) != {"schema_version", "fixture", "result", "repair_action"} or
                type(obj["schema_version"]) is not int or obj["schema_version"] != 1 or
                obj["fixture"] != "synthetic-only" or obj["result"] != "ok" or
                obj["repair_action"] != "None"):
                return _result("InvalidFixtureOutput", time.monotonic() - started)
            return _result("Completed", time.monotonic() - started)
        finally:
            try:
                # The job (or POSIX process group) is always cleaned, including
                # a worker that exits while its descendants are still alive.
                if not cleaned:
                    _stop_tree(proc, job)
            finally:
                if job is not None:
                    job.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-inert", action="store_true", required=True,
                        help="print offline-only status; do not launch even a fixture")
    parser.parse_args(argv)
    print(json.dumps({
        "source": "OnyxV080M2SyntheticSupervisor",
        "synthetic_only": True,
        "runtime_enabled": False,
        "live_probe_authorized": False,
        "task_creation_authorized": False,
        "store_modified": False,
        "repair_action": "None",
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
