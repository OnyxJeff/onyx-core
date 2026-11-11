"""R3 offline synthetic SQLite journal tests; only test-owned temporary fixtures."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
MODULE_DIR = ROOT / "windows" / "monitoring" / "v080"
sys.path.insert(0, str(MODULE_DIR))
import OnyxOfflineIncidentJournal as r3

T0 = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
IID = "inc-" + "a" * 24
IID2 = "inc-" + "b" * 24


def stamp(t=0):
    return (T0 + timedelta(seconds=t)).isoformat(timespec="microseconds").replace("+00:00", "Z")


def event(kind="IncidentOpened", t=0, iid=IID, old="Unknown", new="Suspected",
          decision="WaitAndRetry"):
    when = stamp(t)
    digest_basis = "|".join((kind, when, iid or "none"))
    return {"schema_version": 1, "event_id": "evt-" + hashlib.sha256(digest_basis.encode()).hexdigest()[:24],
            "event_type": kind, "timestamp_utc": when, "incident_id": iid,
            "from_phase": old, "to_phase": new, "connectivity_decision": decision,
            "repair_action": "None"}


def opened(t=0, iid=IID, old="Unknown"):
    return event(t=t, iid=iid, old=old)


def escalated(t=40):
    return event("IncidentEscalated", t, old="Suspected", new="Active", decision="PossibleIcsFailure")


def recovered(t=100, phase="Active"):
    return event("IncidentRecovered", t, old=phase, new="Recovered", decision="Healthy")


def missing(t=50, phase="Active"):
    return event("EvidenceIncomplete", t, old=phase, new=phase, decision="Investigate")


def restored(t=60, phase="Active"):
    return event("EvidenceRestored", t, old=phase, new=phase, decision="Investigate")


def raw(*events, ref=180):
    return json.dumps({"schema_version": 1, "source": r3.m3.SOURCE,
                       "provenance": r3.m3.PROVENANCE, "reference_utc": stamp(ref),
                       "events": events}, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


class R3JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="onyx-r3-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / r3.DB_NAME
        r3.initialize_synthetic_store(self.root)

    def apply(self, *events, ref=180, **kwargs):
        return r3.ingest_synthetic_batch(self.root, raw(*events, ref=ref), **kwargs)

    def run_good_history(self):
        self.apply(opened(), escalated(), missing(), ref=180)
        self.apply(restored(), recovered(), ref=180)

    def sql(self, statement, params=()):
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(statement, params)
            conn.commit()
        finally:
            conn.close()

    def assert_inert(self, obj):
        self.assertIs(obj["simulation_only"], True)
        for field in ("runtime_enabled", "live_probe_authorized", "task_creation_authorized",
                      "notification_enabled", "enrollment_authorized", "delivery_permitted"):
            self.assertIs(obj[field], False)
        self.assertEqual(obj["repair_action"], "None")

    def test_cli_inert(self):
        proc = subprocess.run([sys.executable, "-I", "-B", str(MODULE_DIR / "OnyxOfflineIncidentJournal.py"),
                               "--check-inert"], capture_output=True, timeout=5)
        self.assertEqual(proc.returncode, 0)
        state = json.loads(proc.stdout)
        self.assert_inert(state)
        self.assertIs(state["store_modified"], False)
        self.assertIs(state["real_store_authorized"], False)
        self.assertIs(state["temp_fixture_only"], True)

    def test_cli_rejects_live_modes(self):
        for arg in ("--run", "--live", "--notify", "--persist", "--enroll", "--migrate",
                    "--production", "--repair", "--execute", "--fixture"):
            with self.subTest(arg=arg):
                proc = subprocess.run([sys.executable, "-I", "-B", str(MODULE_DIR / "OnyxOfflineIncidentJournal.py"),
                                       arg], capture_output=True, timeout=5)
                self.assertNotEqual(proc.returncode, 0)

    def test_initializer_state_unknown(self):
        state = r3.inspect_synthetic_store(self.root)
        self.assertEqual((state["durable_event_count"], state["durable_undelivered_intent_count"]), (0, 0))
        self.assertEqual(state["display_status"], "Unknown")
        self.assert_inert(state)
        self.assertFalse(state["store_modified"])

    def test_only_one_fixture_file(self):
        self.assertEqual({x.name for x in self.root.iterdir()}, {r3.DB_NAME})

    def test_valid_open_proposes_one_not_delivered(self):
        result = self.apply(opened())
        self.assertEqual(result["processed_new_events"], 1)
        self.assertEqual(len(result["proposed_intents_not_delivered"]), 1)
        self.assertFalse(result["proposed_intents_not_delivered"][0]["delivery_permitted"])
        self.assertEqual(result["display_status"], "Suspected")
        self.assert_inert(result)

    def test_good_transitions_integrity_and_counters(self):
        self.run_good_history()
        state = r3.inspect_synthetic_store(self.root)
        self.assertEqual(state["state"]["phase"], "Recovered")
        self.assertEqual(state["durable_event_count"], 5)
        self.assertEqual(state["durable_undelivered_intent_count"], 4)
        self.assert_inert(state)

    def test_duplicate_replay_is_read_only(self):
        self.apply(opened())
        original = self.db.read_bytes()
        result = self.apply(opened())
        self.assertEqual(result["processed_new_events"], 0)
        self.assertEqual(result["suppressed_duplicate_events"], 1)
        self.assertEqual(result["proposed_intents_not_delivered"], [])
        self.assertFalse(result["store_modified"])
        self.assertEqual(self.db.read_bytes(), original)

    def test_duplicate_in_same_batch(self):
        result = self.apply(opened(), opened())
        self.assertEqual(result["processed_new_events"], 1)
        self.assertEqual(result["suppressed_duplicate_events"], 1)
        self.assertEqual(r3.inspect_synthetic_store(self.root)["durable_event_count"], 1)

    def test_conflicting_digest_same_id_refused(self):
        self.apply(opened())
        bad = opened()
        bad["connectivity_decision"] = "Investigate"
        with self.assertRaises(r3.OfflineJournalError):
            self.apply(bad)
        self.assertEqual(r3.inspect_synthetic_store(self.root)["durable_event_count"], 1)

    def test_invalid_event_rejected_no_writes(self):
        baseline = self.db.read_bytes()
        with self.assertRaises(r3.OfflineJournalError):
            self.apply(event(kind="NotAnEvent"))
        self.assertEqual(self.db.read_bytes(), baseline)

    def test_unapproved_live_provenance_rejected(self):
        data = json.loads(raw(opened()))
        data["source"] = "real-windows"
        with self.assertRaises(r3.OfflineJournalError):
            r3.ingest_synthetic_batch(self.root, json.dumps(data).encode())

    def test_bad_json_rejected(self):
        for value in (b'not json', b'{"x":1,"x":2}', b'\xff'):
            with self.subTest(value=value), self.assertRaises(r3.OfflineJournalError):
                r3.ingest_synthetic_batch(self.root, value)

    def test_duplicate_json_property_in_batch_refused(self):
        data = raw(opened()).decode()
        duplicate = data.replace('"schema_version":1', '"schema_version":1,"schema_version":1', 1)
        with self.assertRaises(r3.OfflineJournalError):
            r3.ingest_synthetic_batch(self.root, duplicate.encode())

    def test_replayed_batch_reference_may_change_when_fresh(self):
        self.apply(opened(), ref=180)
        result = self.apply(opened(), ref=200)
        self.assertEqual(result["suppressed_duplicate_events"], 1)

    def test_duplicate_after_restart(self):
        self.apply(opened())
        reloaded = r3.inspect_synthetic_store(self.root)
        self.assertEqual(reloaded["durable_event_count"], 1)
        outcome = r3.ingest_synthetic_batch(self.root, raw(opened()))
        self.assertEqual(outcome["suppressed_duplicate_events"], 1)

    def test_restart_in_another_python_process(self):
        self.apply(opened())
        code = "import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[2]);import OnyxOfflineIncidentJournal as j;print(json.dumps(j.inspect_synthetic_store(Path(sys.argv[1]))))"
        p = subprocess.run([sys.executable, "-B", "-c", code, str(self.root), str(MODULE_DIR)],
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["durable_event_count"], 1)

    def test_repeated_intent_suppressed_persistently(self):
        self.apply(opened(), escalated(), missing(), ref=180)
        self.apply(restored(), missing(t=61), ref=180)
        state = r3.inspect_synthetic_store(self.root)
        self.assertEqual(state["durable_undelivered_intent_count"], 3)

    def test_replay_after_recovery_does_not_reopen(self):
        self.run_good_history()
        result = self.apply(opened())
        self.assertEqual(result["suppressed_duplicate_events"], 1)
        self.assertEqual(result["state"]["phase"], "Recovered")

    def test_new_incident_after_recovered(self):
        self.run_good_history()
        result = self.apply(opened(t=200, iid=IID2, old="Recovered"), ref=220)
        self.assertEqual(result["state"]["phase"], "Suspected")
        self.assertEqual(r3.inspect_synthetic_store(self.root)["durable_event_count"], 6)

    def test_open_evidence_loss_displays_unknown(self):
        self.apply(opened(), missing(t=45, phase="Suspected"))
        self.assertEqual(r3.inspect_synthetic_store(self.root)["display_status"], "Unknown")

    def test_failed_transition_atomic_no_intent(self):
        before = r3.inspect_synthetic_store(self.root)
        with self.assertRaises(r3.OfflineJournalError):
            self.apply(escalated())
        after = r3.inspect_synthetic_store(self.root)
        self.assertEqual(after, before)

    def test_mixed_valid_and_invalid_rolls_back_entire_batch(self):
        with self.assertRaises(r3.OfflineJournalError):
            self.apply(opened(), opened(t=100))
        self.assertEqual(r3.inspect_synthetic_store(self.root)["durable_event_count"], 0)

    def test_injected_rollback_leaves_no_durable_event(self):
        with self.assertRaises(r3.SyntheticFault):
            self.apply(opened(), inject_fault="before_commit")
        self.assertEqual(r3.inspect_synthetic_store(self.root)["durable_event_count"], 0)

    def test_rollback_allows_retry_once(self):
        with self.assertRaises(r3.SyntheticFault):
            self.apply(opened(), inject_fault="before_commit")
        result = self.apply(opened())
        self.assertEqual(result["processed_new_events"], 1)

    def test_lost_postcommit_confirmation_retry_suppressed(self):
        with self.assertRaises(r3.SyntheticFault):
            self.apply(opened(), inject_fault="after_commit")
        state = r3.inspect_synthetic_store(self.root)
        self.assertEqual(state["durable_undelivered_intent_count"], 1)
        replay = self.apply(opened())
        self.assertEqual(replay["suppressed_duplicate_events"], 1)
        self.assertEqual(r3.inspect_synthetic_store(self.root)["durable_undelivered_intent_count"], 1)

    def test_abrupt_process_exit_rolls_back_via_explicit_temp_recovery(self):
        import base64
        payload = base64.b64encode(raw(opened())).decode("ascii")
        code = ("import sys,base64;from pathlib import Path;"
                "sys.path.insert(0,sys.argv[2]);"
                "import OnyxOfflineIncidentJournal as j;"
                "j.ingest_synthetic_batch(Path(sys.argv[1]),base64.b64decode(sys.argv[3]),"
                "inject_fault='hard_exit_before_commit')")
        proc = subprocess.run([sys.executable, "-B", "-c", code, str(self.root),
                               str(MODULE_DIR), payload], capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 71, proc.stderr.decode(errors="replace"))
        # SQLite versions / Windows filesystems may remove a cold journal on
        # process exit, or retain it until an explicit test-only recovery.
        if (self.root / (r3.DB_NAME + "-journal")).exists():
            recovered = r3.recover_test_fixture_after_crash(self.root)
            self.assertTrue(recovered["recovered_synthetic_rollback"])
        else:
            recovered = r3.inspect_synthetic_store(self.root)
        self.assertEqual(recovered["durable_event_count"], 0)
        self.assertEqual(self.apply(opened())["processed_new_events"], 1)
        self.assertEqual(r3.inspect_synthetic_store(self.root)["durable_event_count"], 1)

    def test_explicit_recovery_refuses_clean_fixture(self):
        with self.assertRaises(r3.OfflineJournalError):
            r3.recover_test_fixture_after_crash(self.root)

    def test_unexpected_malformed_rollback_marker_refused(self):
        (self.root / (r3.DB_NAME + "-journal")).write_text("not a real journal")
        with self.assertRaises(r3.OfflineJournalError):
            r3.recover_test_fixture_after_crash(self.root)

    def test_bad_fault_token_refused(self):
        with self.assertRaises(r3.OfflineJournalError):
            self.apply(opened(), inject_fault="real")

    def test_event_capacity_fail_closed_no_prune(self):
        with mock.patch.object(r3, "MAX_EVENTS", 1):
            self.apply(opened())
            with self.assertRaises(r3.OfflineJournalError):
                self.apply(escalated())
        self.assertEqual(r3.inspect_synthetic_store(self.root)["durable_event_count"], 1)

    def test_intent_capacity_fail_closed(self):
        with mock.patch.object(r3, "MAX_INTENTS", 0):
            with self.assertRaises(r3.OfflineJournalError):
                self.apply(opened())
        self.assertEqual(r3.inspect_synthetic_store(self.root)["durable_event_count"], 0)

    def test_after_24_events_prior_id_still_suppressed(self):
        self.apply(opened())
        for index in range(13):
            t = 50 + index * 2
            self.apply(missing(t, "Suspected"), restored(t + 1, "Suspected"), ref=t + 130)
        state = r3.inspect_synthetic_store(self.root)
        self.assertEqual(state["durable_event_count"], 27)
        self.assertLessEqual(len(state["state"]["seen_events"]), 24)
        self.assertEqual(self.apply(opened())["suppressed_duplicate_events"], 1)

    def test_after_24_events_intent_remains_deduplicated(self):
        self.apply(opened())
        for index in range(13):
            t = 50 + index * 2
            self.apply(missing(t, "Suspected"), restored(t + 1, "Suspected"), ref=t + 130)
        state = r3.inspect_synthetic_store(self.root)
        self.assertEqual(state["durable_undelivered_intent_count"], 2)

    def test_no_delivery_status_ever_changes(self):
        self.run_good_history()
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual({row[0] for row in con.execute("SELECT delivery_status FROM intent_journal")},
                             {"NotAttempted"})
        finally:
            con.close()

    def test_inspect_does_not_modify_db(self):
        self.apply(opened())
        original = self.db.read_bytes()
        r3.inspect_synthetic_store(self.root)
        self.assertEqual(self.db.read_bytes(), original)

    def test_metadata_tamper_detected(self):
        self.apply(opened())
        self.sql("UPDATE meta SET next_seq=999")
        with self.assertRaises(r3.OfflineJournalError):
            r3.inspect_synthetic_store(self.root)

    def test_state_snapshot_tamper_detected(self):
        self.apply(opened())
        self.sql("UPDATE meta SET state_sha=?", ("f"*64,))
        with self.assertRaises(r3.OfflineJournalError):
            self.apply(opened())

    def test_event_digest_tamper_detected(self):
        self.apply(opened())
        self.sql("UPDATE event_journal SET event_sha=? WHERE seq=1", ("f"*64,))
        with self.assertRaises(r3.OfflineJournalError):
            r3.inspect_synthetic_store(self.root)

    def test_event_payload_tamper_detected(self):
        self.apply(opened())
        self.sql("UPDATE event_journal SET event_json='{}' WHERE seq=1")
        with self.assertRaises(r3.OfflineJournalError):
            r3.inspect_synthetic_store(self.root)

    def test_event_chain_tamper_detected(self):
        self.apply(opened())
        self.sql("UPDATE event_journal SET record_sha=? WHERE seq=1", ("f"*64,))
        with self.assertRaises(r3.OfflineJournalError):
            r3.inspect_synthetic_store(self.root)

    def test_event_previous_chain_tamper_detected(self):
        self.apply(opened())
        self.sql("UPDATE event_journal SET prev_sha=? WHERE seq=1", ("f"*64,))
        with self.assertRaises(r3.OfflineJournalError):
            r3.inspect_synthetic_store(self.root)

    def test_snapshot_after_tamper_detected(self):
        self.apply(opened())
        self.sql("UPDATE event_journal SET after_json='{}' WHERE seq=1")
        with self.assertRaises(r3.OfflineJournalError):
            r3.inspect_synthetic_store(self.root)

    def test_intent_body_tamper_detected(self):
        self.apply(opened())
        self.sql("UPDATE intent_journal SET intent_json='{}'")
        with self.assertRaises(r3.OfflineJournalError):
            r3.inspect_synthetic_store(self.root)

    def test_intent_status_cannot_change(self):
        self.apply(opened())
        with self.assertRaises(sqlite3.IntegrityError):
            self.sql("UPDATE intent_journal SET delivery_status='Sent'")
        self.assertEqual(r3.inspect_synthetic_store(self.root)["durable_undelivered_intent_count"], 1)

    def test_intent_row_missing_detected(self):
        self.apply(opened())
        self.sql("DELETE FROM intent_journal")
        with self.assertRaises(r3.OfflineJournalError):
            r3.inspect_synthetic_store(self.root)

    def test_intent_row_extra_detected(self):
        self.apply(opened())
        self.sql("INSERT INTO intent_journal VALUES (?,?,?,?,?,?)",
                 ("fake", 1, opened()["event_id"], "{}", "f"*64, "NotAttempted"))
        with self.assertRaises(r3.OfflineJournalError):
            r3.inspect_synthetic_store(self.root)

    def test_unknown_schema_version_detected(self):
        self.apply(opened())
        self.sql("PRAGMA user_version=99")
        with self.assertRaises(r3.OfflineJournalError):
            r3.inspect_synthetic_store(self.root)

    def test_unknown_application_id_detected(self):
        self.apply(opened())
        self.sql("PRAGMA application_id=0")
        with self.assertRaises(r3.OfflineJournalError):
            r3.inspect_synthetic_store(self.root)

    def test_sqlite_integrity_corruption_refused(self):
        self.apply(opened())
        self.db.write_bytes(b"not-a-sqlite-file")
        with self.assertRaises(r3.OfflineJournalError):
            r3.inspect_synthetic_store(self.root)

    def test_db_removed_refused_no_auto_init(self):
        self.db.unlink()
        with self.assertRaises(r3.OfflineJournalError):
            r3.inspect_synthetic_store(self.root)
        self.assertFalse(self.db.exists())

    def test_db_file_extra_refused(self):
        (self.root / "other.txt").write_text("do not auto-delete")
        with self.assertRaises(r3.OfflineJournalError):
            r3.inspect_synthetic_store(self.root)

    def test_path_not_a_path_refused(self):
        with self.assertRaises(r3.OfflineJournalError):
            r3.inspect_synthetic_store(str(self.root))

    def test_missing_folder_refused(self):
        with self.assertRaises(r3.OfflineJournalError):
            r3.inspect_synthetic_store(self.root / "missing")

    def test_nested_temp_folder_refused(self):
        nested = self.root / "onyx-r3-nested"
        nested.mkdir()
        with self.assertRaises(r3.OfflineJournalError):
            r3.initialize_synthetic_store(nested)

    def test_wrong_prefix_temp_folder_refused(self):
        with tempfile.TemporaryDirectory(prefix="not-onyx-") as directory:
            with self.assertRaises(r3.OfflineJournalError):
                r3.initialize_synthetic_store(Path(directory))

    def test_refuse_double_initialize_without_overwriting(self):
        original = self.db.read_bytes()
        with self.assertRaises(r3.OfflineJournalError):
            r3.initialize_synthetic_store(self.root)
        self.assertEqual(original, self.db.read_bytes())

    def test_symlink_fixture_is_never_accepted_if_created(self):
        target = Path(tempfile.gettempdir()) / ("onyx-r3-link-" + str(os.getpid()))
        try:
            target.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError):
            # Exercise the lexical name and nested-root rejection even where
            # Windows denies symlink creation. No extra test skip is introduced.
            with self.assertRaises(r3.OfflineJournalError):
                r3.inspect_synthetic_store(self.root / "not-a-direct-temp-dir")
            return
        try:
            with self.assertRaises(r3.OfflineJournalError):
                r3.inspect_synthetic_store(target)
        finally:
            target.unlink()

    def test_invalid_reference_date_refused(self):
        data = json.loads(raw(opened()))
        data["reference_utc"] = "no-date"
        with self.assertRaises(r3.OfflineJournalError):
            r3.ingest_synthetic_batch(self.root, json.dumps(data).encode())

    def test_backdated_new_unseen_event_refused(self):
        self.apply(opened(t=100), ref=180)
        with self.assertRaises(r3.OfflineJournalError):
            self.apply(event("EvidenceIncomplete", 50, old="Suspected", new="Suspected",
                             decision="Investigate"), ref=180)

    def test_wrong_event_payload_shape_rejected(self):
        data = opened()
        data["notify"] = True
        with self.assertRaises(r3.OfflineJournalError):
            self.apply(data)

    def test_no_implicit_cleanup_or_repair(self):
        self.apply(opened())
        self.assertEqual({x.name for x in self.root.iterdir()}, {r3.DB_NAME})
        self.assert_inert(r3.inspect_synthetic_store(self.root))

    def test_readonly_reader_rejects_any_insert(self):
        with r3._database(self.root, readonly=True) as conn:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("INSERT INTO event_journal (seq) VALUES (999)")

    def test_another_open_writer_lock_is_bounded(self):
        conn = sqlite3.connect(self.db, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            with self.assertRaises(r3.OfflineJournalError):
                self.apply(opened())
            self.assertEqual(conn.in_transaction, True)
        finally:
            conn.execute("ROLLBACK")
            conn.close()
        self.assertEqual(r3.inspect_synthetic_store(self.root)["durable_event_count"], 0)

    def test_retention_never_deletes_or_evictions(self):
        self.run_good_history()
        conn = sqlite3.connect(self.db)
        try:
            result = conn.execute("SELECT COUNT(*), COUNT(DISTINCT event_id) FROM event_journal").fetchone()
            self.assertEqual(result, (5, 5))
        finally:
            conn.close()

    def test_snapshot_is_detached_from_db(self):
        self.apply(opened())
        snapshot = r3.inspect_synthetic_store(self.root)
        snapshot["state"]["phase"] = "Active"
        self.assertEqual(r3.inspect_synthetic_store(self.root)["state"]["phase"], "Suspected")

    def test_no_automatic_external_network_imports(self):
        import ast
        tree = ast.parse((MODULE_DIR / "OnyxOfflineIncidentJournal.py").read_text(encoding="utf8"))
        forbidden = {"requests", "urllib", "http", "socket", "win32com", "subprocess", "ctypes"}
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        self.assertFalse(imports & forbidden)

    def test_no_touch_of_protected_history_literals(self):
        text = (MODULE_DIR / "OnyxOfflineIncidentJournal.py").read_text(encoding="utf8")
        self.assertNotIn("recovery-observations.json", text)
        self.assertNotIn("OnyxCore-v070-Release", text)
        self.assertNotIn("OnyxCore-v070-Development", text)


if __name__ == "__main__":
    unittest.main()
