"""Export SQLite data to JSON files consumed by the static site."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _query_window(conn: sqlite3.Connection, days: int) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cur = conn.execute(
        """
        SELECT train_id, line, station, direction, scheduled_time, actual_time,
               delay_minutes, cancelled, reason
        FROM arrivals
        WHERE scheduled_time >= ?
        ORDER BY scheduled_time
        """,
        (since,),
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _aggregate(rows: list[dict]) -> dict:
    total = len(rows)
    cancelled = sum(1 for r in rows if r["cancelled"])
    late = sum(1 for r in rows if not r["cancelled"] and (r["delay_minutes"] or 0) > 0)
    on_time = total - cancelled - late
    delays = [r["delay_minutes"] for r in rows if not r["cancelled"] and r["delay_minutes"] is not None]
    avg_delay = round(sum(delays) / len(delays), 1) if delays else 0.0
    return {"total": total, "on_time": on_time, "late": late, "cancelled": cancelled, "avg_delay_min": avg_delay}


def _today_rows(rows: list[dict]) -> list[dict]:
    today = datetime.now(timezone.utc).date().isoformat()
    return [r for r in rows if r["scheduled_time"].startswith(today)]


def export_latest(conn: sqlite3.Connection, out_path: Path, window_days: int = 7) -> None:
    rows = _query_window(conn, window_days)
    today_rows = _today_rows(rows)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "station": "Baierbrunn",
        "line": "S7",
        "window_days": window_days,
        "arrivals": rows,
        "aggregates": {
            "today": _aggregate(today_rows),
            "last_7_days": _aggregate(rows),
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def export_monthly_archive(conn: sqlite3.Connection, year: int, month: int, out_path: Path) -> None:
    """Export one calendar month of data to an archive JSON file."""
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"

    cur = conn.execute(
        """
        SELECT train_id, line, station, direction, scheduled_time, actual_time,
               delay_minutes, cancelled, reason
        FROM arrivals
        WHERE scheduled_time >= ? AND scheduled_time < ?
        ORDER BY scheduled_time
        """,
        (start, end),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "station": "Baierbrunn",
        "line": "S7",
        "period": f"{year:04d}-{month:02d}",
        "arrivals": rows,
        "aggregates": _aggregate(rows),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
