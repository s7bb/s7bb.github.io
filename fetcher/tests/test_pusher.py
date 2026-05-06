"""Tests for pusher.py PAT-over-HTTPS push flow.

No network access: a local bare repo stands in for the GitHub upstream and
the dynamic `git.cmd.Git.push` method is replaced via monkeypatch. Tests
exercise URL construction, GIT_ASKPASS helper lifecycle, slug parsing, and
error propagation.
"""

import glob
import os
import re
import tempfile
from pathlib import Path

import git
import pytest

from s7bb_fetcher import pusher
from s7bb_fetcher.pusher import push_latest


@pytest.fixture
def working_repo(tmp_path: Path) -> git.Repo:
    """A working git repo with `origin` pointing at a local bare upstream and
    `data/latest.json` already committed on `main`."""
    bare_path = tmp_path / "remote.git"
    git.Repo.init(bare_path, bare=True, initial_branch="main")
    work = git.Repo.clone_from(str(bare_path), tmp_path / "work")
    # Force HTTPS-style remote so slug parsing has something deterministic by default.
    work.remotes["origin"].set_url("https://github.com/owner/s7bb.git")

    data_dir = Path(work.working_tree_dir) / "data"
    data_dir.mkdir()
    (data_dir / "latest.json").write_text('{"v":0}\n')
    work.index.add(["data/latest.json"])
    work.index.commit(
        "seed",
        author=git.Actor("seed", "seed@local"),
        committer=git.Actor("seed", "seed@local"),
    )
    if work.active_branch.name != "main":
        work.git.branch("-M", "main")
    return work


@pytest.fixture
def dirty_latest(working_repo: git.Repo) -> git.Repo:
    target = Path(working_repo.working_tree_dir) / "data" / "latest.json"
    target.write_text('{"v":1}\n')
    return working_repo


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    """Strip env vars that would otherwise leak from the dev shell into tests."""
    for var in (
        "GITHUB_PAT", "GITHUB_REPO_SLUG",
        "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
        "GIT_ASKPASS", "GIT_TERMINAL_PROMPT",
    ):
        monkeypatch.delenv(var, raising=False)


def _install_fake_push(monkeypatch, side_effect):
    """Replace `git.cmd.Git.push` (a dynamic method) with a real attribute.

    `side_effect` is a callable taking (self, *args, **kwargs); its return
    value or raised exception drives the test.
    """
    monkeypatch.setattr(git.cmd.Git, "push", side_effect, raising=False)


def test_pat_push_happy_path(monkeypatch, dirty_latest):
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    captured = {}

    def fake_push(self, *args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs.get("env", {}).copy()
        captured["helper_existed_during_call"] = os.path.exists(
            kwargs.get("env", {}).get("GIT_ASKPASS", "")
        )
        return ""

    _install_fake_push(monkeypatch, fake_push)
    result = push_latest(Path(dirty_latest.working_tree_dir))

    assert result is True
    assert captured["args"][0] == "https://x-access-token@github.com/owner/s7bb.git"
    assert captured["args"][1] == "HEAD:refs/heads/main"
    assert captured["env"]["GITHUB_PAT"] == "ghp_fake"
    assert captured["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert captured["helper_existed_during_call"] is True
    # Helper unlinked after the push.
    assert not os.path.exists(captured["env"]["GIT_ASKPASS"])


def test_no_changes_skips_push(monkeypatch, working_repo):
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    called = []

    def fake_push(self, *args, **kwargs):
        called.append(True)
        return ""

    _install_fake_push(monkeypatch, fake_push)
    result = push_latest(Path(working_repo.working_tree_dir))
    assert result is False
    assert called == []


def test_push_failure_propagates(monkeypatch, dirty_latest):
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")

    def fake_push(self, *args, **kwargs):
        raise git.GitCommandError(["git", "push"], 128, stderr=b"refused by ruleset")

    _install_fake_push(monkeypatch, fake_push)
    with pytest.raises(git.GitCommandError):
        push_latest(Path(dirty_latest.working_tree_dir))


def test_helper_cleaned_up_on_push_failure(monkeypatch, dirty_latest):
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    pattern = os.path.join(tempfile.gettempdir(), "s7bb-askpass-*.sh")
    before = set(glob.glob(pattern))

    def fake_push(self, *args, **kwargs):
        raise git.GitCommandError(["git", "push"], 128, stderr=b"boom")

    _install_fake_push(monkeypatch, fake_push)
    with pytest.raises(git.GitCommandError):
        push_latest(Path(dirty_latest.working_tree_dir))

    after = set(glob.glob(pattern))
    assert after == before, f"leftover helpers: {after - before}"


def test_missing_pat_raises(monkeypatch, dirty_latest):
    # GITHUB_PAT cleared by the autouse hermetic fixture.
    called = []

    def fake_push(self, *args, **kwargs):
        called.append(True)
        return ""

    _install_fake_push(monkeypatch, fake_push)
    with pytest.raises(RuntimeError, match="GITHUB_PAT not set"):
        push_latest(Path(dirty_latest.working_tree_dir))
    assert called == []


@pytest.mark.parametrize("origin_url", [
    "git@github.com:owner/s7bb.git",
    "git@github.com:owner/s7bb",
    "https://github.com/owner/s7bb.git",
    "https://github.com/owner/s7bb",
])
def test_slug_parsing_from_origin(monkeypatch, dirty_latest, origin_url):
    dirty_latest.remotes["origin"].set_url(origin_url)
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    captured = {}

    def fake_push(self, *args, **kwargs):
        captured["url"] = args[0]
        return ""

    _install_fake_push(monkeypatch, fake_push)
    push_latest(Path(dirty_latest.working_tree_dir))

    assert captured["url"] == "https://x-access-token@github.com/owner/s7bb.git"


def test_repo_slug_override_wins(monkeypatch, dirty_latest):
    dirty_latest.remotes["origin"].set_url("https://github.com/wrong/wrong.git")
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    monkeypatch.setenv("GITHUB_REPO_SLUG", "right/right")
    captured = {}

    def fake_push(self, *args, **kwargs):
        captured["url"] = args[0]
        return ""

    _install_fake_push(monkeypatch, fake_push)
    push_latest(Path(dirty_latest.working_tree_dir))

    assert captured["url"] == "https://x-access-token@github.com/right/right.git"


def test_unparseable_origin_raises(monkeypatch, dirty_latest):
    dirty_latest.remotes["origin"].set_url("file:///tmp/not-github.git")
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    with pytest.raises(RuntimeError, match="cannot parse owner/repo"):
        push_latest(Path(dirty_latest.working_tree_dir))


def test_origin_regex_rejects_non_github():
    assert pusher._ORIGIN_RE.match("https://gitlab.com/owner/repo.git") is None
    assert pusher._ORIGIN_RE.match("git@gitlab.com:owner/repo.git") is None


def test_origin_regex_accepts_pat_embedded_https():
    m = pusher._ORIGIN_RE.match("https://x-access-token:tok@github.com/o/r.git")
    assert m is not None
    assert m["owner"] == "o" and m["repo"] == "r"


def test_helper_script_content_uses_pat_env_var():
    # Sanity: the helper body must reference $GITHUB_PAT, not embed the token,
    # so the token never lands in the helper file on disk.
    src = (Path(__file__).resolve().parent.parent
           / "src" / "s7bb_fetcher" / "pusher.py").read_text()
    assert re.search(r'printf %s "\$GITHUB_PAT"', src)
