# Terminus Health Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the `terminus_health` SQLite table as a top-level array
in `data/latest.json` so external observers (operators, downstream
monitors) can watch `zero_match_streak` per terminus EVA without SSH access.

**Architecture:** Single-file extension to `export_latest()` in the
fetcher's exporter. Query `terminus_health` ordered by `eva`, attach the
rows as `payload["terminus_health"]` before atomic-writing JSON. No
schema change, no site change, no archive change.

**Tech Stack:** Python 3.12, `sqlite3` stdlib, `pytest`, `ruff`. Project
layout: `fetcher/` (uv-managed). Spec at
`docs/superpowers/specs/2026-05-23-terminus-health-export.md`.

---

## File Structure

- Modify: `fetcher/src/s7bb_fetcher/exporter.py` — extend `export_latest()`.
- Modify: `fetcher/tests/test_exporter.py` — add two new tests.
- Modify: `CHANGELOG.md` — `[Unreleased]` `Added` entry.
- Commit (already on disk): `docs/superpowers/specs/2026-05-23-terminus-health-export.md`.
- Commit (already on disk): `docs/superpowers/plans/2026-05-23-terminus-health-export.md`.

No new files. No new modules. No new imports beyond what `exporter.py`
already pulls in (`sqlite3` is already wired through the `conn` arg).
Spec + plan files staged per CLAUDE.md "Plan files" rule.

---

### Task 1: Empty-table test (TDD — red)

**Files:**
- Modify: `fetcher/tests/test_exporter.py` — append new test at end of file.

- [ ] **Step 1: Add failing test for empty `terminus_health`**

Append to `fetcher/tests/test_exporter.py`:

```python
def test_terminus_health_empty_table(tmp_path):
    """latest.json must always carry a `terminus_health` key — empty list when
    the table has no rows (fresh DB, pre-first terminus fetch)."""
    conn = open_db(tmp_path / "test.db")
    out = tmp_path / "latest.json"
    export_latest(conn, out)
    data = json.loads(out.read_text())
    assert "terminus_health" in data
    assert data["terminus_health"] == []
```

- [ ] **Step 2: Run test — expect failure**

Run from `fetcher/`:

```bash
uv run pytest tests/test_exporter.py::test_terminus_health_empty_table -v
```

Expected: FAIL with `AssertionError: assert 'terminus_health' in {...}`.

---

### Task 2: Populated-table test (TDD — red)

**Files:**
- Modify: `fetcher/tests/test_exporter.py` — append second new test.

- [ ] **Step 1: Add failing test for populated `terminus_health`**

Append to `fetcher/tests/test_exporter.py`:

```python
def test_terminus_health_populated_sorted_by_eva(tmp_path):
    """`terminus_health` rows emitted as list[{eva,zero_match_streak,updated_at}],
    ordered by eva ASC for stable diffs in the s7bb-data repo."""
    conn = open_db(tmp_path / "test.db")
    conn.executemany(
        "INSERT INTO terminus_health (eva, zero_match_streak, updated_at) VALUES (?,?,?)",
        [
            ("8004158", 12, "2026-05-23T07:42:11+00:00"),
            ("8000261",  0, "2026-05-23T07:42:11+00:00"),
        ],
    )
    conn.commit()

    out = tmp_path / "latest.json"
    export_latest(conn, out)
    data = json.loads(out.read_text())

    assert data["terminus_health"] == [
        {"eva": "8000261", "zero_match_streak":  0, "updated_at": "2026-05-23T07:42:11+00:00"},
        {"eva": "8004158", "zero_match_streak": 12, "updated_at": "2026-05-23T07:42:11+00:00"},
    ]
```

- [ ] **Step 2: Run test — expect failure**

Run from `fetcher/`:

```bash
uv run pytest tests/test_exporter.py::test_terminus_health_populated_sorted_by_eva -v
```

Expected: FAIL with `KeyError: 'terminus_health'` (or `AssertionError`
depending on Python dict access path; either way: red).

---

### Task 3: Implement export (TDD — green)

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/exporter.py:138-155` — extend
  `export_latest()`.

- [ ] **Step 1: Add query + payload key**

In `fetcher/src/s7bb_fetcher/exporter.py`, replace the body of
`export_latest()` (currently lines 138-155) with:

```python
def export_latest(conn: sqlite3.Connection, out_path: Path, window_days: int = 7) -> None:
    rows = _query_window(conn, window_days)
    today_rows = _today_rows(rows)
    today_agg, week_agg, today_slots = _build_aggregates(rows, today_rows)

    health_cur = conn.execute(
        "SELECT eva, zero_match_streak, updated_at FROM terminus_health ORDER BY eva"
    )
    terminus_health = [
        {"eva": eva, "zero_match_streak": streak, "updated_at": updated_at}
        for eva, streak, updated_at in health_cur.fetchall()
    ]

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "station": "Baierbrunn",
        "line": "S7",
        "window_days": window_days,
        "arrivals": rows,
        "aggregates": {
            "today": today_agg,
            "last_7_days": week_agg,
        },
        "expected_slots": {"today": today_slots},
        "terminus_health": terminus_health,
    }
    _atomic_write_json(out_path, payload)
```

- [ ] **Step 2: Run both new tests — expect pass**

Run from `fetcher/`:

```bash
uv run pytest tests/test_exporter.py::test_terminus_health_empty_table tests/test_exporter.py::test_terminus_health_populated_sorted_by_eva -v
```

Expected: 2 passed.

- [ ] **Step 3: Run full exporter test file — guard regressions**

Run from `fetcher/`:

```bash
uv run pytest tests/test_exporter.py -v
```

Expected: all green (previously-passing tests still pass; the two new
ones pass).

- [ ] **Step 4: Run full fetcher test suite**

Run from `fetcher/`:

```bash
uv run pytest
```

Expected: all green.

- [ ] **Step 5: Lint**

Run from `fetcher/`:

```bash
uv run ruff check src tests
```

Expected: `All checks passed!`.

---

### Task 4: Changelog

**Files:**
- Modify: `CHANGELOG.md` — add `Added` entry under `[Unreleased]`.

- [ ] **Step 1: Add changelog entry**

Open `CHANGELOG.md`. Under `## [Unreleased]`, in (or create) an `### Added`
subsection, add:

```markdown
- Export `terminus_health` table as top-level array in `data/latest.json`
  for external observability of per-terminus `zero_match_streak`. (#52)
```

If no `[Unreleased]` block exists yet, create it at the top of the
changelog above the most recent released version, per Keep a Changelog.

- [ ] **Step 2: Verify markdown shape**

Run:

```bash
awk '/^## \[Unreleased\]/,/^## \[/' CHANGELOG.md
```

Expected: `[Unreleased]` block printed, containing the new bullet under
`### Added`.

---

### Task 5: Commit + push + PR

**Files:**
- All of the above.

- [ ] **Step 1: Stage exactly the changed files**

```bash
git add fetcher/src/s7bb_fetcher/exporter.py \
        fetcher/tests/test_exporter.py \
        CHANGELOG.md \
        docs/superpowers/specs/2026-05-23-terminus-health-export.md \
        docs/superpowers/plans/2026-05-23-terminus-health-export.md
```

(Plan + spec files **must** be committed per CLAUDE.md "Plan files"
rule — never leave untracked.)

- [ ] **Step 2: Commit (Conventional Commits)**

```bash
git commit -m "$(cat <<'EOF'
feat(exporter): expose terminus_health in latest.json

Adds top-level `terminus_health` array (eva, zero_match_streak,
updated_at) to data/latest.json so external observers can watch the
terminus matching canary without SSH access to the VM.

Empty table emits `[]`. Rows ordered by EVA for stable diffs in the
s7bb-data repo. No site, schema, or archive changes.

Closes #52
EOF
)"
```

- [ ] **Step 3: Push + open PR**

```bash
git push -u origin HEAD
gh pr create --title "feat(exporter): expose terminus_health in latest.json" \
  --body "$(cat <<'EOF'
## Summary
- Add top-level `terminus_health` array to `data/latest.json` (eva, zero_match_streak, updated_at).
- Empty table → `[]`. Sorted by EVA ASC.
- Closes #52.

## Test plan
- [ ] `uv run pytest` green in `fetcher/`.
- [ ] After deploy: `curl .../latest.json | jq .terminus_health` returns array.
EOF
)"
```

- [ ] **Step 4: Post-merge release**

After PR merges, follow CLAUDE.md "Post-merge release trigger" — this is
a `feat:`, so MINOR bump (e.g. 0.7.2 → 0.8.0). Run the full Release
procedure (pyproject.toml bump, `uv sync --no-dev`, CHANGELOG date stamp,
tag, GitHub Release).

---

## Self-Review

**Spec coverage:**
- "Top-level `terminus_health` key" → Task 3 (Step 1).
- "Sorted by eva ASC" → Task 2 (assertion), Task 3 (`ORDER BY eva`).
- "Empty table → `[]`" → Task 1 (assertion), Task 3 (list comprehension on empty fetchall).
- "Always present" → covered by Task 1 — unconditional payload key.
- "Unit test covers populated + empty" → Tasks 1 & 2.
- "No site / archive / migration change" → only `export_latest()` and its
  tests touched; `export_monthly_archive` and site code untouched.

**Placeholder scan:** no TBD, no "add appropriate X", no "similar to" — all
code blocks complete.

**Type consistency:** keys `eva` / `zero_match_streak` / `updated_at`
match across spec, test fixture INSERTs, SELECT, and dict comprehension.
Sort order (`ORDER BY eva`) matches the test's expected list ordering
(`8000261` before `8004158`).
