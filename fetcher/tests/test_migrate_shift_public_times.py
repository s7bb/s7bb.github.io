import sqlite3
from pathlib import Path

from s7bb_fetcher.parser import ArrivalRecord
from s7bb_fetcher.storage import open_db, upsert_records


def _make(tid: str, scheduled: str, actual: str | None = None) -> ArrivalRecord:
    return ArrivalRecord(
        train_id=tid, line="S7", station="Baierbrunn",
        direction="Wolfratshausen", direction_bucket="wolfratshausen",
        scheduled_time=scheduled,
        actual_time=actual if actual is not None else scheduled,
        delay_minutes=0, cancelled=False, reason=None,
    )


def test_migration_shifts_scheduled_and_actual_by_one_minute(tmp_path: Path):
    from scripts.migrate_shift_public_times import run as migrate

    db = tmp_path / "s7bb.db"
    conn = open_db(db)
    upsert_records(conn, [
        _make("a", "2026-05-05T10:59:00+00:00"),
        _make("b", "2026-05-05T11:19:00+00:00", actual="2026-05-05T11:21:00+00:00"),
    ])
    conn.close()

    migrate(db)

    conn = sqlite3.connect(db)
    rows = sorted(conn.execute(
        "SELECT train_id, scheduled_time, actual_time FROM arrivals"
    ).fetchall())
    assert rows == [
        ("a", "2026-05-05T11:00:00+00:00", "2026-05-05T11:00:00+00:00"),
        ("b", "2026-05-05T11:20:00+00:00", "2026-05-05T11:22:00+00:00"),
    ]


def test_migration_preserves_null_actual_time(tmp_path: Path):
    from scripts.migrate_shift_public_times import run as migrate

    db = tmp_path / "s7bb.db"
    conn = open_db(db)
    cancelled = ArrivalRecord(
        train_id="c", line="S7", station="Baierbrunn",
        direction="Wolfratshausen", direction_bucket="wolfratshausen",
        scheduled_time="2026-05-05T10:59:00+00:00",
        actual_time=None,
        delay_minutes=None, cancelled=True, reason="STOERUNG",
    )
    upsert_records(conn, [cancelled])
    conn.close()

    migrate(db)

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT scheduled_time, actual_time FROM arrivals WHERE train_id='c'"
    ).fetchone()
    assert row == ("2026-05-05T11:00:00+00:00", None)


def test_migration_is_idempotent(tmp_path: Path):
    from scripts.migrate_shift_public_times import run as migrate

    db = tmp_path / "s7bb.db"
    conn = open_db(db)
    upsert_records(conn, [_make("a", "2026-05-05T10:59:00+00:00")])
    conn.close()

    migrate(db)
    migrate(db)  # second run must be a no-op

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT scheduled_time FROM arrivals WHERE train_id='a'"
    ).fetchone()
    assert row == ("2026-05-05T11:00:00+00:00",)


def test_migration_sets_user_version(tmp_path: Path):
    from scripts.migrate_shift_public_times import run as migrate

    db = tmp_path / "s7bb.db"
    conn = open_db(db)
    upsert_records(conn, [_make("a", "2026-05-05T10:59:00+00:00")])
    conn.close()

    migrate(db)

    conn = sqlite3.connect(db)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 1
