"""SQLite-authoritative receiver store. Experimental v0.3.0; not deployed.

The database transaction is the acceptance boundary; the latest JSON is a
best-effort compatibility cache rebuilt from committed SQLite state.
"""
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
    from history import HistoryStore  # direct /opt/onyxcore/receiver.py execution


def _stamp(sample):
    return datetime.fromisoformat(sample["timestamp_utc"].replace("Z", "+00:00"))


class IntegratedStore:
    def __init__(self, database, snapshot):
        database_already_exists = Path(database).exists()
        self.history = HistoryStore(database)
        self.snapshot = Path(snapshot)
        self.lock = threading.Lock()
        self.last_cache_error = False
        try:
            with self.lock:
                # One-time bootstrap from the last v0.2 snapshot when SQLite is new.
                # The existing database always takes priority over the JSON cache.
                if not database_already_exists and self.history.count() == 0 and self.snapshot.is_file():
                    try:
                        from .receiver import validate
                    except ImportError:
                        from receiver import validate
                    with self.snapshot.open("r", encoding="utf-8") as stream:
                        candidate = json.load(stream)
                    validate(candidate, check_freshness=False)
                    self.history.append(candidate)
                self._repair_cache()
        except Exception:
            self.history.close()
            raise

    def _repair_cache(self):
        latest = self.history.boundary()
        if latest is None:
            return
        sample = {"schema_version": 1, **latest}
        self.snapshot.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".snapshot-", dir=self.snapshot.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(sample, stream, separators=(",", ":"), allow_nan=False)
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
                if sample["session_id"] == last["session_id"]:
                    if sample["sequence"] <= last["sequence"]:
                        return False
                elif _stamp(sample) <= _stamp(last):
                    return False
            # A failed SQLite write MUST raise and must not acknowledge.
            inserted = self.history.append(sample)
            if not inserted:
                return False
            # Committed data is authoritative. Failure to refresh JSON does not
            # undo SQLite commit; next restart/accepted sample repairs cache.
            try:
                self._repair_cache()
                self.last_cache_error = False
            except OSError:
                self.last_cache_error = True
            return True

    def recent(self, limit=120):
        with self.lock:
            return self.history.recent(limit)

    def close(self):
        with self.lock:
            self.history.close()
