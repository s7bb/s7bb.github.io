"""One-shot migration: shift `arrivals.scheduled_time` / `actual_time` by +1 minute.

Background: PR a8222a4 backfilled `data/latest.json` so the deployed times
matched the public S7 board, but the producing fetcher (parser.py) was
unchanged, so the next hourly export overwrote the file with the old
`:59` / `:19` / `:39` values. Once the parser fix lands (this release),
historical SQLite rows still carry the old internal-time convention.
This script rewrites them once.

Guarded by `PRAGMA user_version`. Schema version 0 → run migration → 1.
Subsequent runs are no-ops.

Usage on the VM:

    cd fetcher
    uv run python -m scripts.migrate_shift_public_times \\
        --db /path/to/data/s7bb.db
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

_SCHEMA_VERSION = 1
_OFFSET = timedelta(minutes=1)


def _shift(iso: str | None) -> str | None:
    if iso is None:
        return None
    return (datetime.fromisoformat(iso) + _OFFSET).isoformat()


def run(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current >= _SCHEMA_VERSION:
            return  # already migrated

        rows = conn.execute(
            "SELECT rowid, scheduled_time, actual_time FROM arrivals"
        ).fetchall()
        with conn:
            for rowid, scheduled, actual in rows:
                conn.execute(
                    "UPDATE arrivals SET scheduled_time=?, actual_time=? WHERE rowid=?",
                    (_shift(scheduled), _shift(actual), rowid),
                )
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
    finally:
        conn.close()


def _cli() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, required=True, help="Path to s7bb.db")
    args = p.parse_args()
    run(args.db)


if __name__ == "__main__":
    _cli()
