"""Milestone 5 offline release-policy contracts; NEVER probes or launches services."""
from __future__ import annotations

import copy
import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "windows" / "monitoring"
sys.path.insert(0, str(MODULES))
import OnyxReleasePolicy as policy
import OnyxMonitorConfig as dev_config

RELEASE = MODULES / policy.RELEASE_CONFIG_NAME
DEV = MODULES / "monitoring.development.example.json"


class ReleasePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.example = policy.load_release_config(RELEASE)

    def altered(self, *path_and_value):
        *path, value = path_and_value
        value_copy = copy.deepcopy(self.example)
        current = value_copy
        for key in path[:-1]:
            current = current[key]
        current[path[-1]] = value
        return value_copy

    def rejected(self, *path_and_value):
        with self.assertRaises(policy.ReleasePolicyError):
            policy.validate_release_config(self.altered(*path_and_value))

    def intent(self, **updates):
        args = dict(config=self.example, root=policy.RELEASE_ROOT,
                    branch="main", operation="report")
        args.update(updates)
        return policy.validate_release_intent(**args)

    def test_reference_is_separate_and_valid(self):
        self.assertEqual(self.example["profile"], "release")
        self.assertEqual(self.example["state_dir"], policy.RELEASE_STATE)
        self.assertTrue(self.example["read_only"])

    def test_existing_development_contract_is_unchanged(self):
        dev = dev_config.load_config(DEV)
        self.assertEqual(dev["profile"], "development")
        with self.assertRaises(dev_config.ConfigError):
            dev_config.validate_config(copy.deepcopy(self.example))

    def test_must_be_release_profile(self):
        self.rejected("profile", "development")

    def test_dedicated_state_path_cannot_be_dev_or_generic(self):
        self.rejected("state_dir", dev_config.DEV_STATE)
        self.rejected("state_dir", r"%LOCALAPPDATA%\OnyxCore\Monitoring")
        self.rejected("state_dir", r"D:\alternate\Monitoring")

    def test_read_only_and_no_repair_mandatory(self):
        self.rejected("read_only", False)
        self.rejected("repair_action", "RestartSharedAccess")

    def test_key_must_be_restricted_monitoring_identity(self):
        self.rejected("pi", "monitor_key_path", r"%USERPROFILE%\.ssh\id_rsa")

    def test_unknown_key_is_refused(self):
        candidate = copy.deepcopy(self.example)
        candidate["enable_scheduler"] = True
        with self.assertRaises(policy.ReleasePolicyError):
            policy.validate_release_config(candidate)

    def test_invalid_network_and_runtime_are_rejected(self):
        self.rejected("windows", "gateway_ip", "not-an-address")
        self.rejected("windows", "receiver_ip", self.example["windows"]["gateway_ip"])
        self.rejected("runtime", "ssh_executable", "ssh")
        self.rejected("timeouts", "ssh_seconds", 500)

    def test_wrong_schema_is_rejected(self):
        self.rejected("schema_version", 2)
        self.rejected("schema_version", True)

    def test_boolean_does_not_pass_number_bound(self):
        self.rejected("monitoring_interval_seconds", True)

    def test_missing_field_rejected(self):
        candidate = copy.deepcopy(self.example)
        del candidate["pi"]
        with self.assertRaises(policy.ReleasePolicyError):
            policy.validate_release_config(candidate)

    def test_config_is_not_mutated(self):
        before = copy.deepcopy(self.example)
        result = policy.validate_release_config(self.example)
        self.assertEqual(self.example, before)
        self.assertEqual(result, before)
        self.assertIsNot(result, self.example)

    def test_duplicate_keys_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "bad.json"
            path.write_text('{"profile":"release","profile":"release"}', encoding="utf-8")
            with self.assertRaises(policy.ReleasePolicyError):
                policy.load_release_config(path)

    def test_json_nonfinite_values_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "bad.json"
            path.write_text(RELEASE.read_text(encoding="utf-8").replace(
                '"receiver_port": 8765', '"receiver_port": NaN'), encoding="utf-8")
            with self.assertRaises(policy.ReleasePolicyError):
                policy.load_release_config(path)

    def test_invalid_utf8_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "bad.json"
            path.write_bytes(b"\xff\xfe\xff")
            with self.assertRaises(policy.ReleasePolicyError):
                policy.load_release_config(path)

    def test_oversized_config_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "oversize.json"
            path.write_bytes(b" " * 16385)
            with self.assertRaises(policy.ReleasePolicyError):
                policy.load_release_config(path)

    def test_missing_config_refused(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(policy.ReleasePolicyError):
                policy.load_release_config(Path(root) / "missing.json")

    def test_release_root_must_be_expected_path(self):
        for bad in ("D:\\github_repos\\other", "/tmp/onyx-core", "onyx-core",
                    r"\\server\share\onyx-core", "C:\\github_repos\\onyx-core",
                    policy.RELEASE_ROOT + "\\", r"D:\github_repos\other\..\onyx-core",
                    r"D:/github_repos/onyx-core"):
            with self.subTest(bad=bad), self.assertRaises(policy.ReleasePolicyError):
                self.intent(root=bad)

    def test_release_path_is_case_insensitive_on_windows(self):
        self.assertEqual(self.intent(root=policy.RELEASE_ROOT.upper())["operation"], "report")

    def test_branch_must_be_main(self):
        for bad in ("feature/v0.7.0-monitoring", "HEAD", "master", "Main"):
            with self.subTest(bad=bad), self.assertRaises(policy.ReleasePolicyError):
                self.intent(branch=bad)

    def test_unknown_operation_fails(self):
        with self.assertRaises(policy.ReleasePolicyError):
            self.intent(operation="repair")

    def test_status_and_report_are_read_only(self):
        self.assertFalse(self.intent(operation="status")["runtime_enabled"])
        self.assertFalse(self.intent(operation="report")["runtime_enabled"])
        self.assertTrue(self.intent(operation="status")["manual_only"])

    def test_cycle_requires_explicit_authorization(self):
        with self.assertRaises(policy.ReleasePolicyError):
            self.intent(operation="one-shot-cycle")
        output = self.intent(operation="one-shot-cycle", explicit_live_read_only=True)
        self.assertFalse(output["runtime_enabled"])
        self.assertTrue(output["requires_runtime_preflight"])

    def test_initialization_requires_one_shot_cycle(self):
        with self.assertRaises(policy.ReleasePolicyError):
            self.intent(initialize_new=True)
        output = self.intent(operation="one-shot-cycle", explicit_live_read_only=True,
                             initialize_new=True)
        self.assertFalse(output["runtime_enabled"])

    def test_stored_data_views_refuse_live_flag(self):
        for operation in ("status", "report"):
            with self.subTest(operation=operation), self.assertRaises(policy.ReleasePolicyError):
                self.intent(operation=operation, explicit_live_read_only=True)

    def test_scheduler_is_forbidden(self):
        with self.assertRaises(policy.ReleasePolicyError):
            self.intent(schedule_requested=True)

    def test_repair_action_is_forbidden(self):
        with self.assertRaises(policy.ReleasePolicyError):
            self.intent(repair_action="RestartSharedAccess")

    def test_malformed_flags_are_rejected(self):
        for flag, bad in (("explicit_live_read_only", 1), ("initialize_new", "yes"),
                          ("schedule_requested", "yes")):
            with self.subTest(flag=flag), self.assertRaises(policy.ReleasePolicyError):
                self.intent(**{flag: bad})

    def test_cli_check_is_offline_and_has_no_live_arguments(self):
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(policy.main(["--check", str(RELEASE)]), 0)
        self.assertIn("runtime NOT enabled", output.getvalue())
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            policy.main(["--check", str(RELEASE), "--live-read-only"])

    def test_policy_never_creates_state_or_invokes_network(self):
        with (mock.patch("subprocess.run", side_effect=AssertionError("process used")),
              mock.patch("socket.socket", side_effect=AssertionError("network used")),
              mock.patch.object(Path, "mkdir", side_effect=AssertionError("mkdir used"))):
            self.intent(operation="one-shot-cycle", explicit_live_read_only=True)
            self.intent(operation="report")
            policy.validate_release_config(self.example)

    def test_configuration_does_not_depend_on_old_main_sha(self):
        # No v0.6.0 SHA, untracked backup, or Git status is consumed by the
        # policy. Actual Git/source/ACL preflight is a later explicit gate.
        data = self.intent()
        self.assertEqual(data["profile"], "release")
        self.assertNotIn("baseline", data)
        self.assertNotIn("backup_hash", data)


if __name__ == "__main__":
    unittest.main()
