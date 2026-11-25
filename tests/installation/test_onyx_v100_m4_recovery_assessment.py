"""Offline tests for the manual v100 recovery assessment, no real probes."""
from pathlib import Path
import sys
import json
import subprocess
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'windows/monitoring/v100'))
import OnyxV100RecoveryAssessment as assessment


def observation(w='WindowsPathReady', p='PiInternetVerified', **changes):
    win = dict(classification=w, adapter_up=True, gateway_preferred=True,
               route_via_usb=True, receiver_tcp_reachable=True, ics_service_status='Running')
    win.update(changes)
    pi = dict(classification=p, interface_ready=True, route_via_usb=True,
              gateway_reachable=True, external_tcp_443=True, dns_resolves=True, https_works=True)
    status, reason = assessment.connectivity.classify(win, pi)
    return dict(source='OnyxV080LiveConnectivity', windows=win, pi=pi,
                status=status, reason=reason, repair_action='None',
                incident_history_written=False, notification_sent=False, scheduler_enabled=False,
                checked_at_utc='2026-11-25T17:34:22+00:00', issues=[name for cond, name in ((w == 'WindowsProbeUnavailable', 'WindowsDiagnosticUnavailable'), (p == 'PiProbeUnavailable', 'PiDiagnosticUnavailable')) if cond])


class RecoveryTests(unittest.TestCase):
    def test_healthy_no_restart(self):
        r = assessment.summarize(observation(), .5)
        self.assertEqual(r['recommendation'], 'NoRepairNeeded')
        self.assertFalse(r['repair_performed'])
        self.assertFalse(r['journal_written'])
        self.assertEqual(r['observation']['status'], 'Healthy')

    def test_healthy_contradiction_refused(self):
        with self.assertRaises(ValueError):
            assessment.recovery_recommendation(observation(adapter_up=False))

    def test_stopped_service_recommendation_only(self):
        r = assessment.summarize(observation('IcsServiceStopped', 'PiProbeUnavailable',
                                             ics_service_status='Stopped'), 1)
        self.assertEqual(r['recommendation'], 'OperatorMayConsiderStartingICS')
        self.assertFalse(r['repair_performed'])

    def test_service_pending_not_start_candidate(self):
        self.assertEqual(assessment.recovery_recommendation(observation('IcsServiceStopped',
            ics_service_status='StartPending')), 'InvestigateICSServiceState')

    def test_usb_missing_not_repair(self):
        for w in ('AdapterMissing','AdapterDown','GatewayAddressMissing','RouteNotViaUsb','WindowsProbeUnavailable'):
            with self.subTest(w=w):
                self.assertEqual(assessment.recovery_recommendation(observation(w)), 'InvestigateUsbOrWindowsEvidence')

    def test_receiver_unreachable_not_repair(self):
        self.assertEqual(assessment.recovery_recommendation(observation('ReceiverUnreachable')), 'InvestigateReceiverOrUsb')

    def test_external_failure_not_automatic_restart(self):
        for p in ('ExternalTcpUnverified','DnsUnverified','HttpsUnverified'):
            with self.subTest(p=p):
                self.assertEqual(assessment.recovery_recommendation(observation(p=p)), 'InvestigateForwardingOrUpstream')

    def test_missing_pi_evidence_not_healthy(self):
        self.assertEqual(assessment.recovery_recommendation(observation(p='PiProbeUnavailable')), 'InvestigatePiOrMissingEvidence')

    def test_forged_status_refused(self):
        r = observation('AdapterDown'); r['status'] = 'Healthy'
        with self.assertRaises(ValueError): assessment.recovery_recommendation(r)

    def test_valid_config(self):
        c = assessment.make_config('Ethernet 3','192.168.137.1','192.168.137.167',8765,'svr-onyxcore.local','onyxpi','key','ssh')
        self.assertEqual(c['profile'], 'release')
        self.assertEqual(c['timeouts']['ssh_seconds'],30)

    def test_bad_config(self):
        good = ['Ethernet 3','192.168.137.1','192.168.137.167',8765,'svr-onyxcore.local','onyxpi','key','ssh']
        for i,v in ((0,'-bad'),(1,'8.8.8.8'),(2,'192.168.137.1'),(3,0),(4,'-bad'),(5,'user@other')):
            args = good.copy(); args[i] = v
            with self.subTest(i=i), self.assertRaises(ValueError): assessment.make_config(*args)

    def test_existing_worker_composition(self):
        win = dict(schema_version=1, source='OnyxV080WindowsUsbReadiness',
                   classification='WindowsPathReady', adapter_present=True,
                   adapter_up=True, gateway_preferred=True, route_via_usb=True,
                   receiver_tcp_reachable=True, ics_service_status='Running', repair_action='None')
        pi = dict(observation()['pi'], repair_action='None')
        config = assessment.make_config('Ethernet 3','192.168.137.1','192.168.137.167',8765,
                                        'svr-onyxcore.local','onyxpi','key','ssh')
        calls = []
        def runner(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return subprocess.CompletedProcess(cmd, 0, json.dumps(win if len(calls)==1 else pi).encode(), b'')
        report = assessment.connectivity._run_once_from_bounded_workers(config, runner=runner)
        self.assertEqual(assessment.summarize(report, .5)['recommendation'], 'NoRepairNeeded')
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][0][-1], 'onyxcore-monitor')
        self.assertEqual(calls[0][1]['timeout'], 25)
        self.assertEqual(calls[1][1]['timeout'], 30)

    def test_system_hardlinks_only_at_exact_paths(self):
        info = SimpleNamespace(st_mode=stat.S_IFREG, st_nlink=2, st_file_attributes=0)
        with patch.object(Path, 'lstat', return_value=info):
            for path in (assessment.SYSTEM_SSH, assessment.SYSTEM_PS5):
                assessment.check_system_executable(path)
                with self.assertRaises(ValueError):
                    assessment.check_regular(path)
            with self.assertRaises(ValueError):
                assessment.check_system_executable(Path('other/ssh.exe'))
            with self.assertRaises(ValueError):
                assessment.check_regular(Path('private-key'))

    def test_system_nonregular_and_reparse_refused(self):
        for mode, attrs, links in ((stat.S_IFREG, 0x400, 2),
                                   (stat.S_IFLNK, 0, 2),
                                   (stat.S_IFDIR, 0, 2),
                                   (stat.S_IFREG, 0, 0)):
            info = SimpleNamespace(st_mode=mode, st_nlink=links, st_file_attributes=attrs)
            with self.subTest(mode=mode, attrs=attrs, links=links):
                with patch.object(Path, 'lstat', return_value=info), self.assertRaises(ValueError):
                    assessment.check_system_executable(assessment.SYSTEM_SSH)

    def test_redirected_parent_refused(self):
        path = Path('parent/file')
        good = SimpleNamespace(st_mode=stat.S_IFREG, st_nlink=1, st_file_attributes=0)
        bad = SimpleNamespace(st_mode=stat.S_IFDIR, st_nlink=1, st_file_attributes=0x400)
        def info(p):
            return bad if p == path.parent else good
        with patch.object(Path, 'lstat', autospec=True, side_effect=info), self.assertRaises(ValueError):
            assessment.check_regular(path)

    def test_single_link_application_file_accepted(self):
        info = SimpleNamespace(st_mode=stat.S_IFREG, st_nlink=1, st_file_attributes=0)
        with patch.object(Path, 'lstat', return_value=info):
            assessment.check_regular(Path('private-key'))

    def test_explicit_opt_in(self):
        with patch.object(assessment.connectivity,'run_once') as probe, self.assertRaises(SystemExit):
            assessment.main([])
        probe.assert_not_called()


if __name__ == '__main__': unittest.main()
