"""R6.2B2C offline contract for retained Windows process-handle exit waits.

Does NOT launch a process or change any OS state. Native acceptance remains
mandatory and cannot be inferred from these fakes.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[3]
MON = ROOT / 'windows' / 'monitoring' / 'v080'
sys.path.insert(0, str(MON))
import OnyxWindowsJobRunner as job


class FakeKernel:
    def __init__(self, pids, *, not_member=None):
        self.pids = tuple(pids)
        self.not_member = not_member
        self.closed = []
        self.waits = []
        self.wait_result = 0

    def QueryInformationJobObject(self, _job, klass, output, length, _returned):
        if klass != 3:
            raise AssertionError('only PID snapshot is mocked')
        capacity = (length - 8) // ctypes.sizeof(ctypes.c_size_t)
        if len(self.pids) > capacity:
            raise AssertionError('unexpected synthetic PID overflow')
        fields = ctypes.cast(output, ctypes.POINTER(ctypes.c_uint32))
        fields[0] = len(self.pids)
        fields[1] = len(self.pids)
        pids = ctypes.cast(ctypes.c_void_p(ctypes.cast(output, ctypes.c_void_p).value+8),
                          ctypes.POINTER(ctypes.c_size_t))
        for i, pid in enumerate(self.pids):
            pids[i] = pid
        return True

    def OpenProcess(self, _access, _inherit, pid):
        return pid + 1000

    def IsProcessInJob(self, h, _job, response):
        ctypes.cast(response, ctypes.POINTER(wintypes.BOOL)).contents.value = (
            0 if h - 1000 == self.not_member else 1)
        return True

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True

    def WaitForSingleObject(self, h, ms):
        self.waits.append((h, ms))
        return self.wait_result


class RetainedHandleTests(unittest.TestCase):
    def test_retains_identity_verified_descendants(self):
        win = FakeKernel((211, 222))
        handles = job._retain_current_job_processes(win, 999)
        self.assertEqual(handles, [1211, 1222])
        self.assertEqual(win.closed, [])
        for h in handles:
            win.CloseHandle(h)

    def test_refuses_unverified_job_pid_and_closes_handles(self):
        win = FakeKernel((211, 222), not_member=222)
        with self.assertRaises(job.JobRunnerRefused):
            job._retain_current_job_processes(win, 999)
        self.assertEqual(win.closed, [1211, 1222])

    def test_refuses_duplicate_job_pids(self):
        win = FakeKernel((211, 211))
        with self.assertRaises(job.JobRunnerRefused):
            job._retain_current_job_processes(win, 999)

    def test_each_known_handle_must_signal(self):
        win = FakeKernel(())
        job._require_signaled_handles(win, (110, 111), deadline=time.monotonic()+1)
        self.assertEqual([h for h, _ in win.waits], [110, 111])

    def test_unsignaled_descendant_refuses_completion(self):
        win = FakeKernel(())
        win.wait_result = 0x102
        with self.assertRaisesRegex(job.JobRunnerRefused, 'not confirmed'):
            job._require_signaled_handles(win, (110, 111), deadline=time.monotonic()+1)
        self.assertEqual([h for h, _ in win.waits], [110])

    def test_expired_deadline_cannot_be_extended(self):
        win = FakeKernel(())
        win.wait_result = 0x102
        with self.assertRaises(job.JobRunnerRefused):
            job._require_signaled_handles(win, (110,), deadline=time.monotonic()-0.5)
        self.assertEqual(win.waits[0][1], 0)


if __name__ == '__main__':
    unittest.main()
