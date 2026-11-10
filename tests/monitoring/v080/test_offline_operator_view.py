"""M4 read-only synthetic snapshot and static HTML/text rendering tests."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
VIEW_FILE = ROOT / "windows" / "monitoring" / "v080" / "OnyxOfflineOperatorView.py"
M3_FILE = ROOT / "windows" / "monitoring" / "v080" / "OnyxOfflineAlertLifecycle.py"
# The locally installed M3 code is loaded through its fixed file path.
sp = importlib.util.spec_from_file_location("OnyxOfflineOperatorView", VIEW_FILE)
assert sp and sp.loader
view = importlib.util.module_from_spec(sp)
sp.loader.exec_module(view)
core = view.alerts
BASE = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
ID1 = "inc-" + "a" * 24
ID2 = "inc-" + "b" * 24


def t(seconds: int = 0) -> str:
    return (BASE + timedelta(seconds=seconds)).isoformat(timespec="microseconds").replace("+00:00", "Z")


def event(kind="IncidentOpened", sec=0, iid=ID1, old="Unknown", new="Suspected", decision="WaitAndRetry"):
    ts = t(sec)
    basis = "|".join((kind, ts, iid or "none"))
    return {"schema_version": 1, "event_id": "evt-" + hashlib.sha256(basis.encode()).hexdigest()[:24],
            "event_type": kind, "timestamp_utc": ts, "incident_id": iid,
            "from_phase": old, "to_phase": new, "connectivity_decision": decision, "repair_action": "None"}


def batch(*items, ref=180):
    return json.dumps({"schema_version": 1, "source": core.SOURCE, "provenance": core.PROVENANCE,
                       "reference_utc": t(ref), "events": items}, separators=(",", ":")).encode()


class DOMInspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.content = []
        self.attrs = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.extend(attrs)

    def handle_data(self, data):
        self.content.append(data)


class M4OfflineOperatorViewTests(unittest.TestCase):
    def setUp(self):
        self.state = core.initial_state()
        self.result = core.ingest_synthetic_batch(self.state, batch(event()))
        self.state = self.result["state"]

    def step(self, *events):
        self.result = core.ingest_synthetic_batch(self.state, batch(*events))
        self.state = self.result["state"]
        return self.result

    def escalation(self):
        return self.step(event("IncidentEscalated", 40, old="Suspected", new="Active", decision="PossibleIcsFailure"))

    def missing(self, sec=50):
        return self.step(event("EvidenceIncomplete", sec, old=self.state["phase"],
                               new=self.state["phase"], decision="Investigate"))

    def restored(self, sec=70):
        return self.step(event("EvidenceRestored", sec, old=self.state["phase"],
                               new=self.state["phase"], decision="Investigate"))

    def recovered(self, sec=120):
        return self.step(event("IncidentRecovered", sec, old=self.state["phase"],
                               new="Recovered", decision="Healthy"))

    def ack(self, actor="synthetic:operator-a", seconds=200):
        return core.acknowledge_synthetic(self.state, ID1, actor, t(seconds))

    def assert_rejected(self, mutator, *, ack=False):
        source = self.ack() if ack else self.result
        changed = copy.deepcopy(source)
        original = copy.deepcopy(source)
        mutator(changed)
        with self.assertRaises(view.OfflineViewError):
            if ack:
                view.build_synthetic_operator_snapshot(self.result, changed)
            else:
                view.build_synthetic_operator_snapshot(changed)
        self.assertEqual(source, original)

    def test_check_inert_cli(self):
        run = subprocess.run([sys.executable, "-I", "-B", str(VIEW_FILE), "--check-inert"],
                             capture_output=True, text=True, timeout=5)
        self.assertEqual(run.returncode, 0)
        cap = json.loads(run.stdout)
        self.assertTrue(cap["simulation_only"])
        self.assertTrue(cap["read_only"])
        for key in ("notification_enabled", "delivery_permitted", "runtime_enabled",
                    "live_probe_authorized", "task_creation_authorized", "store_modified"):
            self.assertIs(cap[key], False)
        self.assertEqual(cap["repair_action"], "None")

    def test_cli_refuses_execution_flags(self):
        for flag in ("--live", "--monitor", "--notify", "--serve", "--port", "--write",
                     "--persist", "--acknowledge", "--repair", "--html", "--demo"):
            with self.subTest(flag=flag):
                p = subprocess.run([sys.executable, "-I", "-B", str(VIEW_FILE), flag],
                                   capture_output=True, timeout=5)
                self.assertNotEqual(p.returncode, 0)

    def test_cli_does_not_render_without_inert_switch(self):
        p = subprocess.run([sys.executable, "-I", "-B", str(VIEW_FILE)], capture_output=True, timeout=5)
        self.assertNotEqual(p.returncode, 0)

    def test_summary_suspected(self):
        s = view.build_synthetic_operator_snapshot(self.result)
        self.assertEqual(s["display_status"], "Suspected")
        self.assertEqual(s["incident_phase"], "Suspected")
        self.assertEqual(s["evidence_status"], "Complete")
        self.assertEqual(s["incident_id"], ID1)
        self.assertIn("Open synthetic incident", s["lifecycle"])

    def test_summary_active(self):
        s = view.build_synthetic_operator_snapshot(self.escalation())
        self.assertEqual(s["display_status"], "Active")
        self.assertIn("No synthetic recovery", s["recovery"])

    def test_evidence_loss_masks_health(self):
        self.escalation()
        s = view.build_synthetic_operator_snapshot(self.missing())
        self.assertEqual(s["incident_phase"], "Active")
        self.assertEqual(s["display_status"], "Unknown")
        self.assertEqual(s["evidence_status"], "Incomplete")
        self.assertIn("Not confirmable", s["recovery"])
        self.assertIn("Unknown", view.render_synthetic_operator_text(self.result))

    def test_evidence_restoration_not_recovery(self):
        self.escalation()
        self.missing()
        s = view.build_synthetic_operator_snapshot(self.restored())
        self.assertEqual(s["display_status"], "Active")
        self.assertNotIn("candidate only", s["recovery"])
        self.assertEqual(s["new_proposed_intents"], [])

    def test_recovery_is_candidate_only(self):
        self.escalation()
        s = view.build_synthetic_operator_snapshot(self.recovered())
        self.assertEqual(s["incident_phase"], "Recovered")
        self.assertIn("candidate only", s["recovery"])
        self.assertIsNone(s["incident_id"])
        self.assertEqual([p["kind"] for p in s["new_proposed_intents"]], ["RecoveryCandidate"])

    def test_recovery_not_independently_proven(self):
        self.escalation()
        self.recovered()
        summary = view.render_synthetic_operator_text(self.result)
        self.assertIn("no recovery, ICS fault or real-world health proven".lower(), summary.lower())

    def test_ack_displays_actor_and_time(self):
        acknowledgement = self.ack()
        s = view.build_synthetic_operator_snapshot(self.result, acknowledgement)
        self.assertEqual(s["acknowledged_by"], "synthetic:operator-a")
        self.assertEqual(s["acknowledged_at_utc"], t(200))
        self.assertIn("synthetic:operator-a", view.render_synthetic_operator_html(self.result, acknowledgement))

    def test_ack_does_not_change_phase(self):
        s = view.build_synthetic_operator_snapshot(self.result, self.ack())
        self.assertEqual(s["incident_phase"], "Suspected")
        self.assertIn("does not resolve", s["lifecycle"])

    def test_ack_after_incomplete_still_unknown(self):
        self.missing()
        s = view.build_synthetic_operator_snapshot(self.result, self.ack())
        self.assertEqual(s["display_status"], "Unknown")
        self.assertEqual(s["acknowledged_by"], "synthetic:operator-a")

    def test_ack_idempotent_display(self):
        first = self.ack()
        again = core.acknowledge_synthetic(first["state"], ID1, "synthetic:operator-a", t(200))
        self.assertFalse(again["changed"])
        prior = copy.deepcopy(self.result)
        prior["state"] = first["state"]
        s = view.build_synthetic_operator_snapshot(prior, again)
        self.assertEqual(s["acknowledged_by"], "synthetic:operator-a")

    def test_exact_replay_counts(self):
        self.step(event())
        s = view.build_synthetic_operator_snapshot(self.result)
        self.assertEqual(s["new_events"], 0)
        self.assertEqual(s["suppressed_replays"], 1)
        self.assertEqual(s["new_proposed_intents"], [])
        self.assertEqual(s["tracked_intent_keys"], 1)

    def test_intent_dedup_distinct_from_event_replay(self):
        self.escalation()
        self.missing()
        self.restored()
        s = view.build_synthetic_operator_snapshot(self.missing(sec=80))
        self.assertEqual(s["new_events"], 1)
        self.assertEqual(s["suppressed_replays"], 0)
        self.assertEqual(s["new_proposed_intents"], [])
        self.assertEqual(s["total_proposed_intents"], 3)

    def test_new_proposal_details(self):
        s = view.build_synthetic_operator_snapshot(self.result)
        self.assertEqual([p["kind"] for p in s["new_proposed_intents"]], ["Investigate"])
        self.assertEqual(s["new_proposed_intents"][0]["event_id"], event()["event_id"])

    def test_proposed_intents_never_delivered(self):
        s = view.build_synthetic_operator_snapshot(self.result)
        self.assertFalse(s["notification_enabled"])
        self.assertFalse(s["delivery_permitted"])
        self.assertTrue(s["read_only"])
        self.assertTrue(s["simulation_only"])

    def test_text_contains_all_sections(self):
        result = view.render_synthetic_operator_text(self.result)
        for word in ("OFFLINE", "Display:", "Incident:", "Evidence:", "Lifecycle:",
                     "Acknowledgement:", "Recovery:", "replays suppressed", "PROPOSAL ONLY"):
            self.assertIn(word, result)

    def test_text_reproducible(self):
        self.assertEqual(view.render_synthetic_operator_text(self.result),
                         view.render_synthetic_operator_text(copy.deepcopy(self.result)))

    def test_html_has_all_required_panels(self):
        output = view.render_synthetic_operator_html(self.result)
        for label in ("Evidence completeness", "Incident phase", "Alert lifecycle",
                      "Acknowledgement", "Recovery", "Deduplication", "New events", "Alert proposals"):
            self.assertIn(label, output)

    def test_html_is_static_no_action_elements(self):
        parser = DOMInspector()
        parser.feed(view.render_synthetic_operator_html(self.result))
        for tag in ("script", "iframe", "form", "button", "input", "a", "img", "object", "link"):
            self.assertNotIn(tag, parser.tags)
        self.assertIn("meta", parser.tags)
        self.assertIn("style", parser.tags)
        self.assertNotIn("src", [k for k, v in parser.attrs])

    def test_html_csp_disables_connections(self):
        output = view.render_synthetic_operator_html(self.result)
        self.assertIn("default-src 'none'", output)
        self.assertIn("connect-src 'none'", output)
        self.assertIn("form-action 'none'", output)

    def test_html_escapes_user_controlled_fake_actor(self):
        fake_actor = "synthetic:<img/src=x>"
        # M3 actor allows only printable ASCII, including HTML-sensitive characters.
        acknowledgement = self.ack(actor=fake_actor)
        html = view.render_synthetic_operator_html(self.result, acknowledgement)
        self.assertIn("synthetic:&lt;img/src=x&gt;", html)
        self.assertNotIn("synthetic:<img/src=x>", html)
        p = DOMInspector()
        p.feed(html)
        self.assertNotIn("img", p.tags)

    def test_html_escapes_quote_and_ampersand_in_actor(self):
        acknowledgement = self.ack(actor='synthetic:&"danger')
        html = view.render_synthetic_operator_html(self.result, acknowledgement)
        self.assertIn("synthetic:&amp;&quot;danger", html)

    def test_html_responsive_and_accessible(self):
        html = view.render_synthetic_operator_html(self.result)
        self.assertIn('lang="en"', html)
        self.assertIn('name="viewport"', html)
        self.assertIn("@media(max-width:650px)", html)
        self.assertIn("<table>", html)

    def test_html_deterministic(self):
        x = view.render_synthetic_operator_html(self.result)
        self.assertEqual(x, view.render_synthetic_operator_html(copy.deepcopy(self.result)))

    def test_html_no_live_health_claim(self):
        html = view.render_synthetic_operator_html(self.result)
        self.assertIn("NOT LIVE MONITORING", html)
        self.assertIn("no live health, root cause, or recovery proven", html)

    def test_input_does_not_mutate(self):
        original = copy.deepcopy(self.result)
        view.render_synthetic_operator_html(self.result)
        view.render_synthetic_operator_text(self.result)
        view.build_synthetic_operator_snapshot(self.result)
        self.assertEqual(self.result, original)

    def test_actor_not_authenticated(self):
        html = view.render_synthetic_operator_html(self.result, self.ack())
        self.assertIn("not a control or authenticated user", html)

    def test_refuses_forged_live_capability(self):
        for name, value in (("runtime_enabled", True), ("live_probe_authorized", True),
                            ("notification_enabled", True), ("delivery_permitted", True),
                            ("task_creation_authorized", True), ("store_modified", True),
                            ("repair_action", "RepairICS"), ("simulation_only", False)):
            with self.subTest(name=name):
                self.assert_rejected(lambda r: r.__setitem__(name, value))

    def test_refuses_non_synthetic_provenance(self):
        for name, value in (("source", "LiveRestrictedDiagnostic"), ("provenance", "ObservedLive")):
            with self.subTest(name=name):
                self.assert_rejected(lambda r: r.__setitem__(name, value))

    def test_refuses_unexpected_outcome_field(self):
        self.assert_rejected(lambda r: r.__setitem__("send_to_webhook", "https://example.com"))

    def test_refuses_missing_outcome_field(self):
        self.assert_rejected(lambda r: r.pop("display_status"))

    def test_refuses_display_mismatch(self):
        self.assert_rejected(lambda r: r.__setitem__("display_status", "Healthy"))

    def test_refuses_evidence_mask_bypass(self):
        self.missing()
        self.assert_rejected(lambda r: r.__setitem__("display_status", "Active"))

    def test_refuses_bad_state(self):
        self.assert_rejected(lambda r: r["state"].__setitem__("phase", "Healthy"))

    def test_refuses_forged_counter_bool(self):
        self.assert_rejected(lambda r: r.__setitem__("processed_new_events", True))

    def test_refuses_negative_counter(self):
        self.assert_rejected(lambda r: r.__setitem__("suppressed_duplicate_events", -1))

    def test_refuses_zero_total_events(self):
        self.assert_rejected(lambda r: r.__setitem__("processed_new_events", 0))

    def test_refuses_over_32_events(self):
        self.assert_rejected(lambda r: r.__setitem__("processed_new_events", 33))

    def test_refuses_too_many_proposals(self):
        self.assert_rejected(lambda r: r.__setitem__("proposed_intents", r["proposed_intents"] * 2))

    def test_refuses_duplicate_proposal_intent_key(self):
        self.assert_rejected(lambda r: (r.__setitem__("processed_new_events", 2), r["proposed_intents"].extend(r["proposed_intents"])))

    def test_refuses_proposal_with_live_delivery(self):
        self.assert_rejected(lambda r: r["proposed_intents"][0].__setitem__("delivery_permitted", True))

    def test_refuses_proposal_fake_event_id(self):
        self.assert_rejected(lambda r: r["proposed_intents"][0].__setitem__("event_id", "evt-" + "b" * 24))

    def test_refuses_proposal_wrong_intent(self):
        self.assert_rejected(lambda r: r["proposed_intents"][0].__setitem__("kind", "RecoveryCandidate"))

    def test_refuses_proposal_extra_action_field(self):
        self.assert_rejected(lambda r: r["proposed_intents"][0].__setitem__("notify", True))

    def test_refuses_proposal_future_of_state(self):
        self.assert_rejected(lambda r: r["proposed_intents"][0].__setitem__("timestamp_utc", t(200)))

    def test_refuses_proposal_nonfinite(self):
        self.assert_rejected(lambda r: r.__setitem__("bogus_nan", float("nan")))

    def test_refuses_proposal_invalid_type(self):
        self.assert_rejected(lambda r: r.__setitem__("proposed_intents", {}))

    def test_refuses_ack_non_synthetic_source(self):
        self.assert_rejected(lambda a: a.__setitem__("source", "LiveWindows"), ack=True)

    def test_refuses_ack_delivery_claim(self):
        self.assert_rejected(lambda a: a.__setitem__("delivery_permitted", True), ack=True)

    def test_refuses_ack_notification_enabled(self):
        self.assert_rejected(lambda a: a.__setitem__("notification_enabled", True), ack=True)

    def test_refuses_ack_phase_change(self):
        self.assert_rejected(lambda a: a["state"].__setitem__("phase", "Active"), ack=True)

    def test_refuses_ack_evidence_change(self):
        self.assert_rejected(lambda a: a["state"].__setitem__("evidence_status", "Incomplete"), ack=True)

    def test_refuses_ack_intent_ledger_change(self):
        self.assert_rejected(lambda a: a["state"].__setitem__("intent_keys", []), ack=True)

    def test_refuses_ack_changed_false_on_new_ack(self):
        self.assert_rejected(lambda a: a.__setitem__("changed", False), ack=True)

    def test_refuses_ack_changed_non_boolean(self):
        self.assert_rejected(lambda a: a.__setitem__("changed", 1), ack=True)

    def test_refuses_ack_backdated(self):
        self.assert_rejected(lambda a: a["state"].__setitem__("acknowledged_at_utc", t(-1)), ack=True)

    def test_refuses_ack_when_recovered(self):
        self.escalation()
        self.recovered()
        ack = core.acknowledge_synthetic(core.ingest_synthetic_batch(core.initial_state(), batch(event()))["state"], ID1, "synthetic:operator-a", t(200))
        with self.assertRaises(view.OfflineViewError):
            view.build_synthetic_operator_snapshot(self.result, ack)

    def test_refuses_ack_unknown_field(self):
        self.assert_rejected(lambda a: a.__setitem__("write_to_store", True), ack=True)

    def test_refuses_ack_conflicting_actor_state(self):
        self.assert_rejected(lambda a: a["state"].__setitem__("acknowledged_by", "real_user"), ack=True)

    def test_refuses_non_json_input(self):
        broken = copy.deepcopy(self.result)
        broken["state"]["seen_events"] = {1, 2}
        with self.assertRaises(view.OfflineViewError):
            view.render_synthetic_operator_html(broken)

    def test_existing_m3_engine_unchanged(self):
        self.assertEqual(core.SOURCE, "OnyxV080M3SyntheticAlerts")
        self.assertTrue(M3_FILE.is_file())

    def test_no_file_network_or_scheduler_execution_in_module(self):
        contents = VIEW_FILE.read_text(encoding="utf-8")
        for forbidden in ("import socket", "import requests", "import urllib", "import smtplib",
                          "import subprocess", "import winreg", "import ctypes", "import os",
                          "open(", ".write_text(", ".write_bytes(", "ScheduledTasks", "Repair-ICS"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, contents)


if __name__ == "__main__":
    unittest.main()
