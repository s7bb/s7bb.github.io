"""Push latest.json + archive/*.json to the s7bb-data repo via GitHub PAT (HTTPS)."""

import enum
import logging
import os
import re
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import git


class PushOutcome(enum.Enum):
    """Result of a `push_data` call.

    - COMMITTED_AND_PUSHED: staged file changes -> new commit -> pushed.
    - PUSHED_EXISTING: nothing new to commit, but local HEAD was ahead of
      origin/main, so existing commits were pushed.
    - NOOP: nothing new to commit AND local HEAD already matches origin/main.
    """

    COMMITTED_AND_PUSHED = "committed_and_pushed"
    PUSHED_EXISTING = "pushed_existing"
    NOOP = "noop"

logger = logging.getLogger(__name__)

_LATEST_JSON = "latest.json"
_ARCHIVE_GLOB = "archive/*.json"
_HTTPS_USER = "x-access-token"
_PUSH_REFSPEC = "HEAD:refs/heads/main"

# Matches both `git@github.com:owner/repo(.git)?` and `https://github.com/owner/repo(.git)?`.
_ORIGIN_RE = re.compile(
    r"^(?:git@github\.com:|https?://(?:[^@]+@)?github\.com/)"
    r"(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)


def _actor(name_var: str, email_var: str, default_name: str) -> git.Actor:
    return git.Actor(
        os.environ.get(name_var, default_name),
        os.environ.get(email_var, "s7bb-bot@localhost"),
    )


def _resolve_slug(repo: git.Repo) -> str:
    """Return `owner/repo` from GITHUB_REPO_SLUG or by parsing origin."""
    override = os.environ.get("GITHUB_REPO_SLUG", "").strip()
    if override:
        return override

    origin_url = repo.remotes["origin"].url
    m = _ORIGIN_RE.match(origin_url)
    if not m:
        raise RuntimeError(
            f"cannot parse owner/repo from origin URL {origin_url!r}; "
            "set GITHUB_REPO_SLUG=owner/repo to override"
        )
    return f"{m['owner']}/{m['repo']}"


def _push_via_pat(repo: git.Repo, token: str) -> None:
    """Push HEAD to origin/main over HTTPS, delivering token via GIT_ASKPASS."""
    slug = _resolve_slug(repo)
    https_url = f"https://{_HTTPS_USER}@github.com/{slug}.git"

    fd, helper_path = tempfile.mkstemp(prefix="s7bb-askpass-", suffix=".sh")
    try:
        with os.fdopen(fd, "w") as f:
            f.write('#!/bin/sh\nprintf %s "$GITHUB_PAT"\n')
        os.chmod(helper_path, stat.S_IRWXU)  # 0o700

        env = os.environ.copy()
        env["GIT_ASKPASS"] = helper_path
        env["GITHUB_PAT"] = token
        env["GIT_TERMINAL_PROMPT"] = "0"

        repo.git.push(https_url, _PUSH_REFSPEC, env=env)
    finally:
        try:
            os.unlink(helper_path)
        except OSError:
            logger.warning("failed to unlink GIT_ASKPASS helper %s", helper_path)


def _is_ahead_of_origin(repo: git.Repo) -> bool:
    """Return True iff local HEAD has commits that origin/main does not.

    Uses the local `origin/main` ref as-is — caller is responsible for
    refreshing it (e.g. via `origin.fetch()`) when freshness matters.
    """
    try:
        ahead = list(repo.iter_commits("origin/main..HEAD", max_count=1))
    except git.GitCommandError:
        # origin/main ref missing — treat as "nothing to compare against".
        return False
    return bool(ahead)


def push_data(repo_path: Path) -> PushOutcome:
    """Stage data files, commit if changed, then push HEAD to origin/main.

    Always pushes if local HEAD is ahead of origin/main, even when nothing
    new was committed. This prevents silent accumulation of unpushed local
    commits if a previous push failed.

    Raises on git or push errors.
    """
    repo = git.Repo(str(repo_path))

    paths: list[str] = []
    if (repo_path / _LATEST_JSON).exists():
        paths.append(_LATEST_JSON)
    archive_files = sorted((repo_path / "archive").glob("*.json"))
    for f in archive_files:
        paths.append(f.relative_to(repo_path).as_posix())

    if not paths:
        logger.warning("push_data: no data files found, skipping")
        return PushOutcome.NOOP

    repo.index.add(paths)

    committed_new = False
    if repo.index.diff("HEAD"):
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        author = _actor("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "s7bb-bot")
        committer = _actor("GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "s7bb-bot")
        repo.index.commit(
            f"chore: update data {ts}",
            author=author,
            committer=committer,
        )
        committed_new = True

    if not committed_new and not _is_ahead_of_origin(repo):
        logger.info("push_data: nothing to commit and local == origin/main, noop")
        return PushOutcome.NOOP

    token = os.environ.get("GITHUB_PAT", "").strip()
    if not token:
        raise RuntimeError("GITHUB_PAT not set; cannot push to GitHub")

    _push_via_pat(repo, token)

    if committed_new:
        logger.info("push_data: committed and pushed to origin/main (%d file(s))", len(paths))
        return PushOutcome.COMMITTED_AND_PUSHED
    logger.info("push_data: pushed existing commits to origin/main (no new commit)")
    return PushOutcome.PUSHED_EXISTING
