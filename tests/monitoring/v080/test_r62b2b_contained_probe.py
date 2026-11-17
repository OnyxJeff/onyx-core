"""R6.2B2B offline: strict contained child report and no unsafe fallback."""
from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
MON = ROOT / 'windows' / 'monitoring' / 'v080'
sys.path.insert(0, str(MON))
import OnyxV080ContainedProbe as contained
import OnyxWindowsJobRunner as job

PYTHON = r'C:\Python313\python.exe'


def valid_report():
    return dict(
        schema_version=1, source='OnyxV080LiveConnectivity', mode='ManualReadOnly',
        checked_at_utc=datetime.now(timezone.utc).isoformat(),
        status='Unknown', reason='DiagnosticEvidenceUnavailable',
        windows={'classification':'WindowsProbeUnavailable'},
        pi={'classification':'PiProbeUnavailable'},
        issues=['WindowsDiagnosticUnavailable','PiDiagnosticUnavailable'],
        repair_action='None', incident_history_written=False,
        scheduler_enabled=False, notification_sent=False)


def encode(report):
    return json.dumps(report, separators=(',', ':')).encode('utf-8')


class ContainedProbeOfflineTests(unittest.TestCase):
    def test_no_live_cli_without_explicit_child_flag(self):
        self.assertEqual(contained.main(['--check-inert']), 0)
        with self.assertRaises(SystemExit):
            contained.main([])

    def test_low_token_query_refuses_non_windows(self):
        if sys.platform == 'win32':
            self.skipTest('no real low token in offline tests')
        with self.assertRaises(contained.ContainmentRefused):
            contained._assert_low_integrity()

    def test_valid_sanitized_unknown_result(self):
        self.assertEqual(contained._decode_checked(encode(valid_report()))['status'], 'Unknown')

    def test_duplicate_json_key_rejected(self):
        raw = encode(valid_report())[:-1] + b',"status":"Healthy"}'
        with self.assertRaises(contained.ContainmentRefused):
            contained._decode_checked(raw)

    def test_extra_raw_child_field_refused(self):
        sample = valid_report(); sample['stdout']='private diagnostic output'
        with self.assertRaises(contained.ContainmentRefused):
            contained._decode_checked(encode(sample))

    def test_forged_healthy_and_side_effects_refused(self):
        for name,value in (('status','Healthy'),('reason','Fake'),('repair_action','Fix'),
                           ('scheduler_enabled',True),('incident_history_written',True),
                           ('notification_sent',1),('schema_version',True)):
            sample=valid_report(); sample[name]=value
            with self.subTest(name=name), self.assertRaises(contained.ContainmentRefused):
                contained._decode_checked(encode(sample))

    def test_missing_evidence_issue_refused(self):
        sample=valid_report(); sample['issues']=[]
        with self.assertRaises(contained.ContainmentRefused):
            contained._decode_checked(encode(sample))

    def test_nested_raw_evidence_refused(self):
        sample=valid_report(); sample['windows']['raw_ssh']='sensitive'
        with self.assertRaises(contained.ContainmentRefused):
            contained._decode_checked(encode(sample))

    def test_nonfinite_and_oversized_output_refused(self):
        for bad in (b'{}', b'{"x":NaN}', b'{' * 20000, b'\xff'):
            with self.subTest(raw=bad[:10]), self.assertRaises(contained.ContainmentRefused):
                contained._decode_checked(bad)

    def test_stale_timestamp_refused(self):
        sample=valid_report(); sample['checked_at_utc']='2000-01-01T00:00:00+00:00'
        with self.assertRaises(contained.ContainmentRefused):
            contained._decode_checked(encode(sample))

    def test_injected_backend_cannot_claim_low_token_or_live_consent(self):
        fake=job.WindowsJobRunner((PYTHON,), _backend=lambda cmd,secs: subprocess.CompletedProcess(cmd,0,b'{}',b''))
        with self.assertRaisesRegex(job.JobRunnerRefused, 'injected backend'):
            fake.run([PYTHON],timeout=5,low_integrity=True)
        with self.assertRaisesRegex(job.JobRunnerRefused, 'injected backend'):
            fake.run([PYTHON],timeout=5,consent_check=lambda: True)

    def test_invalid_native_job_arguments_refused(self):
        fake=job.WindowsJobRunner((PYTHON,), _backend=lambda cmd,secs: subprocess.CompletedProcess(cmd,0,b'{}',b''))
        with self.assertRaises(job.JobRunnerRefused):
            fake.run([PYTHON],timeout=5,low_integrity='low')
        with self.assertRaises(job.JobRunnerRefused):
            fake.run([PYTHON],timeout=5,consent_check=True)

    def test_guarded_probe_denies_outside_protected_release_install(self):
        with self.assertRaises(contained.ContainmentRefused):
            contained.run_protected_probe({},source_root=ROOT,authorize=lambda: True)
        with self.assertRaises(contained.ContainmentRefused):
            contained.run_protected_probe({},source_root=contained.INSTALL_ROOT,authorize=lambda: False)

    def test_low_worker_diagnostic_only_composer_does_not_spawn_from_unit_test(self):
        import OnyxLiveConnectivity as m1
        with patch.object(m1, '_windows', return_value={'classification':'WindowsProbeUnavailable'}), \
             patch.object(m1, '_pi', return_value={'classification':'PiProbeUnavailable'}):
            result = m1._run_once_from_bounded_workers({'profile':'release'},
                runner=lambda *a,**kw: self.fail('no process from offline unit test'))
        self.assertEqual(result['status'], 'Unknown')
        self.assertFalse(result['incident_history_written'])

    def test_trusted_release_binding_routes_to_containment_not_inline_m1(self):
        import OnyxV080ReleaseBinding as binding
        self.assertIsNot(binding.contained.run_protected_probe, binding.m1.run_once)
        self.assertIn('OnyxV080ContainedProbe.py', ' '.join(
            __import__('OnyxWindowsRuntimeAttestation').REQUIRED_FILES))


if __name__ == '__main__':
    unittest.main()
