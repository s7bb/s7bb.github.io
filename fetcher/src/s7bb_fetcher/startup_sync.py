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

_DEFAULT_TIMEOUT_SEC = 10.0
_DEFAULT_TOLERANCE_SEC = 60.0


@dataclass(frozen=True)
class SyncResult:
    action: Literal["push", "pull", "noop"]
    local_generated_at: datetime | None
    remote_generated_at: datetime | None
    message: str


def startup_sync(
    repo_path: Path,
    data_path: Path,
    slug: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT_SEC,
    tolerance_seconds: float = _DEFAULT_TOLERANCE_SEC,
) -> SyncResult:
    """Reconcile local data/latest.json with origin/main before scheduler starts.

    Raises on any failure that prevents reconciliation. Caller should treat a
    raise as a hard startup failure.
    """
    logger.info("startup_sync: checking drift against origin/main (%s)", slug)

    local_ts = _read_local_generated_at(data_path)
    remote_body, remote_ts = _fetch_remote(slug, timeout)

    if local_ts is None and remote_ts is None:
        return _result("noop", local_ts, remote_ts, "no local file, remote 404 — nothing to sync")

    if local_ts is not None and remote_ts is not None:
        delta = (local_ts - remote_ts).total_seconds()
        if abs(delta) <= tolerance_seconds:
            return _result(
                "noop", local_ts, remote_ts,
                f"in sync (Δ={delta:+.0f}s, tolerance={tolerance_seconds:.0f}s)",
            )
        # push/pull branches added in next task
        raise NotImplementedError("push/pull branches not yet implemented")

    raise NotImplementedError("one-sided cases not yet implemented")


def _result(
    action: Literal["push", "pull", "noop"],
    local_ts: datetime | None,
    remote_ts: datetime | None,
    message: str,
) -> SyncResult:
    logger.info(
        "startup_sync: action=%s local=%s remote=%s — %s",
        action, local_ts, remote_ts, message,
    )
    return SyncResult(action=action, local_generated_at=local_ts,
                      remote_generated_at=remote_ts, message=message)


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
