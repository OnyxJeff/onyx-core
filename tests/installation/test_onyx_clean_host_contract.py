"""Offline-only clean-host registration policy tests; never executes registration."""
from __future__ import annotations
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PI = ROOT / 'tools/installation/pi/manage-onyx-v090-clean-host-unit.sh'
WIN = ROOT / 'tools/installation/windows/Manage-OnyxV090CleanHostTasks.ps1'
GUIDE = ROOT / 'docs/v0.9.0/CLEAN_INSTALL_OPERATIONS.md'
SHA = 'a' * 40

class CleanHostTests(unittest.TestCase):
    def test_shell_syntax(self):
        if sys.platform == 'win32':
            self.skipTest('POSIX sh not available on this host')
        proc = subprocess.run(['sh', '-n', str(PI)], capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())

    def test_pi_refuses_missing_or_unmatched_approval(self):
        if sys.platform == 'win32':
            self.skipTest('POSIX sh not available on this host')
        for argv in ([], ['--commit', SHA, '--approve-registration'],
                     ['--commit', SHA, '--register'], ['--commit', SHA, '--remove'],
                     ['--commit', 'bad'], ['--commit', SHA, '--remove', '--approve-registration']):
            with self.subTest(argv=argv):
                result = subprocess.run(['sh', str(PI), *argv], capture_output=True)
                self.assertNotEqual(result.returncode, 0)

    def test_pi_registers_only_inactive_and_refuses_legacy(self):
        content = PI.read_text()
        self.assertIn('[ ! -e /etc/systemd/system/onyxcore-receiver.service ]', content)
        self.assertIn('systemctl daemon-reload', content)
        self.assertNotIn('systemctl enable', content)
        self.assertNotIn('systemctl start', content)
        self.assertIn('systemctl is-active --quiet', content)
        self.assertIn('systemctl is-enabled --quiet', content)
        self.assertIn('cmp -s', content)
        self.assertIn('onyx_runtime_plan.py', content)
        self.assertIn('--installed-root "$root"', content)

    def test_windows_is_clean_user_scoped_candidate_only(self):
        content = WIN.read_text()
        self.assertIn('Windows PowerShell 5.1 required', content)
        self.assertIn('LogonType Interactive -RunLevel Limited', content)
        self.assertIn("'ONYX CORE - Telemetry Collector'", content)
        self.assertIn("'ONYX CORE - Local Gateway'", content)
        self.assertIn('Existing production ONYX tasks detected', content)
        self.assertIn('candidate_gateway_loopback_port -ne 18769', content)
        self.assertIn('collector-token.dpapi', content)
        self.assertIn('source_commit -cne $ExpectedCommit', content)
        self.assertNotIn('Start-ScheduledTask', content)
        self.assertNotIn('Stop-ScheduledTask', content)
        self.assertNotIn('Set-ScheduledTask', content)

    def test_guide_explicitly_bounds_scope(self):
        content = GUIDE.read_text()
        for term in ('clean-host', 'ARMv6', 'v0.8.0', 'telemetry.db',
                     'SQUALL', 'PowerShell 5.1', 'separate explicit operator decision',
                     'native ARMv6'):
            self.assertIn(term, content)

if __name__ == '__main__':
    unittest.main(verbosity=2)
