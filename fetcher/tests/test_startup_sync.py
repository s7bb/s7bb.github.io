"""Tests for startup_sync.py."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from s7bb_fetcher import startup_sync
from s7bb_fetcher.startup_sync import (
    SyncResult,
    _fetch_remote,
    _pull,
    _read_local_generated_at,
)


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


# ---------------------------------------------------------------------------
# Task 4: _pull atomic-write helper
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Task 5: orchestration — noop branches
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Task 6: push branches
# ---------------------------------------------------------------------------


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
    import logging as _logging
    data_path = tmp_path / "data" / "latest.json"
    local_ts = datetime(2026, 5, 8, 11, 0, 0, tzinfo=UTC)
    remote_ts = datetime(2026, 5, 8, 10, 0, 0, tzinfo=UTC)
    _write_latest(data_path, local_ts)
    body = json.dumps({"generated_at": remote_ts.isoformat()}).encode()
    with patch("s7bb_fetcher.startup_sync._fetch_remote",
               return_value=(body, remote_ts)), \
         patch("s7bb_fetcher.startup_sync.pusher.push_data",
               return_value=False):
        with caplog.at_level(_logging.WARNING, logger="s7bb_fetcher.startup_sync"):
            result = startup_sync.startup_sync(tmp_path, data_path, "owner/repo")
    assert result.action == "push"
    assert any("matches HEAD" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Task 7: pull branches
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Task 8: error-propagation paths
# ---------------------------------------------------------------------------


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


def test_sync_pushes_just_outside_tolerance(tmp_path: Path):
    """Δ = 90 s (> 60 s tolerance) → push."""
    data_path = tmp_path / "data" / "latest.json"
    local_ts = datetime(2026, 5, 8, 10, 1, 30, tzinfo=UTC)
    remote_ts = datetime(2026, 5, 8, 10, 0, 0, tzinfo=UTC)  # 90 s older
    _write_latest(data_path, local_ts)
    body = json.dumps({"generated_at": remote_ts.isoformat()}).encode()
    with patch("s7bb_fetcher.startup_sync._fetch_remote",
               return_value=(body, remote_ts)), \
         patch("s7bb_fetcher.startup_sync.pusher.push_data",
               return_value=True) as push:
        result = startup_sync.startup_sync(tmp_path, data_path, "owner/repo")
    push.assert_called_once_with(tmp_path)
    assert result.action == "push"


def test_sync_logs_error_before_raising(tmp_path: Path, caplog):
    import logging as _logging
    data_path = tmp_path / "data" / "latest.json"
    _write_latest(data_path, datetime(2026, 5, 8, 10, 0, 0, tzinfo=UTC))
    with patch("s7bb_fetcher.startup_sync.requests.get",
               return_value=_mock_response(500)), \
         caplog.at_level(_logging.ERROR, logger="s7bb_fetcher.startup_sync"), \
         pytest.raises(requests.exceptions.HTTPError):
        startup_sync.startup_sync(tmp_path, data_path, "owner/repo")
    assert any(
        r.levelno == _logging.ERROR and "startup_sync failed" in r.message
        for r in caplog.records
    )
