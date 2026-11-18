#!/usr/bin/env python3
"""ONYX CORE v0.9.0: operator-approved, SQLite-consistent Pi backup.

Production CLI accepts ONLY the current ONYX CORE database and a preexisting,
root-owned backup parent. No service changes, no live restore, no credentials.
A separate sandbox API is used by offline unit tests. Preview never opens SQLite.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import stat
import sys
import tempfile

SOURCE = Path('/var/lib/onyxcore/telemetry.db')
BACKUP_PARENT = Path('/var/backups/onyxcore')
BACKUP_ID = re.compile(r'v090-[A-Za-z0-9_-]{8,64}\Z')
DATABASE_NAME = 'telemetry.db'
MANIFEST_NAME = 'snapshot-manifest.json'


class Refused(RuntimeError):
    pass


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


def _sha(path):
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def _no_redirects(path):
    current = path
    while True:
        if current.is_symlink():
            raise Refused('symlink/redirected path refused')
        if current.parent == current:
            break
        current = current.parent


def _check_source(source):
    if not source.is_absolute() or '..' in source.parts:
        raise Refused('absolute SQLite source required')
    _no_redirects(source)
    if not source.is_file() or source.name != DATABASE_NAME:
        raise Refused('expected telemetry.db source missing')
    if source.stat().st_size < 100:
        raise Refused('database suspiciously small')


def _check_parent(parent, *, production):
    if not parent.is_absolute() or '..' in parent.parts:
        raise Refused('absolute backup parent required')
    _no_redirects(parent)
    if not parent.is_dir():
        raise Refused('backup parent must exist before invocation')
    if production:
        if parent != BACKUP_PARENT or os.geteuid() != 0 or platform.machine().lower() != 'armv6l':
            raise Refused('approved root-only ARMv6 backup parent required')
        info = parent.stat()
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
            raise Refused('backup parent must be root-owned mode 0700')


def _verify_sqlite(database):
    # immutable opens a completed independent snapshot without making WAL/SHM.
    connection = sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        if connection.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise Refused('SQLite integrity_check failed')
        tables = sorted(row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
        if not tables:
            raise Refused('backup database has no application tables')
        user_version = int(connection.execute('PRAGMA user_version').fetchone()[0])
    finally:
        connection.close()
    return {'tables': tables, 'user_version': user_version}


def inspect_backup(folder):
    folder = Path(folder)
    _no_redirects(folder)
    if not folder.is_dir():
        raise Refused('backup directory missing')
    if set(p.name for p in folder.iterdir()) != {DATABASE_NAME, MANIFEST_NAME}:
        raise Refused('unexpected backup directory contents')
    raw = (folder / MANIFEST_NAME).read_bytes()
    doc = json.loads(raw)
    if type(doc) is not dict or set(doc) != {
        'schema_version', 'kind', 'source', 'created_utc', 'database', 'sqlite'}:
        raise Refused('incorrect backup manifest schema')
    if doc['schema_version'] != 1 or doc['kind'] != 'onyx-v090-pi-sqlite-backup' or doc['source'] != str(SOURCE):
        raise Refused('incorrect backup identity')
    entry = doc['database']
    if type(entry) is not dict or set(entry) != {'name', 'size', 'sha256'} or entry['name'] != DATABASE_NAME:
        raise Refused('incorrect backup file inventory')
    db = folder / DATABASE_NAME
    _no_redirects(db)
    _no_redirects(folder / MANIFEST_NAME)
    if type(entry['size']) is not int or entry['size'] < 100 or db.stat().st_size != entry['size']:
        raise Refused('backup size mismatch')
    if type(entry['sha256']) is not str or not re.fullmatch('[a-f0-9]{64}', entry['sha256']) or _sha(db) != entry['sha256']:
        raise Refused('backup SHA256 mismatch')
    if type(doc['created_utc']) is not str or type(doc['sqlite']) is not dict or _canonical(doc) != raw:
        raise Refused('noncanonical or invalid receipt')
    if _verify_sqlite(db) != doc['sqlite']:
        raise Refused('backup SQLite inventory mismatch')
    return doc


def create_backup(source, parent, backup_id, *, apply=False, production=False):
    source = Path(source)
    parent = Path(parent)
    if not BACKUP_ID.fullmatch(backup_id):
        raise Refused('invalid backup ID')
    _check_source(source)
    _check_parent(parent, production=production)
    destination = parent / backup_id
    _no_redirects(destination)
    if destination.exists() or destination.is_symlink():
        raise Refused('existing backup cannot be overwritten')
    if not apply:
        return {'status': 'PREVIEW_ONLY', 'source': str(source), 'destination': str(destination),
                'writes': False, 'services_changed': False}
    # Create a private temporary directory next to the destination, and rename
    # only a verified SQLite-consistent snapshot into its final location.
    temporary = Path(tempfile.mkdtemp(prefix='.onyx-v090-backup-', dir=str(parent)))
    os.chmod(temporary, 0o700)
    try:
        target = temporary / DATABASE_NAME
        # Mode=ro means source cannot be modified through this connection.
        reader = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=10)
        writer = sqlite3.connect(str(target), timeout=10)
        try:
            reader.backup(writer, pages=100, sleep=0.05)
            writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            writer.execute('PRAGMA journal_mode=DELETE')
        finally:
            writer.close()
            reader.close()
        os.chmod(target, 0o600)
        sqlite_info = _verify_sqlite(target)
        manifest = {
            'schema_version': 1,
            'kind': 'onyx-v090-pi-sqlite-backup',
            'source': str(SOURCE),
            'created_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'database': {'name': DATABASE_NAME, 'size': target.stat().st_size, 'sha256': _sha(target)},
            'sqlite': sqlite_info,
        }
        (temporary / MANIFEST_NAME).write_bytes(_canonical(manifest))
        os.chmod(temporary / MANIFEST_NAME, 0o600)
        # Avoid writing a backup before expected contents are validated.
        # inspect_backup validates the final directory after atomic rename.
        if destination.exists() or destination.is_symlink():
            raise Refused('backup destination appeared during preparation')
        temporary.rename(destination)
        temporary = None
        inspect_backup(destination)
        return {'status': 'BACKUP_VERIFIED', 'destination': str(destination),
                'sqlite': sqlite_info, 'services_changed': False}
    finally:
        if temporary is not None:
            shutil.rmtree(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--preview', action='store_true')
    group.add_argument('--backup', action='store_true')
    group.add_argument('--verify', metavar='BACKUP_ID')
    parser.add_argument('--backup-id')
    parser.add_argument('--approve-live-backup', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.verify:
            if args.backup_id or args.approve_live_backup or not BACKUP_ID.fullmatch(args.verify):
                raise Refused('unexpected verify arguments')
            _check_parent(BACKUP_PARENT, production=True)
            result = inspect_backup(BACKUP_PARENT / args.verify)
            print(_canonical({'status': 'VERIFIED', 'sqlite': result['sqlite']}).decode('ascii').strip())
            return 0
        if args.approve_live_backup != args.backup:
            raise Refused('backup requires explicit --approve-live-backup; preview forbids approval')
        if not args.backup_id:
            raise Refused('--backup-id required')
        result = create_backup(SOURCE, BACKUP_PARENT, args.backup_id,
                               apply=args.backup, production=args.backup)
        print(_canonical(result).decode('ascii').strip())
        return 0
    except (OSError, ValueError, Refused, sqlite3.Error, json.JSONDecodeError) as error:
        print('STOP: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
