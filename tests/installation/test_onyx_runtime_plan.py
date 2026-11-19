#!/usr/bin/env python3
"""Five focused offline installation inventory and launch-plan checks."""
import hashlib,importlib.util,json,shutil,tempfile,unittest,uuid
from pathlib import Path

src=Path(__file__).resolve().parents[2]/'tools/installation/common/onyx_runtime_plan.py'
spec=importlib.util.spec_from_file_location('onyx_runtime_plan',src)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
COMMIT='a'*40
REQUIRED={
'windows':['windows/collector/Send-OnyxTelemetry.ps1','windows/collector/Launch-OnyxTelemetry.vbs',
           'windows/gateway/OnyxGateway.py','windows/gateway/gateway-dashboard.html'],
'pi-armv6':['pi/services/receiver/receiver.py','pi/services/receiver/integrated_store.py',
            'pi/services/receiver/history.py','pi/services/receiver/health.py',
            'tools/installation/pi/launch-onyx-v090-receiver.sh',
            'tools/installation/pi/onyxcore-v090-receiver.service',
            'tools/installation/pi/90-onyx-v090-receiver']}

def stage(platform):
    root=Path(tempfile.gettempdir())/('OnyxV090-'+uuid.uuid4().hex)
    root.mkdir()
    rows=[]
    for rel in sorted(REQUIRED[platform]):
        file=root/rel
        file.parent.mkdir(parents=True,exist_ok=True)
        payload=('test '+rel+'\n').encode()
        file.write_bytes(payload)
        rows.append({'path':rel,'size':len(payload),'sha256':hashlib.sha256(payload).hexdigest()})
    man={'schema_version':1,'product':'ONYX CORE','version':'0.9.0-rc1','platform':platform,'source_commit':COMMIT,'files':rows}
    rec={'status':'PREPARED','platform':platform,'version':man['version'],'source_commit':COMMIT,
         'archive_sha256':'b'*64,'target':str(root),'file_count':len(rows),'activated':False,'mode':'inactive-code-only'}
    (root/'manifest.json').write_bytes(m._canonical(man))
    (root/'installation-receipt.json').write_bytes(m._canonical(rec))
    return root

class RuntimePlanTests(unittest.TestCase):
    def setUp(self):self.paths=[]
    def tearDown(self):
        for p in self.paths:shutil.rmtree(p,ignore_errors=True)
    def make(self,platform):
        root=stage(platform);self.paths.append(root);return root
    def test_windows_plan_is_inert_and_port_separate(self):
        p=m.plan(self.make('windows'),COMMIT,'windows')
        self.assertFalse(p['activated'])
        self.assertEqual(18769,p['proposal']['candidate_gateway_loopback_port'])
        self.assertEqual(18766,p['proposal']['production_gateway_reserved_port'])
    def test_pi_plan_uses_versioned_paths_and_existing_external_data(self):
        p=m.plan(self.make('pi-armv6'),COMMIT,'pi-armv6')
        self.assertFalse(p['activated'])
        self.assertEqual('/var/lib/onyxcore/telemetry.db',p['proposal']['database_path'])
        self.assertTrue(p['proposal']['script_target'].startswith('/opt/onyxcore/v0.9.0/'))
    def test_modified_file_refused(self):
        root=self.make('windows')
        (root/'windows/gateway/OnyxGateway.py').write_bytes(b'TAMPER')
        with self.assertRaises(m.PlanRefused):m.plan(root,COMMIT,'windows')
    def test_wrong_commit_and_platform_refused(self):
        root=self.make('pi-armv6')
        with self.assertRaises(m.PlanRefused):m.plan(root,'c'*40,'pi-armv6')
        with self.assertRaises(m.PlanRefused):m.plan(root,COMMIT,'windows')
    def test_unexpected_files_refused(self):
        root=self.make('pi-armv6')
        (root/'unapproved.py').write_text('print(1)')
        with self.assertRaises(m.PlanRefused):m.plan(root,COMMIT,'pi-armv6')

if __name__=='__main__':unittest.main(verbosity=2)
