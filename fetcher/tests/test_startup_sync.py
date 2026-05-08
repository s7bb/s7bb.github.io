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


# ---------------------------------------------------------------------------
# Task 3: _fetch_remote
# ---------------------------------------------------------------------------

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
