# Housekeeping & Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add monthly archive JSON files (rolling current month + finalized past months), an archive index, a single hourly multi-file push, and a site `Archiv` tab so non-technical Baierbrunn residents can browse historical S7 punctuality.

**Architecture:** Hourly `_export_job` writes `data/latest.json` (unchanged 7-day window), rewrites `data/archive/YYYY-MM.json` for the current UTC month every hour, finalizes the previous month exactly once at `day=1 hour=0` UTC, regenerates `data/archive/index.json`, and the renamed `push_data` stages all of `data/latest.json` + `data/archive/*.json` in a single commit. The static site grows a top-level `Live` / `Archiv` tab pair, fetches `index.json` for a 12-month bar strip on load, and lazy-fetches monthly archives on `#/archiv/YYYY-MM` navigation.

**Tech Stack:** Python 3.11 + APScheduler + GitPython + freezegun (new test dep) + SQLite. TypeScript + Vite + Chart.js + vitest (new test dep) + jsdom.

**Spec reference:** `docs/superpowers/specs/2026-05-07-housekeeping-design.md`

**Sub-projects:** This plan covers two coupled subsystems — fetcher backend (Tasks 1–9) and site frontend (Tasks 10–17). Each fetcher task is independently shippable; site tasks depend on Tasks 2–4 producing the new JSON shapes (use fixtures during site work to decouple).

---

## File Structure

### Fetcher (`fetcher/src/s7bb_fetcher/`)

| File | Responsibility | Change |
|---|---|---|
| `exporter.py` | Build `latest.json`, monthly archive, archive index | Extend `export_monthly_archive`; add `export_archive_index`; add `_atomic_write` helper |
| `pusher.py` | Stage + commit + push data files | Rename `push_latest` → `push_data`; stage `data/archive/*.json` |
| `service.py` | APScheduler entrypoint, `_export_job` orchestration | Rewrite `_export_job` for 4-step sequence + per-step try/except + day-1 finalize |
| `cli.py` | `s7bb-fetch`, `s7bb-export` | Add `--archive-index` and `--refinalize` flags |
| `tests/test_exporter.py` | Exporter unit tests | Add monthly archive + index + finalize tests |
| `tests/test_pusher.py` | Pusher unit tests | Add archive-staging + combined-commit tests; rename references |
| `tests/test_service.py` (NEW) | Service `_export_job` orchestration tests | Cover full 4-step sequence with mocked exporter/pusher and freezegun |

### Site (`site/src/`)

| File | Responsibility | Change |
|---|---|---|
| `archive.ts` (NEW) | Types + `loadIndex()` + `loadMonth(yyyymm)` with session cache | Create |
| `pages/archive-list.ts` (NEW) | `Archiv` landing page: month list + 12-month bar | Create |
| `pages/archive-detail.ts` (NEW) | Per-month detail: daily line chart by direction, arrival table, JSON download | Create |
| `charts/monthsBar.ts` (NEW) | 12-month stacked bar chart from index | Create |
| `charts/dailyByDirection.ts` (NEW) | Daily line chart from monthly archive `daily_by_direction` | Create |
| `main.ts` | Top-level routing + nav | Add `Live`/`Archiv` parent tabs, hash router for `#/archiv` and `#/archiv/YYYY-MM`, keep nested `#heute`/`#woche`/`#statistik`/`#methodik` |
| `pages/week.ts` | Week page | Add 12-month strip section after summary bar |
| `data.ts` | Existing types | Unchanged |
| `tests/archive.test.ts` (NEW) | vitest specs for `archive.ts` helpers | Create |
| `vitest.config.ts` (NEW) | Test runner config | Create |
| `index.html` | Markup | Replace single nav with two-level (top: Live/Archiv; sub-nav rendered dynamically) |

### Repo

| File | Change |
|---|---|
| `CHANGELOG.md` | Add Unreleased entry for archive feature |
| `fetcher/pyproject.toml` | Add `freezegun==1.5.1` to `[dependency-groups].dev`; bump version to `0.2.0` |
| `site/package.json` | Add `vitest`, `jsdom`; add `test` script; bump version to `0.2.0` |

---

## Task 1: Add `freezegun` test dependency

**Files:**
- Modify: `fetcher/pyproject.toml`

- [ ] **Step 1: Add freezegun to dev deps**

Edit `fetcher/pyproject.toml`, in `[dependency-groups]` block:

```toml
[dependency-groups]
dev = [
    "pytest==9.0.3",
    "ruff==0.4.8",
    "freezegun==1.5.1",
]
```

- [ ] **Step 2: Sync deps**

```bash
cd fetcher && uv sync --group dev
```

Expected: `freezegun` installed.

- [ ] **Step 3: Smoke import**

```bash
cd fetcher && uv run python -c "from freezegun import freeze_time; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add fetcher/pyproject.toml fetcher/uv.lock
git commit -m "chore(fetcher): add freezegun dev dependency"
```

---

## Task 2: Atomic-write helper in exporter

Reason: spec §Error Handling requires temp + `os.replace` to avoid half-written files on crash.

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/exporter.py`
- Modify: `fetcher/tests/test_exporter.py`

- [ ] **Step 1: Write the failing test**

Append to `fetcher/tests/test_exporter.py`:

```python
def test_atomic_write_replaces_existing_file(tmp_path):
    from s7bb_fetcher.exporter import _atomic_write_json

    target = tmp_path / "out.json"
    target.write_text('{"old": true}', encoding="utf-8")

    _atomic_write_json(target, {"new": True})

    assert json.loads(target.read_text()) == {"new": True}
    # No leftover temp files in the directory
    leftovers = [p for p in tmp_path.iterdir() if p.name != "out.json"]
    assert leftovers == []


def test_atomic_write_creates_parent_dirs(tmp_path):
    from s7bb_fetcher.exporter import _atomic_write_json

    target = tmp_path / "sub" / "deeper" / "out.json"
    _atomic_write_json(target, {"k": 1})
    assert target.exists()
    assert json.loads(target.read_text()) == {"k": 1}
```

- [ ] **Step 2: Run test — expect failure**

```bash
cd fetcher && uv run pytest tests/test_exporter.py::test_atomic_write_replaces_existing_file -v
```

Expected: FAIL — `ImportError` or `AttributeError: module 's7bb_fetcher.exporter' has no attribute '_atomic_write_json'`.

- [ ] **Step 3: Implement helper**

Add to `fetcher/src/s7bb_fetcher/exporter.py` near the top (after imports):

```python
import os
import tempfile


def _atomic_write_json(path: Path, payload: object) -> None:
    """Write JSON atomically: temp file in same dir, then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
```

Also replace the existing `out_path.write_text(json.dumps(...))` calls in `export_latest` and `export_monthly_archive` with `_atomic_write_json(out_path, payload)`. Drop the now-redundant `out_path.parent.mkdir(...)` calls — `_atomic_write_json` does it.

- [ ] **Step 4: Run tests — expect pass**

```bash
cd fetcher && uv run pytest tests/test_exporter.py -v
```

Expected: all green, including the two new tests and the pre-existing exporter tests.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/exporter.py fetcher/tests/test_exporter.py
git commit -m "refactor(exporter): atomic JSON writes via temp file + os.replace"
```

---

## Task 3: Extend `export_monthly_archive` — `by_direction` aggregates

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/exporter.py`
- Modify: `fetcher/tests/test_exporter.py`

- [ ] **Step 1: Write the failing test**

Append to `fetcher/tests/test_exporter.py`:

```python
def test_monthly_archive_includes_by_direction(tmp_path):
    from s7bb_fetcher.exporter import export_monthly_archive

    conn = open_db(tmp_path / "test.db")
    records = [
        _make_arrival("m1", "2026-04-01T08:00:00+00:00", "muenchen"),
        _make_arrival("m2", "2026-04-15T08:00:00+00:00", "muenchen", delay_minutes=3),
        _make_arrival("w1", "2026-04-01T08:13:00+00:00", "wolfratshausen"),
        _make_arrival("w2", "2026-04-20T08:13:00+00:00", "wolfratshausen", cancelled=True),
    ]
    upsert_records(conn, records)
    out = tmp_path / "2026-04.json"

    export_monthly_archive(conn, 2026, 4, out)
    data = json.loads(out.read_text())

    bd = data["aggregates"]["by_direction"]
    assert bd["muenchen"]["total"] == 2
    assert bd["muenchen"]["late"] == 1
    assert bd["wolfratshausen"]["cancelled"] == 1
```

- [ ] **Step 2: Run test — expect failure**

```bash
cd fetcher && uv run pytest tests/test_exporter.py::test_monthly_archive_includes_by_direction -v
```

Expected: FAIL — `KeyError: 'by_direction'`.

- [ ] **Step 3: Add `by_direction` to monthly archive aggregates**

In `fetcher/src/s7bb_fetcher/exporter.py`, edit `export_monthly_archive`. Replace the `aggregates` field of `payload` with:

```python
    aggregates = {
        **_aggregate(rows),
        "by_direction": {
            "muenchen":       _aggregate([r for r in rows if r["direction_bucket"] == "muenchen"]),
            "wolfratshausen": _aggregate([r for r in rows if r["direction_bucket"] == "wolfratshausen"]),
        },
    }
```

Then build `payload`:

```python
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "station": "Baierbrunn",
        "line": "S7",
        "period": f"{year:04d}-{month:02d}",
        "arrivals": rows,
        "aggregates": aggregates,
    }
```

- [ ] **Step 4: Run test — expect pass**

```bash
cd fetcher && uv run pytest tests/test_exporter.py::test_monthly_archive_includes_by_direction -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/exporter.py fetcher/tests/test_exporter.py
git commit -m "feat(exporter): add by_direction aggregates to monthly archive"
```

---

## Task 4: Add `daily` and `daily_by_direction` to monthly archive

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/exporter.py`
- Modify: `fetcher/tests/test_exporter.py`

- [ ] **Step 1: Write the failing test**

Append to `fetcher/tests/test_exporter.py`:

```python
def test_monthly_archive_includes_daily_aggregates(tmp_path):
    from s7bb_fetcher.exporter import export_monthly_archive

    conn = open_db(tmp_path / "test.db")
    records = [
        _make_arrival("m1", "2026-04-01T08:00:00+00:00", "muenchen"),
        _make_arrival("m2", "2026-04-01T08:20:00+00:00", "muenchen", delay_minutes=5),
        _make_arrival("m3", "2026-04-02T08:00:00+00:00", "muenchen"),
        _make_arrival("w1", "2026-04-01T08:13:00+00:00", "wolfratshausen"),
        _make_arrival("w2", "2026-04-02T08:13:00+00:00", "wolfratshausen", cancelled=True),
    ]
    upsert_records(conn, records)
    out = tmp_path / "2026-04.json"

    export_monthly_archive(conn, 2026, 4, out)
    data = json.loads(out.read_text())

    daily = {d["date"]: d for d in data["daily"]}
    assert "2026-04-01" in daily
    assert daily["2026-04-01"]["total"] == 3
    assert daily["2026-04-01"]["late"] == 1

    by_dir = data["daily_by_direction"]
    assert by_dir["muenchen"][0]["date"] == "2026-04-01"
    by_dir_w_dates = [d["date"] for d in by_dir["wolfratshausen"]]
    assert by_dir_w_dates == ["2026-04-01", "2026-04-02"]
```

- [ ] **Step 2: Run test — expect failure**

```bash
cd fetcher && uv run pytest tests/test_exporter.py::test_monthly_archive_includes_daily_aggregates -v
```

Expected: FAIL — `KeyError: 'daily'`.

- [ ] **Step 3: Implement daily helpers**

Add to `fetcher/src/s7bb_fetcher/exporter.py` above `export_monthly_archive`:

```python
def _daily_aggregates(rows: list[dict]) -> list[dict]:
    by_date: dict[str, list[dict]] = {}
    for r in rows:
        date = r["scheduled_time"][:10]
        by_date.setdefault(date, []).append(r)
    return [
        {"date": date, **_aggregate(day_rows)}
        for date, day_rows in sorted(by_date.items())
    ]
```

Then in `export_monthly_archive`, before building `payload` add:

```python
    daily = _daily_aggregates(rows)
    daily_by_direction = {
        "muenchen":       _daily_aggregates([r for r in rows if r["direction_bucket"] == "muenchen"]),
        "wolfratshausen": _daily_aggregates([r for r in rows if r["direction_bucket"] == "wolfratshausen"]),
    }
```

Extend `payload`:

```python
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "station": "Baierbrunn",
        "line": "S7",
        "period": f"{year:04d}-{month:02d}",
        "arrivals": rows,
        "aggregates": aggregates,
        "daily": daily,
        "daily_by_direction": daily_by_direction,
    }
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd fetcher && uv run pytest tests/test_exporter.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/exporter.py fetcher/tests/test_exporter.py
git commit -m "feat(exporter): add per-day aggregates to monthly archive"
```

---

## Task 5: Add `finalized` flag to monthly archive

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/exporter.py`
- Modify: `fetcher/tests/test_exporter.py`

- [ ] **Step 1: Write the failing test**

Append to `fetcher/tests/test_exporter.py`:

```python
def test_finalized_flag_default_false(tmp_path):
    from s7bb_fetcher.exporter import export_monthly_archive

    conn = open_db(tmp_path / "test.db")
    upsert_records(conn, [_make_arrival("m1", "2026-04-01T08:00:00+00:00", "muenchen")])
    out = tmp_path / "2026-04.json"

    export_monthly_archive(conn, 2026, 4, out)
    data = json.loads(out.read_text())
    assert data["finalized"] is False


def test_finalized_flag_true_when_requested(tmp_path):
    from s7bb_fetcher.exporter import export_monthly_archive

    conn = open_db(tmp_path / "test.db")
    upsert_records(conn, [_make_arrival("m1", "2026-04-01T08:00:00+00:00", "muenchen")])
    out = tmp_path / "2026-04.json"

    export_monthly_archive(conn, 2026, 4, out, finalized=True)
    data = json.loads(out.read_text())
    assert data["finalized"] is True
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd fetcher && uv run pytest tests/test_exporter.py::test_finalized_flag_default_false tests/test_exporter.py::test_finalized_flag_true_when_requested -v
```

Expected: FAIL — `KeyError: 'finalized'` and `TypeError: unexpected keyword argument 'finalized'`.

- [ ] **Step 3: Add `finalized` parameter**

In `fetcher/src/s7bb_fetcher/exporter.py`, change signature of `export_monthly_archive`:

```python
def export_monthly_archive(
    conn: sqlite3.Connection,
    year: int,
    month: int,
    out_path: Path,
    finalized: bool = False,
) -> None:
```

Add `"finalized": finalized,` to the `payload` dict.

- [ ] **Step 4: Run tests — expect pass**

```bash
cd fetcher && uv run pytest tests/test_exporter.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/exporter.py fetcher/tests/test_exporter.py
git commit -m "feat(exporter): add finalized flag to monthly archive"
```

---

## Task 6: Add `export_archive_index`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/exporter.py`
- Modify: `fetcher/tests/test_exporter.py`

- [ ] **Step 1: Write the failing test**

Append to `fetcher/tests/test_exporter.py`:

```python
def test_archive_index_lists_months_in_order(tmp_path):
    from s7bb_fetcher.exporter import export_archive_index, export_monthly_archive

    conn = open_db(tmp_path / "test.db")
    upsert_records(conn, [
        _make_arrival("a", "2026-03-15T08:00:00+00:00", "muenchen"),
        _make_arrival("b", "2026-04-15T08:00:00+00:00", "muenchen"),
        _make_arrival("c", "2026-05-01T08:00:00+00:00", "wolfratshausen"),
    ])
    archive_dir = tmp_path / "archive"
    export_monthly_archive(conn, 2026, 3, archive_dir / "2026-03.json", finalized=True)
    export_monthly_archive(conn, 2026, 4, archive_dir / "2026-04.json", finalized=True)
    export_monthly_archive(conn, 2026, 5, archive_dir / "2026-05.json", finalized=False)

    index_path = archive_dir / "index.json"
    export_archive_index(archive_dir, index_path)
    idx = json.loads(index_path.read_text())

    periods = [m["period"] for m in idx["months"]]
    assert periods == ["2026-03", "2026-04", "2026-05"]
    finals = [m["finalized"] for m in idx["months"]]
    assert finals == [True, True, False]


def test_archive_index_includes_summary_and_by_direction(tmp_path):
    from s7bb_fetcher.exporter import export_archive_index, export_monthly_archive

    conn = open_db(tmp_path / "test.db")
    upsert_records(conn, [
        _make_arrival("m1", "2026-04-01T08:00:00+00:00", "muenchen"),
        _make_arrival("w1", "2026-04-01T08:13:00+00:00", "wolfratshausen", delay_minutes=2),
    ])
    archive_dir = tmp_path / "archive"
    export_monthly_archive(conn, 2026, 4, archive_dir / "2026-04.json")

    index_path = archive_dir / "index.json"
    export_archive_index(archive_dir, index_path)
    idx = json.loads(index_path.read_text())

    apr = next(m for m in idx["months"] if m["period"] == "2026-04")
    assert apr["total"] == 2
    assert apr["by_direction"]["muenchen"]["total"] == 1
    assert apr["by_direction"]["wolfratshausen"]["late"] == 1
    assert idx["station"] == "Baierbrunn"
    assert "generated_at" in idx


def test_archive_index_skips_non_period_files(tmp_path):
    from s7bb_fetcher.exporter import export_archive_index

    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    # Stray files that should not be parsed as months
    (archive_dir / "index.json").write_text('{"months":[]}')
    (archive_dir / "README.txt").write_text("ignore me")
    (archive_dir / "garbage.json").write_text('{"period":"not-a-month"}')

    out = archive_dir / "index.json"
    export_archive_index(archive_dir, out)
    idx = json.loads(out.read_text())
    assert idx["months"] == []
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd fetcher && uv run pytest tests/test_exporter.py -k archive_index -v
```

Expected: FAIL — `ImportError: cannot import name 'export_archive_index'`.

- [ ] **Step 3: Implement `export_archive_index`**

Append to `fetcher/src/s7bb_fetcher/exporter.py`:

```python
import re

_PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")


def export_archive_index(archive_dir: Path, index_path: Path) -> None:
    """Build data/archive/index.json by scanning archive_dir for YYYY-MM.json files."""
    months: list[dict] = []
    if archive_dir.exists():
        for entry in sorted(archive_dir.iterdir()):
            if entry.name == index_path.name or entry.suffix != ".json":
                continue
            stem = entry.stem
            if not _PERIOD_RE.match(stem):
                continue
            try:
                payload = json.loads(entry.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            agg = payload.get("aggregates", {})
            months.append({
                "period": payload.get("period", stem),
                "finalized": bool(payload.get("finalized", False)),
                "total":         agg.get("total", 0),
                "on_time":       agg.get("on_time", 0),
                "late":          agg.get("late", 0),
                "cancelled":     agg.get("cancelled", 0),
                "avg_delay_min": agg.get("avg_delay_min", 0.0),
                "by_direction":  agg.get("by_direction", {}),
            })

    months.sort(key=lambda m: m["period"])
    out = {
        "generated_at": datetime.now(UTC).isoformat(),
        "station": "Baierbrunn",
        "months": months,
    }
    _atomic_write_json(index_path, out)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd fetcher && uv run pytest tests/test_exporter.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/exporter.py fetcher/tests/test_exporter.py
git commit -m "feat(exporter): add export_archive_index for archive month list"
```

---

## Task 7: Rename `push_latest` → `push_data`, stage archive files

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/pusher.py`
- Modify: `fetcher/tests/test_pusher.py`
- Modify: `fetcher/src/s7bb_fetcher/service.py` (callsite)

- [ ] **Step 1: Update test fixtures + add new tests**

In `fetcher/tests/test_pusher.py`:

1. Replace all `from s7bb_fetcher.pusher import push_latest` with `from s7bb_fetcher.pusher import push_data`.
2. Replace every `push_latest(` call with `push_data(`.
3. Replace test names containing `push_latest` with `push_data`.
4. Append the following new tests:

```python
def test_push_data_stages_archive_and_latest(monkeypatch, dirty_latest):
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    work = Path(dirty_latest.working_tree_dir)

    arch_dir = work / "data" / "archive"
    arch_dir.mkdir(parents=True, exist_ok=True)
    (arch_dir / "2026-04.json").write_text('{"period":"2026-04"}\n')
    (arch_dir / "index.json").write_text('{"months":[]}\n')

    captured = {}

    def fake_push(self, *args, **kwargs):
        captured["url"] = args[0]
        return ""

    _install_fake_push(monkeypatch, fake_push)
    result = push_data(work)

    assert result is True
    # New commit should contain all three changed files
    last = dirty_latest.head.commit
    files = set(last.stats.files.keys())
    assert "data/latest.json" in files
    assert "data/archive/2026-04.json" in files
    assert "data/archive/index.json" in files
    assert last.message.startswith("chore: update data ")


def test_push_data_skips_when_no_diff(monkeypatch, working_repo):
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    called = []

    def fake_push(self, *args, **kwargs):
        called.append(True)
        return ""

    _install_fake_push(monkeypatch, fake_push)
    result = push_data(Path(working_repo.working_tree_dir))
    assert result is False
    assert called == []


def test_push_data_single_commit_for_combined_changes(monkeypatch, dirty_latest):
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    work = Path(dirty_latest.working_tree_dir)
    arch_dir = work / "data" / "archive"
    arch_dir.mkdir(parents=True, exist_ok=True)
    (arch_dir / "2026-04.json").write_text('{"period":"2026-04"}\n')

    head_before = dirty_latest.head.commit
    _install_fake_push(monkeypatch, lambda self, *a, **kw: "")
    push_data(work)
    head_after = dirty_latest.head.commit

    assert head_after != head_before
    assert head_after.parents[0] == head_before  # exactly one new commit
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd fetcher && uv run pytest tests/test_pusher.py -v
```

Expected: FAIL — `ImportError: cannot import name 'push_data'`.

- [ ] **Step 3: Implement `push_data` (rename + extend)**

Replace the body of `fetcher/src/s7bb_fetcher/pusher.py` from the `_LATEST_JSON` constant down. Keep `_actor`, `_resolve_slug`, `_push_via_pat`, `_ORIGIN_RE`, and the imports unchanged.

```python
_LATEST_JSON = "data/latest.json"
_ARCHIVE_GLOB = "data/archive/*.json"
_HTTPS_USER = "x-access-token"
_PUSH_REFSPEC = "HEAD:refs/heads/main"
```

Then replace `push_latest` with:

```python
def push_data(repo_path: Path) -> bool:
    """Stage data/latest.json + data/archive/*.json, commit if changed, push.

    Returns True if a commit was made and pushed, False if nothing changed.
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
        return False

    repo.index.add(paths)

    if not repo.index.diff("HEAD"):
        logger.info("push_data: no changes, skipping commit")
        return False

    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    author = _actor("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "s7bb-bot")
    committer = _actor("GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "s7bb-bot")
    repo.index.commit(
        f"chore: update data {ts}",
        author=author,
        committer=committer,
    )

    token = os.environ.get("GITHUB_PAT", "").strip()
    if not token:
        raise RuntimeError("GITHUB_PAT not set; cannot push to GitHub")

    _push_via_pat(repo, token)
    logger.info("push_data: pushed to origin/main (%d file(s))", len(paths))
    return True
```

- [ ] **Step 4: Update service.py callsite**

In `fetcher/src/s7bb_fetcher/service.py`, change:

```python
    from .pusher import push_latest
```
to:
```python
    from .pusher import push_data
```

And `push_latest(REPO_PATH)` to `push_data(REPO_PATH)`.

- [ ] **Step 5: Run tests — expect pass**

```bash
cd fetcher && uv run pytest tests/test_pusher.py -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add fetcher/src/s7bb_fetcher/pusher.py fetcher/src/s7bb_fetcher/service.py fetcher/tests/test_pusher.py
git commit -m "feat(pusher)!: rename push_latest to push_data and stage archive files

BREAKING CHANGE: push_latest is removed; callers must use push_data which
stages data/latest.json and all data/archive/*.json in one commit."
```

---

## Task 8: Rewrite `_export_job` for 4-step archive sequence

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/service.py`
- Create: `fetcher/tests/test_service.py`

- [ ] **Step 1: Write failing tests for `_export_job`**

Create `fetcher/tests/test_service.py`:

```python
"""Tests for service._export_job orchestration."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    # Mid-month: only the current month is exported, never the previous.
    monthly_calls = mocks["export_monthly"].call_args_list
    assert len(monthly_calls) == 1
    args, kwargs = monthly_calls[0]
    # signature: (conn, year, month, out_path, finalized=...)
    assert args[1] == 2026
    assert args[2] == 5
    assert kwargs.get("finalized", args[4] if len(args) > 4 else False) is False
    assert mocks["export_index"].call_count == 1
    assert mocks["push_data"].call_count == 1


@freeze_time("2026-05-01T00:00:00+00:00")
def test_export_job_finalizes_prev_month_on_day_one_hour_zero(mocks):
    from s7bb_fetcher.service import _export_job

    _export_job()

    # Two monthly exports: current (2026-05, finalized=False) + previous (2026-04, finalized=True)
    calls = mocks["export_monthly"].call_args_list
    assert len(calls) == 2
    periods = sorted(((c.args[1], c.args[2]) for c in calls))
    assert periods == [(2026, 4), (2026, 5)]
    finalized_flags = {(c.args[1], c.args[2]): c.kwargs.get("finalized", False) for c in calls}
    assert finalized_flags[(2026, 4)] is True
    assert finalized_flags[(2026, 5)] is False


@freeze_time("2026-01-01T00:00:00+00:00")
def test_export_job_finalize_handles_year_boundary(mocks):
    from s7bb_fetcher.service import _export_job

    _export_job()

    calls = mocks["export_monthly"].call_args_list
    periods = sorted(((c.args[1], c.args[2]) for c in calls))
    assert periods == [(2025, 12), (2026, 1)]


@freeze_time("2026-05-01T01:00:00+00:00")
def test_export_job_skips_finalize_when_not_hour_zero(mocks):
    from s7bb_fetcher.service import _export_job

    _export_job()
    # Day 1 but hour 1 → only current month, no finalize.
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
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd fetcher && uv run pytest tests/test_service.py -v
```

Expected: FAIL — assertions about new behavior fail.

- [ ] **Step 3: Implement new `_export_job`**

Replace `_export_job` in `fetcher/src/s7bb_fetcher/service.py`. Also add a helper for previous-month math at module top:

```python
from datetime import UTC, datetime
```

(Keep existing imports; just add `datetime` and `UTC` if not already imported.)

Replace `_export_job`:

```python
ARCHIVE_DIR = DATA_DIR / "archive"
INDEX_PATH  = ARCHIVE_DIR / "index.json"


def _prev_year_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _safe(label: str, fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except Exception:
        logger.exception("export_job step %s failed", label)


def _export_job() -> None:
    from .exporter import export_archive_index, export_latest, export_monthly_archive
    from .pusher import push_data
    from .storage import open_db

    now = datetime.now(UTC)
    conn = None
    try:
        conn = open_db(DB_PATH)
    except Exception:
        logger.exception("export_job: open_db failed; aborting")
        return

    _safe("latest", export_latest, conn, OUT_PATH)

    current_archive = ARCHIVE_DIR / f"{now.year:04d}-{now.month:02d}.json"
    _safe(
        "archive_current",
        export_monthly_archive,
        conn, now.year, now.month, current_archive, finalized=False,
    )

    if now.day == 1 and now.hour == 0:
        py, pm = _prev_year_month(now.year, now.month)
        prev_archive = ARCHIVE_DIR / f"{py:04d}-{pm:02d}.json"
        _safe(
            "archive_finalize",
            export_monthly_archive,
            conn, py, pm, prev_archive, finalized=True,
        )

    _safe("archive_index", export_archive_index, ARCHIVE_DIR, INDEX_PATH)

    _safe("push", push_data, REPO_PATH)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd fetcher && uv run pytest tests/test_service.py -v
```

Expected: all green.

- [ ] **Step 5: Run full fetcher suite + lint**

```bash
cd fetcher && uv run pytest && uv run ruff check src tests
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add fetcher/src/s7bb_fetcher/service.py fetcher/tests/test_service.py
git commit -m "feat(service): hourly archive export sequence with day-1 finalize"
```

---

## Task 9: Add CLI flags `--archive-index` and `--refinalize`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/cli.py`
- Create: `fetcher/tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Create `fetcher/tests/test_cli.py`:

```python
import json
from pathlib import Path

from s7bb_fetcher.cli import export


def _seed_db(db_path: Path) -> None:
    from s7bb_fetcher.parser import ArrivalRecord
    from s7bb_fetcher.storage import open_db, upsert_records
    conn = open_db(db_path)
    upsert_records(conn, [
        ArrivalRecord(
            train_id="t1", line="S7", station="Baierbrunn",
            direction="München", direction_bucket="muenchen",
            scheduled_time="2026-04-01T08:00:00+00:00",
            actual_time="2026-04-01T08:00:00+00:00",
            delay_minutes=0, cancelled=False, reason=None,
        ),
    ])


def test_cli_archive_index_flag(tmp_path, capsys):
    db = tmp_path / "s7bb.db"
    _seed_db(db)
    archive_dir = tmp_path / "archive"
    out = archive_dir / "2026-04.json"

    export(["--db", str(db), "--archive", "2026-04", "--out-dir", str(archive_dir)])
    export(["--db", str(db), "--archive-index", "--out-dir", str(archive_dir)])

    idx = json.loads((archive_dir / "index.json").read_text())
    assert any(m["period"] == "2026-04" for m in idx["months"])


def test_cli_refinalize_flag_overwrites_finalized_archive(tmp_path):
    db = tmp_path / "s7bb.db"
    _seed_db(db)
    archive_dir = tmp_path / "archive"

    # First write: not finalized.
    export(["--db", str(db), "--archive", "2026-04", "--out-dir", str(archive_dir)])
    archive = archive_dir / "2026-04.json"
    data1 = json.loads(archive.read_text())
    assert data1["finalized"] is False

    # Refinalize: same month, but flag flips to True.
    export([
        "--db", str(db), "--archive", "2026-04",
        "--out-dir", str(archive_dir), "--refinalize",
    ])
    data2 = json.loads(archive.read_text())
    assert data2["finalized"] is True


def test_cli_archive_index_requires_dir(tmp_path):
    db = tmp_path / "s7bb.db"
    _seed_db(db)
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()

    export(["--db", str(db), "--archive-index", "--out-dir", str(archive_dir)])
    assert (archive_dir / "index.json").exists()
```

- [ ] **Step 2: Run — expect failure**

```bash
cd fetcher && uv run pytest tests/test_cli.py -v
```

Expected: FAIL — unknown args `--archive-index`, `--refinalize`, `--out-dir`.

- [ ] **Step 3: Update `cli.py`**

Replace the `export` function in `fetcher/src/s7bb_fetcher/cli.py`:

```python
def export(argv: list[str] | None = None) -> None:
    from .exporter import export_archive_index, export_latest, export_monthly_archive
    from .storage import open_db

    parser = argparse.ArgumentParser(description="Export DB data to JSON")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite DB path")
    parser.add_argument("--out", default=str(LATEST_JSON), help="latest.json output path")
    parser.add_argument("--out-dir", default=str(ARCHIVE_DIR), help="Archive directory")
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument(
        "--archive",
        metavar="YYYY-MM",
        help="Export a monthly archive instead (format: 2026-04)",
    )
    parser.add_argument(
        "--archive-index",
        action="store_true",
        help="Regenerate data/archive/index.json from existing archive files",
    )
    parser.add_argument(
        "--refinalize",
        action="store_true",
        help="With --archive YYYY-MM: rewrite the archive with finalized=true",
    )
    args = parser.parse_args(argv)

    conn = open_db(Path(args.db))
    archive_dir = Path(args.out_dir)

    if args.archive_index:
        archive_dir.mkdir(parents=True, exist_ok=True)
        export_archive_index(archive_dir, archive_dir / "index.json")
        print(f"Archive index written → {archive_dir / 'index.json'}")
        return

    if args.archive:
        try:
            dt = datetime.strptime(args.archive, "%Y-%m")
        except ValueError:
            print(f"Invalid archive period '{args.archive}', expected YYYY-MM", file=sys.stderr)
            sys.exit(1)
        out = archive_dir / f"{args.archive}.json"
        export_monthly_archive(conn, dt.year, dt.month, out, finalized=args.refinalize)
        print(f"Archive written → {out} (finalized={args.refinalize})")
        return

    export_latest(conn, Path(args.out), args.window_days)
    print(f"latest.json written → {args.out}")
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd fetcher && uv run pytest tests/test_cli.py -v && uv run ruff check src tests
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/cli.py fetcher/tests/test_cli.py
git commit -m "feat(cli): add --archive-index and --refinalize flags"
```

---

## Task 10: Add vitest + jsdom to site dev deps

**Files:**
- Modify: `site/package.json`
- Create: `site/vitest.config.ts`

- [ ] **Step 1: Install dev deps**

```bash
cd site && npm install --save-dev vitest@2.1.4 jsdom@25.0.1
```

- [ ] **Step 2: Add `test` script**

Edit `site/package.json` `scripts`:

```json
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "lint": "eslint src",
    "test": "vitest run"
  },
```

- [ ] **Step 3: Create vitest config**

Create `site/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts"],
  },
});
```

- [ ] **Step 4: Smoke test**

Create `site/src/smoke.test.ts` (temporary):

```ts
import { describe, it, expect } from "vitest";

describe("smoke", () => {
  it("runs", () => {
    expect(1 + 1).toBe(2);
  });
});
```

```bash
cd site && npm test
```

Expected: 1 passed.

- [ ] **Step 5: Remove smoke test, commit**

```bash
rm site/src/smoke.test.ts
git add site/package.json site/package-lock.json site/vitest.config.ts
git commit -m "chore(site): add vitest and jsdom for unit tests"
```

---

## Task 11: Site `archive.ts` types + helpers

**Files:**
- Create: `site/src/archive.ts`
- Create: `site/src/archive.test.ts`

- [ ] **Step 1: Write failing tests**

Create `site/src/archive.test.ts`:

```ts
import { describe, it, expect, beforeEach, vi } from "vitest";
import { loadIndex, loadMonth, _resetCache } from "./archive.js";

const indexJson = {
  generated_at: "2026-05-07T07:00:00+00:00",
  station: "Baierbrunn",
  months: [
    {
      period: "2026-04", finalized: true,
      total: 1234, on_time: 1100, late: 120, cancelled: 14, avg_delay_min: 1.2,
      by_direction: {
        muenchen:       { total: 617, on_time: 550, late: 60, cancelled: 7, avg_delay_min: 1.3 },
        wolfratshausen: { total: 617, on_time: 550, late: 60, cancelled: 7, avg_delay_min: 1.1 },
      },
    },
  ],
};

const monthJson = {
  generated_at: "2026-04-30T23:59:00+00:00",
  station: "Baierbrunn", line: "S7", period: "2026-04", finalized: true,
  arrivals: [],
  aggregates: { total: 1, on_time: 1, late: 0, cancelled: 0, avg_delay_min: 0,
    by_direction: { muenchen: {}, wolfratshausen: {} } },
  daily: [{ date: "2026-04-01", total: 1, on_time: 1, late: 0, cancelled: 0, avg_delay_min: 0 }],
  daily_by_direction: { muenchen: [], wolfratshausen: [] },
};

beforeEach(() => {
  _resetCache();
  vi.restoreAllMocks();
});

describe("loadIndex", () => {
  it("fetches and parses index.json", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(indexJson), { status: 200 }) as Response,
    );
    const idx = await loadIndex();
    expect(idx.months[0].period).toBe("2026-04");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("caches across calls within a session", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(indexJson), { status: 200 }) as Response,
    );
    await loadIndex();
    await loadIndex();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("throws on non-200", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("nope", { status: 404 }) as Response,
    );
    await expect(loadIndex()).rejects.toThrow();
  });
});

describe("loadMonth", () => {
  it("fetches archive/YYYY-MM.json", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(monthJson), { status: 200 }) as Response,
    );
    const m = await loadMonth("2026-04");
    expect(m.period).toBe("2026-04");
    expect(fetchSpy.mock.calls[0][0]).toContain("2026-04.json");
  });

  it("caches per-month", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(monthJson), { status: 200 }) as Response,
    );
    await loadMonth("2026-04");
    await loadMonth("2026-04");
    await loadMonth("2026-05");
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("rejects malformed period", async () => {
    await expect(loadMonth("2026-4")).rejects.toThrow();
    await expect(loadMonth("../etc")).rejects.toThrow();
  });
});
```

- [ ] **Step 2: Run — expect failure**

```bash
cd site && npm test
```

Expected: FAIL — `Cannot find module './archive.js'`.

- [ ] **Step 3: Implement `archive.ts`**

Create `site/src/archive.ts`:

```ts
import type { Arrival, DayAggregate } from "./data.js";

export interface MonthSummary {
  period: string;
  finalized: boolean;
  total: number;
  on_time: number;
  late: number;
  cancelled: number;
  avg_delay_min: number;
  by_direction: Record<"muenchen" | "wolfratshausen", DayAggregate>;
}

export interface ArchiveIndex {
  generated_at: string;
  station: string;
  months: MonthSummary[];
}

export interface MonthlyArchive {
  generated_at: string;
  station: string;
  line: string;
  period: string;
  finalized: boolean;
  arrivals: Arrival[];
  aggregates: DayAggregate & {
    by_direction: Record<"muenchen" | "wolfratshausen", DayAggregate>;
  };
  daily: (DayAggregate & { date: string })[];
  daily_by_direction: Record<"muenchen" | "wolfratshausen", (DayAggregate & { date: string })[]>;
}

const _PERIOD_RE = /^\d{4}-\d{2}$/;

let _indexCache: Promise<ArchiveIndex> | null = null;
const _monthCache = new Map<string, Promise<MonthlyArchive>>();

function archiveBase(): string {
  return import.meta.env.DEV
    ? "../data/archive"
    : `${import.meta.env.BASE_URL}data/archive`;
}

export async function loadIndex(): Promise<ArchiveIndex> {
  if (!_indexCache) {
    _indexCache = (async () => {
      const url = `${archiveBase()}/index.json`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`Failed to load archive index: ${resp.status}`);
      return resp.json() as Promise<ArchiveIndex>;
    })().catch((e) => { _indexCache = null; throw e; });
  }
  return _indexCache;
}

export async function loadMonth(period: string): Promise<MonthlyArchive> {
  if (!_PERIOD_RE.test(period)) {
    throw new Error(`Invalid period: ${period}`);
  }
  let cached = _monthCache.get(period);
  if (!cached) {
    cached = (async () => {
      const url = `${archiveBase()}/${period}.json`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`Failed to load month ${period}: ${resp.status}`);
      return resp.json() as Promise<MonthlyArchive>;
    })().catch((e) => { _monthCache.delete(period); throw e; });
    _monthCache.set(period, cached);
  }
  return cached;
}

export function _resetCache(): void {
  _indexCache = null;
  _monthCache.clear();
}
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd site && npm test
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add site/src/archive.ts site/src/archive.test.ts
git commit -m "feat(site): archive index + month loaders with session cache"
```

---

## Task 12: Hash router for `Live` / `Archiv` top-level tabs

**Files:**
- Modify: `site/index.html`
- Modify: `site/src/main.ts`

- [ ] **Step 1: Update markup**

Replace the `<nav>` and `<main>` blocks in `site/index.html`:

```html
    <nav id="top-nav">
      <a href="#/" data-section="live" class="active">Live</a>
      <a href="#/archiv" data-section="archiv">Archiv</a>
    </nav>
    <nav id="sub-nav"></nav>
    <main id="content">
      <p class="loading">Lade Daten…</p>
    </main>
```

- [ ] **Step 2: Rewrite `main.ts`**

Replace `site/src/main.ts`:

```ts
import "./style.css";
import { loadData } from "./data.js";
import { renderToday } from "./pages/today.js";
import { renderWeek } from "./pages/week.js";
import { renderStats } from "./pages/stats.js";
import { renderMethodology } from "./pages/methodology.js";
import { renderArchiveList } from "./pages/archive-list.js";
import { renderArchiveDetail } from "./pages/archive-detail.js";

type LivePage = "heute" | "woche" | "statistik" | "methodik";

interface Route {
  section: "live" | "archiv";
  livePage?: LivePage;
  period?: string;
}

function parseRoute(hash: string): Route {
  const h = hash.replace(/^#\/?/, "");
  if (h.startsWith("archiv/")) {
    const period = h.slice("archiv/".length);
    return { section: "archiv", period };
  }
  if (h === "archiv") return { section: "archiv" };
  if (h === "" || h === "live") return { section: "live", livePage: "heute" };
  if (["heute", "woche", "statistik", "methodik"].includes(h)) {
    return { section: "live", livePage: h as LivePage };
  }
  return { section: "live", livePage: "heute" };
}

const liveTabs: { id: LivePage; label: string }[] = [
  { id: "heute",     label: "Heute" },
  { id: "woche",     label: "Letzte 7 Tage" },
  { id: "statistik", label: "Statistik" },
  { id: "methodik",  label: "Methodik" },
];

function renderSubNav(route: Route): void {
  const subnav = document.getElementById("sub-nav")!;
  if (route.section === "live") {
    subnav.innerHTML = liveTabs
      .map((t) => `<a href="#${t.id}" data-page="${t.id}">${t.label}</a>`)
      .join("");
    subnav.querySelectorAll("a").forEach((a) =>
      a.classList.toggle("active", a.dataset.page === route.livePage),
    );
    subnav.style.display = "";
  } else {
    subnav.innerHTML = "";
    subnav.style.display = "none";
  }
}

async function main() {
  const content = document.getElementById("content")!;
  const topNav = document.getElementById("top-nav")!;

  let liveData: Awaited<ReturnType<typeof loadData>> | null = null;
  async function getLiveData() {
    if (!liveData) liveData = await loadData();
    return liveData;
  }

  async function renderRoute(route: Route): Promise<void> {
    topNav.querySelectorAll("a").forEach((a) =>
      a.classList.toggle("active", a.dataset.section === route.section),
    );
    renderSubNav(route);
    content.innerHTML = `<p class="loading">Lade Daten…</p>`;

    try {
      if (route.section === "archiv") {
        if (route.period) {
          await renderArchiveDetail(route.period, content);
        } else {
          await renderArchiveList(content);
        }
        return;
      }
      const data = await getLiveData();
      content.innerHTML = "";
      switch (route.livePage) {
        case "heute":     renderToday(data, content); break;
        case "woche":     renderWeek(data, content); break;
        case "statistik": renderStats(data, content); break;
        case "methodik":  renderMethodology(content); break;
      }
    } catch (e) {
      console.error(e);
      content.innerHTML = `<p class="error">Fehler beim Laden der Daten. Bitte später nochmal versuchen.</p>`;
    }
  }

  function navigate() {
    void renderRoute(parseRoute(location.hash));
  }

  window.addEventListener("hashchange", navigate);
  document.addEventListener("click", (e) => {
    const a = (e.target as HTMLElement).closest("a");
    if (!a || !a.getAttribute("href")?.startsWith("#")) return;
    // hashchange handles the rest after the browser updates location.hash
  });

  navigate();
}

void main();
```

- [ ] **Step 3: Add subnav styles**

In `site/src/style.css` append:

```css
#sub-nav {
  display: flex;
  gap: 0.5rem;
  border-bottom: 1px solid var(--border, #ddd);
  padding: 0.25rem 0.5rem;
  font-size: 0.9rem;
}
#sub-nav a {
  text-decoration: none;
  padding: 0.2rem 0.5rem;
  color: inherit;
}
#sub-nav a.active {
  border-bottom: 2px solid currentColor;
}
```

- [ ] **Step 4: Stub the new page renderers so the build passes**

Create `site/src/pages/archive-list.ts`:

```ts
export async function renderArchiveList(container: HTMLElement): Promise<void> {
  container.innerHTML = `<p>Archiv (TODO)</p>`;
}
```

Create `site/src/pages/archive-detail.ts`:

```ts
export async function renderArchiveDetail(period: string, container: HTMLElement): Promise<void> {
  container.innerHTML = `<p>Archiv ${period} (TODO)</p>`;
}
```

These stubs will be replaced in Tasks 13–14. Stubs prevent type-check failure on the import.

- [ ] **Step 5: Build + verify**

```bash
cd site && npm run build && npm run lint
```

Expected: build + lint clean.

- [ ] **Step 6: Commit**

```bash
git add site/index.html site/src/main.ts site/src/style.css site/src/pages/archive-list.ts site/src/pages/archive-detail.ts
git commit -m "feat(site): two-level Live/Archiv routing with hash router"
```

---

## Task 13: 12-month bar chart

**Files:**
- Create: `site/src/charts/monthsBar.ts`

- [ ] **Step 1: Implement chart helper**

Create `site/src/charts/monthsBar.ts`:

```ts
import { Chart, registerables } from "chart.js";
import type { MonthSummary } from "../archive.js";

Chart.register(...registerables);

export function renderMonthsBar(canvasId: string, months: MonthSummary[]): void {
  const canvas = document.getElementById(canvasId) as HTMLCanvasElement | null;
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const labels = months.map((m) => m.period);
  const onTime    = months.map((m) => m.on_time);
  const late      = months.map((m) => m.late);
  const cancelled = months.map((m) => m.cancelled);

  new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Pünktlich",    data: onTime,    backgroundColor: "#2e7d32", stack: "s" },
        { label: "Verspätet",    data: late,      backgroundColor: "#f9a825", stack: "s" },
        { label: "Ausgefallen",  data: cancelled, backgroundColor: "#c62828", stack: "s" },
      ],
    },
    options: {
      responsive: true,
      onClick: (_evt, elements) => {
        if (!elements.length) return;
        const i = elements[0].index;
        location.hash = `#/archiv/${labels[i]}`;
      },
      plugins: { legend: { position: "bottom" } },
      scales: {
        x: { stacked: true },
        y: { stacked: true, beginAtZero: true },
      },
    },
  });
}
```

- [ ] **Step 2: Build to type-check**

```bash
cd site && npm run build
```

Expected: build clean (file is unused yet — TypeScript only flags unused imports).

- [ ] **Step 3: Commit**

```bash
git add site/src/charts/monthsBar.ts
git commit -m "feat(site): 12-month stacked bar chart with click-to-navigate"
```

---

## Task 14: Archive list page

**Files:**
- Modify: `site/src/pages/archive-list.ts`

- [ ] **Step 1: Replace stub with real implementation**

Replace `site/src/pages/archive-list.ts`:

```ts
import { loadIndex } from "../archive.js";
import { renderMonthsBar } from "../charts/monthsBar.js";

function germanMonth(period: string): string {
  const [y, m] = period.split("-");
  const months = ["", "Januar", "Februar", "März", "April", "Mai", "Juni",
                  "Juli", "August", "September", "Oktober", "November", "Dezember"];
  return `${months[parseInt(m, 10)]} ${y}`;
}

export async function renderArchiveList(container: HTMLElement): Promise<void> {
  let idx;
  try {
    idx = await loadIndex();
  } catch {
    container.innerHTML = `<p class="error">Archivdaten nicht verfügbar</p>`;
    return;
  }

  const last12 = idx.months.slice(-12);

  container.innerHTML = `
    <h2>Archiv — S7 Baierbrunn</h2>
    <section class="months-overview">
      <h3>Letzte 12 Monate</h3>
      <div class="chart-container">
        <canvas id="chart-months-bar"></canvas>
      </div>
    </section>
    <section class="months-list">
      <h3>Alle Monate</h3>
      <ul class="month-links">
        ${idx.months.slice().reverse().map((m) => `
          <li>
            <a href="#/archiv/${m.period}">${germanMonth(m.period)}</a>
            <span class="month-summary">
              ${m.total} Züge · ${m.on_time} pünktlich · ${m.late} verspätet · ${m.cancelled} ausgefallen
              ${m.finalized ? "" : " <em>(läuft)</em>"}
            </span>
          </li>`).join("")}
      </ul>
    </section>
  `;

  renderMonthsBar("chart-months-bar", last12);
}
```

- [ ] **Step 2: Add 12-month strip on the week page**

Modify `site/src/pages/week.ts`. Add this import at the top:

```ts
import { loadIndex } from "../archive.js";
import { renderMonthsBar } from "../charts/monthsBar.js";
```

Change the function signature to async and append a chart container + render call. Replace the existing `export function renderWeek(...)` body with:

```ts
export async function renderWeek(data: S7Data, container: HTMLElement): Promise<void> {
  const agg = data.aggregates.last_7_days;

  container.innerHTML = `
    <h2>Letzte 7 Tage — S7 Baierbrunn</h2>
    <div class="summary-bar">
      <span class="summary-item summary-item--ok">✓ ${agg.on_time} pünktlich</span>
      <span class="summary-item summary-item--late">⏱ ${agg.late} verspätet</span>
      <span class="summary-item summary-item--cancelled">✕ ${agg.cancelled} ausgefallen</span>
      <span class="summary-item">Ø ${agg.avg_delay_min} min Verspätung</span>
    </div>
    <div class="chart-container">
      <h3>Richtung ${directionLabel("muenchen")}</h3>
      <canvas id="chart-week-muenchen"></canvas>
    </div>
    <div class="chart-container">
      <h3>Richtung ${directionLabel("wolfratshausen")}</h3>
      <canvas id="chart-week-wolfratshausen"></canvas>
    </div>
    <h3>Letzte 12 Monate</h3>
    <div class="chart-container">
      <canvas id="chart-week-months"></canvas>
    </div>
  `;

  renderDelayHistogram("chart-week-muenchen", last7DaysByDay(data, "muenchen"));
  renderDelayHistogram("chart-week-wolfratshausen", last7DaysByDay(data, "wolfratshausen"));

  try {
    const idx = await loadIndex();
    renderMonthsBar("chart-week-months", idx.months.slice(-12));
  } catch {
    const el = document.getElementById("chart-week-months")?.parentElement;
    if (el) el.innerHTML = `<p class="error">Monatsübersicht nicht verfügbar</p>`;
  }
}
```

`renderWeek` is now async — `main.ts` already `await`s page renderers via the dispatch in `renderRoute` (the `renderWeek(data, content)` call returns void; await it). Update the switch in `main.ts`:

```ts
        case "woche":     await renderWeek(data, content); break;
```

- [ ] **Step 3: Build + verify**

```bash
cd site && npm run build && npm run lint && npm test
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add site/src/pages/archive-list.ts site/src/pages/week.ts site/src/main.ts
git commit -m "feat(site): archive list page and 12-month strip on week view"
```

---

## Task 15: Daily-by-direction line chart

**Files:**
- Create: `site/src/charts/dailyByDirection.ts`

- [ ] **Step 1: Implement chart**

Create `site/src/charts/dailyByDirection.ts`:

```ts
import { Chart, registerables } from "chart.js";
import type { MonthlyArchive } from "../archive.js";

Chart.register(...registerables);

type DailyRow = MonthlyArchive["daily_by_direction"]["muenchen"][number];

function onTimePercent(d: DailyRow): number {
  return d.total > 0 ? (d.on_time / d.total) * 100 : 0;
}

export function renderDailyByDirection(canvasId: string, archive: MonthlyArchive): void {
  const canvas = document.getElementById(canvasId) as HTMLCanvasElement | null;
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const m = archive.daily_by_direction.muenchen;
  const w = archive.daily_by_direction.wolfratshausen;
  const labels = Array.from(new Set([...m.map(d => d.date), ...w.map(d => d.date)])).sort();

  const byDate = (rows: DailyRow[]) =>
    new Map(rows.map((r) => [r.date, r]));
  const mMap = byDate(m);
  const wMap = byDate(w);

  new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "München (Pünktlich %)",
          data: labels.map((d) => mMap.has(d) ? onTimePercent(mMap.get(d)!) : null),
          borderColor: "#1565c0",
          spanGaps: true,
        },
        {
          label: "Wolfratshausen (Pünktlich %)",
          data: labels.map((d) => wMap.has(d) ? onTimePercent(wMap.get(d)!) : null),
          borderColor: "#6a1b9a",
          spanGaps: true,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { position: "bottom" } },
      scales: { y: { beginAtZero: true, max: 100, ticks: { callback: (v) => `${v}%` } } },
    },
  });
}
```

- [ ] **Step 2: Build**

```bash
cd site && npm run build
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add site/src/charts/dailyByDirection.ts
git commit -m "feat(site): daily by-direction on-time line chart"
```

---

## Task 16: Archive detail page

**Files:**
- Modify: `site/src/pages/archive-detail.ts`

- [ ] **Step 1: Replace stub**

Replace `site/src/pages/archive-detail.ts`:

```ts
import { loadMonth } from "../archive.js";
import { escapeHtml } from "../data.js";
import { renderDailyByDirection } from "../charts/dailyByDirection.js";

function germanMonth(period: string): string {
  const [y, m] = period.split("-");
  const months = ["", "Januar", "Februar", "März", "April", "Mai", "Juni",
                  "Juli", "August", "September", "Oktober", "November", "Dezember"];
  return `${months[parseInt(m, 10)]} ${y}`;
}

function fmtTime(iso: string): string {
  return iso.slice(11, 16);
}

function archiveJsonUrl(period: string): string {
  return import.meta.env.DEV
    ? `../data/archive/${period}.json`
    : `${import.meta.env.BASE_URL}data/archive/${period}.json`;
}

export async function renderArchiveDetail(period: string, container: HTMLElement): Promise<void> {
  if (!/^\d{4}-\d{2}$/.test(period)) {
    container.innerHTML = `<p class="error">Ungültiger Zeitraum: ${escapeHtml(period)}</p>`;
    return;
  }

  let arc;
  try {
    arc = await loadMonth(period);
  } catch {
    container.innerHTML = `<p class="error">Archiv für ${escapeHtml(germanMonth(period))} nicht verfügbar</p>`;
    return;
  }

  const agg = arc.aggregates;

  container.innerHTML = `
    <h2>${germanMonth(period)} — S7 Baierbrunn ${arc.finalized ? "" : "<em>(läuft)</em>"}</h2>
    <div class="summary-bar">
      <span class="summary-item summary-item--ok">✓ ${agg.on_time} pünktlich</span>
      <span class="summary-item summary-item--late">⏱ ${agg.late} verspätet</span>
      <span class="summary-item summary-item--cancelled">✕ ${agg.cancelled} ausgefallen</span>
      <span class="summary-item">Ø ${agg.avg_delay_min} min Verspätung</span>
    </div>
    <h3>Pünktlichkeit pro Tag</h3>
    <div class="chart-container">
      <canvas id="chart-archive-daily"></canvas>
    </div>
    <h3>Alle Ankünfte (${arc.arrivals.length})</h3>
    <div class="archive-table-wrap">
      <table class="archive-table">
        <thead>
          <tr><th>Datum</th><th>Soll</th><th>Ist</th><th>Verspätung</th><th>Richtung</th><th>Status</th></tr>
        </thead>
        <tbody>
          ${arc.arrivals.map((a) => `
            <tr>
              <td>${a.scheduled_time.slice(0, 10)}</td>
              <td>${fmtTime(a.scheduled_time)}</td>
              <td>${a.actual_time ? fmtTime(a.actual_time) : "—"}</td>
              <td>${a.delay_minutes ?? 0} min</td>
              <td>${escapeHtml(a.direction)}</td>
              <td>${a.cancelled ? "Ausgefallen" : (a.delay_minutes && a.delay_minutes > 0 ? "Verspätet" : "Pünktlich")}</td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>
    <p class="data-age">
      <a href="${archiveJsonUrl(period)}" download>Rohdaten herunterladen (JSON)</a>
    </p>
  `;

  renderDailyByDirection("chart-archive-daily", arc);
}
```

- [ ] **Step 2: Add styling**

Append to `site/src/style.css`:

```css
.archive-table-wrap { overflow-x: auto; }
.archive-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.archive-table th, .archive-table td { padding: 0.25rem 0.5rem; border-bottom: 1px solid #eee; text-align: left; }
.archive-table th { background: #f5f5f5; }
.month-links { list-style: none; padding: 0; }
.month-links li { padding: 0.4rem 0; border-bottom: 1px solid #eee; }
.month-summary { color: #666; font-size: 0.85rem; margin-left: 0.5rem; }
```

- [ ] **Step 3: Build + lint + test**

```bash
cd site && npm run build && npm run lint && npm test
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add site/src/pages/archive-detail.ts site/src/style.css
git commit -m "feat(site): monthly archive detail page with table and daily chart"
```

---

## Task 17: Manual smoke test + CHANGELOG + version bump

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `fetcher/pyproject.toml`
- Modify: `site/package.json`

- [ ] **Step 1: Generate fixture archive locally**

```bash
cd /home/lima.guest/aiworkshop/s7bb/fetcher
uv run s7bb-export --archive 2026-04
uv run s7bb-export --archive 2026-05
uv run s7bb-export --archive-index
ls -la ../data/archive/
```

Expected: `2026-04.json`, `2026-05.json`, `index.json` exist; each contains the new fields (`finalized`, `daily`, `daily_by_direction`, `by_direction`).

- [ ] **Step 2: Spot-check JSON shape**

```bash
cd /home/lima.guest/aiworkshop/s7bb
python -c "import json; d=json.load(open('data/archive/index.json')); print(list(d), [m['period'] for m in d['months']])"
python -c "import json; d=json.load(open(sorted(__import__('pathlib').Path('data/archive').glob('2026-*.json'))[-1])); print(list(d), 'finalized=', d['finalized'])"
```

Expected: index has `months` listing periods; monthly file has `finalized`, `daily`, `daily_by_direction`.

- [ ] **Step 3: Run dev server, walk the UI**

```bash
cd site && npm run dev
```

Open `http://localhost:5173` and verify:

- Top nav shows `Live` / `Archiv`.
- Default route lands on `Live → Heute` (sub-nav visible).
- Click `Letzte 7 Tage` → 12-month bar chart renders below the day histograms.
- Click `Archiv` → list page with bar + month list.
- Click a month → detail page with summary, daily line chart, table, JSON download link.
- Bar-chart click on a month also navigates to the detail page.
- "Archivdaten nicht verfügbar" appears if `data/archive/index.json` is removed (rename it temporarily to test).

Stop dev server with Ctrl-C.

- [ ] **Step 4: Update CHANGELOG.md**

Add to `CHANGELOG.md` under `[Unreleased]`:

```markdown
### Added
- Monthly archive JSON files at `data/archive/YYYY-MM.json` with full row history, daily aggregates, and per-direction breakdowns.
- `data/archive/index.json` summarising all available months.
- Site `Archiv` tab with 12-month bar chart, monthly detail view, and raw-data download.
- CLI flags `s7bb-export --archive-index` and `--refinalize`.

### Changed
- Hourly export job now writes `latest.json` plus current-month archive plus archive index, and pushes everything in one commit.
- Site nav reorganized into top-level `Live` / `Archiv` tabs.

### BREAKING CHANGE
- `pusher.push_latest` renamed to `push_data` and now stages `data/archive/*.json` in addition to `data/latest.json`.
```

- [ ] **Step 5: Bump versions**

`fetcher/pyproject.toml`:
```toml
version = "0.2.0"
```

`site/package.json`:
```json
"version": "0.2.0",
```

- [ ] **Step 6: Run all tests + lint one final time**

```bash
cd /home/lima.guest/aiworkshop/s7bb/fetcher && uv run pytest && uv run ruff check src tests
cd /home/lima.guest/aiworkshop/s7bb/site    && npm run build && npm run lint && npm test
```

Expected: all green everywhere.

- [ ] **Step 7: Commit**

```bash
git add CHANGELOG.md fetcher/pyproject.toml site/package.json
git commit -m "chore(release): 0.2.0 — archive feature

See CHANGELOG.md for details. Includes breaking rename of push_latest → push_data."
```

---

## Self-Review Checklist (run after writing the plan)

**Spec coverage:**
- ✅ Decision 1 (raw + stats) — Tasks 3–4 (full rows + aggregates).
- ✅ Decision 2 (monthly flat files) — Tasks 3–6.
- ✅ Decision 3 (rolling rewrite + day-1 finalize) — Task 8.
- ✅ Decision 4 (latest.json unchanged) — `export_latest` untouched.
- ✅ Decision 5 (full rows + monthly + daily + by-direction daily) — Tasks 3–4.
- ✅ Decision 6 (`index.json`) — Task 6.
- ✅ Decision 7 (12-month strip + Archiv tab) — Tasks 12–16.
- ✅ Decision 8 (single hourly commit) — Task 7.
- ✅ Decision 9 (DB retention forever) — no code change required (already true).
- ✅ Atomic writes — Task 2.
- ✅ Per-step try/except in `_export_job` — Task 8.
- ✅ `--refinalize` and `--archive-index` CLI — Task 9.

**Type / signature consistency:**
- `export_monthly_archive(conn, year, month, out_path, finalized=False)` — used identically in Tasks 5, 8, 9.
- `export_archive_index(archive_dir, index_path)` — same signature in Tasks 6, 8, 9.
- `push_data(repo_path)` — same in Tasks 7, 8.
- `loadIndex()` / `loadMonth(period)` — same in Tasks 11, 14, 16.
- `MonthSummary.by_direction.muenchen` matches `_aggregate(...)` shape (no `missing` key — that field is `latest.json`-only).

**No placeholders:** every step has concrete code or a concrete command.
