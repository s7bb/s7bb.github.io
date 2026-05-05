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


def test_missing_slot_detected(populated_db, tmp_path):
    out = tmp_path / "latest.json"
    export_latest(populated_db, out)
    data = json.loads(out.read_text())

    w = data["aggregates"]["today"]["by_direction"]["wolfratshausen"]
    # 3 expected slots (10:13, 10:33, 10:53) but only 2 records → 1 missing
    assert w["missing"] >= 1


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


def test_expected_slots_cadence():
    rows = [
        {"scheduled_time": "2026-05-05T10:00:00+00:00"},
        {"scheduled_time": "2026-05-05T10:20:00+00:00"},
        {"scheduled_time": "2026-05-05T10:40:00+00:00"},
    ]
    slots = _expected_slots(rows)
    assert len(slots) == 3
    # Each slot 20 min apart
    times = [datetime.fromisoformat(s) for s in slots]
    gaps = [(times[i+1] - times[i]).seconds // 60 for i in range(len(times)-1)]
    assert all(g == 20 for g in gaps)


def test_direction_bucket_in_arrivals(populated_db, tmp_path):
    out = tmp_path / "latest.json"
    export_latest(populated_db, out)
    data = json.loads(out.read_text())
    buckets = {a["direction_bucket"] for a in data["arrivals"]}
    assert "muenchen" in buckets
    assert "wolfratshausen" in buckets
