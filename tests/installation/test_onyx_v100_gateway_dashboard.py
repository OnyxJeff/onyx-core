#!/usr/bin/env python3
"""Offline tests for reproducible v1 gateway dashboard portability correction."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PARSER = argparse.ArgumentParser(add_help=False)
PARSER.add_argument('--source', type=Path)
PARSER.add_argument('--artifact', type=Path)
ARGS, REST = PARSER.parse_known_args()
sys.argv[:] = [sys.argv[0]] + REST

HERE = Path(__file__).resolve().parents[2]
TOOL_DIR = HERE / 'tools/installation/windows'
if not (TOOL_DIR / 'onyx_v100_make_dashboard.py').exists():
    TOOL_DIR = HERE.parent.parent / 'tools/installation/windows'
sys.path.insert(0, str(TOOL_DIR))
import onyx_v100_make_dashboard as make  # noqa: E402


def source_file():
    return ARGS.source or HERE / 'windows/gateway/gateway-dashboard.html'


def artifact_file():
    return ARGS.artifact or HERE / 'windows/gateway/gateway-dashboard-v100.html'


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = source_file().read_bytes()
        cls.expected = artifact_file().read_bytes()

    def test_source_git_fingerprint(self):
        self.assertEqual(hashlib.sha256(make.normalize(self.raw)).hexdigest(),
                         make.EXPECTED_LEGACY_SHA256)

    def test_versioned_dashboard_deterministic(self):
        self.assertEqual(make.transform(self.raw), self.expected)
        self.assertEqual(make.transform(self.raw), make.transform(self.raw))

    def test_source_preserved_in_transform(self):
        before = bytes(self.raw)
        make.transform(self.raw)
        self.assertEqual(self.raw, before)

    def test_lf_and_windows_crlf(self):
        raw = make.normalize(self.raw)
        self.assertEqual(make.transform(raw), make.transform(raw.replace(b'\n', b'\r\n')))

    def test_malformed_or_mixed_line_endings_refused(self):
        raw = make.normalize(self.raw)
        with self.assertRaises(make.DashboardRefused):
            make.transform(raw.replace(b'\n', b'\r\r\n'))
        with self.assertRaises(make.DashboardRefused):
            make.transform(raw.replace(b'\n', b'\r\n', 1))

    def test_unreviewed_base_refused(self):
        self.assertRaises(make.DashboardRefused, make.transform, self.raw + b'<!-- tamper -->')

    def test_no_legacy_workstation_branding(self):
        self.assertNotIn('SQUALL', self.expected.decode())
        self.assertIn('USB TELEMETRY', self.expected.decode())

    def test_gateway_mode_independent_of_fixed_ports(self):
        s = self.expected.decode()
        self.assertIn("const gatewayMode=location.protocol==='http:'&&location.hostname==='127.0.0.1';", s)
        self.assertNotIn("['http://127.0.0.1:18766'", s)
        self.assertIn("const options=gatewayMode?{cache:'no-store'}", s)
        self.assertIn("if(gatewayMode){", s)

    def test_strict_source_contract(self):
        old, new = make.REPLACEMENTS[-1]
        s = self.raw.decode('utf-8')
        self.assertEqual(s.count(old), 1)
        self.assertNotIn(new, s)
        self.assertNotIn(old, self.expected.decode())

    def test_cli_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'orig.html'
            out = Path(d) / 'new.html'
            src.write_bytes(self.raw)
            out.write_bytes(b'preserve')
            run = subprocess.run([sys.executable, '-I', '-B', str(Path(make.__file__)),
                                  '--source', str(src), '--output', str(out)],
                                 capture_output=True, text=True, timeout=8)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(out.read_bytes(), b'preserve')

    def test_cli_produces_exact_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'orig.html'
            out = Path(d) / 'new.html'
            src.write_bytes(self.raw)
            run = subprocess.run([sys.executable, '-I', '-B', str(Path(make.__file__)),
                                  '--source', str(src), '--output', str(out)],
                                 capture_output=True, text=True, timeout=8)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(out.read_bytes(), self.expected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
