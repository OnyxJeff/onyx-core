"""R2 adversarial tests: only in-memory JSON and synthetic events, no real workers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ast
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "windows" / "monitoring" / "v080" / "OnyxOfflineExecutionEvidenceContract.py"
spec = importlib.util.spec_from_file_location("onyx_r2_offline_evidence", MODULE)
r2 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(r2)
T0 = datetime(2026, 11, 10, 16, 0, tzinfo=timezone.utc)


def iso(milliseconds: int) -> str:
    return (T0 + timedelta(milliseconds=milliseconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def raw(obj) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def fixture():
    p = {"schema_version": 1, "simulation_only": True, "fixture_provider": "R2InMemoryFixtures",
         "worker_id": "r2-synthetic-observer-v1", "deadline_ms": 90000,
         "max_stdout_bytes": 8192, "max_samples": 4, "required_channels": list(r2.CHANNELS),
         "clock_skew_tolerance_ms": 2000, "live_probe_authorized": False,
         "task_creation_authorized": False, "repair_authorized": False,
         "notification_authorized": False}
    c = {"schema_version": 1, "simulation_only": True, "fixture_provider": "R2InMemoryFixtures",
         "worker_id": p["worker_id"], "anchor_utc": iso(0),
         "job": {"created_suspended": True, "assigned_before_resume": True,
                 "kill_on_close": True, "breakaway_allowed": False,
                 "nested_processes_allowed": False, "windows_job_attested": False,
                 "live_process_started": False},
         "phases": [{"phase": name, "tick_ms": tick}
                    for name, tick in zip(r2.PHASES, [0, 1, 2, 4000, 4050, 4100])],
         "outcome": {"kind": "success", "exit_code": 0,
                     "stdout_bytes": 120, "stderr_bytes": 0,
                     "descendants_remaining": 0,
                     "cleanup_completed": True, "job_closed": True}}
    e = {"schema_version": 1, "simulation_only": True, "fixture_provider": "R2InMemoryFixtures",
         "origin": "SyntheticFixtureOnly", "read_only": True, "attempted_writes": 0,
         "protected_store_accesses": 0, "external_calls": 0,
         "clock_confidence": "SyntheticUnattested", "captured_at_utc": iso(4000),
         "captured_tick_ms": 4070, "samples": []}
    for index, channel in enumerate(r2.CHANNELS):
        sample = {"channel": channel, "status": "Healthy", "detail_code": "fixture_ok",
                  "observed_at_utc": iso((index + 1) * 1000),
                  "tick_ms": (index + 1) * 1000 - 500, "read_only": True,
                  "provenance": "SyntheticFixtureOnly"}
        sample["sha256"] = r2.digest_sample(sample)
        e["samples"].append(sample)
    return p, c, e


def set_at(root, path, value):
    container = root
    for key in path[:-1]:
        container = container[key]
    container[path[-1]] = value


def drop_at(root, path):
    container = root
    for key in path[:-1]:
        container = container[key]
    del container[path[-1]]


class R2OfflineTests(unittest.TestCase):
    def setUp(self):
        self.p, self.c, self.e = fixture()

    def assess(self):
        return r2.assess_synthetic_cycle(raw(self.p), raw(self.c), raw(self.e))

    def test_complete_synthetic_healthy_is_never_live_health(self):
        result = self.assess()
        self.assertEqual(result["classification"], "SyntheticHealthy")
        for key in ("runtime_enabled", "live_probe_authorized", "windows_job_attested",
                    "clock_attested", "evidence_authentic", "task_creation_authorized",
                    "notification_enabled", "delivery_permitted", "store_modified"):
            self.assertIs(result[key], False)
        self.assertIs(result["simulation_only"], True)
        self.assertEqual(result["repair_action"], "None")

    def test_one_suspect_is_only_synthetic(self):
        s = self.e["samples"][2]
        s["status"] = "Suspect"
        s["detail_code"] = "fixture_suspect"
        s["sha256"] = r2.digest_sample(s)
        self.assertEqual(self.assess()["classification"], "SyntheticSuspect")

    def test_unknown_masks_synthetic_health(self):
        s = self.e["samples"][2]
        s["status"] = "Unknown"
        s["detail_code"] = "fixture_unknown"
        s["sha256"] = r2.digest_sample(s)
        self.assertEqual(self.assess()["classification"], "Unknown")

    def test_unknown_overrides_suspect(self):
        for ix, status in ((0, "Suspect"), (1, "Unknown")):
            s = self.e["samples"][ix]
            s["status"] = status
            s["detail_code"] = r2.STATUSES[status]
            s["sha256"] = r2.digest_sample(s)
        self.assertEqual(self.assess()["classification"], "Unknown")

    def test_timeout_has_no_evidence_and_unknown_result(self):
        self.c["outcome"].update(kind="timed_out", exit_code=None)
        self.c["phases"][3]["tick_ms"] = 90000
        self.c["phases"][4]["tick_ms"] = 90001
        self.c["phases"][5]["tick_ms"] = 90002
        self.e["captured_tick_ms"] = 90001
        self.e["captured_at_utc"] = iso(90000)
        self.e["samples"] = []
        self.assertEqual(self.assess()["classification"], "Unknown")

    def test_failed_worker_has_no_evidence_and_unknown_result(self):
        self.c["outcome"].update(kind="worker_failed", exit_code=5)
        self.e["samples"] = []
        self.assertEqual(self.assess()["classification"], "Unknown")

    def test_inert_cli(self):
        proc = subprocess.run([sys.executable, "-I", "-B", str(MODULE), "--check-inert"],
                              capture_output=True, text=True, timeout=8)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["source"], r2.STATUS_SOURCE)
        self.assertFalse(doc["runtime_enabled"])
        self.assertFalse(doc["live_probe_authorized"])
        self.assertFalse(doc["windows_job_attested"])
        self.assertFalse(doc["clock_attested"])
        self.assertFalse(doc["evidence_authentic"])

    def test_cli_refuses_execution_flags(self):
        for flag in ("--run", "--live", "--probe", "--enroll", "--repair", "--notify", "--worker"):
            with self.subTest(flag=flag):
                proc = subprocess.run([sys.executable, "-I", "-B", str(MODULE), flag],
                                      capture_output=True, text=True, timeout=8)
                self.assertNotEqual(proc.returncode, 0)

    def test_module_has_no_io_or_process_imports(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        forbidden = {"os", "subprocess", "socket", "pathlib", "ctypes", "winreg", "requests",
                     "urllib", "threading", "multiprocessing", "asyncio", "shutil", "tempfile"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertFalse({a.name.split(".")[0] for a in node.names} & forbidden)
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], forbidden)
            if isinstance(node, (ast.Call,)) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "exec", "eval", "__import__"})

    def test_input_unchanged(self):
        before = copy.deepcopy((self.p, self.c, self.e))
        self.assess()
        self.assertEqual((self.p, self.c, self.e), before)

    def test_digest_case_sensitive(self):
        s = self.e["samples"][0]
        self.assertRegex(r2.digest_sample(s), r"^[0-9a-f]{64}$")
        s["sha256"] = s["sha256"].upper()
        with self.assertRaises(r2.OfflineEvidenceError):
            self.assess()

    def test_duplicate_json_key_refused(self):
        data = raw(self.p).replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1', 1)
        with self.assertRaises(r2.OfflineEvidenceError):
            r2.assess_synthetic_cycle(data, raw(self.c), raw(self.e))

    def test_nonfinite_json_refused(self):
        data = raw(self.c).replace(b'"stdout_bytes":120', b'"stdout_bytes":NaN', 1)
        with self.assertRaises(r2.OfflineEvidenceError):
            r2.assess_synthetic_cycle(raw(self.p), data, raw(self.e))

    def test_invalid_utf8_refused(self):
        with self.assertRaises(r2.OfflineEvidenceError):
            r2.assess_synthetic_cycle(b"\xff", raw(self.c), raw(self.e))

    def test_oversize_fixture_refused(self):
        with self.assertRaises(r2.OfflineEvidenceError):
            r2.assess_synthetic_cycle(raw(self.p) + b" " * 65536, raw(self.c), raw(self.e))

    def test_wrong_type_refused(self):
        with self.assertRaises(r2.OfflineEvidenceError):
            r2.assess_synthetic_cycle("not bytes", raw(self.c), raw(self.e))

    def test_no_runtime_worker_is_invoked(self):
        # Patch the process spawning surface only during an in-memory call.
        from unittest.mock import patch
        with patch("subprocess.Popen", side_effect=AssertionError("spawn attempted")):
            self.assertEqual(self.assess()["classification"], "SyntheticHealthy")

    def test_no_live_io_invoked(self):
        from unittest.mock import patch
        with patch("builtins.open", side_effect=AssertionError("file open attempted")):
            self.assertEqual(self.assess()["classification"], "SyntheticHealthy")


# Each name describes a distinct adversarial case. The same fixture is mutated
# in memory; NO Windows token/ACL, Job Object, network, or protected store touched.
BAD_VALUES = [
    ("policy_wrong_schema", "p", ("schema_version",), 2),
    ("policy_bool_schema", "p", ("schema_version",), True),
    ("policy_simulation_off", "p", ("simulation_only",), False),
    ("policy_wrong_provider", "p", ("fixture_provider",), "WindowsAPI"),
    ("policy_worker_mismatch", "p", ("worker_id",), "C:\\Windows\\System32\\cmd.exe"),
    ("policy_deadline_too_long", "p", ("deadline_ms",), 90001),
    ("policy_deadline_too_short", "p", ("deadline_ms",), 89999),
    ("policy_boolean_deadline", "p", ("deadline_ms",), True),
    ("policy_unbounded_output", "p", ("max_stdout_bytes",), 10_000_000),
    ("policy_wrong_sample_count", "p", ("max_samples",), 12),
    ("policy_duplicate_channels", "p", ("required_channels",), ["pc_usb_network"] * 4),
    ("policy_reordered_channels", "p", ("required_channels",), list(reversed(r2.CHANNELS))),
    ("policy_loose_skew", "p", ("clock_skew_tolerance_ms",), 100000),
    ("policy_live_probe_claim", "p", ("live_probe_authorized",), True),
    ("policy_task_creation_claim", "p", ("task_creation_authorized",), True),
    ("policy_repair_claim", "p", ("repair_authorized",), True),
    ("policy_notification_claim", "p", ("notification_authorized",), True),
    ("containment_wrong_schema", "c", ("schema_version",), 3),
    ("containment_simulation_false", "c", ("simulation_only",), False),
    ("containment_provider_forged", "c", ("fixture_provider",), "RealJobObjects"),
    ("containment_worker_switched", "c", ("worker_id",), "other-worker"),
    ("containment_missing_suspended", "c", ("job", "created_suspended"), False),
    ("containment_job_assigned_late", "c", ("job", "assigned_before_resume"), False),
    ("containment_job_not_killed_on_close", "c", ("job", "kill_on_close"), False),
    ("containment_breakaway_permitted", "c", ("job", "breakaway_allowed"), True),
    ("containment_nested_worker_allowed", "c", ("job", "nested_processes_allowed"), True),
    ("containment_windows_job_attested_forged", "c", ("job", "windows_job_attested"), True),
    ("containment_live_process_started_claim", "c", ("job", "live_process_started"), True),
    ("containment_phase_reordered", "c", ("phases", 1, "phase"), "resumed"),
    ("containment_initial_tick_nonzero", "c", ("phases", 0, "tick_ms"), 1),
    ("containment_nonmonotonic_tick", "c", ("phases", 2, "tick_ms"), 1),
    ("containment_boolean_tick", "c", ("phases", 1, "tick_ms"), True),
    ("containment_negative_tick", "c", ("phases", 1, "tick_ms"), -1),
    ("containment_success_after_deadline", "c", ("phases", 3, "tick_ms"), 90000),
    ("containment_cleanup_after_budget", "c", ("phases", 5, "tick_ms"), 97000),
    ("containment_unknown_outcome", "c", ("outcome", "kind"), "success_with_repair"),
    ("containment_success_exit_nonzero", "c", ("outcome", "exit_code"), 1),
    ("containment_success_exit_bool", "c", ("outcome", "exit_code"), False),
    ("containment_output_oversized", "c", ("outcome", "stdout_bytes"), 8193),
    ("containment_output_negative", "c", ("outcome", "stdout_bytes"), -1),
    ("containment_stderr_oversized", "c", ("outcome", "stderr_bytes"), 8193),
    ("containment_descendant_survived", "c", ("outcome", "descendants_remaining"), 1),
    ("containment_cleanup_incomplete", "c", ("outcome", "cleanup_completed"), False),
    ("containment_job_not_closed", "c", ("outcome", "job_closed"), False),
    ("containment_invalid_anchor", "c", ("anchor_utc",), "2026-11-10T16:00:00+00:00"),
    ("evidence_wrong_schema", "e", ("schema_version",), 2),
    ("evidence_simulation_false", "e", ("simulation_only",), False),
    ("evidence_provider_forged", "e", ("fixture_provider",), "TrustedWindowsCollector"),
    ("evidence_live_origin_forged", "e", ("origin",), "RealWindowsObservations"),
    ("evidence_readonly_false", "e", ("read_only",), False),
    ("evidence_write_attempt", "e", ("attempted_writes",), 1),
    ("evidence_v070_store_access", "e", ("protected_store_accesses",), 1),
    ("evidence_external_network_call", "e", ("external_calls",), 1),
    ("evidence_fake_clock_attestation", "e", ("clock_confidence",), "TrustedWindowsUTC"),
    ("evidence_capture_future_tick", "e", ("captured_tick_ms",), 4500),
    ("evidence_capture_before_worker_end", "e", ("captured_tick_ms",), 3000),
    ("evidence_capture_bad_wall_clock", "e", ("captured_at_utc",), "2026-11-10T16:05:00Z"),
    ("evidence_capture_offset_timestamp", "e", ("captured_at_utc",), "2026-11-10T16:00:04+00:00"),
    ("sample_reordered_channel", "e", ("samples", 1, "channel"), "pi_another"),
    ("sample_duplicate_channel", "e", ("samples", 1, "channel"), "pc_usb_network"),
    ("sample_false_health_status", "e", ("samples", 0, "status"), "VerifiedHealthy"),
    ("sample_healthy_detail_contradiction", "e", ("samples", 0, "detail_code"), "fixture_suspect"),
    ("sample_fake_real_provenance", "e", ("samples", 0, "provenance"), "TrustedWindowsCollector"),
    ("sample_readonly_false", "e", ("samples", 0, "read_only"), False),
    ("sample_duplicate_tick", "e", ("samples", 1, "tick_ms"), 500),
    ("sample_negative_tick", "e", ("samples", 0, "tick_ms"), -1),
    ("sample_tick_after_worker_end", "e", ("samples", 0, "tick_ms"), 4001),
    ("sample_wrong_digest", "e", ("samples", 0, "sha256"), "f" * 64),
    ("sample_uppercase_digest", "e", ("samples", 0, "sha256"), "A" * 64),
    ("sample_future_wall_clock", "e", ("samples", 0, "observed_at_utc"), "2026-11-10T16:06:00Z"),
    ("sample_nan_tick", "e", ("samples", 0, "tick_ms"), float("nan")),
]


def create_bad_value_test(root: str, path: tuple, replacement):
    def check(self):
        data = {"p": self.p, "c": self.c, "e": self.e}[root]
        set_at(data, path, replacement)
        with self.assertRaises(r2.OfflineEvidenceError):
            self.assess()
    return check


for name, target, path, bad in BAD_VALUES:
    setattr(R2OfflineTests, "test_refuses_" + name, create_bad_value_test(target, path, bad))


def make_missing_test(target: str, key: tuple):
    def check(self):
        data = {"p": self.p, "c": self.c, "e": self.e}[target]
        drop_at(data, key)
        with self.assertRaises(r2.OfflineEvidenceError):
            self.assess()
    return check


for name, target, path in [
    ("policy_missing_field", "p", ("worker_id",)),
    ("policy_extra_field", "p", ("repair_authorized",)),
    ("containment_missing_job_property", "c", ("job", "kill_on_close")),
    ("containment_missing_phase", "c", ("phases", 3)),
    ("containment_missing_exit", "c", ("outcome", "exit_code")),
    ("evidence_missing_channel", "e", ("samples", 2)),
    ("evidence_missing_provenance", "e", ("samples", 0, "provenance")),
    ("evidence_missing_readonly", "e", ("read_only",)),
]:
    setattr(R2OfflineTests, "test_refuses_" + name, make_missing_test(target, path))


if __name__ == "__main__":
    unittest.main()
