#!/usr/bin/env python3
"""ONYX CORE v0.9.0: SQLite-consistent backup and isolated restore rehearsal.

Offline/SANDBOX ONLY. Source is never written. No production or protected
history directory may be supplied. No credential, lock, JSON or task migration.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import uuid

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,90}\.(?:db|sqlite|sqlite3)\Z')
HEX = re.compile(r'[0-9a-f]{64}\Z')

class Refused(ValueError):
    pass


def _canonical(data):
    return (json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True)+'\n').encode('ascii')


def _hash(file):
    h=hashlib.sha256()
    with file.open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):
            h.update(block)
    return h.hexdigest()


def _temp_root():
    return Path(tempfile.gettempdir()).resolve(strict=True)


def _no_redirects(path):
    cur=path
    while True:
        if cur.is_symlink() or (hasattr(cur,'is_junction') and cur.is_junction()):
            raise Refused('redirected path refused')
        if cur.parent==cur:break
        cur=cur.parent


def _sandbox_directory(directory, *, must_exist):
    """Only direct OS-temp children named OnyxV090-* are accepted, no ancestors."""
    directory=Path(directory)
    if not directory.is_absolute() or '..' in directory.parts:
        raise Refused('absolute sandbox directory required')
    _no_redirects(directory)
    if directory.parent.resolve(strict=True)!=_temp_root() or not re.fullmatch(r'OnyxV090-[A-Za-z0-9_-]{1,55}',directory.name):
        raise Refused('only a direct disposable OnyxV090-* OS-temp directory is allowed')
    if must_exist and not directory.is_dir():
        raise Refused('sandbox directory is missing')
    if not must_exist and (directory.exists() or directory.is_symlink()):
        raise Refused('destination already exists; no overwrite')
    return directory


def _database_paths(source, names):
    source=_sandbox_directory(source,must_exist=True)
    if not names or len(names)>16 or len(names)!=len(set(names)):
        raise Refused('provide 1 to 16 unique SQLite filenames')
    result=[]
    for name in names:
        if not isinstance(name,str) or not NAME.fullmatch(name) or name in ('.','..'):
            raise Refused('invalid SQLite filename')
        file=source/name
        _no_redirects(file)
        if not file.is_file():
            raise Refused('missing SQLite source')
        result.append(file)
    return result


def _integrity_check(db):
    connection=sqlite3.connect(db.as_uri()+'?mode=ro&immutable=1',uri=True,timeout=5)
    try:
        result=connection.execute('PRAGMA integrity_check').fetchone()
        if result!=('ok',):raise Refused('SQLite integrity check failed')
    finally:connection.close()


def _atomic_new_folder(destination, callback):
    dest=_sandbox_directory(destination,must_exist=False)
    stage=Path(tempfile.mkdtemp(prefix='.onyx-v090-snapshot-',dir=str(dest.parent)))
    try:
        callback(stage)
        _sandbox_directory(dest,must_exist=False)
        stage.rename(dest)
        stage=None
    finally:
        if stage is not None:shutil.rmtree(stage,ignore_errors=True)


def backup(source, destination, names, *, apply=False):
    dbs=_database_paths(source,names)
    _sandbox_directory(destination,must_exist=False)
    result={'status':'PREVIEW' if not apply else 'BACKUP_CREATED', 'sqlite_files':sorted(names),
            'source_untouched':True,'destination':str(destination)}
    if not apply:return result
    def write(stage):
        rows=[]
        for original in sorted(dbs,key=lambda p:p.name):
            target=stage/original.name
            # SQLite backup() captures a transactionally consistent database,
            # including committed WAL contents, without copying WAL/SHM files.
            src=sqlite3.connect(original.as_uri()+'?mode=ro',uri=True,timeout=5)
            dst=sqlite3.connect(str(target),timeout=5)
            try:
                src.backup(dst,pages=100,sleep=0.05)
                # Normalize snapshot to a self-contained single-file database.
                dst.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                dst.execute('PRAGMA journal_mode=DELETE')
            finally:
                dst.close();src.close()
            _integrity_check(target)
            rows.append({'name':original.name,'sha256':_hash(target),'size':target.stat().st_size})
        (stage/'snapshot-manifest.json').write_bytes(_canonical({'schema_version':1,'kind':'sqlite-sandbox-backup','files':rows}))
    _atomic_new_folder(destination,write)
    return result


def inspect_backup(source):
    source=_sandbox_directory(source,must_exist=True)
    manifest_path=source/'snapshot-manifest.json'
    _no_redirects(manifest_path)
    manifest=json.loads(manifest_path.read_bytes())
    if type(manifest)!=dict or set(manifest)!={'schema_version','kind','files'} or manifest['schema_version']!=1 or manifest['kind']!='sqlite-sandbox-backup':
        raise Refused('unexpected backup manifest')
    rows=manifest['files']
    if type(rows)!=list or not 1<=len(rows)<=16:
        raise Refused('invalid backup inventory')
    names=[]
    for row in rows:
        if type(row)!=dict or set(row)!={'name','sha256','size'}:raise Refused('invalid backup entry')
        name=row['name']
        if type(name)!=str or not NAME.fullmatch(name) or name in names or type(row['sha256'])!=str or not HEX.fullmatch(row['sha256']) or type(row['size'])!=int or row['size']<1:
            raise Refused('invalid backup metadata')
        file=source/name
        _no_redirects(file)
        if not file.is_file() or file.stat().st_size!=row['size'] or _hash(file)!=row['sha256']:
            raise Refused('backup content differs from recorded digest')
        _integrity_check(file)
        names.append(name)
    if set(p.name for p in source.iterdir()) != {*names,'snapshot-manifest.json'}:
        raise Refused('unexpected backup contents')
    if _canonical(manifest)!=manifest_path.read_bytes():raise Refused('noncanonical manifest')
    return manifest


def restore(backup_dir,destination,*,apply=False):
    backup_dir=_sandbox_directory(backup_dir,must_exist=True)
    _sandbox_directory(destination,must_exist=False)
    manifest=inspect_backup(backup_dir)
    result={'status':'PREVIEW' if not apply else 'RESTORED_TO_NEW_SANDBOX', 'sqlite_files':[x['name'] for x in manifest['files']],
            'source_untouched':True, 'destination':str(destination)}
    if not apply:return result
    def write(stage):
        for row in manifest['files']:
            shutil.copyfile(backup_dir/row['name'],stage/row['name'],follow_symlinks=False)
            if _hash(stage/row['name'])!=row['sha256']:raise Refused('restore digest mismatch')
            _integrity_check(stage/row['name'])
        (stage/'snapshot-manifest.json').write_bytes(_canonical(manifest))
    _atomic_new_folder(destination,write)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('backup','verify','restore'))
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--destination',type=Path)
    p.add_argument('--database',action='append',default=[])
    p.add_argument('--apply',action='store_true')
    args=p.parse_args(argv)
    try:
        if args.command=='backup':
            if args.destination is None:raise Refused('destination required')
            result=backup(args.source,args.destination,args.database,apply=args.apply)
        elif args.command=='verify':
            if args.destination or args.database or args.apply:raise Refused('verify has no other flags')
            manifest=inspect_backup(args.source)
            result={'status':'VERIFIED','files':len(manifest['files'])}
        else:
            if args.destination is None or args.database:raise Refused('restore requires destination and no database names')
            result=restore(args.source,args.destination,apply=args.apply)
        print(_canonical(result).decode('ascii').strip())
        return 0
    except (OSError,ValueError,sqlite3.Error,json.JSONDecodeError) as exc:
        print('STOP: '+str(exc),file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())
