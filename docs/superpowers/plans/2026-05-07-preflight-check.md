# Preflight Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a startup-time preflight check to the `s7bb-fetcher` service that validates volume access, git repo writability and ownership, SQLite DB integrity, and GitHub PAT/repo access — and expose it as a standalone `s7bb-preflight` CLI for operator diagnostics.

**Architecture:** New `preflight.py` module in `s7bb_fetcher` with a single public `run()` function that returns a list of `Check` results. Two callers: `service.main()` invokes it before scheduling jobs (raising `PreflightFailed` on hard-severity failures), and a new `s7bb-preflight` CLI lets operators run the same checks on demand. Hard-fail on volume/ownership/DB problems; soft-warn on GitHub reachability.

**Tech Stack:** Python 3.11+, GitPython, sqlite3 stdlib, `requests` (already a project dep) for the GitHub API call, pytest + `unittest.mock`.

---

## File Structure

- **New:** `fetcher/src/s7bb_fetcher/preflight.py` — `Severity`, `Check`, `PreflightFailed`, individual `_check_*` functions, public `run()`.
- **New:** `fetcher/tests/test_preflight.py` — unit tests per check + `run()` orchestrator tests.
- **Modify:** `fetcher/src/s7bb_fetcher/service.py` — invoke `preflight.run()` at the top of `main()`, log results, raise `PreflightFailed` on hard failures.
- **Modify:** `fetcher/src/s7bb_fetcher/cli.py` — add `preflight()` entry point.
- **Modify:** `fetcher/pyproject.toml` — add `s7bb-preflight = "s7bb_fetcher.cli:preflight"` to `[project.scripts]`.
- **Modify:** `fetcher/tests/test_service.py` — assert preflight is invoked before `scheduler.start()` and that hard failures abort.
- **Modify:** `CHANGELOG.md` — entry under `[Unreleased]` → `Added`.
- **Modify:** `README.md` — short subsection under VM setup describing `s7bb-preflight` and what each check covers.

---

## Task 1: Scaffold the preflight module

**Files:**
- Create: `fetcher/src/s7bb_fetcher/preflight.py`
- Create: `fetcher/tests/test_preflight.py`

- [ ] **Step 1: Write the failing test for module surface**

```python
# fetcher/tests/test_preflight.py
"""Tests for preflight.py."""

import pytest

from s7bb_fetcher import preflight
from s7bb_fetcher.preflight import Check, PreflightFailed, Severity


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd fetcher && uv run pytest tests/test_preflight.py -v`
Expected: ImportError or ModuleNotFoundError — `preflight` module does not exist.

- [ ] **Step 3: Create the module**

```python
# fetcher/src/s7bb_fetcher/preflight.py
"""Startup preflight checks for the s7bb-fetcher service.

Validates volume access, git repo writability and ownership, SQLite DB
integrity, and GitHub PAT/repo access. Hard-fail checks abort startup;
soft-fail checks log a warning and let the service continue.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class Severity(enum.Enum):
    HARD = "hard"
    SOFT = "soft"


@dataclass(frozen=True)
class Check:
    name: str
    severity: Severity
    ok: bool
    message: str


class PreflightFailed(RuntimeError):
    """Raised when one or more hard preflight checks fail."""


def run(*_args, **_kwargs) -> list[Check]:
    """Placeholder; later tasks fill this in."""
    return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd fetcher && uv run pytest tests/test_preflight.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/preflight.py fetcher/tests/test_preflight.py
git commit -m "feat(preflight): scaffold module with Check/Severity/PreflightFailed"
```

---

## Task 2: `_check_data_writable`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/preflight.py`
- Modify: `fetcher/tests/test_preflight.py`

- [ ] **Step 1: Write the failing tests**

Append to `fetcher/tests/test_preflight.py`:

```python
import os

from s7bb_fetcher.preflight import _check_data_writable


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fetcher && uv run pytest tests/test_preflight.py::test_data_writable_ok -v`
Expected: ImportError on `_check_data_writable`.

- [ ] **Step 3: Implement the check**

In `fetcher/src/s7bb_fetcher/preflight.py`, add at top after the `Path` import (also add `from pathlib import Path` to the imports):

```python
import os
import tempfile
from pathlib import Path


def _check_data_writable(data_dir: Path) -> Check:
    name = "data_writable"
    if not data_dir.exists():
        return Check(name, Severity.HARD, False, f"{data_dir} does not exist")
    if not data_dir.is_dir():
        return Check(name, Severity.HARD, False, f"{data_dir} is not a directory")
    try:
        fd, path = tempfile.mkstemp(prefix=".preflight-", dir=str(data_dir))
        os.close(fd)
        os.unlink(path)
    except PermissionError as e:
        return Check(name, Severity.HARD, False, f"permission denied writing to {data_dir}: {e}")
    except OSError as e:
        return Check(name, Severity.HARD, False, f"cannot write to {data_dir}: {e}")
    return Check(name, Severity.HARD, True, f"{data_dir} is writable")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd fetcher && uv run pytest tests/test_preflight.py -v`
Expected: all `data_writable` tests pass plus the four scaffolding tests.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/preflight.py fetcher/tests/test_preflight.py
git commit -m "feat(preflight): add data-volume writability check"
```

---

## Task 3: `_check_repo_writable`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/preflight.py`
- Modify: `fetcher/tests/test_preflight.py`

- [ ] **Step 1: Write the failing tests**

Append to `fetcher/tests/test_preflight.py`:

```python
import git as _git_for_repo_writable_setup

from s7bb_fetcher.preflight import _check_repo_writable


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fetcher && uv run pytest tests/test_preflight.py::test_repo_writable_ok -v`
Expected: ImportError on `_check_repo_writable`.

- [ ] **Step 3: Implement the check**

Append to `fetcher/src/s7bb_fetcher/preflight.py`:

```python
import git


def _check_repo_writable(repo_path: Path) -> Check:
    name = "repo_writable"
    if not repo_path.exists():
        return Check(name, Severity.HARD, False, f"{repo_path} does not exist")
    try:
        git.Repo(str(repo_path))
    except git.InvalidGitRepositoryError:
        return Check(name, Severity.HARD, False, f"{repo_path} is not a git repository")
    except git.NoSuchPathError:
        return Check(name, Severity.HARD, False, f"{repo_path} has no git directory")
    try:
        fd, path = tempfile.mkstemp(prefix=".preflight-", dir=str(repo_path))
        os.close(fd)
        os.unlink(path)
    except PermissionError as e:
        return Check(name, Severity.HARD, False, f"permission denied writing to {repo_path}: {e}")
    except OSError as e:
        return Check(name, Severity.HARD, False, f"cannot write to {repo_path}: {e}")
    return Check(name, Severity.HARD, True, f"{repo_path} is writable and git-readable")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd fetcher && uv run pytest tests/test_preflight.py -v`
Expected: all repo_writable tests pass.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/preflight.py fetcher/tests/test_preflight.py
git commit -m "feat(preflight): add git repo writability check"
```

---

## Task 4: `_check_repo_ownership`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/preflight.py`
- Modify: `fetcher/tests/test_preflight.py`

- [ ] **Step 1: Write the failing tests**

Append to `fetcher/tests/test_preflight.py`:

```python
from unittest.mock import MagicMock, patch

from s7bb_fetcher.preflight import _check_repo_ownership


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fetcher && uv run pytest tests/test_preflight.py::test_repo_ownership_ok -v`
Expected: ImportError on `_check_repo_ownership`.

- [ ] **Step 3: Implement the check**

Append to `fetcher/src/s7bb_fetcher/preflight.py`:

```python
def _check_repo_ownership(repo_path: Path) -> Check:
    name = "repo_ownership"
    try:
        repo = git.Repo(str(repo_path))
        repo.git.status()
    except git.InvalidGitRepositoryError:
        return Check(name, Severity.HARD, False, f"{repo_path} is not a git repository")
    except git.NoSuchPathError:
        return Check(name, Severity.HARD, False, f"{repo_path} does not exist")
    except git.exc.GitCommandError as e:
        stderr = (e.stderr or "").strip()
        if "dubious ownership" in stderr.lower():
            return Check(
                name,
                Severity.HARD,
                False,
                f"git refuses to use {repo_path}: dubious ownership detected. "
                f"Fix host mount ownership to match the container user, "
                f"or set GIT_SAFE_DIRECTORY={repo_path} in .env.",
            )
        return Check(name, Severity.HARD, False, f"git status failed: {stderr or e}")
    return Check(name, Severity.HARD, True, f"git accepts {repo_path}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd fetcher && uv run pytest tests/test_preflight.py -v`
Expected: all repo_ownership tests pass.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/preflight.py fetcher/tests/test_preflight.py
git commit -m "feat(preflight): detect git \"dubious ownership\" with remediation hint"
```

---

## Task 5: `_check_sqlite`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/preflight.py`
- Modify: `fetcher/tests/test_preflight.py`

- [ ] **Step 1: Write the failing tests**

Append to `fetcher/tests/test_preflight.py`:

```python
from s7bb_fetcher.preflight import _check_sqlite


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fetcher && uv run pytest tests/test_preflight.py::test_sqlite_creates_and_passes -v`
Expected: ImportError on `_check_sqlite`.

- [ ] **Step 3: Implement the check**

Append to `fetcher/src/s7bb_fetcher/preflight.py`:

```python
import sqlite3

from .storage import open_db


def _check_sqlite(db_path: Path) -> Check:
    name = "sqlite"
    try:
        conn = open_db(db_path)
    except sqlite3.DatabaseError as e:
        return Check(name, Severity.HARD, False, f"{db_path} is not a valid SQLite database: {e}")
    except PermissionError as e:
        return Check(name, Severity.HARD, False, f"cannot create DB at {db_path}: {e}")
    except OSError as e:
        return Check(name, Severity.HARD, False, f"cannot open DB at {db_path}: {e}")
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        result = row[0] if row else "(no result)"
        if result != "ok":
            return Check(name, Severity.HARD, False, f"integrity_check returned: {result}")
    except sqlite3.DatabaseError as e:
        return Check(name, Severity.HARD, False, f"integrity_check failed: {e}")
    finally:
        conn.close()
    return Check(name, Severity.HARD, True, f"{db_path} opens and integrity_check=ok")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd fetcher && uv run pytest tests/test_preflight.py -v`
Expected: all sqlite tests pass.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/preflight.py fetcher/tests/test_preflight.py
git commit -m "feat(preflight): add SQLite integrity check"
```

---

## Task 6: `_check_github`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/preflight.py`
- Modify: `fetcher/tests/test_preflight.py`

- [ ] **Step 1: Write the failing tests**

Append to `fetcher/tests/test_preflight.py`:

```python
import requests

from s7bb_fetcher.preflight import _check_github


class _FakeResp:
    def __init__(self, status_code, json_body=None):
        self.status_code = status_code
        self._json = json_body or {}

    def json(self):
        return self._json


def test_github_no_token():
    c = _check_github(slug="owner/repo", token=None)
    assert c.ok is False
    assert c.severity is Severity.SOFT
    assert "GITHUB_PAT" in c.message


def test_github_no_slug():
    c = _check_github(slug=None, token="t")
    assert c.ok is False
    assert c.severity is Severity.SOFT
    assert "slug" in c.message.lower() or "GITHUB_REPO_SLUG" in c.message


def test_github_ok():
    with patch("s7bb_fetcher.preflight.requests.get", return_value=_FakeResp(200)) as m:
        c = _check_github(slug="o/r", token="ghp_123")
    assert c.ok is True
    assert c.severity is Severity.SOFT
    headers = m.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer ghp_123"
    assert headers["Accept"] == "application/vnd.github+json"


def test_github_401():
    with patch("s7bb_fetcher.preflight.requests.get", return_value=_FakeResp(401)):
        c = _check_github(slug="o/r", token="bad")
    assert c.ok is False
    assert "expired" in c.message.lower() or "bad" in c.message.lower()


def test_github_403():
    with patch("s7bb_fetcher.preflight.requests.get", return_value=_FakeResp(403)):
        c = _check_github(slug="o/r", token="t")
    assert c.ok is False
    assert "access" in c.message.lower() or "scope" in c.message.lower()


def test_github_404():
    with patch("s7bb_fetcher.preflight.requests.get", return_value=_FakeResp(404)):
        c = _check_github(slug="o/r", token="t")
    assert c.ok is False
    assert "not found" in c.message.lower()


def test_github_network_error():
    with patch(
        "s7bb_fetcher.preflight.requests.get",
        side_effect=requests.exceptions.ConnectionError("dns lookup failed"),
    ):
        c = _check_github(slug="o/r", token="t")
    assert c.ok is False
    assert c.severity is Severity.SOFT
    assert "dns lookup failed" in c.message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fetcher && uv run pytest tests/test_preflight.py::test_github_ok -v`
Expected: ImportError on `_check_github`.

- [ ] **Step 3: Implement the check**

Append to `fetcher/src/s7bb_fetcher/preflight.py`:

```python
import requests

_GITHUB_TIMEOUT_SEC = 5.0


def _check_github(slug: str | None, token: str | None) -> Check:
    name = "github"
    if not token:
        return Check(name, Severity.SOFT, False, "GITHUB_PAT not set; push will fail at next export")
    if not slug:
        return Check(
            name,
            Severity.SOFT,
            False,
            "could not resolve repo slug (set GITHUB_REPO_SLUG or fix origin URL)",
        )
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{slug}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=_GITHUB_TIMEOUT_SEC,
        )
    except requests.exceptions.RequestException as e:
        return Check(name, Severity.SOFT, False, f"network error reaching api.github.com: {e}")

    if resp.status_code == 200:
        return Check(name, Severity.SOFT, True, f"GitHub PAT can read repo {slug}")
    if resp.status_code == 401:
        return Check(name, Severity.SOFT, False, "bad or expired GITHUB_PAT (HTTP 401)")
    if resp.status_code == 403:
        return Check(name, Severity.SOFT, False, "GITHUB_PAT lacks required access (HTTP 403)")
    if resp.status_code == 404:
        return Check(name, Severity.SOFT, False, f"repo {slug} not found or PAT cannot see it (HTTP 404)")
    return Check(name, Severity.SOFT, False, f"unexpected HTTP {resp.status_code} from api.github.com")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd fetcher && uv run pytest tests/test_preflight.py -v`
Expected: all github tests pass.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/preflight.py fetcher/tests/test_preflight.py
git commit -m "feat(preflight): add GitHub PAT/repo access check"
```

---

## Task 7: `run()` orchestrator

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/preflight.py`
- Modify: `fetcher/tests/test_preflight.py`

- [ ] **Step 1: Write the failing tests**

Append to `fetcher/tests/test_preflight.py`:

```python
def test_run_returns_all_checks(tmp_path):
    _init_repo(tmp_path)
    db = tmp_path / "s7bb.db"
    with patch("s7bb_fetcher.preflight._check_github",
               return_value=Check("github", Severity.SOFT, True, "ok")):
        results = preflight.run(
            data_dir=tmp_path, repo_path=tmp_path, db_path=db,
            github_slug="o/r", github_token="t",
        )
    names = [c.name for c in results]
    assert names == ["data_writable", "repo_writable", "repo_ownership", "sqlite", "github"]


def test_run_does_not_short_circuit(tmp_path):
    bad = tmp_path / "missing"
    with patch("s7bb_fetcher.preflight._check_github",
               return_value=Check("github", Severity.SOFT, False, "n/a")):
        results = preflight.run(
            data_dir=bad, repo_path=bad, db_path=bad / "x.db",
            github_slug=None, github_token=None,
        )
    assert len(results) == 5  # every check is attempted


def test_run_resolves_slug_from_repo_when_unset(tmp_path):
    repo = _init_repo(tmp_path)
    repo.create_remote("origin", url="https://github.com/foo/bar.git")
    db = tmp_path / "s7bb.db"
    seen = {}

    def fake_github(slug, token):
        seen["slug"] = slug
        seen["token"] = token
        return Check("github", Severity.SOFT, True, "ok")

    with patch("s7bb_fetcher.preflight._check_github", side_effect=fake_github):
        preflight.run(
            data_dir=tmp_path, repo_path=tmp_path, db_path=db,
            github_slug=None, github_token="t",
        )
    assert seen["slug"] == "foo/bar"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fetcher && uv run pytest tests/test_preflight.py::test_run_returns_all_checks -v`
Expected: failure — current `run()` returns `[]`.

- [ ] **Step 3: Replace the placeholder `run()`**

In `fetcher/src/s7bb_fetcher/preflight.py`, replace the placeholder `run()` with:

```python
def _resolve_slug(repo_path: Path) -> str | None:
    """Return owner/repo from origin URL, or None if not parseable."""
    from .pusher import _ORIGIN_RE  # reuse the regex used by pusher

    try:
        repo = git.Repo(str(repo_path))
        url = repo.remotes["origin"].url
    except (git.InvalidGitRepositoryError, git.NoSuchPathError, IndexError, KeyError):
        return None
    m = _ORIGIN_RE.match(url)
    if not m:
        return None
    return f"{m['owner']}/{m['repo']}"


def run(
    *,
    data_dir: Path,
    repo_path: Path,
    db_path: Path,
    github_slug: str | None = None,
    github_token: str | None = None,
) -> list[Check]:
    """Run all preflight checks. Never raises; returns one Check per probe."""
    if not github_slug:
        github_slug = _resolve_slug(repo_path)

    return [
        _check_data_writable(data_dir),
        _check_repo_writable(repo_path),
        _check_repo_ownership(repo_path),
        _check_sqlite(db_path),
        _check_github(github_slug, github_token),
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd fetcher && uv run pytest tests/test_preflight.py -v`
Expected: all preflight tests pass (including the orchestrator tests).

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/preflight.py fetcher/tests/test_preflight.py
git commit -m "feat(preflight): wire run() orchestrator with origin-URL slug fallback"
```

---

## Task 8: CLI entry `s7bb-preflight`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/cli.py`
- Modify: `fetcher/pyproject.toml`
- Modify: `fetcher/tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `fetcher/tests/test_cli.py` (create the file's import block additions if missing):

```python
import os
from unittest.mock import patch

import pytest

from s7bb_fetcher import cli, preflight
from s7bb_fetcher.preflight import Check, Severity


def _checks(*pairs):
    return [Check(name=n, severity=s, ok=ok, message=m) for n, s, ok, m in pairs]


def test_cli_preflight_exits_zero_when_all_ok(capsys):
    fake = _checks(
        ("data_writable", Severity.HARD, True, "ok"),
        ("github", Severity.SOFT, True, "ok"),
    )
    with patch.object(preflight, "run", return_value=fake):
        with pytest.raises(SystemExit) as ei:
            cli.preflight([])
    assert ei.value.code == 0


def test_cli_preflight_exits_one_on_hard_fail(capsys):
    fake = _checks(
        ("data_writable", Severity.HARD, False, "denied"),
        ("github", Severity.SOFT, True, "ok"),
    )
    with patch.object(preflight, "run", return_value=fake):
        with pytest.raises(SystemExit) as ei:
            cli.preflight([])
    assert ei.value.code == 1
    out = capsys.readouterr().out
    assert "data_writable" in out
    assert "denied" in out


def test_cli_preflight_soft_fail_still_zero(capsys):
    fake = _checks(
        ("data_writable", Severity.HARD, True, "ok"),
        ("github", Severity.SOFT, False, "no token"),
    )
    with patch.object(preflight, "run", return_value=fake):
        with pytest.raises(SystemExit) as ei:
            cli.preflight([])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "github" in out
    assert "no token" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fetcher && uv run pytest tests/test_cli.py -v`
Expected: AttributeError — `cli.preflight` does not exist.

- [ ] **Step 3: Add the CLI function**

Append to `fetcher/src/s7bb_fetcher/cli.py`:

```python
def preflight(argv: list[str] | None = None) -> None:
    import argparse
    import os

    from . import preflight as preflight_mod
    from .preflight import Severity

    parser = argparse.ArgumentParser(description="Run s7bb-fetcher preflight checks")
    parser.add_argument("--data-dir", default=os.environ.get("DATA_DIR", "/data"))
    parser.add_argument("--repo-path", default=os.environ.get("REPO_PATH", "/repo"))
    parser.add_argument("--db", default=None,
                        help="SQLite DB path; defaults to <data-dir>/s7bb.db")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    repo_path = Path(args.repo_path)
    db_path = Path(args.db) if args.db else data_dir / "s7bb.db"

    results = preflight_mod.run(
        data_dir=data_dir,
        repo_path=repo_path,
        db_path=db_path,
        github_slug=os.environ.get("GITHUB_REPO_SLUG") or None,
        github_token=os.environ.get("GITHUB_PAT") or None,
    )

    hard_fail = False
    print(f"preflight: {len(results)} checks")
    for c in results:
        if c.ok:
            mark = "[OK]"
        else:
            mark = "[FAIL]" if c.severity is Severity.HARD else "[WARN]"
            if c.severity is Severity.HARD:
                hard_fail = True
        print(f"  {mark:6} {c.name:18} {c.message}")

    sys.exit(1 if hard_fail else 0)
```

- [ ] **Step 4: Register the CLI script**

In `fetcher/pyproject.toml`, under `[project.scripts]`, add:

```toml
s7bb-preflight = "s7bb_fetcher.cli:preflight"
```

So the section reads:

```toml
[project.scripts]
s7bb-fetch     = "s7bb_fetcher.cli:fetch"
s7bb-export    = "s7bb_fetcher.cli:export"
s7bb-preflight = "s7bb_fetcher.cli:preflight"
s7bb-service   = "s7bb_fetcher.service:main"
```

- [ ] **Step 5: Run tests to verify they pass and reinstall scripts**

Run: `cd fetcher && uv sync --group dev && uv run pytest tests/test_cli.py -v`
Expected: all `cli.preflight` tests pass; `which s7bb-preflight` (inside `uv run`) resolves.

- [ ] **Step 6: Commit**

```bash
git add fetcher/src/s7bb_fetcher/cli.py fetcher/pyproject.toml fetcher/tests/test_cli.py fetcher/uv.lock
git commit -m "feat(preflight): add s7bb-preflight CLI entry"
```

---

## Task 9: Wire preflight into `service.main()`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/service.py`
- Modify: `fetcher/tests/test_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `fetcher/tests/test_service.py`:

```python
from unittest.mock import patch

import pytest

from s7bb_fetcher import preflight, service
from s7bb_fetcher.preflight import Check, PreflightFailed, Severity


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

    with patch.object(preflight, "run", side_effect=fake_preflight), \
         patch("s7bb_fetcher.service.BlockingScheduler", DummyScheduler):
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

    with patch.object(preflight, "run", return_value=fake), \
         patch("s7bb_fetcher.service.BlockingScheduler", DummyScheduler):
        with pytest.raises(SystemExit):
            service.main()
    assert started["flag"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fetcher && uv run pytest tests/test_service.py::test_service_aborts_on_hard_failure -v`
Expected: failure — `service.main()` does not call preflight.

- [ ] **Step 3: Modify `service.main()`**

In `fetcher/src/s7bb_fetcher/service.py`:

(a) Add this import block near the top, alongside the existing imports:

```python
from . import preflight
from .preflight import PreflightFailed, Severity
```

(b) Replace the body of `main()` with:

```python
def main() -> None:
    fetch_cron  = os.environ.get("FETCH_CRON",  "*/5 * * * *")
    export_cron = os.environ.get("EXPORT_CRON", "0 * * * *")

    results = preflight.run(
        data_dir=DATA_DIR,
        repo_path=REPO_PATH,
        db_path=DB_PATH,
        github_slug=os.environ.get("GITHUB_REPO_SLUG") or None,
        github_token=os.environ.get("GITHUB_PAT") or None,
    )
    hard_failed = False
    logger.info("preflight: %d checks", len(results))
    for c in results:
        if c.ok:
            logger.info("preflight ✓ %s: %s", c.name, c.message)
        elif c.severity is Severity.SOFT:
            logger.warning("preflight ! %s: %s", c.name, c.message)
        else:
            logger.error("preflight ✗ %s: %s", c.name, c.message)
            hard_failed = True
    if hard_failed:
        raise PreflightFailed("one or more hard preflight checks failed; aborting startup")

    scheduler = BlockingScheduler()
    scheduler.add_job(
        _fetch_job,
        CronTrigger.from_crontab(fetch_cron),
        id="fetch",
        misfire_grace_time=None,
    )
    scheduler.add_job(
        _export_job,
        CronTrigger.from_crontab(export_cron),
        id="export",
        misfire_grace_time=None,
    )

    def _shutdown(signum, frame):
        logger.info("signal %s received, shutting down", signum)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("s7bb-service starting: FETCH_CRON=%s EXPORT_CRON=%s", fetch_cron, export_cron)
    scheduler.start()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd fetcher && uv run pytest tests/test_service.py tests/test_preflight.py tests/test_cli.py -v`
Expected: all pass; no regressions in existing test_service tests.

- [ ] **Step 5: Lint**

Run: `cd fetcher && uv run ruff check src tests`
Expected: no errors. If ruff complains about unused imports or ordering, fix and re-run.

- [ ] **Step 6: Commit**

```bash
git add fetcher/src/s7bb_fetcher/service.py fetcher/tests/test_service.py
git commit -m "feat(preflight): run preflight at service startup, abort on hard fail"
```

---

## Task 10: Documentation

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 1: Update CHANGELOG**

In `CHANGELOG.md`, under `## [Unreleased]` → `### Added`, add a bullet:

```markdown
- Startup preflight check in `s7bb-fetcher` validating volume permissions, git repo writability, "dubious ownership", SQLite integrity, and GitHub PAT/repo access. Hard failures abort startup; soft failures (e.g. GitHub reach) log a warning. New `s7bb-preflight` CLI runs the same checks on demand.
```

- [ ] **Step 2: Update README**

In `README.md`, locate the VM Setup section (the one referenced in `CLAUDE.md`). Add a subsection after the `docker compose up -d s7bb-fetcher` step:

```markdown
### Diagnosing startup problems

The fetcher runs a preflight check on startup. If the container exits immediately, run the same checks manually to see which one failed:

```bash
docker compose run --rm s7bb-fetcher s7bb-preflight
```

The CLI prints one line per check. `[OK]` is healthy, `[WARN]` is a soft failure (the service would still start), `[FAIL]` is a hard failure (the service aborts). Common fixes:

- `repo_ownership [FAIL]: dubious ownership` — set `GIT_SAFE_DIRECTORY=/repo` in `.env` or align host UID with the container's `UID`/`GID`.
- `data_writable [FAIL]: permission denied` — the bind-mounted `data/` directory is not writable by the container user.
- `github [WARN]: bad or expired GITHUB_PAT` — issue a new fine-grained PAT and update `.env`.
```

- [ ] **Step 3: Verify build still passes end-to-end**

Run: `cd fetcher && uv run pytest && uv run ruff check src tests`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs(preflight): document s7bb-preflight CLI and remediation hints"
```

---

## Task 11: End-to-end smoke test

**Files:** none (verification only)

- [ ] **Step 1: Build the container**

Run: `docker compose build s7bb-fetcher`
Expected: build succeeds.

- [ ] **Step 2: Run the standalone CLI inside the container**

Run: `docker compose run --rm s7bb-fetcher s7bb-preflight`
Expected: output shows 5 check lines. On a correctly configured host: 4× `[OK]` + 1× `[OK]` for github (if `GITHUB_PAT` is set) or `[WARN]` (if not). Exit code 0 when no `[FAIL]`.

- [ ] **Step 3: Force a hard failure to confirm the abort path**

Run:
```bash
docker compose run --rm -e DATA_DIR=/nonexistent s7bb-fetcher s7bb-service
```
Expected: log shows `preflight ✗ data_writable: /nonexistent does not exist` and `PreflightFailed: one or more hard preflight checks failed; aborting startup`. Container exits non-zero.

- [ ] **Step 4: No commit needed — this task is verification only**

If any of the smoke checks fail, return to the relevant task and fix.

---

## Self-Review Notes

**Spec coverage check:**
- Failure mode (mixed): Tasks 2-7 set `Severity.HARD`/`Severity.SOFT` matching the spec table.
- GitHub check depth (`GET /repos/{slug}`): Task 6.
- Volume scope (data write + repo write + ownership): Tasks 2, 3, 4.
- SQLite check: Task 5 (added during brainstorming).
- Code structure (`preflight.py` + new CLI): Tasks 1, 8.
- No auto-fix of dubious ownership: Task 4 surfaces remediation in `Check.message` only.
- Error handling (each check wraps in try/except, `run()` never raises): Tasks 2-7 + Task 7 docstring.
- Logging at startup with INFO/WARNING/ERROR by severity: Task 9.
- Exit-code behaviour for CLI (0 on all-OK or soft-only fail; 1 on any hard fail): Task 8.
- Tests called out in the spec are all present: Tasks 2-9 cover every named test plus a few extras (`test_run_does_not_short_circuit`, slug-resolution test).

**Type consistency check:** `Check`, `Severity`, `PreflightFailed`, `run(*, data_dir, repo_path, db_path, github_slug=None, github_token=None) -> list[Check]` — same signature in module, CLI, and service caller. Function names match between tests and implementation.

**Placeholder scan:** none.
