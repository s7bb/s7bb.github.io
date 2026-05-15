# Two-Repository Data Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the VM's hourly schedule JSON out of the code repository into a dedicated, single-writer data repository (`s7bb/s7bb-data`), so VM pushes never collide with Dependabot/PR merges and the bot PAT is physically scoped away from code.

**Architecture:** A new GitHub repo `s7bb/s7bb-data` holds a flat tree (`latest.json`, `archive/*.json`, `archive/index.json` at the root) on its `main` branch. The VM clones *that* repo at `REPO_PATH=/repo`; the exporter still writes to `/data` (host bind-mount, untracked); a new service step copies `/data` → `/repo` before the existing push. The push refspec stays `HEAD:refs/heads/main` (now the data repo's main — single writer, zero contention). GitHub Actions builds the site from the code repo and assembles JSON by also checking out `s7bb/s7bb-data`. The code repo stops tracking `data/`.

**Tech Stack:** Python 3.11+ (fetcher, GitPython, APScheduler), GitHub Actions, Docker Compose.

**Design rationale (this plan supersedes the orphan-branch design):**
- The original spec `docs/superpowers/specs/2026-05-14-orphan-data-branch-design.md` proposed an *orphan branch* in the same repo. A separate repo is chosen instead because: (a) the bot PAT is scoped to a different repository and literally cannot touch code — strongest isolation, no same-repo path ruleset; (b) no `git checkout --orphan` seeding dance; (c) the build workflow stays on the code repo where its workflow file lives — an orphan branch would *not* trigger `build-site.yml` on push (the workflow file would not exist on that branch), so the orphan design's "instant deploy on data push" advantage was illusory anyway.
- The defensive `fetch + merge --ff-only` step from the orphan plan is **dropped** (YAGNI): the data repo has exactly one writer (the VM), so non-fast-forward divergence cannot occur. If a second writer is ever added, revisit.
- `push_data` keeps returning the `PushOutcome` enum and the refspec stays `HEAD:refs/heads/main`; only the staged paths go flat. This minimises churn and avoids breaking `startup_sync` / `service` callers.
- The freshness badge feature is split into its own plan: `docs/superpowers/plans/2026-05-15-freshness-badge.md`. It is independent of this change.
- Follow-up (not in this plan): the committed orphan spec should be superseded by a `docs:` PR. Flag to the maintainer; out of scope here.

---

## File structure

**Modified (fetcher):**
- `fetcher/src/s7bb_fetcher/exporter.py` — `ORDER BY scheduled_time, train_id` in both queries (deterministic, smaller git deltas).
- `fetcher/src/s7bb_fetcher/pusher.py` — flat staging paths (`latest.json`, `archive/*.json`); docstring. Refspec and `PushOutcome` unchanged.
- `fetcher/src/s7bb_fetcher/service.py` — new `_stage_into_repo` helper + call before push; `import shutil`.
- `fetcher/src/s7bb_fetcher/startup_sync.py` — raw URL drops the `/data` path segment; docstring wording.
- `fetcher/tests/test_exporter.py` — tie-break ordering tests.
- `fetcher/tests/test_pusher.py` — fixtures + archive tests rebuilt for flat layout (refspec assertion unchanged).
- `fetcher/tests/test_service.py` — staging-step test.
- `fetcher/tests/test_startup_sync.py` — raw URL assertion updated + new template test.

**Modified (infra):**
- `.github/workflows/build-site.yml` — second checkout of `s7bb/s7bb-data`; drop `data/**` path filter; shift fallback cron to `:10`.
- `docker-compose.yml` — `s7bb-data-init` service (profile `dev`) + `s7bb-data-checkout` named volume; `s7bb-site-dev` depends on it and mounts it at `/repo/data:ro`.
- `.gitignore` — add `/data/` and `/.data-checkout/`.

**Modified (docs):**
- `README.md` — §VM Setup, §GitHub Pages Setup, §Local development.
- `CLAUDE.md` — architecture diagram + key decisions.
- `CHANGELOG.md` — `[Unreleased]` entries.

**Removed (final code task):**
- `data/latest.json`, `data/archive/*.json` — `git rm -r data/`.

**Maintainer-manual (documented in PR body, not code):**
- Create + seed `s7bb/s7bb-data`; rotate PAT; VM cutover.

---

## Task 1: Stable export ordering (tie-break on `train_id`)

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/exporter.py` (two `ORDER BY scheduled_time` clauses)
- Modify: `fetcher/tests/test_exporter.py`

- [ ] **Step 1: Inspect existing test helpers.**

Run: `cd fetcher && grep -n "_make_arrival\|^import\|^from" tests/test_exporter.py | head -30`
Confirm a `_make_arrival(...)` helper exists and note its signature (expected: `_make_arrival(train_id, scheduled_time_iso, direction_bucket)`), and that `json`, `datetime`, `UTC` are importable in the file. The test snippet below imports what it needs locally so it is robust regardless.

- [ ] **Step 2: Write failing tests.** Append to `fetcher/tests/test_exporter.py`:

```python
def test_export_latest_orders_ties_by_train_id(tmp_path):
    import json
    from datetime import UTC, datetime

    from s7bb_fetcher.exporter import export_latest
    from s7bb_fetcher.storage import open_db, upsert_records

    conn = open_db(tmp_path / "test.db")
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    upsert_records(conn, [
        _make_arrival("m_zzz", f"{today}T10:00:00+00:00", "muenchen"),
        _make_arrival("m_aaa", f"{today}T10:00:00+00:00", "muenchen"),
    ])
    out = tmp_path / "latest.json"
    export_latest(conn, out)
    arrivals = json.loads(out.read_text())["arrivals"]
    same = [a for a in arrivals if a["scheduled_time"].startswith(f"{today}T10:00")]
    assert [a["train_id"] for a in same] == ["m_aaa", "m_zzz"]


def test_export_monthly_archive_orders_ties_by_train_id(tmp_path):
    import json

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
    same = [a for a in arrivals if a["scheduled_time"].startswith("2026-04-15T10:00")]
    assert [a["train_id"] for a in same] == ["a1", "z2"]
```

If `_make_arrival`'s real signature differs from `(train_id, scheduled_time_iso, direction_bucket)`, adjust these two calls to match it; do not change the assertions.

- [ ] **Step 3: Run, verify failure.**

Run: `cd fetcher && uv run pytest tests/test_exporter.py -v -k ties`
Expected: FAIL — ordering is implementation-defined without an explicit tie-break.

- [ ] **Step 4: Implement.** In `fetcher/src/s7bb_fetcher/exporter.py`, change **both** occurrences of:

```sql
ORDER BY scheduled_time
```

to:

```sql
ORDER BY scheduled_time, train_id
```

(One is in the `WHERE scheduled_time >= ?` query, the other in the `WHERE scheduled_time >= ? AND scheduled_time < ?` query.)

- [ ] **Step 5: Run, verify pass.**

Run: `cd fetcher && uv run pytest tests/test_exporter.py -v`
Expected: all pass.

- [ ] **Step 6: Commit.**

```bash
git add fetcher/src/s7bb_fetcher/exporter.py fetcher/tests/test_exporter.py
git commit -m "refactor(exporter): tie-break ORDER BY scheduled_time on train_id

Deterministic row order keeps the hourly archive rewrite byte-stable for
rows sharing a scheduled_time, shrinking git deltas on the data repo."
```

---

## Task 2: Pusher — flat staging layout (`latest.json` + `archive/*.json` at root)

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/pusher.py`
- Modify: `fetcher/tests/test_pusher.py`

The data repo has a flat tree. The push refspec (`HEAD:refs/heads/main`) and `PushOutcome` enum are **unchanged** — only the staged working-tree paths drop the `data/` prefix.

- [ ] **Step 1: Rewrite the `working_repo` fixture** for a flat layout. In `fetcher/tests/test_pusher.py`, replace the fixture body (lines 22-45) with:

```python
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
```

(The origin URL stays `owner/s7bb` so the slug-parsing tests are untouched — they exercise URL parsing, not the repo name.)

- [ ] **Step 2: Update `dirty_latest`** (lines 48-52) to the flat path:

```python
@pytest.fixture
def dirty_latest(working_repo: git.Repo) -> git.Repo:
    target = Path(working_repo.working_tree_dir) / "latest.json"
    target.write_text('{"v":1}\n')
    return working_repo
```

- [ ] **Step 3: Update the archive + is-ahead tests** to flat paths. In `fetcher/tests/test_pusher.py`:

In `test_push_data_stages_archive_and_latest`, replace its body's archive setup and assertions:

```python
    arch_dir = work / "archive"
    arch_dir.mkdir(parents=True, exist_ok=True)
    (arch_dir / "2026-04.json").write_text('{"period":"2026-04"}\n')
    (arch_dir / "index.json").write_text('{"months":[]}\n')
```

and:

```python
    assert "latest.json" in files
    assert "archive/2026-04.json" in files
    assert "archive/index.json" in files
```

In `test_push_data_single_commit_for_combined_changes`:

```python
    arch_dir = work / "archive"
    arch_dir.mkdir(parents=True, exist_ok=True)
    (arch_dir / "2026-04.json").write_text('{"period":"2026-04"}\n')
```

In `test_is_ahead_of_origin_true_when_local_has_extra_commits`, replace the three `data/latest.json` references:

```python
    target = Path(working_repo.working_tree_dir) / "latest.json"
    target.write_text('{"v":2}\n')
    working_repo.index.add(["latest.json"])
```

In `test_push_data_pushes_existing_unpushed_commits`, same substitution:

```python
    target = Path(working_repo.working_tree_dir) / "latest.json"
    target.write_text('{"v":99}\n')
    working_repo.index.add(["latest.json"])
```

Leave the `assert captured["args"][1] == "HEAD:refs/heads/main"` line **unchanged**.

- [ ] **Step 4: Run, verify failure.**

Run: `cd fetcher && uv run pytest tests/test_pusher.py -v`
Expected: failures in the archive/staging tests (production pusher still looks under `data/`).

- [ ] **Step 5: Implement.** In `fetcher/src/s7bb_fetcher/pusher.py`:

Change the module docstring (line 1):

```python
"""Push latest.json + archive/*.json to the s7bb-data repo via GitHub PAT (HTTPS)."""
```

Change the path constants (lines 30-31):

```python
_LATEST_JSON = "latest.json"
_ARCHIVE_GLOB = "archive/*.json"
```

In `push_data`, change the archive discovery line (currently `archive_files = sorted((repo_path / "data" / "archive").glob("*.json"))`):

```python
    archive_files = sorted((repo_path / "archive").glob("*.json"))
```

(`_LATEST_JSON` is already used via `(repo_path / _LATEST_JSON).exists()`; no other change. Refspec `_PUSH_REFSPEC = "HEAD:refs/heads/main"` stays.)

- [ ] **Step 6: Run, verify pass.**

Run: `cd fetcher && uv run pytest tests/test_pusher.py -v`
Expected: all pass.

- [ ] **Step 7: Commit.**

```bash
git add fetcher/src/s7bb_fetcher/pusher.py fetcher/tests/test_pusher.py
git commit -m "feat(pusher): flat staging layout for the s7bb-data repo

Staged working-tree paths drop the data/ prefix (latest.json and
archive/*.json now live at the repo root). Refspec and PushOutcome
unchanged — the data repo is single-writer, so HEAD:refs/heads/main
can never be non-fast-forward."
```

---

## Task 3: Service — copy `/data` → `/repo` before push

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/service.py`
- Modify: `fetcher/tests/test_service.py`

The exporter writes JSON to `DATA_DIR` (`/data`, host bind-mount, untracked). The pusher reads from `REPO_PATH` (`/repo`, the data-repo clone). These were the same path before; now they diverge. A new step mirrors exporter output into the data-repo working tree before the existing `_run_push_step()`.

- [ ] **Step 1: Inspect the current push wiring.**

Run: `cd fetcher && grep -n "_run_push_step\|_safe(\"archive_index\|_export_job\|^import\|^from" src/s7bb_fetcher/service.py`
Confirm `_export_job` ends with `_safe("archive_index", ...)` then `_run_push_step()`, and that `shutil` is not yet imported.

- [ ] **Step 2: Write failing test.** Append to `fetcher/tests/test_service.py`:

```python
def test_export_job_stages_data_into_repo_before_push(tmp_path, monkeypatch):
    """After the exporter writes /data, _export_job mirrors it into /repo
    (flat) and then runs the push step."""
    from s7bb_fetcher import exporter, service, storage

    data_dir = tmp_path / "data"
    repo_path = tmp_path / "repo"
    (data_dir / "archive").mkdir(parents=True)
    repo_path.mkdir()

    monkeypatch.setattr(service, "DATA_DIR", data_dir)
    monkeypatch.setattr(service, "REPO_PATH", repo_path)
    monkeypatch.setattr(service, "DB_PATH", data_dir / "s7bb.db")
    monkeypatch.setattr(service, "OUT_PATH", data_dir / "latest.json")
    monkeypatch.setattr(service, "ARCHIVE_DIR", data_dir / "archive")
    monkeypatch.setattr(service, "INDEX_PATH", data_dir / "archive" / "index.json")

    monkeypatch.setattr(storage, "open_db", lambda _p: object())

    def fake_latest(_conn, out_path):
        out_path.write_text('{"v":1}')

    def fake_monthly(_conn, _y, _m, out_path, **_kw):
        out_path.write_text('{"period":"x"}')

    def fake_index(_archive_dir, out_path):
        out_path.write_text('{"months":[]}')

    monkeypatch.setattr(exporter, "export_latest", fake_latest)
    monkeypatch.setattr(exporter, "export_monthly_archive", fake_monthly)
    monkeypatch.setattr(exporter, "export_archive_index", fake_index)

    pushed = []
    monkeypatch.setattr(service, "_run_push_step", lambda: pushed.append(True))

    service._export_job()

    assert (repo_path / "latest.json").read_text() == '{"v":1}'
    assert (repo_path / "archive" / "index.json").read_text() == '{"months":[]}'
    assert pushed == [True]
```

- [ ] **Step 3: Run, verify failure.**

Run: `cd fetcher && uv run pytest tests/test_service.py::test_export_job_stages_data_into_repo_before_push -v`
Expected: FAIL — staging step does not exist; `repo_path/latest.json` absent.

- [ ] **Step 4: Implement.** In `fetcher/src/s7bb_fetcher/service.py`:

Add `import shutil` to the import block (with the other stdlib imports near the top).

Add this helper after `_safe(...)` (around line 41):

```python
def _stage_into_repo(data_dir: Path, repo_path: Path) -> None:
    """Mirror exporter outputs from data_dir into the data-repo working tree.

    Copies latest.json and archive/*.json to repo_path's root (flat layout).
    Idempotent; overwrites destination files.
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

In `_export_job`, replace the final `_run_push_step()` call with:

```python
    _safe("stage", _stage_into_repo, DATA_DIR, REPO_PATH)
    _run_push_step()
```

- [ ] **Step 5: Run, verify pass.**

Run: `cd fetcher && uv run pytest tests/test_service.py -v`
Expected: all pass.

- [ ] **Step 6: Commit.**

```bash
git add fetcher/src/s7bb_fetcher/service.py fetcher/tests/test_service.py
git commit -m "feat(service): stage /data into /repo before push

Decouples 'produce JSON in /data' (untracked bind-mount) from 'stage for
git push in /repo' (the s7bb-data clone). Flat layout at the repo root."
```

---

## Task 4: Startup-sync — raw URL targets the data repo (flat path)

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/startup_sync.py`
- Modify: `fetcher/tests/test_startup_sync.py`

`slug` is resolved from `REPO_PATH`'s origin, which on the VM is the data repo (`s7bb/s7bb-data`). Only the path segment changes: `/main/data/latest.json` → `/main/latest.json`.

- [ ] **Step 1: Write failing tests.** In `fetcher/tests/test_startup_sync.py`, update the URL assertion in `test_fetch_remote_returns_body_and_timestamp_on_200` (the `get.assert_called_once_with(...)` block):

```python
    get.assert_called_once_with(
        "https://raw.githubusercontent.com/owner/repo/main/latest.json",
        timeout=5.0,
    )
```

Then append a new test:

```python
def test_raw_url_template_targets_data_repo_root():
    from s7bb_fetcher.startup_sync import _RAW_URL_TMPL

    assert "/main/latest.json" in _RAW_URL_TMPL
    assert "/data/" not in _RAW_URL_TMPL
    assert (
        _RAW_URL_TMPL.format(slug="s7bb/s7bb-data")
        == "https://raw.githubusercontent.com/s7bb/s7bb-data/main/latest.json"
    )
```

- [ ] **Step 2: Run, verify failure.**

Run: `cd fetcher && uv run pytest tests/test_startup_sync.py -v -k "raw_url or returns_body_and_timestamp"`
Expected: FAIL — template still has the `/data/` segment.

- [ ] **Step 3: Implement.** In `fetcher/src/s7bb_fetcher/startup_sync.py`, replace `_RAW_URL_TMPL` (line 162):

```python
_RAW_URL_TMPL = "https://raw.githubusercontent.com/{slug}/main/latest.json"
```

Update the module docstring (lines 1-11) to:

```python
"""Reconcile local latest.json with the s7bb-data repo at service startup.

On startup, before the scheduler begins, this module compares the local
``latest.json`` against the copy published on the data repository's
``main`` branch and either pushes the local file (if local is newer),
overwrites local with the remote bytes (if remote is newer), or does
nothing (if they are in sync within a small clock-skew tolerance).

All failure modes raise. The caller treats any raise as a hard startup
failure.
"""
```

Update the `_fetch_remote` docstring (line 166): replace `data/latest.json from origin/main` with `latest.json from the data repo's main branch`.

Update the log line in `startup_sync` (line 55):

```python
    logger.info("startup_sync: checking drift against s7bb-data main (%s)", slug)
```

- [ ] **Step 4: Run, verify pass.**

Run: `cd fetcher && uv run pytest tests/test_startup_sync.py -v`
Expected: all pass. If any other test hard-codes the old URL string, update it inline to the new template.

- [ ] **Step 5: Commit.**

```bash
git add fetcher/src/s7bb_fetcher/startup_sync.py fetcher/tests/test_startup_sync.py
git commit -m "feat(startup-sync): reconcile against s7bb-data repo root URL"
```

---

## Task 5: Build workflow — second checkout of the data repo

**Files:**
- Modify: `.github/workflows/build-site.yml`

The site code lives on the code repo's `main`; the JSON lives on `s7bb/s7bb-data` `main`. The build checks out both. The `data/**` push path filter is removed (no longer in this repo). The fallback cron is shifted to `:10` so it runs *after* the VM's `:00` hourly export+push, picking up fresh data within ~10 min instead of up to ~1 h.

- [ ] **Step 1: Replace `.github/workflows/build-site.yml`** with:

```yaml
name: Build and deploy site

on:
  push:
    branches: [main]
    paths:
      - "site/**"
      - ".github/workflows/build-site.yml"
  schedule:
    - cron: "10 * * * *"  # after the VM's :00 hourly data push
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
      - name: Checkout code + site
        uses: actions/checkout@v4

      - name: Checkout data repo
        uses: actions/checkout@v4
        with:
          repository: s7bb/s7bb-data
          ref: main
          path: data-src

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
          cp data-src/latest.json site/dist/data/latest.json || true
          cp data-src/archive/*.json site/dist/data/archive/ 2>/dev/null || true

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

Note: `s7bb/s7bb-data` must be a **public** repo for the token-free second checkout (it carries only public schedule JSON; the org Pages site is public anyway). If it is ever made private, add `token:` / a deploy key to the second `actions/checkout` step.

- [ ] **Step 2: YAML sanity check.**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/build-site.yml'))"`
Expected: no exception.

- [ ] **Step 3: Commit.**

```bash
git add .github/workflows/build-site.yml
git commit -m "ci(pages): assemble site from code repo + s7bb-data checkout

Drops the data/** path filter (no longer tracked here) and shifts the
fallback rebuild cron to :10 so it lands after the VM's hourly push."
```

---

## Task 6: Docker Compose — `s7bb-data-init` service + read-only mount

**Files:**
- Modify: `docker-compose.yml`

`s7bb-site-dev`'s entrypoint reads `/repo/data/latest.json`. With `data/` no longer tracked, a dev-only init container clones the data repo into a named volume mounted read-only at `/repo/data`.

- [ ] **Step 1: Replace `docker-compose.yml`** with:

```yaml
services:
  s7bb-fetcher:
    build:
      context: fetcher
      dockerfile: Dockerfile
    restart: unless-stopped
    env_file: .env
    # Run as container UID 0. In rootless nerdctl this maps to the host
    # invoking user, so bind mounts (data/, repo) preserve ownership.
    # Setting UID=1000 here would map to a sub-UID and break write access.
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
      DATA_REPO_URL: https://github.com/s7bb/s7bb-data.git
    entrypoint: ["sh", "-c"]
    command:
      - |
        set -e
        if [ ! -d /data-checkout/.git ]; then
          git clone --branch main --single-branch --depth=1 \
            "$$DATA_REPO_URL" /data-checkout
        else
          git -C /data-checkout fetch --depth=1 origin main
          git -C /data-checkout reset --hard FETCH_HEAD
        fi
    volumes:
      - s7bb-data-checkout:/data-checkout

  s7bb-site-dev:
    image: node:20-alpine
    working_dir: /repo/site
    # Entrypoint derives VITE_DEV_NOW from data/latest.json's generated_at so
    # the today page treats the bundled data as "now" (it's filtered to the
    # viewer's current Europe/Berlin date in production).
    command: ["sh", "/repo/site/dev-entrypoint.sh"]
    ports:
      - "5173:5173"
    depends_on:
      s7bb-data-init:
        condition: service_completed_successfully
    volumes:
      - .:/repo
      # Data-repo tip, read-only, at the path dev-entrypoint.sh expects.
      - s7bb-data-checkout:/repo/data:ro
      # Anonymous volume overlays the bind mount so the entrypoint can
      # write a transformed latest.json into /repo/site/data without
      # leaking back into the host's site/ tree. Vite serves it under
      # /data/ (which is what fetch("../data/latest.json") resolves to).
      - /repo/site/data
      - s7bb-site-node-modules:/repo/site/node_modules
    profiles:
      - dev

volumes:
  s7bb-site-node-modules:
  s7bb-data-checkout:
```

Note the `$$DATA_REPO_URL` (double dollar) — Compose interpolation escape so the shell sees `$DATA_REPO_URL`.

- [ ] **Step 2: Compose-config sanity check.**

Run: `docker compose --profile dev config >/dev/null && echo OK`
Expected: `OK` (no error; `s7bb-data-init` and `s7bb-site-dev` rendered).

- [ ] **Step 3: Commit.**

```bash
git add docker-compose.yml
git commit -m "feat(dev): s7bb-data-init clones the data repo into a volume

s7bb-site-dev depends on it and mounts it read-only at /repo/data, so
the dev entrypoint reads the data-repo tip without main tracking data/."
```

---

## Task 7: `.gitignore` — `/data/` and `/.data-checkout/`

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Append** to `.gitignore`:

```gitignore
# Local data working dir (untracked here; s7bb-data repo is the source of truth)
/data/

# Optional host-side clone of the data repo for offline inspection
/.data-checkout/
```

The existing `data/s7bb.db*` lines become redundant but leave them — defence-in-depth.

- [ ] **Step 2: Commit.**

```bash
git add .gitignore
git commit -m "chore: ignore /data/ and /.data-checkout/"
```

---

## Task 8: Documentation — README, CLAUDE.md, CHANGELOG

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update `README.md`.**

In §VM Setup, replace the clone step with:

```markdown
1. Clone the **data repo** over HTTPS into the path the container bind-mounts as `/repo`:

       git clone --depth=1 https://github.com/s7bb/s7bb-data.git /path/to/repo

   `REPO_PATH=/repo` points at this clone. The DB and generated JSON live
   under `/data` (host bind-mount, untracked). Each hourly cycle the
   exporter writes `/data/{latest.json,archive/*.json}`, the service
   copies them into `/repo` (flat, at the root), commits, and pushes to
   `s7bb/s7bb-data` `main`.
```

In §GitHub Pages Setup, add:

```markdown
The build workflow checks out **both** this repo (site code) and
`s7bb/s7bb-data` (the JSON) and assembles them into the deployed
artifact. `s7bb/s7bb-data` must stay public for the token-free checkout.
The fallback `schedule:` cron runs at `:10` so it picks up the VM's
`:00` hourly push.
```

In §Local development, add:

```markdown
Primary dev entry point:

    docker compose --profile dev up

`s7bb-data-init` clones the data repo into a named volume that
`s7bb-site-dev` mounts read-only at `/repo/data`. To refresh the
data-repo tip without restarting the site container:

    docker compose --profile dev run --rm s7bb-data-init

For editor inspection of the data outside Docker, clone it alongside the
repo (the path is gitignored):

    git clone --depth=1 https://github.com/s7bb/s7bb-data.git ./.data-checkout
```

- [ ] **Step 2: Update `CLAUDE.md`.** Replace the `## Architecture` diagram block with:

```markdown
## Architecture

Two repositories:

- **`s7bb/s7bb.github.io`** (this repo) — humans + Dependabot. Code,
  site, fetcher, workflows, docs. Does **not** track `data/`.
- **`s7bb/s7bb-data`** — VM bot, sole writer. Flat tree at the root:
  `latest.json`, `archive/*.json`, `archive/index.json`. Single-writer,
  so VM pushes never collide with Dependabot/PR merges.

```
DB Timetables API (XML)
  → Python fetcher → SQLite (/data/s7bb.db, VM-only)
                       ↓
                     /data/latest.json + /data/archive/*.json   (exporter)
                       ↓ (copy)
                     /repo/latest.json + /repo/archive/*.json   (s7bb-data clone)
                       ↓ (hourly push, HEAD:refs/heads/main)
                     GitHub: s7bb/s7bb-data main updated
                       ↓
                     Actions build-site.yml checks out this repo +
                     s7bb-data, assembles site/dist, deploys gh-pages.
```
```

In §Key decisions (locked), replace the GitHub-push bullet with:

```markdown
- GitHub push: VM commits a flat `latest.json` + `archive/*.json` hourly
  to **`s7bb/s7bb-data`** `main` via a fine-grained GitHub PAT scoped to
  that single repository (`Contents: read/write`). The bot PAT has no
  access to this code repo. Generated site deployed by Actions, which
  also checks out `s7bb/s7bb-data`.
```

- [ ] **Step 3: Update `CHANGELOG.md`.** Under `## [Unreleased]` add:

```markdown
### Added

- Schedule JSON moved to a dedicated single-writer repository
  `s7bb/s7bb-data`. The VM is its sole writer, so hourly data pushes no
  longer compete with Dependabot/PR merges on `main` for fast-forward —
  this removes the silent non-fast-forward push-rejection class that
  left the site serving stale data after `main` activity. The bot PAT
  is scoped to `s7bb/s7bb-data` only and cannot touch code.

### Changed

- Exporter SQL: `ORDER BY scheduled_time, train_id` (deterministic
  tie-break) — byte-stable hourly archive rewrites, smaller git deltas.
- Build workflow checks out both this repo and `s7bb/s7bb-data`;
  fallback rebuild cron shifted to `:10`.
- `docker-compose.yml`: new `s7bb-data-init` (profile `dev`) clones the
  data repo into a named volume; `s7bb-site-dev` mounts it read-only at
  `/repo/data`.
- This repo no longer tracks `data/`; it is gitignored locally.
```

- [ ] **Step 4: Commit.**

```bash
git add README.md CLAUDE.md CHANGELOG.md
git commit -m "docs: two-repository data split — README, CLAUDE.md, CHANGELOG"
```

---

## Task 9: Remove `data/` from this repo's tracked tree

**Files:**
- Delete: `data/latest.json`, `data/archive/*.json`

⚠ This is the **final code commit on the PR**. It must not be merged until `s7bb/s7bb-data` exists and is seeded (Task 11) — otherwise the build workflow's second checkout fails. The PR body must state this ordering.

- [ ] **Step 1: Confirm the data repo prerequisite is acknowledged** in the PR plan (Task 11 is performed by the maintainer *before* merge). This step is a checklist gate, not a command.

- [ ] **Step 2: Remove tracked files.**

```bash
git rm -r data/
```

(Local working-tree `data/` files remain on disk because `/data/` is now gitignored — `git rm` only updates the index.)

- [ ] **Step 3: Verify gitignore catches re-creation.**

Run: `git status --porcelain | grep '^?? data/' && echo LEAK || echo CLEAN`
Expected: `CLEAN`.

- [ ] **Step 4: Sanity-run the suites** (nothing should read tracked `data/`):

```bash
cd fetcher && uv run pytest -q && cd ../site && npm run build
```

Expected: pass.

- [ ] **Step 5: Commit.**

```bash
git commit -m "chore: stop tracking data/ — s7bb-data repo is the source of truth

latest.json and archive/*.json now live in s7bb/s7bb-data. Local working
trees still produce data/ but it is gitignored."
```

---

## Task 10: Open and self-review the PR

- [ ] **Step 1:** Push the branch and open a PR titled:

```
feat: split schedule JSON into the s7bb-data repository
```

PR body: one-paragraph summary of the design rationale at the top of this plan; link this plan file; **explicitly state the maintainer must complete Task 11 (create + seed `s7bb/s7bb-data`, rotate PAT) before merge, and Task 12 (VM cutover) after merge**; note the orphan spec `docs/superpowers/specs/2026-05-14-orphan-data-branch-design.md` is superseded and should get a follow-up `docs:` PR.

- [ ] **Step 2:** Verify CI: only `ci.yml` runs (lint + test). `build-site.yml` does **not** run on the PR (it triggers on push to `main`, schedule, or dispatch).

- [ ] **Step 3:** Self-review the diff: no `data/` paths remain in pusher/service code or their tests; `HEAD:refs/heads/main` refspec assertion still present and unchanged; `.gitignore` covers `/data/`.

---

## Task 11: One-time GitHub setup (maintainer, manual — performed BEFORE merge)

Document these steps verbatim in the PR body.

- [ ] **Step 1: Create the `s7bb/s7bb-data` repository** (public, empty, no README).

- [ ] **Step 2: Seed it from the current `data/` contents (flat layout).**

```bash
git clone --depth=1 https://github.com/s7bb/s7bb.github.io.git /tmp/code
SHA=$(git -C /tmp/code rev-parse --short HEAD)
mkdir /tmp/s7bb-data-seed
cp -a /tmp/code/data/. /tmp/s7bb-data-seed/
cd /tmp/s7bb-data-seed
git init -b main
git add .
git -c user.email=s7bb-bot@localhost -c user.name=s7bb-bot \
    commit -m "chore: seed data repo from s7bb.github.io@${SHA}"
git remote add origin https://github.com/s7bb/s7bb-data.git
git push -u origin main
```

- [ ] **Step 3: Mint a new fine-grained PAT** scoped to **`s7bb/s7bb-data` only**, permission `Contents: Read and write`. Optionally add a ruleset on `s7bb/s7bb-data` `main` blocking force-push and deletion.

- [ ] **Step 4: Retire the old access path on the code repo:** remove the `main`-branch path-scoped ruleset that allowed the old bot PAT to push `data/**`, and revoke the old PAT.

- [ ] **Step 5: Merge** the PR from Task 10.

---

## Task 12: VM cutover (maintainer, manual — performed AFTER merge)

- [ ] **Step 1:** SSH to the VM, `docker compose down s7bb-fetcher`.

- [ ] **Step 2: Repoint the `/repo` clone at the data repo.**

```bash
mv /path/to/repo /path/to/repo.old
git clone --depth=1 https://github.com/s7bb/s7bb-data.git /path/to/repo
```

(Use the actual host path backing the `.:/repo` bind mount.)

- [ ] **Step 3:** In `.env`, set the rotated `GITHUB_PAT` and `GITHUB_REPO_SLUG=s7bb/s7bb-data`.

- [ ] **Step 4:** `docker compose up -d s7bb-fetcher && docker compose logs -f s7bb-fetcher`. Expect:

  - `startup_sync: checking drift against s7bb-data main (s7bb/s7bb-data)`.
  - First hourly `_export_job`, then `export_job step stage` (no error).
  - `push_data: committed and pushed to origin/main (N file(s))`.

- [ ] **Step 5: Verify** the data repo received the push and, within ~10 min after the next `:00`, `https://<gh-pages-url>/data/latest.json` shows a `generated_at` inside the last ~75 minutes. (`build-site.yml` rebuilds on its `:10` schedule; trigger `workflow_dispatch` once manually to confirm immediately.)

---

## Task 13: Cut release per CLAUDE.md procedure

This PR contains `feat:` commits → MINOR bump.

- [ ] **Step 1:** Confirm `fetcher/pyproject.toml` `version = "0.4.5"`. Next version: `0.5.0`. (If a freshness-badge release landed first and bumped to `0.5.0`, use `0.6.0` instead and substitute it everywhere below.)

- [ ] **Step 2:** Bump and re-sync the lock:

```bash
cd fetcher
sed -i 's/^version = "0.4.5"/version = "0.5.0"/' pyproject.toml
uv sync --no-dev
cd ..
```

- [ ] **Step 3:** In `CHANGELOG.md`, rename `## [Unreleased]` to `## [0.5.0] - 2026-05-15` and add a fresh empty `## [Unreleased]` above it.

- [ ] **Step 4:** Commit + tag + push:

```bash
git add fetcher/pyproject.toml fetcher/uv.lock CHANGELOG.md
git commit -m "chore(release): 0.5.0"
git tag -a v0.5.0 -m "v0.5.0"
git push origin main v0.5.0
```

- [ ] **Step 5:** Create the GitHub Release:

```bash
gh release create v0.5.0 --title "v0.5.0" --latest \
  --notes-file <(awk '/^## \[0.5.0\]/,/^## \[/' CHANGELOG.md | sed '$d')
```

---

## Self-review (run by the plan author; included for the executor)

**Spec / rationale coverage:**
- Decouple VM pushes from `main` → Tasks 2 (flat pusher), 11 (data repo + PAT), 12 (cutover).
- Strongest PAT isolation → Task 11 Step 3-4 (separate-repo scoped PAT, old one revoked).
- Clean `main` history → Task 9 (`git rm -r data/`).
- Deterministic JSON / smaller deltas → Task 1.
- Site still publishes → Task 5 (two-repo checkout) + Task 8 README/CLAUDE.
- Local dev still works → Task 6 (`s7bb-data-init`) + Task 7 (`.gitignore`).
- Stale-data window bounded → Task 5 cron shifted to `:10`.
- Defensive ff-only merge intentionally **not** included — single-writer repo (rationale section).
- Freshness badge intentionally **not** here — separate plan `2026-05-15-freshness-badge.md`.

**Type / contract consistency:**
- `push_data` → still returns `pusher.PushOutcome`; `_PUSH_REFSPEC = "HEAD:refs/heads/main"` unchanged; `service._run_push_step` and `startup_sync._push` callers untouched (verified: no signature change).
- `_stage_into_repo(data_dir: Path, repo_path: Path) -> None` — defined and called in `service.py` only; test patches `service._run_push_step` so no real git is invoked.
- `_RAW_URL_TMPL` formatted with `slug=` only; matches `startup_sync` usage and the new test.
- Flat paths: `_LATEST_JSON = "latest.json"`, archive glob `repo_path / "archive"` — consistent across pusher code, pusher tests, `_stage_into_repo`, build workflow, and dev mount.

**Placeholder scan:** none — every step has the actual code, command, or text. `<owner>`/`/path/to/repo`/`<gh-pages-url>` in the maintainer tasks are deliberate environment-specific values, called out as such.
