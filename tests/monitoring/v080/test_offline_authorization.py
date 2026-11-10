"""M2B authorization decisions: simulation-only, no Windows identity/ACL access."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

MONITOR = Path(__file__).resolve().parents[3] / 'windows' / 'monitoring' / 'v080'
if str(MONITOR) not in sys.path:
    sys.path.insert(0, str(MONITOR))

import OnyxOfflineAuthorization as auth
import OnyxUnattendedPolicy as m1

ACCOUNT = r"SQUALL\jmay2"
SID = "S-1-5-21-101-202-303-1001"
COMMIT = "6fb4001a9b270a0631be129aa1310335c36f7970"
COMPONENT = "a" * 64


def encode(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def build():
    config = json.loads((MONITOR / "monitoring.unattended.example.json").read_text(encoding="utf-8"))
    config["enabled"] = True  # In-memory test data ONLY; never alter checked-in file.
    cr = encode(config)
    enrollment = {
        "schema_version": 1,
        "approval_scope": m1.SCOPE,
        "approved_account": ACCOUNT,
        "source_commit_sha": COMMIT,
        "config_sha256": sha(cr),
        "approved_at_utc": "2026-11-10T12:00:00Z",
        "operator_approved": True,
        "read_only": True,
        "repair_action": "None",
    }
    er = encode(enrollment)
    revocation = {
        "schema_version": 1,
        "grant_sha256": sha(er),
        "generation": 5,
        "revoked": False,
        "reason": "None",
    }
    roles = {}
    for role in auth.ROLES:
        roles[role] = {
            "path": "C:\\Simulated\\OnyxCore-v080\\" + role,
            "owner_sid": SID,
            "write_sids": [SID, "S-1-5-18", "S-1-5-32-544"],
            "dacl_checked": True,
            "redirected": False,
            "inherited_untrusted_write": False,
        }
    facts = {
        "schema_version": 1,
        "simulation_only": True,
        "identity": {
            "account": ACCOUNT,
            "sid": SID,
            "authenticated": True,
            "interactive": True,
            "session": "LoggedOnUserOnly",
        },
        "source": {
            "branch": "feature/v0.8.0-continuous-monitoring",
            "commit_sha": COMMIT,
            "clean": True,
            "observed_component_sha256": COMPONENT,
            "approved_component_sha256": COMPONENT,
            "source_path_redirected": False,
        },
        "acl_paths": roles,
        "approval": {
            "operator_consent_observed": True,
            "enrollment_sha256": sha(er),
            "config_sha256": sha(cr),
        },
        "revocation_floor": 5,
    }
    return config, enrollment, revocation, facts


class OfflineAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.c, self.e, self.r, self.f = build()

    def decide(self):
        return auth.assess_simulated_preflight(encode(self.c), encode(self.e),
                                               encode(self.r), encode(self.f))

    def rejected(self):
        with self.assertRaises(auth.OfflineAuthorizationError):
            self.decide()

    def test_positive_is_data_only_never_runtime(self):
        v = self.decide()
        self.assertEqual(v["simulated_preflight"], "EligibleDataOnly")
        self.assertTrue(v["simulation_only"])
        for name in ("runtime_enabled", "live_probe_authorized", "task_creation_authorized",
                     "store_modified", "identity_authenticated_in_windows",
                     "windows_acls_verified", "revocation_authoritative"):
            self.assertIs(v[name], False)
        self.assertEqual(v["repair_action"], "None")

    def test_account_case_insensitive_binding(self):
        self.f["identity"]["account"] = ACCOUNT.lower()
        self.assertEqual(self.decide()["simulated_preflight"], "EligibleDataOnly")

    def test_disabled_config_refused(self):
        self.c["enabled"] = False
        self.rejected()

    def test_changed_config_refused_even_if_facts_claim_approval(self):
        self.c["schedule"]["interval_seconds"] = 90
        self.rejected()

    def test_fake_matching_approval_is_not_live_authorization(self):
        self.assertIs(self.decide()["live_probe_authorized"], False)

    def test_changed_enrollment_after_consent_refused(self):
        self.e["approved_at_utc"] = "2026-11-10T13:00:00Z"
        self.rejected()

    def test_no_independent_consent_refused(self):
        self.f["approval"]["operator_consent_observed"] = False
        self.rejected()

    def test_consent_wrong_grant_hash_refused(self):
        self.f["approval"]["enrollment_sha256"] = "b" * 64
        self.rejected()

    def test_consent_wrong_config_hash_refused(self):
        self.f["approval"]["config_sha256"] = "b" * 64
        self.rejected()

    def test_account_mismatch_refused(self):
        self.f["identity"]["account"] = r"SQUALL\other"
        self.rejected()

    def test_unverified_identity_refused(self):
        self.f["identity"]["authenticated"] = False
        self.rejected()

    def test_noninteractive_identity_refused(self):
        self.f["identity"]["interactive"] = False
        self.rejected()

    def test_session_mismatch_refused(self):
        self.f["identity"]["session"] = "Service"
        self.rejected()

    def test_fake_identity_bool_refused(self):
        self.f["identity"]["authenticated"] = 1
        self.rejected()

    def test_invalid_sid_refused(self):
        self.f["identity"]["sid"] = "S-1-5-32-545"
        self.rejected()

    def test_unexpected_identity_field_refused(self):
        self.f["identity"]["administrator"] = True
        self.rejected()

    def test_source_commit_mismatch_refused(self):
        self.f["source"]["commit_sha"] = "b" * 40
        self.rejected()

    def test_dirty_source_refused(self):
        self.f["source"]["clean"] = False
        self.rejected()

    def test_source_redirect_refused(self):
        self.f["source"]["source_path_redirected"] = True
        self.rejected()

    def test_source_branch_mismatch_refused(self):
        self.f["source"]["branch"] = "main"
        self.rejected()

    def test_source_digest_mismatch_refused(self):
        self.f["source"]["observed_component_sha256"] = "b" * 64
        self.rejected()

    def test_source_nonboolean_clean_refused(self):
        self.f["source"]["clean"] = 1
        self.rejected()

    def test_removed_acl_role_refused(self):
        del self.f["acl_paths"]["ssh"]
        self.rejected()

    def test_untrusted_acl_writer_everyone_refused(self):
        self.f["acl_paths"]["state"]["write_sids"].append("S-1-1-0")
        self.rejected()

    def test_untrusted_acl_writer_users_refused(self):
        self.f["acl_paths"]["python"]["write_sids"].append("S-1-5-32-545")
        self.rejected()

    def test_duplicate_acl_writer_refused(self):
        self.f["acl_paths"]["python"]["write_sids"].append(SID)
        self.rejected()

    def test_bad_acl_owner_refused(self):
        self.f["acl_paths"]["worktree"]["owner_sid"] = "S-1-5-32-545"
        self.rejected()

    def test_redirected_acl_path_refused(self):
        self.f["acl_paths"]["enrollment"]["redirected"] = True
        self.rejected()

    def test_unchecked_dacl_refused(self):
        self.f["acl_paths"]["config"]["dacl_checked"] = False
        self.rejected()

    def test_untrusted_inherited_writer_refused(self):
        self.f["acl_paths"]["revocation"]["inherited_untrusted_write"] = True
        self.rejected()

    def test_duplicate_acl_path_refused(self):
        self.f["acl_paths"]["revocation"]["path"] = self.f["acl_paths"]["enrollment"]["path"]
        self.rejected()

    def test_windows_parent_traversal_refused(self):
        self.f["acl_paths"]["worktree"]["path"] = r"C:\Simulated\..\OnyxCore-v080\worktree"
        self.rejected()

    def test_windows_unc_path_refused(self):
        self.f["acl_paths"]["worktree"]["path"] = r"\\other\share\OnyxCore-v080"
        self.rejected()

    def test_windows_v070_path_refused(self):
        self.f["acl_paths"]["state"]["path"] = r"C:\Simulated\OnyxCore-v070-Release\Monitoring"
        self.rejected()

    def test_windows_alternate_stream_refused(self):
        self.f["acl_paths"]["config"]["path"] += ":evil"
        self.rejected()

    def test_revoked_grant_refused(self):
        self.r["revoked"] = True
        self.r["reason"] = "Operator revoked"
        self.rejected()

    def test_revocation_missing_refused(self):
        with self.assertRaises(auth.OfflineAuthorizationError):
            auth.assess_simulated_preflight(encode(self.c), encode(self.e), b"", encode(self.f))

    def test_stale_revocation_generation_refused(self):
        self.r["generation"] = 4
        self.rejected()

    def test_revocation_floor_changed_refused(self):
        self.f["revocation_floor"] = 6
        self.rejected()

    def test_revocation_generation_bool_refused(self):
        self.r["generation"] = True
        self.rejected()

    def test_revocation_grant_digest_mismatch_refused(self):
        self.r["grant_sha256"] = "b" * 64
        self.rejected()

    def test_revocation_no_reason_with_not_revoked_refused(self):
        self.r["reason"] = "old approval"
        self.rejected()

    def test_revocation_extra_field_refused(self):
        self.r["arbitrary_allow"] = True
        self.rejected()

    def test_revocation_duplicate_json_property_refused(self):
        raw = encode(self.r).replace(b'"schema_version":1',
                                     b'"schema_version":1,"schema_version":1')
        with self.assertRaises(auth.OfflineAuthorizationError):
            auth.assess_simulated_preflight(encode(self.c), encode(self.e), raw, encode(self.f))

    def test_invalid_utf8_fact_refused(self):
        with self.assertRaises(auth.OfflineAuthorizationError):
            auth.assess_simulated_preflight(encode(self.c), encode(self.e),
                                              encode(self.r), b"\xff")

    def test_oversized_facts_refused(self):
        with self.assertRaises(auth.OfflineAuthorizationError):
            auth.assess_simulated_preflight(encode(self.c), encode(self.e),
                                              encode(self.r), b" " * (auth.MAX_FACTS_BYTES + 1))

    def test_unexpected_fact_field_refused(self):
        self.f["real_access"] = True
        self.rejected()

    def test_false_simulation_flag_refused(self):
        self.f["simulation_only"] = False
        self.rejected()

    def test_fixture_read_only_in_temporary_directory(self):
        with tempfile.TemporaryDirectory(prefix=auth.FIXTURE_PREFIX) as td:
            directory = Path(td)
            inputs = {
                "config.json": encode(self.c),
                "enrollment.json": encode(self.e),
                "revocation.json": encode(self.r),
                "facts.json": encode(self.f),
            }
            for name, data in inputs.items():
                (directory / name).write_bytes(data)
            before = {p.name: sha(p.read_bytes()) for p in directory.iterdir()}
            with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("spawned")):
                value = auth.assess_temporary_fixture(directory)
            after = {p.name: sha(p.read_bytes()) for p in directory.iterdir()}
            self.assertEqual(before, after)
            self.assertEqual(value["simulated_preflight"], "EligibleDataOnly")

    def test_missing_fixture_file_refused(self):
        with tempfile.TemporaryDirectory(prefix=auth.FIXTURE_PREFIX) as td:
            with self.assertRaises(auth.OfflineAuthorizationError):
                auth.assess_temporary_fixture(Path(td))

    def test_fixture_rejects_unapproved_directory(self):
        with tempfile.TemporaryDirectory(prefix="unrelated-") as td:
            with self.assertRaises(auth.OfflineAuthorizationError):
                auth.assess_temporary_fixture(Path(td))

    def test_revocation_floor_boolean_refused(self):
        self.f["revocation_floor"] = True
        self.rejected()

    def test_revocation_generation_decrease_after_approval_refused(self):
        self.r["generation"] = 2
        self.rejected()

    def test_acl_path_relative_refused(self):
        self.f["acl_paths"]["ssh"]["path"] = r"Simulated\ssh"
        self.rejected()

    def test_acl_path_unverified_writer_list_refused(self):
        self.f["acl_paths"]["config"]["write_sids"] = "S-1-5-18"
        self.rejected()

    def test_missing_enrollment_bytes_refused(self):
        with self.assertRaises(auth.OfflineAuthorizationError):
            auth.assess_simulated_preflight(encode(self.c), b"", encode(self.r), encode(self.f))

    def test_temp_fixture_rejects_extra_file(self):
        with tempfile.TemporaryDirectory(prefix=auth.FIXTURE_PREFIX) as td:
            (Path(td) / "intrusion.txt").write_text("not allowed", encoding="utf-8")
            with self.assertRaises(auth.OfflineAuthorizationError):
                auth.assess_temporary_fixture(Path(td))

    def test_temp_fixture_refuses_oversized_config(self):
        with tempfile.TemporaryDirectory(prefix=auth.FIXTURE_PREFIX) as td:
            directory = Path(td)
            values = {"config.json": b"X" * (m1.MAX_CONFIG_BYTES + 2),
                      "enrollment.json": encode(self.e),
                      "revocation.json": encode(self.r),
                      "facts.json": encode(self.f)}
            for name, raw in values.items():
                (directory / name).write_bytes(raw)
            with self.assertRaises(auth.OfflineAuthorizationError):
                auth.assess_temporary_fixture(directory)

    def test_fixture_rejects_redirected_directory(self):
        with tempfile.TemporaryDirectory(prefix=auth.FIXTURE_PREFIX) as td:
            with mock.patch.object(auth.Path, "is_junction", create=True, return_value=True):
                with self.assertRaises(auth.OfflineAuthorizationError):
                    auth.assess_temporary_fixture(Path(td))

    def test_cli_inert(self):
        module = MONITOR / "OnyxOfflineAuthorization.py"
        result = subprocess.run([sys.executable, "-I", "-B", str(module), "--check-inert"],
                                capture_output=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        value = json.loads(result.stdout)
        self.assertFalse(value["runtime_enabled"])
        self.assertFalse(value["live_probe_authorized"])
        self.assertFalse(value["identity_authenticated_in_windows"])

    def test_cli_refuses_live_and_fixture_execution(self):
        module = MONITOR / "OnyxOfflineAuthorization.py"
        for arg in ("--live-read-only", "--enroll", "--run", "--fixture", "--revoke"):
            with self.subTest(arg=arg):
                result = subprocess.run([sys.executable, "-I", "-B", str(module), arg],
                                        capture_output=True, timeout=5, check=False)
                self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
