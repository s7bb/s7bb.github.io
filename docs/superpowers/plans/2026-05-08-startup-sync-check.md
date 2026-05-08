# Startup Sync Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile local `data/latest.json` with `origin/main` on s7bb-fetcher startup — push if local is newer, pull if remote is newer, hard-fail on any error.

**Architecture:** New module `fetcher/src/s7bb_fetcher/startup_sync.py` providing a single public function `startup_sync(repo_path, data_path, slug)`. Called from `service.main()` after preflight, before `scheduler.start()`. Reads local `generated_at` from `data/latest.json`, fetches remote copy from `raw.githubusercontent.com`, compares timestamps with a ±60 s tolerance band, then dispatches to `pusher.push_data` (push leg) or atomic file replace (pull leg). All failure modes raise; the existing top-level entrypoint exits non-zero.

**Tech Stack:** Python 3.11, `requests==2.33.1`, `gitpython==3.1.49`, `pytest==9.0.3`, `freezegun==1.5.1`. No new dependencies.

**Spec:** [`docs/superpowers/specs/2026-05-08-startup-sync-check-design.md`](../specs/2026-05-08-startup-sync-check-design.md)

---

## File Structure

| File | Role | Status |
|---|---|---|
| `fetcher/src/s7bb_fetcher/startup_sync.py` | New module: `SyncResult`, `startup_sync()`, internal helpers | **create** |
| `fetcher/tests/test_startup_sync.py` | Unit tests for the new module | **create** |
| `fetcher/src/s7bb_fetcher/service.py` | Call `startup_sync` after preflight | **modify** |
| `fetcher/tests/test_service.py` | Assert service invokes `startup_sync` and aborts on its exceptions | **modify** |
| `CHANGELOG.md` | `[Unreleased] / Added` entry | **modify** |
| `README.md` | Brief paragraph under VM Setup | **modify** |

Each task below is one TDD cycle: **write a failing test → run it → write the minimum code → run again → commit.** Steps are bite-sized (2–5 min each).

---

## Task 1: Module skeleton + `SyncResult` dataclass

**Files:**
- Create: `fetcher/src/s7bb_fetcher/startup_sync.py`
- Create: `fetcher/tests/test_startup_sync.py`

- [ ] **Step 1: Write the failing test**

```python
# fetcher/tests/test_startup_sync.py
"""Tests for startup_sync.py."""

from datetime import UTC, datetime

import pytest

from s7bb_fetcher import startup_sync
from s7bb_fetcher.startup_sync import SyncResult


def test_module_exports_expected_symbols():
    assert hasattr(startup_sync, "startup_sync")
    assert hasattr(startup_sync, "SyncResult")


def test_sync_result_is_frozen_dataclass():
    r = SyncResult(
        action="noop",
        local_generated_at=datetime(2026, 5, 8, tzinfo=UTC),
        remote_generated_at=datetime(2026, 5, 8, tzinfo=UTC),
        message="in sync",
    )
    assert r.action == "noop"
    assert r.message == "in sync"
    with pytest.raises((AttributeError, Exception)):
        r.action = "push"  # frozen


def test_sync_result_accepts_none_timestamps():
    r = SyncResult(
        action="push",
        local_generated_at=datetime(2026, 5, 8, tzinfo=UTC),
        remote_generated_at=None,
        message="remote missing",
    )
    assert r.remote_generated_at is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd fetcher
uv run pytest tests/test_startup_sync.py -v
```

Expected: `ModuleNotFoundError: No module named 's7bb_fetcher.startup_sync'`.

- [ ] **Step 3: Write minimal implementation**

```python
# fetcher/src/s7bb_fetcher/startup_sync.py
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_startup_sync.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/startup_sync.py fetcher/tests/test_startup_sync.py
git commit -m "feat(startup-sync): add SyncResult dataclass scaffold"
```

---

## Task 2: `_read_local_generated_at` helper

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/startup_sync.py`
- Modify: `fetcher/tests/test_startup_sync.py`

- [ ] **Step 1: Append failing tests**

Append to `fetcher/tests/test_startup_sync.py`:

```python
import json
from datetime import timedelta
from pathlib import Path

from s7bb_fetcher.startup_sync import _read_local_generated_at


def test_read_local_returns_none_when_file_missing(tmp_path: Path):
    assert _read_local_generated_at(tmp_path / "latest.json") is None


def test_read_local_parses_generated_at(tmp_path: Path):
    p = tmp_path / "latest.json"
    p.write_text(json.dumps({"generated_at": "2026-05-08T10:00:00+00:00"}))
    ts = _read_local_generated_at(p)
    assert ts == datetime(2026, 5, 8, 10, 0, 0, tzinfo=UTC)


def test_read_local_attaches_utc_when_naive(tmp_path: Path):
    p = tmp_path / "latest.json"
    p.write_text(json.dumps({"generated_at": "2026-05-08T10:00:00"}))
    ts = _read_local_generated_at(p)
    assert ts is not None
    assert ts.tzinfo is UTC


def test_read_local_raises_on_garbage_bytes(tmp_path: Path):
    p = tmp_path / "latest.json"
    p.write_text("not json at all")
    with pytest.raises(json.JSONDecodeError):
        _read_local_generated_at(p)


def test_read_local_raises_on_missing_field(tmp_path: Path):
    p = tmp_path / "latest.json"
    p.write_text(json.dumps({"station": "Baierbrunn"}))
    with pytest.raises(KeyError):
        _read_local_generated_at(p)


def test_read_local_raises_on_bad_iso(tmp_path: Path):
    p = tmp_path / "latest.json"
    p.write_text(json.dumps({"generated_at": "not-a-timestamp"}))
    with pytest.raises(ValueError):
        _read_local_generated_at(p)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_startup_sync.py -v
```

Expected: 6 failures with `ImportError: cannot import name '_read_local_generated_at'`.

- [ ] **Step 3: Implement helper**

Append to `fetcher/src/s7bb_fetcher/startup_sync.py`:

```python
import json
from datetime import UTC
from pathlib import Path


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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_startup_sync.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/startup_sync.py fetcher/tests/test_startup_sync.py
git commit -m "feat(startup-sync): add _read_local_generated_at helper"
```

---

## Task 3: `_fetch_remote` helper

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/startup_sync.py`
- Modify: `fetcher/tests/test_startup_sync.py`

- [ ] **Step 1: Append failing tests**

Append to `fetcher/tests/test_startup_sync.py`:

```python
from unittest.mock import MagicMock, patch

import requests

from s7bb_fetcher.startup_sync import _fetch_remote


def _mock_response(status_code: int, body: bytes = b"") -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.content = body
    if status_code >= 400 and status_code != 404:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"{status_code} error"
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_fetch_remote_returns_body_and_timestamp_on_200():
    body = json.dumps({"generated_at": "2026-05-08T11:00:00+00:00"}).encode()
    with patch("s7bb_fetcher.startup_sync.requests.get",
               return_value=_mock_response(200, body)) as get:
        raw, ts = _fetch_remote("owner/repo", timeout=5.0)
    get.assert_called_once_with(
        "https://raw.githubusercontent.com/owner/repo/main/data/latest.json",
        timeout=5.0,
    )
    assert raw == body
    assert ts == datetime(2026, 5, 8, 11, 0, 0, tzinfo=UTC)


def test_fetch_remote_returns_none_pair_on_404():
    with patch("s7bb_fetcher.startup_sync.requests.get",
               return_value=_mock_response(404)):
        raw, ts = _fetch_remote("owner/repo", timeout=5.0)
    assert raw is None
    assert ts is None


def test_fetch_remote_raises_on_500():
    with patch("s7bb_fetcher.startup_sync.requests.get",
               return_value=_mock_response(500)):
        with pytest.raises(requests.exceptions.HTTPError):
            _fetch_remote("owner/repo", timeout=5.0)


def test_fetch_remote_raises_on_timeout():
    with patch("s7bb_fetcher.startup_sync.requests.get",
               side_effect=requests.exceptions.Timeout("slow")):
        with pytest.raises(requests.exceptions.Timeout):
            _fetch_remote("owner/repo", timeout=5.0)


def test_fetch_remote_raises_on_malformed_json():
    with patch("s7bb_fetcher.startup_sync.requests.get",
               return_value=_mock_response(200, b"not json")):
        with pytest.raises(json.JSONDecodeError):
            _fetch_remote("owner/repo", timeout=5.0)


def test_fetch_remote_raises_on_missing_generated_at():
    body = json.dumps({"station": "Baierbrunn"}).encode()
    with patch("s7bb_fetcher.startup_sync.requests.get",
               return_value=_mock_response(200, body)):
        with pytest.raises(KeyError):
            _fetch_remote("owner/repo", timeout=5.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_startup_sync.py -v
```

Expected: 6 failures, `ImportError: cannot import name '_fetch_remote'`.

- [ ] **Step 3: Implement helper**

Append to `fetcher/src/s7bb_fetcher/startup_sync.py`:

```python
import requests

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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_startup_sync.py -v
```

Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/startup_sync.py fetcher/tests/test_startup_sync.py
git commit -m "feat(startup-sync): add _fetch_remote helper"
```

---

## Task 4: `_pull` atomic-write helper

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/startup_sync.py`
- Modify: `fetcher/tests/test_startup_sync.py`

- [ ] **Step 1: Append failing tests**

Append to `fetcher/tests/test_startup_sync.py`:

```python
from s7bb_fetcher.startup_sync import _pull


def test_pull_writes_bytes_to_target(tmp_path: Path):
    target = tmp_path / "data" / "latest.json"
    _pull(target, b'{"hello":"world"}')
    assert target.read_bytes() == b'{"hello":"world"}'


def test_pull_creates_parent_directory(tmp_path: Path):
    target = tmp_path / "deep" / "nested" / "latest.json"
    _pull(target, b"{}")
    assert target.exists()


def test_pull_overwrites_existing_file(tmp_path: Path):
    target = tmp_path / "latest.json"
    target.write_bytes(b"old")
    _pull(target, b"new")
    assert target.read_bytes() == b"new"


def test_pull_leaves_no_tmp_files_on_success(tmp_path: Path):
    target = tmp_path / "latest.json"
    _pull(target, b"{}")
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert leftovers == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_startup_sync.py -v
```

Expected: 4 failures, `ImportError: cannot import name '_pull'`.

- [ ] **Step 3: Implement helper**

Append to `fetcher/src/s7bb_fetcher/startup_sync.py`:

```python
import os
import tempfile


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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_startup_sync.py -v
```

Expected: 19 passed.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/startup_sync.py fetcher/tests/test_startup_sync.py
git commit -m "feat(startup-sync): add _pull atomic-write helper"
```

---

## Task 5: `startup_sync` orchestration — noop branches

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/startup_sync.py`
- Modify: `fetcher/tests/test_startup_sync.py`

The function compares timestamps using a ±60 s tolerance band so the service does not push or pull when local and remote agree within plausible clock skew.

- [ ] **Step 1: Append failing tests**

Append to `fetcher/tests/test_startup_sync.py`:

```python
def _write_latest(path: Path, generated_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"generated_at": generated_at.isoformat()}))


def test_sync_noop_when_no_local_no_remote(tmp_path: Path):
    data_path = tmp_path / "data" / "latest.json"
    with patch("s7bb_fetcher.startup_sync._fetch_remote",
               return_value=(None, None)):
        result = startup_sync.startup_sync(tmp_path, data_path, "owner/repo")
    assert result.action == "noop"
    assert result.local_generated_at is None
    assert result.remote_generated_at is None


def test_sync_noop_when_equal_timestamps(tmp_path: Path):
    data_path = tmp_path / "data" / "latest.json"
    ts = datetime(2026, 5, 8, 10, 0, 0, tzinfo=UTC)
    _write_latest(data_path, ts)
    body = json.dumps({"generated_at": ts.isoformat()}).encode()
    with patch("s7bb_fetcher.startup_sync._fetch_remote",
               return_value=(body, ts)):
        result = startup_sync.startup_sync(tmp_path, data_path, "owner/repo")
    assert result.action == "noop"


def test_sync_noop_when_within_tolerance(tmp_path: Path):
    data_path = tmp_path / "data" / "latest.json"
    local_ts = datetime(2026, 5, 8, 10, 0, 30, tzinfo=UTC)  # +30 s
    remote_ts = datetime(2026, 5, 8, 10, 0, 0, tzinfo=UTC)
    _write_latest(data_path, local_ts)
    body = json.dumps({"generated_at": remote_ts.isoformat()}).encode()
    with patch("s7bb_fetcher.startup_sync._fetch_remote",
               return_value=(body, remote_ts)):
        result = startup_sync.startup_sync(tmp_path, data_path, "owner/repo")
    assert result.action == "noop"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_startup_sync.py -v
```

Expected: 3 failures, `AttributeError: module 's7bb_fetcher.startup_sync' has no attribute 'startup_sync'`.

- [ ] **Step 3: Implement orchestration (noop only)**

Append to `fetcher/src/s7bb_fetcher/startup_sync.py`:

```python
_DEFAULT_TIMEOUT_SEC = 10.0
_DEFAULT_TOLERANCE_SEC = 60.0


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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_startup_sync.py -v
```

Expected: 22 passed.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/startup_sync.py fetcher/tests/test_startup_sync.py
git commit -m "feat(startup-sync): implement noop branches with tolerance band"
```

---

## Task 6: `startup_sync` push branches

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/startup_sync.py`
- Modify: `fetcher/tests/test_startup_sync.py`

- [ ] **Step 1: Append failing tests**

Append to `fetcher/tests/test_startup_sync.py`:

```python
def test_sync_pushes_when_local_newer(tmp_path: Path):
    data_path = tmp_path / "data" / "latest.json"
    local_ts = datetime(2026, 5, 8, 11, 0, 0, tzinfo=UTC)
    remote_ts = datetime(2026, 5, 8, 10, 0, 0, tzinfo=UTC)  # 1 h older
    _write_latest(data_path, local_ts)
    body = json.dumps({"generated_at": remote_ts.isoformat()}).encode()
    with patch("s7bb_fetcher.startup_sync._fetch_remote",
               return_value=(body, remote_ts)), \
         patch("s7bb_fetcher.startup_sync.pusher.push_data",
               return_value=True) as push:
        result = startup_sync.startup_sync(tmp_path, data_path, "owner/repo")
    push.assert_called_once_with(tmp_path)
    assert result.action == "push"
    assert "newer" in result.message.lower()


def test_sync_pushes_when_remote_404_and_local_present(tmp_path: Path):
    data_path = tmp_path / "data" / "latest.json"
    local_ts = datetime(2026, 5, 8, 10, 0, 0, tzinfo=UTC)
    _write_latest(data_path, local_ts)
    with patch("s7bb_fetcher.startup_sync._fetch_remote",
               return_value=(None, None)), \
         patch("s7bb_fetcher.startup_sync.pusher.push_data",
               return_value=True) as push:
        result = startup_sync.startup_sync(tmp_path, data_path, "owner/repo")
    push.assert_called_once_with(tmp_path)
    assert result.action == "push"


def test_sync_push_clean_tree_warns_no_raise(tmp_path: Path, caplog):
    data_path = tmp_path / "data" / "latest.json"
    local_ts = datetime(2026, 5, 8, 11, 0, 0, tzinfo=UTC)
    remote_ts = datetime(2026, 5, 8, 10, 0, 0, tzinfo=UTC)
    _write_latest(data_path, local_ts)
    body = json.dumps({"generated_at": remote_ts.isoformat()}).encode()
    with patch("s7bb_fetcher.startup_sync._fetch_remote",
               return_value=(body, remote_ts)), \
         patch("s7bb_fetcher.startup_sync.pusher.push_data",
               return_value=False):
        with caplog.at_level(logging.WARNING, logger="s7bb_fetcher.startup_sync"):
            result = startup_sync.startup_sync(tmp_path, data_path, "owner/repo")
    assert result.action == "push"
    assert any("matches HEAD" in r.message for r in caplog.records)
```

Add at the top of the file if not already present:

```python
import logging
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_startup_sync.py -v
```

Expected: 3 failures, `NotImplementedError`.

- [ ] **Step 3: Wire push branches**

In `fetcher/src/s7bb_fetcher/startup_sync.py`, add a `pusher` import at the top and replace the `raise NotImplementedError(...)` lines. Top of file:

```python
from . import pusher
```

Replace the body of `startup_sync` after the noop guard with the full decision tree:

```python
    if local_ts is not None and remote_ts is None:
        # remote missing — push local
        _push(repo_path)
        return _result("push", local_ts, remote_ts, "remote 404 — pushed local")

    if local_ts is None and remote_ts is not None:
        # bootstrap local from remote — implemented in Task 7
        raise NotImplementedError("pull branch not yet implemented")

    # both present
    delta = (local_ts - remote_ts).total_seconds()
    if abs(delta) <= tolerance_seconds:
        return _result(
            "noop", local_ts, remote_ts,
            f"in sync (Δ={delta:+.0f}s, tolerance={tolerance_seconds:.0f}s)",
        )
    if delta > 0:
        _push(repo_path)
        return _result(
            "push", local_ts, remote_ts,
            f"local newer by {delta:.0f}s — pushed",
        )
    # delta < 0 — pull (Task 7)
    raise NotImplementedError("pull branch not yet implemented")
```

Restructure: the function now reads top-to-bottom: load timestamps, dispatch by case. Replace the whole body (after the `_fetch_remote` call) with the version above. Then add the `_push` helper:

```python
def _push(repo_path: Path) -> None:
    pushed = pusher.push_data(repo_path)
    if not pushed:
        logger.warning(
            "startup_sync: local generated_at is newer but git working tree "
            "matches HEAD; nothing to commit"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_startup_sync.py -v
```

Expected: 25 passed.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/startup_sync.py fetcher/tests/test_startup_sync.py
git commit -m "feat(startup-sync): implement push branches"
```

---

## Task 7: `startup_sync` pull branches

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/startup_sync.py`
- Modify: `fetcher/tests/test_startup_sync.py`

- [ ] **Step 1: Append failing tests**

Append to `fetcher/tests/test_startup_sync.py`:

```python
def test_sync_pulls_when_remote_newer(tmp_path: Path):
    data_path = tmp_path / "data" / "latest.json"
    local_ts = datetime(2026, 5, 8, 9, 0, 0, tzinfo=UTC)
    remote_ts = datetime(2026, 5, 8, 11, 0, 0, tzinfo=UTC)
    _write_latest(data_path, local_ts)
    remote_body = json.dumps({
        "generated_at": remote_ts.isoformat(),
        "marker": "from-remote",
    }).encode()
    with patch("s7bb_fetcher.startup_sync._fetch_remote",
               return_value=(remote_body, remote_ts)), \
         patch("s7bb_fetcher.startup_sync.pusher.push_data") as push:
        result = startup_sync.startup_sync(tmp_path, data_path, "owner/repo")
    push.assert_not_called()
    assert result.action == "pull"
    assert data_path.read_bytes() == remote_body


def test_sync_pulls_when_no_local_remote_present(tmp_path: Path):
    data_path = tmp_path / "data" / "latest.json"
    remote_ts = datetime(2026, 5, 8, 11, 0, 0, tzinfo=UTC)
    remote_body = json.dumps({"generated_at": remote_ts.isoformat()}).encode()
    with patch("s7bb_fetcher.startup_sync._fetch_remote",
               return_value=(remote_body, remote_ts)), \
         patch("s7bb_fetcher.startup_sync.pusher.push_data") as push:
        result = startup_sync.startup_sync(tmp_path, data_path, "owner/repo")
    push.assert_not_called()
    assert result.action == "pull"
    assert data_path.read_bytes() == remote_body
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_startup_sync.py -v
```

Expected: 2 failures, `NotImplementedError("pull branch not yet implemented")`.

- [ ] **Step 3: Wire pull branches**

In `fetcher/src/s7bb_fetcher/startup_sync.py`, replace the two `raise NotImplementedError("pull branch not yet implemented")` lines with calls to `_pull` and `_result`:

For the `local_ts is None and remote_ts is not None` case:

```python
    if local_ts is None and remote_ts is not None:
        _pull(data_path, remote_body)
        return _result(
            "pull", local_ts, remote_ts,
            "no local file — pulled remote",
        )
```

For the `delta < 0` case at the bottom of the function:

```python
    # delta < 0 — remote newer, pull
    _pull(data_path, remote_body)
    return _result(
        "pull", local_ts, remote_ts,
        f"remote newer by {-delta:.0f}s — pulled",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_startup_sync.py -v
```

Expected: 27 passed.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/startup_sync.py fetcher/tests/test_startup_sync.py
git commit -m "feat(startup-sync): implement pull branches"
```

---

## Task 8: Error propagation tests

**Files:**
- Modify: `fetcher/tests/test_startup_sync.py`

These tests confirm `startup_sync` propagates exceptions from its dependencies rather than swallowing them. The implementation already does this — these tests document and lock in the behavior.

- [ ] **Step 1: Append failing tests**

Append to `fetcher/tests/test_startup_sync.py`:

```python
def test_sync_propagates_remote_500(tmp_path: Path):
    data_path = tmp_path / "data" / "latest.json"
    _write_latest(data_path, datetime(2026, 5, 8, 10, 0, 0, tzinfo=UTC))
    with patch("s7bb_fetcher.startup_sync.requests.get",
               return_value=_mock_response(500)):
        with pytest.raises(requests.exceptions.HTTPError):
            startup_sync.startup_sync(tmp_path, data_path, "owner/repo")


def test_sync_propagates_local_garbage(tmp_path: Path):
    data_path = tmp_path / "data" / "latest.json"
    data_path.parent.mkdir()
    data_path.write_text("not json")
    # _read_local_generated_at runs before _fetch_remote, so we don't even
    # need to mock the remote; the exception fires first.
    with pytest.raises(json.JSONDecodeError):
        startup_sync.startup_sync(tmp_path, data_path, "owner/repo")


def test_sync_propagates_push_failure(tmp_path: Path):
    data_path = tmp_path / "data" / "latest.json"
    local_ts = datetime(2026, 5, 8, 11, 0, 0, tzinfo=UTC)
    remote_ts = datetime(2026, 5, 8, 10, 0, 0, tzinfo=UTC)
    _write_latest(data_path, local_ts)
    body = json.dumps({"generated_at": remote_ts.isoformat()}).encode()
    with patch("s7bb_fetcher.startup_sync._fetch_remote",
               return_value=(body, remote_ts)), \
         patch("s7bb_fetcher.startup_sync.pusher.push_data",
               side_effect=RuntimeError("auth failed")):
        with pytest.raises(RuntimeError, match="auth failed"):
            startup_sync.startup_sync(tmp_path, data_path, "owner/repo")


def test_sync_propagates_pull_write_failure(tmp_path: Path, monkeypatch):
    data_path = tmp_path / "data" / "latest.json"
    local_ts = datetime(2026, 5, 8, 9, 0, 0, tzinfo=UTC)
    remote_ts = datetime(2026, 5, 8, 11, 0, 0, tzinfo=UTC)
    _write_latest(data_path, local_ts)
    body = json.dumps({"generated_at": remote_ts.isoformat()}).encode()

    def boom(*a, **kw):
        raise OSError("disk full")

    with patch("s7bb_fetcher.startup_sync._fetch_remote",
               return_value=(body, remote_ts)):
        monkeypatch.setattr("s7bb_fetcher.startup_sync._pull", boom)
        with pytest.raises(OSError, match="disk full"):
            startup_sync.startup_sync(tmp_path, data_path, "owner/repo")
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
uv run pytest tests/test_startup_sync.py -v
```

Expected: 31 passed (no implementation changes needed — these document existing behavior).

- [ ] **Step 3: Lint check**

```bash
uv run ruff check src/s7bb_fetcher/startup_sync.py tests/test_startup_sync.py
```

Expected: `All checks passed!`. If imports are out of order, run `uv run ruff check --fix` and re-run.

- [ ] **Step 4: Commit**

```bash
git add fetcher/tests/test_startup_sync.py
git commit -m "test(startup-sync): cover error-propagation paths"
```

---

## Task 9: Service integration

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/service.py`
- Modify: `fetcher/tests/test_service.py`

- [ ] **Step 1: Add failing tests**

Append to `fetcher/tests/test_service.py`:

```python
def test_main_calls_startup_sync_after_preflight(monkeypatch, tmp_path):
    """service.main() must call startup_sync.startup_sync after preflight
    succeeds and before scheduler.start()."""
    _patch_service(monkeypatch, tmp_path)

    # Preflight passes
    monkeypatch.setattr(
        preflight, "run",
        lambda **kw: [Check(name="ok", severity=Severity.HARD, ok=True, message="")],
    )

    # Track ordering between startup_sync and scheduler.start
    order = []

    mock_sync = MagicMock(side_effect=lambda *a, **kw: order.append("sync"))
    mock_scheduler_cls = MagicMock()
    mock_scheduler = mock_scheduler_cls.return_value
    mock_scheduler.start.side_effect = lambda: order.append("start")

    monkeypatch.setattr("s7bb_fetcher.startup_sync.startup_sync", mock_sync)
    monkeypatch.setattr("s7bb_fetcher.service.BlockingScheduler", mock_scheduler_cls)
    # Pretend slug resolution succeeds
    monkeypatch.setattr(
        "s7bb_fetcher.pusher._resolve_slug",
        lambda repo: "owner/repo",
    )

    from s7bb_fetcher.service import main
    main()

    assert mock_sync.call_count == 1
    assert order == ["sync", "start"]


def test_main_aborts_when_startup_sync_raises(monkeypatch, tmp_path):
    _patch_service(monkeypatch, tmp_path)

    monkeypatch.setattr(
        preflight, "run",
        lambda **kw: [Check(name="ok", severity=Severity.HARD, ok=True, message="")],
    )

    mock_scheduler_cls = MagicMock()
    monkeypatch.setattr("s7bb_fetcher.service.BlockingScheduler", mock_scheduler_cls)
    monkeypatch.setattr(
        "s7bb_fetcher.pusher._resolve_slug",
        lambda repo: "owner/repo",
    )
    monkeypatch.setattr(
        "s7bb_fetcher.startup_sync.startup_sync",
        MagicMock(side_effect=RuntimeError("network down")),
    )

    from s7bb_fetcher.service import main
    with pytest.raises(RuntimeError, match="network down"):
        main()
    mock_scheduler_cls.return_value.start.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_service.py -v
```

Expected: 2 failures (no startup_sync call yet).

- [ ] **Step 3: Modify `service.py`**

In `fetcher/src/s7bb_fetcher/service.py`, after the preflight `if hard_failed: raise PreflightFailed(...)` block and before `scheduler = BlockingScheduler()`, insert:

```python
    from . import pusher, startup_sync as _startup_sync
    import git

    slug = pusher._resolve_slug(git.Repo(str(REPO_PATH)))
    sync_result = _startup_sync.startup_sync(REPO_PATH, OUT_PATH, slug)
    logger.info(
        "startup_sync done: action=%s message=%s",
        sync_result.action, sync_result.message,
    )
```

The local-import keeps the module load cost out of unit tests that import `service` without exercising `main`.

- [ ] **Step 4: Run all fetcher tests**

```bash
uv run pytest -v
```

Expected: all passing (31 startup_sync tests + existing suite + 2 new service tests).

- [ ] **Step 5: Lint**

```bash
uv run ruff check src tests
```

Expected: `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add fetcher/src/s7bb_fetcher/service.py fetcher/tests/test_service.py
git commit -m "feat(service): run startup_sync after preflight, before scheduler"
```

---

## Task 10: CHANGELOG + README

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 1: Read current CHANGELOG**

```bash
head -40 CHANGELOG.md
```

Locate the `## [Unreleased]` section and the `### Added` subsection (create one if absent).

- [ ] **Step 2: Add CHANGELOG entry**

Under `## [Unreleased]` → `### Added`, add:

```markdown
- Startup sync check: on s7bb-fetcher startup, after preflight and before the scheduler runs, reconcile `data/latest.json` with `origin/main`. Pushes the local file when it is newer (avoids waiting up to an hour for the next hourly export); overwrites the local file with the remote bytes when remote is newer (handles VM rollback). Hard-fails startup on network, parse, or push errors.
```

- [ ] **Step 3: Read current README**

```bash
grep -n "VM Setup\|Startup\|preflight" README.md
```

- [ ] **Step 4: Add README paragraph**

In `README.md`, find the "VM Setup" section (or wherever startup behavior is described — same place that mentions `s7bb-preflight` or the systemd/docker-compose unit). Add:

```markdown
**Startup sequence.** When `s7bb-service` starts, it runs preflight checks (volumes, git, SQLite, GitHub PAT) and then a startup sync against `origin/main`: if local `data/latest.json` is newer than the published copy, it is pushed immediately; if remote is newer, the remote bytes overwrite the local file. The scheduler does not start until both succeed — any error aborts startup so an operator notices the divergence.
```

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs(startup-sync): add CHANGELOG entry and README startup section"
```

---

## Task 11: End-to-end verification

**Files:** none modified.

- [ ] **Step 1: Run the full fetcher test suite**

```bash
cd fetcher
uv run pytest -v
```

Expected: every test passes; new file `tests/test_startup_sync.py` reports 31 passing tests.

- [ ] **Step 2: Run lint**

```bash
uv run ruff check src tests
```

Expected: `All checks passed!`.

- [ ] **Step 3: Smoke-test the help / module import**

```bash
uv run python -c "from s7bb_fetcher import startup_sync; print(startup_sync.startup_sync.__doc__)"
```

Expected: prints the function docstring.

- [ ] **Step 4: Verify CHANGELOG and README rendered well**

```bash
grep -A3 "Unreleased" CHANGELOG.md | head -10
grep -A3 "Startup sequence" README.md | head -10
```

Expected: both excerpts visible and complete.

- [ ] **Step 5: Final commit if anything was touched during verification**

If steps 1-4 produced any fixups, commit them with a single `chore: address verification feedback` commit. Otherwise nothing to commit — done.

---

## Out of scope (do not implement here)

- A `s7bb-sync` CLI entrypoint — the spec keeps reconciliation as a service-internal step. Add later if operators need ad-hoc invocation.
- Reconciliation of `data/archive/*.json` — append-only files; the existing hourly export covers them.
- Soft-fail flag (`STARTUP_SYNC_BEST_EFFORT=true`) — the design hard-fails by choice; revisit if flaky networks cause restart loops.
- Multi-runner coordination — single-VM deployment, intentionally last-write-wins.
