"""Startup preflight checks for the s7bb-fetcher service.

Validates volume access, git repo writability and ownership, SQLite DB
integrity, and GitHub PAT/repo access. Hard-fail checks abort startup;
soft-fail checks log a warning and let the service continue.
"""

from __future__ import annotations

import enum
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

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


def run(*_args, **_kwargs) -> list[Check]:
    """Placeholder; later tasks fill this in."""
    return []
