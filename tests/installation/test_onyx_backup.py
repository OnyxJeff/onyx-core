#!/usr/bin/env python3
"""Six targeted nonproduction SQLite snapshot and recovery checks."""
import importlib.util, os, sqlite3, tempfile, unittest, uuid
from pathlib import Path

src=Path(__file__).resolve().parents[2]/'tools/installation/common/onyx_backup.py'
spec=importlib.util.spec_from_file_location('onyx_backup',src)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class BackupTests(unittest.TestCase):
    def setUp(self):
        self.source=Path(tempfile.gettempdir())/('OnyxV090-'+uuid.uuid4().hex)
        self.source.mkdir()
        self.backup=Path(tempfile.gettempdir())/('OnyxV090-'+uuid.uuid4().hex)
        self.restore=Path(tempfile.gettempdir())/('OnyxV090-'+uuid.uuid4().hex)
        self.connection=sqlite3.connect(self.source/'telemetry.db')
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.execute('CREATE TABLE metrics (value INTEGER)')
        self.connection.execute('INSERT INTO metrics VALUES (41)')
        self.connection.commit()
    def tearDown(self):
        self.connection.close()
        for p in (self.source,self.backup,self.restore):
            if p.exists():import_shutil.rmtree(p)
    def test_preview_does_not_write(self):
        result=m.backup(self.source,self.backup,['telemetry.db'])
        self.assertEqual('PREVIEW',result['status'])
        self.assertFalse(self.backup.exists())
    def test_wal_aware_consistent_backup_and_isolated_restore(self):
        m.backup(self.source,self.backup,['telemetry.db'],apply=True)
        self.assertEqual(1,len(m.inspect_backup(self.backup)['files']))
        self.connection.execute('INSERT INTO metrics VALUES (99)')
        self.connection.commit()
        m.restore(self.backup,self.restore,apply=True)
        db=sqlite3.connect(self.restore/'telemetry.db')
        try:self.assertEqual([(41,)],db.execute('SELECT value FROM metrics').fetchall())
        finally:db.close()
        self.assertEqual([(41,),(99,)],self.connection.execute('SELECT value FROM metrics').fetchall())
    def test_tampered_snapshot_refused_before_restore(self):
        m.backup(self.source,self.backup,['telemetry.db'],apply=True)
        with (self.backup/'telemetry.db').open('ab') as f:f.write(b'tamper')
        with self.assertRaises(m.Refused):m.restore(self.backup,self.restore,apply=True)
        self.assertFalse(self.restore.exists())
    def test_existing_backup_never_overwritten(self):
        self.backup.mkdir()
        with self.assertRaises(m.Refused):m.backup(self.source,self.backup,['telemetry.db'],apply=True)
        self.assertEqual([],list(self.backup.iterdir()))
    def test_outside_temp_refused(self):
        with self.assertRaises(m.Refused):m.backup(self.source,Path(self.source.parent.parent)/'NotAnOnyxBackup',['telemetry.db'],apply=True)
    def test_traversal_and_non_db_refused(self):
        with self.assertRaises(m.Refused):m.backup(self.source,self.backup,['../telemetry.db'],apply=True)
        with self.assertRaises(m.Refused):m.backup(self.source,self.backup,['collector-token.dpapi'],apply=True)

import shutil as import_shutil
if __name__=='__main__':unittest.main(verbosity=2)
