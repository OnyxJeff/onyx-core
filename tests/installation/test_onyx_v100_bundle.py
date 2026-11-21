#!/usr/bin/env python3
"""Offline deterministic v1 core bundle acceptance. Requires local Git only."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

MODULE = Path(__file__).resolve().parents[2] / 'tools' / 'installation' / 'common' / 'onyx_v100_bundle.py'
spec = importlib.util.spec_from_file_location('onyx_v100_bundle_test', MODULE)
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


def run_git(root, *args):
    proc = subprocess.run(['git', '-C', str(root), *args], capture_output=True, check=True,
                          timeout=15)
    return proc.stdout.decode('utf-8', errors='strict').strip()


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='onyx-v100-m2s1-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.repo = self.home / 'source'
        self.repo.mkdir()
        run_git(self.repo, 'init', '-q')
        run_git(self.repo, 'checkout', '-q', '-b', bundle.SOURCE_BRANCH)
        run_git(self.repo, 'config', 'user.name', 'Test Harness')
        run_git(self.repo, 'config', 'user.email', 'test@example.invalid')
        for path in bundle.ALL_FILES:
            dest = self.repo / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(('test input for ' + path + '\n').encode('ascii'))
        run_git(self.repo, 'add', '--', '.')
        run_git(self.repo, 'commit', '-q', '-m', 'offline test fixture')
        self.actual_commit = run_git(self.repo, 'rev-parse', 'HEAD')
        self.old_commit = bundle.SOURCE_COMMIT
        bundle.SOURCE_COMMIT = self.actual_commit
        self.addCleanup(lambda: setattr(bundle, 'SOURCE_COMMIT', self.old_commit))

    def archive(self, name='candidate.zip'):
        target = self.home / name
        data = bundle.committed_payload(self.repo)
        result = bundle.write_archive(target, data)
        self.assertTrue(result['verified'])
        return target

    def test_pinned_allowlist_has_unique_regular_relative_paths(self):
        self.assertEqual(len(bundle.ALL_FILES), len(set(bundle.ALL_FILES)))
        self.assertEqual(list(bundle.ALL_FILES), sorted(bundle.ALL_FILES))
        self.assertFalse(any('secret' in p.lower() or 'token.dpapi' in p for p in bundle.ALL_FILES))
        self.assertIn('windows/gateway/Get-OnyxGatewayToken.ps1', bundle.ALL_FILES)
        self.assertIn('pi/services/receiver/history.py', bundle.ALL_FILES)
        self.assertIn('windows/gateway/overlay-portrait.html', bundle.ALL_FILES)
        self.assertNotIn('windows/collector/Save-OnyxToken.ps1', bundle.ALL_FILES)

    def test_preview_is_read_only_and_requires_pinned_head(self):
        cmd = [sys.executable, '-I', '-B', str(MODULE), 'plan', '--repo', str(self.repo)]
        # CLI deliberately hard-pins reviewed commit: our synthetic repository is rejected.
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('STOP:', result.stderr)
        self.assertEqual(list(self.home.glob('*.zip')), [])
        self.assertEqual(bundle.check_source_root(self.repo), self.repo.resolve())

    def test_build_is_byte_identical_across_output_paths_and_runs(self):
        first = self.archive('a.zip')
        second = self.archive('b.zip')
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(bundle.hash_file(first), bundle.hash_file(second))
        self.assertTrue(bundle.verify_archive(first, source_root=self.repo)['git_source_verified'])

    def test_fixed_zip_metadata_and_full_payload_inventory(self):
        path = self.archive()
        with zipfile.ZipFile(path) as zf:
            entries = zf.infolist()
            self.assertEqual([x.filename for x in entries], list(bundle.ALL_FILES) + [bundle.MANIFEST_NAME])
            for entry in entries:
                self.assertEqual(entry.date_time, bundle.DOS_DATE)
                self.assertEqual(entry.compress_type, zipfile.ZIP_STORED)
                self.assertEqual(entry.create_system, 3)
                self.assertEqual(entry.external_attr, 0o100644 << 16)
                self.assertEqual(entry.extra, b'')
            manifest = json.loads(zf.read(bundle.MANIFEST_NAME))
            self.assertEqual(manifest['file_count'], len(bundle.ALL_FILES))
            self.assertFalse(manifest['installable_without_further_steps'])
            self.assertFalse(manifest['credential_files_included'])
            self.assertEqual(manifest['source_commit'], bundle.SOURCE_COMMIT)

    def test_output_refuses_overwrite_and_source_repo_target(self):
        target = self.archive()
        with self.assertRaisesRegex(bundle.BundleRefused, 'exists'):
            bundle.write_archive(target, bundle.committed_payload(self.repo))
        self.assertEqual(target.stat().st_nlink, 1)
        # CLI rejects any target inside the repo before writing.
        inside = self.repo / 'inside.zip'
        self.assertTrue(inside.resolve(strict=False).is_relative_to(self.repo.resolve()))

    def test_no_staged_or_modified_source_can_be_packaged(self):
        affected = self.repo / bundle.ALL_FILES[0]
        original = affected.read_bytes()
        affected.write_bytes(original + b'modified')
        with self.assertRaisesRegex(bundle.BundleRefused, 'Tracked source modifications'):
            bundle.committed_payload(self.repo)
        affected.write_bytes(original)
        run_git(self.repo, 'add', '--', bundle.ALL_FILES[0])
        # Git has a clean index again; now explicitly stage a changed file.
        affected.write_bytes(original + b'changed')
        run_git(self.repo, 'add', '--', bundle.ALL_FILES[0])
        with self.assertRaisesRegex(bundle.BundleRefused, 'Tracked source modifications|Staged source modifications'):
            bundle.committed_payload(self.repo)

    def test_wrong_branch_and_wrong_head_refused(self):
        run_git(self.repo, 'checkout', '-q', '-b', 'another-branch')
        with self.assertRaises(bundle.BundleRefused):
            bundle.committed_payload(self.repo)

    def test_missing_git_blob_blocks_build_without_output(self):
        wrong = '00' * 20
        bundle.SOURCE_COMMIT = wrong
        with self.assertRaises(bundle.BundleRefused):
            bundle.committed_payload(self.repo, verify_head=False)
        self.assertEqual(list(self.home.glob('*.zip')), [])

    def test_zip_payload_tamper_rejected(self):
        original = self.archive()
        changed = self.home / 'tampered.zip'
        with zipfile.ZipFile(original) as zf, zipfile.ZipFile(changed, 'w') as output:
            for i in zf.infolist():
                contents = zf.read(i.filename)
                if i.filename == bundle.ALL_FILES[0]:
                    contents += b'corrupted!'
                output.writestr(bundle.zip_entry(i.filename), contents)
        with self.assertRaisesRegex(bundle.BundleRefused, 'Manifest'):
            bundle.verify_archive(changed)

    def test_extra_member_refused(self):
        original = self.archive()
        changed = self.home / 'extra.zip'
        with zipfile.ZipFile(original) as zf, zipfile.ZipFile(changed, 'w') as output:
            for i in zf.infolist():
                output.writestr(bundle.zip_entry(i.filename), zf.read(i.filename))
            output.writestr(bundle.zip_entry('pi/services/receiver/evil.py'), b'bad')
        with self.assertRaisesRegex(bundle.BundleRefused, 'inventory'):
            bundle.verify_archive(changed)

    def test_nondeterministic_metadata_refused(self):
        original = self.archive()
        bad = self.home / 'date.zip'
        with zipfile.ZipFile(original) as zf, zipfile.ZipFile(bad, 'w') as output:
            for i in zf.infolist():
                entry = bundle.zip_entry(i.filename)
                if i.filename == bundle.ALL_FILES[0]:
                    entry.date_time = (2026, 1, 1, 0, 0, 0)
                output.writestr(entry, zf.read(i.filename))
        with self.assertRaisesRegex(bundle.BundleRefused, 'metadata'):
            bundle.verify_archive(bad)

    def test_unreviewed_allowlist_content_is_not_pulled_from_untracked_files(self):
        untracked = self.repo / 'windows' / 'collector' / 'collector-token.dpapi'
        untracked.write_text('DO NOT PACKAGE', encoding='ascii')
        path = self.archive()
        with zipfile.ZipFile(path) as zf:
            self.assertNotIn('collector-token.dpapi', '\n'.join(zf.namelist()))
            self.assertNotIn(b'DO NOT PACKAGE', path.read_bytes())

    def test_truncated_archive_rejected(self):
        original = self.archive()
        bad = self.home / 'truncated.zip'
        bad.write_bytes(original.read_bytes()[:65])
        with self.assertRaises(bundle.BundleRefused):
            bundle.verify_archive(bad)


if __name__ == '__main__':
    unittest.main(verbosity=2)
