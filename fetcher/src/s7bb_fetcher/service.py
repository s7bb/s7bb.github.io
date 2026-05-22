"""s7bb-service: long-running APScheduler entrypoint for fetch + export + push."""

import logging
import os
import shutil
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from . import preflight
from .preflight import PreflightFailed, Severity

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

_consecutive_push_failures = 0


def _prev_year_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _safe(label: str, fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except Exception:
        logger.exception("export_job step %s failed", label)


def _stage_into_repo(data_dir: Path, repo_path: Path) -> None:
    """Mirror exporter outputs from data_dir into the data-repo working tree.

    Copies latest.json and archive/*.json to repo_path's root (flat layout).
    Idempotent; overwrites destination files.
    """
    repo_archive = repo_path / "archive"
    repo_archive.mkdir(parents=True, exist_ok=True)

    latest = data_dir / "latest.json"
    if latest.exists():
        shutil.copy2(latest, repo_path / "latest.json")

    src_archive = data_dir / "archive"
    if src_archive.exists():
        for f in src_archive.glob("*.json"):
            shutil.copy2(f, repo_archive / f.name)


def _fetch_job() -> None:
    from . import api as _api
    from .parser import parse_timetable
    from .storage import open_db, upsert_records
    from .terminus import update_terminus_for_window

    try:
        plan_xml, changes_xml = _api.fetch_baierbrunn_now()
        records = parse_timetable(plan_xml, changes_xml)
        conn = open_db(DB_PATH)
        n = upsert_records(conn, records)
        logger.info("fetch_job: %d stops, %d upserted", len(records), n)
    except Exception:
        logger.exception("fetch_job failed")
        return

    # Terminus tracking runs in its own try/except so a terminus failure
    # never invalidates the Baierbrunn data we just committed.
    try:
        updated = update_terminus_for_window(conn, _api)
        logger.info("fetch_job: terminus %d rows updated", updated)
    except Exception:
        logger.exception("fetch_job: terminus tracking failed")


def _run_push_step() -> None:
    """Push step for the hourly export job — loud failures, fetch first.

    Logs at ERROR with the `PUSH_FAILED` prefix and a consecutive-failure
    counter so the metric is visible in `docker logs | grep PUSH_FAILED`.
    Does not raise — the scheduler must keep running so the next hour gets
    another shot.
    """
    global _consecutive_push_failures

    import git

    from . import pusher

    try:
        repo = git.Repo(str(REPO_PATH))
        repo.remotes["origin"].fetch()
        pusher.push_data(REPO_PATH)
    except Exception:
        _consecutive_push_failures += 1
        logger.exception(
            "PUSH_FAILED consecutive_failures=%d — commits will accumulate "
            "locally until next successful push",
            _consecutive_push_failures,
        )
        return

    _consecutive_push_failures = 0


def _export_job() -> None:
    from . import exporter, storage

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

    _safe("stage", _stage_into_repo, DATA_DIR, REPO_PATH)
    _run_push_step()


def main() -> None:
    fetch_cron  = os.environ.get("FETCH_CRON",  "*/5 * * * *")
    export_cron = os.environ.get("EXPORT_CRON", "0 * * * *")

    results = preflight.run(
        data_dir=DATA_DIR,
        repo_path=REPO_PATH,
        db_path=DB_PATH,
        github_slug=os.environ.get("GITHUB_REPO_SLUG") or None,
        github_token=os.environ.get("GITHUB_PAT") or None,
    )
    hard_failed = False
    logger.info("preflight: %d checks", len(results))
    for c in results:
        if c.ok:
            logger.info("preflight ✓ %s: %s", c.name, c.message)
        elif c.severity is Severity.SOFT:
            logger.warning("preflight ! %s: %s", c.name, c.message)
        else:
            logger.error("preflight ✗ %s: %s", c.name, c.message)
            hard_failed = True
    if hard_failed:
        raise PreflightFailed("one or more hard preflight checks failed; aborting startup")

    import git

    from . import pusher
    from . import startup_sync as _startup_sync

    slug = pusher._resolve_slug(git.Repo(str(REPO_PATH)))
    sync_result = _startup_sync.startup_sync(REPO_PATH, OUT_PATH, slug)
    logger.info(
        "startup_sync done: action=%s message=%s",
        sync_result.action, sync_result.message,
    )

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
