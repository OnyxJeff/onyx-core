"""Bounded SQLite history for already-validated ONYX CORE telemetry samples.

Standalone in v0.3.0 development: NOT yet wired into the live receiver.
Caller must validate schema and decide acceptance before append.
"""
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCHEMA_VERSION = 1
RETENTION_DAYS = 7
MAX_QUERY_ROWS = 500


class HistoryStore:
    def __init__(self, filename, retention_days=RETENTION_DAYS):
        if retention_days < 1 or retention_days > 365:
            raise ValueError("retention_days must be between 1 and 365")
        self.path = Path(filename)
        self.retention_days = retention_days
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=5)
        try:
            # One writer, low commit frequency (30-second cadence); avoid
            # permanent -wal / -shm files on power-loss-sensitive microSD.
            self.conn.execute("PRAGMA journal_mode=DELETE")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.execute("PRAGMA user_version=1")
            self.conn.execute("""CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY,
                timestamp_utc TEXT NOT NULL,
                source TEXT NOT NULL,
                session_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                cpu_percent REAL NOT NULL,
                memory_used_percent REAL NOT NULL,
                uptime_seconds INTEGER NOT NULL,
                UNIQUE(session_id, sequence)
            )""")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_samples_timestamp ON samples(timestamp_utc)")
            self.conn.commit()
        except Exception:
            self.conn.close()
            raise

    def append(self, sample, now=None):
        """Insert one already-validated sample and prune in one transaction.

        Returns True for inserted rows; False for same-session duplicates.
        Raises on storage problems so callers never claim successful history writes.
        """
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            raise ValueError("now must be timezone aware")
        cutoff = (reference - timedelta(days=self.retention_days)).isoformat(timespec="seconds").replace("+00:00", "Z")
        metrics = sample["metrics"]
        with self.conn:
            self.conn.execute("DELETE FROM samples WHERE timestamp_utc < ?", (cutoff,))
            cursor = self.conn.execute(
                """INSERT OR IGNORE INTO samples
                (timestamp_utc, source, session_id, sequence, cpu_percent,
                 memory_used_percent, uptime_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (sample["timestamp_utc"], sample["source"], sample["session_id"],
                 sample["sequence"], metrics["cpu_percent"],
                 metrics["memory_used_percent"], metrics["uptime_seconds"]),
            )
        return cursor.rowcount == 1

    def recent(self, limit=120):
        if type(limit) is not int or not 1 <= limit <= MAX_QUERY_ROWS:
            raise ValueError("invalid limit")
        rows = self.conn.execute(
            """SELECT timestamp_utc, source, session_id, sequence,
                      cpu_percent, memory_used_percent, uptime_seconds
               FROM samples ORDER BY timestamp_utc DESC, id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {"timestamp_utc": r[0], "source": r[1], "session_id": r[2],
             "sequence": r[3],
             "metrics": {"cpu_percent": r[4], "memory_used_percent": r[5],
                         "uptime_seconds": r[6]}}
            for r in reversed(rows)
        ]

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]

    def close(self):
        self.conn.close()
