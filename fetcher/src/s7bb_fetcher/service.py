"""s7bb-service: long-running APScheduler entrypoint for fetch + export + push."""

import logging
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR  = Path(os.environ.get("DATA_DIR",  "/data"))
REPO_PATH = Path(os.environ.get("REPO_PATH", "/repo"))
DB_PATH   = DATA_DIR / "s7bb.db"
OUT_PATH  = DATA_DIR / "latest.json"
ARCHIVE_DIR = DATA_DIR / "archive"
INDEX_PATH  = ARCHIVE_DIR / "index.json"


def _prev_year_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _safe(label: str, fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except Exception:
        logger.exception("export_job step %s failed", label)


def _fetch_job() -> None:
    from .api import fetch_baierbrunn_now
    from .parser import parse_timetable
    from .storage import open_db, upsert_records

    try:
        plan_xml, changes_xml = fetch_baierbrunn_now()
        records = parse_timetable(plan_xml, changes_xml)
        conn = open_db(DB_PATH)
        n = upsert_records(conn, records)
        logger.info("fetch_job: %d stops, %d upserted", len(records), n)
    except Exception:
        logger.exception("fetch_job failed")


def _export_job() -> None:
    from . import exporter, pusher, storage

    now = datetime.now(UTC)
    conn = None
    try:
        conn = storage.open_db(DB_PATH)
    except Exception:
        logger.exception("export_job: open_db failed; aborting")
        return

    _safe("latest", exporter.export_latest, conn, OUT_PATH)

    current_archive = ARCHIVE_DIR / f"{now.year:04d}-{now.month:02d}.json"
    _safe(
        "archive_current",
        exporter.export_monthly_archive,
        conn, now.year, now.month, current_archive, finalized=False,
    )

    if now.day == 1 and now.hour == 0:
        py, pm = _prev_year_month(now.year, now.month)
        prev_archive = ARCHIVE_DIR / f"{py:04d}-{pm:02d}.json"
        _safe(
            "archive_finalize",
            exporter.export_monthly_archive,
            conn, py, pm, prev_archive, finalized=True,
        )

    _safe("archive_index", exporter.export_archive_index, ARCHIVE_DIR, INDEX_PATH)

    _safe("push", pusher.push_data, REPO_PATH)


def main() -> None:
    fetch_cron  = os.environ.get("FETCH_CRON",  "*/5 * * * *")
    export_cron = os.environ.get("EXPORT_CRON", "0 * * * *")

    scheduler = BlockingScheduler()
    scheduler.add_job(
        _fetch_job,
        CronTrigger.from_crontab(fetch_cron),
        id="fetch",
        misfire_grace_time=None,
    )
    scheduler.add_job(
        _export_job,
        CronTrigger.from_crontab(export_cron),
        id="export",
        misfire_grace_time=None,
    )

    def _shutdown(signum, frame):
        logger.info("signal %s received, shutting down", signum)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("s7bb-service starting: FETCH_CRON=%s EXPORT_CRON=%s", fetch_cron, export_cron)
    scheduler.start()
