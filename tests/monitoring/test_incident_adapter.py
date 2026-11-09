"""Offline integration tests: no Pi, ICS, network, tasks or real development state."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

HERE = Path(__file__).resolve().parents[2] / "windows" / "monitoring"
sys.path.insert(0, str(HERE))
import OnyxIncidentAdapter as adapter
import OnyxIncidentStore as storage

BASE = datetime(2026, 11, 9, 11, 0, 0, tzinfo=timezone.utc)


def cycle(seconds=0, decision="Healthy", complete=True, suspected=0):
    start = BASE + timedelta(seconds=seconds)
    end = start + timedelta(seconds=4)
    pi = "PiInternetVerified" if decision == "Healthy" else ("ExternalTcpUnverified" if decision == "PossibleIcsFailure" else "DnsUnverified")
    return {
        "schema_version": 1,
        "source": "LiveRestrictedDiagnostic",
        "cycle_started_utc": start.isoformat(),
        "cycle_finished_utc": end.isoformat(),
        "duration_ms": 4000,
        "cycle_status": "Complete" if complete else "EvidenceIncomplete",
        "connectivity_decision": decision if complete else "Investigate",
        "decision_reason": "synthetic fixture must not be stored",
        "windows_classification": "WindowsPathReady",
        "pi_classification": pi,
        "observation_count": max(1, suspected),
        "consecutive_suspected": suspected,
        "history_error_present": not complete,
        "windows_error_present": False,
        "pi_error_present": False,
        "repair_action": "None",
    }


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="onyx-adapter-tests-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "incident-state.json"

    def test_initial_healthy(self):
        out = adapter.apply_cycle_to_store(cycle(), self.path)
        self.assertEqual(out["phase"], "Healthy")
        self.assertEqual(out["display_status"], "Healthy")
        self.assertEqual(out["generation"], 1)
        self.assertEqual(out["transition_events"], [])

    def test_suspected_to_active_then_recovery_after_restart(self):
        seq = [cycle(0, "Investigate"), cycle(40, "PossibleIcsFailure", suspected=3),
               cycle(80, "Healthy"), cycle(120, "Healthy")]
        first = adapter.apply_cycle_to_store(seq[0], self.path)
        self.assertEqual(first["phase"], "Suspected")
        self.assertEqual(first["transition_events"][0]["event_type"], "IncidentOpened")
        second = adapter.apply_cycle_to_store(seq[1], self.path)
        self.assertEqual(second["phase"], "Active")
        self.assertEqual(second["transition_events"][0]["event_type"], "IncidentEscalated")
        self.assertEqual(second["incident_id"], first["incident_id"])
        self.assertEqual(adapter.apply_cycle_to_store(seq[2], self.path)["phase"], "Active")
        # New load acts like another monitoring process after restart.
        self.assertEqual(storage.load_store(self.path)["state"]["phase"], "Active")
        last = adapter.apply_cycle_to_store(seq[3], self.path)
        self.assertEqual(last["phase"], "Recovered")
        self.assertEqual(last["transition_events"][0]["event_type"], "IncidentRecovered")
        self.assertIsNone(last["incident_id"])
        self.assertEqual(storage.load_store(self.path)["generation"], 4)
        self.assertEqual(storage.load_store(self.path)["events_discarded"], 0)

    def test_restart_replay_is_idempotent(self):
        a = cycle(0, "Investigate")
        adapter.apply_cycle_to_store(a, self.path)
        before = self.path.read_bytes()
        repeated = adapter.apply_cycle_to_store(a, self.path)
        self.assertTrue(repeated["replayed"])
        self.assertEqual(repeated["transition_events"], [])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(repeated["generation"], 1)

    def test_missing_evidence_does_not_recover(self):
        adapter.apply_cycle_to_store(cycle(0, "PossibleIcsFailure", suspected=3), self.path)
        state = adapter.apply_cycle_to_store(cycle(60, complete=False), self.path)
        self.assertEqual(state["phase"], "Active")
        self.assertEqual(state["display_status"], "Unknown")
        self.assertEqual(state["transition_events"][0]["event_type"], "EvidenceIncomplete")
        self.assertIsNotNone(state["incident_id"])

    def test_bad_cycle_rejected_without_storage_change(self):
        adapter.apply_cycle_to_store(cycle(), self.path)
        before = self.path.read_bytes()
        bad = cycle(60)
        bad["repair_action"] = "RepairICS"
        with self.assertRaises(ValueError):
            adapter.apply_cycle_to_store(bad, self.path)
        self.assertEqual(before, self.path.read_bytes())

    def test_out_of_order_rejected_without_storage_change(self):
        adapter.apply_cycle_to_store(cycle(60), self.path)
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            adapter.apply_cycle_to_store(cycle(0), self.path)
        self.assertEqual(before, self.path.read_bytes())

    def test_corrupt_store_remains_untouched(self):
        adapter.apply_cycle_to_store(cycle(0), self.path)
        self.path.write_bytes(b'{"broken":true}')
        with self.assertRaises(storage.CorruptIncidentStore):
            adapter.apply_cycle_to_store(cycle(60), self.path)
        self.assertEqual(self.path.read_bytes(), b'{"broken":true}')

    def test_final_summary_is_sanitized(self):
        input_cycle = cycle(0)
        out = adapter.apply_cycle_to_store(input_cycle, self.path)
        encoded = json.dumps(out)
        self.assertNotIn("synthetic fixture must not be stored", encoded)
        self.assertEqual(out["repair_action"], "None")
        self.assertEqual(out["source"], "SyntheticIncidentIntegration")
        self.assertEqual(input_cycle["decision_reason"], "synthetic fixture must not be stored")

    def test_simulation_sequence(self):
        seq = [cycle(0, "Investigate"), cycle(60, "PossibleIcsFailure", suspected=3),
               cycle(120, "Healthy"), cycle(180, "Healthy"), cycle(180, "Healthy")]
        out = adapter.simulate_cycles(seq, self.path)
        self.assertEqual(out["cycles_committed"], 4)
        self.assertEqual(out["cycles_replayed"], 1)
        self.assertEqual(out["transition_events_emitted"], 3)
        self.assertEqual(out["final"]["phase"], "Recovered")
        self.assertEqual(out["journal_count"], 3)

    def test_simulate_rejects_empty_and_bad_sequences(self):
        for value in ([], [None], "bad", [cycle()] * 65):
            with self.assertRaises(adapter.IncidentAdapterError):
                adapter.simulate_cycles(value, self.path)
        self.assertFalse(self.path.exists())

    def test_parse_sequence_roundtrip(self):
        path = Path(self.temp.name) / 'cycles.json'
        path.write_text(json.dumps({"schema_version":1,"cycles":[cycle()]}), encoding='utf8')
        self.assertEqual(adapter.read_sequence(path)[0]['source'], 'LiveRestrictedDiagnostic')
        self.assertFalse(self.path.exists())

    def test_parse_sequence_duplicate_key(self):
        path = Path(self.temp.name) / 'cycles.json'
        path.write_text('{"schema_version":1,"schema_version":1,"cycles":[]}',encoding='utf8')
        with self.assertRaises(adapter.IncidentAdapterError):
            adapter.read_sequence(path)

    def test_parse_sequence_invalid_type(self):
        path = Path(self.temp.name) / 'cycles.json'
        path.write_text('{"schema_version":1,"cycles":[null]}',encoding='utf8')
        with self.assertRaises(adapter.IncidentAdapterError):
            adapter.read_sequence(path)

    def test_parse_sequence_nonfinite(self):
        path = Path(self.temp.name) / 'cycles.json'
        path.write_text('{"schema_version":1,"cycles":[NaN]}',encoding='utf8')
        with self.assertRaises(adapter.IncidentAdapterError):
            adapter.read_sequence(path)

    def test_parse_sequence_too_large(self):
        path = Path(self.temp.name) / 'cycles.json'
        path.write_bytes(b'x' * (adapter.MAX_SEQUENCE_BYTES + 1))
        with self.assertRaises(adapter.IncidentAdapterError):
            adapter.read_sequence(path)

    def test_packaged_fixture_reproduces_recovery_and_replay(self):
        fixture = Path(__file__).resolve().parent / 'fixtures' / 'm2_incident_sequence.json'
        steps = adapter.read_sequence(fixture)
        out = adapter.simulate_cycles(steps, self.path)
        self.assertEqual(out['final']['phase'], 'Recovered')
        self.assertEqual(out['cycles_committed'], 4)
        self.assertEqual(out['cycles_replayed'], 1)
        self.assertEqual(out['transition_events_emitted'], 3)

    def test_snapshot_bounds(self):
        seq = [cycle(i * 40) for i in range(40)]
        result = adapter.simulate_cycles(seq, self.path)
        self.assertEqual(result["cycles_committed"], 40)
        self.assertLess(self.path.stat().st_size, storage.MAX_RECORD_BYTES)

    def test_no_default_store_path_or_live_entry(self):
        text = (HERE / "OnyxIncidentAdapter.py").read_text(encoding="utf8")
        self.assertIn("TemporaryDirectory(", text)
        self.assertNotIn('subprocess.Popen(', text)
        self.assertNotIn('Invoke-OnyxMonitoringCycle', text)
        self.assertNotIn('Repair-ICS.ps1', text)
        self.assertNotIn('schtasks', text)

    def test_import_has_no_side_effects(self):
        self.assertFalse(self.path.exists())
        self.assertEqual(adapter.SCHEMA, 1)
        self.assertFalse(self.path.exists())

    def test_rehash_existing_event_does_not_misreport(self):
        first = adapter.apply_cycle_to_store(cycle(0, 'Investigate'),self.path)
        self.assertEqual(first['transition_events'][0]['event_type'],'IncidentOpened')
        state = storage.load_store(self.path)
        self.assertEqual(state['events'][0]['event_id'], first['transition_events'][0]['event_id'])

    def test_approved_cli_guards_windows_only(self):
        if os.name != 'nt':
            with self.assertRaises(adapter.IncidentAdapterError):
                adapter.assert_approved_development_cli()

    def test_recovery_rejected_after_incomplete_then_single_good(self):
        seq = [cycle(0,'PossibleIcsFailure',suspected=3),cycle(50,'Healthy'),
               cycle(100,complete=False),cycle(150,'Healthy')]
        out=adapter.simulate_cycles(seq,self.path)
        self.assertEqual(out['final']['phase'],'Active')
        self.assertEqual(out['final']['display_status'],'Active')


if __name__ == '__main__':
    unittest.main()
