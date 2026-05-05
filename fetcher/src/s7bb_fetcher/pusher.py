"""Push data/latest.json to git remote via SSH deploy key."""

import logging
import os
import shlex
from datetime import UTC, datetime
from pathlib import Path

import git

logger = logging.getLogger(__name__)

_LATEST_JSON = "data/latest.json"


def _actor(name_var: str, email_var: str, default_name: str) -> git.Actor:
    return git.Actor(
        os.environ.get(name_var, default_name),
        os.environ.get(email_var, "s7bb-bot@localhost"),
    )


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

    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    author = _actor("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "s7bb-bot")
    committer = _actor("GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "s7bb-bot")
    repo.index.commit(
        f"chore: update latest.json {ts}",
        author=author,
        committer=committer,
    )

    env = {}
    ssh_key = os.environ.get("SSH_DEPLOY_KEY_PATH", "")
    if ssh_key:
        parts = ["ssh", "-i", shlex.quote(ssh_key),
                 "-o", "IdentitiesOnly=yes",
                 "-o", "StrictHostKeyChecking=accept-new"]
        known_hosts = os.environ.get("SSH_KNOWN_HOSTS_PATH", "")
        if known_hosts:
            parts += ["-o", f"UserKnownHostsFile={shlex.quote(known_hosts)}"]
        env["GIT_SSH_COMMAND"] = " ".join(parts)

    origin = repo.remotes["origin"]
    push_infos = origin.push(env=env)
    for info in push_infos:
        if info.flags & git.PushInfo.ERROR:
            raise RuntimeError(f"git push failed: {info.summary}")

    logger.info("push_latest: pushed to origin/main")
    return True
