"""M2C synthetic integration: actual M2A/M2B code; no live diagnostics."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
MOD = ROOT / "windows" / "monitoring" / "v080" / "OnyxOfflineEvidenceIntegration.py"
spec = importlib.util.spec_from_file_location("onyx_m2c_offline_evidence", MOD)
assert spec and spec.loader
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

# Reuse existing *test-only* M2B fixture generation, never enrolled credentials.
from test_offline_authorization import build, encode

BASE = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)

def dt(seconds):
    return (BASE + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def sample(seconds, *, w="WindowsPathReady", pi="PiInternetVerified", **flags):
    return {"finished_utc": dt(seconds), "windows_classification": w,
            "pi_classification": pi,
            "history_error_present": flags.get("history_error_present", False),
            "windows_error_present": flags.get("windows_error_present", False),
            "pi_error_present": flags.get("pi_error_present", False)}


class OfflineEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.auth_dir = tempfile.TemporaryDirectory(prefix="onyx-v080-m2b-")
        self.addCleanup(self.auth_dir.cleanup)
        self.worker_dir = tempfile.TemporaryDirectory(prefix="onyx-v080-m2-")
        self.addCleanup(self.worker_dir.cleanup)
        self.ap = Path(self.auth_dir.name)
        self.wp = Path(self.worker_dir.name)
        c, e, r, f = build()
        self.raw = [encode(x) for x in (c, e, r, f)]
        for name, value in zip(("config.json", "enrollment.json", "revocation.json", "facts.json"), self.raw):
            (self.ap / name).write_bytes(value)
        self.samples = [sample(0)]
        self.reference = 180

    def evidence(self):
        return encode({"schema_version": 1, "provenance": "SyntheticFixtureOnly",
                       "reference_utc": dt(self.reference), "samples": self.samples})

    def run_case(self, mode="ok"):
        return core.run_offline_evidence(self.ap, self.wp, self.evidence(), worker_mode=mode)

    def assert_inert(self, result):
        self.assertTrue(result["simulation_only"])
        self.assertEqual(result["provenance"], "SyntheticFixtureOnly")
        self.assertEqual(result["authorization_status"], "EligibleDataOnly")
        for field in ("runtime_enabled", "live_probe_authorized", "task_creation_authorized",
                      "store_modified", "real_incident_confirmed", "connectivity_assessed"):
            self.assertIs(result[field], False, field)
        self.assertEqual(result["repair_action"], "None")
        self.assertNotIn("LiveRestrictedDiagnostic", json.dumps(result))

    def test_single_healthy_is_only_simulated(self):
        r = self.run_case()
        self.assert_inert(r)
        self.assertEqual((r["simulated_phase"], r["display_status"], r["processed_cycles"]),
                         ("Healthy", "Healthy", 1))
        self.assertEqual(r["event_types"], [])

    def test_two_suspects_not_active(self):
        self.samples = [sample(0, pi="ExternalTcpUnverified"),
                        sample(40, pi="ExternalTcpUnverified")]
        r = self.run_case()
        self.assertEqual(r["simulated_phase"], "Suspected")
        self.assertNotIn("IncidentEscalated", r["event_types"])
        self.assert_inert(r)

    def test_three_correlated_suspects_active_not_proven_ics(self):
        self.samples = [sample(t, pi="ExternalTcpUnverified") for t in (0, 40, 80)]
        r = self.run_case()
        self.assertEqual(r["simulated_phase"], "Active")
        self.assertIn("IncidentEscalated", r["event_types"])
        self.assert_inert(r)

    def test_suspicion_reset_prevents_escalation(self):
        self.samples = [sample(0, pi="ExternalTcpUnverified"), sample(40),
                        sample(80, pi="ExternalTcpUnverified"),
                        sample(120, pi="ExternalTcpUnverified")]
        r = self.run_case()
        self.assertEqual(r["simulated_phase"], "Suspected")
        self.assert_inert(r)

    def test_active_needs_two_spaced_recovery_cycles(self):
        self.samples = [sample(t, pi="ExternalTcpUnverified") for t in (0, 40, 80)]
        self.samples.extend([sample(120), sample(160)])
        r = self.run_case()
        self.assertEqual(r["simulated_phase"], "Recovered")
        self.assertEqual(r["display_status"], "Recovered")
        self.assertEqual(r["event_types"].count("IncidentRecovered"), 1)
        self.assert_inert(r)

    def test_recovery_not_accepted_with_short_spacing(self):
        self.samples = [sample(t, pi="ExternalTcpUnverified") for t in (0, 40, 80)]
        self.samples.extend([sample(120), sample(140)])
        r = self.run_case()
        self.assertEqual(r["simulated_phase"], "Active")
        self.assertNotIn("IncidentRecovered", r["event_types"])

    def test_incomplete_does_not_clear_active_incident(self):
        self.samples = [sample(t, pi="ExternalTcpUnverified") for t in (0, 40, 80)]
        self.samples.append(sample(110, pi="PiInternetVerified", pi_error_present=True))
        r = self.run_case()
        self.assertEqual(r["simulated_phase"], "Active")
        self.assertEqual(r["display_status"], "Unknown")
        self.assertEqual(r["evidence_status"], "Incomplete")
        self.assertIn("EvidenceIncomplete", r["event_types"])
        self.assert_inert(r)

    def test_incomplete_breaks_recovery_candidate(self):
        self.samples = [sample(t, pi="ExternalTcpUnverified") for t in (0, 40, 80)]
        self.samples.extend([sample(110), sample(140, windows_error_present=True), sample(175)])
        r = self.run_case()
        self.assertEqual(r["simulated_phase"], "Active")
        self.assertNotIn("IncidentRecovered", r["event_types"])

    def test_incomplete_then_restored(self):
        self.samples = [sample(0, pi_error_present=True), sample(40)]
        r = self.run_case()
        self.assertEqual(r["simulated_phase"], "Healthy")
        self.assertIn("EvidenceRestored", r["event_types"])

    def test_nonhealthy_different_status_does_not_confirm_ics(self):
        self.samples = [sample(t, w="WindowsPathUnverified", pi="PiUnreachable") for t in (0, 40, 80)]
        r = self.run_case()
        self.assertEqual(r["simulated_phase"], "Suspected")
        self.assertNotIn("IncidentEscalated", r["event_types"])
        self.assert_inert(r)

    def test_timeout_cannot_claim_health(self):
        r = self.run_case("hang")
        self.assertEqual((r["display_status"], r["evidence_status"], r["processed_cycles"]),
                         ("Unknown", "Unavailable", 0))
        self.assert_inert(r)

    def test_failed_worker_cannot_claim_health(self):
        for mode in ("nonzero", "invalid", "repair", "oversize"):
            with self.subTest(mode=mode):
                r = self.run_case(mode)
                self.assertEqual((r["display_status"], r["processed_cycles"]), ("Unknown", 0))
                self.assert_inert(r)

    def test_invalid_auth_refused_before_spawn(self):
        (self.ap / "facts.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(core.supervisor, "run_synthetic_cycle", side_effect=AssertionError("spawned")):
            with self.assertRaises(core.auth.OfflineAuthorizationError):
                self.run_case()
        self.assertEqual(tuple(self.wp.iterdir()), ())

    def test_invalid_evidence_refused_before_auth_or_spawn(self):
        with mock.patch.object(core.auth, "assess_temporary_fixture", side_effect=AssertionError("auth read")):
            with self.assertRaises(core.OfflineEvidenceError):
                core.run_offline_evidence(self.ap, self.wp, b"garbage")
        self.assertEqual(tuple(self.wp.iterdir()), ())

    def test_refuses_duplicate_json_keys(self):
        raw = self.evidence().replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
        with self.assertRaises(core.OfflineEvidenceError):
            core.run_offline_evidence(self.ap, self.wp, raw)

    def test_refuses_live_provenance(self):
        raw = self.evidence().replace(b'SyntheticFixtureOnly', b'LiveRestrictedDiagnostic')
        with self.assertRaises(core.OfflineEvidenceError):
            core.run_offline_evidence(self.ap, self.wp, raw)

    def test_refuses_invalid_utf8(self):
        with self.assertRaises(core.OfflineEvidenceError):
            core.run_offline_evidence(self.ap, self.wp, b"\xff")

    def test_refuses_nonfinite(self):
        raw = self.evidence().replace(b'"schema_version":1', b'"schema_version":NaN')
        with self.assertRaises(core.OfflineEvidenceError):
            core.run_offline_evidence(self.ap, self.wp, raw)

    def test_refuses_boolean_schema(self):
        raw = self.evidence().replace(b'"schema_version":1', b'"schema_version":true')
        with self.assertRaises(core.OfflineEvidenceError):
            core.run_offline_evidence(self.ap, self.wp, raw)

    def test_refuses_oversize(self):
        with self.assertRaises(core.OfflineEvidenceError):
            core.run_offline_evidence(self.ap, self.wp, b"X" * (core.MAX_EVIDENCE_BYTES + 1))

    def test_refuses_13_samples(self):
        self.samples = [sample(t) for t in range(13)]
        with self.assertRaises(core.OfflineEvidenceError):
            self.run_case()

    def test_refuses_out_of_order_samples(self):
        self.samples = [sample(40), sample(0)]
        with self.assertRaises(core.OfflineEvidenceError):
            self.run_case()

    def test_refuses_duplicate_timestamp(self):
        self.samples = [sample(40), sample(40)]
        with self.assertRaises(core.OfflineEvidenceError):
            self.run_case()

    def test_refuses_stale(self):
        self.reference = 601
        with self.assertRaises(core.OfflineEvidenceError):
            self.run_case()

    def test_refuses_future(self):
        self.reference = -10
        with self.assertRaises(core.OfflineEvidenceError):
            self.run_case()

    def test_refuses_naive_datetime(self):
        self.samples[0]["finished_utc"] = "2026-11-10T12:00:00"
        with self.assertRaises(core.OfflineEvidenceError):
            self.run_case()

    def test_refuses_false_flag_strings(self):
        for key in core.FLAGS:
            with self.subTest(key=key):
                self.samples[0][key] = "false"
                with self.assertRaises(core.OfflineEvidenceError):
                    self.run_case()
                self.samples[0][key] = False

    def test_refuses_unknown_sample_field(self):
        self.samples[0]["source"] = "live"
        with self.assertRaises(core.OfflineEvidenceError):
            self.run_case()

    def test_refuses_invalid_classifications(self):
        self.samples[0]["pi_classification"] = "PiInternetVERIFIED"
        with self.assertRaises(core.OfflineEvidenceError):
            self.run_case()

    def test_refuses_bad_fixture_directory_before_spawn(self):
        with mock.patch.object(core.supervisor, "run_synthetic_cycle", side_effect=AssertionError("spawned")):
            with self.assertRaises(core.auth.OfflineAuthorizationError):
                core.run_offline_evidence(Path(r"C:\\Production"), self.wp, self.evidence())

    def test_supervisor_forged_capability_refused(self):
        with mock.patch.object(core.supervisor, "run_synthetic_cycle", return_value={
            "source": "OnyxV080M2SyntheticSupervisor",
            "synthetic_only": True, "connectivity_assessed": False,
            "runtime_enabled": True, "live_probe_authorized": False,
            "task_creation_authorized": False, "store_modified": False,
            "repair_action": "None", "supervision_status": "Completed",
        }):
            with self.assertRaises(core.OfflineEvidenceError):
                self.run_case()

    def test_supervisor_forged_task_right_refused(self):
        with mock.patch.object(core.supervisor, "run_synthetic_cycle", return_value={
            "source": "OnyxV080M2SyntheticSupervisor", "synthetic_only": True,
            "connectivity_assessed": False, "runtime_enabled": False,
            "live_probe_authorized": False, "task_creation_authorized": True,
            "store_modified": False, "repair_action": "None", "supervision_status": "Completed",
        }):
            with self.assertRaises(core.OfflineEvidenceError):
                self.run_case()

    def test_simulated_auth_forged_real_windows_identity_refused(self):
        original = core.auth.assess_temporary_fixture(self.ap)
        original["identity_authenticated_in_windows"] = True
        with mock.patch.object(core.auth, "assess_temporary_fixture", return_value=original):
            with mock.patch.object(core.supervisor, "run_synthetic_cycle", side_effect=AssertionError("spawned")):
                with self.assertRaises(core.OfflineEvidenceError):
                    self.run_case()

    def test_in_repository_reducer_is_pure(self):
        reducer = core._load_v070_reducer()
        self.assertEqual(Path(reducer.__file__).name, "OnyxIncidentState.py")
        self.assertEqual(reducer.initial_state()["phase"], "Unknown")

    def test_module_inert_cli(self):
        result = subprocess.run([sys.executable, "-I", "-B", str(MOD), "--check-inert"],
                                capture_output=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        response = json.loads(result.stdout)
        self.assertIs(response["runtime_enabled"], False)
        self.assertIs(response["live_probe_authorized"], False)
        self.assertIs(response["store_modified"], False)

    def test_cli_refuses_execution_switch(self):
        for args in (["--live-read-only"], ["--check-inert", "--execute"], ["--fixture", str(self.ap)]):
            with self.subTest(args=args):
                run = subprocess.run([sys.executable, "-I", "-B", str(MOD), *args],
                                     capture_output=True, timeout=5, check=False)
                self.assertNotEqual(run.returncode, 0)

    def test_no_incident_state_files_created(self):
        self.run_case()
        self.assertEqual({p.name for p in self.wp.iterdir()}, {"fixture-cycle.lock"})
        self.assertEqual({p.name for p in self.ap.iterdir()}, {"config.json", "enrollment.json", "revocation.json", "facts.json"})

    def test_missing_v070_reducer_refused(self):
        with mock.patch.object(core, "_load_v070_reducer", side_effect=core.OfflineEvidenceError("missing")):
            with mock.patch.object(core.supervisor, "run_synthetic_cycle", side_effect=AssertionError("spawned")):
                with self.assertRaises(core.OfflineEvidenceError):
                    self.run_case()


if __name__ == "__main__":
    unittest.main()
