"""Push data/latest.json to git remote via SSH deploy key."""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import git

logger = logging.getLogger(__name__)

_LATEST_JSON = "data/latest.json"


def push_latest(repo_path: Path) -> bool:
    """Stage, commit, and push data/latest.json.

    Returns True if a commit was made, False if nothing changed.
    Raises on git or push errors.
    """
    repo = git.Repo(str(repo_path))

    target = repo_path / _LATEST_JSON
    if not target.exists():
        logger.warning("push_latest: %s not found, skipping", target)
        return False

    repo.index.add([_LATEST_JSON])

    if not repo.index.diff("HEAD"):
        logger.info("push_latest: no changes, skipping commit")
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
