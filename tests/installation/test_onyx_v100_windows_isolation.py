#!/usr/bin/env python3
"""Offline acceptance for M2-S4A; no system credentials or live services."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve()
TOOL = HERE.parents[2] / 'tools/installation/windows/onyx_v100_windows_isolation.py'
BUNDLE = Path(os.environ.get('ONYX_V100_BUNDLE', ''))
spec = importlib.util.spec_from_file_location('isolation_tool', TOOL)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class IsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BUNDLE.is_file():
            raise RuntimeError('set ONYX_V100_BUNDLE to the approved candidate ZIP')
        cls.files, cls.manifest = mod.expected(BUNDLE)

    def call(self, *args):
        return subprocess.run([sys.executable, '-I', '-B', str(TOOL), '--bundle', str(BUNDLE), *args],
                              capture_output=True, text=True, timeout=20)

    def test_fixed_source_sha(self):
        self.assertEqual(mod.sha_file(BUNDLE), mod.BUNDLE_SHA256)

    def test_exact_derived_inventory(self):
        self.assertEqual(set(self.files), set(mod.SOURCES))
        self.assertEqual(self.manifest['file_count'], 3)

    def test_exact_provenance(self):
        self.assertEqual(self.manifest['source_commit'], mod.COMMIT)
        self.assertEqual(self.manifest['bundle_sha256'], mod.BUNDLE_SHA256)
        self.assertEqual(self.manifest['schema_version'], 1)

    def test_versioned_token_storage(self):
        p = self.files['windows/gateway/Get-OnyxGatewayToken.ps1']
        self.assertIn(b"'OnyxCore-v100\\collector-token.dpapi'", p)
        self.assertNotIn(b"'OnyxCore\\collector-token.dpapi'", p)

    def test_collector_unique_mutex(self):
        p = self.files['windows/collector/Send-OnyxTelemetry-v100.ps1']
        self.assertIn(b"'Local\\OnyxCoreV100Collector'", p)
        self.assertNotIn(b"'Local\\OnyxCoreCollector'", p)

    def test_collector_unique_data_directory(self):
        p = self.files['windows/collector/Send-OnyxTelemetry-v100.ps1']
        self.assertIn(b"$logDir = Join-Path $env:LOCALAPPDATA 'OnyxCore-v100'", p)
        self.assertNotIn(b"$logDir = Join-Path $env:LOCALAPPDATA 'OnyxCore'", p)

    def test_launcher_requires_versioned_token(self):
        p = self.files['tools/installation/windows/Invoke-OnyxV100WindowsRuntime.ps1']
        self.assertIn(b"'OnyxCore-v100\\collector-token.dpapi'", p)
        self.assertNotIn(b"'OnyxCore\\collector-token.dpapi'", p)

    def test_powershell_bom_preserved(self):
        self.assertTrue(self.files['windows/collector/Send-OnyxTelemetry-v100.ps1'].startswith(b'\xef\xbb\xbf'))

    def test_no_credentials_or_production_data(self):
        self.assertFalse(self.manifest['credential_enrolled'])
        self.assertFalse(self.manifest['production_modified'])
        self.assertTrue(self.manifest['requires_install_integration'])
        for p in self.files:
            self.assertNotIn('database', p.lower())

    def test_preview_has_no_output(self):
        r = self.call()
        self.assertEqual(r.returncode, 0, r.stderr)
        x = json.loads(r.stdout)
        self.assertFalse(x['installation_performed'])
        self.assertFalse(x['integration_completed'])

    def test_partial_approval_is_refused(self):
        r = self.call('--approve-build')
        self.assertEqual(r.returncode, 2)
        self.assertIn('build approval without output', r.stderr)

    def test_output_requires_explicit_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'isolated'
            r = self.call('--output', str(p))
            self.assertEqual(r.returncode, 2)
            self.assertFalse(p.exists())

    def test_built_files_verified_in_disposable_dir(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'isolated'
            r = self.call('--output', str(p), '--approve-build')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)['file_count'], 3)
            mod.read_verified(p, self.files, self.manifest)
            r2 = self.call('--verify-directory', str(p))
            self.assertEqual(r2.returncode, 0, r2.stderr)

    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'isolated'
            self.assertEqual(self.call('--output', str(p), '--approve-build').returncode, 0)
            self.assertEqual(self.call('--output', str(p), '--approve-build').returncode, 2)
            mod.read_verified(p, self.files, self.manifest)

    def test_tampered_derived_file_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'isolated'
            self.assertEqual(self.call('--output', str(p), '--approve-build').returncode, 0)
            f = p / 'windows/gateway/Get-OnyxGatewayToken.ps1'
            f.write_bytes(f.read_bytes() + b'evil\n')
            self.assertEqual(self.call('--verify-directory', str(p)).returncode, 2)

    def test_extra_derived_file_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'isolated'
            self.assertEqual(self.call('--output', str(p), '--approve-build').returncode, 0)
            (p / 'unexpected.txt').write_text('x')
            self.assertEqual(self.call('--verify-directory', str(p)).returncode, 2)

    def test_manifest_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'isolated'
            self.assertEqual(self.call('--output', str(p), '--approve-build').returncode, 0)
            f = p / mod.MANIFEST_NAME
            f.write_bytes(f.read_bytes() + b' ')
            self.assertEqual(self.call('--verify-directory', str(p)).returncode, 2)

    def test_wrong_bundle_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'bad.zip'
            p.write_bytes(BUNDLE.read_bytes() + b'junk')
            r = subprocess.run([sys.executable, '-I', '-B', str(TOOL), '--bundle', str(p)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)
            self.assertIn('SHA256 mismatch', r.stderr)

    def test_generator_deterministic_bytes(self):
        first, manifest = mod.expected(BUNDLE)
        second, second_manifest = mod.expected(BUNDLE)
        self.assertEqual(first, second)
        self.assertEqual(mod.canonical(manifest), mod.canonical(second_manifest))

    def test_source_has_no_live_mutations(self):
        src = TOOL.read_text('utf-8')
        for token in ['Register-ScheduledTask','systemctl enable','ssh ','Invoke-RestMethod',
                      'ConvertFrom-SecureString','Set-Content -Path']:
            self.assertNotIn(token, src)

    def test_paths_do_not_overlap_legacy(self):
        self.assertNotEqual(self.manifest['logging_directory'], '%LOCALAPPDATA%\\OnyxCore')
        self.assertNotEqual(self.manifest['collector_mutex'], 'Local\\OnyxCoreCollector')


if __name__ == '__main__':
    unittest.main(verbosity=2)
