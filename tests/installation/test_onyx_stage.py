"""M2 focused sandbox staging checks; no ONYX CORE host/service access."""
from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'release'))
sys.path.insert(0, str(ROOT / 'tools' / 'installation' / 'common'))
import onyx_release as release
import onyx_stage as module

COMMIT = 'a' * 40
VERSION = '0.9.0-rc1'


class StageTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix='onyx-m2-tests-'))
        self.target = Path(tempfile.gettempdir()) / ('OnyxV090-' + uuid.uuid4().hex[:16])
        self.archive = self.folder / 'pkg.zip'
        self.files = {
            'windows/collector/Send-OnyxTelemetry.ps1': b'#safe test file\n',
            'docs/v0.9.0/INSTALL.md': b'hello\n',
        }
        self.archive.write_bytes(release.encode_zip('windows', VERSION, COMMIT, self.files))
        self.digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)
        shutil.rmtree(self.target, ignore_errors=True)

    def args(self, *extra):
        return ['--archive', str(self.archive), '--platform', 'windows',
                '--expected-commit', COMMIT, '--expected-version', VERSION,
                '--expected-sha256', self.digest, '--target', str(self.target), *extra]

    def test_preview_does_not_create_target(self):
        self.assertEqual(0, module.main(self.args()))
        self.assertFalse(self.target.exists())

    def test_stage_verifies_content_and_records_provenance(self):
        self.assertEqual(0, module.main(self.args('--stage')))
        self.assertEqual(b'#safe test file\n', (self.target / 'windows/collector/Send-OnyxTelemetry.ps1').read_bytes())
        self.assertEqual(release.canonical(release.verify_archive(self.archive)),
                         (self.target / 'manifest.json').read_bytes())

    def test_existing_target_is_not_overwritten(self):
        self.target.mkdir()
        (self.target / 'keep.txt').write_text('preserve')
        self.assertEqual(2, module.main(self.args('--stage')))
        self.assertEqual('preserve', (self.target / 'keep.txt').read_text())

    def test_wrong_sha_and_wrong_commit_fail_before_writes(self):
        bad_sha = self.args()
        bad_sha[bad_sha.index('--expected-sha256') + 1] = 'f'*64
        self.assertEqual(2, module.main(bad_sha + ['--stage']))
        bad_commit = self.args()
        bad_commit[bad_commit.index('--expected-commit') + 1] = 'b'*40
        self.assertEqual(2, module.main(bad_commit + ['--stage']))
        self.assertFalse(self.target.exists())

    def test_refuses_outside_temp_and_corrupt_archive(self):
        self.assertRaises(module.StageRefused, module.check_destination,
                          Path('/opt/onyxcore/OnyxV090-test'))
        self.archive.write_bytes(self.archive.read_bytes() + b'altered')
        self.assertEqual(2, module.main(self.args('--stage')))
        self.assertFalse(self.target.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
