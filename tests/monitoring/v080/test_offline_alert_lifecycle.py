"""M3 pure synthetic alert planner. No credentials, networking, scheduler or writes."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "windows" / "monitoring" / "v080" / "OnyxOfflineAlertLifecycle.py"
spec = importlib.util.spec_from_file_location("onyx_m3_synthetic_alerts", MODULE)
assert spec and spec.loader
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
BASE = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
ID1 = "inc-" + "a" * 24
ID2 = "inc-" + "b" * 24


def stamp(seconds=0):
    return (BASE + timedelta(seconds=seconds)).isoformat(timespec="microseconds").replace("+00:00", "Z")


def ev(kind="IncidentOpened", t=0, iid=ID1, old="Unknown", new="Suspected", decision="WaitAndRetry"):
    when = stamp(t)
    basis = "|".join((kind, when, iid or "none"))
    return {"schema_version": 1, "event_id": "evt-" + hashlib.sha256(basis.encode()).hexdigest()[:24],
            "event_type": kind, "timestamp_utc": when, "incident_id": iid,
            "from_phase": old, "to_phase": new,
            "connectivity_decision": decision, "repair_action": "None"}


def escalate(t=40):
    return ev("IncidentEscalated", t, old="Suspected", new="Active", decision="PossibleIcsFailure")


def recover(t=100, phase="Active"):
    return ev("IncidentRecovered", t, old=phase, new="Recovered", decision="Healthy")


def missing(t=50, phase="Active", iid=ID1):
    return ev("EvidenceIncomplete", t, iid=iid, old=phase, new=phase, decision="Investigate")


def restored(t=60, phase="Active", iid=ID1):
    return ev("EvidenceRestored", t, iid=iid, old=phase, new=phase, decision="Investigate")


def batch(*events, ref=180):
    return json.dumps({"schema_version": 1, "source": core.SOURCE,
                       "provenance": core.PROVENANCE, "reference_utc": stamp(ref),
                       "events": events}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class M3OfflineAlertTests(unittest.TestCase):
    def setUp(self):
        self.state = core.initial_state()

    def apply(self, *events, ref=180):
        result = core.ingest_synthetic_batch(self.state, batch(*events, ref=ref))
        self.state = result["state"]
        return result

    def opened(self):
        return self.apply(ev())

    def active(self):
        self.opened()
        return self.apply(escalate())

    def assert_inert(self, outcome):
        self.assertTrue(outcome["simulation_only"])
        self.assertFalse(outcome["notification_enabled"])
        self.assertFalse(outcome["delivery_permitted"])
        self.assertFalse(outcome["runtime_enabled"])
        self.assertFalse(outcome["live_probe_authorized"])
        self.assertFalse(outcome["task_creation_authorized"])
        self.assertFalse(outcome["store_modified"])
        self.assertEqual(outcome["repair_action"], "None")

    def test_inert_only_cli(self):
        p = subprocess.run([sys.executable, "-I", "-B", str(MODULE), "--check-inert"],
                           capture_output=True, text=True, timeout=5)
        self.assertEqual(p.returncode, 0)
        self.assert_inert(json.loads(p.stdout))

    def test_cli_refuses_live(self):
        for flag in ("--live", "--notify", "--send", "--enable", "--acknowledge", "--persist", "--repair"):
            with self.subTest(flag=flag):
                p = subprocess.run([sys.executable, "-I", "-B", str(MODULE), flag], capture_output=True, timeout=5)
                self.assertNotEqual(p.returncode, 0)

    def test_initial_state_is_safe(self):
        core.validate_state(self.state)
        self.assertEqual(self.state["phase"], "Unknown")
        self.assertEqual(self.state["intent_keys"], [])

    def test_first_suspect_proposes_one_intent(self):
        result = self.opened()
        self.assertEqual(result["processed_new_events"], 1)
        self.assertEqual([x["kind"] for x in result["proposed_intents"]], ["Investigate"])
        self.assertEqual(self.state["phase"], "Suspected")
        self.assert_inert(result)

    def test_proposal_is_not_message_delivery(self):
        result = self.opened()
        self.assertFalse(result["proposed_intents"][0]["delivery_permitted"])
        self.assertNotIn("channel", json.dumps(result))

    def test_open_direct_active_is_possible_ics_not_proven_root_cause(self):
        result = self.apply(ev(new="Active", decision="PossibleIcsFailure"))
        self.assertEqual(self.state["phase"], "Active")
        self.assertIn("Investigate", [x["kind"] for x in result["proposed_intents"]])

    def test_escalation_proposes_distinct_intent(self):
        result = self.active()
        self.assertEqual([x["kind"] for x in result["proposed_intents"]], ["Escalated"])
        self.assertEqual(self.state["phase"], "Active")

    def test_exact_event_replay_no_new_intent(self):
        result = self.opened()
        replay = self.apply(ev())
        self.assertEqual(replay["suppressed_duplicate_events"], 1)
        self.assertEqual(replay["processed_new_events"], 0)
        self.assertEqual(replay["proposed_intents"], [])
        self.assertEqual(replay["state"], result["state"])

    def test_replay_after_escalation_has_no_effect(self):
        self.active()
        before = copy.deepcopy(self.state)
        result = self.apply(ev())
        self.assertEqual(result["state"], before)

    def test_duplicate_in_single_batch(self):
        result = self.apply(ev(), ev())
        self.assertEqual(result["processed_new_events"], 1)
        self.assertEqual(result["suppressed_duplicate_events"], 1)
        self.assertEqual(len(result["proposed_intents"]), 1)

    def test_event_source_must_be_synthetic(self):
        obj = json.loads(batch(ev()).decode())
        for field, value in (("source", "LiveRestrictedDiagnostic"), ("provenance", "LiveRestrictedDiagnostic")):
            with self.subTest(field=field):
                obj2 = dict(obj); obj2[field] = value
                with self.assertRaises(core.OfflineAlertError):
                    core.ingest_synthetic_batch(self.state, json.dumps(obj2).encode())

    def test_replay_with_changed_contents_is_rejected(self):
        self.opened()
        tampered = ev(); tampered["connectivity_decision"] = "Investigate"
        with self.assertRaises(core.OfflineAlertError):
            self.apply(tampered)

    def test_mismatched_event_hash_refused(self):
        broken = ev(); broken["event_id"] = "evt-" + "1" * 24
        with self.assertRaises(core.OfflineAlertError):
            self.apply(broken)

    def test_out_of_order_new_event_refused(self):
        self.active()
        late = missing(30)
        with self.assertRaises(core.OfflineAlertError):
            self.apply(late)

    def test_same_timestamp_evidence_restored_and_recovered(self):
        self.active()
        self.apply(missing(50))
        result = self.apply(restored(90), recover(90))
        self.assertEqual(result["state"]["phase"], "Recovered")
        self.assertEqual([p["kind"] for p in result["proposed_intents"]], ["RecoveryCandidate"])

    def test_incomplete_evidence_is_unknown_not_recovery(self):
        self.active()
        result = self.apply(missing())
        self.assertEqual(result["display_status"], "Unknown")
        self.assertEqual(result["state"]["phase"], "Active")
        self.assertEqual(result["state"]["evidence_status"], "Incomplete")
        self.assertEqual(result["proposed_intents"][0]["kind"], "EvidenceMissing")

    def test_incomplete_does_not_resolve(self):
        self.active()
        self.apply(missing())
        original = copy.deepcopy(self.state)
        with self.assertRaises(core.OfflineAlertError):
            self.apply(recover())
        self.assertEqual(self.state, original)

    def test_evidence_restoration_does_not_resolve(self):
        self.active()
        self.apply(missing())
        result = self.apply(restored())
        self.assertEqual(result["proposed_intents"], [])
        self.assertEqual(result["state"]["phase"], "Active")
        self.assertEqual(result["state"]["evidence_status"], "Complete")

    def test_recovery_only_after_explicit_reducer_event(self):
        self.active()
        self.assertEqual(self.state["phase"], "Active")
        result = self.apply(recover())
        self.assertEqual(result["state"]["phase"], "Recovered")
        self.assertEqual(result["proposed_intents"][0]["kind"], "RecoveryCandidate")
        self.assertIsNone(result["state"]["incident_id"])

    def test_repeated_recovery_suppressed(self):
        self.active(); self.apply(recover())
        result = self.apply(recover())
        self.assertEqual(result["suppressed_duplicate_events"], 1)
        self.assertEqual(result["proposed_intents"], [])

    def test_incorrect_recovery_incident_refused(self):
        self.active()
        with self.assertRaises(core.OfflineAlertError):
            self.apply(recover().copy() | {"incident_id": ID2, "event_id": ev("IncidentRecovered", 100, ID2, "Active", "Recovered", "Healthy")["event_id"]})

    def test_unauthorized_escalation_without_suspect_refused(self):
        with self.assertRaises(core.OfflineAlertError):
            self.apply(escalate())

    def test_recovery_without_incident_refused(self):
        with self.assertRaises(core.OfflineAlertError):
            self.apply(recover())

    def test_second_opening_with_active_incident_refused(self):
        self.opened()
        with self.assertRaises(core.OfflineAlertError):
            self.apply(ev(t=40, iid=ID2))

    def test_new_incident_after_recovered(self):
        self.active(); self.apply(recover())
        result = self.apply(ev(t=120, iid=ID2, old="Recovered"))
        self.assertEqual(result["state"]["incident_id"], ID2)
        self.assertEqual(result["state"]["phase"], "Suspected")

    def test_ack_works_for_suspected(self):
        self.opened()
        result = core.acknowledge_synthetic(self.state, ID1, "synthetic:operator-1", stamp(10))
        self.assertTrue(result["changed"])
        self.assertEqual(result["state"]["acknowledged_by"], "synthetic:operator-1")
        self.assert_inert(result)

    def test_ack_is_idempotent(self):
        self.opened()
        a = core.acknowledge_synthetic(self.state, ID1, "synthetic:operator-1", stamp(10))
        b = core.acknowledge_synthetic(a["state"], ID1, "synthetic:operator-1", stamp(10))
        self.assertFalse(b["changed"])
        self.assertEqual(b["state"], a["state"])

    def test_ack_conflict_refused(self):
        self.opened()
        self.state = core.acknowledge_synthetic(self.state, ID1, "synthetic:operator-1", stamp(10))["state"]
        with self.assertRaises(core.OfflineAlertError):
            core.acknowledge_synthetic(self.state, ID1, "synthetic:operator-2", stamp(12))

    def test_ack_never_recovers(self):
        self.active()
        self.state = core.acknowledge_synthetic(self.state, ID1, "synthetic:operator-1", stamp(50))["state"]
        self.assertEqual(self.state["phase"], "Active")
        self.assertEqual(self.state["evidence_status"], "Complete")

    def test_ack_persists_after_evidence_loss(self):
        self.active()
        self.state = core.acknowledge_synthetic(self.state, ID1, "synthetic:operator-1", stamp(50))["state"]
        result = self.apply(missing(60))
        self.assertEqual(result["state"]["acknowledged_by"], "synthetic:operator-1")
        self.assertEqual(result["display_status"], "Unknown")

    def test_ack_cleared_on_recovery(self):
        self.active()
        self.state = core.acknowledge_synthetic(self.state, ID1, "synthetic:operator-1", stamp(50))["state"]
        result = self.apply(recover(100))
        self.assertIsNone(result["state"]["acknowledged_by"])

    def test_ack_wrong_id_refused(self):
        self.opened()
        with self.assertRaises(core.OfflineAlertError):
            core.acknowledge_synthetic(self.state, ID2, "synthetic:operator-1", stamp(10))

    def test_ack_too_early_refused(self):
        self.opened()
        with self.assertRaises(core.OfflineAlertError):
            core.acknowledge_synthetic(self.state, ID1, "synthetic:operator-1", stamp(-10))

    def test_ack_bad_actor_refused(self):
        self.opened()
        for actor in ("SYSTEM", "S-1-5-18", "jmay2", "synthetic:", "synthetic:\nfoo", 12, None):
            with self.subTest(actor=actor):
                with self.assertRaises(core.OfflineAlertError):
                    core.acknowledge_synthetic(self.state, ID1, actor, stamp(10))

    def test_ack_after_recovery_refused(self):
        self.active(); self.apply(recover())
        with self.assertRaises(core.OfflineAlertError):
            core.acknowledge_synthetic(self.state, ID1, "synthetic:operator-1", stamp(120))

    def test_batch_out_of_order_refused(self):
        with self.assertRaises(core.OfflineAlertError):
            self.apply(escalate(40), ev(t=0))

    def test_malformed_event_extra_field_refused(self):
        bad = ev(); bad["network_target"] = "real-device"
        with self.assertRaises(core.OfflineAlertError):
            self.apply(bad)

    def test_missing_event_field_refused(self):
        bad = ev(); bad.pop("repair_action")
        with self.assertRaises(core.OfflineAlertError):
            self.apply(bad)

    def test_repair_claim_refused(self):
        bad = ev(); bad["repair_action"] = "FixICS"
        with self.assertRaises(core.OfflineAlertError):
            self.apply(bad)

    def test_invalid_decision_refused(self):
        bad = ev(); bad["connectivity_decision"] = "RebootNow"
        with self.assertRaises(core.OfflineAlertError):
            self.apply(bad)

    def test_invalid_incident_id_refused(self):
        bad = ev(iid="test-incident")
        with self.assertRaises(core.OfflineAlertError):
            self.apply(bad)

    def test_boolean_schema_refused(self):
        bad = json.loads(batch(ev())); bad["schema_version"] = True
        with self.assertRaises(core.OfflineAlertError):
            core.ingest_synthetic_batch(self.state, json.dumps(bad).encode())

    def test_nonfinite_refused(self):
        raw = batch(ev()).replace(b'"schema_version":1', b'"schema_version":NaN')
        with self.assertRaises(core.OfflineAlertError):
            core.ingest_synthetic_batch(self.state, raw)

    def test_duplicate_json_key_refused(self):
        raw = batch(ev()).replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1', 1)
        with self.assertRaises(core.OfflineAlertError):
            core.ingest_synthetic_batch(self.state, raw)

    def test_bad_utf8_refused(self):
        with self.assertRaises(core.OfflineAlertError):
            core.ingest_synthetic_batch(self.state, b'\xff')

    def test_oversized_batch_refused(self):
        with self.assertRaises(core.OfflineAlertError):
            core.ingest_synthetic_batch(self.state, b' ' * (core.MAX_RAW_BYTES + 1))

    def test_empty_batch_refused(self):
        with self.assertRaises(core.OfflineAlertError):
            core.ingest_synthetic_batch(self.state, batch())

    def test_future_refused(self):
        with self.assertRaises(core.OfflineAlertError):
            self.apply(ev(t=200), ref=180)

    def test_stale_refused(self):
        with self.assertRaises(core.OfflineAlertError):
            self.apply(ev(t=0), ref=301)

    def test_timezone_required(self):
        bad = ev(); bad["timestamp_utc"] = "2026-11-10T12:00:00"
        with self.assertRaises(core.OfflineAlertError):
            self.apply(bad)

    def test_32_events_limit(self):
        objects = [ev(t=i, iid=ID1, old="Unknown", new="Suspected") for i in range(33)]
        with self.assertRaises(core.OfflineAlertError):
            self.apply(*objects)

    def test_all_or_nothing_when_late_event_invalid(self):
        before = copy.deepcopy(self.state)
        with self.assertRaises(core.OfflineAlertError):
            self.apply(ev(), escalate(40), missing(50), recover(100))
        self.assertEqual(self.state, before)

    def test_state_argument_immutable(self):
        before = copy.deepcopy(self.state)
        core.ingest_synthetic_batch(self.state, batch(ev()))
        self.assertEqual(self.state, before)

    def test_bad_state_refused(self):
        bad = copy.deepcopy(self.state); bad["notification_enabled"] = True
        with self.assertRaises(core.OfflineAlertError):
            core.ingest_synthetic_batch(bad, batch(ev()))

    def test_history_state_bounded_no_eviction(self):
        state = core.initial_state()
        state["seen_events"] = [{"event_id": "evt-" + f"{i:024x}", "sha256": "f" * 64}
                                for i in range(core.MAX_TRACKED)]
        state["last_timestamp_utc"] = stamp(-1)
        with self.assertRaises(core.OfflineAlertError):
            core.ingest_synthetic_batch(state, batch(ev()))
        self.assertEqual(len(state["seen_events"]), core.MAX_TRACKED)

    def test_evidence_toggle_dedup_intent_across_different_events(self):
        self.active()
        self.apply(missing(50)); self.apply(restored(60))
        second = self.apply(missing(80))
        self.assertEqual(second["proposed_intents"], [])
        self.assertEqual(second["processed_new_events"], 1)

    def test_evidence_restored_without_loss_refused(self):
        self.active()
        with self.assertRaises(core.OfflineAlertError):
            self.apply(restored())

    def test_phase_mismatch_evidence_refused(self):
        self.active()
        with self.assertRaises(core.OfflineAlertError):
            self.apply(missing(50, phase="Suspected"))

    def test_failed_batch_does_not_claim_delivery(self):
        self.active()
        outcome = self.apply(missing())
        self.assert_inert(outcome)

    def test_reducer_event_id_compatibility(self):
        path = ROOT / "windows" / "monitoring" / "OnyxIncidentState.py"
        rspec = importlib.util.spec_from_file_location("onyx_v070_pure_reducer_test", path)
        assert rspec and rspec.loader
        reducer = importlib.util.module_from_spec(rspec)
        rspec.loader.exec_module(reducer)
        if not hasattr(reducer, "_event"):
            self.skipTest("sandbox-only reducer-interface mirror: SQUALL must run actual v0.7 reducer")
        real = reducer._event("IncidentOpened", stamp(0), ID1, "Unknown", "Suspected", "WaitAndRetry")
        self.assertEqual(set(real), core.EVENT_FIELDS)
        result = self.apply(real)
        self.assertEqual(result["proposed_intents"][0]["kind"], "Investigate")


    def test_real_reducer_recovery_spacing_compatibility(self):
        """Host gate: real reducer controls recovery; M3 only plans from emitted events."""
        path = ROOT / "windows" / "monitoring" / "OnyxIncidentState.py"
        rspec = importlib.util.spec_from_file_location("onyx_v070_recovery_gate", path)
        assert rspec and rspec.loader
        reducer = importlib.util.module_from_spec(rspec)
        rspec.loader.exec_module(reducer)
        if not hasattr(reducer, "_event"):
            self.skipTest("sandbox reducer mirror: must pass with real reducer on SQUALL")

        def cycle(t, decision, suspects):
            healthy = decision == "Healthy"
            return {"schema_version": 1, "source": "LiveRestrictedDiagnostic",
                    "cycle_started_utc": stamp(t - 1), "cycle_finished_utc": stamp(t),
                    "duration_ms": 1000, "cycle_status": "Complete",
                    "connectivity_decision": decision, "decision_reason": "synthetic-test-only",
                    "windows_classification": "WindowsPathReady",
                    "pi_classification": "PiInternetVerified" if healthy else "ExternalTcpUnverified",
                    "observation_count": min(12, (t // 40) + 1),
                    "consecutive_suspected": suspects, "history_error_present": False,
                    "windows_error_present": False, "pi_error_present": False,
                    "repair_action": "None"}

        states = reducer.initial_state()
        all_events = []
        for t, decision, suspects in ((0, "WaitAndRetry", 1),
                                       (40, "WaitAndRetry", 2),
                                       (80, "PossibleIcsFailure", 3),
                                       (120, "Healthy", 0)):
            states, events = reducer.apply_cycle(states, cycle(t, decision, suspects))
            all_events.extend(events)
        self.assertEqual(states["phase"], "Active")
        self.assertNotIn("IncidentRecovered", [e["event_type"] for e in all_events])
        states, recovered_events = reducer.apply_cycle(states, cycle(160, "Healthy", 0))
        self.assertEqual(states["phase"], "Recovered")
        self.assertEqual([e["event_type"] for e in recovered_events], ["IncidentRecovered"])
        all_events.extend(recovered_events)
        outcome = self.apply(*all_events)
        self.assertEqual(outcome["state"]["phase"], "Recovered")
        self.assertEqual([p["kind"] for p in outcome["proposed_intents"]],
                         ["Investigate", "Escalated", "RecoveryCandidate"])
        self.assert_inert(outcome)


if __name__ == "__main__":
    unittest.main()
