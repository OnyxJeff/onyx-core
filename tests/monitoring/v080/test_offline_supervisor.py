"""M2A synthetic-only process supervision tests: no network, Pi, or live data."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "windows" / "monitoring" / "v080" / "OnyxOfflineSupervisor.py"
spec = importlib.util.spec_from_file_location("onyx_v080_offline_supervisor", MODULE)
assert spec is not None and spec.loader is not None
sup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sup)


class SyntheticSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="onyx-v080-m2-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def cycle(self, mode="ok", timeout=1.5):
        return sup.run_synthetic_cycle(self.directory, mode, timeout)

    def assert_inert(self, result):
        self.assertTrue(result["synthetic_only"])
        for key in ("connectivity_assessed", "runtime_enabled", "live_probe_authorized",
                    "task_creation_authorized", "store_modified"):
            self.assertIs(result[key], False, key)
        self.assertEqual(result["repair_action"], "None")

    def test_synthetic_success_has_no_connectivity_claim(self):
        value = self.cycle()
        self.assertEqual(value["supervision_status"], "Completed")
        self.assert_inert(value)

    def test_nonzero_exit_is_failure(self):
        value = self.cycle("nonzero")
        self.assertEqual(value["supervision_status"], "WorkerFailed")
        self.assert_inert(value)

    def test_invalid_json_refused(self):
        value = self.cycle("invalid")
        self.assertEqual(value["supervision_status"], "InvalidFixtureOutput")
        self.assert_inert(value)

    def test_excessive_output_refused(self):
        value = self.cycle("oversize")
        self.assertEqual(value["supervision_status"], "InvalidFixtureOutput")
        self.assert_inert(value)

    def test_repair_claim_refused(self):
        value = self.cycle("repair")
        self.assertEqual(value["supervision_status"], "InvalidFixtureOutput")
        self.assert_inert(value)

    def test_timeout_bounded_and_inert(self):
        started = time.monotonic()
        value = self.cycle("hang", 0.2)
        self.assertEqual(value["supervision_status"], "TimedOut")
        self.assertLess(time.monotonic() - started, 4.0)
        self.assert_inert(value)

    def test_tree_timeout_captures_descendant_and_tears_down(self):
        value = self.cycle("tree", 1.5)
        self.assertEqual(value["supervision_status"], "TimedOut")
        self.assertIsInstance(value["fixture_descendant_pid"], int)
        self.assert_inert(value)
        pid = value["fixture_descendant_pid"]
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                try:
                    status = wintypes.DWORD()
                    self.assertTrue(kernel32.GetExitCodeProcess(handle, ctypes.byref(status)))
                    self.assertNotEqual(status.value, 259, "mock grandchild still running")
                finally:
                    kernel32.CloseHandle(handle)
            else:
                # Only ERROR_INVALID_PARAMETER (87) means the PID is absent.
                # Access denied or another error is NOT proof of cleanup.
                self.assertEqual(ctypes.get_last_error(), 87,
                                 "cannot verify mock grandchild termination")
        elif Path("/proc").is_dir():
            stat = Path("/proc") / str(pid) / "stat"
            # A brief kernel scheduling window can show R immediately after
            # SIGKILL; allow it to transition to a zombie or disappear.
            for attempt in range(30):
                if not stat.exists():
                    break
                if stat.read_text().split(") ", 1)[1][0] == "Z":
                    break
                time.sleep(0.05)
            else:
                self.fail("mock grandchild remains active after process-group termination")

    def test_timeout_tree_marker_survives_missing_partial_stdout(self):
        # Windows TimeoutExpired.output may be None after a flushed marker.
        real_communicate = subprocess.Popen.communicate

        def hide_partial_stdout(proc, *args, **kwargs):
            try:
                return real_communicate(proc, *args, **kwargs)
            except subprocess.TimeoutExpired as exc:
                exc.output = None
                raise

        with mock.patch.object(subprocess.Popen, "communicate", hide_partial_stdout):
            value = self.cycle("tree", 1.5)
        self.assertEqual(value["supervision_status"], "TimedOut")
        self.assertIsInstance(value["fixture_descendant_pid"], int)
        self.assert_inert(value)

    def test_second_cycle_refused_while_locked(self):
        lock = sup._checked_fixture_directory(self.directory)
        with sup._exclusive_lock(lock):
            with self.assertRaises(sup.OfflineCycleBusy):
                self.cycle()
        self.assertEqual(self.cycle()["supervision_status"], "Completed")

    def test_lock_released_after_timeout(self):
        self.cycle("hang", 0.1)
        self.assertEqual(self.cycle()["supervision_status"], "Completed")

    def test_lock_released_after_worker_failure(self):
        self.cycle("nonzero")
        self.assertEqual(self.cycle()["supervision_status"], "Completed")

    def test_rejects_unrecognized_mode(self):
        for mode in ("ssh", "powershell", "live", "release", "", "--live-read-only"):
            with self.subTest(mode=mode), self.assertRaises(sup.OfflineSupervisorError):
                self.cycle(mode)

    def test_rejects_non_string_mode(self):
        with self.assertRaises(sup.OfflineSupervisorError):
            self.cycle(None)

    def test_rejects_bool_timeout(self):
        with self.assertRaises(sup.OfflineSupervisorError):
            self.cycle(timeout=True)

    def test_rejects_oversized_timeout(self):
        with self.assertRaises(sup.OfflineSupervisorError):
            self.cycle(timeout=90)

    def test_rejects_zero_timeout(self):
        with self.assertRaises(sup.OfflineSupervisorError):
            self.cycle(timeout=0)

    def test_rejects_unapproved_directory(self):
        with tempfile.TemporaryDirectory(prefix="anything-else-") as td:
            with self.assertRaises(sup.OfflineSupervisorError):
                sup.run_synthetic_cycle(Path(td), "ok")

    def test_rejects_v070_or_production_directory(self):
        for path in (Path(r"C:\\Users\\jmay2\\AppData\\Local\\OnyxCore-v070-Release\\Monitoring"),
                     Path(r"D:\\github_repos\\onyx-core")):
            with self.subTest(path=str(path)), self.assertRaises(sup.OfflineSupervisorError):
                sup.run_synthetic_cycle(path, "ok")

    def test_rejects_symlinked_fixture_directory(self):
        with tempfile.TemporaryDirectory(prefix="onyx-v080-m2-target-") as target:
            link = Path(tempfile.gettempdir()) / ("onyx-v080-m2-redirect-" + next(tempfile._get_candidate_names()))
            try:
                link.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation not permitted")
            try:
                with self.assertRaises(sup.OfflineSupervisorError):
                    sup.run_synthetic_cycle(link, "ok")
            finally:
                link.unlink()

    def test_rejects_junctioned_fixture_directory(self):
        # Simulate a Windows junction even where creation rights are absent.
        with mock.patch.object(sup.Path, "is_junction", create=True, return_value=True):
            with mock.patch.object(sup.subprocess, "Popen", side_effect=AssertionError("spawned")):
                with self.assertRaises(sup.OfflineSupervisorError):
                    self.cycle()
        self.assertEqual(tuple(self.directory.iterdir()), ())

    def test_no_fixture_invocation_for_rejected_path(self):
        with mock.patch.object(sup.subprocess, "Popen", side_effect=AssertionError("started")):
            with self.assertRaises(sup.OfflineSupervisorError):
                sup.run_synthetic_cycle(Path(r"D:\\github_repos\\onyx-core"), "ok")

    def test_inert_cli_only(self):
        run = subprocess.run([sys.executable, "-I", "-B", str(MODULE), "--check-inert"],
                             capture_output=True, timeout=5, check=False)
        self.assertEqual(run.returncode, 0, run.stderr.decode(errors="replace"))
        obj = json.loads(run.stdout)
        self.assertFalse(obj["runtime_enabled"])
        self.assertFalse(obj["live_probe_authorized"])
        self.assertFalse(obj["task_creation_authorized"])
        self.assertFalse(obj["store_modified"])

    def test_cli_refuses_live_switch(self):
        run = subprocess.run([sys.executable, "-I", "-B", str(MODULE), "--live-read-only"],
                             capture_output=True, timeout=5, check=False)
        self.assertNotEqual(run.returncode, 0)

    def test_cli_refuses_worker_arguments(self):
        run = subprocess.run([sys.executable, "-I", "-B", str(MODULE), "--check-inert", "--fixture-mode", "tree"],
                             capture_output=True, timeout=5, check=False)
        self.assertNotEqual(run.returncode, 0)

    def test_no_persistent_state_files_created(self):
        self.cycle()
        names = {p.name for p in self.directory.iterdir()}
        self.assertEqual(names, {"fixture-cycle.lock"})

    def test_inputs_do_not_change(self):
        before = hashlib.sha256(MODULE.read_bytes()).hexdigest()
        self.cycle()
        self.assertEqual(hashlib.sha256(MODULE.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
