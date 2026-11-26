"""Offline tests against the frozen source; no actual collector execution."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'tools/installation/common'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

c = load('onyx_v100_m5_candidate')
h = load('onyx_v100_m5_collector_hotfix')

class HotfixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = c.zip_bytes('windows', {p:(ROOT/p).read_bytes().replace(b'\r\n',b'\n') for p in c.ROLES['windows']})
        cls.launcher = (ROOT/h.SOURCE_LAUNCHER).read_bytes()

    def test_deterministic_and_line_endings(self):
        a = h.candidate(self.base, self.launcher)
        b = h.candidate(self.base, self.launcher.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
        self.assertEqual(a,b)

    def test_exact_payload_delta(self):
        with zipfile.ZipFile(io.BytesIO(self.base)) as old, zipfile.ZipFile(io.BytesIO(h.candidate(self.base,self.launcher))) as new:
            self.assertEqual(set(new.namelist())-set(old.namelist()),{h.LAUNCHER})
            self.assertEqual(set(old.namelist())-set(new.namelist()),set())
            for name in old.namelist():
                if name not in (h.COLLECTOR,h.MANIFEST): self.assertEqual(old.read(name),new.read(name))
            collector = new.read(h.COLLECTOR)
            self.assertIn(b'[switch]$RequireLauncher',collector)
            self.assertIn(b'Local\\OnyxCoreV100Collector',collector)
            self.assertIn(b'OnyxCore-v100',collector)
            self.assertLess(collector.index(b'Expected supervised launcher missing'),collector.index(b'ConvertTo-SecureString'))
            self.assertEqual(collector.replace(b'    [switch]$RequireLauncher,\n',b'').replace(b"        if ($RequireLauncher -and $null -eq $launcherPid) { throw 'Expected supervised launcher missing.' }\n",b''),old.read(h.COLLECTOR))

    def test_manifest(self):
        with zipfile.ZipFile(io.BytesIO(h.candidate(self.base,self.launcher))) as z:
            m=json.loads(z.read(h.MANIFEST))
            self.assertEqual(m['base_archive_sha256'],h.BASE_SHA)
            self.assertEqual(len(m['files']),25)
            self.assertFalse(m['activation_performed'])
            for row in m['files']:
                self.assertEqual(h.sha(z.read(row['path'])),row['sha256'])

    def test_bad_inputs(self):
        with self.assertRaises(ValueError): h.candidate(self.base+b'x',self.launcher)
        with self.assertRaises(ValueError): h.candidate(self.base,self.launcher+b'x')

    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'candidate.zip'
            h.build(self.base,self.launcher,p)
            before=p.read_bytes()
            with self.assertRaises(FileExistsError): h.build(self.base,self.launcher,p)
            self.assertEqual(before,p.read_bytes())

    def test_launcher_static_contract(self):
        for part in (b'shell.Run(command, 0, True)',b'WScript.Quit result',b'-RequireLauncher',b'GetSpecialFolder(1)',b'Send-OnyxTelemetry-v100.ps1',b'InStr(value, "%")'):
            self.assertIn(part,self.launcher)
        self.assertNotIn(b'collector-token.dpapi',self.launcher)

if __name__=='__main__': unittest.main()
