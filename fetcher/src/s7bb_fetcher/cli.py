"""CLI entry points: s7bb-fetch and s7bb-export."""

import argparse
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "s7bb.db"
LATEST_JSON = Path(__file__).parent.parent.parent.parent / "data" / "latest.json"
ARCHIVE_DIR = Path(__file__).parent.parent.parent.parent / "data" / "archive"


def fetch(argv: list[str] | None = None) -> None:
    from .api import fetch_baierbrunn_now
    from .parser import parse_timetable
    from .storage import open_db, upsert_records

    parser = argparse.ArgumentParser(description="Fetch S7 timetable from DB API")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite DB path")
    args = parser.parse_args(argv)

    plan_xml, changes_xml = fetch_baierbrunn_now()
    records = parse_timetable(plan_xml, changes_xml)
    conn = open_db(Path(args.db))
    n = upsert_records(conn, records)
    print(f"Fetched {len(records)} stops, {n} rows upserted → {args.db}")


def export(argv: list[str] | None = None) -> None:
    from .exporter import export_latest, export_monthly_archive
    from .storage import open_db

    parser = argparse.ArgumentParser(description="Export DB data to JSON")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite DB path")
    parser.add_argument("--out", default=str(LATEST_JSON), help="latest.json output path")
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument(
        "--archive",
        metavar="YYYY-MM",
        help="Export a monthly archive instead (format: 2026-04)",
    )
    args = parser.parse_args(argv)

    conn = open_db(Path(args.db))

    if args.archive:
        try:
            dt = datetime.strptime(args.archive, "%Y-%m")
        except ValueError:
            print(f"Invalid archive period '{args.archive}', expected YYYY-MM", file=sys.stderr)
            sys.exit(1)
        out = ARCHIVE_DIR / f"{args.archive}.json"
        export_monthly_archive(conn, dt.year, dt.month, out)
        print(f"Archive written → {out}")
    else:
        export_latest(conn, Path(args.out), args.window_days)
        print(f"latest.json written → {args.out}")
