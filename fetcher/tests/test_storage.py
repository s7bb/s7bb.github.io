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
