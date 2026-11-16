"""Offline release-storage startup regression: no live Windows calls or probes."""
from __future__ import annotations
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'windows' / 'monitoring' / 'v080'))
import OnyxV080ProtectedLogonRuntime as runtime

NAME = 'ONYXCORE_V080_STORAGE_PROFILE'

class ReleaseStorageStartupTests(unittest.TestCase):
    def test_unset_profile_selects_release_only_during_monitor(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(NAME, None)
            seen = []
            def fake_loop(**kwargs):
                seen.append(os.environ.get(NAME))
                return {'result': 'CONSENT_REQUIRED', 'completed_sessions': 0}
            with patch.object(runtime, 'run_bounded_logon_loop', side_effect=fake_loop):
                self.assertEqual(runtime.run_monitor(), 0)
            self.assertEqual(seen, ['release'])
            self.assertNotIn(NAME, os.environ)

    def test_existing_release_profile_restored(self):
        with patch.dict(os.environ, {NAME: 'release'}):
            def fake_loop(**kwargs):
                self.assertEqual(os.environ.get(NAME), 'release')
                return {'result': 'CONSENT_REQUIRED', 'completed_sessions': 0}
            with patch.object(runtime, 'run_bounded_logon_loop', side_effect=fake_loop):
                self.assertEqual(runtime.run_monitor(), 0)
            self.assertEqual(os.environ[NAME], 'release')

    def test_development_profile_fails_without_any_session(self):
        with patch.dict(os.environ, {NAME: 'development'}):
            with patch.object(runtime, 'run_bounded_logon_loop', side_effect=AssertionError('launched')) as loop:
                self.assertEqual(runtime.run_monitor(), 2)
                loop.assert_not_called()
            self.assertEqual(os.environ[NAME], 'development')

    def test_unexpected_profile_fails_without_any_session(self):
        with patch.dict(os.environ, {NAME: 'invalid'}):
            with patch.object(runtime, 'run_bounded_logon_loop', side_effect=AssertionError('launched')) as loop:
                self.assertEqual(runtime.run_monitor(), 2)
                loop.assert_not_called()
            self.assertEqual(os.environ[NAME], 'invalid')

    def test_worker_error_restores_unset_profile(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(NAME, None)
            with patch.object(runtime, 'run_bounded_logon_loop', side_effect=RuntimeError('synthetic')):
                self.assertEqual(runtime.run_monitor(), 2)
            self.assertNotIn(NAME, os.environ)

    def test_keyboard_interrupt_restores_unset_profile(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(NAME, None)
            with patch.object(runtime, 'run_bounded_logon_loop', side_effect=KeyboardInterrupt):
                self.assertEqual(runtime.run_monitor(), 0)
            self.assertNotIn(NAME, os.environ)

if __name__ == '__main__':
    unittest.main()
