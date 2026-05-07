"""Tests for preflight.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import git as _git_for_repo_writable_setup
import pytest

from s7bb_fetcher import preflight
from s7bb_fetcher.preflight import (
    Check,
    PreflightFailed,
    Severity,
    _check_data_writable,
    _check_repo_ownership,
    _check_repo_writable,
    _check_sqlite,
)


def test_module_exports_expected_symbols():
    assert hasattr(preflight, "run")
    assert hasattr(preflight, "Check")
    assert hasattr(preflight, "Severity")
    assert hasattr(preflight, "PreflightFailed")


def test_severity_has_hard_and_soft():
    assert Severity.HARD != Severity.SOFT


def test_check_is_dataclass_with_fields():
    c = Check(name="x", severity=Severity.HARD, ok=True, message="fine")
    assert c.name == "x"
    assert c.severity is Severity.HARD
    assert c.ok is True
    assert c.message == "fine"


def test_preflight_failed_is_exception():
    with pytest.raises(PreflightFailed):
        raise PreflightFailed("boom")


def test_data_writable_ok(tmp_path):
    c = _check_data_writable(tmp_path)
    assert c.ok is True
    assert c.severity is Severity.HARD
    assert c.name == "data_writable"


def test_data_writable_missing_dir(tmp_path):
    c = _check_data_writable(tmp_path / "does_not_exist")
    assert c.ok is False
    assert "does not exist" in c.message.lower() or "not found" in c.message.lower()


def test_data_writable_readonly(tmp_path):
    tmp_path.chmod(0o500)
    try:
        c = _check_data_writable(tmp_path)
        assert c.ok is False
        assert "permission" in c.message.lower() or "denied" in c.message.lower()
    finally:
        tmp_path.chmod(0o700)


def test_data_writable_leaves_no_residue(tmp_path):
    _check_data_writable(tmp_path)
    assert list(tmp_path.iterdir()) == []


def _init_repo(path):
    repo = _git_for_repo_writable_setup.Repo.init(path)
    (path / "README.md").write_text("hello")
    repo.index.add(["README.md"])
    repo.index.commit("init", author=_git_for_repo_writable_setup.Actor("t", "t@t"),
                       committer=_git_for_repo_writable_setup.Actor("t", "t@t"))
    return repo


def test_repo_writable_ok(tmp_path):
    _init_repo(tmp_path)
    c = _check_repo_writable(tmp_path)
    assert c.ok is True
    assert c.name == "repo_writable"


def test_repo_writable_missing(tmp_path):
    c = _check_repo_writable(tmp_path / "nope")
    assert c.ok is False


def test_repo_writable_not_a_git_repo(tmp_path):
    c = _check_repo_writable(tmp_path)
    assert c.ok is False
    assert "git" in c.message.lower()


def test_repo_writable_readonly(tmp_path):
    _init_repo(tmp_path)
    tmp_path.chmod(0o500)
    try:
        c = _check_repo_writable(tmp_path)
        assert c.ok is False
    finally:
        tmp_path.chmod(0o700)


def test_repo_ownership_ok(tmp_path):
    _init_repo(tmp_path)
    c = _check_repo_ownership(tmp_path)
    assert c.ok is True
    assert c.name == "repo_ownership"


def test_repo_ownership_dubious_message():
    fake_repo = MagicMock()
    err = _git_for_repo_writable_setup.exc.GitCommandError(
        ["git", "status"],
        128,
        stderr="fatal: detected dubious ownership in repository at '/repo'",
    )
    fake_repo.git.status.side_effect = err
    with patch("s7bb_fetcher.preflight.git.Repo", return_value=fake_repo):
        c = _check_repo_ownership(Path("/repo"))
    assert c.ok is False
    assert c.severity is Severity.HARD
    assert "dubious ownership" in c.message.lower()
    assert "GIT_SAFE_DIRECTORY" in c.message  # remediation hint surfaced


def test_repo_ownership_other_git_error_passthrough():
    fake_repo = MagicMock()
    err = _git_for_repo_writable_setup.exc.GitCommandError(
        ["git", "status"], 1, stderr="some other failure"
    )
    fake_repo.git.status.side_effect = err
    with patch("s7bb_fetcher.preflight.git.Repo", return_value=fake_repo):
        c = _check_repo_ownership(Path("/repo"))
    assert c.ok is False
    assert "some other failure" in c.message


def test_sqlite_creates_and_passes(tmp_path):
    db = tmp_path / "s7bb.db"
    c = _check_sqlite(db)
    assert c.ok is True
    assert c.name == "sqlite"
    assert db.exists()  # open_db creates it


def test_sqlite_corrupt(tmp_path):
    db = tmp_path / "s7bb.db"
    db.write_bytes(b"this is not a sqlite database\x00\x01\x02")
    c = _check_sqlite(db)
    assert c.ok is False
    assert c.severity is Severity.HARD


def test_sqlite_parent_unwritable(tmp_path):
    parent = tmp_path / "ro"
    parent.mkdir()
    parent.chmod(0o500)
    try:
        c = _check_sqlite(parent / "s7bb.db")
        assert c.ok is False
    finally:
        parent.chmod(0o700)
