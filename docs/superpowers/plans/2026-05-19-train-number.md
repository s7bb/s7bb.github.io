# Train Number Inclusion (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture the DB Timetables public train number (`<tl n>`, Zugnummer) going forward and flow it through parser → SQLite → `latest.json`/`archive/*.json` → the site TypeScript contract, with no UI rendering.

**Architecture:** No new API calls, files, or UI. The `<tl>` element is already fetched in the plan XML but discarded by the parser. We add one nullable `train_number` field that rides the existing data path. Upsert uses a fill-only `COALESCE` so a re-observation lacking `<tl n>` never regresses a captured value to `NULL`. Pre-existing rows stay `NULL` (Phase 1 only; retroactive backfill is impossible — the plan endpoint 404s on past dates and the number is not in the opaque `train_id`).

**Tech Stack:** Python 3.11 (lxml, sqlite3, pytest, ruff), TypeScript (Vite, vitest).

**Spec:** `docs/superpowers/specs/2026-05-19-train-number-design.md`

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `fetcher/src/s7bb_fetcher/parser.py` | XML → `ArrivalRecord` | Add `train_number` dataclass field (last, `= None`); extract `<tl n>` defensively |
| `fetcher/src/s7bb_fetcher/storage.py` | SQLite persistence | Add `train_number TEXT` to `SCHEMA`; add `_migrate` branch; add fill-only `COALESCE` upsert |
| `fetcher/src/s7bb_fetcher/exporter.py` | SQLite → JSON | Add `train_number` to both hardcoded SELECT column lists |
| `fetcher/tests/fixtures/plan.xml` | Parser test fixture | Add one S7 `<s>` that **lacks** `<tl>` (missing-`<tl>` branch coverage) |
| `fetcher/tests/test_parser.py` | Parser tests | Assert `<tl n>` parsed; assert no-`<tl>` stop → `None` and still emitted |
| `fetcher/tests/test_storage.py` | Storage tests | Round-trip column; migration on pre-column DB; fill-only `COALESCE` upsert |
| `fetcher/tests/test_exporter.py` | Exporter tests | Assert key present in `latest.json` + monthly archive `arrivals[]` |
| `site/src/data.ts` | JS/TS data contract | Add `train_number?: string \| null` to `Arrival` |
| `site/src/data.test.ts` | Site data tests | Add `train_number: null` to the `arrival()` default builder (explicitness only) |

`site/src/archive.test.ts` was checked — it constructs **no** typed `Arrival` literals (grep for `train_id`/`Arrival` literal returned nothing), so it needs no edit. It is intentionally absent from the task list.

---

### Task 1: Parser — capture `<tl n>` into `ArrivalRecord`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/parser.py` (dataclass `ArrivalRecord` lines 12-23; extraction between the skip guards at `parser.py:86-87` and the `records.append` at `parser.py:130-141`)
- Modify: `fetcher/tests/fixtures/plan.xml` (currently 3 S7 `<s>`, all with `<tl n>`)
- Test: `fetcher/tests/test_parser.py`

#### Step 1.1 — Add the missing-`<tl>` fixture stop

- [ ] **Add a 4th S7 `<s>` with no `<tl>` element to `fetcher/tests/fixtures/plan.xml`.**

This is the *inverse* of the happy path. The existing three stops already carry `<tl ... n="676x"/>`, so the `<tl n>` → value branch is already exercised. We need a fixture for the `train_number is None` branch (relief/extra trains that lack `<tl>`). The stop has a valid S7 `<dp>` (so it is not skipped) and a Wolfratshausen `ppth` (so `direction_bucket` is a valid value and `test_records_have_direction_bucket` still passes). No matching `<s id>` exists in any `changes_*.xml`, so it is treated as on-time — irrelevant to this test.

Insert this block immediately before the closing `</timetable>` in `fetcher/tests/fixtures/plan.xml`:

```xml
  <s id="trip-S7-004-2605051330">
    <ar pt="2605051330" pp="1" l="S7" ppth="Wolfratshausen|Icking|Ebenhausen-Schäftlarn|Hohenschäftlarn"/>
    <dp pt="2605051331" pp="1" l="S7" ppth="Buchenhain|Höllriegelskreuth|Pullach|Großhesselohe Isartalbahnhof|München-Solln|München Siemenswerke|München-Mittersendling|München Harras|München Heimeranplatz|München Donnersbergerbrücke|München Hbf Gl.27-36"/>
  </s>
```

(Note: this `<dp ppth>` terminates at München, so its `direction_bucket` is `"muenchen"` — a valid bucket. Intentionally no `<tl>` child.)

#### Step 1.2 — Write the failing tests

- [ ] **Append these two tests to `fetcher/tests/test_parser.py`:**

```python
def test_train_number_parsed_from_tl():
    records = parse_timetable(_load("plan.xml"), _load("changes_empty.xml"))
    r = next(r for r in records if r.train_id == "trip-S7-002-2605051230")
    assert r.train_number == "6762"


def test_missing_tl_yields_none_and_row_still_emitted():
    records = parse_timetable(_load("plan.xml"), _load("changes_empty.xml"))
    no_tl = next(
        (r for r in records if r.train_id == "trip-S7-004-2605051330"), None
    )
    assert no_tl is not None, "stop without <tl> must still be emitted"
    assert no_tl.train_number is None
```

`trip-S7-002-2605051230` carries `<tl ... n="6762"/>` (verified in the current fixture). `trip-S7-004-2605051330` is the no-`<tl>` stop added in Step 1.1.

#### Step 1.3 — Run the tests, verify they fail

- [ ] **Run:**

```bash
cd fetcher && uv run pytest tests/test_parser.py::test_train_number_parsed_from_tl tests/test_parser.py::test_missing_tl_yields_none_and_row_still_emitted -v
```

Expected: FAIL — `AttributeError: 'ArrivalRecord' object has no attribute 'train_number'`.

#### Step 1.4 — Add the dataclass field

- [ ] **In `fetcher/src/s7bb_fetcher/parser.py`, add `train_number` as the LAST field of `ArrivalRecord`, with a `= None` default.**

Placement is load-bearing, not cosmetic: a Python dataclass field without a default cannot follow one with a default. Every existing field (`train_id` … `reason`) has no default. Placing a defaulted `train_number` mid-class raises `TypeError` **at import** → the fetcher cannot start → zero records for the whole outage. The `= None` default is required because every `ArrivalRecord(...)` construction is keyword-based and no existing call site passes `train_number`.

Change (lines 12-23):

```python
@dataclass
class ArrivalRecord:
    train_id: str
    line: str
    station: str
    direction: str           # raw terminus from DB API
    direction_bucket: str    # "muenchen" | "wolfratshausen" | "unknown"
    scheduled_time: str      # ISO8601 UTC
    actual_time: str | None  # ISO8601 UTC, None if cancelled
    delay_minutes: int | None
    cancelled: bool
    reason: str | None
    train_number: str | None = None
```

#### Step 1.5 — Extract `<tl n>` defensively and pass it to the constructor

- [ ] **In `parse_timetable`, between the `pt_raw` skip guard and `scheduled_dt = _parse_db_time(pt_raw)`, add the guarded extraction.**

It must go **after** the early-`continue` skip guards (`parser.py:77-87`) so dropped stops do not waste a `find`, and **before** `records.append(...)`. Do **not** chain `tl.get("n").strip()`: a present `<tl>` lacking `n`, or an absent `<tl>`, would `AttributeError` and abort `parse_timetable` for the entire fetch cycle (no records that cycle = data loss).

Locate this block (currently `parser.py:85-89`):

```python
        pt_raw = dp.get("pt")
        if not pt_raw:
            continue

        scheduled_dt = _parse_db_time(pt_raw)
```

Replace it with:

```python
        pt_raw = dp.get("pt")
        if not pt_raw:
            continue

        tl = stop.find("tl")
        n = tl.get("n") if tl is not None else None
        train_number = n.strip() if n and n.strip() else None

        scheduled_dt = _parse_db_time(pt_raw)
```

- [ ] **Pass `train_number` into the `ArrivalRecord(...)` constructor.**

Locate the `records.append(ArrivalRecord(...))` call (currently `parser.py:130-141`) and add `train_number=train_number` as the last argument:

```python
        records.append(ArrivalRecord(
            train_id=sid,
            line="S7",
            station=station,
            direction=direction,
            direction_bucket=direction_bucket,
            scheduled_time=_iso(scheduled_dt),
            actual_time=_iso(actual_dt),
            delay_minutes=delay_minutes,
            cancelled=cancelled,
            reason=reason,
            train_number=train_number,
        ))
```

#### Step 1.6 — Run the tests, verify they pass

- [ ] **Run:**

```bash
cd fetcher && uv run pytest tests/test_parser.py -v
```

Expected: PASS — the two new tests pass AND all pre-existing `test_parser.py` tests still pass (the 4th fixture stop has `line="S7"` and a valid `direction_bucket`, so `test_all_records_have_line` and `test_records_have_direction_bucket` are unaffected; the `next(... train_id == ...)` lookups in other tests are unaffected).

#### Step 1.7 — Lint

- [ ] **Run:**

```bash
cd fetcher && uv run ruff check src tests
```

Expected: no errors.

#### Step 1.8 — Commit

- [ ] **Commit:**

```bash
git add fetcher/src/s7bb_fetcher/parser.py fetcher/tests/fixtures/plan.xml fetcher/tests/test_parser.py
git commit -m "feat(fetcher): parse train number from <tl n>"
```

---

### Task 2: Storage — schema, migration, fill-only upsert

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/storage.py` (`SCHEMA` lines 9-26; `_migrate` lines 29-44; `upsert_records` lines 59-87)
- Test: `fetcher/tests/test_storage.py` (helper `_record` lines 15-21; migration test pattern at lines 51-83)

#### Step 2.1 — Write the failing tests

- [ ] **Append these tests to `fetcher/tests/test_storage.py`.**

`_record(**kwargs)` (lines 15-21) builds an `ArrivalRecord` from a defaults dict merged with kwargs; after Task 1, `train_number` defaults to `None` via the dataclass, so `_record()` needs no edit and `_record(train_number="6762")` works directly.

```python
def test_train_number_round_trip(tmp_db):
    upsert_records(tmp_db, [_record(train_number="6762")])
    row = tmp_db.execute("SELECT train_number FROM arrivals").fetchone()
    assert row[0] == "6762"


def test_train_number_null_when_absent(tmp_db):
    upsert_records(tmp_db, [_record()])  # train_number defaults to None
    row = tmp_db.execute("SELECT train_number FROM arrivals").fetchone()
    assert row[0] is None


def test_upsert_fills_null_train_number(tmp_db):
    """Re-observed row with <tl n> fills a previously NULL train_number."""
    upsert_records(tmp_db, [_record(train_number=None)])
    upsert_records(tmp_db, [_record(train_number="6762")])
    rows = tmp_db.execute("SELECT train_number FROM arrivals").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "6762"


def test_upsert_does_not_regress_train_number_to_null(tmp_db):
    """COALESCE guard: a later observation lacking <tl n> must NOT
    overwrite an already-captured train_number with NULL."""
    upsert_records(tmp_db, [_record(train_number="6762")])
    upsert_records(tmp_db, [_record(train_number=None)])
    rows = tmp_db.execute("SELECT train_number FROM arrivals").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "6762"  # preserved, not regressed to NULL


def test_migration_adds_train_number_column(tmp_path: Path):
    """A DB created without train_number is migrated on open_db,
    existing rows keep train_number NULL (Phase 1: no backfill)."""
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE arrivals (
            id INTEGER PRIMARY KEY,
            train_id TEXT NOT NULL,
            line TEXT NOT NULL,
            station TEXT NOT NULL,
            direction TEXT NOT NULL,
            direction_bucket TEXT NOT NULL DEFAULT 'unknown',
            scheduled_time TEXT NOT NULL,
            actual_time TEXT,
            delay_minutes INTEGER,
            cancelled INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            fetched_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX idx_dedup ON arrivals(train_id, scheduled_time);
        INSERT INTO arrivals (train_id, line, station, direction, scheduled_time, cancelled, fetched_at)
        VALUES ('t1', 'S7', 'Baierbrunn', 'Wolfratshausen', '2026-05-05T10:00:00+00:00', 0, '2026-05-05T10:01:00+00:00');
    """)
    conn.commit()
    conn.close()

    conn2 = open_db(db_path)
    cols = {row[1] for row in conn2.execute("PRAGMA table_info(arrivals)").fetchall()}
    assert "train_number" in cols
    row = conn2.execute("SELECT train_number FROM arrivals WHERE train_id='t1'").fetchone()
    assert row[0] is None  # pre-existing row stays NULL, no backfill
```

#### Step 2.2 — Run the tests, verify they fail

- [ ] **Run:**

```bash
cd fetcher && uv run pytest tests/test_storage.py -v -k "train_number or migration_adds_train_number"
```

Expected: FAIL — `sqlite3.OperationalError: no such column: train_number`.

#### Step 2.3 — Add column to `SCHEMA`

- [ ] **In `fetcher/src/s7bb_fetcher/storage.py`, add `train_number TEXT` to `SCHEMA` after `reason` (line 21).**

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS arrivals (
    id             INTEGER PRIMARY KEY,
    train_id       TEXT NOT NULL,
    line           TEXT NOT NULL,
    station        TEXT NOT NULL,
    direction      TEXT NOT NULL,
    direction_bucket TEXT NOT NULL DEFAULT 'unknown',
    scheduled_time TEXT NOT NULL,
    actual_time    TEXT,
    delay_minutes  INTEGER,
    cancelled      INTEGER NOT NULL DEFAULT 0,
    reason         TEXT,
    train_number   TEXT,
    fetched_at     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_dedup ON arrivals(train_id, scheduled_time);
CREATE INDEX IF NOT EXISTS idx_scheduled ON arrivals(scheduled_time);
"""
```

#### Step 2.4 — Add the migration branch

- [ ] **In `_migrate`, add a `train_number` branch mirroring the `direction_bucket` structure. NO backfill `UPDATE` (Phase 1: existing rows stay `NULL`).**

Append, inside `_migrate`, after the existing `direction_bucket` block (after line 44):

```python
    if "train_number" not in cols:
        conn.execute("ALTER TABLE arrivals ADD COLUMN train_number TEXT")
        conn.commit()
```

(`cols` is already computed at the top of `_migrate` from `PRAGMA table_info(arrivals)` — reuse it; do not recompute.)

#### Step 2.5 — Add to upsert with fill-only `COALESCE`

- [ ] **In `upsert_records`, add `r.train_number` to the value tuple, `train_number` to the INSERT column list and the `VALUES` placeholder count, and a fill-only `COALESCE` clause to `ON CONFLICT ... DO UPDATE SET`.**

The `COALESCE(excluded.train_number, train_number)` is deliberate, NOT the bare `= excluded.train_number` that `reason` uses. `train_number` is assumed immutable for a `(train_id, scheduled_time)` key. A bare assignment would silently and irreversibly regress a captured number to `NULL` when a later relief/extra-train observation lacks `<tl n>`. `COALESCE` keeps the stored value if the new one is `NULL`, while still letting a re-observation fill a previously `NULL` row.

Replace `upsert_records` (lines 59-87) with:

```python
def upsert_records(conn: sqlite3.Connection, records: list[ArrivalRecord]) -> int:
    """Insert or replace records. Returns number of rows affected."""
    now = datetime.now(UTC).isoformat()
    rows = [
        (
            r.train_id, r.line, r.station, r.direction, r.direction_bucket,
            r.scheduled_time, r.actual_time, r.delay_minutes,
            1 if r.cancelled else 0, r.reason, r.train_number, now,
        )
        for r in records
    ]
    cursor = conn.executemany(
        """
        INSERT INTO arrivals
            (train_id, line, station, direction, direction_bucket, scheduled_time,
             actual_time, delay_minutes, cancelled, reason, train_number, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(train_id, scheduled_time) DO UPDATE SET
            actual_time      = excluded.actual_time,
            delay_minutes    = excluded.delay_minutes,
            cancelled        = excluded.cancelled,
            reason           = excluded.reason,
            direction_bucket = excluded.direction_bucket,
            train_number     = COALESCE(excluded.train_number, train_number),
            fetched_at       = excluded.fetched_at
        """,
        rows,
    )
    conn.commit()
    return cursor.rowcount
```

(One extra `?` added to `VALUES` — now 12 placeholders for 12 columns. The value tuple now has 12 elements.)

#### Step 2.6 — Run the tests, verify they pass

- [ ] **Run:**

```bash
cd fetcher && uv run pytest tests/test_storage.py -v
```

Expected: PASS — all new tests AND all pre-existing storage tests (the pre-existing `test_migration_adds_column` still passes; `idx_dedup` and the existing `ON CONFLICT` columns are unchanged).

#### Step 2.7 — Lint

- [ ] **Run:**

```bash
cd fetcher && uv run ruff check src tests
```

Expected: no errors.

#### Step 2.8 — Commit

- [ ] **Commit:**

```bash
git add fetcher/src/s7bb_fetcher/storage.py fetcher/tests/test_storage.py
git commit -m "feat(fetcher): persist train_number with fill-only upsert"
```

---

### Task 3: Exporter — emit `train_number` in `latest.json` and `archive/*.json`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/exporter.py` (`_query_window` SELECT lines 39-40; `export_monthly_archive` SELECT lines 184-185)
- Test: `fetcher/tests/test_exporter.py` (helper `_make_arrival` lines 12-19)

There are **two** hardcoded SELECT column lists. Both must be updated or the archive path silently omits the field. `dict(zip(cols, row))` propagates the new key automatically once it is in the SELECT — no other exporter change is needed. Aggregates are untouched (per-arrival attribute only).

#### Step 3.1 — Write the failing tests

- [ ] **Append these tests to `fetcher/tests/test_exporter.py`.**

`_make_arrival` (lines 12-19) forwards `**kwargs` into `ArrivalRecord`, so `_make_arrival(..., train_number="6762")` works after Task 1, and an omitted `train_number` defaults to `None`.

```python
def test_latest_json_includes_train_number(tmp_path):
    conn = open_db(tmp_path / "test.db")
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    upsert_records(conn, [
        _make_arrival("m1", f"{today}T10:00:00+00:00", "muenchen", train_number="6762"),
        _make_arrival("m2", f"{today}T10:20:00+00:00", "muenchen"),  # no train_number
    ])
    out = tmp_path / "latest.json"
    export_latest(conn, out)
    arrivals = {a["train_id"]: a for a in json.loads(out.read_text())["arrivals"]}
    assert arrivals["m1"]["train_number"] == "6762"
    assert "train_number" in arrivals["m2"]
    assert arrivals["m2"]["train_number"] is None


def test_monthly_archive_includes_train_number(tmp_path):
    from s7bb_fetcher.exporter import export_monthly_archive

    conn = open_db(tmp_path / "test.db")
    upsert_records(conn, [
        _make_arrival("m1", "2026-04-01T08:00:00+00:00", "muenchen", train_number="6762"),
        _make_arrival("w1", "2026-04-01T08:13:00+00:00", "wolfratshausen"),
    ])
    out = tmp_path / "2026-04.json"
    export_monthly_archive(conn, 2026, 4, out)
    arrivals = {a["train_id"]: a for a in json.loads(out.read_text())["arrivals"]}
    assert arrivals["m1"]["train_number"] == "6762"
    assert "train_number" in arrivals["w1"]
    assert arrivals["w1"]["train_number"] is None
```

#### Step 3.2 — Run the tests, verify they fail

- [ ] **Run:**

```bash
cd fetcher && uv run pytest tests/test_exporter.py -v -k train_number
```

Expected: FAIL — `KeyError: 'train_number'` (the SELECT does not yet include the column, so the key is absent from the row dict).

#### Step 3.3 — Add `train_number` to the `_query_window` SELECT

- [ ] **In `fetcher/src/s7bb_fetcher/exporter.py`, add `train_number` to the SELECT in `_query_window` (lines 39-40).**

```python
        SELECT train_id, line, station, direction, direction_bucket, scheduled_time,
               actual_time, delay_minutes, cancelled, reason, train_number
        FROM arrivals
        WHERE scheduled_time >= ?
        ORDER BY scheduled_time, train_id
```

#### Step 3.4 — Add `train_number` to the `export_monthly_archive` SELECT

- [ ] **In `export_monthly_archive`, add `train_number` to the SELECT (lines 184-185).**

```python
        SELECT train_id, line, station, direction, direction_bucket, scheduled_time,
               actual_time, delay_minutes, cancelled, reason, train_number
        FROM arrivals
        WHERE scheduled_time >= ? AND scheduled_time < ?
        ORDER BY scheduled_time, train_id
```

#### Step 3.5 — Run the tests, verify they pass

- [ ] **Run:**

```bash
cd fetcher && uv run pytest tests/test_exporter.py -v
```

Expected: PASS — both new tests AND all pre-existing exporter tests (aggregates and slot logic are untouched; only an extra key is added to each row dict).

#### Step 3.6 — Full fetcher suite + lint

- [ ] **Run:**

```bash
cd fetcher && uv run pytest && uv run ruff check src tests
```

Expected: entire fetcher test suite PASSES, no lint errors.

#### Step 3.7 — Commit

- [ ] **Commit:**

```bash
git add fetcher/src/s7bb_fetcher/exporter.py fetcher/tests/test_exporter.py
git commit -m "feat(fetcher): emit train_number in latest.json and archive"
```

---

### Task 4: Site TypeScript contract

**Files:**
- Modify: `site/src/data.ts` (`Arrival` interface lines 3-14)
- Modify: `site/src/data.test.ts` (`arrival()` default builder lines 6-19)

The field is **optional** (`?`), not a required `string | null`. Finalized pre-0.6.0 `archive/*.json` already in `s7bb-data` permanently lack the key; their runtime value is `undefined`, not `null`. A non-optional type would mis-model them. No consumer reads the field, so there is no behavioural impact today — the `?` is correctness for future readers. No rendering anywhere.

#### Step 4.1 — Add the optional field to `Arrival`

- [ ] **In `site/src/data.ts`, add `train_number?: string | null` to the `Arrival` interface after `reason` (line 13).**

```typescript
export interface Arrival {
  train_id: string;
  line: string;
  station: string;
  direction: string;
  direction_bucket: DirectionBucket;
  scheduled_time: string;
  actual_time: string | null;
  delay_minutes: number | null;
  cancelled: boolean;
  reason: string | null;
  train_number?: string | null;
}
```

#### Step 4.2 — Add `train_number` to the test default builder (explicitness only)

- [ ] **In `site/src/data.test.ts`, add `train_number: null` to the object returned by the `arrival()` helper (lines 6-19), after `reason: null`.**

Because the interface field is optional, this is cosmetic — the helper and every partial-literal call site already type-check unchanged. Adding it makes the default object explicit and consistent with the other nullable fields.

```typescript
function arrival(overrides: Partial<Arrival>): Arrival {
  return {
    train_id: "x",
    line: "S7",
    station: "Baierbrunn",
    direction: "",
    direction_bucket: "muenchen",
    scheduled_time: "2026-05-01T08:00:00",
    actual_time: null,
    delay_minutes: 0,
    cancelled: false,
    reason: null,
    train_number: null,
    ...overrides,
  };
}
```

#### Step 4.3 — Type-check, build, lint, test

- [ ] **Run:**

```bash
cd site && npm run build && npm run lint && npm test
```

Expected: type-check passes (`tsc`), Vite build succeeds, eslint clean, vitest green. `site/src/archive.test.ts` constructs no typed `Arrival` literals, so it compiles unchanged.

#### Step 4.4 — Commit

- [ ] **Commit:**

```bash
git add site/src/data.ts site/src/data.test.ts
git commit -m "feat(site): add optional train_number to Arrival contract"
```

---

### Task 5: Release `0.6.0` (post-merge, per CLAUDE.md)

A new data field is a `feat` → MINOR bump. Per the CLAUDE.md "Post-merge release trigger", this runs **after** the implementation PR is merged into `main`, not on the feature branch. Follow `.claude/skills/release-hygiene/SKILL.md`.

> **Note on `[Unreleased]`:** `CHANGELOG.md` currently has an `[Unreleased]` → `### Changed` entry for the event-driven deploy (PR #43, infra/`ci`, no prior release cut). When `[Unreleased]` is renamed to `[0.6.0]`, that existing `### Changed` block is carried into the `0.6.0` section alongside the new `### Added` entry. Do not delete it.

#### Step 5.1 — Pull main

- [ ] **Run:**

```bash
git checkout main && git pull
```

#### Step 5.2 — Bump version

- [ ] **In `fetcher/pyproject.toml`, change `version = "0.5.2"` (line 3) to `version = "0.6.0"`.**

#### Step 5.3 — Sync lockfile

- [ ] **Run:**

```bash
cd fetcher && uv sync --no-dev
```

Expected: `fetcher/uv.lock` updated to reflect `0.6.0`.

#### Step 5.4 — Update CHANGELOG

- [ ] **In `CHANGELOG.md`, rename `## [Unreleased]` to `## [0.6.0] - 2026-05-19` and add an `### Added` section above the carried-over `### Changed` block:**

```markdown
## [0.6.0] - 2026-05-19

### Added

- The public train number (Zugnummer, DB Timetables `<tl n>`) is now
  captured going forward and exposed as a nullable `train_number` field
  in SQLite, `latest.json`, and `archive/*.json`. Rows observed before
  this release stay `null` (the plan endpoint has no history). No UI
  change — the field is data-only.

### Changed

- Site deploy is now triggered by each data commit (a `push`-triggered
  dispatch workflow in `s7bb/s7bb-data` calls this repo's
  `workflow_dispatch` API) instead of an hourly `schedule:` cron, which
  GitHub silently dropped under load (multi-hour gaps observed). The
  cross-repo dispatch token is `Actions: write`-only and lives in
  s7bb-data secrets, not on the VM — the VM's data-repo PAT is unchanged.
```

(Then add a fresh empty `## [Unreleased]` section above `## [0.6.0]`, per Keep a Changelog.)

#### Step 5.5 — Commit, tag, push

- [ ] **Run:**

```bash
git add fetcher/pyproject.toml fetcher/uv.lock CHANGELOG.md
git commit -m "chore(release): 0.6.0"
git tag v0.6.0
git push && git push origin v0.6.0
```

#### Step 5.6 — GitHub Release

- [ ] **Create the GitHub Release from the CHANGELOG section (note the dot-escaped, explicit-end awk form per the project's release-notes gotcha):**

```bash
gh release create v0.6.0 --title "v0.6.0" --latest \
  --notes-file <(awk '/^## \[0\.6\.0\]/{f=1} f&&/^## \[0\.5\.2\]/{exit} f' CHANGELOG.md | sed '$d')
```

- [ ] **Verify the release body is non-empty** at <https://github.com/s7bb/s7bb.github.io/releases> before considering the release done. (An empty body means the awk range did not match — fix and re-run with `gh release edit`.)

---

## Self-Review

**1. Spec coverage** — every spec section maps to a task:

- §2 Schema + migration → Task 2 (Steps 2.3, 2.4); fill-only upsert → Step 2.5
- §3 Parser (dataclass last/`= None`, guarded extraction, placement) → Task 1 (Steps 1.4, 1.5)
- §4 Exporter + JSON (both SELECT lists) → Task 3 (Steps 3.3, 3.4)
- §5 Site TS contract (optional `?`, `data.test.ts` default; `archive.test.ts` only if literals break — confirmed none) → Task 4
- §6 Tests: parser happy + no-`<tl>` fixture → Task 1; storage round-trip + migration + fill-only → Task 2; exporter latest + monthly archive → Task 3
- §7 Release `0.6.0` → Task 5
- §Risks — all addressed: short plan window/`NULL` rows (accepted, no backfill in Step 2.4); defensive `None` (Step 1.5 guarded form); dataclass last/`= None` (Step 1.4); fill-only `COALESCE` (Step 2.5); optional TS `?` (Step 4.1); both exporter SELECTs (Steps 3.3 + 3.4).

**2. Placeholder scan** — no TBD/TODO; every code step shows complete code; every command shows expected output. No "similar to Task N" — code is repeated where referenced.

**3. Type consistency** — `train_number` is the single name used everywhere: `ArrivalRecord.train_number: str | None = None` (Python), `train_number TEXT` (SQLite column), `"train_number"` (JSON key, via `dict(zip(cols, row))`), `train_number?: string | null` (TypeScript). The value tuple in `upsert_records` (12 elements) matches the INSERT column list (12 columns) matches the `VALUES` placeholders (12 `?`). The `COALESCE(excluded.train_number, train_number)` clause name matches the column.
