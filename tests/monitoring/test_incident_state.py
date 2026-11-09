"""Offline incident reducer tests: no filesystem state, sockets or subprocesses."""
import copy
import importlib.util
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2] / "windows" / "monitoring" / "OnyxIncidentState.py"
spec = importlib.util.spec_from_file_location("onyx_incident_state", MODULE)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
START = datetime(2026, 11, 9, 4, 0, 0, tzinfo=timezone.utc)


def cycle(seconds=0, decision="Healthy", *, incomplete=False, **extra):
    finished = START + timedelta(seconds=seconds)
    started = finished - timedelta(seconds=4)
    data = {
        "schema_version": 1,
        "source": "LiveRestrictedDiagnostic",
        "cycle_started_utc": started.isoformat(),
        "cycle_finished_utc": finished.isoformat(),
        "duration_ms": 4000,
        "cycle_status": "EvidenceIncomplete" if incomplete else "Complete",
        "connectivity_decision": decision,
        "decision_reason": "Offline synthetic test",
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
        data.update(pi_classification="ExternalTcpUnverified", observation_count=3, consecutive_suspected=3)
    if incomplete:
        data.update(connectivity_decision="Investigate", pi_classification="PiProbeUnavailable")
    data.update(extra)
    return data


def apply_many(*args):
    state = engine.initial_state()
    events = []
    for data in args:
        state, new_events = engine.apply_cycle(state, data)
        events.extend(new_events)
    return state, events


class ReducerTests(unittest.TestCase):
    def test_new_state_is_unknown(self):
        state = engine.initial_state()
        self.assertEqual(engine.display_status(state), "Unknown")
        self.assertEqual(state["processed_cycles"], 0)

    def test_first_healthy_is_healthy_without_incident(self):
        state, events = apply_many(cycle())
        self.assertEqual(state["phase"], "Healthy")
        self.assertEqual(state["evidence_status"], "Complete")
        self.assertEqual(events, [])

    def test_healthy_does_not_repeat_transition_events(self):
        state, events = apply_many(cycle(), cycle(40), cycle(80))
        self.assertEqual(events, [])
        self.assertEqual(state["processed_cycles"], 3)

    def test_suspected_single_signal_opens_once(self):
        state, events = apply_many(cycle(), cycle(40, "WaitAndRetry"), cycle(80, "WaitAndRetry"))
        self.assertEqual(state["phase"], "Suspected")
        self.assertEqual([e["event_type"] for e in events], ["IncidentOpened"])

    def test_complete_investigate_opens_suspected(self):
        state, events = apply_many(cycle(0, "Investigate"))
        self.assertEqual(state["phase"], "Suspected")
        self.assertEqual(events[0]["event_type"], "IncidentOpened")

    def test_escalation_after_corroborated_probe(self):
        state, events = apply_many(cycle(0, "WaitAndRetry"), cycle(40, "PossibleIcsFailure"))
        self.assertEqual(state["phase"], "Active")
        self.assertEqual([e["event_type"] for e in events], ["IncidentOpened", "IncidentEscalated"])
        self.assertEqual(events[0]["incident_id"], events[1]["incident_id"])

    def test_first_seen_possible_ics_creates_active(self):
        state, events = apply_many(cycle(0, "PossibleIcsFailure"))
        self.assertEqual(state["phase"], "Active")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["to_phase"], "Active")

    def test_active_does_not_duplicate_events(self):
        state, events = apply_many(cycle(0, "PossibleIcsFailure"), cycle(40, "PossibleIcsFailure"), cycle(80, "WaitAndRetry"))
        self.assertEqual(state["phase"], "Active")
        self.assertEqual(len(events), 1)

    def test_suspected_single_healthy_recovers(self):
        state, events = apply_many(cycle(0, "WaitAndRetry"), cycle(40))
        self.assertEqual(state["phase"], "Recovered")
        self.assertIsNone(state["incident"])
        self.assertEqual(events[-1]["event_type"], "IncidentRecovered")

    def test_recovered_becomes_healthy_on_next_good_cycle(self):
        state, events = apply_many(cycle(0, "WaitAndRetry"), cycle(40), cycle(80))
        self.assertEqual(state["phase"], "Healthy")
        self.assertEqual([e["event_type"] for e in events], ["IncidentOpened", "IncidentRecovered"])

    def test_active_requires_two_good_cycles(self):
        state, events = apply_many(cycle(0, "PossibleIcsFailure"), cycle(40))
        self.assertEqual(state["phase"], "Active")
        self.assertEqual(engine.display_status(state), "Active")
        self.assertEqual(len(events), 1)
        state, more = engine.apply_cycle(state, cycle(80))
        self.assertEqual(state["phase"], "Recovered")
        self.assertEqual(more[0]["event_type"], "IncidentRecovered")

    def test_active_recovery_rejects_too_fast_second_good_cycle(self):
        state, _ = apply_many(cycle(0, "PossibleIcsFailure"), cycle(40), cycle(50))
        self.assertEqual(state["phase"], "Active")
        state, _ = engine.apply_cycle(state, cycle(70))
        self.assertEqual(state["phase"], "Recovered")

    def test_active_recovery_resets_after_long_gap(self):
        state, _ = apply_many(cycle(0, "PossibleIcsFailure"), cycle(40), cycle(400))
        self.assertEqual(state["phase"], "Active")
        state, _ = engine.apply_cycle(state, cycle(440))
        self.assertEqual(state["phase"], "Recovered")

    def test_new_failure_resets_recovery_candidate(self):
        state, _ = apply_many(cycle(0, "PossibleIcsFailure"), cycle(40), cycle(80, "Investigate"), cycle(120))
        self.assertEqual(state["phase"], "Active")
        self.assertIsNotNone(state["incident"]["recovery_candidate_utc"])
        state, _ = engine.apply_cycle(state, cycle(160))
        self.assertEqual(state["phase"], "Recovered")

    def test_initial_incomplete_is_unknown_not_healthy(self):
        state, events = apply_many(cycle(0, incomplete=True))
        self.assertEqual(state["phase"], "Unknown")
        self.assertEqual(engine.display_status(state), "Unknown")
        self.assertEqual([e["event_type"] for e in events], ["EvidenceIncomplete"])

    def test_incomplete_from_healthy_is_unknown_display(self):
        state, events = apply_many(cycle(0), cycle(40, incomplete=True))
        self.assertEqual(state["phase"], "Healthy")
        self.assertEqual(engine.display_status(state), "Unknown")
        self.assertEqual(events[-1]["event_type"], "EvidenceIncomplete")

    def test_repeated_incomplete_is_deduplicated(self):
        state, events = apply_many(cycle(0, incomplete=True), cycle(40, incomplete=True), cycle(80, incomplete=True))
        self.assertEqual([e["event_type"] for e in events], ["EvidenceIncomplete"])
        self.assertEqual(state["processed_cycles"], 3)

    def test_incomplete_never_closes_active_incident(self):
        state, events = apply_many(cycle(0, "PossibleIcsFailure"), cycle(40), cycle(80, incomplete=True), cycle(120))
        self.assertEqual(state["phase"], "Active")
        self.assertEqual(engine.display_status(state), "Active")
        self.assertEqual([e["event_type"] for e in events], ["IncidentOpened", "EvidenceIncomplete", "EvidenceRestored"])
        state, _ = engine.apply_cycle(state, cycle(160))
        self.assertEqual(state["phase"], "Recovered")

    def test_incomplete_preserves_incident_phase_but_displays_unknown(self):
        state, events = apply_many(cycle(0, "PossibleIcsFailure"), cycle(40, incomplete=True))
        self.assertEqual(state["phase"], "Active")
        self.assertEqual(engine.display_status(state), "Unknown")
        self.assertEqual(events[-1]["event_type"], "EvidenceIncomplete")

    def test_restore_evidence_without_making_false_green(self):
        state, events = apply_many(cycle(0, incomplete=True), cycle(40, "WaitAndRetry"))
        self.assertEqual(state["phase"], "Suspected")
        self.assertEqual([e["event_type"] for e in events], ["EvidenceIncomplete", "EvidenceRestored", "IncidentOpened"])

    def test_replay_idempotent(self):
        first = cycle(0, "WaitAndRetry")
        state, _ = apply_many(first)
        replay, events = engine.apply_cycle(state, first)
        self.assertEqual(replay, state)
        self.assertEqual(events, [])

    def test_replay_with_same_timestamp_different_content_is_rejected(self):
        state, _ = apply_many(cycle())
        before = copy.deepcopy(state)
        with self.assertRaises(engine.InvalidIncidentInput):
            engine.apply_cycle(state, cycle(0, "WaitAndRetry"))
        self.assertEqual(state, before)

    def test_out_of_order_rejected(self):
        state, _ = apply_many(cycle(100))
        before = copy.deepcopy(state)
        with self.assertRaises(engine.InvalidIncidentInput):
            engine.apply_cycle(state, cycle(90))
        self.assertEqual(state, before)

    def test_initial_state_input_immutable(self):
        state = engine.initial_state()
        prior = copy.deepcopy(state)
        engine.apply_cycle(state, cycle())
        self.assertEqual(state, prior)

    def test_event_ids_are_unique_and_no_repairs(self):
        _, events = apply_many(cycle(0, "WaitAndRetry"), cycle(40, "PossibleIcsFailure"), cycle(80), cycle(120))
        self.assertEqual(len({e["event_id"] for e in events}), len(events))
        self.assertTrue(all(e["repair_action"] == "None" for e in events))

    def test_roundtrip_state_json(self):
        state, _ = apply_many(cycle(0, "WaitAndRetry"), cycle(40, "PossibleIcsFailure"))
        loaded = json.loads(json.dumps(state))
        next_state, _ = engine.apply_cycle(loaded, cycle(80, incomplete=True))
        self.assertEqual(engine.display_status(next_state), "Unknown")

    def test_recovered_incident_fresh_failure_creates_new_id(self):
        state, events = apply_many(cycle(0, "WaitAndRetry"), cycle(40), cycle(80, "WaitAndRetry"))
        self.assertEqual(state["phase"], "Suspected")
        self.assertNotEqual(events[0]["incident_id"], events[-1]["incident_id"])

    def test_bad_cycle_contract_rejected(self):
        bads = [
            {"repair_action": "RepairICS"},
            {"source": "Untrusted"},
            {"cycle_status": "EvidenceIncomplete"},
            {"history_error_present": True},
            {"connectivity_decision": "PossiblyFine"},
            {"connectivity_decision": "PossibleIcsFailure"},
            {"connectivity_decision": "Healthy", "pi_classification": "DnsUnverified"},
            {"schema_version": True},
            {"observation_count": True},
            {"consecutive_suspected": 6},
            {"duration_ms": 5000},
            {"cycle_finished_utc": "2026-11-09T04:00:00"},
            {"cycle_finished_utc": "bad"},
            {"cycle_finished_utc": "2026-11-09T03:59:55+00:00"},
            {"pi_error_present": "False"},
        ]
        for changes in bads:
            with self.subTest(changes=changes):
                candidate = cycle()
                candidate.update(changes)
                with self.assertRaises(engine.InvalidIncidentInput):
                    engine.apply_cycle(engine.initial_state(), candidate)

    def test_corrupted_state_fail_closed(self):
        for change in (
            {"schema_version": 22},
            {"phase": "Active"},
            {"processed_cycles": -1},
            {"evidence_status": "Healthy"},
            {"last_cycle_digest": "invalid"},
            {"incident": {"id": "a"}},
            {"credential": "must-not-persist"},
        ):
            with self.subTest(change=change):
                state = engine.initial_state()
                state.update(change)
                with self.assertRaises(engine.InvalidIncidentInput):
                    engine.apply_cycle(state, cycle())

    def test_state_and_events_never_record_decision_reason(self):
        suspect = cycle(0, "Investigate", decision_reason="PRIVATE-MESSAGE")
        state, events = apply_many(suspect)
        self.assertNotIn("PRIVATE-MESSAGE", json.dumps(state))
        self.assertNotIn("PRIVATE-MESSAGE", json.dumps(events))


if __name__ == "__main__":
    unittest.main()
