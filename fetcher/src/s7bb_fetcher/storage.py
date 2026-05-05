"""SQLite storage for arrival records."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .parser import ArrivalRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS arrivals (
    id            INTEGER PRIMARY KEY,
    train_id      TEXT NOT NULL,
    line          TEXT NOT NULL,
    station       TEXT NOT NULL,
    direction     TEXT NOT NULL,
    scheduled_time TEXT NOT NULL,
    actual_time   TEXT,
    delay_minutes INTEGER,
    cancelled     INTEGER NOT NULL DEFAULT 0,
    reason        TEXT,
    fetched_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_dedup ON arrivals(train_id, scheduled_time);
CREATE INDEX IF NOT EXISTS idx_scheduled ON arrivals(scheduled_time);
"""


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def upsert_records(conn: sqlite3.Connection, records: list[ArrivalRecord]) -> int:
    """Insert or replace records. Returns number of rows affected."""
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (
            r.train_id, r.line, r.station, r.direction,
            r.scheduled_time, r.actual_time, r.delay_minutes,
            1 if r.cancelled else 0, r.reason, now,
        )
        for r in records
    ]
    cursor = conn.executemany(
        """
        INSERT INTO arrivals
            (train_id, line, station, direction, scheduled_time, actual_time,
             delay_minutes, cancelled, reason, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(train_id, scheduled_time) DO UPDATE SET
            actual_time    = excluded.actual_time,
            delay_minutes  = excluded.delay_minutes,
            cancelled      = excluded.cancelled,
            reason         = excluded.reason,
            fetched_at     = excluded.fetched_at
        """,
        rows,
    )
    conn.commit()
    return cursor.rowcount
