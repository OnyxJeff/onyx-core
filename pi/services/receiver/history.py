"""Bounded SQLite history for already-validated ONYX CORE telemetry samples.

Standalone in v0.3.0 development: NOT yet wired into the live receiver.
Caller must validate schema and decide acceptance before append.
"""
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCHEMA_VERSION = 2
OPTIONAL_FIELDS = (
    "gpu_percent", "gpu_temp_c", "gpu_vram_used_mib", "gpu_vram_total_mib",
    "network_rx_bps", "network_tx_bps", "cpu_temp_c",
)
BASE_FIELDS = ("timestamp_utc", "source", "session_id", "sequence",
               "cpu_percent", "memory_used_percent", "uptime_seconds")
DATA_FIELDS = BASE_FIELDS + OPTIONAL_FIELDS

def _db_record_to_payload(row):
    record = dict(zip(DATA_FIELDS, row))
    return {
        "timestamp_utc": record["timestamp_utc"], "source": record["source"],
        "session_id": record["session_id"], "sequence": record["sequence"],
        "metrics": {key: record[key] for key in DATA_FIELDS[4:]},
    }

RETENTION_DAYS = 7
MAX_QUERY_ROWS = 500


class HistoryStore:
    def __init__(self, filename, retention_days=RETENTION_DAYS):
        if retention_days < 1 or retention_days > 365:
            raise ValueError("retention_days must be between 1 and 365")
        self.path = Path(filename)
        self.retention_days = retention_days
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=5, check_same_thread=False)
        try:
            # One writer, low commit frequency (30-second cadence); avoid
            # permanent -wal / -shm files on power-loss-sensitive microSD.
            self.conn.execute("PRAGMA journal_mode=DELETE")
            self.conn.execute("PRAGMA busy_timeout=5000")
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
            # Acceptance watermark survives history pruning.
            self.conn.execute("""CREATE TABLE IF NOT EXISTS acceptance_watermark (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                timestamp_utc TEXT NOT NULL,
                source TEXT NOT NULL,
                session_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                cpu_percent REAL NOT NULL,
                memory_used_percent REAL NOT NULL,
                uptime_seconds INTEGER NOT NULL
            )""")
            # Idempotent, additive migration: existing three-metric rows remain valid.
            for table in ("samples", "acceptance_watermark"):
                present = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
                for field in OPTIONAL_FIELDS:
                    if field not in present:
                        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {field} REAL")
            self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
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
            prev = self.boundary()
            if prev is not None:
                if sample["session_id"] == prev["session_id"]:
                    if sample["sequence"] <= prev["sequence"]:
                        return False
                elif sample["timestamp_utc"] <= prev["timestamp_utc"]:
                    return False
            self.conn.execute("DELETE FROM samples WHERE timestamp_utc < ?", (cutoff,))
            names = ", ".join(DATA_FIELDS)
            marks = ", ".join("?" for _ in DATA_FIELDS)
            values = (sample["timestamp_utc"], sample["source"],
                      sample["session_id"], sample["sequence"]) + tuple(
                          metrics.get(k) for k in DATA_FIELDS[4:])
            cursor = self.conn.execute(
                f"INSERT OR IGNORE INTO samples ({names}) VALUES ({marks})", values)
            if cursor.rowcount:
                self.conn.execute(
                    f"INSERT OR REPLACE INTO acceptance_watermark (singleton, {names}) "
                    f"VALUES (1, {marks})", values)
        return cursor.rowcount == 1

    def boundary(self):
        names = ", ".join(DATA_FIELDS)
        row = self.conn.execute(
            f"SELECT {names} FROM acceptance_watermark WHERE singleton = 1"
        ).fetchone()
        return _db_record_to_payload(row) if row is not None else None

    def recent(self, limit=120):
        if type(limit) is not int or not 1 <= limit <= MAX_QUERY_ROWS:
            raise ValueError("invalid limit")
        names = ", ".join(DATA_FIELDS)
        rows = self.conn.execute(
            f"SELECT {names} FROM samples "
            f"ORDER BY timestamp_utc DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_db_record_to_payload(row) for row in reversed(rows)]

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]

    def close(self):
        self.conn.close()
