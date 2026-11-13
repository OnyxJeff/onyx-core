"""Phase 18G1: deterministic tests only. Never call native Windows APIs."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import importlib.util
import sys
import unittest

SOURCE = (Path(__file__).resolve().parents[3] /
          'windows/monitoring/v080/OnyxWindowsNativeAdmission.py')
SPEC = importlib.util.spec_from_file_location('onyx_phase18g_native', SOURCE)
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)

SID = 'S-1-5-21-101-202-303-1001'
OTHER = 'S-1-5-21-101-202-303-1002'


class NativeAdmissionTests(unittest.TestCase):
    def test_status_is_inert(self):
        d = MOD.inert_status()
        self.assertFalse(d['native_adapter_invoked'])
        self.assertFalse(d['trusted_enrollment_implemented'])
        self.assertFalse(d['live_runtime_enabled'])
        self.assertEqual(d['release_status'], 'HOLD')

    def test_name_uses_global_not_local_namespace(self):
        self.assertTrue(MOD.MUTEX_NAME.startswith('Global\\'))
        self.assertFalse(MOD.MUTEX_NAME.startswith('Local\\'))

    def test_protected_sddl_user_and_system_only(self):
        s = MOD.protected_sddl(SID)
        self.assertEqual(s, 'D:P(A;;GA;;;SY)(A;;GA;;;{})'.format(SID))
        self.assertNotIn(';;;WD', s)
        self.assertNotIn(';;;AU', s)

    def test_sid_bad_inputs_refused(self):
        for sid in (None, '', ' S-1-5-21-1', 'S-1-5-21-1\n',
                    'S-1-5-21-1);(A;;GA;;;WD)', 'S-1-abc-1',
                    'S-1-5-21--1001', SID + '0'*190, 5, True):
            with self.subTest(sid=sid), self.assertRaises(MOD.NativeAdmissionRefused):
                MOD.validate_sid(sid)

    def test_valid_sid(self):
        self.assertEqual(MOD.validate_sid(SID), SID)

    def test_identity_mismatch_denied_before_lock(self):
        calls = []
        def factory(sid):
            calls.append(sid)
            raise AssertionError('lock must not be touched')
        with self.assertRaisesRegex(MOD.NativeAdmissionRefused, 'identity mismatch'):
            with MOD.verified_sid_mutex(SID, sid_reader=lambda: OTHER, mutex_factory=factory):
                self.fail('body ran')
        self.assertEqual(calls, [])

    def test_good_identity_lock_and_release(self):
        activity = []
        @contextmanager
        def lock(sid):
            activity.append(('lock', sid))
            try:
                yield
            finally:
                activity.append(('unlock', sid))
        with MOD.verified_sid_mutex(SID, sid_reader=lambda: SID, mutex_factory=lock):
            activity.append(('cycle', SID))
        self.assertEqual(activity, [('lock', SID), ('cycle', SID), ('unlock', SID)])

    def test_lock_refusal_blocks_body(self):
        @contextmanager
        def locked(_sid):
            raise MOD.NativeAdmissionRefused('already running')
            yield
        body = []
        with self.assertRaises(MOD.NativeAdmissionRefused):
            with MOD.verified_sid_mutex(SID, sid_reader=lambda: SID, mutex_factory=locked):
                body.append(1)
        self.assertEqual(body, [])

    def test_exception_releases_lock(self):
        events = []
        @contextmanager
        def lock(_):
            events.append('start')
            try:
                yield
            finally:
                events.append('stop')
        with self.assertRaisesRegex(ValueError, 'fixture'):
            with MOD.verified_sid_mutex(SID, sid_reader=lambda: SID, mutex_factory=lock):
                raise ValueError('fixture')
        self.assertEqual(events, ['start', 'stop'])

    def test_bad_expected_sid_does_not_read_token(self):
        called = []
        with self.assertRaises(MOD.NativeAdmissionRefused):
            with MOD.verified_sid_mutex('unsafe;', sid_reader=lambda: called.append(True)):
                self.fail('body ran')
        self.assertEqual(called, [])

    def test_bad_observed_sid_denied_before_lock(self):
        with self.assertRaises(MOD.NativeAdmissionRefused):
            with MOD.verified_sid_mutex(SID, sid_reader=lambda: 'bad SID',
                                        mutex_factory=lambda _: self.fail('mutex invoked')):
                self.fail('body ran')

    def test_non_windows_native_sid_refused(self):
        if MOD.os.name != 'nt':
            with self.assertRaises(MOD.NativeAdmissionRefused):
                MOD.current_process_sid()
        else:
            self.assertTrue(callable(MOD.current_process_sid))

    def test_cli_inert_only(self):
        self.assertEqual(MOD.main(['--check-inert']), 0)
        with self.assertRaises(SystemExit):
            MOD.main(['--live'])

    def test_missing_adapters_refused(self):
        with self.assertRaises(MOD.NativeAdmissionRefused):
            with MOD.verified_sid_mutex(SID, sid_reader=None):
                self.fail('body ran')


if __name__ == '__main__':
    unittest.main()
