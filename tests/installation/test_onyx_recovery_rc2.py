#!/usr/bin/env python3
"""RC2 M5 interrupted-state recovery: synthetic host tests; never live services."""
from __future__ import annotations
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'tests/installation/test_onyx_cutover_rehearsal.py'
spec = importlib.util.spec_from_file_location('cutover_fixture_rc2', BASE)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
mod = base.mod
SHA = base.SHA

@unittest.skipUnless(os.name == 'posix', 'Pi synthetic recovery behavior requires POSIX')
class RecoveryTest(unittest.TestCase):
    advance = base.PiTest.advance

    def setUp(self):
        base.PiTest.setUp(self)
        self.real_run = self.host.run

    def candidate_registration(self):
        with redirect_stdout(io.StringIO()):
            mod.escrow(SHA)
            mod.quiesce(SHA)
        self.host.fail_candidate_start = True
        with self.assertRaises(mod.Refused):
            mod.activate(SHA)
        self.host.fail_candidate_start = False
        self.assertEqual(json.loads(mod.JOURNAL.read_bytes())['phase'],
                         'candidate-unit-registered')

    def test_resume_activation_starts_exact_registered_service_once(self):
        self.candidate_registration()
        with redirect_stdout(io.StringIO()):
            mod.resume_activate(SHA)
        self.assertTrue(self.host.candidate_active)
        self.assertFalse(self.host.candidate_enabled)
        self.assertEqual(json.loads(mod.JOURNAL.read_bytes())['phase'],
                         'candidate-running-rehearsal')
        self.assertEqual(sum(1 for cmd in self.host.trace if cmd[:2] == ('systemctl','start')
                             and cmd[2] == mod.CANDIDATE), 2)  # failed first + recovered

    def test_resume_activation_does_not_restart_healthy_candidate(self):
        self.candidate_registration()
        self.host.candidate_active = True  # started, crash before journal commit
        with redirect_stdout(io.StringIO()):
            mod.resume_activate(SHA)
        self.assertEqual(sum(1 for cmd in self.host.trace if cmd[:2] == ('systemctl','start')
                             and cmd[2] == mod.CANDIDATE), 1)

    def test_resume_activation_rejects_unexpected_candidate_autostart(self):
        self.candidate_registration()
        self.host.candidate_enabled = True
        before = mod.JOURNAL.read_bytes()
        with self.assertRaisesRegex(mod.Refused, 'unexpected boot startup'):
            mod.resume_activate(SHA)
        self.assertEqual(before, mod.JOURNAL.read_bytes())

    def test_reconcile_rollback_when_services_restored_does_not_touch_services_or_data(self):
        self.advance()
        # Simulate interruption after final service start, before set_phase.
        real_set_phase = mod.set_phase
        def interrupted(doc, phase):
            if phase == 'rolled-back':
                raise mod.Refused('synthetic journal interruption')
            return real_set_phase(doc, phase)
        with patch.object(mod, 'set_phase', side_effect=interrupted):
            with self.assertRaisesRegex(mod.Refused, 'synthetic journal interruption'):
                mod.rollback(SHA)
        journal_before = json.loads(mod.JOURNAL.read_bytes())
        self.assertEqual(journal_before['phase'], 'candidate-running-rehearsal')
        operations = list(self.host.trace)
        database_before = self.telemetry.read_bytes()
        snapshot_before = self.snapshot.read_bytes()
        # Mock only socket ownership report; unit pid is supplied by synthetic host.
        old_property = mod.unit_property
        def property_with_mainpid(unit, prop):
            return '2922' if prop == 'MainPID' else old_property(unit, prop)
        class Result:
            stdout = 'LISTEN 0 5 192.168.137.167:8765 0.0.0.0:* users:(("python3",pid=2922,fd=4))\n'
        def run_with_ss(*args, **kwargs):
            if args[0] == 'ss': return Result()
            return self.real_run(*args, **kwargs)
        with patch.object(mod, 'unit_property', side_effect=property_with_mainpid), \
             patch.object(mod, 'run', side_effect=run_with_ss), \
             redirect_stdout(io.StringIO()):
            mod.reconcile_rollback(SHA)
        self.assertEqual(self.host.trace, operations)  # no service mutations
        self.assertEqual(database_before, self.telemetry.read_bytes())
        self.assertEqual(snapshot_before, self.snapshot.read_bytes())
        self.assertEqual(json.loads(mod.JOURNAL.read_bytes())['phase'], 'rolled-back')

    def test_reconcile_rollback_refuses_active_candidate(self):
        self.advance()
        original = mod.JOURNAL.read_bytes()
        with self.assertRaisesRegex(mod.Refused, 'not fully restored'):
            mod.reconcile_rollback(SHA)
        self.assertEqual(original, mod.JOURNAL.read_bytes())

    def test_reconcile_rollback_refuses_wrong_legacy_socket_owner(self):
        self.advance()
        self.host.candidate_active = False
        self.host.legacy_active = True
        self.host.legacy_enabled = True
        mod.DROPIN.unlink()
        original = mod.JOURNAL.read_bytes()
        old_property = mod.unit_property
        def property_with_mainpid(unit, prop):
            return '2922' if prop == 'MainPID' else old_property(unit, prop)
        class Result:
            stdout = 'LISTEN 0 5 192.168.137.167:8765 0.0.0.0:* users:(("python3",pid=3999,fd=4))\n'
        with patch.object(mod, 'unit_property', side_effect=property_with_mainpid), \
             patch.object(mod, 'run', return_value=Result()):
            with self.assertRaisesRegex(mod.Refused, 'does not own'):
                mod.reconcile_rollback(SHA)
        self.assertEqual(original, mod.JOURNAL.read_bytes())

class WindowsRecoveryContractTest(unittest.TestCase):
    def test_explicit_windows_recovery_phases_are_gated(self):
        s = (ROOT/'tools/installation/windows/Invoke-OnyxV090Rehearsal.ps1').read_text()
        self.assertIn("if ($Phase -eq 'ResumeCandidate')", s)
        self.assertIn("if ($record.phase -cne 'candidate-registration-created')", s)
        self.assertIn("if ($Phase -eq 'ReconcileLegacy')", s)
        self.assertIn("if ($Phase -eq 'ResumeLegacy')", s)
        self.assertIn("if ($record.phase -cne 'candidate-quiesced')", s)
        self.assertIn("if ($record.phase -notin @('candidate-quiesced','quiescing'))", s)
        self.assertIn('ConfirmCandidatePiActive', s)
        self.assertIn('ConfirmLegacyPiRestored', s)
        self.assertIn("Set-State $record 'candidate-running-rehearsal'", s)
        self.assertIn("Set-State $record 'rolled-back'", s)

if __name__ == '__main__':
    unittest.main(verbosity=2)
