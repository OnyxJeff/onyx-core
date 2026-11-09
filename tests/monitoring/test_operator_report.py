"""Offline tests for M4 age-aware operator report; temp stores only."""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

MODULES = Path(__file__).resolve().parents[2] / "windows" / "monitoring"
sys.path.insert(0, str(MODULES))
import OnyxLiveIncident as live
import OnyxOperatorStatus as operator
import OnyxOperatorReport as report

START = datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc)


def sample(seconds=0, decision="Healthy", *, incomplete=False):
    at = START + timedelta(seconds=seconds)
    data = {
        "schema_version": 1, "source": "LiveRestrictedDiagnostic",
        "cycle_started_utc": (at - timedelta(seconds=4)).isoformat(),
        "cycle_finished_utc": at.isoformat(), "duration_ms": 4000,
        "cycle_status": "EvidenceIncomplete" if incomplete else "Complete",
        "connectivity_decision": "Investigate" if incomplete else decision,
        "decision_reason": "SECRET-NOT-FOR-REPORT",
        "windows_classification": "WindowsPathReady",
        "pi_classification": "PiProbeUnavailable" if incomplete else "PiInternetVerified",
        "observation_count": 3 if decision == "PossibleIcsFailure" and not incomplete else 1,
        "consecutive_suspected": 3 if decision == "PossibleIcsFailure" and not incomplete else 0,
        "history_error_present": incomplete,
        "windows_error_present": False, "pi_error_present": False,
        "repair_action": "None",
    }
    if decision == "PossibleIcsFailure" and not incomplete:
        data["pi_classification"] = "ExternalTcpUnverified"
    return data


class OperatorReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="onyx-m4-report-")
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "Monitoring"
        self.directory.mkdir()

    def first(self, data=None):
        live.apply_live_cycle(data if data is not None else sample(),
                              self.directory, initialize_new=True)

    def next(self, data):
        live.apply_live_cycle(data, self.directory)

    def view(self, *, now=START, stale=30, events=10):
        stored = operator.read_status(self.directory, max_events=events)
        return report.summarize(stored, now_utc=now, stale_minutes=stale)

    def test_recent_healthy_is_explicitly_historical(self):
        self.first()
        result = self.view(now=START + timedelta(minutes=2))
        self.assertEqual((result["freshness"], result["phase"]), ("Recent", "Healthy"))
        self.assertFalse(result["live_probed"])
        self.assertIn("no fresh probe", result["assessment"])

    def test_stale_healthy_is_not_current_health_claim(self):
        self.first()
        r = self.view(now=START + timedelta(minutes=31))
        self.assertEqual(r["freshness"], "Stale")
        self.assertIn("stale", r["assessment"])
        self.assertEqual(r["display_status_at_observation"], "Healthy")

    def test_exact_threshold_is_recent(self):
        self.first()
        self.assertEqual(self.view(now=START + timedelta(minutes=30))["freshness"], "Recent")

    def test_one_second_after_threshold_is_stale(self):
        self.first()
        self.assertEqual(self.view(now=START + timedelta(seconds=1801))["freshness"], "Stale")

    def test_custom_threshold_changes_freshness(self):
        self.first()
        self.assertEqual(self.view(now=START + timedelta(minutes=11), stale=10)["freshness"], "Stale")
        self.assertEqual(self.view(now=START + timedelta(minutes=11), stale=12)["freshness"], "Recent")

    def test_future_within_tolerance_is_recent_but_age_zero(self):
        self.first()
        r = self.view(now=START - timedelta(seconds=120))
        self.assertEqual((r["freshness"], r["age_seconds"]), ("Recent", 0))

    def test_future_beyond_tolerance_is_clock_skew(self):
        self.first()
        r = self.view(now=START - timedelta(seconds=121))
        self.assertEqual(r["freshness"], "FutureClockSkew")
        self.assertIsNone(r["age_seconds"])
        self.assertIn("clock", r["assessment"])

    def test_timezone_conversion_of_reference(self):
        self.first()
        eastern = timezone(timedelta(hours=-5))
        r = self.view(now=datetime(2026, 11, 9, 13, 10, tzinfo=eastern))
        self.assertEqual(r["age_seconds"], 600)
        self.assertTrue(r["as_of_utc"].endswith("Z"))

    def test_naive_reference_rejected(self):
        self.first()
        with self.assertRaises(report.OperatorReportError):
            self.view(now=datetime(2026, 11, 9, 18, 0))

    def test_invalid_stale_thresholds_rejected(self):
        self.first()
        for val in (0, -1, 1441, True, False, 1.5, "30", None):
            with self.subTest(val=val), self.assertRaises(report.OperatorReportError):
                self.view(stale=val)

    def test_invalid_observation_timestamp_rejected(self):
        self.first()
        s = operator.read_status(self.directory)
        for val in (None, 4, "", "tomorrow", "2026-11-09T18:00:00"):
            with self.subTest(val=val), self.assertRaises(report.OperatorReportError):
                report.summarize({**s, "last_cycle_finished_utc": val}, now_utc=START)

    def test_bad_status_source_refused(self):
        self.first()
        s = operator.read_status(self.directory)
        with self.assertRaises(report.OperatorReportError):
            report.summarize({**s, "source": "External"}, now_utc=START)

    def test_live_probed_status_refused(self):
        self.first()
        s = operator.read_status(self.directory)
        with self.assertRaises(report.OperatorReportError):
            report.summarize({**s, "live_probed": True}, now_utc=START)

    def test_repair_action_refused(self):
        self.first()
        s = operator.read_status(self.directory)
        with self.assertRaises(report.OperatorReportError):
            report.summarize({**s, "repair_action": "RestartICS"}, now_utc=START)

    def test_incomplete_evidence_never_claims_healthy(self):
        self.first(sample(0, incomplete=True))
        r = self.view(now=START + timedelta(minutes=3))
        self.assertEqual(r["evidence_status"], "Incomplete")
        self.assertIn("incomplete", r["assessment"])

    def test_open_active_incident_reported(self):
        self.first(sample(0, "PossibleIcsFailure"))
        r = self.view(now=START + timedelta(seconds=15))
        self.assertTrue(r["incident_open"])
        self.assertEqual(r["phase"], "Active")
        self.assertIn("open", r["assessment"])

    def test_active_incomplete_evidence_preserves_incident(self):
        self.first(sample(0, "PossibleIcsFailure"))
        self.next(sample(60, incomplete=True))
        r = self.view(now=START + timedelta(seconds=70))
        self.assertTrue(r["incident_open"])
        self.assertEqual(r["display_status_at_observation"], "Unknown")
        self.assertEqual(r["phase"], "Active")

    def test_recovered_incident_no_longer_open(self):
        self.first(sample(0, "PossibleIcsFailure"))
        self.next(sample(60))
        self.next(sample(120))
        r = self.view(now=START + timedelta(seconds=125))
        self.assertFalse(r["incident_open"])
        self.assertEqual(r["phase"], "Recovered")
        self.assertIn("recovered", r["assessment"])

    def test_zero_events_does_not_claim_complete_journal(self):
        self.first(sample(0, "WaitAndRetry"))
        r = self.view(events=0)
        self.assertEqual(r["selected_event_count"], 0)
        self.assertEqual(r["journal_count"], 1)
        self.assertTrue(r["history_is_partial"])

    def test_event_limit_and_selected_counts(self):
        self.first(sample(0, "WaitAndRetry"))
        self.next(sample(60, "PossibleIcsFailure"))
        r = self.view(now=START + timedelta(seconds=65), events=1)
        self.assertEqual(r["selected_event_count"], 1)
        self.assertEqual(r["selected_event_counts"], {"IncidentEscalated": 1})
        self.assertTrue(r["history_is_partial"])

    def test_full_selected_events_are_not_partial(self):
        self.first(sample(0, "WaitAndRetry"))
        self.next(sample(60, "PossibleIcsFailure"))
        r = self.view(now=START + timedelta(seconds=65), events=10)
        self.assertEqual(r["selected_event_count"], 2)
        self.assertFalse(r["history_is_partial"])

    def test_text_output_explains_historical_state(self):
        self.first()
        text = report.render_text(self.view(now=START + timedelta(minutes=50)))
        self.assertIn("Historical stored data", text)
        self.assertIn("Stale", text)
        self.assertIn("No live USB/ICS probe", text)

    def test_json_no_private_fields_or_paths(self):
        self.first(sample(0, "WaitAndRetry"))
        j = json.dumps(self.view(now=START + timedelta(minutes=5)))
        self.assertNotIn("SECRET-NOT-FOR-REPORT", j)
        self.assertNotIn("decision_reason", j)
        self.assertNotIn(str(self.directory), j)

    def test_repeat_reports_do_not_modify_files(self):
        self.first(sample(0, "WaitAndRetry"))
        before = {p.name: p.read_bytes() for p in self.directory.iterdir() if p.is_file()}
        for minute in range(40):
            self.view(now=START + timedelta(minutes=minute))
        after = {p.name: p.read_bytes() for p in self.directory.iterdir() if p.is_file()}
        self.assertEqual(before, after)

    def test_corrupt_store_refused_no_repair(self):
        self.first()
        path = self.directory / "incident-state.json"
        path.write_bytes(b'corrupt')
        before = path.read_bytes()
        with self.assertRaises(Exception):
            self.view()
        self.assertEqual(path.read_bytes(), before)

    def test_cli_requires_report_flag(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                report.main([])
        self.assertEqual(caught.exception.code, 2)

    def test_cli_json_and_text_match(self):
        self.first()
        with mock.patch.object(report, "approved_report", side_effect=lambda **kw:
                               self.view(now=START + timedelta(minutes=5),
                                         stale=kw["stale_minutes"], events=kw["events"])):
            jstream = io.StringIO()
            with contextlib.redirect_stdout(jstream):
                self.assertEqual(report.main(["--report", "--json", "--events", "0"]), 0)
            tstream = io.StringIO()
            with contextlib.redirect_stdout(tstream):
                self.assertEqual(report.main(["--report", "--events", "0"]), 0)
            parsed = json.loads(jstream.getvalue())
            self.assertEqual(parsed["generation"], 1)
            self.assertIn(parsed["freshness"], tstream.getvalue())

    def test_cli_ancestry_and_context_required(self):
        self.first()
        root = MODULES.parents[1]
        with (mock.patch.object(report.live, "approved_context", return_value=(root, self.directory)),
              mock.patch.object(report.live, "_git", return_value="") as git):
            result = report.approved_report(events=0)
        git.assert_called_once_with(root, "merge-base", "--is-ancestor",
                                    report.CHECKPOINT_J, "HEAD")
        self.assertEqual(result["generation"], 1)

    def test_no_live_runner_even_in_cli(self):
        self.first()
        with (mock.patch.object(report.live, "run_existing_runner",
                                side_effect=AssertionError("LIVE PROBE")),
              mock.patch.object(report.live, "approved_context", return_value=(MODULES.parents[1], self.directory)),
              mock.patch.object(report.live, "_git", return_value="")):
            self.assertEqual(report.approved_report()["generation"], 1)

    def test_missing_store_does_not_initialize(self):
        with mock.patch.object(report.live, "approved_context", return_value=(MODULES.parents[1], self.directory)), \
             mock.patch.object(report.live, "_git", return_value=""):
            with self.assertRaises(operator.OperatorStatusError):
                report.approved_report()
        self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
