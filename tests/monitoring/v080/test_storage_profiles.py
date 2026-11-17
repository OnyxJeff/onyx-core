"""Phase 17 storage isolation: synthetic/tempfile only; no real probes or alerts."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main, mock
import os
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'windows/monitoring/v080'))
sys.path.insert(0, str(ROOT / 'windows/gateway'))
from test_live_incident_history import sample
import OnyxLiveIncidentHistory as m3
import OnyxMonitoringView as m4
import OnyxIncidentNotifications as m5


class StorageProfilesTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    @contextmanager
    def environment(self, profile=None):
        with mock.patch.dict(os.environ, {'LOCALAPPDATA': str(self.base)}):
            if profile is None:
                os.environ.pop(m3.STORAGE_PROFILE_ENV, None)
            else:
                os.environ[m3.STORAGE_PROFILE_ENV] = profile
            yield

    def test_default_profile_is_development_and_no_file_created(self):
        with self.environment():
            self.assertEqual(m3.storage_profile(), 'development')
            self.assertEqual(m3.history_path(), self.base / 'OnyxCore-v080-Development' / 'Monitoring' / 'incident-history.sqlite3')
            self.assertFalse((self.base / 'OnyxCore-v080-Development').exists())
            self.assertFalse((self.base / 'OnyxCore-v080-Release').exists())

    def test_explicit_release_isolated_and_does_not_create_files(self):
        with self.environment('release'):
            self.assertEqual(m3.storage_profile(), 'release')
            self.assertEqual(m3.history_path(), self.base / 'OnyxCore-v080-Release' / 'Monitoring' / 'incident-history.sqlite3')
            self.assertFalse((self.base / 'OnyxCore-v080-Release').exists())

    def test_invalid_profiles_fail_closed_without_files(self):
        for value in ('', 'Release', 'development ', 'production', '../Release', 'release/../../', 'RELEASE', 'dev'):
            with self.subTest(value=value), self.environment(value):
                with self.assertRaises(m3.HistoryError):
                    m3.history_path()
                with self.assertRaises(m3.HistoryError):
                    m5.state_path()
        self.assertEqual(list(self.base.iterdir()), [])

    def test_invalid_profile_refuses_read_only_m3_and_m5_modes(self):
        with self.environment('bad'):
            with mock.patch.object(m3.m2, 'run_monitor', side_effect=AssertionError('probe forbidden')):
                self.assertEqual(m3.main(['--history']), 2)
                self.assertEqual(m3.main(['--check-config']), 2)
                self.assertEqual(m5.main(['--status']), 2)
                self.assertEqual(m5.main(['--check-config']), 2)
        self.assertEqual(list(self.base.iterdir()), [])

    def test_environment_does_not_control_arbitrary_directory(self):
        with mock.patch.dict(os.environ, {'LOCALAPPDATA': str(self.base), m3.STORAGE_PROFILE_ENV: 'release'}):
            self.assertEqual(m3.history_path().parent.parent.parent, self.base)

    def test_missing_or_relative_localappdata_fails_closed(self):
        with self.environment('release'):
            with mock.patch.dict(os.environ, {'LOCALAPPDATA': 'relative'}, clear=False):
                with self.assertRaises(m3.HistoryError):
                    m3.history_path()
            os.environ.pop('LOCALAPPDATA', None)
            with self.assertRaises(m3.HistoryError):
                m3.history_path()
        self.assertEqual(list(self.base.iterdir()), [])

    def test_symlinked_localappdata_refused_if_supported(self):
        with TemporaryDirectory() as parent:
            link = Path(parent) / 'alias'
            try:
                link.symlink_to(self.base, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('symlink creation unavailable on this platform')
            with mock.patch.dict(os.environ, {'LOCALAPPDATA': str(link), m3.STORAGE_PROFILE_ENV: 'release'}):
                with self.assertRaises(m3.HistoryError):
                    m3.history_path()

    def test_profiles_are_isolated_with_synthetic_history(self):
        with self.environment():
            development = m3.history_path()
            m3.record_cycle(development, sample())
            self.assertEqual(m3.history_report(development)['recorded_checks'], 1)
        with self.environment('release'):
            release = m3.history_path()
            self.assertNotEqual(development, release)
            self.assertEqual(m3.history_report(release)['recorded_checks'], 0)
            self.assertFalse(release.exists())
            m3.record_cycle(release, sample('Degraded', windows='AdapterDown'))
            self.assertEqual(m3.history_report(release)['incident_count'], 1)
        with self.environment():
            self.assertEqual(m3.history_report(m3.history_path())['incident_count'], 0)
            self.assertEqual(m3.history_report(m3.history_path())['recorded_checks'], 1)

    def test_m4_snapshot_uses_selected_storage_and_never_writes(self):
        with self.environment():
            development = m3.history_path()
            m3.record_cycle(development, sample())
        with self.environment('release'):
            release = m3.history_path()
            report = m4.snapshot()
            self.assertEqual(report['state'], 'NoData')
            self.assertFalse(release.exists())
            self.assertEqual(report['recorded_checks'], 0)
        with self.environment():
            self.assertEqual(m4.snapshot()['recorded_checks'], 1)

    def test_m5_cursor_matches_selected_history(self):
        for profile, folder in [('development','OnyxCore-v080-Development'),('release','OnyxCore-v080-Release')]:
            with self.subTest(profile=profile), self.environment(profile):
                journal = m3.history_path()
                cursor = m5.state_path()
                self.assertEqual(cursor, self.base / folder / 'Monitoring' / m5.CURSOR_DB_NAME)
                self.assertEqual(cursor, m5.state_path(journal))
                self.assertFalse(cursor.exists())

    def test_m5_status_does_not_initialize_selected_history_or_cursor(self):
        for profile in ('development', 'release'):
            with self.subTest(profile=profile), self.environment(profile):
                with mock.patch.object(m5, 'send_webhook', side_effect=AssertionError('delivery forbidden')):
                    self.assertEqual(m5.main(['--status']), 0)
                self.assertFalse(m3.history_path().exists())
                self.assertFalse(m5.state_path().exists())

    def test_notification_profile_resolved_once_per_main_call(self):
        with self.environment('release'):
            # If M5 recomputed history_path for the cursor, this side effect
            # would reject the second call. --status must never send alerts.
            with mock.patch.object(m5.m3, 'history_path', side_effect=[m3.history_path(), AssertionError('reselected')]) as path:
                self.assertEqual(m5.main(['--status']), 0)
                self.assertEqual(path.call_count, 1)


if __name__ == '__main__':
    main()
