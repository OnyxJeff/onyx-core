"""ONYX CORE v0.7.0 — M3 Step 2, advanced *offline* failure-sequence tests.

No network, real collector, production paths, Windows ICS, tasks or services are used.
Every writable incident state is located inside a fresh TemporaryDirectory.
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

START = datetime(2026, 11, 9, 21, 0, tzinfo=timezone.utc)


def sample(second=0, decision="Healthy", *, incomplete=False, **updates):
    finished = START + timedelta(seconds=second)
    started = finished - timedelta(seconds=4)
    result = {
        "schema_version": 1,
        "source": "LiveRestrictedDiagnostic",
        "cycle_started_utc": started.isoformat(),
        "cycle_finished_utc": finished.isoformat(),
        "duration_ms": 4000,
        "cycle_status": "EvidenceIncomplete" if incomplete else "Complete",
        "connectivity_decision": "Investigate" if incomplete else decision,
        "decision_reason": "M3-PRIVATE-SYNTHETIC-SIGNAL",
        "windows_classification": "WindowsPathReady",
        "pi_classification": "PiProbeUnavailable" if incomplete else "PiInternetVerified",
        "observation_count": 1,
        "consecutive_suspected": 0,
        "history_error_present": bool(incomplete),
        "windows_error_present": False,
        "pi_error_present": False,
        "repair_action": "None",
    }
    if decision == "PossibleIcsFailure" and not incomplete:
        result.update(pi_classification="ExternalTcpUnverified", observation_count=3,
                      consecutive_suspected=3)
    result.update(updates)
    return result


class AdvancedFailureTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="onyx-m3-advanced-")
        self.addCleanup(self.scratch.cleanup)
        self.dir = Path(self.scratch.name) / "Monitoring"
        self.dir.mkdir()
        self.path = self.dir / "incident-state.json"
        self.marker = self.dir / live.MARKER_NAME
        self.root = MODULES.parents[1]

    def first(self, c=None):
        return live.apply_live_cycle(sample(0) if c is None else c, self.dir,
                                     initialize_new=True)

    def next(self, c):
        return live.apply_live_cycle(c, self.dir)

    def state(self):
        return storage.load_store(self.path)

    def events(self):
        return [event["event_type"] for event in self.state()["events"]]

    def assert_untouched(self, previous):
        self.assertEqual(self.path.read_bytes(), previous)

    # Multi-signal and flapping sequences that reach across adapter + reducer + store.
    def test_flapping_active_stays_open_until_two_new_good_samples(self):
        self.first(sample(0, "PossibleIcsFailure"))
        self.next(sample(60))
        self.next(sample(75, "Investigate", pi_classification="DnsUnverified"))
        self.assertEqual(self.next(sample(95))["phase"], "Active")
        self.assertEqual(self.next(sample(125))["phase"], "Recovered")
        self.assertEqual(self.events(), ["IncidentOpened", "IncidentRecovered"])

    def test_mixed_windows_and_pi_problem_remains_suspected(self):
        self.first(sample(0, "Investigate", windows_classification="IcsServiceStopped",
                          pi_classification="DnsUnverified"))
        outcome = self.next(sample(65, "Investigate", windows_classification="AdapterDown",
                                   pi_classification="GatewayUnreachable"))
        self.assertEqual(outcome["phase"], "Suspected")
        self.assertEqual(self.events(), ["IncidentOpened"])

    def test_unknown_during_active_then_new_problem_keeps_same_incident(self):
        self.first(sample(0, "PossibleIcsFailure"))
        incident = self.state()["state"]["incident"]["id"]
        self.assertEqual(self.next(sample(60, incomplete=True))["display_status"], "Unknown")
        self.assertEqual(self.next(sample(120, "WaitAndRetry"))["phase"], "Active")
        self.assertEqual(self.state()["state"]["incident"]["id"], incident)
        self.assertEqual(self.events(), ["IncidentOpened", "EvidenceIncomplete", "EvidenceRestored"])

    def test_incomplete_windows_and_pi_flags_do_not_close_incident(self):
        self.first(sample(0, "PossibleIcsFailure"))
        c = sample(60, incomplete=True, windows_error_present=True, pi_error_present=True,
                   history_error_present=True)
        self.assertEqual(self.next(c)["display_status"], "Unknown")
        self.assertEqual(self.state()["state"]["phase"], "Active")

    def test_unknown_from_healthy_then_restored_is_not_incident_recovered(self):
        self.first(sample(0))
        self.next(sample(60, incomplete=True))
        self.assertEqual(self.next(sample(120))["phase"], "Healthy")
        self.assertEqual(self.events(), ["EvidenceIncomplete", "EvidenceRestored"])
        self.assertIsNone(self.state()["state"]["incident"])

    def test_multiple_unknown_cycles_open_only_one_evidence_event(self):
        self.first(sample(0, incomplete=True))
        for second in (60, 120, 180, 240):
            self.next(sample(second, incomplete=True))
        self.assertEqual(self.events(), ["EvidenceIncomplete"])
        self.assertEqual(self.state()["generation"], 5)

    def test_evidence_flap_emits_restored_only_when_evidence_returns(self):
        self.first(sample(0, incomplete=True))
        self.next(sample(60, incomplete=True))
        self.next(sample(120))
        self.next(sample(180, incomplete=True))
        self.next(sample(240))
        self.assertEqual(self.events(), ["EvidenceIncomplete", "EvidenceRestored",
                                        "EvidenceIncomplete", "EvidenceRestored"])

    def test_recovered_then_unknown_then_new_outage_new_identity(self):
        self.first(sample(0, "WaitAndRetry"))
        original = self.state()["state"]["incident"]["id"]
        self.next(sample(60))
        self.next(sample(120, incomplete=True))
        self.next(sample(180, "WaitAndRetry"))
        current = self.state()["state"]["incident"]["id"]
        self.assertNotEqual(original, current)
        self.assertEqual(self.events().count("IncidentOpened"), 2)

    def test_three_consecutive_correlated_failures_create_single_active(self):
        self.first(sample(0, "Investigate", pi_classification="DnsUnverified"))
        self.next(sample(60, "PossibleIcsFailure"))
        for second in (120, 180, 240):
            self.next(sample(second, "PossibleIcsFailure"))
        self.assertEqual(self.events(), ["IncidentOpened", "IncidentEscalated"])
        self.assertEqual(self.state()["state"]["phase"], "Active")

    def test_recovery_exactly_at_minimum_spacing(self):
        self.first(sample(0, "PossibleIcsFailure"))
        self.next(sample(60))
        self.assertEqual(self.next(sample(90))["phase"], "Recovered")

    def test_recovery_just_short_of_minimum_does_not_close(self):
        self.first(sample(0, "PossibleIcsFailure"))
        self.next(sample(60))
        self.assertEqual(self.next(sample(89))["phase"], "Active")
        self.assertEqual(self.next(sample(90))["phase"], "Recovered")

    def test_recovery_after_long_gap_needs_fresh_confirmation(self):
        self.first(sample(0, "PossibleIcsFailure"))
        self.next(sample(60))
        self.assertEqual(self.next(sample(361))["phase"], "Active")
        self.assertEqual(self.next(sample(391))["phase"], "Recovered")

    def test_replay_at_recovery_boundary_never_counts_as_second_sample(self):
        self.first(sample(0, "PossibleIcsFailure"))
        good = sample(60)
        self.next(good)
        self.assertTrue(self.next(copy.deepcopy(good))["replayed"])
        self.assertEqual(self.state()["state"]["phase"], "Active")
        self.assertEqual(self.next(sample(90))["phase"], "Recovered")
        self.assertEqual(self.state()["generation"], 3)

    def test_sixty_cycle_endurance_remains_bounded_without_repairs(self):
        self.first(sample(0))
        for idx in range(1, 60):
            choice = idx % 5
            data = (sample(idx * 60, incomplete=True) if choice == 0 else
                    sample(idx * 60, "Investigate", pi_classification="DnsUnverified") if choice == 1 else
                    sample(idx * 60))
            self.next(data)
        record = self.state()
        self.assertEqual(record["generation"], 60)
        self.assertEqual(record["state"]["processed_cycles"], 60)
        self.assertLessEqual(len(record["events"]), storage.MAX_EVENTS)
        self.assertTrue(all(event["repair_action"] == "None" for event in record["events"]))
        self.assertNotIn("M3-PRIVATE-SYNTHETIC-SIGNAL", self.path.read_text(encoding="utf8"))

    # Crash boundaries, store replay, locking and marker recovery.
    def test_failure_before_first_marker_creation_keeps_initial_state_absent(self):
        with mock.patch.object(live, "_make_marker", side_effect=OSError("simulated disk full")):
            with self.assertRaises(OSError):
                self.first(sample(0))
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.path.exists())

    def test_failure_after_marker_before_first_store_fails_closed(self):
        with mock.patch.object(adapter, "apply_cycle_to_store", side_effect=OSError("simulated crash")):
            with self.assertRaises(OSError):
                self.first(sample(0))
        self.assertTrue(self.marker.exists())
        self.assertFalse(self.path.exists())
        with self.assertRaises(live.LiveIncidentError):
            self.next(sample(60))
        with self.assertRaises(live.LiveIncidentError):
            live.apply_live_cycle(sample(60), self.dir, initialize_new=True)

    def test_replay_after_post_commit_exception_preserves_exact_bytes(self):
        self.first(sample(0))
        new = sample(60, "WaitAndRetry")
        original_replace = storage._atomic_replace
        def commit_then_raise(path, data):
            original_replace(path, data)
            raise OSError("simulated exception after successful replacement")
        with mock.patch.object(storage, "_atomic_replace", side_effect=commit_then_raise):
            with self.assertRaises(OSError):
                self.next(new)
        committed = self.path.read_bytes()
        self.assertEqual(self.state()["generation"], 2)
        replay = self.next(copy.deepcopy(new))
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["generation"], 2)
        self.assert_untouched(committed)

    def test_failed_precommit_replace_keeps_old_journal_and_retry_works(self):
        self.first(sample(0, "WaitAndRetry"))
        prior = self.path.read_bytes()
        with mock.patch.object(storage.os, "replace", side_effect=OSError("simulated I/O error")):
            with self.assertRaises(OSError):
                self.next(sample(60))
        self.assert_untouched(prior)
        outcome = self.next(sample(60))
        self.assertEqual(outcome["phase"], "Recovered")
        self.assertEqual(self.events(), ["IncidentOpened", "IncidentRecovered"])

    def test_writer_lock_refuses_simultaneous_commit_without_state_damage(self):
        self.first(sample(0))
        prior = self.path.read_bytes()
        with storage._writer_lock(self.path):
            with self.assertRaises(storage.IncidentStoreBusy):
                self.next(sample(60))
        self.assert_untouched(prior)
        self.assertEqual(self.next(sample(60))["generation"], 2)

    def test_live_lock_releases_after_collector_exception(self):
        self.first(sample(0))
        prior = self.path.read_bytes()
        def boom(_root):
            raise RuntimeError("simulated injected collector failure")
        with self.assertRaises(RuntimeError):
            live.execute_one_cycle(self.root, self.dir, False, collect=boom)
        self.assert_untouched(prior)
        out = live.execute_one_cycle(self.root, self.dir, False,
                                     collect=lambda root: sample(60))
        self.assertEqual(out["generation"], 2)

    def test_preexisting_unheld_lock_file_allows_next_cycle(self):
        self.first(sample(0))
        lockfile = self.dir / "incident-cycle.lock"
        lockfile.write_bytes(b"\0")
        out = live.execute_one_cycle(self.root, self.dir, False,
                                     collect=lambda root: sample(60))
        self.assertEqual(out["generation"], 2)
        self.assertEqual(lockfile.read_bytes(), b"\0")

    def test_corrupt_store_preflight_does_not_run_collector(self):
        self.first(sample(0))
        self.path.write_bytes(b"not-json")
        collect = mock.Mock(return_value=sample(60))
        with self.assertRaises(storage.CorruptIncidentStore):
            live.execute_one_cycle(self.root, self.dir, False, collect=collect)
        collect.assert_not_called()
        self.assertEqual(self.path.read_bytes(), b"not-json")

    def test_unexpected_journal_fields_fail_even_with_new_valid_checksum(self):
        self.first(sample(0, "WaitAndRetry"))
        record = self.state()
        record["events"][0]["unapproved_private_note"] = "EXTRA-PRIVATE"
        body = {k: v for k, v in record.items() if k != "integrity_sha256"}
        record["integrity_sha256"] = storage._digest(body)
        self.path.write_bytes(storage._canonical(record) + b"\n")
        previous = self.path.read_bytes()
        collect = mock.Mock(return_value=sample(60))
        with self.assertRaises(storage.CorruptIncidentStore):
            live.execute_one_cycle(self.root, self.dir, False, collect=collect)
        collect.assert_not_called()
        self.assert_untouched(previous)

    def test_runner_duplicate_json_property_is_refused(self):
        self.first(sample(0))
        prior = self.path.read_bytes()
        raw = b'{"schema_version":1,"schema_version":1}'
        with self.assertRaises(live.LiveIncidentError):
            live.read_json_strict(raw)
        self.assert_untouched(prior)

    def test_runner_nonfinite_json_field_is_refused(self):
        self.first(sample(0))
        prior = self.path.read_bytes()
        raw = b'{"value":NaN}'
        with self.assertRaises(live.LiveIncidentError):
            live.read_json_strict(raw)
        self.assert_untouched(prior)

    def test_runner_oversize_json_is_refused(self):
        self.first(sample(0))
        prior = self.path.read_bytes()
        with self.assertRaises(live.LiveIncidentError):
            live.read_json_strict(b" " * (live.MAX_RUNNER_JSON + 1))
        self.assert_untouched(prior)

    def test_runner_invalid_utf8_is_refused(self):
        self.first(sample(0))
        prior = self.path.read_bytes()
        with self.assertRaises(live.LiveIncidentError):
            live.read_json_strict(b"\xff\xfe\xfd")
        self.assert_untouched(prior)

    def test_stale_backdated_cycle_rejected_after_restarts(self):
        self.first(sample(0))
        self.next(sample(120, "WaitAndRetry"))
        prior = self.path.read_bytes()
        with self.assertRaises(reducer.InvalidIncidentInput):
            self.next(sample(60))
        self.assert_untouched(prior)
        self.assertEqual(self.state()["generation"], 2)

    def test_same_timestamp_changed_reason_is_conflict_not_replay(self):
        self.first(sample(0))
        prior = self.path.read_bytes()
        modified = sample(0, decision_reason="different diagnostic content")
        with self.assertRaises(reducer.InvalidIncidentInput):
            self.next(modified)
        self.assert_untouched(prior)

    def test_spoofed_repair_command_rejected_before_marker(self):
        bad = sample(0, repair_action="RestartIcs")
        with self.assertRaises(reducer.InvalidIncidentInput):
            self.first(bad)
        self.assertFalse(self.path.exists())
        self.assertFalse(self.marker.exists())

    def test_private_decision_reason_never_reaches_state_after_many_cycles(self):
        self.first(sample(0, "WaitAndRetry"))
        for idx in range(1, 15):
            self.next(sample(idx * 60, "Investigate", pi_classification="DnsUnverified",
                             decision_reason="PRIVATE-CONNECTION-EVIDENCE-%s" % idx))
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE-CONNECTION-EVIDENCE", raw)
        self.assertEqual(self.state()["generation"], 15)


if __name__ == "__main__":
    unittest.main()
