"""Candidate build reproducibility from *committed* fixture Git objects."""
from __future__ import annotations
import pathlib
import subprocess
import sys
import tempfile
import unittest
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'release'))
import onyx_candidate_verify as candidate


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.t.name)
        for parts in ('windows/collector', 'pi/services/receiver'):
            (self.repo / parts).mkdir(parents=True)
        (self.repo / 'windows/collector/Send-OnyxTelemetry.ps1').write_text('Write-Host test\n', encoding='utf-8')
        (self.repo / 'pi/services/receiver/receiver.py').write_text('print("test")\n', encoding='utf-8')
        def git(*args):
            return subprocess.run(['git', '-C', str(self.repo), *args], check=True,
                                  capture_output=True, text=True).stdout.strip()
        git('init', '--quiet')
        git('config', 'user.email', 'test@invalid.local')
        git('config', 'user.name', 'Fixture')
        git('add', '.')
        git('commit', '--quiet', '-m', 'fixture')
        self.commit = git('rev-parse', 'HEAD')

    def tearDown(self):
        self.t.cleanup()

    def test_twice_identical(self):
        result = candidate.check_repeatable(self.repo, self.commit, '0.9.0-rc1')
        self.assertEqual(result['status'], 'REPRODUCIBLE')
        self.assertEqual(set(result['artifacts']), {'windows', 'pi-armv6'})
        self.assertEqual(result['source_commit'], self.commit)

    def test_wrong_commit_refused(self):
        with self.assertRaises(ValueError):
            candidate.check_repeatable(self.repo, '0' * 40, '0.9.0-rc1')

    def test_wrong_release_version_refused(self):
        with self.assertRaises(ValueError):
            candidate.check_repeatable(self.repo, self.commit, '0.8.0')

if __name__ == '__main__':
    unittest.main(verbosity=2)
