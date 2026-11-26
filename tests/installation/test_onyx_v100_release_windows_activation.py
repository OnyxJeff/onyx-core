"""Windows executor offline tests; never register/start/stop a task."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/installation/common'))
import onyx_v100_release_windows_activation as a
import onyx_v100_release_build as b
from test_onyx_v100_release_install import WIN, PI, PATHS

class WindowsActivationTests(unittest.TestCase):
    def setUp(self):
        self.data,self.report=a.install.inventory({},WIN,'windows','a'*64,peer=PI,**PATHS)

    def test_transport_only_expected_nonsecret_values(self):
        result=a.driver_input(self.report,WIN,PI)
        self.assertEqual(result['plan_sha256'],self.report['plan_sha256'])
        self.assertEqual(result['source'],'SQUALL')
        self.assertEqual(result['gateway_port'],18976)
        self.assertEqual(result['receiver']['host'],'192.168.137.167')
        self.assertEqual([x['task_name'] for x in result['activation']['tasks']],list(a.install.WIN_TASKS))
        self.assertNotIn('ONYXCORE_TOKEN=',json.dumps(result))
        self.assertNotIn('bearer',json.dumps(result).lower())

    def test_wrong_scope_rejected(self):
        report=copy.deepcopy(self.report); report['activation']['tasks'][0]['task_name']='Other'
        with self.assertRaises(ValueError): a.driver_input(report,WIN,PI)
        with self.assertRaises(ValueError): a.driver_input(dict(self.report,role='pi-armv6'),WIN,PI)

    def test_wrong_approval_before_archive_read(self):
        for op in a.APPROVALS:
            args=[op,'--archive','missing.zip','--sha256','a'*64,'--config','missing.json',
                  '--peer-config','missing-peer.json','--approved-plan','b'*64,
                  '--localappdata',PATHS['localappdata'],'--pythonw',PATHS['pythonw'],'--systemroot',PATHS['systemroot']]
            with patch.object(a.native,'read_regular') as read:
                self.assertEqual(a.main(args),2); read.assert_not_called()

    def test_native_guard_precedes_execution(self):
        with patch.object(a.native,'win_guard',side_effect=ValueError('not native')),patch.object(a.subprocess,'run') as run:
            with self.assertRaises(ValueError): a.execute('activate',self.data,self.report,WIN,PI)
            run.assert_not_called()

    def test_packaged_driver_and_role_separation(self):
        win=b.payload(ROOT,'windows'); pi=b.payload(ROOT,'pi-armv6')
        self.assertIn(a.DRIVER,win); self.assertNotIn(a.DRIVER,pi)
        self.assertIn('tools/installation/common/onyx_v100_release_windows_activation.py',win)
        self.assertIn('tools/installation/common/onyx_v100_release_pi_activation.py',pi)
        self.assertNotIn('tools/installation/common/onyx_v100_release_pi_activation.py',win)
        self.assertNotIn('tools/installation/common/onyx_v100_release_windows_activation.py',pi)

    def test_driver_static_ownership_and_credential_contract(self):
        # Static review assertions, not proof of Task Scheduler behavior.
        s=(ROOT/a.DRIVER).read_text(encoding='utf-8')
        for text in ('RegisterTaskDefinition($Expected.task_name,$Definition,2,','FileMode]::CreateNew',
                     'Read-Host','-AsSecureString','ConvertFrom-SecureString','SetAccessRuleProtection($true,$false)',
                     'Assert-Task','Export-ScheduledTask','Stop-ScheduledTask','Unregister-ScheduledTask',
                     'WINDOWS_ROLLED_BACK_RUNTIME_AND_STATE_RETAINED=True'):
            self.assertIn(text,s)
        self.assertNotIn('Register-ScheduledTask -Force',s)
        self.assertNotIn('Remove-Item',s)
        self.assertNotIn('ExecutionPolicy Bypass',s)
        self.assertLess(s.index('Write-New $Intent'),s.index('RegisterTaskDefinition($Expected.task_name'))
        self.assertLess(s.index('Write-New $Owned'),s.index('Start-ScheduledTask -TaskName'))

    @unittest.skipUnless(sys.platform=='win32','Windows PowerShell parser only')
    def test_native_powershell_parser_only(self):
        path=ROOT/a.DRIVER
        ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        script="$ErrorActionPreference='Stop'; $t=$null; $e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('"+str(path).replace("'","''")+"',[ref]$t,[ref]$e); if($e.Count){$e | Out-String | Write-Output; exit 2}; exit 0"
        result=subprocess.run([str(ps),'-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__=='__main__': unittest.main()
