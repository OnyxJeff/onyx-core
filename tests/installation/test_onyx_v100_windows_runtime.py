#!/usr/bin/env python3
"""M1-S6B offline generator and launcher safety contract tests (no host changes)."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / 'tools/installation/windows/onyx_v100_make_windows_runtime.py'
LAUNCHER = ROOT / 'tools/installation/windows/Invoke-OnyxV100WindowsRuntime.ps1'

spec = importlib.util.spec_from_file_location('v100win_generator', GENERATOR)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

COLLECTOR = '''[CmdletBinding()]
param(
    [string]$Receiver = 'svr-onyxcore.local',
    [string]$AdapterName = 'Ethernet',
    [switch]$DryRun
)
if ($DryRun -and $Count -eq 0) { throw 'DryRun requires a finite -Count.' }
$endpoint = "http://${Receiver}:8765/api/v1/telemetry"
if ($current -eq '/Sensor/SQUALL/AMD Ryzen 7 5800X/Temperatures/Core (Tctl/Tdie)') {
$tree = Invoke-RestMethod -Uri 'http://192.168.137.1:8085/data.json' -TimeoutSec 2 -ErrorAction Stop
                source = 'SQUALL'
            if (-not $DryRun) { Add-CpuTemperatureMetrics -Metrics $metrics }
'''
GATEWAY = '''def main():
    p.add_argument('--receiver', default='svr-onyxcore.local')
    if not 1024 <= args.port <= 65535:
        p.error('invalid port')
    server.upstream = f'http://{args.receiver}:8765'
'''


class WindowsRuntimeTests(unittest.TestCase):
    def test_expected_git_object_ids_are_pinned(self):
        self.assertEqual(mod.SOURCES['collector'][2], '74abf45a9a275a311477c164e3e9dee583a181b4')
        self.assertEqual(mod.SOURCES['gateway'][2], '4e9d3fb40d50eaa558ed2b1476c75db03179dcfd')

    def test_canonical_checkout_accepts_lf_and_crlf(self):
        blob = b'alpha\nbeta\n'
        self.assertEqual(mod.canonical_bytes(blob), blob)
        self.assertEqual(mod.canonical_bytes(blob.replace(b'\n', b'\r\n')), blob)
        self.assertEqual(mod.blob_sha(blob), mod.blob_sha(mod.canonical_bytes(blob.replace(b'\n', b'\r\n'))))

    def test_mixed_source_line_endings_refused(self):
        for value in (b'x\r\ny\n', b'x\ry', b'x\r\ny\r\nZ\n'):
            with self.assertRaises(mod.GenerationRefused):
                mod.canonical_bytes(value)

    def test_unreviewed_source_has_wrong_blob(self):
        self.assertNotEqual(mod.blob_sha(b'not the original collector'), mod.SOURCES['collector'][2])

    def test_collector_configurable_parameters_and_port(self):
        out = mod.transform_collector(COLLECTOR)
        self.assertIn('${Receiver}:${ReceiverPort}/api/v1/telemetry', out)
        self.assertIn('source = $Source', out)
        self.assertIn('$CpuSensorEndpoint -TimeoutSec 2', out)
        self.assertIn('if (-not $DryRun -and $EnableCpuTemperature)', out)
        self.assertIn('if ($current -eq $CpuSensorPath)', out)
        self.assertIn('Parameter(Mandatory=$true)', out)
        self.assertNotIn('192.168.137.1:8085', out)
        self.assertNotIn('SQUALL', out)

    def test_collector_unreviewed_or_duplicate_signature_refused(self):
        for src in (COLLECTOR.replace('source = \'SQUALL\'', 'source = \'OTHER\''),
                    COLLECTOR + '                source = \'SQUALL\'\n'):
            with self.assertRaises(mod.GenerationRefused):
                mod.transform_collector(src)

    def test_gateway_configurable_upstream_port(self):
        out = mod.transform_gateway(GATEWAY)
        self.assertIn("p.add_argument('--receiver-port', type=int, required=True)", out)
        self.assertIn("server.upstream = f'http://{args.receiver}:{args.receiver_port}'", out)
        self.assertIn("p.error('invalid receiver port')", out)
        self.assertNotIn("default='svr-onyxcore.local'", out)
        compile(out, '<versioned-gateway-fixture>', 'exec')

    def test_gateway_unreviewed_or_duplicate_signature_refused(self):
        for src in (GATEWAY.replace("{args.receiver}:8765", "{args.receiver}:1111"),
                    GATEWAY + "    server.upstream = f'http://{args.receiver}:8765'\n"):
            with self.assertRaises(mod.GenerationRefused):
                mod.transform_gateway(src)

    def test_generator_refuses_wrong_paths_and_existing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            src = folder / 'Send-OnyxTelemetry.ps1'
            dst = folder / 'Send-OnyxTelemetry-v100.ps1'
            src.write_text(COLLECTOR)
            with self.assertRaises(mod.GenerationRefused):
                mod.build('collector', src, folder / 'bad.ps1')
            dst.write_text('preexisting')
            with self.assertRaises(mod.GenerationRefused):
                mod.build('collector', src, dst)
            self.assertEqual(dst.read_text(), 'preexisting')

    def test_generator_fails_closed_without_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            src = folder / 'Send-OnyxTelemetry.ps1'
            dst = folder / 'Send-OnyxTelemetry-v100.ps1'
            src.write_text(COLLECTOR)
            with self.assertRaises(mod.GenerationRefused):
                mod.build('collector', src, dst)
            self.assertFalse(dst.exists())

    def test_no_live_run_during_import(self):
        self.assertTrue(LAUNCHER.is_file())
        script = LAUNCHER.read_text(encoding='ascii')
        self.assertIn('if (-not $Run) {', script)
        self.assertIn('if ($Run -and -not $ApproveExecution)', script)
        self.assertIn("throw 'Existing ONYX CORE task detected", script)
        self.assertIn("if ($DryRun) { $Argv += '-DryRun' }", script)
        self.assertIn('--receiver-port', script)
        self.assertNotIn('Start-ScheduledTask', script)
        self.assertNotIn('Register-ScheduledTask', script)
        self.assertNotIn('Invoke-RestMethod', script)
        self.assertNotIn('ConvertTo-SecureString', script)

    def test_no_squall_or_fixed_receiver_address_in_launcher(self):
        script = LAUNCHER.read_text(encoding='ascii')
        self.assertNotIn('SQUALL', script)
        self.assertNotIn('192.168.137.', script)
        self.assertNotIn('C:\\Python313', script)


if __name__ == '__main__':
    unittest.main(verbosity=2)
