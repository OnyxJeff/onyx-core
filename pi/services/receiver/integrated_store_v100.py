"""ONYX CORE v1 SQLite-authoritative telemetry store.

Preserve the established HistoryStore schema and transaction semantics. Bootstrap
validation is supplied by the configured v1 receiver; never import the legacy
SQUALL-only receiver validator. No credential contents are handled here.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
from datetime import datetime
from pathlib import Path

try:
    from .history import HistoryStore
except ImportError:
    from history import HistoryStore


def _stamp(sample):
    return datetime.fromisoformat(sample['timestamp_utc'].replace('Z', '+00:00'))


class IntegratedStore:
    def __init__(self, database, snapshot, *, snapshot_validator):
        if not callable(snapshot_validator):
            raise ValueError('A configured snapshot validator is required')
        db_path = Path(database)
        self.snapshot = Path(snapshot)
        if db_path.is_symlink() or self.snapshot.is_symlink():
            raise ValueError('Redirected database or snapshot path refused')
        database_already_exists = db_path.exists()

        # IMPORTANT: check a legacy snapshot BEFORE creating an empty SQLite DB.
        # If its source disagrees with the configured collector identity, stop
        # without modifying or deleting legacy data; require explicit migration.
        candidate = None
        if not database_already_exists and self.snapshot.is_file():
            with self.snapshot.open('r', encoding='utf-8') as stream:
                candidate = json.load(stream)
            snapshot_validator(candidate)

        self.history = HistoryStore(database)
        self.lock = threading.Lock()
        self.last_cache_error = False
        try:
            with self.lock:
                if not database_already_exists and self.history.count() == 0 and candidate is not None:
                    self.history.append(candidate)
                self._repair_cache()
        except Exception:
            self.history.close()
            raise

    def _repair_cache(self):
        latest = self.history.boundary()
        if latest is None:
            return
        sample = {'schema_version': 1, **latest}
        self.snapshot.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.snapshot-', dir=self.snapshot.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(sample, stream, separators=(',', ':'), allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.snapshot)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def accept(self, sample):
        with self.lock:
            last = self.history.boundary()
            if last is not None:
                if sample['session_id'] == last['session_id']:
                    if sample['sequence'] <= last['sequence']:
                        return False
                elif _stamp(sample) <= _stamp(last):
                    return False
            inserted = self.history.append(sample)
            if not inserted:
                return False
            try:
                self._repair_cache()
                self.last_cache_error = False
            except OSError:
                self.last_cache_error = True
            return True

    def recent(self, limit=120):
        with self.lock:
            return self.history.recent(limit)

    def health(self, now=None):
        try:
            from .health import evaluate_health
        except ImportError:
            from health import evaluate_health
        with self.lock:
            boundary = self.history.boundary()
            stamp = boundary['timestamp_utc'] if boundary else None
        return evaluate_health(stamp, now=now, future_tolerance_seconds=5)

    def close(self):
        with self.lock:
            self.history.close()
