"""R1 adversarial tests: synthetic-only; no Windows, network, tasks or protected stores."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "windows" / "monitoring" / "v080" / "OnyxOfflineWindowsTrustContract.py"
spec = importlib.util.spec_from_file_location("onyx_r1_offline_trust", MODULE)
r1 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(r1)
SID = "S-1-5-21-123456789-987654321-12345678-1001"
T0 = datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def serialize(obj):
    return (json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def chain(path):
    prefixes = r1.prefixes(path)
    result = []
    for p in prefixes:
        result.append({
            "path": p,
            "volume_id": hashlib.sha256(path[0].lower().encode()).hexdigest()[:8],
            "file_id": hashlib.sha256(p.casefold().encode()).hexdigest()[:32],
            "reparse_tag": 0, "dacl_examined": True,
            "owner_sid": "S-1-5-18",
            "effective_writers": ["S-1-5-18", SID],
            "inherited_untrusted_write": False,
        })
    return {"path": path, "final_path": path, "source_handle_stable": True,
            "components": result}


def fixture():
    paths = {
        "worktree": r"D:\github_repos\onyx-core-v080",
        "config": r"D:\github_repos\onyx-core-v080\windows\monitoring\v080\monitoring.unattended.example.json",
        "enrollment": r"C:\Users\Operator\AppData\Local\OnyxCore-v080\Monitoring\enrollment.json",
        "revocation": r"C:\Users\Operator\AppData\Local\OnyxCore-v080\Monitoring\revocation.json",
        "state": r"C:\Users\Operator\AppData\Local\OnyxCore-v080\Monitoring\state.json",
        "python": r"C:\Python313\python.exe",
        "ssh": r"C:\Users\Operator\.ssh\onyxcore_monitor_ed25519",
    }
    grant = {
        "schema_version": 1, "simulation_only": True, "approval_method": "SyntheticOnly",
        "grant_id": "fake-grant-1234", "approved_account": r"SQUALL\operator",
        "approved_sid": SID, "source_commit": "8" * 40,
        "tree_sha256": "a" * 64, "config_sha256": "b" * 64,
        "generation_floor": 3, "expires_utc": iso(T0 + timedelta(days=1)),
        "paths": paths,
    }
    before = {
        "schema_version": 1, "simulation_only": True,
        "mock_provider": "SyntheticWindowsTrustProvider", "sequence": 1,
        "captured_at_utc": iso(T0),
        "token": {"account": grant["approved_account"], "sid": SID,
                  "session_id": 1, "logon_type": "Interactive",
                  "is_elevated": False, "windows_authenticated": False,
                  "claim_origin": "SyntheticFixture"},
        "source": {"branch": r1.BRANCH, "commit": grant["source_commit"],
                   "tree_sha256": grant["tree_sha256"], "config_sha256": grant["config_sha256"],
                   "clean": True, "source_handle_stable": True},
        "paths": {name: chain(path) for name, path in paths.items()},
        "consent": {"grant_id": grant["grant_id"], "approved_digest": grant["config_sha256"],
                    "approved_by_windows": False},
        "revocation": {"grant_id": grant["grant_id"], "generation": 3,
                       "revoked": False, "authoritative": False},
    }
    after = copy.deepcopy(before)
    after["sequence"] = 2
    after["captured_at_utc"] = iso(T0 + timedelta(seconds=5))
    return grant, before, after


class R1WindowsTrustTests(unittest.TestCase):
    def setUp(self):
        self.grant, self.before, self.after = fixture()

    def evaluate(self):
        return r1.assess_synthetic_trust(serialize(self.grant), serialize(self.before),
                                         serialize(self.after))

    def refused(self):
        with self.assertRaises(r1.OfflineTrustError):
            self.evaluate()

    def both(self, callback):
        callback(self.before)
        callback(self.after)

    def test_mock_valid_but_no_live_authority(self):
        result = self.evaluate()
        self.assertTrue(result["simulation_only"])
        for key in ("runtime_enabled", "identity_authenticated_in_windows", "windows_acls_verified",
                    "revocation_authoritative", "live_probe_authorized", "task_creation_authorized",
                    "enrollment_authorized", "notification_enabled", "delivery_permitted", "store_modified"):
            self.assertIs(result[key], False)
        self.assertEqual(result["repair_action"], "None")

    def test_mock_identical_response(self):
        self.assertEqual(self.evaluate(), self.evaluate())

    def test_no_input_mutation(self):
        old = copy.deepcopy((self.grant, self.before, self.after))
        self.evaluate()
        self.assertEqual((self.grant, self.before, self.after), old)

    def test_cli_only_check_inert(self):
        proc = subprocess.run([sys.executable, "-I", "-B", str(MODULE), "--check-inert"],
                              capture_output=True, text=True, timeout=5)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), self.evaluate())

    def test_cli_refuses_live_flags(self):
        for args in ([], ["--live"], ["--check-inert", "--enroll"], ["--check-inert", "--probe"]):
            with self.subTest(args=args):
                p = subprocess.run([sys.executable, "-I", "-B", str(MODULE)] + args,
                                   capture_output=True, text=True, timeout=5)
                self.assertNotEqual(p.returncode, 0)

    def test_source_never_windows_api(self):
        source = MODULE.read_text(encoding="utf-8")
        import ast
        parsed = ast.parse(source)
        roots = {a.name.split(".")[0] for node in ast.walk(parsed)
                 if isinstance(node, ast.Import) for a in node.names}
        roots |= {node.module.split(".")[0] for node in ast.walk(parsed)
                  if isinstance(node, ast.ImportFrom) and node.module}
        for forbidden in ("subprocess", "ctypes", "winreg", "socket", "os", "pathlib",
                          "requests", "urllib", "shutil", "tempfile"):
            self.assertNotIn(forbidden, roots)

    def test_bad_grant_schema(self):
        self.grant["schema_version"] = True
        self.refused()

    def test_unknown_grant_property(self):
        self.grant["allow_live"] = True
        self.refused()

    def test_simulation_cannot_be_false(self):
        self.grant["simulation_only"] = False
        self.refused()

    def test_fake_real_approval_method_refused(self):
        self.grant["approval_method"] = "WindowsVerified"
        self.refused()

    def test_invalid_grant_id(self):
        self.grant["grant_id"] = "x"
        self.refused()

    def test_invalid_account(self):
        self.grant["approved_account"] = "operator"
        self.refused()

    def test_invalid_sid(self):
        self.grant["approved_sid"] = "S-1-5-18"
        self.refused()

    def test_invalid_source_commit(self):
        self.grant["source_commit"] = "v0.8.0"
        self.refused()

    def test_invalid_source_sha(self):
        self.grant["tree_sha256"] = "A" * 64
        self.refused()

    def test_invalid_config_sha(self):
        self.grant["config_sha256"] = "f" * 63
        self.refused()

    def test_invalid_revocation_floor(self):
        self.grant["generation_floor"] = True
        self.refused()

    def test_revocation_floor_negative(self):
        self.grant["generation_floor"] = -1
        self.refused()

    def test_approval_expired(self):
        self.grant["expires_utc"] = iso(T0)
        self.refused()

    def test_no_grant_path_role_missing(self):
        del self.grant["paths"]["ssh"]
        self.refused()

    def test_extra_path_role_refused(self):
        self.grant["paths"]["launcher"] = r"C:\windows\system32\cmd.exe"
        self.refused()

    def test_worktree_path_mismatch(self):
        self.grant["paths"]["worktree"] = r"D:\github_repos\onyx-core"
        self.refused()

    def test_protected_v070_path_refused(self):
        self.grant["paths"]["enrollment"] = r"C:\OnyxCore-v070-Release\Monitoring\grant.json"
        self.refused()

    def test_python_change_refused(self):
        self.grant["paths"]["python"] = r"C:\Python312\python.exe"
        self.refused()

    def test_ssh_change_refused(self):
        self.grant["paths"]["ssh"] = r"C:\Users\Operator\.ssh\other_key"
        self.refused()

    def test_duplicate_grant_path_refused(self):
        self.grant["paths"]["revocation"] = self.grant["paths"]["enrollment"]
        self.refused()

    def test_bad_mock_provider(self):
        self.before["mock_provider"] = "WindowsAPI"
        self.refused()

    def test_snapshot_unknown_field(self):
        self.after["live_authorized"] = True
        self.refused()

    def test_snapshot_skipped_sequence(self):
        self.after["sequence"] = 3
        self.refused()

    def test_snapshot_sequence_bool(self):
        self.before["sequence"] = True
        self.refused()

    def test_snapshot_wrong_order(self):
        self.after["sequence"] = 1
        self.refused()

    def test_time_stale_or_reversed(self):
        self.after["captured_at_utc"] = iso(T0 - timedelta(seconds=1))
        self.refused()

    def test_time_over_budget(self):
        self.after["captured_at_utc"] = iso(T0 + timedelta(seconds=91))
        self.refused()

    def test_utc_offset_refused(self):
        self.before["captured_at_utc"] = "2026-11-10T14:00:00+00:00"
        self.refused()

    def test_invalid_date_refused(self):
        self.before["captured_at_utc"] = "2026-02-30T14:00:00Z"
        self.refused()

    def test_token_account_mismatch(self):
        self.both(lambda s: s["token"].__setitem__("account", r"SQUALL\other"))
        self.refused()

    def test_token_sid_mismatch(self):
        self.both(lambda s: s["token"].__setitem__("sid", "S-1-5-18"))
        self.refused()

    def test_token_windows_authenticated_claim_refused(self):
        self.both(lambda s: s["token"].__setitem__("windows_authenticated", True))
        self.refused()

    def test_token_noninteractive_refused(self):
        self.both(lambda s: s["token"].__setitem__("logon_type", "Service"))
        self.refused()

    def test_token_elevated_refused(self):
        self.both(lambda s: s["token"].__setitem__("is_elevated", True))
        self.refused()

    def test_token_session_zero_refused(self):
        self.both(lambda s: s["token"].__setitem__("session_id", 0))
        self.refused()

    def test_token_session_bool_refused(self):
        self.both(lambda s: s["token"].__setitem__("session_id", True))
        self.refused()

    def test_token_extra_field_refused(self):
        self.both(lambda s: s["token"].__setitem__("is_admin", True))
        self.refused()

    def test_token_changed_between_snapshots_refused(self):
        self.after["token"]["session_id"] = 3
        self.refused()

    def test_source_commit_mismatch(self):
        self.both(lambda s: s["source"].__setitem__("commit", "f" * 40))
        self.refused()

    def test_source_dirty(self):
        self.both(lambda s: s["source"].__setitem__("clean", False))
        self.refused()

    def test_source_tree_digest_mismatch(self):
        self.both(lambda s: s["source"].__setitem__("tree_sha256", "c" * 64))
        self.refused()

    def test_config_digest_mismatch(self):
        self.both(lambda s: s["source"].__setitem__("config_sha256", "d" * 64))
        self.refused()

    def test_source_handle_unstable(self):
        self.both(lambda s: s["source"].__setitem__("source_handle_stable", False))
        self.refused()

    def test_source_changed_during_check(self):
        self.after["source"]["tree_sha256"] = "c" * 64
        self.refused()

    def test_revocation_revoked(self):
        self.both(lambda s: s["revocation"].__setitem__("revoked", True))
        self.refused()

    def test_revocation_stale(self):
        self.both(lambda s: s["revocation"].__setitem__("generation", 2))
        self.refused()

    def test_revocation_bool_floor(self):
        self.both(lambda s: s["revocation"].__setitem__("generation", True))
        self.refused()

    def test_revocation_rollback_during_check(self):
        self.after["revocation"]["generation"] = 4
        self.refused()

    def test_authoritative_revocation_claim_refused(self):
        self.both(lambda s: s["revocation"].__setitem__("authoritative", True))
        self.refused()

    def test_revocation_grant_mismatch(self):
        self.both(lambda s: s["revocation"].__setitem__("grant_id", "fake-grant-other"))
        self.refused()

    def test_consent_claimed_windows_approved_refused(self):
        self.both(lambda s: s["consent"].__setitem__("approved_by_windows", True))
        self.refused()

    def test_consent_digest_mismatch(self):
        self.both(lambda s: s["consent"].__setitem__("approved_digest", "0" * 64))
        self.refused()

    def test_consent_grant_mismatch(self):
        self.both(lambda s: s["consent"].__setitem__("grant_id", "fake-grant-wrong"))
        self.refused()

    def test_path_changed_after_snapshot(self):
        self.after["paths"]["state"]["components"][-1]["file_id"] = "f" * 32
        self.refused()

    def test_path_symlink_reparse_refused(self):
        self.both(lambda s: s["paths"]["state"]["components"][3].__setitem__("reparse_tag", 0xA000000C))
        self.refused()

    def test_path_junction_reparse_refused(self):
        self.both(lambda s: s["paths"]["worktree"]["components"][2].__setitem__("reparse_tag", 0xA0000003))
        self.refused()

    def test_path_alternate_stream_refused(self):
        self.grant["paths"]["state"] += ":cache"
        self.refused()

    def test_path_unc_refused(self):
        self.grant["paths"]["state"] = r"\\host\share\state.json"
        self.refused()

    def test_path_device_prefix_refused(self):
        self.grant["paths"]["state"] = r"\\?\C:\Users\Operator\state.json"
        self.refused()

    def test_path_traversal_refused(self):
        self.grant["paths"]["state"] = r"C:\Users\Operator\AppData\Local\OnyxCore-v080\..\Monitoring\state.json"
        self.refused()

    def test_path_trailing_space_refused(self):
        self.grant["paths"]["state"] = r"C:\Users\Operator\AppData\Local\OnyxCore-v080\Monitoring \state.json"
        self.refused()

    def test_path_drive_relative_refused(self):
        self.grant["paths"]["state"] = r"C:Users\Operator\OnyxCore-v080\state.json"
        self.refused()

    def test_path_incomplete_ancestors_refused(self):
        self.both(lambda s: s["paths"]["config"]["components"].pop(-2))
        self.refused()

    def test_path_final_target_switch_refused(self):
        self.both(lambda s: s["paths"]["state"].__setitem__("final_path", r"C:\Temp\state.json"))
        self.refused()

    def test_path_file_id_duplicate_refused(self):
        self.both(lambda s: s["paths"]["state"]["components"][3].__setitem__("file_id", s["paths"]["state"]["components"][2]["file_id"]))
        self.refused()

    def test_path_volume_swap_refused(self):
        self.both(lambda s: s["paths"]["state"]["components"][-1].__setitem__("volume_id", "deadbeef"))
        self.refused()

    def test_path_untrusted_owner_refused(self):
        self.both(lambda s: s["paths"]["state"]["components"][-1].__setitem__("owner_sid", "S-1-5-32-545"))
        self.refused()

    def test_path_untrusted_writer_refused(self):
        self.both(lambda s: s["paths"]["state"]["components"][-1]["effective_writers"].append("S-1-5-32-545"))
        self.refused()

    def test_path_inherited_writable_ancestor_refused(self):
        self.both(lambda s: s["paths"]["state"]["components"][2].__setitem__("inherited_untrusted_write", True))
        self.refused()

    def test_path_unchecked_dacl_refused(self):
        self.both(lambda s: s["paths"]["worktree"]["components"][2].__setitem__("dacl_examined", False))
        self.refused()

    def test_path_duplicate_writer_refused(self):
        self.both(lambda s: s["paths"]["state"]["components"][-1]["effective_writers"].append(SID))
        self.refused()

    def test_path_unknown_component_field(self):
        self.both(lambda s: s["paths"]["state"]["components"][-1].__setitem__("link_target", "C:\\Temp"))
        self.refused()

    def test_path_unstable_handle_refused(self):
        self.both(lambda s: s["paths"]["state"].__setitem__("source_handle_stable", False))
        self.refused()

    def test_invalid_snapshot_json_duplicate_key(self):
        raw = b'{"schema_version":1,"schema_version":1}'
        with self.assertRaises(r1.OfflineTrustError):
            r1.assess_synthetic_trust(serialize(self.grant), raw, serialize(self.after))

    def test_invalid_utf8(self):
        with self.assertRaises(r1.OfflineTrustError):
            r1.assess_synthetic_trust(b"\xff", serialize(self.before), serialize(self.after))

    def test_nonfinite_json(self):
        with self.assertRaises(r1.OfflineTrustError):
            r1.assess_synthetic_trust(b'{"value":NaN}', serialize(self.before), serialize(self.after))

    def test_oversized_fixture(self):
        with self.assertRaises(r1.OfflineTrustError):
            r1.assess_synthetic_trust(b" " * (r1.MAX_BYTES + 1), serialize(self.before), serialize(self.after))

    def test_wrong_input_type(self):
        with self.assertRaises(r1.OfflineTrustError):
            r1.assess_synthetic_trust("not bytes", serialize(self.before), serialize(self.after))

    def test_no_actual_windows_symlink_claim(self):
        # This model exercises reparse-tag rejection only. The M2A privileged
        # host symlink-creation test stays OPEN until separately authorized.
        self.assertFalse(self.evaluate()["windows_acls_verified"])


if __name__ == "__main__":
    unittest.main()
