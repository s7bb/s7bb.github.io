"""Startup preflight checks for the s7bb-fetcher service.

Validates volume access, git repo writability and ownership, SQLite DB
integrity, and GitHub PAT/repo access. Hard-fail checks abort startup;
soft-fail checks log a warning and let the service continue.
"""

from __future__ import annotations

import enum
import logging
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

import git

from .storage import open_db

logger = logging.getLogger(__name__)


class Severity(enum.Enum):
    HARD = "hard"
    SOFT = "soft"


@dataclass(frozen=True)
class Check:
    name: str
    severity: Severity
    ok: bool
    message: str


class PreflightFailed(RuntimeError):
    """Raised when one or more hard preflight checks fail."""


def _check_data_writable(data_dir: Path) -> Check:
    name = "data_writable"
    if not data_dir.exists():
        return Check(name, Severity.HARD, False, f"{data_dir} does not exist")
    if not data_dir.is_dir():
        return Check(name, Severity.HARD, False, f"{data_dir} is not a directory")
    try:
        fd, path = tempfile.mkstemp(prefix=".preflight-", dir=str(data_dir))
        os.close(fd)
        os.unlink(path)
    except PermissionError as e:
        return Check(name, Severity.HARD, False, f"permission denied writing to {data_dir}: {e}")
    except OSError as e:
        return Check(name, Severity.HARD, False, f"cannot write to {data_dir}: {e}")
    return Check(name, Severity.HARD, True, f"{data_dir} is writable")


def _check_repo_writable(repo_path: Path) -> Check:
    name = "repo_writable"
    if not repo_path.exists():
        return Check(name, Severity.HARD, False, f"{repo_path} does not exist")
    try:
        git.Repo(str(repo_path))
    except git.InvalidGitRepositoryError:
        return Check(name, Severity.HARD, False, f"{repo_path} is not a git repository")
    except git.NoSuchPathError:
        return Check(name, Severity.HARD, False, f"{repo_path} has no git directory")
    try:
        fd, path = tempfile.mkstemp(prefix=".preflight-", dir=str(repo_path))
        os.close(fd)
        os.unlink(path)
    except PermissionError as e:
        return Check(name, Severity.HARD, False, f"permission denied writing to {repo_path}: {e}")
    except OSError as e:
        return Check(name, Severity.HARD, False, f"cannot write to {repo_path}: {e}")
    return Check(name, Severity.HARD, True, f"{repo_path} is writable and git-readable")


def _check_repo_ownership(repo_path: Path) -> Check:
    name = "repo_ownership"
    try:
        repo = git.Repo(str(repo_path))
        repo.git.status()
    except git.InvalidGitRepositoryError:
        return Check(name, Severity.HARD, False, f"{repo_path} is not a git repository")
    except git.NoSuchPathError:
        return Check(name, Severity.HARD, False, f"{repo_path} does not exist")
    except git.exc.GitCommandError as e:
        stderr = (e.stderr or "").strip()
        if "dubious ownership" in stderr.lower():
            return Check(
                name,
                Severity.HARD,
                False,
                f"git refuses to use {repo_path}: dubious ownership detected. "
                f"Fix host mount ownership to match the container user, "
                f"or set GIT_SAFE_DIRECTORY={repo_path} in .env.",
            )
        return Check(name, Severity.HARD, False, f"git status failed: {stderr or e}")
    return Check(name, Severity.HARD, True, f"git accepts {repo_path}")


def _check_sqlite(db_path: Path) -> Check:
    name = "sqlite"
    try:
        conn = open_db(db_path)
    except sqlite3.DatabaseError as e:
        return Check(name, Severity.HARD, False, f"{db_path} is not a valid SQLite database: {e}")
    except PermissionError as e:
        return Check(name, Severity.HARD, False, f"cannot create DB at {db_path}: {e}")
    except OSError as e:
        return Check(name, Severity.HARD, False, f"cannot open DB at {db_path}: {e}")
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        result = row[0] if row else "(no result)"
        if result != "ok":
            return Check(name, Severity.HARD, False, f"integrity_check returned: {result}")
    except sqlite3.DatabaseError as e:
        return Check(name, Severity.HARD, False, f"integrity_check failed: {e}")
    finally:
        conn.close()
    return Check(name, Severity.HARD, True, f"{db_path} opens and integrity_check=ok")


def run(*_args, **_kwargs) -> list[Check]:
    """Placeholder; later tasks fill this in."""
    return []
