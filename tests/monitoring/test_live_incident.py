"""Offline-only behavior tests. Nothing calls the network or real dev state."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest import mock

HERE = Path(__file__).resolve().parents[2] / "windows" / "monitoring"
sys.path.insert(0, str(HERE))
import OnyxLiveIncident as live
import OnyxIncidentStore as storage
import OnyxIncidentState as reducer


def cycle(minute=0, decision="Healthy", incomplete=False):
    from datetime import datetime, timezone, timedelta
    start = datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc) + timedelta(minutes=minute)
    end = start + timedelta(seconds=4)
    pi = "PiInternetVerified" if decision == "Healthy" else (
        "ExternalTcpUnverified" if decision == "PossibleIcsFailure" else "DnsUnverified")
    return {
        "schema_version": 1,
        "source": "LiveRestrictedDiagnostic",
        "cycle_started_utc": start.isoformat(),
        "cycle_finished_utc": end.isoformat(),
        "duration_ms": 4000,
        "cycle_status": "EvidenceIncomplete" if incomplete else "Complete",
        "connectivity_decision": "Investigate" if incomplete else decision,
        "decision_reason": "test only, must not persist",
        "windows_classification": "WindowsPathReady",
        "pi_classification": pi,
        "observation_count": 3 if decision == "PossibleIcsFailure" else 1,
        "consecutive_suspected": 3 if decision == "PossibleIcsFailure" else 0,
        "history_error_present": incomplete,
        "windows_error_present": False,
        "pi_error_present": False,
        "repair_action": "None",
    }


class LiveIncidentTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="onyx-live-offline-")
        self.addCleanup(self.scratch.cleanup)
        self.dir = Path(self.scratch.name) / "Monitoring"
        self.dir.mkdir()
        self.state, self.marker = live._state_paths(self.dir)

    def test_cannot_start_without_initialized_files(self):
        with self.assertRaisesRegex(live.LiveIncidentError, "missing"):
            live.apply_live_cycle(cycle(), self.dir)
        self.assertFalse(self.state.exists())

    def test_initialize_then_persist_healthy(self):
        out = live.apply_live_cycle(cycle(), self.dir, initialize_new=True)
        self.assertEqual(out["phase"], "Healthy")
        self.assertEqual(out["source"], "LiveIncidentIntegration")
        self.assertEqual(self.marker.read_bytes(), live.MARKER_BYTES)
        self.assertEqual(storage.load_store(self.state)["generation"], 1)

    def test_next_cycle_preserves_generation(self):
        live.apply_live_cycle(cycle(), self.dir, initialize_new=True)
        out = live.apply_live_cycle(cycle(1), self.dir)
        self.assertEqual(out["generation"], 2)

    def test_replay_idempotent(self):
        live.apply_live_cycle(cycle(), self.dir, initialize_new=True)
        before = self.state.read_bytes()
        out = live.apply_live_cycle(cycle(), self.dir)
        self.assertTrue(out["replayed"])
        self.assertEqual(self.state.read_bytes(), before)

    def test_state_lost_refuses_reset(self):
        live.apply_live_cycle(cycle(), self.dir, initialize_new=True)
        self.state.unlink()
        with self.assertRaisesRegex(live.LiveIncidentError, "missing"):
            live.apply_live_cycle(cycle(1), self.dir)
        with self.assertRaisesRegex(live.LiveIncidentError, "BOTH"):
            live.apply_live_cycle(cycle(1), self.dir, initialize_new=True)
        self.assertFalse(self.state.exists())

    def test_marker_lost_refuses_reset(self):
        live.apply_live_cycle(cycle(), self.dir, initialize_new=True)
        self.marker.unlink()
        with self.assertRaisesRegex(live.LiveIncidentError, "missing"):
            live.apply_live_cycle(cycle(1), self.dir)
        self.assertTrue(self.state.exists())

    def test_marker_invalid_rejected(self):
        live.apply_live_cycle(cycle(), self.dir, initialize_new=True)
        self.marker.write_bytes(b"invalid")
        before = self.state.read_bytes()
        with self.assertRaisesRegex(live.LiveIncidentError, "invalid"):
            live.apply_live_cycle(cycle(1), self.dir)
        self.assertEqual(self.state.read_bytes(), before)

    def test_tamper_store_refused_without_write(self):
        live.apply_live_cycle(cycle(), self.dir, initialize_new=True)
        self.state.write_bytes(b"corrupted")
        with self.assertRaises(storage.CorruptIncidentStore):
            live.apply_live_cycle(cycle(1), self.dir)
        self.assertEqual(self.state.read_bytes(), b"corrupted")

    def test_conflicting_input_refused_without_mutation(self):
        live.apply_live_cycle(cycle(), self.dir, initialize_new=True)
        bad = cycle(1)
        bad["repair_action"] = "Repair"
        before = self.state.read_bytes()
        with self.assertRaises(reducer.InvalidIncidentInput):
            live.apply_live_cycle(bad, self.dir)
        self.assertEqual(self.state.read_bytes(), before)

    def test_bad_initial_input_does_not_create_marker(self):
        bad = cycle()
        bad["repair_action"] = "Repair"
        with self.assertRaises(reducer.InvalidIncidentInput):
            live.apply_live_cycle(bad, self.dir, initialize_new=True)
        self.assertFalse(self.marker.exists())

    def test_initialization_never_overwrites_existing_state(self):
        live.apply_live_cycle(cycle(), self.dir, initialize_new=True)
        before = self.state.read_bytes()
        with self.assertRaisesRegex(live.LiveIncidentError, "BOTH"):
            live.apply_live_cycle(cycle(1), self.dir, initialize_new=True)
        self.assertEqual(self.state.read_bytes(), before)

    def test_evidence_incomplete_remains_unknown(self):
        live.apply_live_cycle(cycle(0, "PossibleIcsFailure"), self.dir, initialize_new=True)
        out = live.apply_live_cycle(cycle(1, "Investigate", incomplete=True), self.dir)
        self.assertEqual(out["phase"], "Active")
        self.assertEqual(out["display_status"], "Unknown")

    def test_recovery_persists_and_no_sensitive_reason(self):
        live.apply_live_cycle(cycle(0, "PossibleIcsFailure"), self.dir, initialize_new=True)
        live.apply_live_cycle(cycle(1), self.dir)
        out = live.apply_live_cycle(cycle(2), self.dir)
        self.assertEqual(out["phase"], "Recovered")
        self.assertNotIn("test only, must not persist", self.state.read_text(encoding="utf8"))
        self.assertNotIn("test only, must not persist", json.dumps(out))

    def test_runner_json_rejects_duplicate_fields(self):
        with self.assertRaises(live.LiveIncidentError):
            live.read_json_strict(b'{"schema_version":1,"schema_version":1}')

    def test_runner_json_rejects_nonfinite(self):
        with self.assertRaises(live.LiveIncidentError):
            live.read_json_strict(b'{"a": NaN}')

    def test_runner_json_rejects_oversize(self):
        with self.assertRaises(live.LiveIncidentError):
            live.read_json_strict(b'x' * 16385)

    def test_runner_json_valid(self):
        self.assertEqual(live.read_json_strict(json.dumps(cycle()).encode())["source"],
                         "LiveRestrictedDiagnostic")

    def test_runner_failure_never_persists(self):
        with mock.patch.object(live.WINDOWS_PS.__class__, 'is_file', return_value=True):
            with self.assertRaisesRegex(live.LiveIncidentError, "unsuccessfully"):
                live.run_existing_runner(Path(self.scratch.name), runner=lambda *a, **k: subprocess.CompletedProcess([], 1, b'', b'failure'))
        self.assertFalse(self.state.exists())

    def test_collector_returns_one_cycle_and_script_has_readonly_flag(self):
        seen = {}
        def fake(cmd, **kwargs):
            seen["cmd"] = cmd
            seen["timeout"] = kwargs["timeout"]
            return subprocess.CompletedProcess(cmd, 0, json.dumps(cycle()).encode(), b"")
        with mock.patch.object(live.WINDOWS_PS.__class__, 'is_file', return_value=True):
            result = live.run_existing_runner(Path(self.scratch.name), runner=fake)
        self.assertIn("-LiveReadOnly -Json", seen["cmd"][-1])
        self.assertEqual(result["repair_action"], "None")
        self.assertLessEqual(seen["timeout"], 120)

    def test_execute_preflight_refuses_missing_state_before_probe(self):
        calls = []
        with self.assertRaises(live.LiveIncidentError):
            live.execute_one_cycle(Path(self.scratch.name), self.dir, False,
                                   collect=lambda root: calls.append(root))
        self.assertEqual(calls, [])

    def test_execute_initialized_invokes_one_probe(self):
        calls = []
        out = live.execute_one_cycle(Path(self.scratch.name), self.dir, True,
                                     collect=lambda root: calls.append(root) or cycle())
        self.assertEqual(len(calls), 1)
        self.assertEqual(out["generation"], 1)

    def test_synthetic_test_never_calls_real_probe(self):
        self.assertFalse(self.state.exists())
        self.assertFalse(self.marker.exists())

    def test_cli_requires_opt_in(self):
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                live.main([])

    def test_no_scheduling_or_repairs_in_source(self):
        src = (HERE / "OnyxLiveIncident.py").read_text(encoding="utf8")
        for forbidden in ("Repair-ICS.ps1", "schtasks.exe", "Register-ScheduledTask", "netsh "):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
