"""ONYX CORE v0.7.0 M3 Step 1: *offline-only* cross-component resilience tests.

Every state file and probe result is synthetic and lives under TemporaryDirectory.
The live collector is never executed. Production/dev state paths are never used.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

MODULES = Path(__file__).resolve().parents[2] / "windows" / "monitoring"
sys.path.insert(0, str(MODULES))
import OnyxIncidentAdapter as adapter
import OnyxIncidentState as reducer
import OnyxIncidentStore as storage
import OnyxLiveIncident as live

BASE = datetime(2026, 11, 9, 20, 0, tzinfo=timezone.utc)


def cycle(seconds=0, decision="Healthy", *, incomplete=False, **changes):
    """Make a contract-valid, artificial M1 diagnostic with second precision."""
    ended = BASE + timedelta(seconds=seconds)
    started = ended - timedelta(seconds=4)
    data = {
        "schema_version": 1,
        "source": "LiveRestrictedDiagnostic",
        "cycle_started_utc": started.isoformat(),
        "cycle_finished_utc": ended.isoformat(),
        "duration_ms": 4000,
        "cycle_status": "EvidenceIncomplete" if incomplete else "Complete",
        "connectivity_decision": "Investigate" if incomplete else decision,
        "decision_reason": "PRIVATE-M3-DIAGNOSTIC-NOT-FOR-STORAGE",
        "windows_classification": "WindowsPathReady",
        "pi_classification": "PiInternetVerified",
        "observation_count": 1,
        "consecutive_suspected": 0,
        "history_error_present": bool(incomplete),
        "windows_error_present": False,
        "pi_error_present": False,
        "repair_action": "None",
    }
    if decision == "PossibleIcsFailure":
        data.update(pi_classification="ExternalTcpUnverified", observation_count=3,
                    consecutive_suspected=3)
    if incomplete:
        data["pi_classification"] = "PiProbeUnavailable"
    data.update(changes)
    return data


class M3ResilienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="onyx-m3-resilience-")
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name) / "Monitoring"
        self.dir.mkdir()
        self.state = self.dir / "incident-state.json"
        self.marker = self.dir / live.MARKER_NAME

    def begin(self, data=None):
        return live.apply_live_cycle(data if data is not None else cycle(0),
                                     self.dir, initialize_new=True)

    def advance(self, data):
        return live.apply_live_cycle(data, self.dir)

    def record(self):
        return storage.load_store(self.state)

    def event_types(self):
        return [e["event_type"] for e in self.record()["events"]]

    def test_windows_adapter_missing_opens_suspected_not_active(self):
        out = self.begin(cycle(0, "Investigate", windows_classification="AdapterMissing",
                               pi_classification="UsbInterfaceNotReady"))
        self.assertEqual(out["phase"], "Suspected")
        self.assertEqual(self.event_types(), ["IncidentOpened"])
        self.assertEqual(out["repair_action"], "None")

    def test_ics_service_stopped_does_not_claim_proven_root_cause(self):
        self.begin(cycle(0, "Investigate", windows_classification="IcsServiceStopped",
                         pi_classification="GatewayUnreachable"))
        out = self.advance(cycle(60, "Investigate", windows_classification="IcsServiceStopped",
                                 pi_classification="GatewayUnreachable"))
        self.assertEqual(out["phase"], "Suspected")
        self.assertEqual(self.event_types(), ["IncidentOpened"])

    def test_pi_dns_only_failure_is_not_confirmed_ics_failure(self):
        out = self.begin(cycle(0, "Investigate", pi_classification="DnsUnverified"))
        self.assertEqual(out["phase"], "Suspected")
        self.assertEqual(self.record()["events"][0]["connectivity_decision"], "Investigate")

    def test_uncorroborated_healthy_windows_only_signal_cannot_be_healthy(self):
        bad = cycle(0, "Healthy", pi_classification="DnsUnverified")
        with self.assertRaises(reducer.InvalidIncidentInput):
            self.begin(bad)
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.state.exists())

    def test_first_missing_evidence_is_unknown_without_open_incident(self):
        out = self.begin(cycle(0, incomplete=True))
        self.assertEqual(out["display_status"], "Unknown")
        self.assertEqual(out["phase"], "Unknown")
        self.assertIsNone(self.record()["state"]["incident"])
        self.assertEqual(self.event_types(), ["EvidenceIncomplete"])

    def test_repeated_missing_evidence_is_deduplicated(self):
        self.begin(cycle(0, incomplete=True))
        self.advance(cycle(60, incomplete=True))
        self.assertEqual(self.event_types(), ["EvidenceIncomplete"])
        self.assertEqual(self.record()["generation"], 2)

    def test_recovering_evidence_does_not_forge_prior_outage(self):
        self.begin(cycle(0, incomplete=True))
        out = self.advance(cycle(60))
        self.assertEqual(out["phase"], "Healthy")
        self.assertEqual(self.event_types(), ["EvidenceIncomplete", "EvidenceRestored"])
        self.assertNotIn("IncidentRecovered", self.event_types())

    def test_active_outage_survives_evidence_gap(self):
        self.begin(cycle(0, "PossibleIcsFailure"))
        out = self.advance(cycle(60, incomplete=True))
        self.assertEqual((out["phase"], out["display_status"]), ("Active", "Unknown"))
        self.assertEqual(self.record()["state"]["incident"]["status"], "Active")

    def test_recovery_candidate_is_cleared_by_missing_evidence(self):
        self.begin(cycle(0, "PossibleIcsFailure"))
        self.advance(cycle(60))
        self.advance(cycle(120, incomplete=True))
        out = self.advance(cycle(180))
        self.assertEqual(out["phase"], "Active")
        self.assertNotIn("IncidentRecovered", self.event_types())
        self.assertEqual(self.advance(cycle(240))["phase"], "Recovered")

    def test_active_requires_two_spaced_healthy_cycles(self):
        self.begin(cycle(0, "PossibleIcsFailure"))
        self.assertEqual(self.advance(cycle(60))["phase"], "Active")
        self.assertEqual(self.advance(cycle(79))["phase"], "Active")
        self.assertEqual(self.advance(cycle(100))["phase"], "Recovered")
        self.assertEqual(self.event_types(), ["IncidentOpened", "IncidentRecovered"])

    def test_long_gap_restarts_recovery_confirmation(self):
        self.begin(cycle(0, "PossibleIcsFailure"))
        self.advance(cycle(60))
        self.assertEqual(self.advance(cycle(380))["phase"], "Active")
        self.assertEqual(self.advance(cycle(420))["phase"], "Recovered")

    def test_new_failure_cancels_pending_recovery(self):
        self.begin(cycle(0, "PossibleIcsFailure"))
        self.advance(cycle(60))
        self.advance(cycle(80, "Investigate", pi_classification="DnsUnverified"))
        self.assertEqual(self.advance(cycle(100))["phase"], "Active")
        self.assertEqual(self.advance(cycle(140))["phase"], "Recovered")

    def test_suspected_recovers_after_one_healthy_cycle(self):
        first = self.begin(cycle(0, "WaitAndRetry"))
        out = self.advance(cycle(60))
        self.assertEqual((first["phase"], out["phase"]), ("Suspected", "Recovered"))
        self.assertEqual(self.event_types(), ["IncidentOpened", "IncidentRecovered"])

    def test_repeated_suspected_does_not_open_duplicate_incidents(self):
        self.begin(cycle(0, "WaitAndRetry"))
        for sec in (60, 120, 180):
            self.advance(cycle(sec, "Investigate", pi_classification="DnsUnverified"))
        self.assertEqual(self.event_types(), ["IncidentOpened"])
        self.assertEqual(self.record()["generation"], 4)

    def test_confirmed_ics_suspicion_escalates_once(self):
        self.begin(cycle(0, "Investigate", pi_classification="DnsUnverified"))
        first = self.advance(cycle(60, "PossibleIcsFailure"))
        second = self.advance(cycle(120, "PossibleIcsFailure"))
        self.assertEqual((first["phase"], second["phase"]), ("Active", "Active"))
        self.assertEqual(self.event_types(), ["IncidentOpened", "IncidentEscalated"])
        self.assertTrue(all(x["repair_action"] == "None" for x in self.record()["events"]))

    def test_recovered_new_failure_has_new_incident_id(self):
        self.begin(cycle(0, "WaitAndRetry"))
        original_id = self.record()["state"]["incident"]["id"]
        self.advance(cycle(60))
        self.advance(cycle(120))
        self.advance(cycle(180, "WaitAndRetry"))
        new_id = self.record()["state"]["incident"]["id"]
        self.assertNotEqual(original_id, new_id)
        self.assertEqual(self.event_types().count("IncidentOpened"), 2)

    def test_replayed_cycle_does_not_rewrite_state(self):
        data = cycle(0, "WaitAndRetry")
        self.begin(data)
        old = self.state.read_bytes()
        out = self.advance(copy.deepcopy(data))
        self.assertTrue(out["replayed"])
        self.assertEqual(old, self.state.read_bytes())
        self.assertEqual(out["generation"], 1)

    def test_conflicting_same_timestamp_fails_without_write(self):
        self.begin(cycle(0))
        old = self.state.read_bytes()
        with self.assertRaises(reducer.InvalidIncidentInput):
            self.advance(cycle(0, "WaitAndRetry"))
        self.assertEqual(old, self.state.read_bytes())

    def test_backdated_cycle_fails_without_write(self):
        self.begin(cycle(80))
        old = self.state.read_bytes()
        with self.assertRaises(reducer.InvalidIncidentInput):
            self.advance(cycle(40))
        self.assertEqual(old, self.state.read_bytes())

    def test_false_corroboration_insufficient_samples_fails_without_write(self):
        self.begin(cycle(0))
        old = self.state.read_bytes()
        with self.assertRaises(reducer.InvalidIncidentInput):
            self.advance(cycle(60, "PossibleIcsFailure", consecutive_suspected=2))
        self.assertEqual(old, self.state.read_bytes())

    def test_false_corroboration_wrong_pi_classification_fails(self):
        self.begin(cycle(0))
        old = self.state.read_bytes()
        with self.assertRaises(reducer.InvalidIncidentInput):
            self.advance(cycle(60, "PossibleIcsFailure", pi_classification="DnsUnverified"))
        self.assertEqual(old, self.state.read_bytes())

    def test_unsanctioned_repair_action_is_rejected(self):
        self.begin(cycle(0))
        old = self.state.read_bytes()
        with self.assertRaises(reducer.InvalidIncidentInput):
            self.advance(cycle(60, repair_action="RestartIcs"))
        self.assertEqual(old, self.state.read_bytes())

    def test_unapproved_source_is_rejected(self):
        self.begin(cycle(0))
        old = self.state.read_bytes()
        with self.assertRaises(reducer.InvalidIncidentInput):
            self.advance(cycle(60, source="InjectedLiveCommand"))
        self.assertEqual(old, self.state.read_bytes())

    def test_corrupt_state_refuses_overwrite(self):
        self.begin()
        self.state.write_bytes(b"{damaged")
        with self.assertRaises(storage.CorruptIncidentStore):
            self.advance(cycle(60))
        self.assertEqual(self.state.read_bytes(), b"{damaged")

    def test_missing_store_blocks_probe_before_collection(self):
        self.begin()
        self.state.unlink()
        collect = mock.Mock(return_value=cycle(60))
        with self.assertRaisesRegex(live.LiveIncidentError, "missing"):
            live.execute_one_cycle(MODULES.parents[1], self.dir, False, collect=collect)
        collect.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_missing_marker_blocks_probe_before_collection(self):
        self.begin()
        self.marker.unlink()
        collect = mock.Mock(return_value=cycle(60))
        with self.assertRaisesRegex(live.LiveIncidentError, "missing"):
            live.execute_one_cycle(MODULES.parents[1], self.dir, False, collect=collect)
        collect.assert_not_called()

    def test_malformed_marker_blocks_probe_before_collection(self):
        self.begin()
        self.marker.write_bytes(b"invalid")
        collect = mock.Mock(return_value=cycle(60))
        with self.assertRaisesRegex(live.LiveIncidentError, "invalid"):
            live.execute_one_cycle(MODULES.parents[1], self.dir, False, collect=collect)
        collect.assert_not_called()

    def test_invalid_collector_output_cannot_overwrite_state(self):
        self.begin()
        old = self.state.read_bytes()
        bad = cycle(60, "Healthy", windows_classification="AdapterDown")
        collect = mock.Mock(return_value=bad)
        with self.assertRaises(reducer.InvalidIncidentInput):
            live.execute_one_cycle(MODULES.parents[1], self.dir, False, collect=collect)
        collect.assert_called_once()
        self.assertEqual(old, self.state.read_bytes())

    def test_collector_crash_does_not_overwrite_store(self):
        self.begin()
        old = self.state.read_bytes()
        collect = mock.Mock(side_effect=RuntimeError("mock crash"))
        with self.assertRaisesRegex(RuntimeError, "mock crash"):
            live.execute_one_cycle(MODULES.parents[1], self.dir, False, collect=collect)
        self.assertEqual(old, self.state.read_bytes())

    def test_atomic_rename_failure_preserves_prior_transaction(self):
        self.begin()
        old = self.state.read_bytes()
        with mock.patch.object(storage.os, "replace", side_effect=OSError("simulated atomic rename failure")):
            with self.assertRaises(OSError):
                self.advance(cycle(60, "WaitAndRetry"))
        self.assertEqual(old, self.state.read_bytes())
        self.assertEqual(self.record()["generation"], 1)
        self.assertEqual(list(self.dir.glob(".onyx-incident-*.tmp")), [])

    def test_overlapping_cycle_is_refused_without_collecting(self):
        self.begin()
        old = self.state.read_bytes()
        collect = mock.Mock(return_value=cycle(60))
        with live._single_cycle_lock(self.dir):
            with self.assertRaisesRegex(live.LiveIncidentError, "already active"):
                live.execute_one_cycle(MODULES.parents[1], self.dir, False, collect=collect)
        collect.assert_not_called()
        self.assertEqual(old, self.state.read_bytes())

    def test_no_real_probe_or_production_path_used(self):
        self.assertFalse(self.state.exists())
        self.assertFalse(self.marker.exists())
        self.assertTrue(str(self.dir).startswith(self.temp.name))
        self.assertFalse(str(self.dir).casefold().startswith(str(live.APPROVED_DEV).casefold()))
        self.assertFalse(str(self.dir).casefold().startswith(str(live.APPROVED_PROD).casefold()))

    def test_private_details_never_persist_to_journal(self):
        self.begin(cycle(0, "WaitAndRetry"))
        data = self.state.read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE-M3-DIAGNOSTIC-NOT-FOR-STORAGE", data)
        self.assertNotIn("PRIVATE-M3-DIAGNOSTIC-NOT-FOR-STORAGE", json.dumps(self.record()))


if __name__ == "__main__":
    unittest.main()
