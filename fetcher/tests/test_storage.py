import sqlite3
from pathlib import Path

import pytest

from s7bb_fetcher.parser import ArrivalRecord
from s7bb_fetcher.storage import open_db, upsert_records


@pytest.fixture
def tmp_db(tmp_path: Path) -> sqlite3.Connection:
    return open_db(tmp_path / "test.db")


def _record(**kwargs) -> ArrivalRecord:
    defaults = dict(
        train_id="trip-001", line="S7", station="Baierbrunn", direction="Wolfratshausen",
        direction_bucket="wolfratshausen",
        scheduled_time="2026-05-05T12:00:00+00:00", actual_time="2026-05-05T12:05:00+00:00",
        delay_minutes=5, cancelled=False, reason=None,
    )
    return ArrivalRecord(**{**defaults, **kwargs})


def test_upsert_insert(tmp_db):
    n = upsert_records(tmp_db, [_record()])
    assert n == 1


def test_upsert_dedup(tmp_db):
    upsert_records(tmp_db, [_record(delay_minutes=5)])
    upsert_records(tmp_db, [_record(delay_minutes=10)])
    rows = tmp_db.execute("SELECT delay_minutes FROM arrivals").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 10  # updated


def test_cancelled_stored(tmp_db):
    upsert_records(tmp_db, [_record(cancelled=True, actual_time=None, delay_minutes=None)])
    row = tmp_db.execute("SELECT cancelled, actual_time FROM arrivals").fetchone()
    assert row[0] == 1
    assert row[1] is None


def test_direction_bucket_stored(tmp_db):
    upsert_records(tmp_db, [_record(direction_bucket="muenchen")])
    row = tmp_db.execute("SELECT direction_bucket FROM arrivals").fetchone()
    assert row[0] == "muenchen"


def test_migration_adds_column(tmp_path: Path):
    """DB created without direction_bucket column should be migrated on open_db."""
    db_path = tmp_path / "old.db"
    # Create old-style DB without direction_bucket
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE arrivals (
            id INTEGER PRIMARY KEY,
            train_id TEXT NOT NULL,
            line TEXT NOT NULL,
            station TEXT NOT NULL,
            direction TEXT NOT NULL,
            scheduled_time TEXT NOT NULL,
            actual_time TEXT,
            delay_minutes INTEGER,
            cancelled INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            fetched_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX idx_dedup ON arrivals(train_id, scheduled_time);
        INSERT INTO arrivals (train_id, line, station, direction, scheduled_time, cancelled, fetched_at)
        VALUES ('t1', 'S7', 'Baierbrunn', 'Wolfratshausen', '2026-05-05T10:00:00+00:00', 0, '2026-05-05T10:01:00+00:00');
    """)
    conn.commit()
    conn.close()

    # Re-open via open_db triggers migration
    conn2 = open_db(db_path)
    cols = {row[1] for row in conn2.execute("PRAGMA table_info(arrivals)").fetchall()}
    assert "direction_bucket" in cols

    row = conn2.execute("SELECT direction_bucket FROM arrivals WHERE train_id='t1'").fetchone()
    assert row[0] == "wolfratshausen"
