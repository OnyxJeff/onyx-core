"""Small offline cleanup classification tests; never deletes anything."""
from __future__ import annotations
import pathlib
import sys
import tempfile
import unittest
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'cleanup'))
import onyx_cleanup_report as cleanup


class CleanupTests(unittest.TestCase):
    def test_milestone_kit_is_not_deletable(self):
        actual, _ = cleanup.classify('ONYX_CORE_v090_M4_RuntimeRecovery_Devkit.zip')
        self.assertEqual(actual, 'HOLD_UNTIL_COMMITTED_RC')

    def test_protected_names_are_preserved(self):
        for name in ('Onyx-v080-backup.zip', 'Onyx_token.txt',
                     'Onyx_evidence_2026.txt', 'Onyx-rollback.ps1'):
            with self.subTest(name=name):
                self.assertEqual(cleanup.classify(name)[0], 'REVIEW_PRESERVE')

    def test_unknown_never_marked_safe(self):
        for name in ('ONYX_CORE_unrecognized_thing.py', 'hello.txt'):
            self.assertNotIn('DELETE', cleanup.classify(name)[0])

    def test_inventory_reports_counts_and_never_deletes(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            (d / 'ONYX_CORE_v090_M4_RuntimeRecovery_Devkit.zip').write_bytes(b'kit')
            (d / 'Onyx_v080_Audit.py').write_bytes(b'keep')
            (d / 'other.txt').write_bytes(b'other')
            x = cleanup.inventory(d)
            self.assertEqual(x['total_matching'], 2)
            self.assertFalse(x['deletion_authorized'])
            self.assertEqual(len(list(d.iterdir())), 3)

if __name__ == '__main__':
    unittest.main(verbosity=2)
