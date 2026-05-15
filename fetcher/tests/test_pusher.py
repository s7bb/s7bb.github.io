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
from s7bb_fetcher.pusher import PushOutcome, push_data


@pytest.fixture
def working_repo(tmp_path: Path) -> git.Repo:
    """Working clone of a local bare upstream, seeded with a flat data-repo
    layout (`latest.json` at the root, no `data/` prefix) on `main`."""
    bare_path = tmp_path / "remote.git"
    git.Repo.init(bare_path, bare=True, initial_branch="main")
    work = git.Repo.clone_from(str(bare_path), tmp_path / "work")

    (Path(work.working_tree_dir) / "latest.json").write_text('{"v":0}\n')
    work.index.add(["latest.json"])
    work.index.commit(
        "seed",
        author=git.Actor("seed", "seed@local"),
        committer=git.Actor("seed", "seed@local"),
    )
    if work.active_branch.name != "main":
        work.git.branch("-M", "main")
    work.git.push("origin", "main")
    work.remotes["origin"].set_url("https://github.com/owner/s7bb.git")
    return work


@pytest.fixture
def dirty_latest(working_repo: git.Repo) -> git.Repo:
    target = Path(working_repo.working_tree_dir) / "latest.json"
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
    result = push_data(Path(dirty_latest.working_tree_dir))

    assert result is PushOutcome.COMMITTED_AND_PUSHED
    assert captured["args"][0] == "https://x-access-token@github.com/owner/s7bb.git"
    assert captured["args"][1] == "HEAD:refs/heads/main"
    assert captured["env"]["GITHUB_PAT"] == "ghp_fake"
    assert captured["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert captured["helper_existed_during_call"] is True
    # Helper unlinked after the push.
    assert not os.path.exists(captured["env"]["GIT_ASKPASS"])


def test_push_failure_propagates(monkeypatch, dirty_latest):
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")

    def fake_push(self, *args, **kwargs):
        raise git.GitCommandError(["git", "push"], 128, stderr=b"refused by ruleset")

    _install_fake_push(monkeypatch, fake_push)
    with pytest.raises(git.GitCommandError):
        push_data(Path(dirty_latest.working_tree_dir))


def test_helper_cleaned_up_on_push_failure(monkeypatch, dirty_latest):
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    pattern = os.path.join(tempfile.gettempdir(), "s7bb-askpass-*.sh")
    before = set(glob.glob(pattern))

    def fake_push(self, *args, **kwargs):
        raise git.GitCommandError(["git", "push"], 128, stderr=b"boom")

    _install_fake_push(monkeypatch, fake_push)
    with pytest.raises(git.GitCommandError):
        push_data(Path(dirty_latest.working_tree_dir))

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
        push_data(Path(dirty_latest.working_tree_dir))
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
    push_data(Path(dirty_latest.working_tree_dir))

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
    push_data(Path(dirty_latest.working_tree_dir))

    assert captured["url"] == "https://x-access-token@github.com/right/right.git"


def test_unparseable_origin_raises(monkeypatch, dirty_latest):
    dirty_latest.remotes["origin"].set_url("file:///tmp/not-github.git")
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    with pytest.raises(RuntimeError, match="cannot parse owner/repo"):
        push_data(Path(dirty_latest.working_tree_dir))


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


def test_push_data_stages_archive_and_latest(monkeypatch, dirty_latest):
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    work = Path(dirty_latest.working_tree_dir)

    arch_dir = work / "archive"
    arch_dir.mkdir(parents=True, exist_ok=True)
    (arch_dir / "2026-04.json").write_text('{"period":"2026-04"}\n')
    (arch_dir / "index.json").write_text('{"months":[]}\n')

    captured = {}

    def fake_push(self, *args, **kwargs):
        captured["url"] = args[0]
        return ""

    _install_fake_push(monkeypatch, fake_push)
    result = push_data(work)

    assert result is PushOutcome.COMMITTED_AND_PUSHED
    last = dirty_latest.head.commit
    files = set(last.stats.files.keys())
    assert "latest.json" in files
    assert "archive/2026-04.json" in files
    assert "archive/index.json" in files
    assert last.message.startswith("chore: update data ")


def test_push_data_skips_when_no_diff(monkeypatch, working_repo):
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    called = []

    def fake_push(self, *args, **kwargs):
        called.append(True)
        return ""

    _install_fake_push(monkeypatch, fake_push)
    result = push_data(Path(working_repo.working_tree_dir))
    assert result is PushOutcome.NOOP
    assert called == []


def test_push_data_single_commit_for_combined_changes(monkeypatch, dirty_latest):
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    work = Path(dirty_latest.working_tree_dir)
    arch_dir = work / "archive"
    arch_dir.mkdir(parents=True, exist_ok=True)
    (arch_dir / "2026-04.json").write_text('{"period":"2026-04"}\n')

    head_before = dirty_latest.head.commit
    _install_fake_push(monkeypatch, lambda self, *a, **kw: "")
    push_data(work)
    head_after = dirty_latest.head.commit

    assert head_after != head_before
    assert head_after.parents[0] == head_before


def test_push_outcome_enum_values():
    from s7bb_fetcher.pusher import PushOutcome

    assert PushOutcome.COMMITTED_AND_PUSHED.value == "committed_and_pushed"
    assert PushOutcome.PUSHED_EXISTING.value == "pushed_existing"
    assert PushOutcome.NOOP.value == "noop"


def test_is_ahead_of_origin_true_when_local_has_extra_commits(working_repo):
    from s7bb_fetcher.pusher import _is_ahead_of_origin

    # Add an extra local commit not on origin/main.
    target = Path(working_repo.working_tree_dir) / "latest.json"
    target.write_text('{"v":2}\n')
    working_repo.index.add(["latest.json"])
    working_repo.index.commit(
        "extra",
        author=git.Actor("a", "a@local"),
        committer=git.Actor("a", "a@local"),
    )

    assert _is_ahead_of_origin(working_repo) is True


def test_is_ahead_of_origin_false_when_in_sync(working_repo, tmp_path):
    from s7bb_fetcher.pusher import _is_ahead_of_origin

    # working_repo fixture pushes seed commit to the local bare upstream, so
    # origin/main already points at the same commit as HEAD — no network fetch needed.
    assert _is_ahead_of_origin(working_repo) is False


def test_push_data_pushes_existing_unpushed_commits(monkeypatch, working_repo):
    """Local HEAD is ahead of origin/main but working tree matches HEAD.

    Old behaviour: returned False ("no changes, skipping commit") — silent
    failure mode that allowed commits to accumulate on the VM for 29h on
    2026-05-14. New behaviour: returns PushOutcome.PUSHED_EXISTING and
    calls git.cmd.Git.push.
    """
    from s7bb_fetcher.pusher import PushOutcome, push_data

    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")

    # Make a local commit that origin/main does not yet have.
    target = Path(working_repo.working_tree_dir) / "latest.json"
    target.write_text('{"v":99}\n')
    working_repo.index.add(["latest.json"])
    working_repo.index.commit(
        "local-only commit",
        author=git.Actor("a", "a@local"),
        committer=git.Actor("a", "a@local"),
    )
    # Working tree now matches HEAD; nothing new to commit.

    push_calls = []

    def fake_push(self, *args, **kwargs):
        push_calls.append((args, kwargs.get("env", {}).copy()))

    _install_fake_push(monkeypatch, fake_push)

    result = push_data(Path(working_repo.working_tree_dir))

    assert result is PushOutcome.PUSHED_EXISTING
    assert len(push_calls) == 1


def test_push_data_noop_when_in_sync(monkeypatch, working_repo):
    from s7bb_fetcher.pusher import PushOutcome, push_data

    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")

    push_calls = []

    def fake_push(self, *args, **kwargs):
        push_calls.append(args)

    _install_fake_push(monkeypatch, fake_push)

    result = push_data(Path(working_repo.working_tree_dir))

    assert result is PushOutcome.NOOP
    assert push_calls == []


def test_push_data_commits_and_pushes_new_changes(monkeypatch, dirty_latest):
    from s7bb_fetcher.pusher import PushOutcome, push_data

    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")

    push_calls = []

    def fake_push(self, *args, **kwargs):
        push_calls.append(args)

    _install_fake_push(monkeypatch, fake_push)

    result = push_data(Path(dirty_latest.working_tree_dir))

    assert result is PushOutcome.COMMITTED_AND_PUSHED
    assert len(push_calls) == 1
