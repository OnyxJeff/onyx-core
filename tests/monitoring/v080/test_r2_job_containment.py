"""Pure offline contract tests for release-only Job Object containment.

All native calls are blocked; these tests never launch Windows worker processes,
probe the Pi, mutate credentials, or write incident history.
"""
from __future__ import annotations

import importlib
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

MONITOR = Path(__file__).resolve().parents[3] / 'windows' / 'monitoring' / 'v080'
sys.path.insert(0, str(MONITOR))
import OnyxWindowsJobRunner as job
import OnyxLiveConnectivity as m1

PS = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
SSH = r'C:\Windows\System32\OpenSSH\ssh.exe'


class JobContainmentOfflineTests(unittest.TestCase):
    def test_import_is_side_effect_free(self):
        self.assertTrue(hasattr(job, 'WindowsJobRunner'))
        self.assertFalse(job.inert_status()['cli_live_enabled'])
        self.assertFalse(job.inert_status()['windows_host_validated'])

    def test_wrong_cli_refused(self):
        self.assertEqual(job.main(['--check-inert']), 0)
        with self.assertRaises(SystemExit):
            job.main(['--live'])

    def test_allowlist_requires_absolute_exes(self):
        for path in ('powershell.exe', r'C:\One\..\two.exe',
                     'C:\\cmd.exe\\', r'C:\foo\a.cmd', 'C:\\foo\\bad.exe\n', ''):
            with self.subTest(path=path), self.assertRaises(job.JobRunnerRefused):
                job.WindowsJobRunner((path,))

    def test_duplicate_exes_refused(self):
        with self.assertRaises(job.JobRunnerRefused):
            job.WindowsJobRunner((PS, PS.upper()))

    def test_refuse_command_injection_before_backend(self):
        invoked = []
        j = job.WindowsJobRunner((PS,), _backend=lambda *a: invoked.append(a))
        for bad in ([SSH], ['powershell.exe'], [], [PS, 'bad\nargument'], [PS, 'x\x00y']):
            with self.subTest(command=bad), self.assertRaises(job.JobRunnerRefused):
                j.run(bad, timeout=5)
        self.assertEqual(invoked, [])

    def test_refuse_unsupported_execution_mode(self):
        invoked = []
        j = job.WindowsJobRunner((PS,), _backend=lambda *a: invoked.append(a))
        for kw in ({'timeout': None}, {'timeout': 0}, {'timeout': 91},
                   {'timeout': True}, {'timeout': 5, 'check': True},
                   {'timeout': 5, 'capture_output': False},
                   {'timeout': 5, 'env': {'X':'Y'}}):
            with self.subTest(kw=kw), self.assertRaises(job.JobRunnerRefused):
                j.run([PS], **kw)
        self.assertFalse(invoked)

    def test_refuse_unbounded_output(self):
        j = job.WindowsJobRunner((PS,), _backend=lambda cmd,timeout: subprocess.CompletedProcess(cmd,0,b'a'*(job.MAX_OUTPUT_BYTES+1),b''))
        with self.assertRaises(job.JobRunnerRefused):
            j.run([PS], timeout=5)

    def test_refuse_invalid_native_response(self):
        for bad in (None, 0, subprocess.CompletedProcess([PS],False,b'',b''),
                    subprocess.CompletedProcess([PS],0,'not bytes',b'')):
            j = job.WindowsJobRunner((PS,), _backend=lambda cmd,timeout: bad)
            with self.subTest(bad=bad), self.assertRaises(job.JobRunnerRefused):
                j.run([PS], timeout=5)

    def test_approved_mock_backend(self):
        calls=[]
        def backend(cmd,timeout):
            calls.append((cmd,timeout))
            return subprocess.CompletedProcess(cmd,0,b'{"ok":true}',b'')
        j=job.WindowsJobRunner((PS,SSH), _backend=backend)
        got=j.run([SSH,'-V'], capture_output=True, timeout=8, check=False)
        self.assertEqual(got.stdout,b'{"ok":true}')
        self.assertEqual(calls,[([SSH,'-V'],8)])

    def test_real_backend_refused_non_windows(self):
        if sys.platform == 'win32':
            self.skipTest('Never launch real processes from unit tests')
        j=job.WindowsJobRunner((PS,))
        with self.assertRaises(job.JobRunnerRefused):
            j.run([PS],timeout=5)

    def test_development_run_once_keeps_existing_runner(self):
        fake = lambda *a, **k: None
        with patch.object(m1, '_windows', return_value={'classification': 'WindowsProbeUnavailable'}), \
             patch.object(m1, '_pi', return_value={'classification': 'PiProbeUnavailable'}):
            # _windows and _pi do not invoke the dummy subprocess runner.
            output = m1.run_once({'profile':'development'}, runner=fake)
        self.assertEqual(output['status'], 'Unknown')

    def test_release_override_refused_before_probes(self):
        with patch.object(m1, '_windows', side_effect=AssertionError('probe called')):
            with self.assertRaises(m1.ConnectivityError):
                m1.run_once({'profile':'release'}, runner=lambda *a,**k: None)

    def test_release_uses_native_job_adapter_without_launch(self):
        seen=[]
        class FakeJob:
            def __init__(self, allowed_executables):
                seen.append(allowed_executables)
            def run(self, *args, **kwargs):
                raise AssertionError('native subprocess not permitted')
        with patch.object(job, 'WindowsJobRunner', FakeJob), \
             patch.object(m1, '_windows', return_value={'classification': 'WindowsProbeUnavailable'}), \
             patch.object(m1, '_pi', return_value={'classification': 'PiProbeUnavailable'}):
            output=m1.run_once({'profile':'release','runtime':{'ssh_executable':SSH}})
        self.assertEqual(output['status'], 'Unknown')
        self.assertEqual(seen, [(str(m1.PS5),SSH)])

    def test_job_failure_aborts_cycle_not_recorded_as_network_outage(self):
        class BrokenJob:
            def __init__(self, *_):
                pass
            def run(self, *args, **kwargs):
                raise job.JobRunnerRefused('assign refused')
        with patch.object(job, 'WindowsJobRunner', BrokenJob):
            with self.assertRaises(job.JobRunnerRefused):
                m1.run_once({'profile': 'release', 'runtime': {'ssh_executable': SSH},
                             'windows': {'adapter_name':'Ethernet 3','gateway_ip':'192.168.137.1',
                                         'receiver_ip':'192.168.137.167','receiver_port':8765},
                             'timeouts': {'receiver_tcp_ms':1000}},
                            )

    def test_no_release_process_started_by_cli(self):
        with patch.object(job, '_run_windows_native', side_effect=AssertionError('native called')):
            self.assertEqual(job.main(['--check-inert']), 0)


if __name__ == '__main__':
    unittest.main()
