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

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncResult:
    action: Literal["push", "pull", "noop"]
    local_generated_at: datetime | None
    remote_generated_at: datetime | None
    message: str


def startup_sync(*args, **kwargs) -> SyncResult:
    raise NotImplementedError


def _read_local_generated_at(path: Path) -> datetime | None:
    """Return ``generated_at`` from ``path`` as a tz-aware datetime, or None
    if the file does not exist. Raises if the file is unreadable, not JSON,
    missing the ``generated_at`` key, or has an unparseable ISO timestamp."""
    if not path.exists():
        return None
    payload = json.loads(path.read_bytes())
    raw = payload["generated_at"]
    ts = datetime.fromisoformat(raw)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts
