# Orphan `data` Branch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple the VM's hourly data pushes from `main` by introducing an orphan `data` branch with no shared history, eliminating non-fast-forward push collisions with Dependabot/PR merges. Bundle a client-side freshness badge that surfaces stale data.

**Architecture:** A new orphan branch `data` (flat layout: `latest.json`, `archive/*.json`, `archive/index.json` at root) is the sole target of the VM's hourly push. `main` no longer tracks `data/`. The container clones only `data` shallowly; the exporter writes to `/data` (host bind-mount, untracked) and a new service step copies to `/repo` at the root for staging. GitHub Actions checks out both refs and assembles them into the deployed site. A new `site/src/freshness.ts` module computes `frisch`/`verzoegert`/`veraltet` from `generated_at` and renders a coloured badge alongside the existing "Stand:" line on every data-driven page.

**Tech Stack:** Python 3.11+ (fetcher, GitPython), TypeScript + Vite + Vitest (site), GitHub Actions, Docker Compose.

**Reference spec:** `docs/superpowers/specs/2026-05-14-orphan-data-branch-design.md`

---

## File structure

**Modified (fetcher):**
- `fetcher/src/s7bb_fetcher/pusher.py` — refspec → `refs/heads/data`; flat staging paths; new `fetch + merge --ff-only origin/data` step before commit.
- `fetcher/src/s7bb_fetcher/startup_sync.py` — raw URL template switches `main` → `data`.
- `fetcher/src/s7bb_fetcher/exporter.py` — `ORDER BY scheduled_time, train_id` in both queries.
- `fetcher/src/s7bb_fetcher/service.py` — new step copies `/data/{latest.json,archive/*.json}` → `/repo/{latest.json,archive/*.json}` before `pusher.push_data`.
- `fetcher/tests/test_pusher.py` — fixtures rebuilt for flat layout; new refspec assertion; new ff-only merge test.
- `fetcher/tests/test_startup_sync.py` — URL template assertion updated.
- `fetcher/tests/test_exporter.py` — assertion on stable ordering for ties.
- `fetcher/tests/test_service.py` — assertion that copy step runs.

**Modified (site):**
- `site/src/style.css` — `.freshness`, `.freshness--frisch`, `.freshness--verzoegert`, `.freshness--veraltet` rules.
- `site/src/pages/today.ts` — render badge in `.data-age` line; mount setInterval.
- `site/src/pages/week.ts` — append `.data-age` line with badge.
- `site/src/pages/stats.ts` — prepend badge to existing `.data-age` line.
- `site/src/pages/archive-list.ts` — append `.data-age` line with badge (uses `idx.generated_at`).

**Created (site):**
- `site/src/freshness.ts` — `freshnessState()`, `renderFreshnessBadge()`, `mountFreshnessTicker()`, exported thresholds.
- `site/src/freshness.test.ts` — boundary and timezone tests.

**Modified (infra):**
- `.github/workflows/build-site.yml` — trigger on `main` and `data`; two-ref checkout; data-staging step uses `data-branch/` working dir.
- `docker-compose.yml` — `s7bb-data-init` service (profile `dev`); `s7bb-data-checkout` named volume; `s7bb-site-dev.depends_on` + `:ro` mount.
- `site/vite.config.ts` — verify `server.fs.allow: [".."]` (already present — no change expected; confirm).
- `.gitignore` — add `/data/` and `/.data-checkout/`.

**Modified (docs):**
- `README.md` — §VM Setup, §GitHub Pages Setup, §Local development.
- `CLAUDE.md` — architecture diagram + repo layout notes.
- `CHANGELOG.md` — two `[Unreleased]` entries.

**Removed (in final task):**
- `data/latest.json`, `data/archive/*.json` — `git rm -r data/`.

---

## Task 1: Stable export ordering (tie-break on `train_id`)

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/exporter.py:42-45` and `:184-191`
- Modify: `fetcher/tests/test_exporter.py`

- [ ] **Step 1: Write failing test** for stable ordering on tied `scheduled_time`.

Append to `fetcher/tests/test_exporter.py`:

```python
def test_export_latest_orders_ties_by_train_id(tmp_path):
    from s7bb_fetcher.exporter import export_latest
    from s7bb_fetcher.storage import open_db, upsert_records

    conn = open_db(tmp_path / "test.db")
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    # Insert in non-sorted train_id order at the same scheduled_time.
    upsert_records(conn, [
        _make_arrival("m_zzz", f"{today}T10:00:00+00:00", "muenchen"),
        _make_arrival("m_aaa", f"{today}T10:00:00+00:00", "muenchen"),
    ])
    out = tmp_path / "latest.json"
    export_latest(conn, out)
    arrivals = json.loads(out.read_text())["arrivals"]
    same_minute = [a for a in arrivals if a["scheduled_time"].startswith(f"{today}T10:00")]
    assert [a["train_id"] for a in same_minute] == ["m_aaa", "m_zzz"]


def test_export_monthly_archive_orders_ties_by_train_id(tmp_path):
    from s7bb_fetcher.exporter import export_monthly_archive
    from s7bb_fetcher.storage import open_db, upsert_records

    conn = open_db(tmp_path / "test.db")
    upsert_records(conn, [
        _make_arrival("z2", "2026-04-15T10:00:00+00:00", "muenchen"),
        _make_arrival("a1", "2026-04-15T10:00:00+00:00", "muenchen"),
    ])
    out = tmp_path / "2026-04.json"
    export_monthly_archive(conn, 2026, 4, out)
    arrivals = json.loads(out.read_text())["arrivals"]
    same_minute = [a for a in arrivals if a["scheduled_time"].startswith("2026-04-15T10:00")]
    assert [a["train_id"] for a in same_minute] == ["a1", "z2"]
```

- [ ] **Step 2: Run tests, verify failure.**

Run: `cd fetcher && uv run pytest tests/test_exporter.py -v -k order`
Expected: FAIL — order is implementation-defined without explicit tie-break.

- [ ] **Step 3: Implement** by adding `train_id` to both `ORDER BY` clauses.

In `fetcher/src/s7bb_fetcher/exporter.py`, replace `ORDER BY scheduled_time` (two occurrences, lines ~44 and ~188) with:

```python
ORDER BY scheduled_time, train_id
```

- [ ] **Step 4: Run tests, verify pass.**

Run: `cd fetcher && uv run pytest tests/test_exporter.py -v`
Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
git add fetcher/src/s7bb_fetcher/exporter.py fetcher/tests/test_exporter.py
git commit -m "refactor(exporter): tie-break ORDER BY scheduled_time on train_id

Stable row ordering for the hourly archive rewrite improves git delta
compression on the (soon-to-be) data branch."
```

---

## Task 2: Pusher — refspec switches to `data`, flat staging paths

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/pusher.py`
- Modify: `fetcher/tests/test_pusher.py`

- [ ] **Step 1: Rewrite the `working_repo` fixture** to seed an orphan-style flat layout.

In `fetcher/tests/test_pusher.py`, replace the existing `working_repo` fixture body (lines 22-43) with:

```python
@pytest.fixture
def working_repo(tmp_path: Path) -> git.Repo:
    """Local bare upstream + working clone seeded with a flat data-branch
    layout (`latest.json` and `archive/` at the root, no `data/` prefix)."""
    bare_path = tmp_path / "remote.git"
    git.Repo.init(bare_path, bare=True, initial_branch="data")
    work = git.Repo.clone_from(str(bare_path), tmp_path / "work")
    work.remotes["origin"].set_url("https://github.com/owner/s7bb.git")

    work_root = Path(work.working_tree_dir)
    (work_root / "latest.json").write_text('{"v":0}\n')
    work.index.add(["latest.json"])
    work.index.commit(
        "seed",
        author=git.Actor("seed", "seed@local"),
        committer=git.Actor("seed", "seed@local"),
    )
    if work.active_branch.name != "data":
        work.git.branch("-M", "data")
    return work
```

- [ ] **Step 2: Update `dirty_latest` fixture** so it writes to the new flat path.

Replace lines 46-50 of `fetcher/tests/test_pusher.py`:

```python
@pytest.fixture
def dirty_latest(working_repo: git.Repo) -> git.Repo:
    target = Path(working_repo.working_tree_dir) / "latest.json"
    target.write_text('{"v":1}\n')
    return working_repo
```

- [ ] **Step 3: Update existing assertions** that hard-code `HEAD:refs/heads/main` and `data/...` paths.

In `fetcher/tests/test_pusher.py`:

- Line 91 — change to:
  ```python
  assert captured["args"][1] == "HEAD:refs/heads/data"
  ```
- In `test_push_data_stages_archive_and_latest` (lines 203-227) — change all four `data/` path strings:

  ```python
  arch_dir = work / "archive"
  arch_dir.mkdir(parents=True, exist_ok=True)
  (arch_dir / "2026-04.json").write_text('{"period":"2026-04"}\n')
  (arch_dir / "index.json").write_text('{"months":[]}\n')
  ...
  assert "latest.json" in files
  assert "archive/2026-04.json" in files
  assert "archive/index.json" in files
  ```

- In `test_push_data_single_commit_for_combined_changes` (lines 244-257) — same flat-path rewrite:

  ```python
  arch_dir = work / "archive"
  arch_dir.mkdir(parents=True, exist_ok=True)
  (arch_dir / "2026-04.json").write_text('{"period":"2026-04"}\n')
  ```

- [ ] **Step 4: Run tests, verify failure.**

Run: `cd fetcher && uv run pytest tests/test_pusher.py -v`
Expected: failures in tests that assert the refspec and the staged file list.

- [ ] **Step 5: Implement pusher changes** — refspec constant + flat paths.

In `fetcher/src/s7bb_fetcher/pusher.py`, replace the module-level constants and the path-staging block:

```python
_LATEST_JSON = "latest.json"
_ARCHIVE_GLOB = "archive/*.json"
_HTTPS_USER = "x-access-token"
_PUSH_REFSPEC = "HEAD:refs/heads/data"
```

In `push_data`, replace the `paths` discovery block (lines 82-91) with:

```python
    paths: list[str] = []
    if (repo_path / _LATEST_JSON).exists():
        paths.append(_LATEST_JSON)
    archive_files = sorted((repo_path / "archive").glob("*.json"))
    for f in archive_files:
        paths.append(f.relative_to(repo_path).as_posix())

    if not paths:
        logger.warning("push_data: no data files found, skipping")
        return False
```

Update the final log line (line 113):

```python
    _push_via_pat(repo, token)
    logger.info("push_data: pushed to origin/data (%d file(s))", len(paths))
    return True
```

Update the module docstring (line 1):

```python
"""Push latest.json + archive/*.json to the data branch via GitHub PAT (HTTPS)."""
```

- [ ] **Step 6: Run tests, verify pass.**

Run: `cd fetcher && uv run pytest tests/test_pusher.py -v`
Expected: all pass.

- [ ] **Step 7: Commit.**

```bash
git add fetcher/src/s7bb_fetcher/pusher.py fetcher/tests/test_pusher.py
git commit -m "feat(pusher): push to data branch with flat layout

Push refspec switches from refs/heads/main to refs/heads/data and the
working-tree staging paths drop the data/ prefix. Sets up the orphan
data branch migration (see docs/superpowers/specs/2026-05-14-orphan-data-branch-design.md)."
```

---

## Task 3: Pusher — defensive `fetch + merge --ff-only origin/data`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/pusher.py`
- Modify: `fetcher/tests/test_pusher.py`

- [ ] **Step 1: Write failing tests.**

Append to `fetcher/tests/test_pusher.py`:

```python
def test_push_data_fetches_origin_data_before_commit(monkeypatch, dirty_latest):
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    calls: list[tuple[str, tuple, dict]] = []

    real_fetch = git.cmd.Git.fetch
    real_merge = git.cmd.Git.execute  # merge invoked via repo.git.merge → execute

    def fake_fetch(self, *args, **kwargs):
        calls.append(("fetch", args, kwargs))
        return ""

    def fake_merge(self, *args, **kwargs):
        # repo.git.merge proxies through this; record only merge invocations.
        if args and args[0] and args[0][:2] == ["git", "merge"]:
            calls.append(("merge", tuple(args[0]), kwargs))
        return ""

    monkeypatch.setattr(git.cmd.Git, "fetch", fake_fetch, raising=False)
    _install_fake_push(monkeypatch, lambda self, *a, **kw: "")

    # Spy merge via the higher-level wrapper.
    real_repo_git_merge = git.Repo(str(dirty_latest.working_tree_dir)).git.merge
    monkeypatch.setattr(
        git.cmd.Git, "merge",
        lambda self, *a, **kw: calls.append(("merge", a, kw)) or "",
        raising=False,
    )

    push_data(Path(dirty_latest.working_tree_dir))

    kinds = [c[0] for c in calls]
    assert "fetch" in kinds, f"expected fetch call before commit, saw {kinds}"
    assert "merge" in kinds, f"expected merge --ff-only call before commit, saw {kinds}"
    # Fetch must precede merge.
    assert kinds.index("fetch") < kinds.index("merge")
    # Fetch args target origin/data.
    fetch_args = [c for c in calls if c[0] == "fetch"][0][1]
    assert "origin" in fetch_args and "data" in fetch_args
    # Merge args carry --ff-only.
    merge_args = [c for c in calls if c[0] == "merge"][0][1]
    assert "--ff-only" in merge_args


def test_push_data_raises_when_ff_only_merge_fails(monkeypatch, dirty_latest):
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    monkeypatch.setattr(git.cmd.Git, "fetch", lambda self, *a, **kw: "", raising=False)

    def fake_merge(self, *args, **kwargs):
        raise git.GitCommandError(["git", "merge", "--ff-only", "origin/data"], 128,
                                  stderr=b"not possible to fast-forward")

    monkeypatch.setattr(git.cmd.Git, "merge", fake_merge, raising=False)
    pushed = []
    _install_fake_push(monkeypatch, lambda self, *a, **kw: pushed.append(a) or "")

    with pytest.raises(git.GitCommandError, match="not possible to fast-forward"):
        push_data(Path(dirty_latest.working_tree_dir))
    assert pushed == [], "must not push when ff-only merge fails"
```

- [ ] **Step 2: Run tests, verify failure.**

Run: `cd fetcher && uv run pytest tests/test_pusher.py::test_push_data_fetches_origin_data_before_commit tests/test_pusher.py::test_push_data_raises_when_ff_only_merge_fails -v`
Expected: FAIL — `fetch` / `merge` not called by current pusher.

- [ ] **Step 3: Implement.**

In `fetcher/src/s7bb_fetcher/pusher.py`, add the fetch+merge step at the start of `push_data` (right after `repo = git.Repo(...)`):

```python
def push_data(repo_path: Path) -> bool:
    """Stage latest.json + archive/*.json, ff-only merge origin/data, commit, push.

    Returns True if a commit was made and pushed, False if nothing changed.
    Raises on git or push errors, including a non-fast-forwardable origin/data.
    """
    repo = git.Repo(str(repo_path))

    # Defensive: in the steady state nobody else writes to `data`, so this is a
    # no-op. If a second writer ever appears, fail loudly instead of silently
    # overwriting their commit on the next push.
    repo.git.fetch("origin", "data")
    repo.git.merge("--ff-only", "origin/data")

    paths: list[str] = []
    ...
```

- [ ] **Step 4: Run tests, verify pass.**

Run: `cd fetcher && uv run pytest tests/test_pusher.py -v`
Expected: all pass (including the existing happy-path test — fakes for `fetch`/`merge` may need to be added as autouse no-ops for the other tests; if they fail, add `monkeypatch.setattr(git.cmd.Git, "fetch"/"merge", ...)` no-ops to the affected tests or to the `_hermetic_env` fixture).

- [ ] **Step 5: If existing tests now fail** because they don't stub `fetch`/`merge`, extend `_hermetic_env` to stub them as no-ops.

Edit `fetcher/tests/test_pusher.py` `_hermetic_env`:

```python
@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    """Strip env vars + stub network-touching git ops (fetch/merge no-ops)."""
    for var in (
        "GITHUB_PAT", "GITHUB_REPO_SLUG",
        "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
        "GIT_ASKPASS", "GIT_TERMINAL_PROMPT",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(git.cmd.Git, "fetch", lambda self, *a, **kw: "", raising=False)
    monkeypatch.setattr(git.cmd.Git, "merge", lambda self, *a, **kw: "", raising=False)
```

Then re-test. Note: the two new tests in Step 1 must override these no-ops with their own spies (they already do via `monkeypatch.setattr`).

- [ ] **Step 6: Commit.**

```bash
git add fetcher/src/s7bb_fetcher/pusher.py fetcher/tests/test_pusher.py
git commit -m "feat(pusher): ff-only merge origin/data before commit

A no-op in the steady state (data branch has one writer), but turns a
silent overwrite into a loud error if a second writer ever appears."
```

---

## Task 4: Service — copy `/data` → `/repo` before push

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/service.py`
- Modify: `fetcher/tests/test_service.py`

The exporter writes JSON to `DATA_DIR` (host-bind-mounted, untracked). Pusher reads from `REPO_PATH` (data-branch shallow clone). The two were the same path on `main`; on `data` they diverge. A new step copies the exporter output into the branch working tree, preserving the existing separation between "produce" and "stage".

- [ ] **Step 1: Read existing test file** to understand patterns.

Run: `cd fetcher && head -80 tests/test_service.py` — sanity-check the patching style used for `pusher.push_data` and `exporter.*`.

- [ ] **Step 2: Write failing test.**

Append to `fetcher/tests/test_service.py`:

```python
def test_export_job_copies_data_dir_into_repo_path(tmp_path, monkeypatch):
    """After exporter writes /data, service copies into /repo before push."""
    from s7bb_fetcher import service

    data_dir = tmp_path / "data"
    repo_path = tmp_path / "repo"
    data_dir.mkdir()
    (data_dir / "archive").mkdir()
    repo_path.mkdir()

    monkeypatch.setattr(service, "DATA_DIR", data_dir)
    monkeypatch.setattr(service, "REPO_PATH", repo_path)
    monkeypatch.setattr(service, "DB_PATH", data_dir / "s7bb.db")
    monkeypatch.setattr(service, "OUT_PATH", data_dir / "latest.json")
    monkeypatch.setattr(service, "ARCHIVE_DIR", data_dir / "archive")
    monkeypatch.setattr(service, "INDEX_PATH", data_dir / "archive" / "index.json")

    # Stub the SQL-touching bits: synthesize the exporter output directly.
    from s7bb_fetcher import exporter, storage
    monkeypatch.setattr(storage, "open_db", lambda p: None)

    def fake_export_latest(_conn, out_path, **kw):
        out_path.write_text('{"v":1}')
    def fake_export_monthly(*a, **kw):
        out_path = a[3]
        out_path.write_text('{"period":"x"}')
    def fake_export_index(_dir, out_path):
        out_path.write_text('{"months":[]}')

    monkeypatch.setattr(exporter, "export_latest", fake_export_latest)
    monkeypatch.setattr(exporter, "export_monthly_archive", fake_export_monthly)
    monkeypatch.setattr(exporter, "export_archive_index", fake_export_index)

    pushed: list = []
    from s7bb_fetcher import pusher
    monkeypatch.setattr(pusher, "push_data", lambda p: pushed.append(p) or True)

    service._export_job()

    assert (repo_path / "latest.json").read_text() == '{"v":1}'
    assert (repo_path / "archive" / "index.json").read_text() == '{"months":[]}'
    assert pushed == [repo_path]
```

- [ ] **Step 3: Run, verify failure.**

Run: `cd fetcher && uv run pytest tests/test_service.py::test_export_job_copies_data_dir_into_repo_path -v`
Expected: FAIL — the copy step does not exist yet.

- [ ] **Step 4: Implement.**

In `fetcher/src/s7bb_fetcher/service.py`, add a helper near the top and call it inside `_export_job` before `_safe("push", ...)`:

```python
import shutil

def _stage_into_repo(data_dir: Path, repo_path: Path) -> None:
    """Copy exporter outputs from data_dir → repo_path at the branch root.

    Mirrors `latest.json` and `archive/*.json` into the data-branch working
    tree. Idempotent; overwrites destination files.
    """
    repo_archive = repo_path / "archive"
    repo_archive.mkdir(parents=True, exist_ok=True)

    latest = data_dir / "latest.json"
    if latest.exists():
        shutil.copy2(latest, repo_path / "latest.json")

    src_archive = data_dir / "archive"
    if src_archive.exists():
        for f in src_archive.glob("*.json"):
            shutil.copy2(f, repo_archive / f.name)
```

Then in `_export_job`, after `_safe("archive_index", ...)` and before `_safe("push", ...)`:

```python
    _safe("stage", _stage_into_repo, DATA_DIR, REPO_PATH)
    _safe("push", pusher.push_data, REPO_PATH)
```

- [ ] **Step 5: Run, verify pass.**

Run: `cd fetcher && uv run pytest tests/test_service.py -v`
Expected: pass.

- [ ] **Step 6: Commit.**

```bash
git add fetcher/src/s7bb_fetcher/service.py fetcher/tests/test_service.py
git commit -m "feat(service): stage data into /repo at branch root before push

Decouples 'produce JSON in /data' from 'stage for git push in /repo'.
Preserves the existing DATA_DIR/REPO_PATH separation after the data
branch loses the data/ prefix."
```

---

## Task 5: Startup-sync raw URL → `data` branch

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/startup_sync.py:154`
- Modify: `fetcher/tests/test_startup_sync.py`

- [ ] **Step 1: Write failing test.**

Append to `fetcher/tests/test_startup_sync.py`:

```python
def test_raw_url_template_targets_data_branch():
    from s7bb_fetcher.startup_sync import _RAW_URL_TMPL
    assert "/data/latest.json" in _RAW_URL_TMPL  # path on data branch
    assert "/main/" not in _RAW_URL_TMPL          # no longer reads from main
    formatted = _RAW_URL_TMPL.format(slug="owner/s7bb")
    assert formatted == "https://raw.githubusercontent.com/owner/s7bb/data/latest.json"
```

- [ ] **Step 2: Run, verify failure.**

Run: `cd fetcher && uv run pytest tests/test_startup_sync.py::test_raw_url_template_targets_data_branch -v`
Expected: FAIL.

- [ ] **Step 3: Implement.**

In `fetcher/src/s7bb_fetcher/startup_sync.py`, replace the template (line 154):

```python
_RAW_URL_TMPL = "https://raw.githubusercontent.com/{slug}/data/latest.json"
```

Also update the docstring (lines 1-11) and the log line (line 55):

```python
"""Reconcile local data/latest.json with the data branch at service startup.

On startup, before the scheduler begins, this module compares the local
``data/latest.json`` against the copy published on the orphan ``data``
branch and either pushes the local file (if local is newer), overwrites
local with the remote bytes (if remote is newer), or does nothing (if
they are in sync within a small clock-skew tolerance).
...
"""
```

```python
    logger.info("startup_sync: checking drift against origin/data (%s)", slug)
```

- [ ] **Step 4: Run all startup_sync tests, verify pass.**

Run: `cd fetcher && uv run pytest tests/test_startup_sync.py -v`
Expected: all pass. If any existing test hard-codes the URL string, update it to the new template inline.

- [ ] **Step 5: Commit.**

```bash
git add fetcher/src/s7bb_fetcher/startup_sync.py fetcher/tests/test_startup_sync.py
git commit -m "feat(startup-sync): reconcile against data branch raw URL"
```

---

## Task 6: Freshness module (`site/src/freshness.ts` + tests)

**Files:**
- Create: `site/src/freshness.ts`
- Create: `site/src/freshness.test.ts`

- [ ] **Step 1: Write failing tests.**

Create `site/src/freshness.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import {
  freshnessState,
  FRESHNESS_FRISCH_MAX_MIN,
  FRESHNESS_VERZOEGERT_MAX_MIN,
} from "./freshness.js";

const now = new Date("2026-05-14T12:00:00Z");
const minutesAgo = (n: number) =>
  new Date(now.getTime() - n * 60_000).toISOString();

describe("freshnessState", () => {
  it("returns 'frisch' at 0 min", () => {
    expect(freshnessState(minutesAgo(0), now)).toBe("frisch");
  });

  it("returns 'frisch' at 74 min (just under threshold)", () => {
    expect(freshnessState(minutesAgo(74), now)).toBe("frisch");
  });

  it("returns 'verzoegert' at exactly 75 min", () => {
    expect(freshnessState(minutesAgo(75), now)).toBe("verzoegert");
  });

  it("returns 'verzoegert' at 179 min", () => {
    expect(freshnessState(minutesAgo(179), now)).toBe("verzoegert");
  });

  it("returns 'veraltet' at exactly 180 min", () => {
    expect(freshnessState(minutesAgo(180), now)).toBe("veraltet");
  });

  it("returns 'veraltet' at 24h", () => {
    expect(freshnessState(minutesAgo(60 * 24), now)).toBe("veraltet");
  });

  it("handles ISO suffix '+00:00' identically to 'Z'", () => {
    const plus = "2026-05-14T11:00:00+00:00";
    const z    = "2026-05-14T11:00:00Z";
    expect(freshnessState(plus, now)).toBe(freshnessState(z, now));
  });

  it("is timezone-independent (input has +02:00 offset)", () => {
    // 2026-05-14T13:00:00+02:00 === 2026-05-14T11:00:00Z (60 min ago) → frisch
    expect(freshnessState("2026-05-14T13:00:00+02:00", now)).toBe("frisch");
  });

  it("exports thresholds as constants", () => {
    expect(FRESHNESS_FRISCH_MAX_MIN).toBe(75);
    expect(FRESHNESS_VERZOEGERT_MAX_MIN).toBe(180);
  });
});
```

- [ ] **Step 2: Run, verify failure.**

Run: `cd site && npx vitest run src/freshness.test.ts`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement** `site/src/freshness.ts`:

```typescript
export type FreshnessState = "frisch" | "verzoegert" | "veraltet";

export const FRESHNESS_FRISCH_MAX_MIN = 75;
export const FRESHNESS_VERZOEGERT_MAX_MIN = 180;

const LABELS: Record<FreshnessState, string> = {
  frisch: "aktuell",
  verzoegert: "verzögert",
  veraltet: "veraltet — Daten nicht aktuell",
};

export function freshnessState(generatedAt: string, now: Date = new Date()): FreshnessState {
  const ageMin = (now.getTime() - new Date(generatedAt).getTime()) / 60_000;
  if (ageMin < FRESHNESS_FRISCH_MAX_MIN) return "frisch";
  if (ageMin < FRESHNESS_VERZOEGERT_MAX_MIN) return "verzoegert";
  return "veraltet";
}

export function renderFreshnessBadge(state: FreshnessState): string {
  return `<span class="freshness freshness--${state}">●&nbsp;${LABELS[state]}</span>`;
}

/**
 * Re-evaluate state every 60s and update a single badge element in place.
 * Returns a teardown function that clears the interval.
 */
export function mountFreshnessTicker(
  el: HTMLElement,
  generatedAt: string,
): () => void {
  const apply = () => {
    const s = freshnessState(generatedAt, new Date());
    el.outerHTML = renderFreshnessBadge(s);
  };
  // First paint is the caller's responsibility (server-rendered HTML).
  const id = window.setInterval(() => {
    const cur = document.querySelector<HTMLElement>(`[data-freshness-anchor="${anchorId}"]`);
    if (!cur) { window.clearInterval(id); return; }
    const s = freshnessState(generatedAt, new Date());
    cur.className = `freshness freshness--${s}`;
    cur.firstChild?.replaceWith(document.createTextNode("● " + LABELS[s]));
  }, 60_000);
  // Anchor placeholder; not used by tests, only by tick lookup.
  const anchorId = "_unused";
  void apply;
  return () => window.clearInterval(id);
}
```

Note: the ticker implementation above is sketched but a simpler version is acceptable. Use this final, simpler implementation instead:

```typescript
/**
 * Re-evaluate state every 60s and update the badge element in place.
 * Returns a teardown function that clears the interval.
 */
export function mountFreshnessTicker(
  el: HTMLElement,
  generatedAt: string,
): () => void {
  const update = () => {
    const s = freshnessState(generatedAt, new Date());
    el.className = `freshness freshness--${s}`;
    el.textContent = `● ${LABELS[s]}`;
  };
  update();
  const id = window.setInterval(update, 60_000);
  return () => window.clearInterval(id);
}
```

Replace the sketched version with this final one in your implementation. Tests only cover `freshnessState` and the threshold constants.

- [ ] **Step 4: Run, verify pass.**

Run: `cd site && npx vitest run src/freshness.test.ts`
Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
git add site/src/freshness.ts site/src/freshness.test.ts
git commit -m "feat(site): freshness state computation and badge renderer

Pure module — pages will wire the badge in subsequent commits."
```

---

## Task 7: Freshness CSS

**Files:**
- Modify: `site/src/style.css`

- [ ] **Step 1: Append rules** to `site/src/style.css`:

```css
/* Freshness badge */
.freshness {
  display: inline-block;
  font-weight: 600;
  font-size: 0.85rem;
  padding: 0.05rem 0.5rem;
  border-radius: 999px;
  border: 1px solid currentColor;
  margin-right: 0.5rem;
}
.freshness--frisch     { color: #16a34a; }
.freshness--verzoegert { color: #d97706; }
.freshness--veraltet   { color: #dc2626; }
```

- [ ] **Step 2: Commit.**

```bash
git add site/src/style.css
git commit -m "feat(site): freshness badge styles"
```

---

## Task 8: Wire badge into `today.ts`

**Files:**
- Modify: `site/src/pages/today.ts`

The existing `.data-age` line currently renders:

```html
<p class="data-age">Stand: ${...} · Nächstes Update: ${...}</p>
```

Prepend the badge to it and mount the ticker.

- [ ] **Step 1: Edit imports** at top of `site/src/pages/today.ts`:

```typescript
import { freshnessState, renderFreshnessBadge, mountFreshnessTicker } from "../freshness.js";
```

- [ ] **Step 2: Update the `.data-age` template line** in `renderToday`. Replace the existing `<p class="data-age">…</p>` line with:

```typescript
    <p class="data-age">
      ${renderFreshnessBadge(freshnessState(data.generated_at))}
      Stand: ${new Date(data.generated_at).toLocaleString("de-DE")} · Nächstes Update: ${formatTime(nextUpdate(data.generated_at).toISOString())}
    </p>
  `;

  const badge = container.querySelector<HTMLElement>(".data-age .freshness");
  if (badge) mountFreshnessTicker(badge, data.generated_at);
```

(That `const badge = …` block goes after `container.innerHTML = …;`, outside the template literal.)

- [ ] **Step 3: Sanity build.**

Run: `cd site && npm run build`
Expected: passes type-check and Vite build.

- [ ] **Step 4: Commit.**

```bash
git add site/src/pages/today.ts
git commit -m "feat(site): freshness badge on Heute page"
```

---

## Task 9: Wire badge into `week.ts`, `stats.ts`, `archive-list.ts`

**Files:**
- Modify: `site/src/pages/week.ts`
- Modify: `site/src/pages/stats.ts`
- Modify: `site/src/pages/archive-list.ts`

- [ ] **Step 1: `week.ts`** — append a `.data-age` line. After the closing `</div>` of `chart-week-months`'s `chart-container` (inside the `container.innerHTML` template), insert before the closing backtick:

```typescript
    <p class="data-age">
      ${renderFreshnessBadge(freshnessState(data.generated_at))}
      Stand: ${new Date(data.generated_at).toLocaleString("de-DE")}
    </p>
```

Add the import at the top:

```typescript
import { freshnessState, renderFreshnessBadge, mountFreshnessTicker } from "../freshness.js";
```

After `renderMonthsBar(...)` at the end of `renderWeek`, add:

```typescript
  const badge = container.querySelector<HTMLElement>(".data-age .freshness");
  if (badge) mountFreshnessTicker(badge, data.generated_at);
```

- [ ] **Step 2: `stats.ts`** — prepend the badge to the existing `.data-age` line.

Add the import:

```typescript
import { freshnessState, renderFreshnessBadge, mountFreshnessTicker } from "../freshness.js";
```

Replace the existing `.data-age` line:

```typescript
    <p class="data-age">
      ${renderFreshnessBadge(freshnessState(data.generated_at))}
      Zeitraum: letzte ${data.window_days} Tage · ${agg.total} Züge erfasst · Stand: ${new Date(data.generated_at).toLocaleString("de-DE")}
    </p>
```

At the bottom of `renderStats` (after the last `renderAvgDelayLine` call):

```typescript
  const badge = container.querySelector<HTMLElement>(".data-age .freshness");
  if (badge) mountFreshnessTicker(badge, data.generated_at);
```

- [ ] **Step 3: `archive-list.ts`** — uses `idx.generated_at`.

Add import:

```typescript
import { freshnessState, renderFreshnessBadge, mountFreshnessTicker } from "../freshness.js";
```

Append inside the `months-list` `<section>` (before its closing `</section>`):

```typescript
      <p class="data-age">
        ${renderFreshnessBadge(freshnessState(idx.generated_at))}
        Stand: ${new Date(idx.generated_at).toLocaleString("de-DE")}
      </p>
```

After `renderMonthsBar(...)`:

```typescript
  const badge = container.querySelector<HTMLElement>(".data-age .freshness");
  if (badge) mountFreshnessTicker(badge, idx.generated_at);
```

Confirm that `loadIndex()`'s return type exposes `generated_at: string`. If not, widen the type in `site/src/archive.ts`. (Check now: `grep generated_at site/src/archive.ts`.)

- [ ] **Step 4: Build + lint.**

Run: `cd site && npm run build && npm run lint`
Expected: pass.

- [ ] **Step 5: Commit.**

```bash
git add site/src/pages/week.ts site/src/pages/stats.ts site/src/pages/archive-list.ts site/src/archive.ts
git commit -m "feat(site): freshness badge on Woche, Statistik, Archiv pages"
```

(Drop `site/src/archive.ts` from the `git add` if no change was needed there.)

---

## Task 10: Build-site workflow — two-ref checkout, trigger on `data`

**Files:**
- Modify: `.github/workflows/build-site.yml`

- [ ] **Step 1: Rewrite the workflow** to check out `main` and `data`.

Replace `.github/workflows/build-site.yml` with:

```yaml
name: Build and deploy site

on:
  push:
    branches: [main, data]
  schedule:
    - cron: "0 * * * *"  # hourly fallback rebuild
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout main (code + site)
        uses: actions/checkout@v4
        with:
          ref: main

      - name: Checkout data branch
        uses: actions/checkout@v4
        with:
          ref: data
          path: data-branch

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: site/package-lock.json

      - name: Install dependencies
        run: npm ci
        working-directory: site

      - name: Build site
        run: npm run build
        working-directory: site
        env:
          GITHUB_PAGES: "1"

      - name: Stage data into dist
        run: |
          mkdir -p site/dist/data/archive
          cp data-branch/latest.json site/dist/data/latest.json || true
          cp data-branch/archive/*.json site/dist/data/archive/ 2>/dev/null || true

      - uses: actions/upload-pages-artifact@v3
        with:
          path: site/dist

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: YAML-lint** (any reasonable YAML linter / `yq`).

Run: `cd .github/workflows && python -c "import yaml; yaml.safe_load(open('build-site.yml'))"`
Expected: no exception.

- [ ] **Step 3: Commit.**

```bash
git add .github/workflows/build-site.yml
git commit -m "ci(pages): check out main + data branches, drop data/** path filter

Workflow now assembles dist from two refs: site code from main, JSON
data from the orphan data branch."
```

---

## Task 11: Docker Compose — `s7bb-data-init` service and `:ro` mount

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add the init service and named volume**, and wire `s7bb-site-dev` to depend on it.

Replace the relevant section of `docker-compose.yml`. The full target file:

```yaml
services:
  s7bb-fetcher:
    build:
      context: fetcher
      dockerfile: Dockerfile
    restart: unless-stopped
    env_file: .env
    user: "0:0"
    volumes:
      - ./data:/data
      - .:/repo
    environment:
      DATA_DIR: /data
      REPO_PATH: /repo

  s7bb-dev:
    image: python:3.12-slim
    command: python3 -m http.server 8080 --directory /data
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data:ro
    profiles:
      - dev

  s7bb-data-init:
    image: alpine/git:latest
    profiles: [dev]
    environment:
      DATA_BRANCH_URL: https://github.com/s7bb/s7bb.github.io.git
    entrypoint: ["sh", "-c"]
    command:
      - |
        set -e
        if [ ! -d /data-checkout/.git ]; then
          git clone --branch data --single-branch --depth=1 \
            "$$DATA_BRANCH_URL" /data-checkout
        else
          git -C /data-checkout fetch --depth=1 origin data
          git -C /data-checkout reset --hard FETCH_HEAD
        fi
    volumes:
      - s7bb-data-checkout:/data-checkout

  s7bb-site-dev:
    image: node:20-alpine
    working_dir: /repo/site
    command: ["sh", "/repo/site/dev-entrypoint.sh"]
    ports:
      - "5173:5173"
    depends_on:
      s7bb-data-init:
        condition: service_completed_successfully
    volumes:
      - .:/repo
      - s7bb-data-checkout:/repo/data:ro
      - /repo/site/data
      - s7bb-site-node-modules:/repo/site/node_modules
    profiles:
      - dev

volumes:
  s7bb-site-node-modules:
  s7bb-data-checkout:
```

Note the `$$DATA_BRANCH_URL` (double dollar) — compose interpolation escape so the shell sees `$DATA_BRANCH_URL` and reads the env var.

- [ ] **Step 2: Compose-config sanity check.**

Run: `docker compose --profile dev config`
Expected: no error, both services rendered.

- [ ] **Step 3: Commit.**

```bash
git add docker-compose.yml
git commit -m "feat(dev): s7bb-data-init clones data branch into shared volume

s7bb-site-dev now depends on it and mounts the volume at /repo/data:ro,
so the dev entrypoint reads the data-branch tip without main needing
to track data/ on disk."
```

---

## Task 12: `.gitignore` — `/data/` and `/.data-checkout/`

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Append** to `.gitignore`:

```gitignore
# Local data working dir (untracked on main; data branch is the source of truth)
/data/

# Optional host-side worktree of the data branch for offline inspection
/.data-checkout/
```

Note: the existing `data/s7bb.db*` lines become redundant but leave them in place — they're a defence-in-depth in case a developer ever un-ignores `/data/` for some reason.

- [ ] **Step 2: Commit.**

```bash
git add .gitignore
git commit -m "chore: ignore /data/ on main and /.data-checkout/ worktree"
```

---

## Task 13: Documentation — README, CLAUDE.md, CHANGELOG

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update `README.md`.**

In `README.md` §VM Setup, replace the clone step with:

```markdown
1. Clone the **data branch** over HTTPS (single-branch, shallow):

       git clone --branch data --single-branch --depth=1 \
         https://github.com/<owner>/<repo>.git /repo

   The container expects `REPO_PATH=/repo`. The DB and generated JSON
   live under `/data` (bind-mount, untracked) — only `latest.json` and
   `archive/*.json` are staged into `/repo` for push.
```

Update §GitHub Pages Setup: note that the build workflow checks out both `main` and `data` and assembles them into the deployed artifact.

Update §Local development: primary entry point is `docker compose --profile dev up`. To refresh the data-branch tip without restarting the site container:

```
docker compose --profile dev run --rm s7bb-data-init
```

Document the alternative host-`git worktree` approach for editor inspection:

```
git worktree add ./.data-checkout data
```

…and that `.data-checkout/` is gitignored.

- [ ] **Step 2: Update `CLAUDE.md`.**

Replace the architecture diagram and the §Key decisions block:

```markdown
## Architecture

main branch (humans + Dependabot):  code, site, fetcher, workflows, docs.
data branch (VM bot, orphan):       latest.json, archive/*.json, archive/index.json (flat layout, at root).

DB Timetables API (XML)
  → Python fetcher → SQLite (/data/s7bb.db, VM-only)
                       ↓
                     /data/latest.json  +  /data/archive/*.json   (exporter)
                       ↓ (copy)
                     /repo/latest.json  +  /repo/archive/*.json   (staging in data-branch clone)
                       ↓ (hourly push)
                     GitHub: data branch updated
                       ↓
                     Actions build-site.yml checks out main + data,
                     assembles site/dist, deploys to gh-pages.
```

In §Key decisions (locked), update:

- VM commits to `data` (orphan branch, no history shared with `main`), restricted by ruleset.
- Path-restricted ruleset on `main` removed; `main` is normal protected branch.
- PAT scoped to `Contents: read/write`, restricted to `data` branch by ruleset.

- [ ] **Step 3: Update `CHANGELOG.md`.**

Under `## [Unreleased]` add:

```markdown
### Added

- Decouple VM data pushes from `main` via an orphan `data` branch. The VM is now the sole writer of `data`; pushes to `data` no longer compete with Dependabot/PR merges on `main` for fast-forward. Resolves the silent non-fast-forward push-rejection class that left the site serving stale data after `main` activity.
- Freshness badge on the today, week, statistics, and archive pages: a coloured "aktuell / verzögert / veraltet" pill rendered next to the "Stand:" timestamp, recomputed every 60 s so a long-open tab transitions states without reload.

### Changed

- Exporter SQL: `ORDER BY scheduled_time, train_id` (deterministic tie-break) — improves git delta compression on the hourly archive rewrite.
- Build workflow checks out both `main` and `data`; data is staged into `dist` from `data-branch/`.
- `docker-compose.yml`: new `s7bb-data-init` service (profile `dev`) clones the `data` branch into a named volume; `s7bb-site-dev` mounts it read-only at `/repo/data`.
```

- [ ] **Step 4: Commit.**

```bash
git add README.md CLAUDE.md CHANGELOG.md
git commit -m "docs: orphan data branch — README, CLAUDE.md, CHANGELOG"
```

---

## Task 14: Remove `data/` from `main`'s tracked tree

**Files:**
- Delete: `data/latest.json`, `data/archive/*.json`

⚠ This is the **final code commit on the PR**. Until the orphan `data` branch exists on GitHub and the workflow change from Task 10 is merged, removing `data/` from `main` will leave the site without data. The migration plan handles this with the "one-time setup on GitHub" step that happens **before** merging the PR — see Task 16.

- [ ] **Step 1: Verify the orphan branch and ruleset already exist on GitHub** (see Task 16 — done by maintainer first, before this commit lands on `main`).

- [ ] **Step 2: Remove tracked files.**

```bash
git rm -r data/
```

(Local `data/` working tree files remain on disk because `/data/` is gitignored — the `git rm` only removes from the index.)

- [ ] **Step 3: Verify gitignore catches re-creation.**

Run: `git status` — `data/` should not appear as untracked.
Expected: clean.

- [ ] **Step 4: Sanity-run the test suites** to confirm nothing in tests reads from `data/` on disk:

```bash
cd fetcher && uv run pytest -q
cd ../site && npm run build && npx vitest run
```

Expected: pass.

- [ ] **Step 5: Commit.**

```bash
git commit -m "chore: remove data/ from main's tracked tree

The orphan data branch is now the source of truth for latest.json and
archive/*.json. main no longer carries them. Local working trees keep
producing data/ but it is gitignored."
```

---

## Task 15: Open and self-review the PR

- [ ] **Step 1:** Push the branch and open a PR titled:

```
feat: orphan data branch — decouple VM data pushes from main + freshness badge
```

Body summarises the spec at one-paragraph fidelity and links `docs/superpowers/specs/2026-05-14-orphan-data-branch-design.md`.

- [ ] **Step 2:** Verify CI: only `ci.yml` runs (lint+test). `build-site.yml` is **not** expected to run on the PR (it triggers on push to `main`/`data`).

- [ ] **Step 3:** Self-review the diff — confirm no `data/` paths leaked into pusher/service tests, confirm freshness CSS does not collide with existing `.badge` rules.

---

## Task 16: One-time GitHub setup (maintainer, manual — NOT a code task)

Performed **before** merging the PR from Tasks 1-15. Document the steps in the PR body.

- [ ] **Step 1: Create the orphan `data` branch locally** from a snapshot of the current `data/` directory contents (flat layout).

In a separate clone:

```bash
# From the current main tip, materialize the data/ contents at the repo root:
git checkout main
mkdir /tmp/data-snapshot
cp -a data/. /tmp/data-snapshot/

git checkout --orphan data
git rm -rf .
cp -a /tmp/data-snapshot/. .
git add .
git -c user.email=s7bb-bot@localhost -c user.name=s7bb-bot \
    commit -m "chore(data): seed orphan data branch from main@<sha>"
git push origin data
```

- [ ] **Step 2: GitHub → Settings → Rules → Rulesets:**

  - **Remove** the existing `main` path-scoped allow rule for `data/**` pushes (bot PAT can no longer push to `main`).
  - **Add** a new ruleset on `data`:
    - Allowed actor: s7bb-bot PAT identity.
    - Block: deletions, force-pushes.
    - No path restriction (branch contains only data by construction).

- [ ] **Step 3: Rotate the fine-grained PAT.**

  - New PAT scope: `Contents: read/write` on this single repository.
  - Ruleset scopes it to `data`.
  - Update the value in `.env` on the VM after cutover (Task 17).

- [ ] **Step 4: Merge** the PR from Task 15.

---

## Task 17: VM cutover (maintainer, manual — NOT a code task)

- [ ] **Step 1:** SSH to VM, `docker compose down s7bb-fetcher`.

- [ ] **Step 2:** Replace `/repo` clone:

```bash
mv /path/to/repo /path/to/repo.old
git clone --branch data --single-branch --depth=1 \
  https://github.com/<owner>/<repo>.git /path/to/repo
```

(Adjust to the actual host path used by the bind mount.)

- [ ] **Step 3:** Update `.env` with the rotated `GITHUB_PAT`.

- [ ] **Step 4:** `docker compose up -d s7bb-fetcher`.

- [ ] **Step 5: Watch the first export cycle** (`docker compose logs -f s7bb-fetcher`). Expect:

  - `startup_sync: action=…` against `origin/data`.
  - First hourly `export_job` runs.
  - `push_data: pushed to origin/data (N file(s))`.
  - `build-site.yml` triggered on the data-branch push; site deploys.

- [ ] **Step 6: Verify** `https://<gh-pages-url>/data/latest.json` shows fresh `generated_at` within the last 75 minutes.

---

## Task 18: Cut release per CLAUDE.md procedure

This PR contains `feat:` commits → MINOR bump.

- [ ] **Step 1:** Determine the new version. Current is `0.4.4` → next is `0.5.0`.

- [ ] **Step 2:** Bump `fetcher/pyproject.toml` `version = "0.5.0"` and re-sync the lock:

```bash
cd fetcher && uv sync --no-dev
```

- [ ] **Step 3:** In `CHANGELOG.md`, rename `## [Unreleased]` to `## [0.5.0] - 2026-05-14` (or current date) and add a fresh empty `## [Unreleased]` above it.

- [ ] **Step 4:** Commit:

```bash
git add fetcher/pyproject.toml fetcher/uv.lock CHANGELOG.md
git commit -m "chore(release): 0.5.0"
git tag -a v0.5.0 -m "v0.5.0"
git push origin main v0.5.0
```

- [ ] **Step 5:** Create the GitHub Release at <https://github.com/s7bb/s7bb.github.io/releases>:

```bash
gh release create v0.5.0 --title "v0.5.0" --latest \
  --notes-file <(awk '/^## \[0.5.0\]/,/^## \[/' CHANGELOG.md | sed '$d')
```

---

## Self-review (done; included for the executor's reference)

**Spec coverage:**
- §1 Repository layout → Tasks 12, 14.
- §2 VM checkout → Tasks 17 (manual) + 11 (compose changes mirror this for dev).
- §3 Pusher changes → Tasks 2, 3.
- §4 Startup sync → Task 5.
- §5 GitHub Actions workflow → Task 10.
- §6 Branch protection/rulesets → Task 16.
- §7 PAT scope → Task 16 Step 3.
- §8 Local development (init container) → Task 11.
- §Archive placement / JSON determinism → Task 1.
- §Freshness badge → Tasks 6, 7, 8, 9.
- §Migration plan / release → Tasks 14, 16, 17, 18.

**Type consistency:**
- `freshnessState`, `renderFreshnessBadge`, `mountFreshnessTicker` — names used identically in `freshness.ts`, `freshness.test.ts`, and all four page wirings.
- `_PUSH_REFSPEC = "HEAD:refs/heads/data"` — used in `pusher.py` only; tests assert `args[1] == "HEAD:refs/heads/data"` (matching).
- `_stage_into_repo(data_dir, repo_path)` — service.py only.

**Placeholder scan:** none — every step has the actual code, command, or text.
