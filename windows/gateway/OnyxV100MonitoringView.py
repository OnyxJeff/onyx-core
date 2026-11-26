"""Explicit v1.0.0 history projection. No probe, writer, scheduler or repair.

The existing v0.8 read-only projector is reused with a fixed v100 path, never
its environment-selected default. Source-only integration until packaged.
"""
from pathlib import Path
import os
import stat

from OnyxMonitoringView import snapshot as legacy_snapshot


def history_path():
    raw = os.environ.get('LOCALAPPDATA')
    if not raw or not Path(raw).is_absolute():
        raise ValueError('LOCALAPPDATA unavailable')
    path = Path(raw) / 'OnyxCore-v100' / 'Monitoring' / 'incident-history.sqlite3'
    # Do not follow existing redirected ancestors, database or SQLite sidecars.
    # These checks are not a substitute for native DACL verification at install.
    for item in (*reversed(path.parents), path,
                 *(path.with_name(path.name + suffix) for suffix in ('-wal', '-shm', '-journal'))):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError('redirected monitoring storage refused')
        if item in path.parents:
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError('monitoring parent must be a directory')
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('non-regular or linked monitoring file refused')
    return path


def snapshot(*, now=None):
    result = legacy_snapshot(now=now, path=history_path())
    return {**result, 'source': 'OnyxV100MonitoringView'}
