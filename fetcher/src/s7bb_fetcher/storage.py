"""SQLite storage for arrival records."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .parser import ArrivalRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS arrivals (
    id             INTEGER PRIMARY KEY,
    train_id       TEXT NOT NULL,
    line           TEXT NOT NULL,
    station        TEXT NOT NULL,
    direction      TEXT NOT NULL,
    direction_bucket TEXT NOT NULL DEFAULT 'unknown',
    scheduled_time TEXT NOT NULL,
    actual_time    TEXT,
    delay_minutes  INTEGER,
    cancelled      INTEGER NOT NULL DEFAULT 0,
    reason         TEXT,
    train_number   TEXT,
    fetched_at     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_dedup ON arrivals(train_id, scheduled_time);
CREATE INDEX IF NOT EXISTS idx_scheduled ON arrivals(scheduled_time);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after initial schema without breaking existing DBs."""
    cur = conn.execute("PRAGMA table_info(arrivals)")
    cols = {row[1] for row in cur.fetchall()}
    if "direction_bucket" not in cols:
        conn.execute(
            "ALTER TABLE arrivals ADD COLUMN direction_bucket TEXT NOT NULL DEFAULT 'unknown'"
        )
        conn.execute("""
            UPDATE arrivals SET direction_bucket = CASE
                WHEN direction = 'Wolfratshausen' THEN 'wolfratshausen'
                WHEN direction LIKE '%München%' THEN 'muenchen'
                ELSE 'unknown'
            END
        """)
        conn.commit()
    if "train_number" not in cols:
        conn.execute("ALTER TABLE arrivals ADD COLUMN train_number TEXT")
        conn.commit()


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)
    return conn


def upsert_records(conn: sqlite3.Connection, records: list[ArrivalRecord]) -> int:
    """Insert or replace records. Returns number of rows affected."""
    now = datetime.now(UTC).isoformat()
    rows = [
        (
            r.train_id, r.line, r.station, r.direction, r.direction_bucket,
            r.scheduled_time, r.actual_time, r.delay_minutes,
            1 if r.cancelled else 0, r.reason, r.train_number, now,
        )
        for r in records
    ]
    cursor = conn.executemany(
        """
        INSERT INTO arrivals
            (train_id, line, station, direction, direction_bucket, scheduled_time,
             actual_time, delay_minutes, cancelled, reason, train_number, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(train_id, scheduled_time) DO UPDATE SET
            actual_time      = excluded.actual_time,
            delay_minutes    = excluded.delay_minutes,
            cancelled        = excluded.cancelled,
            reason           = excluded.reason,
            direction_bucket = excluded.direction_bucket,
            train_number     = COALESCE(excluded.train_number, train_number),
            fetched_at       = excluded.fetched_at
        """,
        rows,
    )
    conn.commit()
    return cursor.rowcount
