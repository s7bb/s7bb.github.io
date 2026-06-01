# Docker Container - Implementation Plan

## Artefacts (in order)

| # | File | Action |
|---|------|--------|
| 1 | `fetcher/pyproject.toml` | Add `apscheduler=3.10.4`, `gitpython=3.1.43`; add `s7bb-service` entrypoint |
| 2 | `fetcher/src/s7bb_fetcher/pusher.py` | New - Python replacement for `push-data.sh` |
| 3 | `fetcher/src/s7bb_fetcher/service.py` | New - long-running APScheduler entrypoint |
| 4 | `fetcher/Dockerfile` | New - `python:3.12-slim` + `apt install git` + `pip install .` |
| 5 | `docker-compose.yml` | New - `s7bb-fetcher` service + `s7bb-dev` web server (profile: dev) |
| 6 | `.env.example` | Update - add `FETCH_CRON`, `EXPORT_CRON`, `SSH_DEPLOY_KEY_PATH`, git identity vars |
| 7 | `CHANGELOG.md` | Update - `[Unreleased]` Added + Changed sections |

---

## Step 1 - `fetcher/pyproject.toml`

```toml
[project.dependencies]
# existing deps unchanged
apscheduler = "3.10.4"
gitpython   = "3.1.43"

[project.scripts]
s7bb-fetch   = "s7bb_fetcher.cli:fetch"
s7bb-export  = "s7bb_fetcher.cli:export"
s7bb-service = "s7bb_fetcher.service:main"
```

---

## Step 2 - `pusher.py`

Replaces `push-data.sh`. Stages only `data/latest.json`, commits, pushes via SSH deploy key.

```python
"""Push data/latest.json to git remote via SSH deploy key."""
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import git

logger = logging.getLogger(__name__)
_LATEST_JSON = "data/latest.json"


def push_latest(repo_path: Path) -> bool:
    """Stage, commit, push data/latest.json. Returns True if committed."""
    repo = git.Repo(str(repo_path))

    target = repo_path / _LATEST_JSON
    if not target.exists():
        logger.warning("push_latest: %s not found, skipping", target)
        return False

    repo.index.add([_LATEST_JSON])
    if not repo.index.diff("HEAD"):
        logger.info("push_latest: no changes, skipping")
        return False

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    repo.index.commit(f"chore: update latest.json {ts}")

    env = {}
    ssh_key = os.environ.get("SSH_DEPLOY_KEY_PATH", "")
    if ssh_key:
        env["GIT_SSH_COMMAND"] = f"ssh -i {ssh_key} -o StrictHostKeyChecking=no"

    origin = repo.remotes["origin"]
    push_infos = origin.push(env=env)
    for info in push_infos:
        if info.flags & git.PushInfo.ERROR:
            raise RuntimeError(f"git push failed: {info.summary}")

    logger.info("push_latest: pushed to origin/main")
    return True
```

**Key points:**
- Only `data/latest.json` ever staged - nothing else
- `SSH_DEPLOY_KEY_PATH` env var points to mounted key
- Checks push result; raises on error (no silent failures)
- `git.Repo()` raises `InvalidGitRepositoryError` on bad `REPO_PATH` - fails early

---

## Step 3 - `service.py`

Long-running process; PID 1 in container.

```python
"""s7bb-service: APScheduler-based fetch+export+push loop."""
import logging
import os
import signal
import sys
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
    from .exporter import export_latest
    from .storage import open_db
    from .pusher import push_latest
    try:
        conn = open_db(DB_PATH)
        export_latest(conn, OUT_PATH)
        logger.info("export_job: wrote %s", OUT_PATH)
        push_latest(REPO_PATH)
    except Exception:
        logger.exception("export_job failed")


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
        logger.info("signal %s - shutting down", signum)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("s7bb-service: FETCH_CRON=%s EXPORT_CRON=%s", fetch_cron, export_cron)
    scheduler.start()
```

**Key points:**
- `BlockingScheduler` - main thread blocks; right choice for single-process container
- `misfire_grace_time=None` - always runs missed jobs (important for hourly export)
- `SIGTERM` handler - clean shutdown on `docker stop`
- Jobs catch all exceptions - one failed fetch never kills the service
- Lazy imports inside job functions - faster startup, no side-effects at module load

---

## Step 4 - `Dockerfile`

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir .

CMD ["s7bb-service"]
```

**Key points:**
- `git` required at runtime - GitPython shells out to the git binary
- Copy only `pyproject.toml` + `src/` - no tests, systemd units, or shell scripts
- Plain `pip install` - simpler than adding uv for a local-only image
- `CMD` not `ENTRYPOINT` - easier to override for debugging

---

## Step 5 - `docker-compose.yml`

```yaml
services:
  s7bb-fetcher:
    build:
      context: fetcher
      dockerfile: Dockerfile
    restart: unless-stopped
    env_file: .env
    # Run as host user to avoid permission issues with the data/ volume.
    # Set UID and GID in .env: UID=1000 GID=1000
    user: "${UID}:${GID}"
    volumes:
      - ./data:/data
      - .:/repo
      - ${SSH_DEPLOY_KEY_PATH}:${SSH_DEPLOY_KEY_PATH}:ro
    environment:
      DATA_DIR: /data
      REPO_PATH: /repo

  s7bb-dev:
    image: python:3.12-slim
    command: python3 -m http.server 8080 --directory /data
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data:ro
    profiles:
      - dev
```

**Key points:**
- `env_file: .env` - loads all vars including crons, API keys, git identity
- SSH key volume: `${SSH_DEPLOY_KEY_PATH}:${SSH_DEPLOY_KEY_PATH}:ro` - same path inside/outside, no translation
- `user: "${UID}:${GID}"` - avoids root-vs-host-user permission conflict on `data/`
- `s7bb-dev` gated by `profiles: [dev]` - not started by default `docker compose up -d`
- `restart: unless-stopped` - survives VM reboots when started with `docker compose up -d`

---

## Step 6 - `.env.example`

```bash
# DB Timetables API credentials
DB_API_KEY=your_key_here
DB_CLIENT_ID=your_client_id_here

# Scheduler cron expressions (standard 5-field cron)
FETCH_CRON=*/5 * * * *
EXPORT_CRON=0 * * * *

# SSH deploy key - absolute path on host, mounted into container at same path
# File must be chmod 600
SSH_DEPLOY_KEY_PATH=/home/s7bb/.ssh/id_ed25519_s7bb_deploy

# Git identity for automated commits inside the container
GIT_AUTHOR_NAME=s7bb-bot
GIT_AUTHOR_EMAIL=s7bb-bot@localhost
GIT_COMMITTER_NAME=s7bb-bot
GIT_COMMITTER_EMAIL=s7bb-bot@localhost

# Host UID/GID for container user (avoids volume permission conflicts)
UID=1000
GID=1000

# Container-internal paths (defaults shown; change only if mounts differ)
# DATA_DIR=/data
# REPO_PATH=/repo
```

---

## Risks and Gotchas

| Risk | Mitigation |
|------|-----------|
| SSH key permissions must be `chmod 600` | Document in `.env.example`; SSH refuses `640`/`644` |
| git identity not set → commit fails | `GIT_AUTHOR_*` / `GIT_COMMITTER_*` in `.env` |
| `data/` volume owned by wrong UID | `user: "${UID}:${GID}"` in compose |
| `push-data.sh` still exists after migration | Delete the file; systemd units kept for reference only |
| `cli.py` path resolution breaks inside container | `service.py` uses `DATA_DIR` env var, not `__file__`; document `s7bb-fetch` CLI needs `--db` / `--out` args inside container |
| APScheduler misfire on container start | `misfire_grace_time=None` ensures missed jobs always run |

---

## Out of Scope

- Tests for `pusher.py` / `service.py`
- Removing systemd units from repo
- Changing existing dep pin style in `pyproject.toml`
