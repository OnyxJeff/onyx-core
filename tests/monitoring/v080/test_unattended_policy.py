"""Offline-only contract tests. No probes, tasks, registry, or protected history."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "windows" / "monitoring" / "v080" / "OnyxUnattendedPolicy.py"
EXAMPLE = ROOT / "windows" / "monitoring" / "v080" / "monitoring.unattended.example.json"

spec = importlib.util.spec_from_file_location("onyx_v080_offline_policy", MODULE)
policy = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(policy)

SOURCE = "a" * 40
ACCOUNT = r"SQUALL\jmay2"


def json_bytes(obj):
    return (json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


class OfflinePolicyTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def checked(self):
        return policy.validate_config(self.config)

    def assert_rejected(self):
        with self.assertRaises(policy.PolicyError):
            self.checked()

    def enrolled(self, *, account=ACCOUNT, source=SOURCE):
        data = copy.deepcopy(self.config)
        data["enabled"] = True
        raw = json_bytes(data)
        enrollment = {
            "schema_version": 1,
            "approval_scope": policy.SCOPE,
            "approved_account": account,
            "source_commit_sha": source,
            "config_sha256": hashlib.sha256(raw).hexdigest(),
            "approved_at_utc": "2026-11-10T13:59:15Z",
            "operator_approved": True,
            "read_only": True,
            "repair_action": "None",
        }
        return raw, enrollment

    def test_example_is_valid_disabled(self):
        self.assertFalse(self.checked()["enabled"])
        self.assertFalse(policy.check_example_file(EXAMPLE)["runtime_enabled"])

    def test_example_check_does_not_modify_file(self):
        before = hashlib.sha256(EXAMPLE.read_bytes()).hexdigest()
        policy.check_example_file(EXAMPLE)
        after = hashlib.sha256(EXAMPLE.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_example_check_rejects_enabled(self):
        self.config["enabled"] = True
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.json"
            p.write_bytes(json_bytes(self.config))
            with self.assertRaises(policy.PolicyError):
                policy.check_example_file(p)

    def test_rejects_absent_enrollment(self):
        config, _ = self.enrolled()
        with self.assertRaises(policy.PolicyError):
            policy.assess_offline_enrollment(config, None,
                verified_account=ACCOUNT, verified_source_commit=SOURCE)

    def test_rejects_disabled_config_even_with_enrollment(self):
        _, enrollment = self.enrolled()
        with self.assertRaises(policy.PolicyError):
            policy.assess_offline_enrollment(json_bytes(self.config), json_bytes(enrollment),
                verified_account=ACCOUNT, verified_source_commit=SOURCE)

    def test_valid_grant_is_still_not_runtime_authorization(self):
        config, grant = self.enrolled()
        outcome = policy.assess_offline_enrollment(config, json_bytes(grant),
            verified_account=ACCOUNT, verified_source_commit=SOURCE)
        self.assertTrue(outcome["enrollment_data_matches"])
        for field in ("runtime_enabled", "live_probe_authorized", "task_creation_authorized"):
            self.assertFalse(outcome[field])
        self.assertEqual(outcome["repair_action"], "None")

    def test_case_insensitive_account_match(self):
        config, grant = self.enrolled(account=r"squall\JMAY2")
        result = policy.assess_offline_enrollment(config, json_bytes(grant),
            verified_account=ACCOUNT, verified_source_commit=SOURCE)
        self.assertTrue(result["enrollment_data_matches"])

    def test_mismatched_account_refused(self):
        config, grant = self.enrolled(account=r"OTHER\jmay2")
        with self.assertRaises(policy.PolicyError):
            policy.assess_offline_enrollment(config, json_bytes(grant),
                verified_account=ACCOUNT, verified_source_commit=SOURCE)

    def test_mismatched_source_refused(self):
        config, grant = self.enrolled(source="b" * 40)
        with self.assertRaises(policy.PolicyError):
            policy.assess_offline_enrollment(config, json_bytes(grant),
                verified_account=ACCOUNT, verified_source_commit=SOURCE)

    def test_mismatched_config_digest_refused(self):
        config, grant = self.enrolled()
        grant["config_sha256"] = "0" * 64
        with self.assertRaises(policy.PolicyError):
            policy.assess_offline_enrollment(config, json_bytes(grant),
                verified_account=ACCOUNT, verified_source_commit=SOURCE)

    def test_changed_config_after_approval_refused(self):
        config, grant = self.enrolled()
        changed = json.loads(config)
        changed["schedule"]["interval_seconds"] = 60
        with self.assertRaises(policy.PolicyError):
            policy.assess_offline_enrollment(json_bytes(changed), json_bytes(grant),
                verified_account=ACCOUNT, verified_source_commit=SOURCE)

    def test_bad_verified_account_refused(self):
        config, grant = self.enrolled()
        with self.assertRaises(policy.PolicyError):
            policy.assess_offline_enrollment(config, json_bytes(grant),
                verified_account="jmay2", verified_source_commit=SOURCE)

    def test_bad_verified_source_refused(self):
        config, grant = self.enrolled()
        with self.assertRaises(policy.PolicyError):
            policy.assess_offline_enrollment(config, json_bytes(grant),
                verified_account=ACCOUNT, verified_source_commit="main")

    def test_bad_schema(self):
        self.config["schema_version"] = 2
        self.assert_rejected()

    def test_bool_schema_is_not_integer(self):
        self.config["schema_version"] = True
        self.assert_rejected()

    def test_rejects_unrecognized_top_level_field(self):
        self.config["run_command"] = "powershell.exe"
        self.assert_rejected()

    def test_rejects_missing_field(self):
        del self.config["authorization"]
        self.assert_rejected()

    def test_rejects_bad_profile(self):
        self.config["profile"] = "release"
        self.assert_rejected()

    def test_rejects_no_read_only(self):
        self.config["read_only"] = False
        self.assert_rejected()

    def test_rejects_repair(self):
        self.config["repair_action"] = "RestartICS"
        self.assert_rejected()

    def test_rejects_non_boolean_enabled(self):
        self.config["enabled"] = "false"
        self.assert_rejected()

    def test_rejects_v070_release_store(self):
        self.config["state_dir"] = policy.RELEASE_STATE_DIR
        self.assert_rejected()

    def test_rejects_v070_development_store(self):
        self.config["state_dir"] = policy.DEVELOPMENT_STATE_DIR
        self.assert_rejected()

    def test_rejects_unknown_state_store(self):
        self.config["state_dir"] = r"C:\Temp\Monitoring"
        self.assert_rejected()

    def test_rejects_ethernet_alias_change(self):
        self.config["windows"]["adapter_name"] = "Ethernet 2"
        self.assert_rejected()

    def test_rejects_target_change(self):
        self.config["windows"]["receiver_ip"] = "192.168.137.41"
        self.assert_rejected()

    def test_rejects_other_pi_key(self):
        self.config["pi"]["monitor_key_path"] = r"C:\Users\Public\key"
        self.assert_rejected()

    def test_rejects_other_python(self):
        self.config["runtime"]["python_executable"] = r"C:\Python312\python.exe"
        self.assert_rejected()

    def test_rejects_fast_interval(self):
        self.config["schedule"]["interval_seconds"] = 30
        self.assert_rejected()

    def test_rejects_slow_interval(self):
        self.config["schedule"]["interval_seconds"] = 300
        self.assert_rejected()

    def test_rejects_bool_interval(self):
        self.config["schedule"]["interval_seconds"] = True
        self.assert_rejected()

    def test_rejects_overlapping(self):
        self.config["schedule"]["overlap_policy"] = "Allow"
        self.assert_rejected()

    def test_rejects_missed_catchup(self):
        self.config["schedule"]["missed_cycle_policy"] = "RunImmediately"
        self.assert_rejected()

    def test_rejects_noninteractive_session(self):
        self.config["schedule"]["session_policy"] = "SYSTEM"
        self.assert_rejected()

    def test_rejects_repeat_alerts(self):
        self.config["alerts"]["repeat_identical_alerts"] = True
        self.assert_rejected()

    def test_rejects_remote_notification_channel(self):
        self.config["alerts"]["channel"] = "Webhook"
        self.assert_rejected()

    def test_rejects_missing_account_binding(self):
        self.config["authorization"]["require_account_match"] = False
        self.assert_rejected()

    def test_rejects_alternate_enrollment_path(self):
        self.config["authorization"]["enrollment_path"] = "C:\\Temp\\grant.json"
        self.assert_rejected()

    def test_rejects_unknown_nested_field(self):
        self.config["schedule"]["run_at_startup"] = True
        self.assert_rejected()

    def test_rejects_duplicate_json_config_field(self):
        raw = b'{"schema_version":1,"schema_version":1}'
        with self.assertRaises(policy.PolicyError):
            policy.parse_config(raw)

    def test_rejects_nonfinite_json(self):
        raw = json_bytes(self.config).replace(b'"interval_seconds":120',
                                              b'"interval_seconds":NaN')
        with self.assertRaises(policy.PolicyError):
            policy.parse_config(raw)

    def test_rejects_invalid_utf8(self):
        with self.assertRaises(policy.PolicyError):
            policy.parse_config(b'\xff')

    def test_rejects_large_config(self):
        with self.assertRaises(policy.PolicyError):
            policy.parse_config(b'x' * (policy.MAX_CONFIG_BYTES + 1))

    def test_rejects_invalid_json_type(self):
        with self.assertRaises(policy.PolicyError):
            policy.parse_config(b'[]')

    def test_rejects_enrollment_unknown_field(self):
        config, grant = self.enrolled()
        grant["task_install"] = True
        with self.assertRaises(policy.PolicyError):
            policy.parse_enrollment(json_bytes(grant))

    def test_rejects_enrollment_extra_permission(self):
        _, grant = self.enrolled()
        grant["repair_action"] = "RestartICS"
        with self.assertRaises(policy.PolicyError):
            policy.parse_enrollment(json_bytes(grant))

    def test_rejects_enrollment_without_operator_approval(self):
        _, grant = self.enrolled()
        grant["operator_approved"] = False
        with self.assertRaises(policy.PolicyError):
            policy.parse_enrollment(json_bytes(grant))

    def test_rejects_bad_enrollment_timestamp(self):
        _, grant = self.enrolled()
        grant["approved_at_utc"] = "2026-11-10T09:00:00"
        with self.assertRaises(policy.PolicyError):
            policy.parse_enrollment(json_bytes(grant))

    def test_rejects_invalid_grant_digest(self):
        _, grant = self.enrolled()
        grant["config_sha256"] = "abc"
        with self.assertRaises(policy.PolicyError):
            policy.parse_enrollment(json_bytes(grant))

    def test_rejects_invalid_grant_source_commit(self):
        _, grant = self.enrolled()
        grant["source_commit_sha"] = "not-a-commit"
        with self.assertRaises(policy.PolicyError):
            policy.parse_enrollment(json_bytes(grant))

    def test_does_not_read_or_create_protected_directories(self):
        # These strings are only parsed/compared. M1 does not expand or open them.
        self.checked()
        self.assertEqual(policy.STATE_DIR,
            r"%LOCALAPPDATA%\OnyxCore-v080\Monitoring")
        self.assertNotEqual(policy.STATE_DIR, policy.RELEASE_STATE_DIR)
        self.assertNotEqual(policy.STATE_DIR, policy.DEVELOPMENT_STATE_DIR)


if __name__ == "__main__":
    unittest.main()
