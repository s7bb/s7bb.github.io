"""One-shot migration: shift `arrivals.scheduled_time` / `actual_time` by +1 minute.

Background: PR a8222a4 backfilled `data/latest.json` so the deployed times
matched the public S7 board, but the producing fetcher (parser.py) was
unchanged, so the next hourly export overwrote the file with the old
`:59` / `:19` / `:39` values. Once the parser fix lands (this release),
historical SQLite rows still carry the old internal-time convention.
This script rewrites them once.

Guarded by `PRAGMA user_version`. Schema version 0 → run migration → 1.
Subsequent runs are no-ops.

### Collision handling

If the new fetcher runs even once before this migration completes, it
inserts new public-time rows (`:00` / `:20` / `:40`) alongside the
existing internal-time rows (`:59` / `:19` / `:39`) — same `train_id`,
different `scheduled_time`. A naive shift then collides on the
`(train_id, scheduled_time)` UNIQUE index.

The migration handles this by detecting old-minute rows whose
+1-minute target already exists for the same `train_id` and dropping
the old row, since the new row is the canonical public-time copy.
Rows that already have public-time minutes (`:00 / :20 / :40`) are
left untouched.

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

# DB-internal minutes that need shifting to the public board (each is one
# minute before a public S7 slot at Baierbrunn). Anything else is either
# already public-time or a delay-stamped actual_time that we don't gate on.
_INTERNAL_MINUTES = {19, 39, 59}


def _shift(iso: str | None) -> str | None:
    if iso is None:
        return None
    return (datetime.fromisoformat(iso) + _OFFSET).isoformat()


def _scheduled_minute(iso: str) -> int:
    return datetime.fromisoformat(iso).minute


def run(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current >= _SCHEMA_VERSION:
            return  # already migrated

        rows = conn.execute(
            "SELECT rowid, train_id, scheduled_time, actual_time FROM arrivals"
        ).fetchall()
        existing_keys = {(train_id, scheduled) for _, train_id, scheduled, _ in rows}

        to_delete: list[int] = []
        to_update: list[tuple[str, str | None, int]] = []

        for rowid, train_id, scheduled, actual in rows:
            if _scheduled_minute(scheduled) not in _INTERNAL_MINUTES:
                continue  # already on public time, leave alone
            shifted_scheduled = _shift(scheduled)
            if (train_id, shifted_scheduled) in existing_keys:
                # New fetcher already wrote the public-time row. Drop this
                # internal-time duplicate; the canonical row stays.
                to_delete.append(rowid)
            else:
                to_update.append((shifted_scheduled, _shift(actual), rowid))

        with conn:
            if to_delete:
                conn.executemany(
                    "DELETE FROM arrivals WHERE rowid=?",
                    [(rid,) for rid in to_delete],
                )
            if to_update:
                conn.executemany(
                    "UPDATE arrivals SET scheduled_time=?, actual_time=? WHERE rowid=?",
                    to_update,
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
