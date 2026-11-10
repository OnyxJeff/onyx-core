"""M5 Step 4B1: offline planned-release-cycle safety tests, disposable paths only."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

MONITOR = Path(__file__).resolve().parents[2] / 'windows' / 'monitoring'
sys.path.insert(0, str(MONITOR))
import OnyxReleaseCyclePreflight as preflight
import OnyxReleaseReadOnly as release
import OnyxReleasePolicy as policy
import OnyxLiveIncident as live
import OnyxIncidentStore as store

START = datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc)


def cycle():
    return {
        'schema_version': 1, 'source': 'LiveRestrictedDiagnostic',
        'cycle_started_utc': (START-timedelta(seconds=3)).isoformat(),
        'cycle_finished_utc': START.isoformat(), 'duration_ms': 3000,
        'cycle_status': 'Complete', 'connectivity_decision': 'Healthy',
        'decision_reason': 'mock reason never exported',
        'windows_classification': 'WindowsPathReady',
        'pi_classification': 'PiInternetVerified',
        'observation_count': 1, 'consecutive_suspected': 0,
        'history_error_present': False, 'windows_error_present': False,
        'pi_error_present': False, 'repair_action': 'None',
    }


class ReleaseCyclePreflightTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='onyx-cycle-plan-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = self.root / 'repo'
        (self.repo / release.CONFIG_REL.parent).mkdir(parents=True)
        shutil.copyfile(MONITOR / policy.RELEASE_CONFIG_NAME, self.repo / release.CONFIG_REL)
        self.appdata = self.root / 'AppData' / 'Local'
        self.appdata.mkdir(parents=True)
        self.directory = self.appdata / release.RELEASE_SUBDIR / 'Monitoring'
        def release_gate(*, operation, require_store):
            self.assertEqual(operation, 'status')
            self.assertFalse(require_store)
            return self.directory
        self.enterContext(mock.patch.object(release, 'approved_release_view', side_effect=release_gate))
        self.enterContext(mock.patch.object(release, '_verified_root', return_value=self.repo))

    def initialized(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        live.apply_live_cycle(cycle(), self.directory, initialize_new=True)

    def plan(self, *, initialize_new=False, opt_in=True):
        return preflight.plan_release_cycle(intended_live_read_only=opt_in,
                                            initialize_new=initialize_new)

    def test_new_store_candidate_without_touching_directory(self):
        result = self.plan(initialize_new=True)
        self.assertEqual(result['store_condition'], 'NewStoreCandidate')
        self.assertFalse(self.directory.exists())

    def test_new_store_candidate_with_empty_directory(self):
        self.directory.mkdir(parents=True)
        self.assertEqual(self.plan(initialize_new=True)['store_condition'], 'NewStoreCandidate')
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_missing_store_refused_without_first_run_approval(self):
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'first-run'):
            self.plan()
        self.assertFalse(self.directory.exists())

    def test_existing_store_reports_generation(self):
        self.initialized()
        result = self.plan()
        self.assertEqual(result['store_condition'], 'ExistingValidated')
        self.assertEqual((result['existing_generation'], result['existing_processed_cycles']), (1, 1))

    def test_existing_store_cannot_initialize_again(self):
        self.initialized()
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'never be reinitialized'):
            self.plan(initialize_new=True)

    def test_partial_marker_only_refused(self):
        self.directory.mkdir(parents=True)
        (self.directory / live.MARKER_NAME).write_bytes(live.MARKER_BYTES)
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'partial'):
            self.plan(initialize_new=True)

    def test_partial_store_only_refused(self):
        self.initialized()
        (self.directory / live.MARKER_NAME).unlink()
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'partial'):
            self.plan()

    def test_corrupt_store_refused_no_reset(self):
        self.initialized()
        file = self.directory / 'incident-state.json'
        file.write_bytes(b'CORRUPT')
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'integrity'):
            self.plan()
        self.assertEqual(file.read_bytes(), b'CORRUPT')

    def test_bad_marker_refused_without_write(self):
        self.initialized()
        marker = self.directory / live.MARKER_NAME
        marker.write_bytes(b'NOT A MARKER')
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'invalid'):
            self.plan()
        self.assertEqual(marker.read_bytes(), b'NOT A MARKER')

    def test_repeated_plans_preserve_all_artifacts(self):
        self.initialized()
        before = {p.name:p.read_bytes() for p in self.directory.iterdir()}
        for _ in range(5):
            self.plan()
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.directory.iterdir()})

    def test_writer_lock_file_is_expected_for_existing_store(self):
        self.initialized()
        lock = self.directory / 'incident-state.json.lock'
        self.assertTrue(lock.is_file())
        self.assertEqual(self.plan()['store_condition'], 'ExistingValidated')

    def test_writer_lock_without_store_is_not_initializable(self):
        self.directory.mkdir(parents=True)
        (self.directory / 'incident-state.json.lock').touch()
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'nonempty'):
            self.plan(initialize_new=True)

    def test_new_with_stray_lock_refused(self):
        self.directory.mkdir(parents=True)
        (self.directory / 'incident-cycle.lock').write_bytes(b'\0')
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'nonempty'):
            self.plan(initialize_new=True)

    def test_new_with_stale_history_refused(self):
        self.directory.mkdir(parents=True)
        (self.directory / 'recovery-observations.json').write_bytes(b'{}')
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'nonempty'):
            self.plan(initialize_new=True)

    def test_new_with_unknown_file_refused(self):
        self.directory.mkdir(parents=True)
        (self.directory / 'unknown.tmp').write_bytes(b'test')
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'unexpected'):
            self.plan(initialize_new=True)

    def test_existing_with_unknown_file_refused(self):
        self.initialized()
        (self.directory / 'unexpected.bak').write_bytes(b'test')
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'unexpected'):
            self.plan()

    def test_existing_with_lock_and_history_can_be_reviewed(self):
        self.initialized()
        (self.directory / 'incident-cycle.lock').write_bytes(b'\0')
        (self.directory / 'recovery-observations.json').write_bytes(b'{}')
        self.assertEqual(self.plan()['store_condition'], 'ExistingValidated')

    def test_store_directory_file_refused(self):
        self.directory.parent.mkdir(parents=True)
        self.directory.write_bytes(b'wrong')
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'not a directory'):
            self.plan(initialize_new=True)

    def test_marker_directory_refused(self):
        self.directory.mkdir(parents=True)
        (self.directory / live.MARKER_NAME).mkdir()
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'regular file'):
            self.plan(initialize_new=True)

    def test_state_directory_refused(self):
        self.directory.mkdir(parents=True)
        (self.directory / 'incident-state.json').mkdir()
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'regular file'):
            self.plan(initialize_new=True)

    def test_invalid_nonboolean_initialization_refused(self):
        for value in (1, None, 'yes', [], {}):
            with self.subTest(value=value), self.assertRaises(preflight.ReleaseCyclePreflightError):
                self.plan(initialize_new=value)

    def test_requires_intended_explicit_readonly(self):
        for value in (False, 1, 'true', None):
            with self.subTest(value=value), self.assertRaisesRegex(
                preflight.ReleaseCyclePreflightError, 'explicit'):
                self.plan(opt_in=value)

    def test_no_root_checks_when_opt_in_absent(self):
        with mock.patch.object(release, 'approved_release_view', side_effect=AssertionError('unexpected')):
            with self.assertRaises(preflight.ReleaseCyclePreflightError):
                self.plan(opt_in=False)

    def test_release_gate_refusal_propagates(self):
        with mock.patch.object(release, 'approved_release_view', side_effect=release.ReleaseReadError('not main')):
            with self.assertRaisesRegex(release.ReleaseReadError, 'not main'):
                self.plan()

    def test_policy_rejects_repair_request(self):
        config = policy.load_release_config(self.repo / release.CONFIG_REL)
        with self.assertRaises(policy.ReleasePolicyError):
            policy.validate_release_intent(config,root=policy.RELEASE_ROOT,branch='main',
                operation='one-shot-cycle',explicit_live_read_only=True,repair_action='ResetIcs')

    def test_policy_rejects_schedule_request(self):
        config = policy.load_release_config(self.repo / release.CONFIG_REL)
        with self.assertRaises(policy.ReleasePolicyError):
            policy.validate_release_intent(config,root=policy.RELEASE_ROOT,branch='main',
                operation='one-shot-cycle',explicit_live_read_only=True,schedule_requested=True)

    def test_no_runtime_authorization_returned(self):
        result = self.plan(initialize_new=True)
        self.assertFalse(result['runtime_enabled'])
        self.assertTrue(result['future_live_consent_required'])
        self.assertTrue(result['exclusive_lock_recheck_required'])
        self.assertFalse(result['probe_performed'])
        self.assertFalse(result['store_modified'])
        self.assertFalse(result['schedule_requested'])
        self.assertEqual(result['repair_action'], 'None')

    def test_no_paths_or_private_reasons_in_structured_output(self):
        self.initialized()
        output = json.dumps(self.plan())
        self.assertNotIn(str(self.directory), output)
        self.assertNotIn('mock reason', output)
        self.assertNotIn('C:\\Python', output)

    def test_cli_requires_flags(self):
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            preflight.main([])

    def test_cli_rejects_live_execution_flags(self):
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            preflight.main(['--plan-one-shot', '--intended-live-read-only', '--repair'])

    def test_cli_json_existing_store(self):
        self.initialized()
        output = StringIO()
        with redirect_stdout(output):
            result = preflight.main(['--plan-one-shot', '--intended-live-read-only', '--json'])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())['store_condition'], 'ExistingValidated')

    def test_cli_text_new_store(self):
        output = StringIO()
        with redirect_stdout(output):
            result = preflight.main(['--plan-one-shot', '--intended-live-read-only', '--initialize-new'])
        self.assertEqual(result, 0)
        self.assertIn('RUNTIME BLOCKED', output.getvalue())
        self.assertFalse(self.directory.exists())

    def test_cli_missing_store_fail_closed(self):
        err = StringIO()
        with redirect_stderr(err):
            code = preflight.main(['--plan-one-shot', '--intended-live-read-only'])
        self.assertEqual(code, 1)
        self.assertIn('REFUSED', err.getvalue())
        self.assertFalse(self.directory.exists())

    def test_cli_bad_config_fails_closed(self):
        configpath = self.repo / release.CONFIG_REL
        body = json.loads(configpath.read_text())
        body['repair_action'] = 'RestartService'
        configpath.write_text(json.dumps(body))
        err = StringIO()
        with redirect_stderr(err):
            self.assertEqual(preflight.main(['--plan-one-shot', '--intended-live-read-only', '--initialize-new']), 1)
        self.assertIn('REFUSED', err.getvalue())

    def test_no_collector_or_cycle_runner_calls(self):
        with mock.patch.object(live, 'execute_one_cycle', side_effect=AssertionError('live invoked')), \
             mock.patch.object(live, 'run_existing_runner', side_effect=AssertionError('runner invoked')):
            self.assertEqual(self.plan(initialize_new=True)['runtime_enabled'], False)

    def test_no_store_mutations_even_if_helpers_patched_to_raise(self):
        with mock.patch.object(live, 'apply_live_cycle', side_effect=AssertionError('store mutated')), \
             mock.patch.object(live, '_ensure_safe_directory', side_effect=AssertionError('mkdir')):
            self.assertEqual(self.plan(initialize_new=True)['probe_performed'], False)

    def test_symlinked_directory_refused(self):
        self.directory.parent.mkdir(parents=True)
        other = self.root / 'other'; other.mkdir()
        try:
            self.directory.symlink_to(other, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('symlink unavailable')
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'redirected'):
            self.plan(initialize_new=True)

    def test_symlinked_marker_refused(self):
        self.initialized()
        marker = self.directory / live.MARKER_NAME
        target = self.root / 'marker'; target.write_bytes(live.MARKER_BYTES)
        marker.unlink()
        try:
            marker.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('symlink unavailable')
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'redirected'):
            self.plan()

    def test_symlinked_store_refused(self):
        self.initialized()
        state = self.directory / 'incident-state.json'
        target = self.root / 'state'; target.write_bytes(state.read_bytes())
        state.unlink()
        try:
            state.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('symlink unavailable')
        with self.assertRaisesRegex(preflight.ReleaseCyclePreflightError, 'redirected'):
            self.plan()


if __name__ == '__main__':
    unittest.main()
