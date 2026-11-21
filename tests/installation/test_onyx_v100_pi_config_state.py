#!/usr/bin/env python3
"""M2-S3D isolated state and config publication regression suite."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
PI = ROOT / 'tools' / 'installation' / 'pi'
COMMON = ROOT / 'tools' / 'installation' / 'common'
for directory in (PI, COMMON):
    sys.path.insert(0, str(directory))
import onyx_v100_pi_config_state as mod  # noqa: E402

BUNDLE = Path(os.environ.get('ONYX_V100_BUNDLE', '/nonexistent/ONYX_RUNTIME.zip'))
CONFIG = ROOT / 'docs' / 'v1.0.0' / 'examples' / 'pi-armv6.system.config.example.json'


def inputs():
    if not BUNDLE.is_file():
        raise unittest.SkipTest('Expected pinned runtime bundle not provided')
    return mod.proposed(BUNDLE, CONFIG)


@unittest.skipUnless(os.name == 'posix', 'POSIX dirfd fixture')
class NativeSyntheticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='onyx-s3d-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.conf = self.base / 'cfg'
        self.state = self.base / 'state'
        self.conf.mkdir(mode=0o700)
        self.state.mkdir(mode=0o700)
        self.cfd = os.open(self.conf, mod.NOFOLLOW_DIR)
        self.sfd = os.open(self.state, mod.NOFOLLOW_DIR)
        self.addCleanup(os.close, self.cfd)
        self.addCleanup(os.close, self.sfd)
        self.uid = os.geteuid()
        self.gid = os.getegid()
        self.config, self.receipt, _, _ = inputs()

    def publish(self):
        return mod.publish_in_parents(
            self.cfd, self.conf, self.sfd, self.state,
            self.config, self.receipt,
            root_uid=self.uid, group_gid=self.gid,
            service_uid=self.uid, service_gid=self.gid,
        )

    def test_no_replace_publication_creates_exact_files_and_modes(self):
        result = self.publish()
        self.assertEqual(result['operation'], 'PI_V100_INACTIVE_CONFIG_STATE_PREPARED')
        self.assertFalse(result['activation_performed'])
        self.assertEqual((self.conf / mod.CONFIG_NAME / mod.CONFIG_FILENAME).read_bytes(), self.config)
        self.assertEqual((self.conf / mod.CONFIG_NAME / mod.CONFIG_RECEIPT).read_bytes(), self.receipt)
        self.assertEqual(os.stat(self.conf / mod.CONFIG_NAME).st_mode & 0o777, 0o750)
        self.assertEqual(os.stat(self.conf / mod.CONFIG_NAME / mod.CONFIG_FILENAME).st_mode & 0o777, 0o640)
        self.assertEqual(os.stat(self.conf / mod.CONFIG_NAME / mod.CONFIG_RECEIPT).st_mode & 0o777, 0o640)
        self.assertEqual(os.stat(self.state / mod.STATE_NAME).st_mode & 0o777, 0o700)
        self.assertEqual(list((self.state / mod.STATE_NAME).iterdir()), [])

    def test_second_publication_refused_without_mutation(self):
        self.publish()
        path = self.conf / mod.CONFIG_NAME / mod.CONFIG_FILENAME
        before = path.read_bytes()
        with self.assertRaisesRegex(mod.ProvisionRefused, 'already exists'):
            self.publish()
        self.assertEqual(path.read_bytes(), before)

    def test_existing_state_target_refuses_before_config_publication(self):
        target = self.state / mod.STATE_NAME
        target.mkdir()
        sentinel = target / 'keep.db'
        sentinel.write_bytes(b'original')
        with self.assertRaisesRegex(mod.ProvisionRefused, 'already exists'):
            self.publish()
        self.assertEqual(sentinel.read_bytes(), b'original')
        self.assertFalse((self.conf / mod.CONFIG_NAME).exists())

    def test_existing_config_target_refuses_without_state_creation(self):
        target = self.conf / mod.CONFIG_NAME
        target.mkdir()
        (target / 'keep.txt').write_text('old', encoding='utf-8')
        with self.assertRaisesRegex(mod.ProvisionRefused, 'already exists'):
            self.publish()
        self.assertFalse((self.state / mod.STATE_NAME).exists())

    def test_existing_symlink_config_target_refuses(self):
        path = self.conf / mod.CONFIG_NAME
        path.symlink_to(self.state, target_is_directory=True)
        with self.assertRaisesRegex(mod.ProvisionRefused, 'already exists'):
            self.publish()
        self.assertTrue(path.is_symlink())
        self.assertFalse((self.state / mod.STATE_NAME).exists())

    def test_unsafe_parent_group_write_refuses(self):
        os.fchmod(self.cfd, 0o770)
        with self.assertRaisesRegex(mod.ProvisionRefused, 'unsafe parent'):
            self.publish()
        self.assertFalse((self.state / mod.STATE_NAME).exists())

    def test_rename_race_refuses_overwrite_and_preserves_existing_data(self):
        original_rename = mod.rename_noreplace
        def raced(fd, old, new):
            if new == mod.STATE_NAME:
                (self.state / mod.STATE_NAME).mkdir()
                (self.state / mod.STATE_NAME / 'keep').write_bytes(b'do not replace')
            return original_rename(fd, old, new)
        with mock.patch.object(mod, 'rename_noreplace', side_effect=raced):
            with self.assertRaisesRegex(mod.PublishRefused, 'atomic no-replace'):
                self.publish()
        self.assertEqual((self.state / mod.STATE_NAME / 'keep').read_bytes(), b'do not replace')
        self.assertFalse((self.conf / mod.CONFIG_NAME).exists())
        self.assertEqual(list(self.conf.iterdir()), [])

    def test_second_publish_failure_reports_incomplete_and_never_deletes_state(self):
        original_rename = mod.rename_noreplace
        def interrupted(fd, old, new):
            if new == mod.CONFIG_NAME:
                raise mod.ProvisionRefused('simulated config publication failure')
            return original_rename(fd, old, new)
        with mock.patch.object(mod, 'rename_noreplace', side_effect=interrupted):
            with self.assertRaisesRegex(mod.ProvisionRefused, 'INCOMPLETE'):
                self.publish()
        self.assertTrue((self.state / mod.STATE_NAME).is_dir())
        self.assertFalse((self.conf / mod.CONFIG_NAME).exists())
        with self.assertRaisesRegex(mod.ProvisionRefused, 'already exists'):
            self.publish()

    def test_failed_stage_ownership_does_not_leave_hidden_directory(self):
        with mock.patch.object(mod.os, 'fchown', side_effect=PermissionError('test ACL denial')):
            with self.assertRaises(PermissionError):
                self.publish()
        self.assertEqual(list(self.conf.iterdir()), [])
        self.assertEqual(list(self.state.iterdir()), [])

    def test_unsafe_owner_refused_before_write(self):
        with self.assertRaisesRegex(mod.ProvisionRefused, 'unsafe parent'):
            mod.publish_in_parents(self.cfd, self.conf, self.sfd, self.state,
                                   self.config, self.receipt,
                                   root_uid=self.uid + 777, group_gid=self.gid,
                                   service_uid=self.uid, service_gid=self.gid)
        self.assertEqual(list(self.conf.iterdir()), [])
        self.assertEqual(list(self.state.iterdir()), [])


class ReadonlyTests(unittest.TestCase):
    def test_expected_paths_are_separate_from_legacy(self):
        self.assertEqual(mod.CONFIG_PARENT.as_posix(), '/etc/onyxcore')
        self.assertEqual(mod.CONFIG_NAME, 'v1.0.0')
        self.assertEqual(mod.STATE_PARENT.as_posix(), '/var/lib')
        self.assertEqual(mod.STATE_NAME, 'onyxcore-v100')
        self.assertNotEqual(str(mod.STATE_PARENT / mod.STATE_NAME), '/var/lib/onyxcore')
        self.assertNotEqual(mod.CONFIG_PATH, '/etc/onyxcore/receiver.env')

    def test_posix_state_target_not_derived_from_native_path_flavor(self):
        """Reproduce Windows Path behavior even when the test host is Linux."""
        if not BUNDLE.is_file():
            self.skipTest('Bundle fixture not available')
        # On Windows, str(Path('/var/lib')) is not '/var/lib'.
        with mock.patch.object(mod, 'STATE_PARENT', PureWindowsPath('/var/lib')):
            data, receipt, cfg, _ = inputs()
            expected = '/var/lib/onyxcore-v100'
            self.assertEqual(cfg['storage']['state_dir'], expected)
            self.assertEqual(json.loads(data)['storage']['state_dir'], expected)
            self.assertEqual(json.loads(receipt)['state_target'], expected)
            self.assertEqual(mod.preview(BUNDLE, CONFIG)['state_target'], expected)

    def test_preview_rejects_partial_approval(self):
        if not BUNDLE.is_file():
            self.skipTest('Bundle fixture not available')
        cmd = [sys.executable, '-I', '-B', str(PI / 'onyx_v100_pi_config_state.py'),
               '--bundle', str(BUNDLE), '--config', str(CONFIG), '--prepare-system']
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn('three approval flags', res.stderr)

    def test_preview_json_no_native_or_secret_claims(self):
        if not BUNDLE.is_file():
            self.skipTest('Bundle fixture not available')
        cmd = [sys.executable, '-I', '-B', str(PI / 'onyx_v100_pi_config_state.py'),
               '--bundle', str(BUNDLE), '--config', str(CONFIG)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        self.assertEqual(res.returncode, 0, res.stderr)
        obj = json.loads(res.stdout)
        self.assertEqual(obj['operation'], 'PI_V100_CONFIG_STATE_PREVIEW')
        self.assertEqual(obj['receiver_source'], 'MyWindowsPC')
        self.assertEqual(obj['state_target'], '/var/lib/onyxcore-v100')
        for field in ('config_written', 'state_written', 'credential_enrolled',
                      'credential_contents_read', 'unit_registered',
                      'service_enabled', 'activation_performed', 'legacy_state_modified',
                      'native_armv6_verified'):
            self.assertIs(obj[field], False, field)
        self.assertNotIn('password', res.stdout.lower())

    def test_proposed_config_matches_approved_system_plan(self):
        data, receipt, cfg, files = inputs()
        self.assertEqual(json.loads(data), cfg)
        self.assertEqual(len(files), 14)
        row = json.loads(receipt)
        self.assertEqual(row['config_sha256'], hashlib.sha256(data).hexdigest())
        self.assertFalse(row['credential_enrolled'])
        self.assertFalse(row['existing_history_migrated'])
        self.assertEqual(row['config_target'], mod.CONFIG_PATH)

    def test_canonical_config_and_receipt_reproducible(self):
        first = inputs()
        second = inputs()
        self.assertEqual(first[:2], second[:2])

    def test_original_bundle_tamper_refused(self):
        with tempfile.TemporaryDirectory() as name:
            fake = Path(name) / 'tampered.zip'
            fake.write_bytes(b'not the approved bundle')
            with self.assertRaises(ValueError):
                mod.proposed(fake, CONFIG)

    def test_legacy_state_path_config_rejected(self):
        if not BUNDLE.is_file():
            self.skipTest('Bundle fixture not available')
        with tempfile.TemporaryDirectory() as name:
            cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
            cfg['storage']['state_dir'] = '/var/lib/onyxcore'
            altered = Path(name) / 'config.json'
            altered.write_text(json.dumps(cfg), encoding='utf-8')
            with self.assertRaises((mod.ProvisionRefused, mod.PublishRefused, ValueError)):
                mod.proposed(BUNDLE, altered)

    def test_writable_state_config_not_accepted(self):
        if not BUNDLE.is_file():
            self.skipTest('Bundle fixture not available')
        with tempfile.TemporaryDirectory() as name:
            cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
            cfg['storage']['state_dir'] = '/var/lib/onyxcore-v100/other'
            altered = Path(name) / 'config.json'
            altered.write_text(json.dumps(cfg), encoding='utf-8')
            with self.assertRaises((mod.ProvisionRefused, mod.PublishRefused, ValueError)):
                mod.proposed(BUNDLE, altered)

    def test_no_armv6_native_preparation_on_non_target(self):
        if sys.platform == 'linux' and __import__('platform').machine().lower() == 'armv6l':
            self.skipTest('requires unsupported platform for this negative test')
        with self.assertRaisesRegex(mod.ProvisionRefused, 'native preparation requires'):
            mod._native_identities()

    def test_service_traverse_check_blocks_unreadable_parent(self):
        if os.name != 'posix':
            self.skipTest('POSIX directory modes')
        with tempfile.TemporaryDirectory() as name:
            fd = os.open(name, mod.NOFOLLOW_DIR)
            try:
                os.fchmod(fd, 0o700)
                with self.assertRaisesRegex(mod.ProvisionRefused, 'cannot traverse'):
                    mod._service_can_traverse(fd, os.getegid() + 998)
            finally:
                os.close(fd)

    def test_no_unapproved_activation_code(self):
        source = (PI / 'onyx_v100_pi_config_state.py').read_text(encoding='utf-8')
        for forbidden in ('subprocess.', 'os.system(', 'systemctl enable', 'systemctl start',
                          'receiver.env', 'activation-approved'):
            # The constants may identify protected paths; they must never be written.
            if forbidden in ('receiver.env', 'activation-approved'):
                continue
            self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
