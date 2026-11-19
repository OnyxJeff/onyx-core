#!/usr/bin/env python3
"""Two end-to-end build -> verified inactive install -> read-only plan checks."""
import hashlib,importlib.util,shutil,tempfile,unittest,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def load(name,relative):
    spec=importlib.util.spec_from_file_location(name,ROOT/relative)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod
build=load('onyx_release','tools/release/onyx_release.py')
install=load('onyx_install','tools/installation/common/onyx_install.py')
plan=load('onyx_runtime_plan','tools/installation/common/onyx_runtime_plan.py')
COMMIT='c'*40
REQUIRED={
'windows':('windows/collector/Send-OnyxTelemetry.ps1','windows/collector/Launch-OnyxTelemetry.vbs',
           'windows/gateway/OnyxGateway.py','windows/gateway/gateway-dashboard.html'),
'pi-armv6':('pi/services/receiver/receiver.py','pi/services/receiver/integrated_store.py',
            'pi/services/receiver/history.py','pi/services/receiver/health.py',
            'tools/installation/pi/launch-onyx-v090-receiver.sh',
            'tools/installation/pi/onyxcore-v090-receiver.service',
            'tools/installation/pi/90-onyx-v090-receiver')}
class EndToEnd(unittest.TestCase):
    def check(self,platform):
        data={n:('demo '+n+'\n').encode() for n in REQUIRED[platform]}
        raw=build.encode_zip(platform,'0.9.0-rc1',COMMIT,data)
        dest=Path(tempfile.gettempdir())/('OnyxV090-'+uuid.uuid4().hex)
        with tempfile.TemporaryDirectory() as tmp:
            archive=Path(tmp)/'package.zip';archive.write_bytes(raw)
            try:
                digest=hashlib.sha256(raw).hexdigest()
                result=install.prepare(archive,dest,platform=platform,commit=COMMIT,
                      version='0.9.0-rc1',digest=digest,apply=True)
                self.assertEqual('PREPARED',result['status'])
                result=plan.plan(dest,COMMIT,platform)
                self.assertEqual('READ_ONLY_ACTIVATION_PLAN',result['operation'])
                self.assertFalse(result['activated'])
                self.assertEqual(len(data),result['audit']['files_verified'])
            finally:shutil.rmtree(dest,ignore_errors=True)
    def test_windows_package_installer_plan(self):self.check('windows')
    def test_pi_package_installer_plan(self):self.check('pi-armv6')
if __name__=='__main__':unittest.main(verbosity=2)
