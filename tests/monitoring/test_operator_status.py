"""M4 Step 1 read-only operator view, using temp stores and mocked CLI guards.

All filesystem write operations are performed by test setup in TemporaryDirectory.
The operator module itself never creates or changes any state, runs a live probe,
or accesses production or SQUALL's actual %LOCALAPPDATA% monitoring store.
"""
from __future__ import annotations

import contextlib
import copy
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
import OnyxIncidentStore as storage
import OnyxLiveIncident as live
import OnyxOperatorStatus as operator

START = datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc)


def sample(second=0, decision="Healthy", *, incomplete=False, **updates):
    end = START + timedelta(seconds=second)
    start = end - timedelta(seconds=4)
    item = {
        "schema_version": 1,
        "source": "LiveRestrictedDiagnostic",
        "cycle_started_utc": start.isoformat(),
        "cycle_finished_utc": end.isoformat(),
        "duration_ms": 4000,
        "cycle_status": "EvidenceIncomplete" if incomplete else "Complete",
        "connectivity_decision": "Investigate" if incomplete else decision,
        "decision_reason": "M4-PRIVATE-DECISION-SHOULD-NOT-APPEAR",
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
        item.update(pi_classification="ExternalTcpUnverified", observation_count=3,
                    consecutive_suspected=3)
    item.update(updates)
    return item


class OperatorStatusTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="onyx-m4-status-")
        self.addCleanup(self.scratch.cleanup)
        self.directory = Path(self.scratch.name) / "Monitoring"
        self.directory.mkdir()
        self.store = self.directory / "incident-state.json"
        self.marker = self.directory / live.MARKER_NAME

    def first(self, item=None):
        return live.apply_live_cycle(sample() if item is None else item,
                                     self.directory, initialize_new=True)

    def next(self, item):
        return live.apply_live_cycle(item, self.directory)

    def test_healthy_status_matches_store(self):
        self.first()
        result = operator.read_status(self.directory)
        self.assertEqual((result["phase"], result["display_status"]), ("Healthy", "Healthy"))
        self.assertEqual((result["generation"], result["processed_cycles"]), (1, 1))
        self.assertFalse(result["live_probed"])
        self.assertEqual(result["repair_action"], "None")

    def test_two_healthy_cycles_preserve_generation(self):
        self.first()
        self.next(sample(60))
        report = operator.read_status(self.directory)
        self.assertEqual(report["generation"], 2)
        self.assertEqual(report["journal_count"], 0)
        self.assertEqual(report["events_shown"], [])

    def test_active_incident_and_last_events(self):
        self.first(sample(0, "WaitAndRetry"))
        self.next(sample(60, "PossibleIcsFailure"))
        report = operator.read_status(self.directory)
        self.assertEqual(report["phase"], "Active")
        self.assertEqual([e["event_type"] for e in report["events_shown"]],
                         ["IncidentOpened", "IncidentEscalated"])
        self.assertTrue(report["incident_id"].startswith("inc-"))
        self.assertIsNotNone(report["incident_opened_utc"])

    def test_active_incomplete_evidence_displays_unknown(self):
        self.first(sample(0, "PossibleIcsFailure"))
        self.next(sample(60, incomplete=True))
        report = operator.read_status(self.directory)
        self.assertEqual(report["phase"], "Active")
        self.assertEqual(report["display_status"], "Unknown")
        self.assertEqual(report["evidence_status"], "Incomplete")
        self.assertTrue(report["incident_id"])

    def test_recovered_reports_last_recovery_and_no_open_incident(self):
        self.first(sample(0, "PossibleIcsFailure"))
        self.next(sample(60))
        self.next(sample(120))
        report = operator.read_status(self.directory)
        self.assertEqual(report["phase"], "Recovered")
        self.assertIsNone(report["incident_id"])
        self.assertIsNotNone(report["last_recovered_utc"])
        self.assertIn("IncidentRecovered", [e["event_type"] for e in report["events_shown"]])

    def test_event_selection_limit_zero(self):
        self.first(sample(0, "WaitAndRetry"))
        report = operator.read_status(self.directory, max_events=0)
        self.assertEqual(report["events_shown"], [])
        self.assertEqual(report["journal_count"], 1)

    def test_event_selection_limit_one_picks_last(self):
        self.first(sample(0, "WaitAndRetry"))
        self.next(sample(60, "PossibleIcsFailure"))
        report = operator.read_status(self.directory, max_events=1)
        self.assertEqual([e["event_type"] for e in report["events_shown"]],
                         ["IncidentEscalated"])
        self.assertEqual(report["journal_count"], 2)

    def test_missing_state_refuses_blank_reset(self):
        with self.assertRaises(operator.OperatorStatusError):
            operator.read_status(self.directory)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_missing_marker_refused(self):
        self.first()
        self.marker.unlink()
        with self.assertRaises(operator.OperatorStatusError):
            operator.read_status(self.directory)
        self.assertTrue(self.store.exists())

    def test_bad_marker_refused_without_write(self):
        self.first()
        self.marker.write_bytes(b"incorrect")
        before = self.store.read_bytes()
        with self.assertRaises(operator.OperatorStatusError):
            operator.read_status(self.directory)
        self.assertEqual(self.store.read_bytes(), before)

    def test_tampered_store_refused_without_write(self):
        self.first()
        raw = self.store.read_bytes().replace(b'"generation":1', b'"generation":9')
        self.store.write_bytes(raw)
        before = self.store.read_bytes()
        with self.assertRaises(storage.CorruptIncidentStore):
            operator.read_status(self.directory)
        self.assertEqual(self.store.read_bytes(), before)

    def test_invalid_event_limits_refused(self):
        self.first()
        for value in (-1, 21, True, 2.5, "1", None):
            with self.subTest(value=value), self.assertRaises(operator.OperatorStatusError):
                operator.read_status(self.directory, max_events=value)

    def test_directory_must_be_absolute(self):
        with self.assertRaises(operator.OperatorStatusError):
            operator.read_status(Path("relative/Monitoring"))

    def test_missing_directory_does_not_get_created(self):
        other = self.directory / "not-created"
        with self.assertRaises(operator.OperatorStatusError):
            operator.read_status(other)
        self.assertFalse(other.exists())

    def test_symlinked_store_refused(self):
        self.first()
        target = self.directory / "original.json"
        self.store.rename(target)
        try:
            self.store.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable")
        with self.assertRaises(operator.OperatorStatusError):
            operator.read_status(self.directory)

    def test_symlinked_directory_refused(self):
        self.first()
        alias = Path(self.scratch.name) / "redirected"
        try:
            alias.symlink_to(self.directory, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable")
        with self.assertRaises(operator.OperatorStatusError):
            operator.read_status(alias)

    def test_repeat_reads_preserve_all_bytes_and_file_names(self):
        self.first(sample(0, "WaitAndRetry"))
        before = {p.name: p.read_bytes() for p in self.directory.iterdir() if p.is_file()}
        for _ in range(5):
            operator.read_status(self.directory)
        after = {p.name: p.read_bytes() for p in self.directory.iterdir() if p.is_file()}
        self.assertEqual(before, after)

    def test_text_output_is_historical_and_sanitized(self):
        self.first(sample(0, "WaitAndRetry"))
        text = operator.render_text(operator.read_status(self.directory))
        self.assertIn("NO new USB/ICS probe was run", text)
        self.assertIn("IncidentOpened", text)
        self.assertNotIn("M4-PRIVATE", text)
        self.assertNotIn(str(self.directory), text)

    def test_json_output_excludes_raw_reason_and_path(self):
        self.first(sample(0, "WaitAndRetry"))
        encoded = json.dumps(operator.read_status(self.directory))
        self.assertNotIn("decision_reason", encoded)
        self.assertNotIn("M4-PRIVATE", encoded)
        self.assertNotIn(str(self.directory), encoded)

    def test_cli_requires_explicit_status_flag(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                operator.main([])
        self.assertEqual(caught.exception.code, 2)

    def test_cli_json_and_text_read_same_store(self):
        self.first()
        with mock.patch.object(operator, "approved_status", side_effect=lambda **kw:
                               operator.read_status(self.directory, **kw)):
            for flags, json_mode in ((["--status", "--json"], True),
                                     (["--status", "--events", "0"], False)):
                stream = io.StringIO()
                with contextlib.redirect_stdout(stream):
                    self.assertEqual(operator.main(flags), 0)
                if json_mode:
                    self.assertEqual(json.loads(stream.getvalue())["generation"], 1)
                else:
                    self.assertIn("Stored incident status", stream.getvalue())

    def test_cli_refuses_missing_state_with_no_written_files(self):
        with mock.patch.object(operator, "approved_status", side_effect=lambda **kw:
                               operator.read_status(self.directory, **kw)):
            with contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(operator.main(["--status"]), 1)
            self.assertIn("REFUSED", error.getvalue())
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_cli_requires_approved_context_and_checkpoint_i(self):
        self.first()
        root = MODULES.parents[1]
        with (mock.patch.object(operator.live, "approved_context",
                                return_value=(root, self.directory)) as approve,
              mock.patch.object(operator.live, "_git", return_value="") as git):
            status = operator.approved_status()
        approve.assert_called_once()
        git.assert_called_once_with(root, "merge-base", "--is-ancestor",
                                    operator.CHECKPOINT_I, "HEAD")
        self.assertEqual(status["generation"], 1)

    def test_no_live_runner_called_by_operator(self):
        self.first()
        with mock.patch.object(operator.live, "run_existing_runner",
                               side_effect=AssertionError("live probe invoked")):
            operator.read_status(self.directory)


if __name__ == "__main__":
    unittest.main()
