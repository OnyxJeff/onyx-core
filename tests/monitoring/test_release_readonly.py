"""M5 release-view boundary: offline-only, simulated root and disposable stores.

The tests never inspect actual SQUALL release history, run PowerShell, SSH or
invoke a Windows network operation; all writable files reside in temp dirs.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone, timedelta
import io
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
import OnyxReleaseReadOnly as release
import OnyxReleasePolicy as policy
import OnyxLiveIncident as live
import OnyxIncidentStore as store


START = datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc)


def cycle(seconds=0, decision='Healthy'):
    stamp = START + timedelta(seconds=seconds)
    return {
        'schema_version': 1, 'source': 'LiveRestrictedDiagnostic',
        'cycle_started_utc': (stamp - timedelta(seconds=4)).isoformat(),
        'cycle_finished_utc': stamp.isoformat(), 'duration_ms': 4000,
        'cycle_status': 'Complete', 'connectivity_decision': decision,
        'decision_reason': 'HIDDEN-PRIVATE-REASON',
        'windows_classification': 'WindowsPathReady',
        'pi_classification': 'PiInternetVerified',
        'observation_count': 1, 'consecutive_suspected': 0,
        'history_error_present': False, 'windows_error_present': False,
        'pi_error_present': False, 'repair_action': 'None',
    }


class ReleaseReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='onyx-release-view-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.repo = root / 'repo'
        (self.repo / release.CONFIG_REL.parent).mkdir(parents=True)
        shutil.copyfile(MONITOR / policy.RELEASE_CONFIG_NAME, self.repo / release.CONFIG_REL)
        self.appdata = root / 'AppData' / 'Local'
        self.appdata.mkdir(parents=True)
        self.state = self.appdata / release.RELEASE_SUBDIR / 'Monitoring'
        self.config = policy.load_release_config(self.repo / release.CONFIG_REL)

    @contextlib.contextmanager
    def authorized(self, *, git=None):
        def git_call(root, *args):
            if git is not None:
                return git(root, *args)
            if args[:2] == ('branch', '--show-current'):
                return 'main'
            return ''
        with mock.patch.object(release, '_verified_root', return_value=self.repo), \
             mock.patch.object(release, '_git', side_effect=git_call), \
             mock.patch.dict(os.environ, {'LOCALAPPDATA': str(self.appdata)}), \
             mock.patch.object(release.sys, 'executable', self.config['runtime']['python_executable']):
            yield

    def initialized(self):
        self.state.mkdir(parents=True, exist_ok=True)
        live.apply_live_cycle(cycle(), self.state, initialize_new=True)

    def test_platform_refused_on_non_windows(self):
        if os.name != 'nt':
            with self.assertRaisesRegex(release.ReleaseReadError, 'Windows'):
                release._verified_root()

    def test_valid_release_context_reads_existing_snapshot(self):
        self.initialized()
        with self.authorized():
            directory = release.approved_release_view(operation='status')
            self.assertEqual(directory, self.state)
            result = release.read_release_view(operation='status')
        self.assertEqual((result['phase'], result['generation']), ('Healthy', 1))
        self.assertFalse(result['live_probed'])
        self.assertEqual(result['repair_action'], 'None')

    def test_report_has_age_and_historical_warning(self):
        self.initialized()
        with self.authorized():
            result = release.read_release_view(operation='report',
                now_utc=START + timedelta(hours=2))
        self.assertEqual(result['freshness'], 'Stale')
        self.assertIn('Historical observation', result['assessment'])
        self.assertFalse(result['live_probed'])

    def test_release_data_does_not_appear_in_development_directory(self):
        self.initialized()
        self.assertNotIn('Development', str(self.state))
        self.assertFalse((self.appdata / 'OnyxCore-v070-Development').exists())

    def test_missing_state_refuses_without_creating_directory(self):
        with self.authorized():
            with self.assertRaisesRegex(release.ReleaseReadError, 'not initialized'):
                release.read_release_view(operation='status')
        self.assertFalse(self.state.exists())

    def test_preflight_can_inspect_context_without_initializing_store(self):
        with self.authorized():
            path = release.approved_release_view(operation='status', require_store=False)
        self.assertEqual(path, self.state)
        self.assertFalse(self.state.exists())

    def test_marker_missing_refused_no_write(self):
        self.initialized()
        (self.state / live.MARKER_NAME).unlink()
        original = (self.state / 'incident-state.json').read_bytes()
        with self.authorized(), self.assertRaises(Exception):
            release.read_release_view(operation='status')
        self.assertEqual(original, (self.state / 'incident-state.json').read_bytes())

    def test_tampered_store_refused_without_reset(self):
        self.initialized()
        path = self.state / 'incident-state.json'
        path.write_bytes(b'NOT A VALID STORE')
        with self.authorized(), self.assertRaises(store.IncidentStoreError):
            release.read_release_view(operation='report')
        self.assertEqual(path.read_bytes(), b'NOT A VALID STORE')

    def test_repeated_reads_preserve_store_marker_and_names(self):
        self.initialized()
        before = {p.name: p.read_bytes() for p in self.state.iterdir()}
        with self.authorized():
            for i in range(4):
                release.read_release_view(operation='status')
                release.read_release_view(operation='report', now_utc=START)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.state.iterdir()})

    def test_invalid_operation_rejected_before_git_or_store(self):
        with mock.patch.object(release, '_verified_root', side_effect=AssertionError('root called')):
            for name in ('one-shot-cycle', 'repair', 'schedule', '', 'STATUS'):
                with self.subTest(name=name), self.assertRaises(release.ReleaseReadError):
                    release.approved_release_view(operation=name)

    def test_release_policy_enforced_on_branch(self):
        def git(root, *args):
            return 'feature/v0.7.0-monitoring' if args[:2] == ('branch', '--show-current') else ''
        with self.authorized(git=git), self.assertRaises(policy.ReleasePolicyError):
            release.approved_release_view(operation='status', require_store=False)

    def test_rejects_dirty_tracked_repo(self):
        def git(root, *args):
            if args[:2] == ('branch', '--show-current'):
                return 'main'
            return ' M windows/monitoring/OnyxIncidentStore.py' if args[0] == 'status' else ''
        with self.authorized(git=git), self.assertRaisesRegex(release.ReleaseReadError, 'not clean'):
            release.approved_release_view(operation='status', require_store=False)

    def test_rejects_untracked_monitoring_source_file(self):
        def git(root, *args):
            if args[:2] == ('branch', '--show-current'):
                return 'main'
            if args[0] == 'status' and '--untracked-files=all' in args:
                return '?? windows/monitoring/evil.py'
            return ''
        with self.authorized(git=git), self.assertRaisesRegex(release.ReleaseReadError, 'unexpected file'):
            release.approved_release_view(operation='status', require_store=False)

    def test_rejects_untracked_required_source(self):
        def git(root, *args):
            if args[:2] == ('branch', '--show-current'):
                return 'main'
            if args[0] == 'ls-files':
                raise release.ReleaseReadError('untracked required source')
            return ''
        with self.authorized(git=git), self.assertRaises(release.ReleaseReadError):
            release.approved_release_view(operation='report', require_store=False)

    def test_python_executable_mismatch_refused(self):
        with self.authorized(), mock.patch.object(release.sys, 'executable', 'C:\\Wrong\\python.exe'):
            with self.assertRaisesRegex(release.ReleaseReadError, 'Python'):
                release.approved_release_view(operation='status', require_store=False)

    def test_invalid_release_config_refused(self):
        path = self.repo / release.CONFIG_REL
        body = json.loads(path.read_text())
        body['repair_action'] = 'RestartSharedAccess'
        path.write_text(json.dumps(body))
        with self.authorized(), self.assertRaises(policy.ReleasePolicyError):
            release.approved_release_view(operation='status', require_store=False)

    def test_release_config_symlink_refused(self):
        path = self.repo / release.CONFIG_REL
        target = self.repo / 'other.json'
        path.rename(target)
        try:
            path.symlink_to(target)
        except (NotImplementedError, OSError):
            self.skipTest('symlink unavailable')
        with self.authorized(), self.assertRaisesRegex(release.ReleaseReadError, 'redirected'):
            release.approved_release_view(operation='status', require_store=False)

    def test_release_directory_symlink_refused(self):
        outer = Path(self.temp.name) / 'elsewhere'
        outer.mkdir()
        try:
            (self.appdata / release.RELEASE_SUBDIR).symlink_to(outer, target_is_directory=True)
        except (NotImplementedError, OSError):
            self.skipTest('symlink unavailable')
        with self.authorized(), self.assertRaisesRegex(release.ReleaseReadError, 'redirected'):
            release.approved_release_view(operation='status', require_store=False)

    def test_localappdata_missing_refused(self):
        with mock.patch.dict(os.environ, {'LOCALAPPDATA': ''}):
            with self.assertRaisesRegex(release.ReleaseReadError, 'LOCALAPPDATA'):
                release._checked_release_state()

    def test_localappdata_relative_refused(self):
        with mock.patch.dict(os.environ, {'LOCALAPPDATA': 'Relative\\State'}):
            with self.assertRaisesRegex(release.ReleaseReadError, 'invalid'):
                release._checked_release_state()

    def test_release_parent_as_file_refused(self):
        (self.appdata / release.RELEASE_SUBDIR).write_text('not a directory')
        with mock.patch.dict(os.environ, {'LOCALAPPDATA': str(self.appdata)}):
            with self.assertRaisesRegex(release.ReleaseReadError, 'not a directory'):
                release._checked_release_state()

    def test_status_event_limit_rejected(self):
        self.initialized()
        with self.authorized(), self.assertRaises(Exception):
            release.read_release_view(operation='status', events=21)

    def test_report_staleness_threshold_rejected(self):
        self.initialized()
        with self.authorized(), self.assertRaises(Exception):
            release.read_release_view(operation='report', stale_minutes=0)

    def test_cli_status_json_renders_sanitized_json(self):
        self.initialized()
        with self.authorized(), contextlib.redirect_stdout(io.StringIO()) as out:
            code = release.main(['--status', '--json'])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload['phase'], 'Healthy')
        self.assertNotIn('HIDDEN-PRIVATE-REASON', out.getvalue())

    def test_cli_report_text_uses_release_header(self):
        self.initialized()
        with self.authorized(), contextlib.redirect_stdout(io.StringIO()) as out:
            code = release.main(['--report'])
        self.assertEqual(code, 0)
        self.assertIn('(release)', out.getvalue())
        self.assertIn('Historical', out.getvalue())
        self.assertNotIn('HIDDEN-PRIVATE-REASON', out.getvalue())

    def test_cli_status_text_uses_release_header(self):
        self.initialized()
        with self.authorized(), contextlib.redirect_stdout(io.StringIO()) as out:
            code = release.main(['--status'])
        self.assertEqual(code, 0)
        self.assertIn('(release)', out.getvalue())
        self.assertIn('NO new USB/ICS probe', out.getvalue())

    def test_cli_invalid_flags_refuse(self):
        for args in (['--status', '--report'], ['--status', '--live-read-only'],
                     ['--report', '--initialize-new'], [], ['--status','--config','x']):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    release.main(args)

    def test_cli_status_stale_minutes_refused(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(release.main(['--status', '--stale-minutes', '30']), 1)
        self.assertIn('REFUSED', err.getvalue())

    def test_no_network_execution_or_writes_from_views(self):
        self.initialized()
        before = {p.name: p.read_bytes() for p in self.state.iterdir()}
        with self.authorized(), \
             mock.patch.object(live, 'run_existing_runner', side_effect=AssertionError('live used')), \
             mock.patch.object(live, 'execute_one_cycle', side_effect=AssertionError('cycle used')), \
             mock.patch('socket.socket', side_effect=AssertionError('socket used')), \
             mock.patch.object(Path, 'mkdir', side_effect=AssertionError('mkdir used')):
            self.assertEqual(release.read_release_view(operation='status')['generation'], 1)
            self.assertEqual(release.read_release_view(operation='report', now_utc=START)['generation'], 1)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.state.iterdir()})

    def test_release_context_does_not_require_old_main_sha_or_backup(self):
        self.initialized()
        calls = []
        def git(root, *args):
            calls.append(args)
            return 'main' if args[:2] == ('branch', '--show-current') else ''
        with self.authorized(git=git):
            release.read_release_view(operation='status')
        self.assertFalse(any('merge-base' in args or 'rev-parse' in args for args in calls))
        self.assertNotIn('Send-OnyxTelemetry.pre-v050', str(calls))

    def test_status_report_outputs_remain_consistent(self):
        self.initialized()
        with self.authorized():
            s = release.read_release_view(operation='status')
            r = release.read_release_view(operation='report', now_utc=START + timedelta(minutes=2))
        self.assertEqual((s['generation'], s['processed_cycles']),
                         (r['generation'], r['processed_cycles']))
        self.assertEqual(s['display_status'], r['display_status_at_observation'])
        self.assertFalse(s['live_probed'] or r['live_probed'])

    def test_missing_config_file_refuses_without_creating(self):
        path = self.repo / release.CONFIG_REL
        path.unlink()
        with self.authorized(), self.assertRaisesRegex(release.ReleaseReadError, 'absent'):
            release.approved_release_view(operation='status', require_store=False)
        self.assertFalse(path.exists())

    def test_bad_marker_refuses_and_preserves_exact_bytes(self):
        self.initialized()
        marker = self.state / live.MARKER_NAME
        marker.write_bytes(b'BAD MARKER')
        with self.authorized(), self.assertRaises(Exception):
            release.read_release_view(operation='status')
        self.assertEqual(marker.read_bytes(), b'BAD MARKER')


if __name__ == '__main__':
    unittest.main()
