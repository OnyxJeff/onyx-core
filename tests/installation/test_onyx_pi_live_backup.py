#!/usr/bin/env python3
"""Offline-only transactional backup tests; only temporary SQLite fixtures."""
import importlib.util
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'tools/installation/pi/onyx_pi_live_backup.py'
spec = importlib.util.spec_from_file_location('onyx_pi_live_backup', SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class PiBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_dir = self.root/'source'
        self.source_dir.mkdir()
        self.source = self.source_dir/'telemetry.db'
        self.parent = self.root/'backups'
        self.parent.mkdir()
        self.conn = sqlite3.connect(self.source)
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('CREATE TABLE telemetry (id INTEGER PRIMARY KEY, data TEXT NOT NULL)')
        self.conn.execute("INSERT INTO telemetry(data) VALUES ('before')")
        self.conn.commit()
        self.addCleanup(self.conn.close)

    def test_preview_is_nonmutating(self):
        result=mod.create_backup(self.source,self.parent,'v090-00000001',apply=False)
        self.assertEqual('PREVIEW_ONLY',result['status'])
        self.assertEqual([],list(self.parent.iterdir()))

    def test_wal_consistent_backup_remains_unchanged_after_future_writes(self):
        result=mod.create_backup(self.source,self.parent,'v090-00000002',apply=True)
        self.assertEqual('BACKUP_VERIFIED',result['status'])
        snapshot = self.parent/'v090-00000002'
        self.conn.execute("INSERT INTO telemetry(data) VALUES ('after')")
        self.conn.commit()
        # immutable, read-only connection never creates WAL/SHM files and is
        # explicitly closed before TemporaryDirectory cleanup on Windows.
        with closing(sqlite3.connect(
            (snapshot / 'telemetry.db').as_uri() + '?mode=ro&immutable=1', uri=True
        )) as snapshot_reader:
            self.assertEqual(1, snapshot_reader.execute(
                'SELECT COUNT(*) FROM telemetry').fetchone()[0])
        self.assertEqual(['telemetry'],mod.inspect_backup(snapshot)['sqlite']['tables'])

    def test_no_overwrite(self):
        mod.create_backup(self.source,self.parent,'v090-00000003',apply=True)
        with self.assertRaises(mod.Refused):
            mod.create_backup(self.source,self.parent,'v090-00000003',apply=True)

    def test_tamper_refuses_verification(self):
        mod.create_backup(self.source,self.parent,'v090-00000004',apply=True)
        snapshot=self.parent/'v090-00000004'
        with (snapshot/'telemetry.db').open('ab') as stream:stream.write(b'tampered')
        with self.assertRaises(mod.Refused):mod.inspect_backup(snapshot)

    def test_source_symlink_refused(self):
        linkdir=self.root/'redirect'
        try:linkdir.symlink_to(self.source_dir,target_is_directory=True)
        except (OSError,NotImplementedError):self.skipTest('symlinks unavailable')
        with self.assertRaises(mod.Refused):
            mod.create_backup(linkdir/'telemetry.db',self.parent,'v090-00000005',apply=True)

    def test_wrong_backup_id_refused(self):
        with self.assertRaises(mod.Refused):
            mod.create_backup(self.source,self.parent,'../evil',apply=True)

if __name__=='__main__':unittest.main(verbosity=2)
