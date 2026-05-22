import sqlite3
from pathlib import Path

import pytest

from s7bb_fetcher.parser import ArrivalRecord
from s7bb_fetcher.storage import open_db, update_terminus_fields, upsert_records


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


def test_upsert_initialises_terminus_status_pending(tmp_db):
    """Newly inserted non-cancelled row gets terminus_status='pending'."""
    upsert_records(tmp_db, [_record(cancelled=False)])
    row = tmp_db.execute("SELECT terminus_status FROM arrivals").fetchone()
    assert row[0] == "pending"


def test_upsert_initialises_terminus_status_null_when_cancelled(tmp_db):
    """A Baierbrunn-cancelled row is not tracked → terminus_status stays NULL."""
    upsert_records(tmp_db, [_record(cancelled=True, actual_time=None, delay_minutes=None)])
    row = tmp_db.execute("SELECT terminus_status FROM arrivals").fetchone()
    assert row[0] is None


def test_upsert_clears_terminus_on_cancellation_flip(tmp_db):
    """A previously pending row that is later marked cancelled at Baierbrunn
    clears its terminus_* fields back to NULL."""
    upsert_records(tmp_db, [_record(cancelled=False)])
    # Simulate that a terminus update wrote a value before the cancellation arrived
    tmp_db.execute(
        "UPDATE arrivals SET terminus_status='arrived', terminus_delay_minutes=3"
    )
    tmp_db.commit()
    upsert_records(tmp_db, [_record(cancelled=True, actual_time=None, delay_minutes=None)])
    row = tmp_db.execute(
        "SELECT terminus_status, terminus_delay_minutes, terminus_short_turn_station "
        "FROM arrivals"
    ).fetchone()
    assert row == (None, None, None)


def test_upsert_preserves_terminus_on_normal_refetch(tmp_db):
    """Re-observation of a still-non-cancelled row must NOT clobber an
    already-written terminus result (idempotent re-fetches)."""
    upsert_records(tmp_db, [_record(cancelled=False)])
    tmp_db.execute(
        "UPDATE arrivals SET terminus_status='arrived', terminus_delay_minutes=2"
    )
    tmp_db.commit()
    upsert_records(tmp_db, [_record(cancelled=False, delay_minutes=1)])  # later refetch
    row = tmp_db.execute(
        "SELECT terminus_status, terminus_delay_minutes FROM arrivals"
    ).fetchone()
    assert row == ("arrived", 2)


def test_upsert_overwrites_dp_ppth_on_conflict(tmp_db):
    """dp_ppth from a fresh non-empty plan fetch overwrites the prior value."""
    upsert_records(tmp_db, [_record(dp_ppth="A|B|München Hbf Gl.27-36")])
    upsert_records(tmp_db, [_record(dp_ppth="A|B|C|München Hbf Gl.27-36")])
    row = tmp_db.execute("SELECT dp_ppth FROM arrivals").fetchone()
    assert row[0] == "A|B|C|München Hbf Gl.27-36"


def test_upsert_preserves_dp_ppth_when_refetch_is_empty(tmp_db):
    """An empty/NULL dp_ppth on refetch (partial XML / outage) preserves the
    last known good path — drilldown must stay usable."""
    upsert_records(tmp_db, [_record(dp_ppth="A|B|München Hbf Gl.27-36")])
    upsert_records(tmp_db, [_record(dp_ppth="")])  # empty → stored as NULL
    row = tmp_db.execute("SELECT dp_ppth FROM arrivals").fetchone()
    assert row[0] == "A|B|München Hbf Gl.27-36"


def test_update_terminus_fields_basic(tmp_db):
    """Writes status + delay + short_turn for a pending row matched by
    (train_id, scheduled_time)."""
    upsert_records(tmp_db, [_record(
        train_id="trip-001", train_number="6762",
        scheduled_time="2026-05-05T12:00:00+00:00",
    )])
    n = update_terminus_fields(tmp_db, [{
        "train_id": "trip-001",
        "scheduled_time": "2026-05-05T12:00:00+00:00",
        "terminus_status": "arrived",
        "terminus_delay_minutes": 3,
        "terminus_short_turn_station": None,
    }])
    assert n == 1
    row = tmp_db.execute(
        "SELECT terminus_status, terminus_delay_minutes, terminus_short_turn_station "
        "FROM arrivals WHERE train_id='trip-001'"
    ).fetchone()
    assert row == ("arrived", 3, None)


def test_update_terminus_fields_idempotent(tmp_db):
    """A second identical call is a no-op — the WHERE filter excludes
    rows no longer in 'pending' state."""
    upsert_records(tmp_db, [_record(train_id="trip-001", train_number="6762")])
    update = {
        "train_id": "trip-001",
        "scheduled_time": _record().scheduled_time,
        "terminus_status": "arrived",
        "terminus_delay_minutes": 0,
        "terminus_short_turn_station": None,
    }
    update_terminus_fields(tmp_db, [update])
    n = update_terminus_fields(tmp_db, [update])
    assert n == 0


def test_update_terminus_fields_guards_cancelled_flip(tmp_db):
    """If a Baierbrunn refetch flipped cancelled=1 between cycles, the
    terminus update for that train is silently dropped."""
    upsert_records(tmp_db, [_record(train_id="trip-001", train_number="6762", cancelled=False)])
    upsert_records(tmp_db, [_record(
        train_id="trip-001", train_number="6762", cancelled=True,
        actual_time=None, delay_minutes=None,
    )])  # flips → terminus_status reset to NULL
    n = update_terminus_fields(tmp_db, [{
        "train_id": "trip-001",
        "scheduled_time": _record().scheduled_time,
        "terminus_status": "arrived",
        "terminus_delay_minutes": 0,
        "terminus_short_turn_station": None,
    }])
    assert n == 0
    row = tmp_db.execute(
        "SELECT terminus_status FROM arrivals WHERE train_id='trip-001'"
    ).fetchone()
    assert row[0] is None  # cancelled rows never gain a terminus_status


def test_update_terminus_fields_only_matches_exact_scheduled_time(tmp_db):
    """Two rows with the same train_id on different days: only the row
    whose scheduled_time equals the update's is touched."""
    upsert_records(tmp_db, [_record(
        train_id="d1", train_number="6762",
        scheduled_time="2026-05-05T12:00:00+00:00",
    )])
    upsert_records(tmp_db, [_record(
        train_id="d2", train_number="6762",
        scheduled_time="2026-05-06T12:00:00+00:00",
    )])
    n = update_terminus_fields(tmp_db, [{
        "train_id": "d1",
        "scheduled_time": "2026-05-05T12:00:00+00:00",
        "terminus_status": "arrived",
        "terminus_delay_minutes": 0,
        "terminus_short_turn_station": None,
    }])
    assert n == 1  # only the May 5 row
    rows = dict(tmp_db.execute(
        "SELECT train_id, terminus_status FROM arrivals ORDER BY train_id"
    ).fetchall())
    assert rows == {"d1": "arrived", "d2": "pending"}
