"""Focused M3 inactive-version install tests; no system paths are written."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import uuid
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'/'release'))
sys.path.insert(0, str(ROOT/'tools'/'installation'/'common'))
import onyx_release as release
import onyx_install as ins

SHA = 'b' * 40
V = '0.9.0-rc1'


class TestInactiveInstaller(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix='onyx-v090-m3-tests-'))
        self.target = Path(tempfile.gettempdir()) / ('OnyxV090-' + uuid.uuid4().hex)
        self.archive = self.work / 'windows.zip'
        self.source = {'windows/collector/Send-OnyxTelemetry.ps1':b'code\n',
                       'tools/installation/common/onyx_install.py':b'# installer\n'}
        self.archive.write_bytes(release.encode_zip('windows', V, SHA, self.source))
        self.digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)
        shutil.rmtree(self.target, ignore_errors=True)

    def call(self, **kwargs):
        values = dict(archive=self.archive,target=self.target,platform='windows',
                      commit=SHA,version=V,digest=self.digest)
        values.update(kwargs)
        return ins.prepare(**values)

    def test_preview_no_write(self):
        r = self.call()
        self.assertEqual('PREVIEW', r['status'])
        self.assertFalse(self.target.exists())

    def test_atomic_inactive_prepare_and_receipt(self):
        r = self.call(apply=True)
        self.assertEqual('PREPARED', r['status'])
        self.assertEqual(b'code\n', (self.target/'windows/collector/Send-OnyxTelemetry.ps1').read_bytes())
        receipt = json.loads((self.target/'installation-receipt.json').read_text())
        self.assertFalse(receipt['activated'])
        self.assertEqual(SHA, receipt['source_commit'])
        self.assertEqual(self.digest, receipt['archive_sha256'])

    def test_no_overwrite_of_existing_release(self):
        self.target.mkdir()
        (self.target/'keep.txt').write_text('pristine')
        with self.assertRaises(ins.InstallRefused):
            self.call(apply=True)
        self.assertEqual('pristine', (self.target/'keep.txt').read_text())

    def test_tampered_archive_refused_without_target(self):
        self.archive.write_bytes(self.archive.read_bytes()+b'X')
        with self.assertRaises(ValueError):
            self.call(apply=True)
        self.assertFalse(self.target.exists())

    def test_wrong_commit_refused_without_target(self):
        with self.assertRaises(ValueError):
            self.call(commit='a'*40, apply=True)
        self.assertFalse(self.target.exists())

    def test_rejects_unsafe_targets(self):
        for path in [self.work/'invalid', self.target.parent/'othername',
                     self.target/'nested']:
            with self.assertRaises(ins.InstallRefused):
                ins.check_target(path,platform='windows',system=False)

    def test_symlink_target_is_refused(self):
        try:
            self.target.symlink_to(self.work, target_is_directory=True)
        except OSError:
            self.skipTest('symlink creation not available without privileges')
        with self.assertRaises(ins.InstallRefused):
            self.call(apply=True)
        self.target.unlink()

    def test_system_path_cannot_be_requested_from_other_os(self):
        with self.assertRaises(ins.InstallRefused):
            ins.check_target(Path('/opt/onyxcore/v0.9.0'),platform='windows',system=True)

    def test_system_install_requires_root_and_existing_parent(self):
        with self.assertRaises(ins.InstallRefused):
            ins.check_target(Path('/opt/onyxcore/v0.9.0'),platform='pi-armv6',
                             system=True,admin_check=lambda _: False)

    def test_package_selects_common_installer_files(self):
        for platform in ('windows','pi-armv6'):
            self.assertTrue(release.selected(platform, 'tools/installation/common/onyx_install.py'))
        self.assertFalse(release.selected('pi-armv6', 'tools/installation/windows/Install-OnyxV090.ps1'))

    def test_pi_scripts_remain_byte_exact_and_executable(self):
        pi_source = {'pi/services/receiver/receiver.py':b'print(1)\n',
                     'tools/installation/pi/install-onyx-v090.sh':b'#!/bin/sh\nexit 0\n'}
        archive = self.work/'pi.zip'
        archive.write_bytes(release.encode_zip('pi-armv6', V, SHA, pi_source))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        res = self.call(archive=archive,digest=digest,platform='pi-armv6',apply=True)
        self.assertFalse(res['activated'])
        f = self.target/'tools/installation/pi/install-onyx-v090.sh'
        self.assertEqual(pi_source['tools/installation/pi/install-onyx-v090.sh'], f.read_bytes())
        import os
        if os.name == 'posix':
            self.assertEqual(0o755,f.stat().st_mode & 0o777)


if __name__ == '__main__':
    unittest.main(verbosity=2)
