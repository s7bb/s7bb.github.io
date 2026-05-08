"""Reconcile local data/latest.json with origin/main at service startup.

On startup, before the scheduler begins, this module compares the local
``data/latest.json`` against the copy published on ``origin/main`` and
either pushes the local file (if local is newer), overwrites local with
the remote bytes (if remote is newer), or does nothing (if they are in
sync within a small clock-skew tolerance).

All failure modes raise. The caller treats any raise as a hard startup
failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncResult:
    action: Literal["push", "pull", "noop"]
    local_generated_at: datetime | None
    remote_generated_at: datetime | None
    message: str


def startup_sync() -> SyncResult:
    """Reconcile local and remote data/latest.json at startup.

    Returns:
        SyncResult describing the action taken (push, pull, or noop).

    Raises:
        Various exceptions on network or I/O failure.
    """
    raise NotImplementedError
