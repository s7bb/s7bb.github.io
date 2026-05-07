"""Tests for service._export_job orchestration."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time


def _patch_service(monkeypatch, tmp_path: Path):
    """Patch external IO calls so _export_job has no real side effects."""
    from s7bb_fetcher import service

    monkeypatch.setattr(service, "DATA_DIR", tmp_path)
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "s7bb.db")
    monkeypatch.setattr(service, "OUT_PATH", tmp_path / "latest.json")
    monkeypatch.setattr(service, "REPO_PATH", tmp_path)


@pytest.fixture
def mocks(monkeypatch, tmp_path):
    _patch_service(monkeypatch, tmp_path)

    mock_open_db = MagicMock(return_value=MagicMock(name="conn"))
    mock_export_latest = MagicMock()
    mock_export_monthly = MagicMock()
    mock_export_index = MagicMock()
    mock_push_data = MagicMock(return_value=True)

    monkeypatch.setattr("s7bb_fetcher.storage.open_db", mock_open_db)
    monkeypatch.setattr("s7bb_fetcher.exporter.export_latest", mock_export_latest)
    monkeypatch.setattr("s7bb_fetcher.exporter.export_monthly_archive", mock_export_monthly)
    monkeypatch.setattr("s7bb_fetcher.exporter.export_archive_index", mock_export_index)
    monkeypatch.setattr("s7bb_fetcher.pusher.push_data", mock_push_data)

    return {
        "export_latest": mock_export_latest,
        "export_monthly": mock_export_monthly,
        "export_index": mock_export_index,
        "push_data": mock_push_data,
    }


@freeze_time("2026-05-15T07:00:00+00:00")
def test_export_job_runs_all_archive_steps_mid_month(mocks):
    from s7bb_fetcher.service import _export_job

    _export_job()

    assert mocks["export_latest"].call_count == 1
    monthly_calls = mocks["export_monthly"].call_args_list
    assert len(monthly_calls) == 1
    args, kwargs = monthly_calls[0]
    assert args[1] == 2026
    assert args[2] == 5
    assert kwargs.get("finalized", args[4] if len(args) > 4 else False) is False
    assert mocks["export_index"].call_count == 1
    assert mocks["push_data"].call_count == 1


@freeze_time("2026-05-01T00:00:00+00:00")
def test_export_job_finalizes_prev_month_on_day_one_hour_zero(mocks):
    from s7bb_fetcher.service import _export_job

    _export_job()

    calls = mocks["export_monthly"].call_args_list
    assert len(calls) == 2
    periods = sorted((c.args[1], c.args[2]) for c in calls)
    assert periods == [(2026, 4), (2026, 5)]
    finalized_flags = {(c.args[1], c.args[2]): c.kwargs.get("finalized", False) for c in calls}
    assert finalized_flags[(2026, 4)] is True
    assert finalized_flags[(2026, 5)] is False


@freeze_time("2026-01-01T00:00:00+00:00")
def test_export_job_finalize_handles_year_boundary(mocks):
    from s7bb_fetcher.service import _export_job

    _export_job()

    calls = mocks["export_monthly"].call_args_list
    periods = sorted((c.args[1], c.args[2]) for c in calls)
    assert periods == [(2025, 12), (2026, 1)]


@freeze_time("2026-05-01T01:00:00+00:00")
def test_export_job_skips_finalize_when_not_hour_zero(mocks):
    from s7bb_fetcher.service import _export_job

    _export_job()
    calls = mocks["export_monthly"].call_args_list
    assert len(calls) == 1
    assert (calls[0].args[1], calls[0].args[2]) == (2026, 5)


@freeze_time("2026-05-15T07:00:00+00:00")
def test_export_job_continues_after_archive_failure(mocks):
    """If archive build fails, latest.json + index + push must still attempt."""
    mocks["export_monthly"].side_effect = RuntimeError("disk full")

    from s7bb_fetcher.service import _export_job
    _export_job()  # must NOT raise

    assert mocks["export_latest"].call_count == 1
    assert mocks["export_index"].call_count == 1
    assert mocks["push_data"].call_count == 1


@freeze_time("2026-05-15T07:00:00+00:00")
def test_export_job_continues_after_latest_failure(mocks):
    mocks["export_latest"].side_effect = RuntimeError("boom")

    from s7bb_fetcher.service import _export_job
    _export_job()

    assert mocks["export_monthly"].call_count == 1
    assert mocks["export_index"].call_count == 1
    assert mocks["push_data"].call_count == 1
