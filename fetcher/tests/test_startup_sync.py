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


# ---------------------------------------------------------------------------
# Task 2: _read_local_generated_at
# ---------------------------------------------------------------------------

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
