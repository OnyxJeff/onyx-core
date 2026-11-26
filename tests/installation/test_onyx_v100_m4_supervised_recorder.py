"""Offline tests of orchestration, with real disposable SQLite history."""
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'windows/monitoring/v100'), str(ROOT / 'tests/monitoring/v080')]
import OnyxV100SupervisedRecorder as recorder
from test_live_incident_history import sample


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'LOCALAPPDATA': self.temp.name})
        env.start()
        self.addCleanup(env.stop)
        self.path = recorder.view.history_path()
        self.locked = False
        self.allowed = True
        self.observed = False
        self.attested = True
        self.legacy = Path(self.temp.name)/'OnyxCore-v080-Release'/'Monitoring'/self.path.name
        self.legacy.parent.mkdir(parents=True)
        self.legacy.write_bytes(b'legacy')

    @contextmanager
    def lock(self):
        self.assertFalse(self.locked)
        self.locked = True
        try:
            yield
        finally:
            self.locked = False

    def prepare(self, path):
        self.assertTrue(self.locked)
        self.assertEqual(path, self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return True

    def attest(self, path):
        self.assertTrue(self.locked)
        self.assertEqual(path, self.path)
        return self.attested

    def observe(self):
        self.assertTrue(self.locked)
        self.observed = True
        return {'observation': sample('Healthy'), 'recommendation': 'NoRepairNeeded',
                'repair_performed': False, 'journal_written': False}

    def run_cycle(self, **kwargs):
        return recorder.supervised_cycle(**{'authorize': lambda: self.allowed,
            'exclusive': self.lock, 'prepare': self.prepare, 'attest': self.attest,
            'observe': self.observe, **kwargs})

    def test_commit_and_projection(self):
        result = self.run_cycle()
        self.assertEqual(result['projection']['recorded_checks'], 1)
        self.assertEqual(result['journal_outcome']['event'], 'NoIncident')
        self.assertFalse(result['scheduler_enabled'])
        self.assertFalse(self.locked)
        self.assertEqual(self.legacy.read_bytes(), b'legacy')

    def test_denied_before_provision_or_probe(self):
        self.allowed = False
        with self.assertRaises(recorder.binding.JournalRefused):
            self.run_cycle()
        self.assertFalse(self.observed)
        self.assertFalse(self.path.parent.exists())

    def test_bad_attestation_before_probe(self):
        self.attested = False
        with self.assertRaises(recorder.binding.JournalRefused):
            self.run_cycle()
        self.assertFalse(self.observed)
        self.assertFalse(self.path.exists())
        self.assertFalse(self.locked)

    def test_revoked_after_probe(self):
        def observe():
            result = self.observe()
            self.allowed = False
            return result
        with self.assertRaises(recorder.binding.JournalRefused):
            self.run_cycle(observe=observe)
        self.assertFalse(self.path.exists())
        self.assertFalse(self.locked)

    def test_side_effect_claim_refused(self):
        def observe():
            return {**self.observe(), 'repair_performed': True}
        with self.assertRaises(recorder.binding.JournalRefused):
            self.run_cycle(observe=observe)
        self.assertFalse(self.path.exists())

    def test_prepare_refused(self):
        with self.assertRaises(recorder.binding.JournalRefused):
            self.run_cycle(prepare=lambda path: False)
        self.assertFalse(self.observed)
        self.assertFalse(self.path.parent.exists())

    def test_cli_requires_explicit_recording_approval(self):
        with self.assertRaises(SystemExit):
            recorder.main([])
        self.assertFalse(self.path.parent.exists())
