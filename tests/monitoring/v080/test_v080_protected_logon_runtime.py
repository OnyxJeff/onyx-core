"""Offline safety tests: protected user-logon runtime never uses Windows/live calls."""
from __future__ import annotations
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'windows'/'monitoring'/'v080'))
import OnyxV080ProtectedLogonRuntime as task


def good():
    return {'result':'PASS', 'session_state':'Completed',
            'cycles':task.SESSION_CYCLES,
            'persisted_cycles':task.SESSION_CYCLES,
            'repairs_invoked':False, 'notifications_sent':False, 'tasks_created':False}


class LogonTests(unittest.TestCase):
    def test_inert_without_host_actions(self):
        with patch.object(task,'run_monitor',side_effect=AssertionError('launched')):
            with patch.object(task,'run_alerts',side_effect=AssertionError('launched')):
                self.assertEqual(task.main(['--check-inert']),0)

    def test_session_rebootstraps_and_full_cooldown(self):
        generations=[];cooldown=[];records=[]
        def bootstrap():
            generations.append(len(generations)+1)
            return generations[-1]
        def run(session):
            records.append(session)
            return good()
        out=task.run_bounded_logon_loop(bootstrap=bootstrap,run_session=run,
              authorize=lambda s: True,sleep=cooldown.append,max_sessions=2)
        self.assertEqual(out,{'result':'STOPPED_TEST','completed_sessions':2})
        self.assertEqual(records,[1,2])
        self.assertEqual(sum(cooldown),120)
        self.assertTrue(all(n <= 2 for n in cooldown))
        self.assertEqual(len(cooldown),60)

    def test_no_consent_never_runs(self):
        worker=Mock(side_effect=AssertionError('unauthorized'))
        out=task.run_bounded_logon_loop(bootstrap=lambda:1,run_session=worker,
             authorize=lambda s: False,max_sessions=1)
        self.assertEqual(out,{'result':'CONSENT_REQUIRED','completed_sessions':0})
        worker.assert_not_called()

    def test_consent_revoked_during_interval_stops_without_more_sessions(self):
        count=[0];records=[]
        def approve(_):
            count[0]+=1
            return count[0] < 4
        out=task.run_bounded_logon_loop(bootstrap=lambda:'approved',
             run_session=lambda s: records.append(s) or good(),
             authorize=approve,sleep=lambda s: None,max_sessions=2)
        self.assertEqual(out,{'result':'CONSENT_REQUIRED','completed_sessions':1})
        self.assertEqual(len(records),1)

    def test_untrusted_worker_outcome_refused(self):
        for bad in ({**good(),'notifications_sent':True},
                    {**good(),'repairs_invoked':True},
                    {**good(),'tasks_created':True},
                    {**good(),'persisted_cycles':19},
                    {**good(),'result':'EXPIRED'},
                    {**good(),'session_state':'Expired'},
                    None,True):
            with self.subTest(bad=bad):
                with self.assertRaises(task.LogonRuntimeRefused):
                    task.run_bounded_logon_loop(bootstrap=lambda:1,
                      authorize=lambda s:True,run_session=lambda s:bad,max_sessions=1)

    def test_no_automatic_retry_after_exception(self):
        attempts=[]
        def failed(_):
            attempts.append(1)
            raise RuntimeError('session abort')
        with self.assertRaises(RuntimeError):
            task.run_bounded_logon_loop(bootstrap=lambda:1,
               authorize=lambda s:True,run_session=failed,max_sessions=5)
        self.assertEqual(attempts,[1])

    def test_invalid_synthetic_inputs_refused(self):
        for cap in (True,0,-1,1.0):
            with self.subTest(cap=cap),self.assertRaises(task.LogonRuntimeRefused):
                task.run_bounded_logon_loop(bootstrap=lambda:1,
                    authorize=lambda s:True,run_session=lambda s:good(),max_sessions=cap)

    def test_release_path_refused_from_development_checkout(self):
        with self.assertRaises(task.LogonRuntimeRefused):
            task.require_fixed_source(module_file=Path(__file__),executable=sys.executable,
                                       isolated=True,no_bytecode=True)
        self.assertEqual(task.run_monitor.__name__,'run_monitor')

    def test_no_background_task_created_by_cli(self):
        script=ROOT/'windows'/'monitoring'/'v080'/'OnyxV080ProtectedLogonRuntime.py'
        out=subprocess.run([sys.executable,'-I','-B',str(script),'--check-inert'],
                           capture_output=True,text=True,timeout=10)
        self.assertEqual(out.returncode,0,out.stderr)
        self.assertIn('"task_installation_enabled": false',out.stdout)

    def test_manifest_includes_all_started_programs(self):
        import OnyxWindowsRuntimeAttestation as att
        expected={'windows/monitoring/v080/OnyxV080ProtectedLogonRuntime.py',
                  'windows/monitoring/v080/OnyxIncidentNotifications.py',
                  'windows/monitoring/v080/operations/Start-OnyxV080ProtectedDiscord.ps1',
                  'windows/monitoring/v080/operations/Install-OnyxV080ProtectedUserTasks.ps1',
                  'windows/monitoring/v080/operations/Remove-OnyxV080ProtectedUserTasks.ps1'}
        self.assertTrue(expected.issubset(set(att.REQUIRED_FILES)))
        self.assertEqual(len(att.REQUIRED_FILES),24)
        self.assertEqual(len(set(att.REQUIRED_FILES)),24)


if __name__ == '__main__':unittest.main()
