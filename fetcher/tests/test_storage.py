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


def test_train_number_round_trip(tmp_db):
    upsert_records(tmp_db, [_record(train_number="6762")])
    row = tmp_db.execute("SELECT train_number FROM arrivals").fetchone()
    assert row[0] == "6762"


def test_train_number_null_when_absent(tmp_db):
    upsert_records(tmp_db, [_record()])  # train_number defaults to None
    row = tmp_db.execute("SELECT train_number FROM arrivals").fetchone()
    assert row[0] is None


def test_upsert_fills_null_train_number(tmp_db):
    """Re-observed row with <tl n> fills a previously NULL train_number."""
    upsert_records(tmp_db, [_record(train_number=None)])
    upsert_records(tmp_db, [_record(train_number="6762")])
    rows = tmp_db.execute("SELECT train_number FROM arrivals").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "6762"


def test_upsert_does_not_regress_train_number_to_null(tmp_db):
    """COALESCE guard: a later observation lacking <tl n> must NOT
    overwrite an already-captured train_number with NULL."""
    upsert_records(tmp_db, [_record(train_number="6762")])
    upsert_records(tmp_db, [_record(train_number=None)])
    rows = tmp_db.execute("SELECT train_number FROM arrivals").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "6762"  # preserved, not regressed to NULL


def test_migration_adds_train_number_column(tmp_path: Path):
    """A DB created without train_number is migrated on open_db,
    existing rows keep train_number NULL (Phase 1: no backfill)."""
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE arrivals (
            id INTEGER PRIMARY KEY,
            train_id TEXT NOT NULL,
            line TEXT NOT NULL,
            station TEXT NOT NULL,
            direction TEXT NOT NULL,
            direction_bucket TEXT NOT NULL DEFAULT 'unknown',
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

    conn2 = open_db(db_path)
    cols = {row[1] for row in conn2.execute("PRAGMA table_info(arrivals)").fetchall()}
    assert "train_number" in cols
    row = conn2.execute("SELECT train_number FROM arrivals WHERE train_id='t1'").fetchone()
    assert row[0] is None  # pre-existing row stays NULL, no backfill


def test_migration_adds_terminus_columns(tmp_path: Path):
    """A pre-terminus DB gains the four new columns on open_db; existing rows
    keep them NULL (no backfill)."""
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE arrivals (
            id INTEGER PRIMARY KEY,
            train_id TEXT NOT NULL,
            line TEXT NOT NULL,
            station TEXT NOT NULL,
            direction TEXT NOT NULL,
            direction_bucket TEXT NOT NULL DEFAULT 'unknown',
            scheduled_time TEXT NOT NULL,
            actual_time TEXT,
            delay_minutes INTEGER,
            cancelled INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            train_number TEXT,
            fetched_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX idx_dedup ON arrivals(train_id, scheduled_time);
        INSERT INTO arrivals (train_id, line, station, direction, scheduled_time, cancelled, fetched_at)
        VALUES ('t1', 'S7', 'Baierbrunn', 'Wolfratshausen', '2026-05-05T10:00:00+00:00', 0, '2026-05-05T10:01:00+00:00');
    """)
    conn.commit()
    conn.close()

    conn2 = open_db(db_path)
    cols = {row[1] for row in conn2.execute("PRAGMA table_info(arrivals)").fetchall()}
    for col in ("terminus_status", "terminus_delay_minutes", "terminus_short_turn_station", "dp_ppth"):
        assert col in cols, f"migration must add {col}"

    row = conn2.execute(
        "SELECT terminus_status, terminus_delay_minutes, terminus_short_turn_station, dp_ppth "
        "FROM arrivals WHERE train_id='t1'"
    ).fetchone()
    assert row == (None, None, None, None), "pre-existing row stays NULL (no backfill)"


def test_migration_creates_terminus_health_table(tmp_path: Path):
    db_path = tmp_path / "old.db"
    sqlite3.connect(str(db_path)).close()  # empty file is enough; open_db creates schema
    conn = open_db(db_path)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "terminus_health" in tables
    cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(terminus_health)"
    ).fetchall()}
    assert cols == {"eva", "zero_match_streak", "updated_at"}
