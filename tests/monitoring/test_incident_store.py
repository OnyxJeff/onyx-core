"""Offline durable-store tests: temp directories, deterministic synthetic cycles, no probes."""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "windows" / "monitoring"))
import OnyxIncidentState as reducer
import OnyxIncidentStore as store

BASE = datetime(2026, 11, 9, 6, 0, tzinfo=timezone.utc)


def make_cycle(seconds=0, decision="Healthy", *, incomplete=False, **changes):
    finished = BASE + timedelta(seconds=seconds)
    started = finished - timedelta(seconds=4)
    cycle = {
        "schema_version": 1,
        "source": "LiveRestrictedDiagnostic",
        "cycle_started_utc": started.isoformat(),
        "cycle_finished_utc": finished.isoformat(),
        "duration_ms": 4000,
        "cycle_status": "EvidenceIncomplete" if incomplete else "Complete",
        "connectivity_decision": decision,
        "decision_reason": "PRIVATE-EVIDENCE-NOT-FOR-STORAGE",
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
        cycle.update(pi_classification="ExternalTcpUnverified", observation_count=3,
                     consecutive_suspected=3)
    if incomplete:
        cycle.update(connectivity_decision="Investigate", pi_classification="PiProbeUnavailable")
    cycle.update(changes)
    return cycle


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "Monitoring" / "incident-state.json"

    def step(self, seconds, decision="Healthy", **kw):
        return store.advance_store(self.path, make_cycle(seconds, decision, **kw))

    def test_missing_returns_initial_without_writes(self):
        self.assertEqual(store.load_store(self.path)["state"], reducer.initial_state())
        self.assertFalse(self.path.exists())

    def test_healthy_first_cycle_persists_atomically(self):
        result = self.step(0)
        self.assertEqual(result["state"]["phase"], "Healthy")
        self.assertEqual(result["events"], [])
        self.assertEqual(result["generation"], 1)
        self.assertTrue(self.path.exists())
        self.assertEqual(store.load_store(self.path)["state"], result["state"])
        self.assertLess(self.path.stat().st_size, store.MAX_RECORD_BYTES)

    def test_suspected_active_recovered_transaction_journal(self):
        self.step(0, "WaitAndRetry")
        self.step(40, "PossibleIcsFailure")
        candidate = self.step(80, "Healthy")
        self.assertEqual(candidate["state"]["phase"], "Active")
        recovered = self.step(120, "Healthy")
        self.assertEqual(recovered["state"]["phase"], "Recovered")
        disk = store.load_store(self.path)
        self.assertEqual([e["event_type"] for e in disk["events"]],
                         ["IncidentOpened", "IncidentEscalated", "IncidentRecovered"])
        self.assertTrue(all(e["repair_action"] == "None" for e in disk["events"]))

    def test_restart_replay_does_not_duplicate_events_or_write(self):
        first = make_cycle(0, "WaitAndRetry")
        store.advance_store(self.path, first)
        before = self.path.read_bytes()
        replay = store.advance_store(self.path, first)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["events"], [])
        self.assertEqual(replay["generation"], 1)
        self.assertEqual(before, self.path.read_bytes())

    def test_conflicting_replay_fails_without_writes(self):
        self.step(0)
        before = self.path.read_bytes()
        with self.assertRaises(reducer.InvalidIncidentInput):
            self.step(0, "WaitAndRetry")
        self.assertEqual(before, self.path.read_bytes())

    def test_out_of_order_fails_without_writes(self):
        self.step(80)
        before = self.path.read_bytes()
        with self.assertRaises(reducer.InvalidIncidentInput):
            self.step(40)
        self.assertEqual(before, self.path.read_bytes())

    def test_incomplete_is_unknown_not_healthy(self):
        self.step(0)
        result = self.step(40, incomplete=True)
        self.assertEqual(reducer.display_status(result["state"]), "Unknown")
        self.assertEqual(store.load_store(self.path)["events"][-1]["event_type"],
                         "EvidenceIncomplete")

    def test_private_decision_reason_not_written(self):
        self.step(0, "WaitAndRetry")
        self.assertNotIn(b"PRIVATE-EVIDENCE-NOT-FOR-STORAGE", self.path.read_bytes())

    def test_checksum_detects_tamper_and_refuses_next_write(self):
        self.step(0, "WaitAndRetry")
        tampered = self.path.read_bytes().replace(b"Suspected", b"Recovered")
        self.path.write_bytes(tampered)
        before = self.path.read_bytes()
        with self.assertRaises(store.CorruptIncidentStore):
            self.step(40)
        self.assertEqual(before, self.path.read_bytes())

    def test_missing_field_fails_closed_even_if_rehashed(self):
        self.step(0)
        record = json.loads(self.path.read_text())
        record.pop("events_discarded")
        record["integrity_sha256"] = store._digest({k: v for k, v in record.items() if k != "integrity_sha256"})
        self.path.write_text(json.dumps(record))
        with self.assertRaises(store.CorruptIncidentStore):
            self.step(40)

    def test_corrupt_state_fails_closed_even_if_rehashed(self):
        self.step(0)
        record = json.loads(self.path.read_text())
        record["state"]["phase"] = "Active"
        record["integrity_sha256"] = store._digest({k: v for k, v in record.items() if k != "integrity_sha256"})
        self.path.write_text(json.dumps(record))
        with self.assertRaises(store.CorruptIncidentStore):
            self.step(40)

    def test_corrupt_event_fails_closed_even_if_rehashed(self):
        self.step(0, "WaitAndRetry")
        record = json.loads(self.path.read_text())
        record["events"][0]["repair_action"] = "RepairICS"
        record["integrity_sha256"] = store._digest({k: v for k, v in record.items() if k != "integrity_sha256"})
        self.path.write_text(json.dumps(record))
        with self.assertRaises(store.CorruptIncidentStore):
            self.step(40)

    def test_duplicate_json_key_rejected(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text('{"x":1,"x":2}')
        with self.assertRaises(store.CorruptIncidentStore):
            store.load_store(self.path)

    def test_non_utf8_rejected(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(b"\xff\xfe\xfd")
        with self.assertRaises(store.CorruptIncidentStore):
            store.load_store(self.path)

    def test_oversized_record_rejected_without_overwrite(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(b"X" * store.MAX_READ_BYTES)
        with self.assertRaises(store.CorruptIncidentStore):
            self.step(0)
        self.assertEqual(self.path.stat().st_size, store.MAX_READ_BYTES)

    def test_invalid_path_refused(self):
        with self.assertRaises(store.IncidentStoreError):
            store.load_store(Path(self.tmp.name) / "telemetry.db")
        with self.assertRaises(store.IncidentStoreError):
            store.load_store("incident-state.json")

    def test_replace_failure_preserves_prior_transaction(self):
        self.step(0, "WaitAndRetry")
        prior = self.path.read_bytes()
        with patch.object(store.os, "replace", side_effect=OSError("simulated write failure")):
            with self.assertRaises(OSError):
                self.step(40, "PossibleIcsFailure")
        self.assertEqual(self.path.read_bytes(), prior)
        self.assertEqual(list(self.path.parent.glob(".onyx-incident-*.tmp")), [])

    def test_first_write_failure_leaves_no_partial_file(self):
        with patch.object(store.os, "replace", side_effect=OSError("simulated failure")):
            with self.assertRaises(OSError):
                self.step(0)
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.glob(".onyx-incident-*.tmp")), [])

    def test_commit_then_reported_error_replay_is_idempotent(self):
        self.step(0, "WaitAndRetry")
        original = store.os.replace
        def ambiguous(*args):
            original(*args)
            raise OSError("simulated failure after rename, before caller gets result")
        with patch.object(store.os, "replace", side_effect=ambiguous):
            with self.assertRaises(OSError):
                self.step(40, "PossibleIcsFailure")
        self.assertEqual(store.load_store(self.path)["state"]["phase"], "Active")
        repeated = self.step(40, "PossibleIcsFailure")
        self.assertTrue(repeated["replayed"])
        self.assertEqual(len(store.load_store(self.path)["events"]), 2)

    def test_preexisting_lock_refuses_concurrent_writer(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with store._writer_lock(self.path):
            with self.assertRaises(store.IncidentStoreBusy):
                self.step(0)
        self.assertFalse(self.path.exists())

    def test_event_rotation_retains_last_128_and_counter(self):
        for i in range(270):
            self.step(i * 40, "WaitAndRetry" if i % 2 == 0 else "Healthy")
        result = store.load_store(self.path)
        self.assertEqual(result["generation"], 270)
        self.assertEqual(len(result["events"]), store.MAX_EVENTS)
        self.assertEqual(result["events_discarded"], 270 - store.MAX_EVENTS)
        self.assertEqual(len(set(e["event_id"] for e in result["events"])), store.MAX_EVENTS)
        self.assertLess(self.path.stat().st_size, store.MAX_RECORD_BYTES)

    def test_no_events_with_many_healthy_cycles(self):
        for i in range(60):
            self.step(i * 40)
        result = store.load_store(self.path)
        self.assertEqual(result["events"], [])
        self.assertEqual(result["generation"], 60)

    def test_recovery_persists_across_loads(self):
        self.step(0, "PossibleIcsFailure")
        self.assertEqual(store.load_store(self.path)["state"]["phase"], "Active")
        self.step(40)
        self.assertEqual(store.load_store(self.path)["state"]["phase"], "Active")
        self.step(80)
        self.assertEqual(store.load_store(self.path)["state"]["phase"], "Recovered")

    def test_no_raw_cycle_data_in_store(self):
        self.step(0, "Investigate", secret_extra="should not persist")
        text = self.path.read_text()
        self.assertNotIn("secret_extra", text)
        self.assertNotIn("PRIVATE-EVIDENCE-NOT-FOR-STORAGE", text)


if __name__ == "__main__":
    unittest.main()
