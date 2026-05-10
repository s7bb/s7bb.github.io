# Fix Public Times + Phantom Slots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the hourly fetcher from regenerating broken `latest.json` (times stuck on `:59/:19/:39` instead of public `:00/:20/:40`, plus phantom "keine Daten" rows outside the schedule). Fix the root cause in code so prior data backfills (PR #a8222a4, PR #8bb4ea7) actually stick.

**Architecture:**
- `parser.py`: shift DB-internal departure timestamp (`<dp pt=...>` / `<dp ct=...>`) by +1 minute so `scheduled_time` and `actual_time` reflect the public S7 timetable rather than the internal track-side time.
- `exporter.py`: replace cadence-inferred slot grid with observed-only slots; per-direction `missing` becomes 0. Matches the UX the v0.4.1 data-only PRs were trying to enforce.
- One-shot SQLite migration script: shift historical `arrivals.scheduled_time`/`actual_time` by +1 minute, guarded by `PRAGMA user_version` so it cannot run twice.
- Fixtures: rename existing fixture into a `legacy_` variant kept for direction tests; add a new `plan_real.xml` mirroring real DB convention (`<dp pt="...59">`) so parser tests assert public-time output.

**Tech Stack:** Python 3.13, lxml, SQLite, pytest, ruff. No site/JS changes (site already unions observed times with `expected_slots`, so observed-only feeds work without TS edits).

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `fetcher/src/s7bb_fetcher/parser.py` | Modify | Add `_PUBLIC_OFFSET = timedelta(minutes=1)`; apply to `scheduled_dt` and `actual_dt`. |
| `fetcher/src/s7bb_fetcher/exporter.py` | Modify | Replace `_expected_slots(...)` body with observed-times-only return; rewrite `_direction_aggregate` so `missing == 0`. |
| `fetcher/scripts/migrate_shift_public_times.py` | Create | One-shot, idempotent migration shifting historical rows by +1 min. Guarded by `PRAGMA user_version`. |
| `fetcher/tests/fixtures/plan_real.xml` | Create | Plan XML mirroring real DB convention (dp pt ends `:59`). |
| `fetcher/tests/fixtures/changes_real.xml` | Create | Matching changes XML with ct ending `:00` (1 min late from internal :59). |
| `fetcher/tests/test_parser.py` | Modify | Add public-time assertion test using new fixtures. |
| `fetcher/tests/test_exporter.py` | Modify | Replace `test_missing_slot_detected` and `test_expected_slots_cadence` with observed-only equivalents; assert `missing == 0`. |
| `fetcher/tests/test_migrate_shift_public_times.py` | Create | Unit test for migration: pre-migration `:59`, post-migration `:00`, second run is no-op. |
| `CHANGELOG.md` | Modify | Add `[Unreleased]` Fixed entries; bump to `[0.4.2]` at release task. |
| `fetcher/pyproject.toml` | Modify | Bump version `0.4.1` → `0.4.2`. |

---

## Task 1: Add public-time fixture pair

**Files:**
- Create: `fetcher/tests/fixtures/plan_real.xml`
- Create: `fetcher/tests/fixtures/changes_real.xml`

- [ ] **Step 1: Create `plan_real.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<timetable station="Baierbrunn" eva="8000781">
  <s id="trip-S7-real-001">
    <tl f="S" t="p" o="800725" c="S" n="6800"/>
    <ar pt="2605051258" pp="1" l="S7" ppth="Wolfratshausen|Icking|Ebenhausen-Schäftlarn|Hohenschäftlarn"/>
    <dp pt="2605051259" pp="1" l="S7" ppth="Buchenhain|Höllriegelskreuth|Pullach|Großhesselohe Isartalbahnhof|München-Solln|München Siemenswerke|München-Mittersendling|München Harras|München Heimeranplatz|München Donnersbergerbrücke|München Hbf Gl.27-36"/>
  </s>
  <s id="trip-S7-real-002">
    <tl f="S" t="p" o="800725" c="S" n="6801"/>
    <ar pt="2605051318" pp="2" l="S7" ppth="München Hbf Gl.27-36|München Donnersbergerbrücke|München Heimeranplatz|München Harras|München-Mittersendling|München Siemenswerke|München-Solln|Großhesselohe Isartalbahnhof|Pullach|Höllriegelskreuth|Buchenhain"/>
    <dp pt="2605051319" pp="2" l="S7" ppth="Hohenschäftlarn|Ebenhausen-Schäftlarn|Icking|Wolfratshausen"/>
  </s>
</timetable>
```

- [ ] **Step 2: Create `changes_real.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<timetable station="Baierbrunn" eva="8000781">
  <s id="trip-S7-real-001">
    <dp ct="2605051300" cs="p"/>
  </s>
</timetable>
```

(`ct=2605051300` = internal arrival 13:00 Berlin = 1 minute late vs public 13:00.)

- [ ] **Step 3: Commit**

```bash
git add fetcher/tests/fixtures/plan_real.xml fetcher/tests/fixtures/changes_real.xml
git commit -m "test(parser): add real-convention DB Timetables fixture pair"
```

---

## Task 2: Failing parser test for public-time shift

**Files:**
- Modify: `fetcher/tests/test_parser.py`

- [ ] **Step 1: Append failing test**

Append at end of `fetcher/tests/test_parser.py`:

```python
def test_scheduled_time_is_public_departure():
    """DB internal `dp pt` is one minute before the public timetable.

    Real-world `<dp pt="2605051259">` (Berlin local) corresponds to the
    public 13:00 Berlin departure. Parser must surface 13:00 (UTC 11:00),
    not 12:59 (UTC 10:59).
    """
    records = parse_timetable(_load("plan_real.xml"), _load("changes_real.xml"))
    rec = next(r for r in records if r.train_id == "trip-S7-real-001")
    assert rec.scheduled_time == "2026-05-05T11:00:00+00:00"


def test_actual_time_is_public_departure():
    """ct=`2605051300` (internal 13:00) is one minute late vs public 13:00.

    Public departure shifts to 13:01 → UTC 11:01; delay is +1 minute.
    """
    records = parse_timetable(_load("plan_real.xml"), _load("changes_real.xml"))
    rec = next(r for r in records if r.train_id == "trip-S7-real-001")
    assert rec.actual_time == "2026-05-05T11:01:00+00:00"
    assert rec.delay_minutes == 1
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd fetcher
uv run pytest tests/test_parser.py::test_scheduled_time_is_public_departure tests/test_parser.py::test_actual_time_is_public_departure -v
```

Expected: both FAIL with assertion error showing `'2026-05-05T10:59:00+00:00' != '2026-05-05T11:00:00+00:00'`.

---

## Task 3: Implement public-time shift in parser

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/parser.py`

- [ ] **Step 1: Add offset constant**

In `fetcher/src/s7bb_fetcher/parser.py`, replace the imports + module constants block:

```python
"""Parse DB Timetables XML into ArrivalRecord dataclasses."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from lxml import etree

_DE_TZ = ZoneInfo("Europe/Berlin")

# DB Timetables emits the internal track-side timestamp on <dp pt=...> /
# <dp ct=...>, which is one minute before the published S7 timetable at
# Baierbrunn. Shift here so consumers see the time on the public board.
_PUBLIC_OFFSET = timedelta(minutes=1)
```

- [ ] **Step 2: Apply shift in `_parse_db_time`**

Replace the `_parse_db_time` function with:

```python
def _parse_db_time(raw: str) -> datetime:
    """DB time format: YYMMDDHHMM (Europe/Berlin local) → public-time UTC datetime."""
    local = datetime.strptime(raw, "%y%m%d%H%M").replace(tzinfo=_DE_TZ)
    return (local + _PUBLIC_OFFSET).astimezone(UTC)
```

- [ ] **Step 3: Run new tests, expect pass**

```bash
cd fetcher
uv run pytest tests/test_parser.py::test_scheduled_time_is_public_departure tests/test_parser.py::test_actual_time_is_public_departure -v
```

Expected: both PASS.

- [ ] **Step 4: Run full parser suite**

```bash
cd fetcher
uv run pytest tests/test_parser.py -v
```

Expected: all PASS. Existing fixture (`plan.xml`) uses `dp pt="2605051201"` so the legacy `test_on_time_record` etc. still pass — they only assert delay/cancellation/direction, never the absolute timestamp value. Verify.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/parser.py fetcher/tests/test_parser.py
git commit -m "fix(parser): shift DB internal time +1 min to public S7 departure"
```

---

## Task 4: Failing exporter test for observed-only slots

**Files:**
- Modify: `fetcher/tests/test_exporter.py`

- [ ] **Step 1: Replace `test_missing_slot_detected`**

In `fetcher/tests/test_exporter.py`, replace the body of `test_missing_slot_detected` (currently lines 55–62) with:

```python
def test_no_phantom_missing_slots(populated_db, tmp_path):
    """expected_slots is observed-only — `missing` is always 0.

    The previous cadence-inferred grid produced phantom "keine Daten" rows
    in operational gaps and outside service hours. PR8bb4ea7 patched data
    after-the-fact; this test locks the code-level behaviour in.
    """
    out = tmp_path / "latest.json"
    export_latest(populated_db, out)
    data = json.loads(out.read_text())

    w = data["aggregates"]["today"]["by_direction"]["wolfratshausen"]
    m = data["aggregates"]["today"]["by_direction"]["muenchen"]
    assert w["missing"] == 0
    assert m["missing"] == 0
```

- [ ] **Step 2: Replace `test_expected_slots_cadence`**

Replace the body of `test_expected_slots_cadence` (currently lines 85–96) with:

```python
def test_expected_slots_observed_only():
    """_expected_slots returns each observed scheduled_time exactly once, sorted."""
    rows = [
        {"scheduled_time": "2026-05-05T10:40:00+00:00"},
        {"scheduled_time": "2026-05-05T10:00:00+00:00"},
        {"scheduled_time": "2026-05-05T10:20:00+00:00"},
        {"scheduled_time": "2026-05-05T10:00:00+00:00"},  # duplicate
    ]
    slots = _expected_slots(rows)
    assert slots == [
        "2026-05-05T10:00:00+00:00",
        "2026-05-05T10:20:00+00:00",
        "2026-05-05T10:40:00+00:00",
    ]


def test_expected_slots_skips_phantom_gap_outside_window():
    """A 4-hour gap between observations does not produce phantom slots."""
    rows = [
        {"scheduled_time": "2026-05-05T05:00:00+00:00"},
        {"scheduled_time": "2026-05-05T09:00:00+00:00"},
    ]
    slots = _expected_slots(rows)
    assert slots == [
        "2026-05-05T05:00:00+00:00",
        "2026-05-05T09:00:00+00:00",
    ]
```

- [ ] **Step 3: Run new tests, expect failure**

```bash
cd fetcher
uv run pytest tests/test_exporter.py::test_no_phantom_missing_slots tests/test_exporter.py::test_expected_slots_observed_only tests/test_exporter.py::test_expected_slots_skips_phantom_gap_outside_window -v
```

Expected:
- `test_no_phantom_missing_slots`: FAIL — Wolfratshausen `missing` is currently `>= 1` (cadence inferred a 10:33 slot).
- `test_expected_slots_observed_only`: FAIL — current cadence inference returns 3 slots aligned to 20-min cycle, not deduped raw observations.
- `test_expected_slots_skips_phantom_gap_outside_window`: FAIL — current code generates ~13 phantom 20-min slots between 05:00 and 09:00.

---

## Task 5: Implement observed-only slots in exporter

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/exporter.py`

- [ ] **Step 1: Replace `_expected_slots`**

In `fetcher/src/s7bb_fetcher/exporter.py`, replace the entire `_expected_slots` function (currently lines 75–110) with:

```python
def _expected_slots(rows: list[dict]) -> list[str]:
    """Return observed `scheduled_time` values, deduped and sorted.

    Earlier versions inferred a 20-min cadence grid between first/last
    observation. That produced phantom slots in operational gaps and
    outside service hours, surfacing as "keine Daten" rows in the today
    view (see PR8bb4ea7). The site now treats every emitted slot as a
    real expected train and unions them with the observed set, so we
    must only emit slots that correspond to a real arrival.
    """
    return sorted({r["scheduled_time"] for r in rows})
```

- [ ] **Step 2: Drop the now-unused `Counter` import**

In the imports block at the top of `fetcher/src/s7bb_fetcher/exporter.py`, change:

```python
from collections import Counter
```

to remove that line entirely (no other consumer remains).

- [ ] **Step 3: Run failing tests, expect pass**

```bash
cd fetcher
uv run pytest tests/test_exporter.py::test_no_phantom_missing_slots tests/test_exporter.py::test_expected_slots_observed_only tests/test_exporter.py::test_expected_slots_skips_phantom_gap_outside_window -v
```

Expected: all PASS.

- [ ] **Step 4: Run full exporter suite**

```bash
cd fetcher
uv run pytest tests/test_exporter.py -v
```

Expected: all PASS. (`test_no_missing_when_all_present` still passes — observed-only also yields `missing == 0`.)

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/exporter.py fetcher/tests/test_exporter.py
git commit -m "fix(exporter): emit only observed scheduled times, drop cadence-inferred phantoms"
```

---

## Task 6: Failing test for one-shot DB migration

**Files:**
- Create: `fetcher/tests/test_migrate_shift_public_times.py`

- [ ] **Step 1: Write test**

Create `fetcher/tests/test_migrate_shift_public_times.py`:

```python
import sqlite3
from pathlib import Path

from s7bb_fetcher.parser import ArrivalRecord
from s7bb_fetcher.storage import open_db, upsert_records


def _make(tid: str, scheduled: str, actual: str | None = None) -> ArrivalRecord:
    return ArrivalRecord(
        train_id=tid, line="S7", station="Baierbrunn",
        direction="Wolfratshausen", direction_bucket="wolfratshausen",
        scheduled_time=scheduled,
        actual_time=actual if actual is not None else scheduled,
        delay_minutes=0, cancelled=False, reason=None,
    )


def test_migration_shifts_scheduled_and_actual_by_one_minute(tmp_path: Path):
    from scripts.migrate_shift_public_times import run as migrate

    db = tmp_path / "s7bb.db"
    conn = open_db(db)
    upsert_records(conn, [
        _make("a", "2026-05-05T10:59:00+00:00"),
        _make("b", "2026-05-05T11:19:00+00:00", actual="2026-05-05T11:21:00+00:00"),
    ])
    conn.close()

    migrate(db)

    conn = sqlite3.connect(db)
    rows = sorted(conn.execute(
        "SELECT train_id, scheduled_time, actual_time FROM arrivals"
    ).fetchall())
    assert rows == [
        ("a", "2026-05-05T11:00:00+00:00", "2026-05-05T11:00:00+00:00"),
        ("b", "2026-05-05T11:20:00+00:00", "2026-05-05T11:22:00+00:00"),
    ]


def test_migration_preserves_null_actual_time(tmp_path: Path):
    from scripts.migrate_shift_public_times import run as migrate

    db = tmp_path / "s7bb.db"
    conn = open_db(db)
    cancelled = ArrivalRecord(
        train_id="c", line="S7", station="Baierbrunn",
        direction="Wolfratshausen", direction_bucket="wolfratshausen",
        scheduled_time="2026-05-05T10:59:00+00:00",
        actual_time=None,
        delay_minutes=None, cancelled=True, reason="STOERUNG",
    )
    upsert_records(conn, [cancelled])
    conn.close()

    migrate(db)

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT scheduled_time, actual_time FROM arrivals WHERE train_id='c'"
    ).fetchone()
    assert row == ("2026-05-05T11:00:00+00:00", None)


def test_migration_is_idempotent(tmp_path: Path):
    from scripts.migrate_shift_public_times import run as migrate

    db = tmp_path / "s7bb.db"
    conn = open_db(db)
    upsert_records(conn, [_make("a", "2026-05-05T10:59:00+00:00")])
    conn.close()

    migrate(db)
    migrate(db)  # second run must be a no-op

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT scheduled_time FROM arrivals WHERE train_id='a'"
    ).fetchone()
    assert row == ("2026-05-05T11:00:00+00:00",)


def test_migration_sets_user_version(tmp_path: Path):
    from scripts.migrate_shift_public_times import run as migrate

    db = tmp_path / "s7bb.db"
    conn = open_db(db)
    upsert_records(conn, [_make("a", "2026-05-05T10:59:00+00:00")])
    conn.close()

    migrate(db)

    conn = sqlite3.connect(db)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 1
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd fetcher
uv run pytest tests/test_migrate_shift_public_times.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'scripts'`.

---

## Task 7: Implement one-shot DB migration

**Files:**
- Create: `fetcher/scripts/__init__.py`
- Create: `fetcher/scripts/migrate_shift_public_times.py`

- [ ] **Step 1: Create empty `__init__.py`**

Create `fetcher/scripts/__init__.py` with empty contents (so pytest can import `scripts.*`).

- [ ] **Step 2: Implement migration**

Create `fetcher/scripts/migrate_shift_public_times.py`:

```python
"""One-shot migration: shift `arrivals.scheduled_time` / `actual_time` by +1 minute.

Background: PR a8222a4 backfilled `data/latest.json` so the deployed times
matched the public S7 board, but the producing fetcher (parser.py) was
unchanged, so the next hourly export overwrote the file with the old
`:59` / `:19` / `:39` values. Once the parser fix lands (this release),
historical SQLite rows still carry the old internal-time convention.
This script rewrites them once.

Guarded by `PRAGMA user_version`. Schema version 0 → run migration → 1.
Subsequent runs are no-ops.

Usage on the VM:

    cd fetcher
    uv run python -m scripts.migrate_shift_public_times \\
        --db /path/to/data/s7bb.db
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

_SCHEMA_VERSION = 1
_OFFSET = timedelta(minutes=1)


def _shift(iso: str | None) -> str | None:
    if iso is None:
        return None
    return (datetime.fromisoformat(iso) + _OFFSET).isoformat()


def run(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current >= _SCHEMA_VERSION:
            return  # already migrated

        rows = conn.execute(
            "SELECT rowid, scheduled_time, actual_time FROM arrivals"
        ).fetchall()
        with conn:
            for rowid, scheduled, actual in rows:
                conn.execute(
                    "UPDATE arrivals SET scheduled_time=?, actual_time=? WHERE rowid=?",
                    (_shift(scheduled), _shift(actual), rowid),
                )
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
    finally:
        conn.close()


def _cli() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, required=True, help="Path to s7bb.db")
    args = p.parse_args()
    run(args.db)


if __name__ == "__main__":
    _cli()
```

- [ ] **Step 3: Run migration tests, expect pass**

```bash
cd fetcher
uv run pytest tests/test_migrate_shift_public_times.py -v
```

Expected: all 4 PASS.

- [ ] **Step 4: Commit**

```bash
git add fetcher/scripts/__init__.py fetcher/scripts/migrate_shift_public_times.py fetcher/tests/test_migrate_shift_public_times.py
git commit -m "feat(scripts): one-shot migration shifting historical arrivals to public time"
```

---

## Task 8: Full suite + lint + type-check

**Files:** none (verification only).

- [ ] **Step 1: Full pytest**

```bash
cd fetcher
uv run pytest
```

Expected: all PASS.

- [ ] **Step 2: Ruff**

```bash
cd fetcher
uv run ruff check src tests scripts
```

Expected: no errors.

- [ ] **Step 3: Site build smoke test (no code change but verify import path still works)**

```bash
cd site
npm run build
```

Expected: build succeeds. (No TS edits in this plan; site already handles observed-only slots correctly.)

---

## Task 9: CHANGELOG + version bump (release per CLAUDE.md PATCH rule)

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `fetcher/pyproject.toml`

- [ ] **Step 1: Add `[Unreleased]` Fixed entries**

In `CHANGELOG.md`, under the `[Unreleased]` heading, add:

```markdown
### Fixed

- Parser now shifts DB Timetables internal departure timestamp by +1 minute so `scheduled_time` and `actual_time` reflect the public S7 board (`:00 / :20 / :40` instead of `:59 / :19 / :39`). Prior backfill of `latest.json` was being overwritten on every hourly export.
- Exporter no longer infers a 20-minute cadence grid between first/last observed train, eliminating the phantom "keine Daten" rows in the today view that appeared outside actual service hours and in operational gaps. Per-direction `missing` counter is consequently always `0`.
- One-shot `scripts/migrate_shift_public_times.py` corrects historical SQLite rows so they match the new public-time convention.
```

- [ ] **Step 2: Rename `[Unreleased]` to `[0.4.2] - 2026-05-10`**

In `CHANGELOG.md`, replace `## [Unreleased]` with `## [0.4.2] - 2026-05-10` and re-add an empty `## [Unreleased]` heading above it.

- [ ] **Step 3: Bump pyproject version**

In `fetcher/pyproject.toml` change the `version` field from `0.4.1` to `0.4.2`.

- [ ] **Step 4: Verify version applied**

```bash
grep '^version' fetcher/pyproject.toml
```

Expected: `version = "0.4.2"`.

- [ ] **Step 5: Release commit**

```bash
git add CHANGELOG.md fetcher/pyproject.toml
git commit -m "chore(release): 0.4.2"
git tag v0.4.2
```

(Tag push deferred — explicitly held until VM rollout in Task 10.)

---

## Task 10: VM rollout (manual, runs on production VM only)

**Files:** none on disk; this is a deployment runbook.

- [ ] **Step 1: Push branch + tag**

```bash
git push origin HEAD
git push origin v0.4.2
```

- [ ] **Step 2: SSH to VM, pull, rebuild fetcher container**

```bash
ssh <vm>
cd /path/to/s7bb
git pull --ff-only
docker compose build s7bb-fetcher
```

- [ ] **Step 3: Stop the scheduler so it cannot run mid-migration**

```bash
docker compose stop s7bb-fetcher
```

- [ ] **Step 4: Run one-shot migration against live DB**

```bash
docker compose run --rm s7bb-fetcher \
  python -m scripts.migrate_shift_public_times --db /data/s7bb.db
```

Expected: completes silently. Re-running prints nothing and changes nothing (idempotent — verify by running twice).

- [ ] **Step 5: Sanity-check `user_version`**

```bash
docker compose run --rm s7bb-fetcher \
  sqlite3 /data/s7bb.db 'PRAGMA user_version;'
```

Expected output: `1`.

- [ ] **Step 6: Restart scheduler**

```bash
docker compose start s7bb-fetcher
```

- [ ] **Step 7: Force one immediate export + push (don't wait for the hourly cron)**

```bash
docker compose exec s7bb-fetcher uv run s7bb-export
docker compose exec s7bb-fetcher git -C /repo push  # or whatever existing push helper is wired
```

(If a separate `s7bb-push` entrypoint exists, use it; otherwise the next hourly cycle will publish.)

- [ ] **Step 8: Verify live site**

```bash
curl -s https://s7bb.github.io/data/latest.json | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
    print('scheduled minute set:', sorted({a['scheduled_time'][14:16] for a in d['arrivals']})); \
    print('today missing m:', d['aggregates']['today']['by_direction']['muenchen']['missing']); \
    print('today missing w:', d['aggregates']['today']['by_direction']['wolfratshausen']['missing'])"
```

Expected: minute set is `{'00', '20', '40'}` (or local-time equivalent in UTC depending on DST), and both `missing` counters are `0`.

---

## Self-Review

**Spec coverage:**
- "Times still on `:59`" → Tasks 1–3 (fixture, failing test, parser shift) + Task 7 (historical SQLite fix) + Task 10 (rollout).
- "Rows with missing data outside the schedule" → Tasks 4–5 (failing exporter test, observed-only slots).
- Per CLAUDE.md "post-merge release trigger" rule for `fix:` PRs → Task 9 cuts 0.4.2 (PATCH).
- All five new test functions reference functions/imports defined in the implementation tasks (`_expected_slots`, `parse_timetable`, `scripts.migrate_shift_public_times.run`).

**Placeholder scan:** none.

**Type/name consistency:**
- `_PUBLIC_OFFSET` referenced in Task 3 step 1 + step 2.
- `scripts.migrate_shift_public_times.run` matches `from scripts.migrate_shift_public_times import run as migrate` in Task 6 tests.
- `_SCHEMA_VERSION = 1` matches `assert version == 1` in Task 6.
- `_expected_slots` signature `list[dict] -> list[str]` unchanged from current code, only body is rewritten (Task 5 step 1) — `_direction_aggregate(... expected_slots)` already returns `missing = max(0, len(expected) - len(rows))`; with observed-only slots this collapses to `max(0, total - total) = 0`, no rewrite needed there. Verified.

**Risk notes for the executor:**
- The legacy fixture `plan.xml` keeps `dp pt="2605051201"` (one minute *after* the round minute, not before). Existing tests don't assert absolute times, so they remain green after the +1 shift, but anyone reading the fixture later may be confused. If desired, a follow-up PR can rename `plan.xml` → `plan_legacy.xml` and migrate remaining tests onto `plan_real.xml`. Out of scope here.
- The migration touches every `arrivals` row. On the production VM that may be ~thousands of rows; trivial for SQLite. If row count ever grows large, swap the per-row UPDATE for a single SQL `UPDATE arrivals SET scheduled_time = strftime(...)`. Not needed at current scale.
