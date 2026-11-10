"""M5 Step 4B2 release-only offline tests. Never invoke real PowerShell, SSH or ICS."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

MONITOR = Path(__file__).resolve().parents[2] / 'windows' / 'monitoring'
ROOT = MONITOR.parents[1]
sys.path.insert(0, str(MONITOR))
import OnyxReleaseLiveIncident as runner
import OnyxReleaseCyclePreflight as preflight
import OnyxReleasePolicy as policy
import OnyxReleaseReadOnly as release
import OnyxLiveIncident as live
import OnyxIncidentStore as storage
import OnyxIncidentState as reducer

UTC = datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc)


def cycle(seconds=0, decision='Healthy'):
    ended = UTC + timedelta(seconds=seconds)
    return {
        'schema_version': 1, 'source': 'LiveRestrictedDiagnostic',
        'cycle_started_utc': (ended - timedelta(seconds=3)).isoformat(),
        'cycle_finished_utc': ended.isoformat(), 'duration_ms': 3000,
        'cycle_status': 'Complete', 'connectivity_decision': decision,
        'decision_reason': 'private reason never exported',
        'windows_classification': 'WindowsPathReady',
        'pi_classification': 'PiInternetVerified',
        'observation_count': 1, 'consecutive_suspected': 0,
        'history_error_present': False, 'windows_error_present': False,
        'pi_error_present': False, 'repair_action': 'None',
    }


class ReleaseLiveIncidentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='onyx-release-runtime-offline-')
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.repo = self.tmp / 'repo'
        config = self.repo / release.CONFIG_REL
        config.parent.mkdir(parents=True)
        shutil.copyfile(MONITOR / policy.RELEASE_CONFIG_NAME, config)
        self.data = self.tmp / 'LocalAppData'
        self.data.mkdir()
        self.directory = self.data / release.RELEASE_SUBDIR / 'Monitoring'
        self.calls = 0
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(release, 'approved_release_view', side_effect=self.approve).start()
        mock.patch.object(release, '_verified_root', return_value=self.repo).start()

    def approve(self, *, operation, require_store):
        self.assertEqual(operation, 'status')
        self.assertFalse(require_store)
        return self.directory

    def fake_collector(self, root):
        self.assertEqual(root, self.repo)
        self.calls += 1
        self.assertTrue((self.directory / 'incident-cycle.lock').is_file())
        self.assertFalse((self.directory / live.MARKER_NAME).is_symlink())
        return cycle((self.calls - 1) * 60)

    def execute(self, *, init=False, collect=None):
        return runner.execute_release_cycle(
            explicit_live_read_only=True, initialize_new=init,
            collect=self.fake_collector if collect is None else collect,
        )

    def initialized(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        live.apply_live_cycle(cycle(), self.directory, initialize_new=True)

    def test_first_run_requires_separate_initialize_authorization(self):
        with self.assertRaises(preflight.ReleaseCyclePreflightError):
            self.execute()
        self.assertEqual(self.calls, 0)
        self.assertFalse(self.directory.exists())

    def test_initialize_new_is_one_manual_cycle(self):
        result = self.execute(init=True)
        self.assertEqual(result['generation'], 1)
        self.assertEqual(result['phase'], 'Healthy')
        self.assertTrue(result['manual_only'])
        self.assertEqual(result['repair_action'], 'None')
        self.assertEqual(result['source'], 'ReleaseOneShotIncidentIntegration')
        self.assertEqual(self.calls, 1)
        self.assertEqual((self.directory / live.MARKER_NAME).read_bytes(), live.MARKER_BYTES)

    def test_followup_cycle_generation_two(self):
        self.execute(init=True)
        result = self.execute()
        self.assertEqual(result['generation'], 2)
        self.assertEqual(result['phase'], 'Healthy')
        self.assertEqual(self.calls, 2)

    def test_followup_does_not_allow_reinitialization(self):
        self.execute(init=True)
        with self.assertRaises(preflight.ReleaseCyclePreflightError):
            self.execute(init=True)
        self.assertEqual(self.calls, 1)

    def test_no_opt_in_never_inspects_release_store(self):
        with mock.patch.object(release, 'approved_release_view', side_effect=AssertionError):
            for value in (False, None, 'yes', 1, []):
                with self.subTest(value=value), self.assertRaises(runner.ReleaseCycleError):
                    runner.execute_release_cycle(explicit_live_read_only=value)

    def test_invalid_first_run_opt_in_never_checks_store(self):
        for value in (None, 'yes', 1, {}):
            with self.subTest(value=value), self.assertRaises(runner.ReleaseCycleError):
                runner.execute_release_cycle(explicit_live_read_only=True, initialize_new=value)
        self.assertFalse(self.directory.exists())

    def test_release_context_refusal_stops_before_probe(self):
        with mock.patch.object(release, 'approved_release_view', side_effect=release.ReleaseReadError('bad context')):
            with self.assertRaises(release.ReleaseReadError):
                self.execute(init=True)
        self.assertFalse(self.directory.exists())
        self.assertEqual(self.calls, 0)

    def test_invalid_policy_stops_before_probe(self):
        with mock.patch.object(policy, 'validate_release_intent', side_effect=policy.ReleasePolicyError('invalid')):
            with self.assertRaises(policy.ReleasePolicyError):
                self.execute(init=True)
        self.assertFalse(self.directory.exists())

    def test_corrupt_store_refused_preserving_bytes(self):
        self.initialized()
        state = self.directory / 'incident-state.json'
        state.write_bytes(b'CORRUPTED-DO-NOT-DELETE')
        with self.assertRaises(preflight.ReleaseCyclePreflightError):
            self.execute()
        self.assertEqual(state.read_bytes(), b'CORRUPTED-DO-NOT-DELETE')
        self.assertEqual(self.calls, 0)

    def test_bad_marker_refused_without_write(self):
        self.initialized()
        marker = self.directory / live.MARKER_NAME
        marker.write_bytes(b'bad marker')
        with self.assertRaises(preflight.ReleaseCyclePreflightError):
            self.execute()
        self.assertEqual(marker.read_bytes(), b'bad marker')
        self.assertEqual(self.calls, 0)

    def test_partial_initialization_refused(self):
        self.initialized()
        (self.directory / live.MARKER_NAME).unlink()
        with self.assertRaises(preflight.ReleaseCyclePreflightError):
            self.execute()
        self.assertEqual(self.calls, 0)

    def test_stray_lock_new_store_refused_before_probe(self):
        self.directory.mkdir(parents=True)
        (self.directory / 'incident-cycle.lock').write_bytes(b'old')
        with self.assertRaises(preflight.ReleaseCyclePreflightError):
            self.execute(init=True)
        self.assertEqual(self.calls, 0)

    def test_unknown_file_new_store_refused(self):
        self.directory.mkdir(parents=True)
        (self.directory / 'unknown.bin').write_bytes(b'!')
        with self.assertRaises(preflight.ReleaseCyclePreflightError):
            self.execute(init=True)
        self.assertEqual(self.calls, 0)

    def test_first_run_collector_writes_observation_history(self):
        def collect(root):
            (self.directory / 'recovery-observations.json').write_text('{"mock":true}')
            return cycle()
        result = self.execute(init=True, collect=collect)
        self.assertEqual(result['generation'], 1)
        self.assertTrue((self.directory / 'recovery-observations.json').is_file())

    def test_first_run_refuses_unexpected_file_added_by_collector(self):
        def collect(root):
            (self.directory / 'unexpected.txt').write_text('do not erase')
            return cycle()
        with self.assertRaises(runner.ReleaseCycleError):
            self.execute(init=True, collect=collect)
        self.assertFalse((self.directory / live.MARKER_NAME).exists())
        self.assertEqual((self.directory / 'unexpected.txt').read_text(), 'do not erase')

    def test_first_run_bad_cycle_leaves_no_marker(self):
        invalid = cycle()
        invalid['repair_action'] = 'ResetIcs'
        with self.assertRaises(reducer.InvalidIncidentInput):
            self.execute(init=True, collect=lambda root: invalid)
        self.assertFalse((self.directory / live.MARKER_NAME).exists())

    def test_existing_bad_cycle_preserves_store(self):
        self.initialized()
        state = self.directory / 'incident-state.json'
        old = state.read_bytes()
        invalid = cycle(60)
        invalid['repair_action'] = 'Repair'
        with self.assertRaises(reducer.InvalidIncidentInput):
            self.execute(collect=lambda root: invalid)
        self.assertEqual(state.read_bytes(), old)

    def test_existing_state_change_during_probe_refused_before_commit(self):
        self.initialized()
        state = self.directory / 'incident-state.json'
        def collect(root):
            state.write_bytes(b'FORCE-CORRUPT')
            return cycle(60)
        with self.assertRaises(preflight.ReleaseCyclePreflightError):
            self.execute(collect=collect)
        self.assertEqual(state.read_bytes(), b'FORCE-CORRUPT')

    def test_existing_replay_remains_idempotent(self):
        self.initialized()
        state = self.directory / 'incident-state.json'
        original = state.read_bytes()
        result = self.execute(collect=lambda root: cycle())
        self.assertTrue(result['replayed'])
        self.assertEqual(state.read_bytes(), original)

    def test_release_data_is_separate_from_development(self):
        dev = self.data / 'OnyxCore-v070-Development' / 'Monitoring'
        dev.mkdir(parents=True)
        (dev / 'incident-state.json').write_bytes(b'keep me')
        self.execute(init=True)
        self.assertEqual((dev / 'incident-state.json').read_bytes(), b'keep me')

    def test_exclusive_lock_refuses_nested_cycle(self):
        self.initialized()
        # Linux and Windows locks both reject an independently opened process.
        # Windows behavior is additionally exercised on SQUALL via offline tests.
        def collect(root):
            with self.assertRaises(live.LiveIncidentError):
                with live._single_cycle_lock(self.directory):
                    pass
            return cycle(60)
        result = self.execute(collect=collect)
        self.assertEqual(result['generation'], 2)

    def test_new_store_owned_lock_validation(self):
        self.directory.mkdir(parents=True)
        (self.directory / 'incident-cycle.lock').write_bytes(b'\0')
        self.assertEqual(preflight._check_store(self.directory, True, owned_cycle_lock=True)[0],
                         'NewStoreCandidate')
        with self.assertRaises(preflight.ReleaseCyclePreflightError):
            preflight._check_store(self.directory, True)

    def test_owned_lock_must_exist(self):
        self.directory.mkdir(parents=True)
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'owned'):
            preflight._check_store(self.directory, True, owned_cycle_lock=True)

    def test_invalid_owned_lock_flag_rejected(self):
        with self.assertRaises(preflight.ReleaseCyclePreflightError):
            preflight._check_store(self.directory, True, owned_cycle_lock=1)

    def test_missing_collector_or_ps_refused(self):
        with self.assertRaises(runner.ReleaseCycleError):
            runner.run_release_evidence(self.repo)

    def test_bounded_subprocess_success_and_one_shot_flags(self):
        power = self.tmp / 'powershell.exe'
        power.write_bytes(b'')
        script = self.repo / runner.RUNNER_REL
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text('test stub')
        collector = self.repo / runner.COLLECTOR_REL
        collector.parent.mkdir(parents=True, exist_ok=True)
        collector.write_text('test stub')
        call = []
        def subprocess_stub(args, **kwargs):
            call.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, json.dumps(cycle()).encode(), b'')
        with mock.patch.object(live, 'WINDOWS_PS', power):
            result = runner.run_release_evidence(self.repo, runner=subprocess_stub)
        self.assertEqual(result['source'], 'LiveRestrictedDiagnostic')
        self.assertEqual(len(call), 1)
        self.assertIn('-LiveReadOnly -Json', call[0][0][-1])
        self.assertEqual(call[0][1]['timeout'], 120)
        self.assertEqual(call[0][1]['env'][runner.SUPERVISION_ENV], 'approved-one-shot')
        self.assertIn('-NonInteractive', call[0][0])
        self.assertTrue(call[0][1]['capture_output'])

    def test_subprocess_nonzero_refused_without_stderr_leak(self):
        power = self.tmp / 'powershell.exe'
        power.write_bytes(b'')
        script = self.repo / runner.RUNNER_REL
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text('stub')
        collector = self.repo / runner.COLLECTOR_REL
        collector.parent.mkdir(parents=True, exist_ok=True)
        collector.write_text('stub')
        def failed(*args, **kwargs):
            return subprocess.CompletedProcess([], 1, b'', b'PRIVATE SSH ERROR')
        with mock.patch.object(live, 'WINDOWS_PS', power):
            with self.assertRaises(runner.ReleaseCycleError) as caught:
                runner.run_release_evidence(self.repo, runner=failed)
        self.assertNotIn('PRIVATE', str(caught.exception))

    def test_subprocess_timeout_refused(self):
        power = self.tmp / 'powershell.exe'
        power.write_bytes(b'')
        script = self.repo / runner.RUNNER_REL
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text('stub')
        collector = self.repo / runner.COLLECTOR_REL
        collector.parent.mkdir(parents=True, exist_ok=True)
        collector.write_text('stub')
        with mock.patch.object(live, 'WINDOWS_PS', power):
            with self.assertRaises(runner.ReleaseCycleError):
                runner.run_release_evidence(self.repo, runner=mock.Mock(side_effect=subprocess.TimeoutExpired('ps',120)))

    def test_subprocess_invalid_json_rejected(self):
        power = self.tmp / 'powershell.exe'
        power.write_bytes(b'')
        script = self.repo / runner.RUNNER_REL
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text('stub')
        collector = self.repo / runner.COLLECTOR_REL
        collector.parent.mkdir(parents=True, exist_ok=True)
        collector.write_text('stub')
        def broken(*args, **kwargs):
            return subprocess.CompletedProcess([], 0, b'{broken', b'')
        with mock.patch.object(live, 'WINDOWS_PS', power):
            with self.assertRaises(live.LiveIncidentError):
                runner.run_release_evidence(self.repo, runner=broken)

    def test_cli_does_not_run_without_explicit_flag(self):
        with mock.patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaises(SystemExit):
                runner.main([])
        self.assertFalse(self.directory.exists())

    def test_cli_refusal_does_not_echo_private_probe_error(self):
        with mock.patch.object(runner, 'execute_release_cycle', side_effect=runner.ReleaseCycleError('no access')):
            with mock.patch('sys.stderr', new_callable=io.StringIO) as out:
                self.assertEqual(runner.main(['--live-read-only']), 1)
        self.assertIn('RELEASE ONE-SHOT REFUSED', out.getvalue())

    def test_release_power_shell_sources_are_separate_and_guarded(self):
        psrunner = (ROOT / runner.RUNNER_REL).read_text()
        collector = (ROOT / runner.COLLECTOR_REL).read_text()
        for forbidden in ('Restart-Service ', 'Stop-Service ', 'Set-NetIPAddress ',
                          'Enable-NetAdapter ', 'Register-ScheduledTask ', 'schtasks.exe '):
            self.assertNotIn(forbidden, psrunner)
            self.assertNotIn(forbidden, collector)
        self.assertIn('OnyxCore-v070-Release', psrunner)
        self.assertIn('monitoring.release.example.json', collector)
        self.assertIn('AuthorizedReleaseRunner', collector)
        self.assertIn('ONYX_CORE_V070_RELEASE_LIVE', collector)
        self.assertIn('HistoryError', collector)
        self.assertIn('null -eq $HistoryError', collector)
        self.assertNotIn('OnyxCore-v070-Development', collector)
        self.assertNotIn('feature/v0.7.0-monitoring', psrunner)
        self.assertNotIn('feature/v0.7.0-monitoring', collector)


if __name__ == '__main__':
    unittest.main()
