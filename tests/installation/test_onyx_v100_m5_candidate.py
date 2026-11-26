"""Offline artifact tests; never call native admission, credential or probe APIs."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'tools/installation/common/onyx_v100_m5_candidate.py'
spec = importlib.util.spec_from_file_location('m5_candidate', MODULE)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Only test fixtures may use review exports. The real CLI always reads
        # the pinned commit via Git and verifies every input fingerprint.
        root = Path(os.environ.get('ONYX_M5_TEST_SOURCE', str(ROOT)))
        cls.data = {role: {p: (root/p).read_bytes().replace(b'\r\n', b'\n')
                          for p in paths} for role, paths in c.ROLES.items()}
        for role, data in cls.data.items():
            c.check_inputs(role, data)

    def test_deterministic_role_packages(self):
        for role, data in self.data.items():
            first = c.zip_bytes(role, data)
            self.assertEqual(first, c.zip_bytes(role, dict(reversed(list(data.items())))))
            with zipfile.ZipFile(io.BytesIO(first)) as z:
                self.assertEqual(z.namelist(), sorted(set(c.payload(role,data)) | {c.MANIFEST}))
                m = json.loads(z.read(c.MANIFEST))
                self.assertEqual(m['source_commit'], c.COMMIT)
                self.assertFalse(m['native_installation_approved'])
                self.assertFalse(m['credential_files_included'])
                for row in m['files']:
                    self.assertEqual(c.sha(z.read(row['path'])), row['sha256'])
                    self.assertEqual(len(z.read(row['path'])), row['size'])
                    self.assertEqual(z.getinfo(row['path']).date_time, (1980,1,1,0,0,0))
                self.assertFalse(any(x.endswith(('.dpapi','.db','.env','.key','.sqlite3')) for x in z.namelist()))

    def test_refuses_changed_or_extra_input(self):
        data = dict(self.data['windows'])
        data[c.GATEWAY] += b'\n'
        with self.assertRaises(c.Refused): c.zip_bytes('windows', data)
        data = dict(self.data['windows']); data['extra'] = b'x'
        with self.assertRaises(c.Refused): c.zip_bytes('windows', data)
        data = dict(self.data['windows']); del data[c.GATEWAY]
        with self.assertRaises(c.Refused): c.zip_bytes('windows', data)

    def test_no_overwrite_and_tamper_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve()/'candidate.zip'
            c.build(target,'windows',self.data['windows'])
            original = target.read_bytes()
            with self.assertRaises(c.Refused): c.build(target,'windows',self.data['windows'])
            self.assertEqual(target.read_bytes(),original)
            with self.assertRaises(c.Refused): c.verify(target,'pi-armv6',self.data['pi-armv6'])
            target.write_bytes(original+b'x')
            with self.assertRaises(c.Refused): c.verify(target,'windows',self.data['windows'])

    def test_isolation_contract(self):
        out = c.payload('windows',self.data['windows'])
        self.assertIn(b"'Local\\OnyxCoreV100Collector'",out[c.COLLECTOR])
        self.assertIn(b"'OnyxCore-v100'",out[c.COLLECTOR])
        for path in (c.HELPER,c.LAUNCHER):
            self.assertIn(b'OnyxCore-v100\\collector-token.dpapi',out[path])
            self.assertNotIn(b'OnyxCore\\collector-token.dpapi',out[path])
        self.assertEqual(out[c.DASH_ALIAS],out[c.DASHBOARD])
        self.assertIn(b'& $PythonPath -I -B $Gateway @GatewayArgs',out[c.LAUNCHER])
        self.assertIn(b"if ($EnableMonitoringView) { $GatewayArgs += '--v100-monitor-view' }",out[c.LAUNCHER])
        self.assertIn(b'ONYX CORE v1.0.0 - Local Gateway',out[c.LAUNCHER])
        self.assertFalse(any(p.startswith('pi/') for p in out))
        self.assertFalse(any(p.startswith('windows/') for p in c.payload('pi-armv6',self.data['pi-armv6'])))

    def fixture(self, tmp, role):
        root = Path(tmp).resolve()/'candidate'
        with zipfile.ZipFile(io.BytesIO(c.zip_bytes(role,self.data[role]))) as archive:
            archive.extractall(root)  # only deterministic allowlisted local fixture bytes
        return root

    def test_installed_gateway_isolated_import_and_projection(self):
        # Stub the server constructor to avoid all network I/O. Supply only a
        # synthetic stdin token; the real DPAPI helper is never invoked.
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fixture(tmp,'windows')
            local = Path(tmp).resolve()/'local'; local.mkdir()
            code = r'''
import http.server,io,os,runpy,sys
from pathlib import Path
root=Path(sys.argv[1]); local=Path(sys.argv[2]); os.environ['LOCALAPPDATA']=str(local)
class FakeServer:
    def __init__(self,addr,handler): assert addr==('127.0.0.1',18976)
    def serve_forever(self,**kwargs):
        assert self.v100_monitor_view
        result=self.monitor_reader()
        assert result['state']=='NoData' and result['source']=='OnyxV100MonitoringView'
        assert not (local/'OnyxCore-v100').exists()
        for name in ('OnyxV100MonitoringView','OnyxMonitoringView','OnyxLiveIncidentHistory','OnyxContinuousMonitor','OnyxLiveConnectivity','OnyxMonitorConfig'):
            assert Path(sys.modules[name].__file__).resolve().is_relative_to(root)
    def server_close(self): pass
http.server.ThreadingHTTPServer=FakeServer
sys.stdin=io.StringIO('fixture-not-a-real-token-'+'x'*32+'\n')
p=root/'windows/gateway/OnyxGateway_v100.py'
sys.argv=[str(p),'--dashboard',str(p.with_name('gateway-dashboard.html')),'--receiver','127.0.0.1','--receiver-port','8765','--port','18976','--v100-monitor-view']
runpy.run_path(str(p),run_name='__main__')
'''
            result = subprocess.run([sys.executable,'-I','-B','-c',code,str(root),str(local)],cwd=tmp,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse((local/'OnyxCore-v100').exists())

    def test_standalone_recorder_and_assessment_help(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fixture(tmp,'windows')
            for name in ('OnyxV100RecoveryAssessment.py','OnyxV100SupervisedRecorder.py'):
                p = root/'windows/monitoring/v100'/name
                result = subprocess.run([sys.executable,'-I','-B',str(p),'--help'],cwd=tmp,capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('--adapter',result.stdout)

    def test_standalone_pi_entrypoints_and_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fixture(tmp,'pi-armv6')
            for rel in ('tools/installation/pi/onyx_v100_pi_launch.py','pi/services/receiver/receiver_v100.py'):
                result = subprocess.run([sys.executable,'-B',str(root/rel),'--help'],cwd=tmp,capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr)
            code = '''import sys; from pathlib import Path
sys.path.insert(0,sys.argv[1]); import integrated_store_v100,health,history
assert health.evaluate_health('2026-11-25T00:00:00Z')['status'] in ('healthy','warning','critical','unknown')
'''
            result=subprocess.run([sys.executable,'-I','-B','-c',code,str(root/'pi/services/receiver')],cwd=tmp,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_pi_state_isolation(self):
        out = c.payload('pi-armv6',self.data['pi-armv6'])
        for name in ('pi-armv6.config.example.json','pi-armv6.system.config.example.json'):
            self.assertEqual(json.loads(out['docs/v1.0.0/examples/'+name])['storage']['state_dir'],'/var/lib/onyxcore-v100')
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fixture(tmp,'pi-armv6')
            code = r"""
import sys,json
from pathlib import Path
root=Path(sys.argv[1]); sys.path.insert(0,str(root/'tools/installation/pi'))
import onyx_v100_pi_launch as launch
cfg=json.loads((root/'docs/v1.0.0/examples/pi-armv6.config.example.json').read_bytes())
cfg['storage']['state_dir']='/var/lib/onyxcore'
try: launch.plan(cfg,'[]',root)
except launch.LaunchRefused as exc: assert 'isolated v100 state' in str(exc)
else: raise AssertionError('legacy state admitted')
"""
            result=subprocess.run([sys.executable,'-I','-B','-c',code,str(root)],cwd=tmp,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_linked_output_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); actual=root/'actual'; actual.mkdir(); link=root/'link'
            try: link.symlink_to(actual,target_is_directory=True)
            except OSError: self.skipTest('symlink privilege unavailable')
            with self.assertRaises(c.Refused): c.build(link/'candidate.zip','windows',self.data['windows'])
            self.assertFalse((actual/'candidate.zip').exists())


if __name__ == '__main__': unittest.main()
