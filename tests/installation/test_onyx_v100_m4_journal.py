"""Synthetic-only v100 journal binding tests; no live authority or probes."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'windows/gateway'), str(ROOT / 'tests/monitoring/v080')]
import OnyxV100MonitoringJournal as binding
import OnyxV100MonitoringView as view
from test_live_incident_history import sample


class JournalBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        env = patch.dict(os.environ, {'LOCALAPPDATA': str(self.base),
                                      'ONYXCORE_V080_STORAGE_PROFILE': 'release'})
        env.start()
        self.addCleanup(env.stop)
        self.path = view.history_path()
        self.old = self.base / 'OnyxCore-v080-Release' / 'Monitoring' / self.path.name
        self.old.parent.mkdir(parents=True)
        self.old.write_bytes(b'legacy sentinel')
        self.now = datetime.now(timezone.utc) - timedelta(minutes=12)
        self.locked = False
        self.allow = True
        self.attested = True

    @contextmanager
    def lock(self):
        self.assertFalse(self.locked)
        self.locked = True
        try:
            yield
        finally:
            self.locked = False

    def attest(self, path):
        self.assertTrue(self.locked)
        self.assertEqual(path, self.path)
        return self.attested

    def observation(self, i=0, *, healthy=True):
        return sample('Healthy' if healthy else 'Degraded',
                      windows='WindowsPathReady' if healthy else 'AdapterDown',
                      timestamp=(self.now + timedelta(seconds=120*i)).isoformat(), cycle=i+1)

    def record(self, result=None, **kwargs):
        return binding.record_observation(result or self.observation(), **{
            'authorize': lambda: self.allow, 'attest_storage': self.attest,
            'exclusive': self.lock, **kwargs})

    def provision(self):
        self.path.parent.mkdir(parents=True)

    def test_no_authority_no_storage(self):
        self.allow = False
        with self.assertRaises(binding.JournalRefused):
            self.record()
        self.assertFalse(self.path.parent.exists())
        self.assertEqual(self.old.read_bytes(), b'legacy sentinel')

    def test_missing_provisioned_directory_refused(self):
        with self.assertRaises(binding.JournalRefused):
            self.record()
        self.assertFalse(self.path.parent.exists())

    def test_native_attestation_required(self):
        self.provision()
        self.attested = False
        with self.assertRaises(binding.JournalRefused):
            self.record()
        self.assertFalse(self.path.exists())
        self.assertFalse(self.locked)

    def test_confirmed_open_recover_and_projection(self):
        self.provision()
        outcomes = [self.record(self.observation(i, healthy=i>=3))['event'] for i in range(5)]
        self.assertEqual(outcomes, ['NoIncident','NoIncident','Opened','Ongoing','Recovered'])
        report = view.snapshot(now=self.now + timedelta(seconds=481))
        self.assertEqual(report['recorded_checks'], 5)
        self.assertEqual(report['incident_count'], 1)
        self.assertIsNone(report['open_incident'])
        self.assertEqual(self.old.read_bytes(), b'legacy sentinel')

    def test_duplicate_operation_preserves_one_check(self):
        self.provision()
        result = self.observation()
        self.assertEqual(self.record(result), self.record(result))
        self.assertEqual(view.snapshot()['recorded_checks'], 1)

    def test_contradictory_evidence_refused(self):
        self.provision()
        result = self.observation()
        result['status'] = 'Degraded'
        with self.assertRaises(binding.journal.HistoryError):
            self.record(result)
        self.assertFalse(self.path.exists())

    def test_revocation_before_cycle_commit_rolls_back(self):
        self.provision()
        self.record()
        original = binding.journal._lookup_receipt
        def revoke(*args, **kwargs):
            value = original(*args, **kwargs)
            self.allow = False
            return value
        with patch.object(binding.journal, '_lookup_receipt', side_effect=revoke):
            with self.assertRaises(binding.JournalRefused):
                self.record(self.observation(1))
        self.assertEqual(view.snapshot()['recorded_checks'], 1)
        self.assertFalse(self.locked)

    def test_hardlink_refused(self):
        self.provision()
        try:
            os.link(self.old, self.path)
        except OSError as exc:
            self.skipTest(f'hardlinks unavailable: {exc}')
        with self.assertRaises(ValueError):
            self.record()
        self.assertEqual(self.old.read_bytes(), b'legacy sentinel')

    def test_sidecar_hardlink_refused(self):
        self.provision()
        try:
            os.link(self.old, self.path.with_name(self.path.name+'-journal'))
        except OSError as exc:
            self.skipTest(f'hardlinks unavailable: {exc}')
        with self.assertRaises(ValueError):
            self.record()
        self.assertFalse(self.path.exists())
        self.assertEqual(self.old.read_bytes(), b'legacy sentinel')

    def test_changed_path_during_attestation_refused(self):
        self.provision()
        def change(path):
            os.environ['LOCALAPPDATA'] = str(self.base / 'elsewhere')
            return True
        with self.assertRaises(binding.JournalRefused):
            self.record(attest_storage=change)
        self.assertFalse(self.path.exists())
        self.assertFalse((self.base/'elsewhere').exists())


if __name__ == '__main__':
    unittest.main()
