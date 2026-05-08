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
