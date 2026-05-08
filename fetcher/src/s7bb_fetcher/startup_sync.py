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
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import requests

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncResult:
    action: Literal["push", "pull", "noop"]
    local_generated_at: datetime | None
    remote_generated_at: datetime | None
    message: str


def startup_sync(*args, **kwargs) -> SyncResult:
    raise NotImplementedError


def _pull(data_path: Path, raw_bytes: bytes) -> None:
    """Atomically replace ``data_path`` with ``raw_bytes``.

    The temp file lives in the same directory so ``os.replace`` is atomic on
    POSIX. Cleans up the temp file if writing fails.
    """
    data_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{data_path.name}.", suffix=".tmp", dir=str(data_path.parent)
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw_bytes)
        os.replace(tmp, data_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


_RAW_URL_TMPL = "https://raw.githubusercontent.com/{slug}/main/data/latest.json"


def _fetch_remote(slug: str, timeout: float) -> tuple[bytes | None, datetime | None]:
    """GET data/latest.json from origin/main via raw.githubusercontent.com.

    Returns ``(body_bytes, generated_at)`` on 200, or ``(None, None)`` on 404.
    Raises on any other HTTP error, network error, or unparseable response.
    """
    url = _RAW_URL_TMPL.format(slug=slug)
    resp = requests.get(url, timeout=timeout)
    if resp.status_code == 404:
        return None, None
    resp.raise_for_status()
    body = resp.content
    payload = json.loads(body)
    raw = payload["generated_at"]
    ts = datetime.fromisoformat(raw)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return body, ts


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
