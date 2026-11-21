#!/usr/bin/env python3
"""M2-S3C offline: deterministic Pi-only code publish and no-replace boundaries."""
from __future__ import annotations

import contextlib
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/installation/pi'))
import onyx_v100_pi_code_publish as subject

BUNDLE = Path(os.environ['ONYX_V100_BUNDLE']) if 'ONYX_V100_BUNDLE' in os.environ else None
CONFIG = ROOT / 'docs/v1.0.0/examples/pi-armv6.system.config.example.json'


class PublishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if BUNDLE is None or not BUNDLE.is_file():
            raise AssertionError('ONYX_V100_BUNDLE must select verified M2-S1 candidate')
        selfhash = hashlib.sha256(BUNDLE.read_bytes()).hexdigest()
        assert selfhash == subject.BUNDLE_SHA256

    def payload(self):
        return subject.expected_files(BUNDLE, CONFIG)

    def test_release_is_exact_and_separate_from_legacy(self):
        self.assertEqual(subject.RELEASE_ROOT, '/opt/onyxcore/v1.0.0')
        self.assertNotEqual(subject.RELEASE_ROOT, subject.LEGACY_STATE)
        self.assertEqual(subject.PARENT, Path('/opt/onyxcore'))
        self.assertEqual(subject.RELEASE_NAME, 'v1.0.0')

    def test_manifest_selection_and_config(self):
        files, config = self.payload()
        self.assertEqual(len(files), 14)
        self.assertEqual(config['storage']['state_dir'], '/var/lib/onyxcore-v100')
        self.assertIn('pi/services/receiver/receiver_v100.py', files)
        self.assertIn('pi/services/receiver/integrated_store_v100.py', files)
        self.assertIn('tools/installation/pi/onyx_v100_pi_launch.py', files)
        self.assertIn(subject.UNIT_CANDIDATE, files)
        self.assertIn(subject.INTERNAL_CONFIG, files)
        self.assertNotIn(subject.RECEIPT, files)
        self.assertFalse(any('windows/' in name for name in files))

    def test_inert_preview_and_no_existing_files(self):
        files, config = self.payload()
        result = subject.plan(files, config)
        self.assertEqual(result['operation'], 'PI_V100_CODE_PUBLICATION_PREVIEW')
        self.assertFalse(result['release_written'])
        self.assertFalse(result['service_registered'])
        self.assertFalse(result['activation_performed'])
        self.assertFalse(result['credential_contents_read'])
        self.assertEqual(result['file_count'], 15)

    def test_unit_template_is_not_installed_in_systemd(self):
        files, _ = self.payload()
        unit = files[subject.UNIT_CANDIDATE].decode('utf-8')
        self.assertIn('ConditionPathExists=', unit)
        self.assertIn('RefuseManualStart=yes', unit)
        self.assertIn('EnvironmentFile=/etc/onyxcore/v1.0.0/receiver.env', unit)
        self.assertIn('ReadWritePaths=/var/lib/onyxcore-v100', unit)
        self.assertNotIn('SQUALL', unit)

    def test_legacy_storage_path_refused(self):
        cfg = json.loads(CONFIG.read_text())
        cfg['storage']['state_dir'] = '/var/lib/onyxcore'
        with tempfile.TemporaryDirectory() as d:
            candidate = Path(d)/'bad.json'
            candidate.write_text(json.dumps(cfg))
            with self.assertRaises((ValueError, subject.PublishRefused)):
                subject.expected_files(BUNDLE, candidate)

    def test_unreviewed_bundle_fails(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'different.zip'
            path.write_bytes(BUNDLE.read_bytes()+b'x')
            with self.assertRaises(ValueError):
                subject.expected_files(path, CONFIG)

    def test_readonly_cli_preview(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            result=subject.main(['--bundle',str(BUNDLE),'--config',str(CONFIG)])
        self.assertEqual(result,0)
        self.assertFalse(json.loads(output.getvalue())['release_written'])

    def test_one_or_two_approval_switches_refused(self):
        flags=['--install','--approve-inactive','--approve-system']
        for subset in ([flags[0]],[flags[1]],[flags[2]],flags[:2],flags[1:]):
            with self.subTest(subset=subset), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(subject.main(['--bundle',str(BUNDLE),'--config',str(CONFIG)]+subset),2)

    def test_native_system_call_blocked_without_hardware(self):
        if sys.platform=='linux' and subject.platform.machine().lower()=='armv6l':
            self.skipTest('ARMv6 native requires separate review')
        with self.assertRaises(subject.PublishRefused):
            subject.native_prerequisites()

    @unittest.skipUnless(sys.platform=='linux' and hasattr(os,'O_NOFOLLOW'), 'POSIX dirfd fixture')
    def test_atomic_publication_and_verification_on_disposable_dir(self):
        files,_=self.payload()
        with tempfile.TemporaryDirectory(prefix='OnyxV100-S3C-') as d:
            parent=Path(d)
            fd=os.open(parent, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                result=subject.publish_in_parent(fd,parent,files,owner=os.getuid(),group=os.getgid(),check_root_parent=False)
                self.assertEqual(result['file_count'],15)
                self.assertFalse(result['activation_performed'])
                release=parent/'v1.0.0'
                self.assertTrue(release.is_dir())
                self.assertEqual(set(str(p.relative_to(release)) for p in release.rglob('*') if p.is_file()), set(files)|{subject.RECEIPT})
                receipt=json.loads((release/subject.RECEIPT).read_text())
                self.assertEqual(len(receipt['files']),14)
                for row in receipt['files']:
                    contents=(release/row['path']).read_bytes()
                    self.assertEqual(row['sha256'],subject.digest(contents))
                self.assertFalse(receipt['service_registered'])
                self.assertFalse(receipt['external_state_changed'])
            finally:
                os.close(fd)

    @unittest.skipUnless(sys.platform=='linux' and hasattr(os,'O_NOFOLLOW'), 'POSIX dirfd fixture')
    def test_existing_release_preserved_no_replace(self):
        files,_=self.payload()
        with tempfile.TemporaryDirectory(prefix='OnyxV100-S3C-') as d:
            parent=Path(d)
            target=parent/subject.RELEASE_NAME
            target.mkdir()
            (target/'do-not-touch').write_text('original')
            fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                with self.assertRaises(subject.PublishRefused):
                    subject.publish_in_parent(fd,parent,files,owner=os.getuid(),group=os.getgid(),check_root_parent=False)
            finally:
                os.close(fd)
            self.assertEqual((target/'do-not-touch').read_text(),'original')

    @unittest.skipUnless(sys.platform=='linux' and hasattr(os,'O_NOFOLLOW'), 'POSIX dirfd fixture')
    def test_atomic_no_replace_race_surfaces_failure(self):
        files,_=self.payload()
        with tempfile.TemporaryDirectory(prefix='OnyxV100-S3C-') as d:
            parent=Path(d)
            fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            def inject(fd_, old, new):
                (parent/new).mkdir(exist_ok=True)
                (parent/new/'preserved').write_text('safe')
                raise subject.PublishRefused('atomic no-replace publication failed: EEXIST')
            try:
                with patch.object(subject, 'rename_noreplace', side_effect=inject):
                    with self.assertRaises(subject.PublishRefused):
                        subject.publish_in_parent(fd,parent,files,owner=os.getuid(),group=os.getgid(),check_root_parent=False)
            finally:
                os.close(fd)
            self.assertEqual((parent/subject.RELEASE_NAME/'preserved').read_text(),'safe')
            self.assertEqual(list(parent.glob('.onyx-v100-staging-*')),[])

    @unittest.skipUnless(sys.platform=='linux', 'POSIX mode fixture')
    def test_mode_excludes_group_write_and_other(self):
        files,_=self.payload()
        with tempfile.TemporaryDirectory(prefix='OnyxV100-S3C-') as d:
            parent=Path(d)
            fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                subject.publish_in_parent(fd,parent,files,owner=os.getuid(),group=os.getgid(),check_root_parent=False)
            finally:
                os.close(fd)
            release=parent/subject.RELEASE_NAME
            self.assertEqual(release.stat().st_mode&0o777,0o750)
            self.assertEqual((release/subject.INTERNAL_CONFIG).stat().st_mode&0o777,0o640)

    def test_no_external_activation_mutators(self):
        source=(ROOT/'tools/installation/pi/onyx_v100_pi_code_publish.py').read_text('utf-8')
        for forbidden in ('systemctl enable','systemctl start','systemctl daemon-reload',
                          'subprocess.run(', 'os.execv(', 'os.makedirs("/var/lib',
                          'os.chmod("/etc', 'os.chown("/etc'):
            self.assertNotIn(forbidden, source)

    def test_hash_receipt_repeatable(self):
        files,_=self.payload()
        self.assertEqual(subject.receipt_bytes(files),subject.receipt_bytes(dict(reversed(list(files.items())))))


if __name__=='__main__':
    unittest.main(verbosity=2)
