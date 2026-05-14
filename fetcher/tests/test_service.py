"""Tests for service._export_job orchestration."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from freezegun import freeze_time

from s7bb_fetcher import preflight, service
from s7bb_fetcher.preflight import Check, PreflightFailed, Severity


def _patch_service(monkeypatch, tmp_path: Path):
    """Patch external IO calls so _export_job has no real side effects."""
    from s7bb_fetcher import service

    monkeypatch.setattr(service, "DATA_DIR", tmp_path)
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "s7bb.db")
    monkeypatch.setattr(service, "OUT_PATH", tmp_path / "latest.json")
    monkeypatch.setattr(service, "REPO_PATH", tmp_path)
    monkeypatch.setattr(service, "ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(service, "INDEX_PATH", tmp_path / "archive" / "index.json")


@pytest.fixture
def mocks(monkeypatch, tmp_path):
    _patch_service(monkeypatch, tmp_path)

    mock_open_db = MagicMock(return_value=MagicMock(name="conn"))
    mock_export_latest = MagicMock()
    mock_export_monthly = MagicMock()
    mock_export_index = MagicMock()
    mock_push_data = MagicMock(return_value=True)
    mock_repo = MagicMock(return_value=MagicMock(remotes={"origin": MagicMock()}))

    monkeypatch.setattr("s7bb_fetcher.storage.open_db", mock_open_db)
    monkeypatch.setattr("s7bb_fetcher.exporter.export_latest", mock_export_latest)
    monkeypatch.setattr("s7bb_fetcher.exporter.export_monthly_archive", mock_export_monthly)
    monkeypatch.setattr("s7bb_fetcher.exporter.export_archive_index", mock_export_index)
    monkeypatch.setattr("s7bb_fetcher.pusher.push_data", mock_push_data)
    monkeypatch.setattr("git.Repo", mock_repo)

    return {
        "export_latest": mock_export_latest,
        "export_monthly": mock_export_monthly,
        "export_index": mock_export_index,
        "push_data": mock_push_data,
        "git_repo": mock_repo,
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


def test_service_runs_preflight_before_scheduler(monkeypatch):
    calls = []

    def fake_preflight(**kwargs):
        calls.append("preflight")
        return [Check("data_writable", Severity.HARD, True, "ok")]

    class DummyScheduler:
        def __init__(self):
            calls.append("scheduler.init")
        def add_job(self, *a, **kw):
            calls.append("scheduler.add_job")
        def start(self):
            calls.append("scheduler.start")
            raise SystemExit(0)
        def shutdown(self, wait=False):
            pass

    _noop_sync = MagicMock(return_value=MagicMock(action="noop", message="ok"))
    with patch.object(preflight, "run", side_effect=fake_preflight), \
         patch("s7bb_fetcher.service.BlockingScheduler", DummyScheduler), \
         patch("s7bb_fetcher.startup_sync.startup_sync", _noop_sync), \
         patch("s7bb_fetcher.pusher._resolve_slug", return_value="owner/repo"), \
         patch("git.Repo", MagicMock(return_value=MagicMock())):
        with pytest.raises(SystemExit):
            service.main()

    # preflight must run before any scheduler interaction
    assert calls.index("preflight") < calls.index("scheduler.init")
    assert "scheduler.start" in calls


def test_service_aborts_on_hard_failure():
    fake = [Check("data_writable", Severity.HARD, False, "denied")]

    class NeverScheduler:
        def __init__(self):
            raise AssertionError("scheduler must not be constructed on hard fail")

    with patch.object(preflight, "run", return_value=fake), \
         patch("s7bb_fetcher.service.BlockingScheduler", NeverScheduler):
        with pytest.raises(PreflightFailed):
            service.main()


def test_service_continues_on_soft_failure():
    fake = [
        Check("data_writable", Severity.HARD, True, "ok"),
        Check("github", Severity.SOFT, False, "no token"),
    ]
    started = {"flag": False}

    class DummyScheduler:
        def add_job(self, *a, **kw):
            pass
        def start(self):
            started["flag"] = True
            raise SystemExit(0)
        def shutdown(self, wait=False):
            pass

    _noop_sync = MagicMock(return_value=MagicMock(action="noop", message="ok"))
    with patch.object(preflight, "run", return_value=fake), \
         patch("s7bb_fetcher.service.BlockingScheduler", DummyScheduler), \
         patch("s7bb_fetcher.startup_sync.startup_sync", _noop_sync), \
         patch("s7bb_fetcher.pusher._resolve_slug", return_value="owner/repo"), \
         patch("git.Repo", MagicMock(return_value=MagicMock())):
        with pytest.raises(SystemExit):
            service.main()
    assert started["flag"] is True


def test_main_calls_startup_sync_after_preflight(monkeypatch, tmp_path):
    """service.main() must call startup_sync.startup_sync after preflight
    succeeds and before scheduler.start()."""
    _patch_service(monkeypatch, tmp_path)

    monkeypatch.setattr(
        preflight, "run",
        lambda **kw: [Check(name="ok", severity=Severity.HARD, ok=True, message="")],
    )

    order = []

    def _ok_sync(*a, **kw):
        order.append("sync")
        return MagicMock(action="noop", message="ok")

    mock_sync = MagicMock(side_effect=_ok_sync)
    mock_scheduler_cls = MagicMock()
    mock_scheduler = mock_scheduler_cls.return_value
    mock_scheduler.start.side_effect = lambda: order.append("start")

    monkeypatch.setattr("s7bb_fetcher.startup_sync.startup_sync", mock_sync)
    monkeypatch.setattr("s7bb_fetcher.service.BlockingScheduler", mock_scheduler_cls)
    monkeypatch.setattr(
        "s7bb_fetcher.pusher._resolve_slug",
        lambda repo: "owner/repo",
    )
    monkeypatch.setattr("git.Repo", MagicMock(return_value=MagicMock()))

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
    monkeypatch.setattr("git.Repo", MagicMock(return_value=MagicMock()))

    from s7bb_fetcher.service import main
    with pytest.raises(RuntimeError, match="network down"):
        main()
    mock_scheduler_cls.return_value.start.assert_not_called()


def test_run_push_step_logs_push_failed_on_exception(mocks, caplog, monkeypatch):
    from s7bb_fetcher import service

    service._consecutive_push_failures = 0
    mocks["push_data"].side_effect = RuntimeError("simulated push failure")

    with caplog.at_level("ERROR"):
        service._run_push_step()

    matches = [r for r in caplog.records if "PUSH_FAILED" in r.message]
    assert len(matches) == 1
    assert "consecutive_failures=1" in matches[0].message
    assert "RuntimeError" in matches[0].message or matches[0].exc_info is not None


def test_run_push_step_resets_counter_on_success(mocks, monkeypatch):
    from s7bb_fetcher import pusher, service

    service._consecutive_push_failures = 0
    mocks["push_data"].side_effect = [
        RuntimeError("boom"),
        pusher.PushOutcome.COMMITTED_AND_PUSHED,
    ]

    service._run_push_step()
    service._run_push_step()

    assert service._consecutive_push_failures == 0


def test_run_push_step_fetches_origin_before_pushing(mocks, monkeypatch):
    from unittest.mock import MagicMock

    from s7bb_fetcher import pusher, service

    fake_remote = MagicMock()
    fake_remote.fetch = MagicMock()
    fake_repo = MagicMock(remotes={"origin": fake_remote})
    monkeypatch.setattr("git.Repo", MagicMock(return_value=fake_repo))
    service._consecutive_push_failures = 0
    mocks["push_data"].return_value = pusher.PushOutcome.NOOP

    service._run_push_step()

    fake_remote.fetch.assert_called_once()
