import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from s7bb_fetcher.exporter import _expected_slots, export_latest
from s7bb_fetcher.parser import ArrivalRecord
from s7bb_fetcher.storage import open_db, upsert_records


def _make_arrival(train_id: str, scheduled: str, direction_bucket: str, **kwargs) -> ArrivalRecord:
    defaults = dict(
        line="S7", station="Baierbrunn",
        direction="Wolfratshausen" if direction_bucket == "wolfratshausen" else "München Hbf Gl.27-36",
        direction_bucket=direction_bucket,
        actual_time=scheduled, delay_minutes=0, cancelled=False, reason=None,
    )
    return ArrivalRecord(train_id=train_id, scheduled_time=scheduled, **{**defaults, **kwargs})


@pytest.fixture
def populated_db(tmp_path: Path) -> sqlite3.Connection:
    conn = open_db(tmp_path / "test.db")
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    records = [
        # München direction: 10:00, 10:20, 10:40, 11:00 (four slots, none missing)
        _make_arrival("m1", f"{today}T10:00:00+00:00", "muenchen"),
        _make_arrival("m2", f"{today}T10:20:00+00:00", "muenchen"),
        _make_arrival("m3", f"{today}T10:40:00+00:00", "muenchen"),
        _make_arrival("m4", f"{today}T11:00:00+00:00", "muenchen"),
        # Wolfratshausen: 10:13, 10:53 — 10:33 missing
        _make_arrival("w1", f"{today}T10:13:00+00:00", "wolfratshausen"),
        _make_arrival("w2", f"{today}T10:53:00+00:00", "wolfratshausen"),
    ]
    upsert_records(conn, records)
    return conn


def test_per_direction_aggregates(populated_db, tmp_path):
    out = tmp_path / "latest.json"
    export_latest(populated_db, out)
    data = json.loads(out.read_text())

    agg = data["aggregates"]["today"]
    assert "by_direction" in agg
    m = agg["by_direction"]["muenchen"]
    w = agg["by_direction"]["wolfratshausen"]
    assert m["total"] == 4
    assert w["total"] == 2


def test_no_phantom_missing_slots(populated_db, tmp_path):
    """expected_slots is observed-only — `missing` is always 0.

    The previous cadence-inferred grid produced phantom "keine Daten" rows
    in operational gaps and outside service hours. PR8bb4ea7 patched data
    after-the-fact; this test locks the code-level behaviour in.
    """
    out = tmp_path / "latest.json"
    export_latest(populated_db, out)
    data = json.loads(out.read_text())

    w = data["aggregates"]["today"]["by_direction"]["wolfratshausen"]
    m = data["aggregates"]["today"]["by_direction"]["muenchen"]
    assert w["missing"] == 0
    assert m["missing"] == 0


def test_no_missing_when_all_present(populated_db, tmp_path):
    out = tmp_path / "latest.json"
    export_latest(populated_db, out)
    data = json.loads(out.read_text())

    m = data["aggregates"]["today"]["by_direction"]["muenchen"]
    assert m["missing"] == 0


def test_expected_slots_in_output(populated_db, tmp_path):
    out = tmp_path / "latest.json"
    export_latest(populated_db, out)
    data = json.loads(out.read_text())

    assert "expected_slots" in data
    assert "today" in data["expected_slots"]
    assert "muenchen" in data["expected_slots"]["today"]
    assert "wolfratshausen" in data["expected_slots"]["today"]


def test_expected_slots_observed_only():
    """_expected_slots returns each observed scheduled_time exactly once, sorted."""
    rows = [
        {"scheduled_time": "2026-05-05T10:40:00+00:00"},
        {"scheduled_time": "2026-05-05T10:00:00+00:00"},
        {"scheduled_time": "2026-05-05T10:20:00+00:00"},
        {"scheduled_time": "2026-05-05T10:00:00+00:00"},  # duplicate
    ]
    slots = _expected_slots(rows)
    assert slots == [
        "2026-05-05T10:00:00+00:00",
        "2026-05-05T10:20:00+00:00",
        "2026-05-05T10:40:00+00:00",
    ]


def test_expected_slots_skips_phantom_gap_outside_window():
    """A 4-hour gap between observations does not produce phantom slots."""
    rows = [
        {"scheduled_time": "2026-05-05T05:00:00+00:00"},
        {"scheduled_time": "2026-05-05T09:00:00+00:00"},
    ]
    slots = _expected_slots(rows)
    assert slots == [
        "2026-05-05T05:00:00+00:00",
        "2026-05-05T09:00:00+00:00",
    ]


def test_direction_bucket_in_arrivals(populated_db, tmp_path):
    out = tmp_path / "latest.json"
    export_latest(populated_db, out)
    data = json.loads(out.read_text())
    buckets = {a["direction_bucket"] for a in data["arrivals"]}
    assert "muenchen" in buckets
    assert "wolfratshausen" in buckets


def test_atomic_write_replaces_existing_file(tmp_path):
    from s7bb_fetcher.exporter import _atomic_write_json

    target = tmp_path / "out.json"
    target.write_text('{"old": true}', encoding="utf-8")

    _atomic_write_json(target, {"new": True})

    assert json.loads(target.read_text()) == {"new": True}
    # No leftover temp files in the directory
    leftovers = [p for p in tmp_path.iterdir() if p.name != "out.json"]
    assert leftovers == []


def test_atomic_write_creates_parent_dirs(tmp_path):
    from s7bb_fetcher.exporter import _atomic_write_json

    target = tmp_path / "sub" / "deeper" / "out.json"
    _atomic_write_json(target, {"k": 1})
    assert target.exists()
    assert json.loads(target.read_text()) == {"k": 1}


def test_monthly_archive_includes_daily_aggregates(tmp_path):
    from s7bb_fetcher.exporter import export_monthly_archive

    conn = open_db(tmp_path / "test.db")
    records = [
        _make_arrival("m1", "2026-04-01T08:00:00+00:00", "muenchen"),
        _make_arrival("m2", "2026-04-01T08:20:00+00:00", "muenchen", delay_minutes=5),
        _make_arrival("m3", "2026-04-02T08:00:00+00:00", "muenchen"),
        _make_arrival("w1", "2026-04-01T08:13:00+00:00", "wolfratshausen"),
        _make_arrival("w2", "2026-04-02T08:13:00+00:00", "wolfratshausen", cancelled=True),
    ]
    upsert_records(conn, records)
    out = tmp_path / "2026-04.json"

    export_monthly_archive(conn, 2026, 4, out)
    data = json.loads(out.read_text())

    daily = {d["date"]: d for d in data["daily"]}
    assert "2026-04-01" in daily
    assert daily["2026-04-01"]["total"] == 3
    assert daily["2026-04-01"]["late"] == 1

    by_dir = data["daily_by_direction"]
    assert by_dir["muenchen"][0]["date"] == "2026-04-01"
    by_dir_w_dates = [d["date"] for d in by_dir["wolfratshausen"]]
    assert by_dir_w_dates == ["2026-04-01", "2026-04-02"]


def test_monthly_archive_includes_by_direction(tmp_path):
    from s7bb_fetcher.exporter import export_monthly_archive

    conn = open_db(tmp_path / "test.db")
    records = [
        _make_arrival("m1", "2026-04-01T08:00:00+00:00", "muenchen"),
        _make_arrival("m2", "2026-04-15T08:00:00+00:00", "muenchen", delay_minutes=3),
        _make_arrival("w1", "2026-04-01T08:13:00+00:00", "wolfratshausen"),
        _make_arrival("w2", "2026-04-20T08:13:00+00:00", "wolfratshausen", cancelled=True),
    ]
    upsert_records(conn, records)
    out = tmp_path / "2026-04.json"

    export_monthly_archive(conn, 2026, 4, out)
    data = json.loads(out.read_text())

    bd = data["aggregates"]["by_direction"]
    assert bd["muenchen"]["total"] == 2
    assert bd["muenchen"]["late"] == 1
    assert bd["wolfratshausen"]["cancelled"] == 1


def test_finalized_flag_default_false(tmp_path):
    from s7bb_fetcher.exporter import export_monthly_archive

    conn = open_db(tmp_path / "test.db")
    upsert_records(conn, [_make_arrival("m1", "2026-04-01T08:00:00+00:00", "muenchen")])
    out = tmp_path / "2026-04.json"

    export_monthly_archive(conn, 2026, 4, out)
    data = json.loads(out.read_text())
    assert data["finalized"] is False


def test_finalized_flag_true_when_requested(tmp_path):
    from s7bb_fetcher.exporter import export_monthly_archive

    conn = open_db(tmp_path / "test.db")
    upsert_records(conn, [_make_arrival("m1", "2026-04-01T08:00:00+00:00", "muenchen")])
    out = tmp_path / "2026-04.json"

    export_monthly_archive(conn, 2026, 4, out, finalized=True)
    data = json.loads(out.read_text())
    assert data["finalized"] is True


def test_archive_index_lists_months_in_order(tmp_path):
    from s7bb_fetcher.exporter import export_archive_index, export_monthly_archive

    conn = open_db(tmp_path / "test.db")
    upsert_records(conn, [
        _make_arrival("a", "2026-03-15T08:00:00+00:00", "muenchen"),
        _make_arrival("b", "2026-04-15T08:00:00+00:00", "muenchen"),
        _make_arrival("c", "2026-05-01T08:00:00+00:00", "wolfratshausen"),
    ])
    archive_dir = tmp_path / "archive"
    export_monthly_archive(conn, 2026, 3, archive_dir / "2026-03.json", finalized=True)
    export_monthly_archive(conn, 2026, 4, archive_dir / "2026-04.json", finalized=True)
    export_monthly_archive(conn, 2026, 5, archive_dir / "2026-05.json", finalized=False)

    index_path = archive_dir / "index.json"
    export_archive_index(archive_dir, index_path)
    idx = json.loads(index_path.read_text())

    periods = [m["period"] for m in idx["months"]]
    assert periods == ["2026-03", "2026-04", "2026-05"]
    finals = [m["finalized"] for m in idx["months"]]
    assert finals == [True, True, False]


def test_archive_index_includes_summary_and_by_direction(tmp_path):
    from s7bb_fetcher.exporter import export_archive_index, export_monthly_archive

    conn = open_db(tmp_path / "test.db")
    upsert_records(conn, [
        _make_arrival("m1", "2026-04-01T08:00:00+00:00", "muenchen"),
        _make_arrival("w1", "2026-04-01T08:13:00+00:00", "wolfratshausen", delay_minutes=2),
    ])
    archive_dir = tmp_path / "archive"
    export_monthly_archive(conn, 2026, 4, archive_dir / "2026-04.json")

    index_path = archive_dir / "index.json"
    export_archive_index(archive_dir, index_path)
    idx = json.loads(index_path.read_text())

    apr = next(m for m in idx["months"] if m["period"] == "2026-04")
    assert apr["total"] == 2
    assert apr["by_direction"]["muenchen"]["total"] == 1
    assert apr["by_direction"]["wolfratshausen"]["late"] == 1
    assert idx["station"] == "Baierbrunn"
    assert "generated_at" in idx


def test_archive_index_skips_non_period_files(tmp_path):
    from s7bb_fetcher.exporter import export_archive_index

    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    (archive_dir / "index.json").write_text('{"months":[]}')
    (archive_dir / "README.txt").write_text("ignore me")
    (archive_dir / "garbage.json").write_text('{"period":"not-a-month"}')

    out = archive_dir / "index.json"
    export_archive_index(archive_dir, out)
    idx = json.loads(out.read_text())
    assert idx["months"] == []
