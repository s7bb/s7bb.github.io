# Pusher: loud failures + accurate startup_sync logging

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate silent buildup of unpushed local commits in the fetcher service, and stop `startup_sync` from logging `pushed` when nothing was pushed.

**Architecture:** Two real bugs were observed in production on 2026-05-14: the VM accumulated 29 unpushed local commits over ~29 hours while logs reported `action=push ... — pushed` every restart. Root cause is a combination of (a) `pusher.push_data` only pushing when there is something *new* to commit — pre-existing unpushed commits stay local forever, (b) `startup_sync._result` always logging `pushed` for `action=push` regardless of whether `push_data` actually called `git push`, and (c) `service._safe("push", ...)` swallowing push exceptions into a generic `export_job step <name> failed` log line that is easy to miss among normal export steps. This plan: makes `push_data` push the branch whenever `HEAD` is ahead of `origin/main` (regardless of whether a new commit was just made), tightens `startup_sync` so its log message reflects the real push outcome, and replaces the swallowing `_safe` call with a dedicated error handler that distinguishes push failures from other export-step failures and tracks consecutive-failure count.

**Tech Stack:** Python 3.12, GitPython, APScheduler, pytest, pytest-monkeypatch, freezegun.

---

## File Structure

- Modify: `fetcher/src/s7bb_fetcher/pusher.py` — split commit step from push step; always push when HEAD ≠ origin/main; return enum / dataclass instead of bool.
- Modify: `fetcher/src/s7bb_fetcher/startup_sync.py` — propagate real push outcome into `SyncResult`; never log `pushed` when push did not happen.
- Modify: `fetcher/src/s7bb_fetcher/service.py` — replace `_safe("push", ...)` with `_run_push_step` that logs at ERROR with `PUSH_FAILED` prefix and increments a module-level consecutive-failure counter (logged on each failure).
- Modify: `fetcher/tests/test_pusher.py` — new tests for the unpushed-commits scenario.
- Modify: `fetcher/tests/test_startup_sync.py` — new tests for accurate `SyncResult.message` when `push_data` returns "no_op".
- Modify: `fetcher/tests/test_service.py` — new test that a raising `pusher.push_data` produces a `PUSH_FAILED` log entry and does not abort the scheduler.
- Modify: `CHANGELOG.md` — `Fixed` entry under `[Unreleased]`.

No new files. No new dependencies.

---

## Task 1: Define `PushOutcome` return type for `pusher.push_data`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/pusher.py` (top of module, near `_PUSH_REFSPEC`)
- Test: `fetcher/tests/test_pusher.py`

- [ ] **Step 1: Write the failing test**

Add to `fetcher/tests/test_pusher.py`:

```python
def test_push_outcome_enum_values():
    from s7bb_fetcher.pusher import PushOutcome

    assert PushOutcome.COMMITTED_AND_PUSHED.value == "committed_and_pushed"
    assert PushOutcome.PUSHED_EXISTING.value == "pushed_existing"
    assert PushOutcome.NOOP.value == "noop"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd fetcher && uv run pytest tests/test_pusher.py::test_push_outcome_enum_values -v`
Expected: `ImportError` (no `PushOutcome` in `pusher`).

- [ ] **Step 3: Add the enum**

Add to top of `fetcher/src/s7bb_fetcher/pusher.py`, right after the `import` block:

```python
import enum


class PushOutcome(enum.Enum):
    """Result of a `push_data` call.

    - COMMITTED_AND_PUSHED: staged file changes -> new commit -> pushed.
    - PUSHED_EXISTING: nothing new to commit, but local HEAD was ahead of
      origin/main, so existing commits were pushed.
    - NOOP: nothing new to commit AND local HEAD already matches origin/main.
    """

    COMMITTED_AND_PUSHED = "committed_and_pushed"
    PUSHED_EXISTING = "pushed_existing"
    NOOP = "noop"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd fetcher && uv run pytest tests/test_pusher.py::test_push_outcome_enum_values -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/pusher.py fetcher/tests/test_pusher.py
git commit -m "refactor(pusher): introduce PushOutcome enum"
```

---

## Task 2: Helper `_is_ahead_of_origin(repo)` in pusher

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/pusher.py`
- Test: `fetcher/tests/test_pusher.py`

The helper answers: "does `HEAD` contain commits that `origin/main` does not?" — without performing a network fetch. The pusher relies on the local `origin/main` ref being a recent-enough snapshot of the remote; the service performs a fetch at startup via `git.Repo.remotes.origin.fetch()` (added later in Task 5).

- [ ] **Step 1: Write the failing test**

Add to `fetcher/tests/test_pusher.py`:

```python
def test_is_ahead_of_origin_true_when_local_has_extra_commits(working_repo):
    from s7bb_fetcher.pusher import _is_ahead_of_origin

    # Add an extra local commit not on origin/main.
    target = Path(working_repo.working_tree_dir) / "data" / "latest.json"
    target.write_text('{"v":2}\n')
    working_repo.index.add(["data/latest.json"])
    working_repo.index.commit(
        "extra",
        author=git.Actor("a", "a@local"),
        committer=git.Actor("a", "a@local"),
    )

    assert _is_ahead_of_origin(working_repo) is True


def test_is_ahead_of_origin_false_when_in_sync(working_repo):
    from s7bb_fetcher.pusher import _is_ahead_of_origin

    # working_repo fixture: HEAD already pushed to bare upstream via clone,
    # so HEAD and origin/main point at the same commit.
    working_repo.remotes["origin"].fetch()
    assert _is_ahead_of_origin(working_repo) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fetcher && uv run pytest tests/test_pusher.py::test_is_ahead_of_origin_true_when_local_has_extra_commits tests/test_pusher.py::test_is_ahead_of_origin_false_when_in_sync -v`
Expected: `ImportError` / `AttributeError`.

- [ ] **Step 3: Implement the helper**

Add to `fetcher/src/s7bb_fetcher/pusher.py`, above `push_data`:

```python
def _is_ahead_of_origin(repo: git.Repo) -> bool:
    """Return True iff local HEAD has commits that origin/main does not.

    Uses the local `origin/main` ref as-is — caller is responsible for
    refreshing it (e.g. via `origin.fetch()`) when freshness matters.
    """
    try:
        ahead = list(repo.iter_commits("origin/main..HEAD", max_count=1))
    except git.GitCommandError:
        # origin/main ref missing — treat as "nothing to compare against".
        return False
    return bool(ahead)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd fetcher && uv run pytest tests/test_pusher.py::test_is_ahead_of_origin_true_when_local_has_extra_commits tests/test_pusher.py::test_is_ahead_of_origin_false_when_in_sync -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/pusher.py fetcher/tests/test_pusher.py
git commit -m "feat(pusher): add _is_ahead_of_origin helper"
```

---

## Task 3: `push_data` returns `PushOutcome` and always pushes when ahead

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/pusher.py:74-114` (the `push_data` function)
- Test: `fetcher/tests/test_pusher.py`

This is the core behaviour change: if `HEAD` is ahead of `origin/main` and there is nothing new to commit, the function now still pushes the existing commits.

- [ ] **Step 1: Write the failing test — pushed_existing path**

Add to `fetcher/tests/test_pusher.py`:

```python
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
    target = Path(working_repo.working_tree_dir) / "data" / "latest.json"
    target.write_text('{"v":99}\n')
    working_repo.index.add(["data/latest.json"])
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
    assert len(push_calls) == 1  # push was actually attempted
```

- [ ] **Step 2: Write the failing test — noop path**

Add to `fetcher/tests/test_pusher.py`:

```python
def test_push_data_noop_when_in_sync(monkeypatch, working_repo):
    from s7bb_fetcher.pusher import PushOutcome, push_data

    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    working_repo.remotes["origin"].fetch()  # ensure origin/main current

    push_calls = []

    def fake_push(self, *args, **kwargs):
        push_calls.append(args)

    _install_fake_push(monkeypatch, fake_push)

    result = push_data(Path(working_repo.working_tree_dir))

    assert result is PushOutcome.NOOP
    assert push_calls == []  # nothing pushed when local == origin/main
```

- [ ] **Step 3: Write the failing test — committed_and_pushed path**

Add to `fetcher/tests/test_pusher.py`:

```python
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
```

- [ ] **Step 4: Run all three tests to verify they fail**

Run: `cd fetcher && uv run pytest tests/test_pusher.py -k "push_data_pushes_existing or push_data_noop or push_data_commits_and_pushes" -v`
Expected: all three FAIL — either return value is `True`/`False` (bool, not enum) or push count assertions fail.

- [ ] **Step 5: Update existing bool-return tests**

Some existing tests in `fetcher/tests/test_pusher.py` assert `push_data(...) is True` or `is False`. Find them and update to the enum equivalents:

Run: `cd fetcher && uv run grep -n "push_data(" tests/test_pusher.py`

For each assertion of the form `assert push_data(...) is True`, replace with `assert push_data(...) is PushOutcome.COMMITTED_AND_PUSHED`. For `is False`, replace with `is PushOutcome.NOOP`. Add `from s7bb_fetcher.pusher import PushOutcome` near the top of the test file if not already present.

- [ ] **Step 6: Modify `push_data`**

Replace the body of `push_data` in `fetcher/src/s7bb_fetcher/pusher.py:74-114` with:

```python
def push_data(repo_path: Path) -> PushOutcome:
    """Stage data files, commit if changed, then push HEAD to origin/main.

    Always pushes if local HEAD is ahead of origin/main, even when nothing
    new was committed. This prevents silent accumulation of unpushed local
    commits if a previous push failed.

    Raises on git or push errors.
    """
    repo = git.Repo(str(repo_path))

    paths: list[str] = []
    if (repo_path / _LATEST_JSON).exists():
        paths.append(_LATEST_JSON)
    archive_files = sorted((repo_path / "data" / "archive").glob("*.json"))
    for f in archive_files:
        paths.append(f.relative_to(repo_path).as_posix())

    if not paths:
        logger.warning("push_data: no data files found, skipping")
        return PushOutcome.NOOP

    repo.index.add(paths)

    committed_new = False
    if repo.index.diff("HEAD"):
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        author = _actor("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "s7bb-bot")
        committer = _actor("GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "s7bb-bot")
        repo.index.commit(
            f"chore: update data {ts}",
            author=author,
            committer=committer,
        )
        committed_new = True

    if not committed_new and not _is_ahead_of_origin(repo):
        logger.info("push_data: nothing to commit and local == origin/main, noop")
        return PushOutcome.NOOP

    token = os.environ.get("GITHUB_PAT", "").strip()
    if not token:
        raise RuntimeError("GITHUB_PAT not set; cannot push to GitHub")

    _push_via_pat(repo, token)

    if committed_new:
        logger.info("push_data: committed and pushed to origin/main (%d file(s))", len(paths))
        return PushOutcome.COMMITTED_AND_PUSHED
    logger.info("push_data: pushed existing commits to origin/main (no new commit)")
    return PushOutcome.PUSHED_EXISTING
```

- [ ] **Step 7: Run the full pusher test file**

Run: `cd fetcher && uv run pytest tests/test_pusher.py -v`
Expected: all PASS (including the three new tests from steps 1-3 and the updated existing tests from step 5).

- [ ] **Step 8: Commit**

```bash
git add fetcher/src/s7bb_fetcher/pusher.py fetcher/tests/test_pusher.py
git commit -m "fix(pusher): push existing local commits when HEAD ahead of origin

Previously push_data returned False without pushing when nothing new was
staged, even if local HEAD already had unpushed commits. Allowed commits
to accumulate locally for ~29h on the VM on 2026-05-14 while logs claimed
pushes succeeded."
```

---

## Task 4: `startup_sync` reflects real push outcome in message

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/startup_sync.py:95-100, 123-129`
- Test: `fetcher/tests/test_startup_sync.py`

`_push` currently calls `pusher.push_data` and discards the result. Now it must surface it so the log message at `_result(...)` reflects whether a push truly happened.

- [ ] **Step 1: Write the failing test — message reflects PUSHED_EXISTING**

Add to `fetcher/tests/test_startup_sync.py`:

```python
def test_startup_sync_message_reports_pushed_existing(tmp_path, monkeypatch):
    """When push_data returns PUSHED_EXISTING, message must say so, not 'pushed'."""
    from datetime import datetime, UTC
    import json
    from unittest.mock import MagicMock

    from s7bb_fetcher import startup_sync
    from s7bb_fetcher.pusher import PushOutcome

    data_path = tmp_path / "latest.json"
    data_path.write_text(json.dumps({"generated_at": "2026-05-14T17:00:00+00:00"}))

    # Remote is older.
    remote_body = json.dumps({"generated_at": "2026-05-13T14:00:00+00:00"}).encode()
    remote_ts = datetime(2026, 5, 13, 14, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(
        startup_sync, "_fetch_remote",
        MagicMock(return_value=(remote_body, remote_ts)),
    )

    fake_push = MagicMock(return_value=PushOutcome.PUSHED_EXISTING)
    monkeypatch.setattr("s7bb_fetcher.pusher.push_data", fake_push)

    result = startup_sync.startup_sync(tmp_path, data_path, "owner/repo")

    assert result.action == "push"
    assert "pushed existing commits" in result.message
    assert "pushed\n" not in result.message  # explicit anti-regression
```

- [ ] **Step 2: Write the failing test — message reflects NOOP**

Add to `fetcher/tests/test_startup_sync.py`:

```python
def test_startup_sync_message_reports_noop_when_push_data_noop(tmp_path, monkeypatch):
    """Local newer but pusher says NOOP (e.g. no data files) -> message says so."""
    from datetime import datetime, UTC
    import json
    from unittest.mock import MagicMock

    from s7bb_fetcher import startup_sync
    from s7bb_fetcher.pusher import PushOutcome

    data_path = tmp_path / "latest.json"
    data_path.write_text(json.dumps({"generated_at": "2026-05-14T17:00:00+00:00"}))

    remote_body = json.dumps({"generated_at": "2026-05-13T14:00:00+00:00"}).encode()
    remote_ts = datetime(2026, 5, 13, 14, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(
        startup_sync, "_fetch_remote",
        MagicMock(return_value=(remote_body, remote_ts)),
    )

    monkeypatch.setattr(
        "s7bb_fetcher.pusher.push_data",
        MagicMock(return_value=PushOutcome.NOOP),
    )

    result = startup_sync.startup_sync(tmp_path, data_path, "owner/repo")

    # Logical action is still "push attempted" but message must not lie.
    assert result.action == "push"
    assert "nothing pushed" in result.message.lower()
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `cd fetcher && uv run pytest tests/test_startup_sync.py -k "message_reports" -v`
Expected: FAIL — current code always appends "— pushed".

- [ ] **Step 4: Modify `_push` and the `delta > 0` branch in `_run`**

In `fetcher/src/s7bb_fetcher/startup_sync.py`:

Replace `_push` (lines 123-129) with:

```python
def _push(repo_path: Path) -> "pusher.PushOutcome":
    return pusher.push_data(repo_path)
```

Replace the `if delta > 0:` block in `_run` (lines 95-100) with:

```python
    if delta > 0:
        outcome = _push(repo_path)
        suffix = _push_suffix(outcome, delta)
        return _result(
            "push", local_ts, remote_ts,
            f"local newer by {delta:.0f}s — {suffix}",
        )
```

Also update the earlier `_push(repo_path)` call (around line 78) to drop the return value:

```python
    if local_ts is not None and remote_ts is None:
        outcome = _push(repo_path)
        return _result(
            "push", local_ts, remote_ts,
            f"remote 404 — {_push_suffix(outcome, None)}",
        )
```

Add the helper directly below `_push`:

```python
def _push_suffix(outcome: "pusher.PushOutcome", delta: float | None) -> str:
    from . import pusher as _pusher

    if outcome is _pusher.PushOutcome.COMMITTED_AND_PUSHED:
        return "committed and pushed"
    if outcome is _pusher.PushOutcome.PUSHED_EXISTING:
        return "pushed existing commits"
    return "nothing pushed (working tree clean and local in sync with origin/main)"
```

Remove the now-unused warning `logger.warning("startup_sync: local generated_at is newer but git working tree matches HEAD; nothing to commit")` — its information is now captured in the `_result` message.

- [ ] **Step 5: Run the full startup_sync test file**

Run: `cd fetcher && uv run pytest tests/test_startup_sync.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add fetcher/src/s7bb_fetcher/startup_sync.py fetcher/tests/test_startup_sync.py
git commit -m "fix(startup_sync): message reflects real push_data outcome

Previously startup_sync logged 'pushed' for action=push regardless of
whether push_data actually called git push. Misled operators during the
2026-05-14 incident where 29 commits sat unpushed while logs claimed
hourly success."
```

---

## Task 5: Service `_run_push_step` with loud failure logging

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/service.py:87`
- Test: `fetcher/tests/test_service.py`

Replace the swallowing `_safe("push", pusher.push_data, REPO_PATH)` with a dedicated handler that (a) logs push failures at ERROR with a `PUSH_FAILED` prefix and a consecutive-failure counter and (b) refreshes `origin/main` first so `_is_ahead_of_origin` has a current reference.

- [ ] **Step 1: Write the failing test — push failure increments counter**

Add to `fetcher/tests/test_service.py`:

```python
def test_run_push_step_logs_push_failed_on_exception(mocks, caplog):
    from s7bb_fetcher import service

    mocks["push_data"].side_effect = RuntimeError("simulated push failure")

    with caplog.at_level("ERROR"):
        service._run_push_step()

    matches = [r for r in caplog.records if "PUSH_FAILED" in r.message]
    assert len(matches) == 1
    assert "consecutive_failures=1" in matches[0].message
    assert "RuntimeError" in matches[0].message or matches[0].exc_info is not None


def test_run_push_step_resets_counter_on_success(mocks, caplog, monkeypatch):
    from s7bb_fetcher import pusher, service

    # First call fails, second succeeds; counter must reset to 0.
    mocks["push_data"].side_effect = [
        RuntimeError("boom"),
        pusher.PushOutcome.COMMITTED_AND_PUSHED,
    ]

    service._run_push_step()
    service._run_push_step()

    assert service._consecutive_push_failures == 0
```

- [ ] **Step 2: Write the failing test — fetch happens before push**

Add to `fetcher/tests/test_service.py`:

```python
def test_run_push_step_fetches_origin_before_pushing(mocks, monkeypatch, tmp_path):
    from unittest.mock import MagicMock
    from s7bb_fetcher import pusher, service

    fake_origin = MagicMock()
    fake_remote = MagicMock()
    fake_remote.fetch = MagicMock()
    fake_origin.remotes = {"origin": fake_remote}

    monkeypatch.setattr("git.Repo", MagicMock(return_value=fake_origin))
    mocks["push_data"].return_value = pusher.PushOutcome.NOOP

    service._run_push_step()

    fake_remote.fetch.assert_called_once()
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `cd fetcher && uv run pytest tests/test_service.py -k "run_push_step" -v`
Expected: FAIL — `_run_push_step` does not exist yet.

- [ ] **Step 4: Implement `_run_push_step` and the counter**

In `fetcher/src/s7bb_fetcher/service.py`:

Add near the top of the module, after the constants block:

```python
_consecutive_push_failures = 0
```

Add a new function above `_export_job`:

```python
def _run_push_step() -> None:
    """Push step for the hourly export job — loud failures, fetch first.

    Logs at ERROR with the `PUSH_FAILED` prefix and a consecutive-failure
    counter so the metric is visible in `docker logs | grep PUSH_FAILED`.
    Does not raise — the scheduler must keep running so the next hour gets
    another shot.
    """
    global _consecutive_push_failures

    import git

    from . import pusher

    try:
        repo = git.Repo(str(REPO_PATH))
        repo.remotes["origin"].fetch()
        pusher.push_data(REPO_PATH)
    except Exception:
        _consecutive_push_failures += 1
        logger.exception(
            "PUSH_FAILED consecutive_failures=%d — commits will accumulate "
            "locally until next successful push",
            _consecutive_push_failures,
        )
        return

    _consecutive_push_failures = 0
```

Replace line 87 (`_safe("push", pusher.push_data, REPO_PATH)`) with:

```python
    _run_push_step()
```

Drop the inline `from . import ... pusher` at the top of `_export_job` if it becomes unused after this change.

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `cd fetcher && uv run pytest tests/test_service.py -k "run_push_step" -v`
Expected: all PASS.

- [ ] **Step 6: Run the full service test file**

Run: `cd fetcher && uv run pytest tests/test_service.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add fetcher/src/s7bb_fetcher/service.py fetcher/tests/test_service.py
git commit -m "fix(service): loud PUSH_FAILED log + consecutive-failure counter

Replaces _safe('push', ...) which buried push exceptions among generic
export-step failures. New _run_push_step logs at ERROR with a PUSH_FAILED
prefix and a counter that resets on success — visible in
'docker logs | grep PUSH_FAILED'."
```

---

## Task 6: Update CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add entries under `[Unreleased]` `Fixed`**

Open `CHANGELOG.md` and add under the `[Unreleased]` section's `Fixed` subsection (create it if missing — Keep a Changelog ordering: Added / Changed / Deprecated / Removed / Fixed / Security):

```markdown
### Fixed

- Pusher now pushes pre-existing unpushed local commits even when no new
  data file changes were staged. Previously commits could accumulate
  locally for hours while logs reported success.
- `startup_sync` log message reflects whether `push_data` actually pushed.
  No more `action=push ... — pushed` when nothing was pushed.
- Hourly push failures now log at ERROR with a `PUSH_FAILED` prefix and a
  consecutive-failure counter, instead of being buried among generic
  `export_job step push failed` lines.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): note pusher loud-failure fixes"
```

---

## Task 7: End-to-end manual verification

**Files:** none (operational check)

- [ ] **Step 1: Full test suite green**

Run: `cd fetcher && uv run pytest -v`
Expected: all PASS (no regressions in `test_cli`, `test_exporter`, `test_parser`, `test_preflight`, `test_storage`).

- [ ] **Step 2: Lint clean**

Run: `cd fetcher && uv run ruff check src tests`
Expected: no errors.

- [ ] **Step 3: Smoke test in container**

On the VM:

```bash
docker compose up -d --build s7bb-fetcher
docker compose logs -f s7bb-fetcher | grep -E "PUSH_FAILED|push_data:|startup_sync"
```

Expected within one export hour:
- `startup_sync` log lines clearly state `committed and pushed`, `pushed existing commits`, or `nothing pushed` — never a bare `pushed` when no push occurred.
- If push fails, a single `PUSH_FAILED consecutive_failures=N` ERROR line per failed attempt.
- `git fetch origin && git log origin/main..HEAD --oneline` on the VM returns empty after a successful export.

---

## Out of scope

Deliberately not in this plan:

- Replacing the PAT-over-HTTPS scheme. The 2026-05-14 incident was about observability, not auth.
- Migrating to the orphan data branch design from `2026-05-14-orphan-data-branch.md`. That work has its own plan.
- Adding metrics export to Prometheus/etc. for the consecutive-failure counter. Logging is sufficient for the current single-VM deployment.
- Retry/backoff inside `_run_push_step`. Hourly scheduler cadence is the retry interval.
