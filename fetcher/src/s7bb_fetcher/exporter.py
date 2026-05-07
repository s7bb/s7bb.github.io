"""Export SQLite data to JSON files consumed by the static site."""

import json
import os
import sqlite3
import tempfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _atomic_write_json(path: Path, payload: object) -> None:
    """Write JSON atomically: temp file in same dir, then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _query_window(conn: sqlite3.Connection, days: int) -> list[dict]:
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    cur = conn.execute(
        """
        SELECT train_id, line, station, direction, direction_bucket, scheduled_time,
               actual_time, delay_minutes, cancelled, reason
        FROM arrivals
        WHERE scheduled_time >= ?
        ORDER BY scheduled_time
        """,
        (since,),
    )
    cols = [d[0] for d in cur.description]
    out = [dict(zip(cols, row)) for row in cur.fetchall()]
    for r in out:
        r["cancelled"] = bool(r["cancelled"])
    return out


def _aggregate(rows: list[dict]) -> dict:
    total = len(rows)
    cancelled = sum(1 for r in rows if r["cancelled"])
    late = sum(1 for r in rows if not r["cancelled"] and (r["delay_minutes"] or 0) > 0)
    on_time = total - cancelled - late
    delays = [
        r["delay_minutes"]
        for r in rows
        if not r["cancelled"] and r["delay_minutes"] is not None
    ]
    avg_delay = round(sum(delays) / len(delays), 1) if delays else 0.0
    return {
        "total": total,
        "on_time": on_time,
        "late": late,
        "cancelled": cancelled,
        "avg_delay_min": avg_delay,
    }


def _expected_slots(rows: list[dict]) -> list[str]:
    """Infer expected 20-min slots from observed scheduled_times.

    Uses the most common minute-offset within a 20-min cycle to anchor the grid,
    then generates one slot per 20 min between first and last observed time.
    """
    if not rows:
        return []

    times = sorted(
        datetime.fromisoformat(r["scheduled_time"])
        for r in rows
    )
    if len(times) < 2:
        return [t.isoformat() for t in times]

    # Most common minute mod 20 = cadence anchor
    offsets = Counter(t.minute % 20 for t in times)
    anchor_offset = offsets.most_common(1)[0][0]

    # Find first slot >= min time with correct offset
    first = times[0]
    start_minute = (first.minute // 20) * 20 + anchor_offset
    if start_minute > first.minute:
        start_minute -= 20
    start = first.replace(minute=start_minute % 60, second=0, microsecond=0)
    if start_minute >= 60:
        start += timedelta(hours=1)

    last = times[-1]
    slots = []
    current = start
    while current <= last + timedelta(minutes=1):
        slots.append(current.isoformat())
        current += timedelta(minutes=20)
    return slots


def _direction_aggregate(rows: list[dict], bucket: str, expected_slots: list[str]) -> dict:
    bucket_rows = [r for r in rows if r["direction_bucket"] == bucket]
    agg = _aggregate(bucket_rows)
    missing = max(0, len(expected_slots) - len(bucket_rows))
    return {**agg, "missing": missing}


def _today_rows(rows: list[dict]) -> list[dict]:
    today = datetime.now(UTC).date().isoformat()
    return [r for r in rows if r["scheduled_time"].startswith(today)]


def _build_aggregates(rows: list[dict], today_rows: list[dict]) -> tuple[dict, dict, dict]:
    """Return (today_agg, week_agg, today_slots)."""
    muenchen_today = [r for r in today_rows if r["direction_bucket"] == "muenchen"]
    wolf_today = [r for r in today_rows if r["direction_bucket"] == "wolfratshausen"]
    muenchen_week = [r for r in rows if r["direction_bucket"] == "muenchen"]
    wolf_week = [r for r in rows if r["direction_bucket"] == "wolfratshausen"]

    slots_muenchen = _expected_slots(muenchen_today)
    slots_wolf = _expected_slots(wolf_today)

    today_agg = {
        **_aggregate(today_rows),
        "by_direction": {
            "muenchen": _direction_aggregate(today_rows, "muenchen", slots_muenchen),
            "wolfratshausen": _direction_aggregate(today_rows, "wolfratshausen", slots_wolf),
        },
    }
    week_agg = {
        **_aggregate(rows),
        "by_direction": {
            "muenchen": _direction_aggregate(
                rows, "muenchen", _expected_slots(muenchen_week)
            ),
            "wolfratshausen": _direction_aggregate(
                rows, "wolfratshausen", _expected_slots(wolf_week)
            ),
        },
    }
    today_slots = {"muenchen": slots_muenchen, "wolfratshausen": slots_wolf}
    return today_agg, week_agg, today_slots


def export_latest(conn: sqlite3.Connection, out_path: Path, window_days: int = 7) -> None:
    rows = _query_window(conn, window_days)
    today_rows = _today_rows(rows)
    today_agg, week_agg, today_slots = _build_aggregates(rows, today_rows)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "station": "Baierbrunn",
        "line": "S7",
        "window_days": window_days,
        "arrivals": rows,
        "aggregates": {
            "today": today_agg,
            "last_7_days": week_agg,
        },
        "expected_slots": {"today": today_slots},
    }
    _atomic_write_json(out_path, payload)


def export_monthly_archive(conn: sqlite3.Connection, year: int, month: int, out_path: Path) -> None:
    """Export one calendar month of data to an archive JSON file."""
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"

    cur = conn.execute(
        """
        SELECT train_id, line, station, direction, direction_bucket, scheduled_time,
               actual_time, delay_minutes, cancelled, reason
        FROM arrivals
        WHERE scheduled_time >= ? AND scheduled_time < ?
        ORDER BY scheduled_time
        """,
        (start, end),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    for r in rows:
        r["cancelled"] = bool(r["cancelled"])

    aggregates = {
        **_aggregate(rows),
        "by_direction": {
            "muenchen":       _aggregate([r for r in rows if r["direction_bucket"] == "muenchen"]),
            "wolfratshausen": _aggregate([r for r in rows if r["direction_bucket"] == "wolfratshausen"]),
        },
    }

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "station": "Baierbrunn",
        "line": "S7",
        "period": f"{year:04d}-{month:02d}",
        "arrivals": rows,
        "aggregates": aggregates,
    }
    _atomic_write_json(out_path, payload)
