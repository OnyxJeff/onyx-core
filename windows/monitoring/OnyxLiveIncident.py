#!/usr/bin/env python3
"""ONYX CORE v0.7.0 M2: explicit single live read-only cycle -> incident store.

An isolated development operator tool, NOT a task, service, or network repairer.
The existing M1 PowerShell runner is the only provider of real cycle evidence.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

import OnyxIncidentAdapter as adapter
import OnyxIncidentState as reducer
import OnyxIncidentStore as storage
from OnyxMonitorConfig import ConfigError, load_config

APPROVED_DEV = Path(r"D:\github_repos\onyx-core-v070")
APPROVED_PROD = Path(r"D:\github_repos\onyx-core")
BASELINE = "68e719b8463c597d9ddac8a8892039c3192ed869"
CHECKPOINT_F = "c0dfbb7966922daf0a43d2394c44cee0b47a0ea3"
BACKUP_REL = Path(r"windows\collector\Send-OnyxTelemetry.pre-v050.bak")
BACKUP_SHA256 = "59e1ee7205efbedb79ba3d0dcb4c9fd0d8ebd3dfa4d5d9313bbd8325976830eb"
APPROVED_BRANCH = "feature/v0.7.0-monitoring"
APPROVED_STATE_SUBDIR = "OnyxCore-v070-Development"
MARKER_NAME = "incident-state.initialized.json"
MARKER_BYTES = b'{"schema_version":1,"marker":"onyx-v070-incident-initialized"}\n'
MAX_RUNNER_JSON = 16384
RUNNER_TIMEOUT_SECONDS = 120
WINDOWS_PS = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")


class LiveIncidentError(RuntimeError):
    """A live integration operation was refused; never infer healthy."""


def _same_path(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", "-C", str(root), *args],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LiveIncidentError("git integrity verification unavailable") from exc
    if result.returncode != 0:
        raise LiveIncidentError("git integrity verification failed")
    try:
        return result.stdout.decode("utf-8", "strict").strip()
    except UnicodeError as exc:
        raise LiveIncidentError("invalid git output") from exc


def approved_context() -> tuple[Path, Path]:
    """Approve only verified SQUALL worktree, baseline, backup and state location."""
    if os.name != "nt":
        raise LiveIncidentError("live incident integration is Windows-only")
    root = Path(__file__).resolve().parents[2]
    if not _same_path(root, APPROVED_DEV):
        raise LiveIncidentError("unapproved development directory")
    if _git(root, "branch", "--show-current") != APPROVED_BRANCH:
        raise LiveIncidentError("wrong development branch")
    _git(root, "merge-base", "--is-ancestor", CHECKPOINT_F, "HEAD")

    if _git(APPROVED_PROD, "branch", "--show-current") != "main":
        raise LiveIncidentError("production branch changed")
    if _git(APPROVED_PROD, "rev-parse", "HEAD") != BASELINE:
        raise LiveIncidentError("production baseline changed")
    if _git(APPROVED_PROD, "status", "--porcelain=v1", "-uall") != (
        "?? windows/collector/Send-OnyxTelemetry.pre-v050.bak"
    ):
        raise LiveIncidentError("unexpected production working-tree changes")
    protected = APPROVED_PROD / BACKUP_REL
    try:
        if hashlib.sha256(protected.read_bytes()).hexdigest() != BACKUP_SHA256:
            raise LiveIncidentError("protected collector backup changed")
    except OSError as exc:
        raise LiveIncidentError("protected collector backup is unavailable") from exc

    try:
        config = load_config(root / "windows" / "monitoring" / "monitoring.development.example.json")
    except (ConfigError, OSError, ValueError, UnicodeError) as exc:
        raise LiveIncidentError("approved monitoring configuration invalid") from exc
    if (config["profile"] != "development" or config["read_only"] is not True
            or config["repair_action"] != "None"
            or config["runtime"]["python_executable"].casefold() != str(Path(sys.executable)).casefold()):
        raise LiveIncidentError("unsafe monitoring profile or Python executable")
    local_app = os.environ.get("LOCALAPPDATA")
    if not local_app:
        raise LiveIncidentError("LOCALAPPDATA is undefined")
    state_dir = Path(local_app) / APPROVED_STATE_SUBDIR / "Monitoring"
    expected = os.path.expandvars(config["state_dir"])
    if os.path.normcase(os.path.normpath(expected)) != os.path.normcase(os.path.normpath(str(state_dir))):
        raise LiveIncidentError("unexpected development state path")
    return root, state_dir


def _ensure_safe_directory(directory: Path) -> None:
    """Prevent replacing the designated development directory with a redirect."""
    if not directory.is_absolute():
        raise LiveIncidentError("incident directory must be absolute")
    for path in (directory.parent, directory):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise LiveIncidentError("redirected incident directory forbidden")
    directory.mkdir(parents=True, exist_ok=True)
    if os.path.normcase(str(directory.resolve())) != os.path.normcase(str(directory.absolute())):
        raise LiveIncidentError("incident directory redirects outside development")


@contextmanager
def _single_cycle_lock(directory: Path):
    """Nonblocking cross-process lock spanning probes and persistent commit."""
    lockfile = directory / "incident-cycle.lock"
    with lockfile.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise LiveIncidentError("another monitoring cycle is already active") from exc
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise LiveIncidentError("another monitoring cycle is already active") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _state_paths(directory: Path) -> tuple[Path, Path]:
    return directory / "incident-state.json", directory / MARKER_NAME


def assert_store_policy(directory: Path, initialize_new: bool) -> tuple[Path, Path]:
    state, marker = _state_paths(directory)
    if state.is_symlink() or marker.is_symlink():
        raise LiveIncidentError("symlinked incident files forbidden")
    if initialize_new:
        if state.exists() or marker.exists():
            raise LiveIncidentError("new-store authorization requires BOTH files absent")
    else:
        if not state.is_file() or not marker.is_file():
            raise LiveIncidentError("incident store or initialization marker missing: refuse reset")
        if marker.read_bytes() != MARKER_BYTES:
            raise LiveIncidentError("incident initialization marker invalid")
        storage.load_store(state)  # checksum + entire schema validation before any probe
    return state, marker


def _make_marker(marker: Path) -> None:
    """Write the fail-closed sentinel before the first incident-store transaction."""
    fd = os.open(str(marker), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(MARKER_BYTES)
        stream.flush()
        os.fsync(stream.fileno())


def read_json_strict(raw: bytes) -> dict:
    if len(raw) == 0 or len(raw) > MAX_RUNNER_JSON:
        raise LiveIncidentError("runner returned empty or oversized JSON")
    try:
        cycle = json.loads(raw.decode("utf-8", "strict"),
                           object_pairs_hook=adapter._unique_pairs,
                           parse_constant=adapter._reject_constant)
        reducer._check_cycle(cycle)
    except (UnicodeError, ValueError, TypeError, OverflowError) as exc:
        raise LiveIncidentError("invalid or contradictory read-only cycle JSON") from exc
    return cycle


def run_existing_runner(root: Path, *, runner: Callable[..., Any] = subprocess.run) -> dict:
    path = root / "windows" / "monitoring" / "Invoke-OnyxMonitoringCycle.ps1"
    if not path.is_file() or not WINDOWS_PS.is_file():
        raise LiveIncidentError("approved read-only PowerShell runner unavailable")
    # Explicit UTF-8 stdout for PowerShell 5.1; no extra probes or repairs.
    script = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); & '" + (
        str(path).replace("'", "''")
    ) + "' -LiveReadOnly -Json"
    try:
        result = runner([str(WINDOWS_PS), "-NoProfile", "-NonInteractive",
                         "-ExecutionPolicy", "Bypass", "-Command", script],
                        capture_output=True, timeout=RUNNER_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LiveIncidentError("read-only runner unavailable or timed out") from exc
    if result.returncode != 0:
        # Never echo diagnostic stderr (could include operator/network information).
        raise LiveIncidentError("read-only runner exited unsuccessfully")
    return read_json_strict(result.stdout)


def apply_live_cycle(cycle: dict, directory: Path, *, initialize_new: bool = False) -> dict:
    """Library for tests and operator; CLI enforces fixed dev path and live opt-in."""
    _ensure_safe_directory(directory)
    state, marker = assert_store_policy(directory, initialize_new)
    # Validate before ever creating an initialization marker or changing state.
    reducer._check_cycle(cycle)
    if initialize_new:
        # If a crash occurs after this point but before the store commit, the
        # marker remains and future ordinary runs fail closed, not reset.
        _make_marker(marker)
    result = adapter.apply_cycle_to_store(cycle, state)
    result = dict(result)
    result["source"] = "LiveIncidentIntegration"
    return result


def execute_one_cycle(root: Path, directory: Path, initialize_new: bool, *,
                      collect: Callable[[Path], dict] = run_existing_runner) -> dict:
    _ensure_safe_directory(directory)
    with _single_cycle_lock(directory):
        # Validate state *before* probing and again immediately before writing.
        assert_store_policy(directory, initialize_new)
        cycle = collect(root)
        return apply_live_cycle(cycle, directory, initialize_new=initialize_new)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-read-only", action="store_true", required=True,
                        help="mandatory explicit authorization to run one diagnostic cycle")
    parser.add_argument("--initialize-new", action="store_true",
                        help="one-time authorization only when store AND marker are absent")
    args = parser.parse_args(argv)
    try:
        root, directory = approved_context()
        status = execute_one_cycle(root, directory, args.initialize_new)
        print(json.dumps(status, sort_keys=True, separators=(",", ":")))
        return 0
    except (LiveIncidentError, reducer.InvalidIncidentInput,
            adapter.IncidentAdapterError, storage.IncidentStoreError,
            OSError, ValueError) as exc:
        print("LIVE INCIDENT CYCLE REFUSED: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
