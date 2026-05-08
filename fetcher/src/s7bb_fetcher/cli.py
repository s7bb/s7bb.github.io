"""CLI entry points: s7bb-fetch and s7bb-export."""

import argparse
import os
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
    from .exporter import export_archive_index, export_latest, export_monthly_archive
    from .storage import open_db

    parser = argparse.ArgumentParser(description="Export DB data to JSON")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite DB path")
    parser.add_argument("--out", default=str(LATEST_JSON), help="latest.json output path")
    parser.add_argument("--out-dir", default=str(ARCHIVE_DIR), help="Archive directory")
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument(
        "--archive",
        metavar="YYYY-MM",
        help="Export a monthly archive instead (format: 2026-04)",
    )
    parser.add_argument(
        "--archive-index",
        action="store_true",
        help="Regenerate data/archive/index.json from existing archive files",
    )
    parser.add_argument(
        "--refinalize",
        action="store_true",
        help="With --archive YYYY-MM: rewrite the archive with finalized=true",
    )
    args = parser.parse_args(argv)

    conn = open_db(Path(args.db))
    archive_dir = Path(args.out_dir)

    if args.archive_index:
        archive_dir.mkdir(parents=True, exist_ok=True)
        export_archive_index(archive_dir, archive_dir / "index.json")
        print(f"Archive index written → {archive_dir / 'index.json'}")
        return

    if args.archive:
        try:
            dt = datetime.strptime(args.archive, "%Y-%m")
        except ValueError:
            print(f"Invalid archive period '{args.archive}', expected YYYY-MM", file=sys.stderr)
            sys.exit(1)
        out = archive_dir / f"{args.archive}.json"
        export_monthly_archive(conn, dt.year, dt.month, out, finalized=args.refinalize)
        print(f"Archive written → {out} (finalized={args.refinalize})")
        return

    export_latest(conn, Path(args.out), args.window_days)
    print(f"latest.json written → {args.out}")


def preflight(argv: list[str] | None = None) -> None:
    from . import preflight as preflight_mod
    from .preflight import Severity

    parser = argparse.ArgumentParser(description="Run s7bb-fetcher preflight checks")
    parser.add_argument("--data-dir", default=os.environ.get("DATA_DIR", "/data"))
    parser.add_argument("--repo-path", default=os.environ.get("REPO_PATH", "/repo"))
    parser.add_argument("--db", default=None,
                        help="SQLite DB path; defaults to <data-dir>/s7bb.db")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    repo_path = Path(args.repo_path)
    db_path = Path(args.db) if args.db else data_dir / "s7bb.db"

    results = preflight_mod.run(
        data_dir=data_dir,
        repo_path=repo_path,
        db_path=db_path,
        github_slug=os.environ.get("GITHUB_REPO_SLUG") or None,
        github_token=os.environ.get("GITHUB_PAT") or None,
    )

    hard_fail = False
    print(f"preflight: {len(results)} checks")
    for c in results:
        if c.ok:
            mark = "[OK]"
        else:
            mark = "[FAIL]" if c.severity is Severity.HARD else "[WARN]"
            if c.severity is Severity.HARD:
                hard_fail = True
        print(f"  {mark:6} {c.name:18} {c.message}")

    sys.exit(1 if hard_fail else 0)
