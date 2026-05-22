# Terminus Arrival Tracking (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add backend tracking of whether each Baierbrunn S7 departure reaches its terminus (München Hbf Gl.27-36 / Wolfratshausen) on time, late, short-turned, or cancelled. Phase 1 ships data only — schema, fetcher, exporter, JSON contract. No UI rendering.

**Architecture:** A new `terminus.py` module is invoked after Baierbrunn upsert inside `_fetch_job()`. Each cycle it (a) reads pending rows in a `[now-2h, now+5min]` window, (b) calls `/fchg/<terminus_eva>` at most once per direction in use, (c) classifies each pending train by `train_number` match, and (d) on `cs="c"` or missing-past-cutoff cases walks the train's own `dp.ppth` reverse to locate the Baierbrunn-most cancellation point. Terminal states (`arrived`/`short_turn`/`cancelled`) are immutable; pending rows simply retry next cycle. All terminus work is wrapped in a try/except so failure cannot abort the parent fetch.

**Tech Stack:** Python 3.11 (lxml, sqlite3, pytest, ruff), TypeScript 5 (Vite, vitest).

**Spec:** `docs/superpowers/specs/2026-05-22-terminus-tracking-design.md`

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `fetcher/src/s7bb_fetcher/parser.py` | XML → `ArrivalRecord` | Add `dp_ppth` field to dataclass; preserve already-read value onto record |
| `fetcher/src/s7bb_fetcher/storage.py` | SQLite persistence | Add 4 columns (`terminus_status`, `terminus_delay_minutes`, `terminus_short_turn_station`, `dp_ppth`) and `terminus_health` table; migrate; seed `terminus_status='pending'`; cancellation-flip clears; `update_terminus_fields()` |
| `fetcher/src/s7bb_fetcher/terminus.py` | Terminus tracking orchestrator | **New file.** Constants, `TerminusUpdate`, `PendingTrain`, `build_index`, `_is_cancelled`, `classify`, `drilldown_short_turn`, `list_pending_trains`, `update_terminus_for_window` |
| `fetcher/src/s7bb_fetcher/service.py` | APScheduler entrypoint | `_fetch_job()` calls `update_terminus_for_window(conn, client)` inside its own try/except |
| `fetcher/src/s7bb_fetcher/exporter.py` | SQLite → JSON | Both SELECTs (latest + monthly archive) gain 3 terminus columns; arrivals[] dict carries 3 new keys |
| `site/src/data.ts` | JS/TS data contract | Add `TerminusStatus` type and 3 optional+nullable fields on `Arrival` |
| `fetcher/tests/test_parser.py` | Parser tests | Assert `dp_ppth` populated on emitted records |
| `fetcher/tests/test_storage.py` | Storage tests | Migration, seed-pending, cancellation-flip-clears, dp_ppth overwrite, `update_terminus_fields`, `terminus_health` table |
| `fetcher/tests/test_terminus.py` | Terminus module tests | **New file.** All classify / drilldown / list_pending / orchestrator scenarios |
| `fetcher/tests/test_exporter.py` | Exporter tests | Terminus keys present in `latest.json` and monthly archive |
| `fetcher/tests/test_service.py` | Service tests | `update_terminus_for_window` raising does not abort `_fetch_job` |
| `fetcher/tests/fixtures/terminus_munich_arrived.xml` | New fixture | `<s>` with `<tl n=...>` matching a pending train, no `cs`, `ct` set |
| `fetcher/tests/fixtures/terminus_munich_delayed.xml` | New fixture | Same as arrived but `ct - pt = 5 min` |
| `fetcher/tests/fixtures/terminus_munich_cancelled.xml` | New fixture | `<ar cs="c">` at terminus |
| `fetcher/tests/fixtures/terminus_wolfratshausen_arrived.xml` | New fixture | Wolfratshausen terminus, no cs |
| `fetcher/tests/fixtures/intermediate_solln_arrived.xml` | New fixture | München-Solln /fchg with train present, no cs (i.e. delayed-only) |
| `fetcher/tests/fixtures/intermediate_solln_cancelled.xml` | New fixture | München-Solln /fchg with `<ar cs="c">` for the same train_number |
| `CHANGELOG.md` | Release notes | New `### Added` entry under `[Unreleased]` |

The `direction_bucket` value `"unknown"` is allowed by the schema (default) but is excluded from terminus polling — pending trains whose bucket is neither `muenchen` nor `wolfratshausen` simply stay pending forever, which is acceptable (extremely rare, e.g. malformed plan XML).

---

### Task 1: Parser — preserve `dp_ppth` onto `ArrivalRecord`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/parser.py` (dataclass at lines 12-24; constructor call at lines 135-147; `dp_ppth` already read at line 96)
- Test: `fetcher/tests/test_parser.py`

#### Step 1.1 — Write the failing test

- [ ] **Append to `fetcher/tests/test_parser.py`:**

```python
def test_dp_ppth_preserved_on_record():
    records = parse_timetable(_load("plan.xml"), _load("changes_empty.xml"))
    munich_bound = [r for r in records if r.direction_bucket == "muenchen"]
    assert munich_bound, "fixture must contain at least one München-bound stop"
    r = munich_bound[0]
    assert r.dp_ppth, "dp_ppth must be populated"
    # ppth is ordered Baierbrunn → terminus, pipe-separated
    parts = r.dp_ppth.split("|")
    assert parts[-1].startswith("München"), f"last stop should be München, got {parts[-1]}"
```

#### Step 1.2 — Run the test, expect failure

Run: `cd fetcher && uv run pytest tests/test_parser.py::test_dp_ppth_preserved_on_record -v`

Expected: FAIL — `AttributeError: 'ArrivalRecord' object has no attribute 'dp_ppth'`.

#### Step 1.3 — Add `dp_ppth` to the dataclass

- [ ] **In `fetcher/src/s7bb_fetcher/parser.py`, modify the `ArrivalRecord` dataclass:**

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
    dp_ppth: str = ""        # pipe-separated path Baierbrunn → terminus
```

#### Step 1.4 — Pass `dp_ppth` into the constructor

- [ ] **In `parse_timetable`, modify the final `records.append(...)` call (parser.py:135-147) to add `dp_ppth=dp_ppth`:**

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
    dp_ppth=dp_ppth,
))
```

The local variable `dp_ppth` is already assigned at `parser.py:96` (`dp.get("ppth", "")`). No new reads required.

#### Step 1.5 — Run the parser tests, verify pass

Run: `cd fetcher && uv run pytest tests/test_parser.py -v`

Expected: ALL PASS. Pre-existing tests construct `ArrivalRecord` only via `parse_timetable`, so the new defaulted field does not break them.

#### Step 1.6 — Commit

```bash
cd fetcher
git add src/s7bb_fetcher/parser.py tests/test_parser.py
git commit -m "feat(parser): preserve dp.ppth onto ArrivalRecord for terminus tracking"
```

---

### Task 2: Storage — schema + migration for terminus columns and `terminus_health` table

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/storage.py` (`SCHEMA` constant lines 9-27; `_migrate` lines 30-48)
- Test: `fetcher/tests/test_storage.py`

#### Step 2.1 — Write failing migration tests

- [ ] **Append to `fetcher/tests/test_storage.py`:**

```python
def test_migration_adds_terminus_columns(tmp_path: Path):
    """A pre-terminus DB gains the four new columns on open_db; existing rows
    keep them NULL (no backfill)."""
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
            train_number TEXT,
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
    for col in ("terminus_status", "terminus_delay_minutes", "terminus_short_turn_station", "dp_ppth"):
        assert col in cols, f"migration must add {col}"

    row = conn2.execute(
        "SELECT terminus_status, terminus_delay_minutes, terminus_short_turn_station, dp_ppth "
        "FROM arrivals WHERE train_id='t1'"
    ).fetchone()
    assert row == (None, None, None, None), "pre-existing row stays NULL (no backfill)"


def test_migration_creates_terminus_health_table(tmp_path: Path):
    db_path = tmp_path / "old.db"
    sqlite3.connect(str(db_path)).close()  # empty file is enough; open_db creates schema
    conn = open_db(db_path)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "terminus_health" in tables
    cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(terminus_health)"
    ).fetchall()}
    assert cols == {"eva", "zero_match_streak", "updated_at"}
```

#### Step 2.2 — Run, expect failure

Run: `cd fetcher && uv run pytest tests/test_storage.py::test_migration_adds_terminus_columns tests/test_storage.py::test_migration_creates_terminus_health_table -v`

Expected: FAIL — assertions on missing columns / table.

#### Step 2.3 — Extend `SCHEMA` and `_migrate`

- [ ] **In `fetcher/src/s7bb_fetcher/storage.py`, replace the `SCHEMA` constant with:**

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
    fetched_at     TEXT NOT NULL,
    terminus_status              TEXT,
    terminus_delay_minutes       INTEGER,
    terminus_short_turn_station  TEXT,
    dp_ppth                      TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_dedup ON arrivals(train_id, scheduled_time);
CREATE INDEX IF NOT EXISTS idx_scheduled ON arrivals(scheduled_time);
CREATE INDEX IF NOT EXISTS idx_terminus_pending
    ON arrivals(scheduled_time) WHERE terminus_status='pending';

CREATE TABLE IF NOT EXISTS terminus_health (
    eva                TEXT PRIMARY KEY,
    zero_match_streak  INTEGER NOT NULL DEFAULT 0,
    updated_at         TEXT NOT NULL
);
"""
```

The partial index `idx_terminus_pending` keeps `list_pending_trains` cheap as the table grows.

- [ ] **Replace `_migrate` with:**

```python
def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns and tables introduced after initial schema without breaking existing DBs."""
    cur = conn.execute("PRAGMA table_info(arrivals)")
    cols = {row[1] for row in cur.fetchall()}
    if "direction_bucket" not in cols:
        conn.execute(
            "ALTER TABLE arrivals ADD COLUMN direction_bucket TEXT NOT NULL DEFAULT 'unknown'"
        )
        conn.execute("""
            UPDATE arrivals SET direction_bucket = CASE
                WHEN direction = 'Wolfratshausen' THEN 'wolfratshausen'
                WHEN direction LIKE '%München%' THEN 'muenchen'
                ELSE 'unknown'
            END
        """)
        conn.commit()
    if "train_number" not in cols:
        conn.execute("ALTER TABLE arrivals ADD COLUMN train_number TEXT")
        conn.commit()
    # Terminus tracking — forward-only ALTERs, no backfill.
    for col, ddl in (
        ("terminus_status",              "ALTER TABLE arrivals ADD COLUMN terminus_status TEXT"),
        ("terminus_delay_minutes",       "ALTER TABLE arrivals ADD COLUMN terminus_delay_minutes INTEGER"),
        ("terminus_short_turn_station",  "ALTER TABLE arrivals ADD COLUMN terminus_short_turn_station TEXT"),
        ("dp_ppth",                      "ALTER TABLE arrivals ADD COLUMN dp_ppth TEXT"),
    ):
        if col not in cols:
            conn.execute(ddl)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_terminus_pending "
        "ON arrivals(scheduled_time) WHERE terminus_status='pending'"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS terminus_health (
            eva                TEXT PRIMARY KEY,
            zero_match_streak  INTEGER NOT NULL DEFAULT 0,
            updated_at         TEXT NOT NULL
        )
    """)
    conn.commit()
```

#### Step 2.4 — Run migration tests, verify pass

Run: `cd fetcher && uv run pytest tests/test_storage.py -v`

Expected: ALL PASS (new and existing).

#### Step 2.5 — Commit

```bash
cd fetcher
git add src/s7bb_fetcher/storage.py tests/test_storage.py
git commit -m "feat(storage): add terminus columns and terminus_health table"
```

---

### Task 3: Storage — upsert seeds `terminus_status='pending'`, clears on cancel-flip, overwrites `dp_ppth`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/storage.py` (`upsert_records` lines 63-92)
- Test: `fetcher/tests/test_storage.py`

#### Step 3.1 — Update the helper builder in `test_storage.py`

The existing `_record(**kwargs)` helper in `test_storage.py` does not pass `dp_ppth`. The dataclass default is `""` so old call-sites still work, but the new tests need to pass an explicit value.

- [ ] **No edit needed to the existing `_record` helper** — its `defaults` dict does not need to include `dp_ppth`. Tests that need a non-empty path pass it explicitly: `_record(dp_ppth="A|B|München Hbf Gl.27-36")`.

#### Step 3.2 — Write failing upsert tests

- [ ] **Append to `fetcher/tests/test_storage.py`:**

```python
def test_upsert_initialises_terminus_status_pending(tmp_db):
    """Newly inserted non-cancelled row gets terminus_status='pending'."""
    upsert_records(tmp_db, [_record(cancelled=False)])
    row = tmp_db.execute("SELECT terminus_status FROM arrivals").fetchone()
    assert row[0] == "pending"


def test_upsert_initialises_terminus_status_null_when_cancelled(tmp_db):
    """A Baierbrunn-cancelled row is not tracked → terminus_status stays NULL."""
    upsert_records(tmp_db, [_record(cancelled=True, actual_time=None, delay_minutes=None)])
    row = tmp_db.execute("SELECT terminus_status FROM arrivals").fetchone()
    assert row[0] is None


def test_upsert_clears_terminus_on_cancellation_flip(tmp_db):
    """A previously pending row that is later marked cancelled at Baierbrunn
    clears its terminus_* fields back to NULL."""
    upsert_records(tmp_db, [_record(cancelled=False)])
    # Simulate that a terminus update wrote a value before the cancellation arrived
    tmp_db.execute(
        "UPDATE arrivals SET terminus_status='arrived', terminus_delay_minutes=3"
    )
    tmp_db.commit()
    upsert_records(tmp_db, [_record(cancelled=True, actual_time=None, delay_minutes=None)])
    row = tmp_db.execute(
        "SELECT terminus_status, terminus_delay_minutes, terminus_short_turn_station "
        "FROM arrivals"
    ).fetchone()
    assert row == (None, None, None)


def test_upsert_preserves_terminus_on_normal_refetch(tmp_db):
    """Re-observation of a still-non-cancelled row must NOT clobber an
    already-written terminus result (idempotent re-fetches)."""
    upsert_records(tmp_db, [_record(cancelled=False)])
    tmp_db.execute(
        "UPDATE arrivals SET terminus_status='arrived', terminus_delay_minutes=2"
    )
    tmp_db.commit()
    upsert_records(tmp_db, [_record(cancelled=False, delay_minutes=1)])  # later refetch
    row = tmp_db.execute(
        "SELECT terminus_status, terminus_delay_minutes FROM arrivals"
    ).fetchone()
    assert row == ("arrived", 2)


def test_upsert_overwrites_dp_ppth_on_conflict(tmp_db):
    """dp_ppth is authoritative from the latest plan fetch — always overwrite."""
    upsert_records(tmp_db, [_record(dp_ppth="A|B|München Hbf Gl.27-36")])
    upsert_records(tmp_db, [_record(dp_ppth="A|B|C|München Hbf Gl.27-36")])
    row = tmp_db.execute("SELECT dp_ppth FROM arrivals").fetchone()
    assert row[0] == "A|B|C|München Hbf Gl.27-36"
```

#### Step 3.3 — Run, expect failure

Run: `cd fetcher && uv run pytest tests/test_storage.py -k "terminus or dp_ppth" -v`

Expected: FAIL — current `upsert_records` writes neither field.

#### Step 3.4 — Modify `upsert_records`

- [ ] **In `fetcher/src/s7bb_fetcher/storage.py`, replace `upsert_records` with:**

```python
def upsert_records(conn: sqlite3.Connection, records: list[ArrivalRecord]) -> int:
    """Insert or replace records. Returns number of rows affected."""
    now = datetime.now(UTC).isoformat()
    rows = [
        (
            r.train_id, r.line, r.station, r.direction, r.direction_bucket,
            r.scheduled_time, r.actual_time, r.delay_minutes,
            1 if r.cancelled else 0, r.reason, r.train_number, now,
            None if r.cancelled else "pending",  # initial terminus_status
            r.dp_ppth or None,                   # store NULL for empty, not ""
        )
        for r in records
    ]
    cursor = conn.executemany(
        """
        INSERT INTO arrivals
            (train_id, line, station, direction, direction_bucket, scheduled_time,
             actual_time, delay_minutes, cancelled, reason, train_number, fetched_at,
             terminus_status, dp_ppth)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(train_id, scheduled_time) DO UPDATE SET
            actual_time      = excluded.actual_time,
            delay_minutes    = excluded.delay_minutes,
            cancelled        = excluded.cancelled,
            reason           = excluded.reason,
            direction_bucket = excluded.direction_bucket,
            train_number     = COALESCE(excluded.train_number, train_number),
            fetched_at       = excluded.fetched_at,
            dp_ppth          = COALESCE(excluded.dp_ppth, dp_ppth),
            -- Cancellation flip wipes any prior terminus result back to NULL.
            -- Non-cancelled refetch leaves terminus_* untouched.
            terminus_status              = CASE WHEN excluded.cancelled = 1
                                               THEN NULL ELSE terminus_status END,
            terminus_delay_minutes       = CASE WHEN excluded.cancelled = 1
                                               THEN NULL ELSE terminus_delay_minutes END,
            terminus_short_turn_station  = CASE WHEN excluded.cancelled = 1
                                               THEN NULL ELSE terminus_short_turn_station END
        """,
        rows,
    )
    conn.commit()
    return cursor.rowcount
```

Notes:
- The `CASE WHEN excluded.cancelled=1 THEN NULL ELSE <existing> END` pattern is the SQL idiom for "clear on flip, otherwise leave alone".
- `dp_ppth` uses `COALESCE` so an unparseable refetch (NULL/empty) doesn't erase a previously-captured path. The spec says "Always overwrite", but a missing value on a refetch is an outage condition and we prefer to keep the last known good value.

#### Step 3.5 — Run, verify pass

Run: `cd fetcher && uv run pytest tests/test_storage.py -v`

Expected: ALL PASS.

#### Step 3.6 — Commit

```bash
cd fetcher
git add src/s7bb_fetcher/storage.py tests/test_storage.py
git commit -m "feat(storage): seed terminus_status, clear on cancel-flip, persist dp_ppth"
```

---

### Task 4: Storage — `update_terminus_fields()` guarded UPDATE

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/storage.py`
- Test: `fetcher/tests/test_storage.py`

#### Step 4.1 — Write failing tests

- [ ] **Append to `fetcher/tests/test_storage.py`:**

```python
from s7bb_fetcher.storage import update_terminus_fields  # added in Task 4


def test_update_terminus_fields_basic(tmp_db):
    """Writes status + delay + short_turn for a pending row matched by
    train_number within the ±4 h window."""
    upsert_records(tmp_db, [_record(
        train_number="6762", scheduled_time="2026-05-05T12:00:00+00:00",
    )])
    n = update_terminus_fields(tmp_db, [{
        "train_number": "6762",
        "scheduled_time": "2026-05-05T12:00:00+00:00",
        "terminus_status": "arrived",
        "terminus_delay_minutes": 3,
        "terminus_short_turn_station": None,
    }])
    assert n == 1
    row = tmp_db.execute(
        "SELECT terminus_status, terminus_delay_minutes, terminus_short_turn_station "
        "FROM arrivals WHERE train_number='6762'"
    ).fetchone()
    assert row == ("arrived", 3, None)


def test_update_terminus_fields_idempotent(tmp_db):
    """A second identical call is a no-op — the WHERE filter excludes
    rows no longer in 'pending' state."""
    upsert_records(tmp_db, [_record(train_number="6762")])
    update = {
        "train_number": "6762",
        "scheduled_time": _record().scheduled_time,
        "terminus_status": "arrived",
        "terminus_delay_minutes": 0,
        "terminus_short_turn_station": None,
    }
    update_terminus_fields(tmp_db, [update])
    n = update_terminus_fields(tmp_db, [update])
    assert n == 0


def test_update_terminus_fields_guards_cancelled_flip(tmp_db):
    """If a Baierbrunn refetch flipped cancelled=1 between cycles, the
    terminus update for that train is silently dropped."""
    upsert_records(tmp_db, [_record(train_number="6762", cancelled=False)])
    upsert_records(tmp_db, [_record(
        train_number="6762", cancelled=True, actual_time=None, delay_minutes=None,
    )])  # flips → terminus_status reset to NULL
    n = update_terminus_fields(tmp_db, [{
        "train_number": "6762",
        "scheduled_time": _record().scheduled_time,
        "terminus_status": "arrived",
        "terminus_delay_minutes": 0,
        "terminus_short_turn_station": None,
    }])
    assert n == 0
    row = tmp_db.execute(
        "SELECT terminus_status FROM arrivals WHERE train_number='6762'"
    ).fetchone()
    assert row[0] is None  # cancelled rows never gain a terminus_status


def test_update_terminus_fields_window_scope(tmp_db):
    """Two rows with same train_number on different days: the one outside
    the ±4 h window is not updated."""
    upsert_records(tmp_db, [_record(
        train_id="d1", train_number="6762",
        scheduled_time="2026-05-05T12:00:00+00:00",
    )])
    upsert_records(tmp_db, [_record(
        train_id="d2", train_number="6762",
        scheduled_time="2026-05-06T12:00:00+00:00",
    )])
    n = update_terminus_fields(tmp_db, [{
        "train_number": "6762",
        "scheduled_time": "2026-05-05T12:00:00+00:00",
        "terminus_status": "arrived",
        "terminus_delay_minutes": 0,
        "terminus_short_turn_station": None,
    }])
    assert n == 1  # only the May 5 row
    rows = dict(tmp_db.execute(
        "SELECT train_id, terminus_status FROM arrivals ORDER BY train_id"
    ).fetchall())
    assert rows == {"d1": "arrived", "d2": "pending"}
```

#### Step 4.2 — Run, expect failure

Run: `cd fetcher && uv run pytest tests/test_storage.py -k "update_terminus_fields" -v`

Expected: FAIL — `ImportError: cannot import name 'update_terminus_fields'`.

#### Step 4.3 — Implement `update_terminus_fields`

- [ ] **Append to `fetcher/src/s7bb_fetcher/storage.py`:**

```python
from datetime import timedelta


def update_terminus_fields(
    conn: sqlite3.Connection, updates: list[dict]
) -> int:
    """Apply a batch of terminus classification results.

    Each update dict carries: train_number, scheduled_time, terminus_status,
    terminus_delay_minutes, terminus_short_turn_station.

    The UPDATE is guarded by `terminus_status='pending' AND cancelled=0`, so
    it is idempotent (a second call is a no-op) and a concurrent cancel-flip
    silently drops the terminus write.

    Match window is ±4 h around the row's scheduled_time on the same
    train_number — avoids UTC-vs-local-DE date ambiguity for late-night
    trains crossing midnight UTC.
    """
    total = 0
    for u in updates:
        sched = datetime.fromisoformat(u["scheduled_time"])
        lo = (sched - timedelta(hours=4)).isoformat()
        hi = (sched + timedelta(hours=4)).isoformat()
        cur = conn.execute(
            """
            UPDATE arrivals
               SET terminus_status              = ?,
                   terminus_delay_minutes       = ?,
                   terminus_short_turn_station  = ?
             WHERE train_number = ?
               AND scheduled_time BETWEEN ? AND ?
               AND terminus_status = 'pending'
               AND cancelled = 0
            """,
            (
                u["terminus_status"],
                u["terminus_delay_minutes"],
                u["terminus_short_turn_station"],
                u["train_number"],
                lo, hi,
            ),
        )
        total += cur.rowcount
    conn.commit()
    return total
```

#### Step 4.4 — Run, verify pass

Run: `cd fetcher && uv run pytest tests/test_storage.py -v`

Expected: ALL PASS.

#### Step 4.5 — Commit

```bash
cd fetcher
git add src/s7bb_fetcher/storage.py tests/test_storage.py
git commit -m "feat(storage): add update_terminus_fields with ±4h window guard"
```

---

### Task 5: Terminus fixtures

**Files:**
- Create: `fetcher/tests/fixtures/terminus_munich_arrived.xml`
- Create: `fetcher/tests/fixtures/terminus_munich_delayed.xml`
- Create: `fetcher/tests/fixtures/terminus_munich_cancelled.xml`
- Create: `fetcher/tests/fixtures/terminus_wolfratshausen_arrived.xml`
- Create: `fetcher/tests/fixtures/intermediate_solln_arrived.xml`
- Create: `fetcher/tests/fixtures/intermediate_solln_cancelled.xml`

All fixtures use `<tl n="6762"/>` so they correlate with the same `train_number` across tests. `pt` (planned time) is `2605051230` (i.e. 2026-05-05 12:30 local DE = 10:30 UTC); fixtures with delay use `ct="2605051235"` (+5 min).

#### Step 5.1 — Create `terminus_munich_arrived.xml`

- [ ] **Write `fetcher/tests/fixtures/terminus_munich_arrived.xml`:**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<timetable station="München Hbf Gl.27-36">
  <s id="trip-S7-arr-001">
    <tl c="S" n="6762"/>
    <ar pt="2605051230" ct="2605051230" pp="27" l="S7"
        ppth="Baierbrunn|Buchenhain|Höllriegelskreuth|Pullach|Großhesselohe Isartalbf|München-Solln|München Siemenswerke|München-Mittersendling|München Harras|München Heimeranplatz|München Donnersbergerbrücke"/>
  </s>
</timetable>
```

#### Step 5.2 — Create `terminus_munich_delayed.xml`

- [ ] **Write `fetcher/tests/fixtures/terminus_munich_delayed.xml`:**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<timetable station="München Hbf Gl.27-36">
  <s id="trip-S7-arr-001">
    <tl c="S" n="6762"/>
    <ar pt="2605051230" ct="2605051235" pp="27" l="S7"
        ppth="Baierbrunn|Buchenhain|Höllriegelskreuth|Pullach|Großhesselohe Isartalbf|München-Solln|München Siemenswerke|München-Mittersendling|München Harras|München Heimeranplatz|München Donnersbergerbrücke"/>
  </s>
</timetable>
```

#### Step 5.3 — Create `terminus_munich_cancelled.xml`

- [ ] **Write `fetcher/tests/fixtures/terminus_munich_cancelled.xml`:**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<timetable station="München Hbf Gl.27-36">
  <s id="trip-S7-arr-001">
    <tl c="S" n="6762"/>
    <ar pt="2605051230" pp="27" l="S7" cs="c"
        ppth="Baierbrunn|Buchenhain|Höllriegelskreuth|Pullach|Großhesselohe Isartalbf|München-Solln|München Siemenswerke|München-Mittersendling|München Harras|München Heimeranplatz|München Donnersbergerbrücke"/>
  </s>
</timetable>
```

#### Step 5.4 — Create `terminus_wolfratshausen_arrived.xml`

- [ ] **Write `fetcher/tests/fixtures/terminus_wolfratshausen_arrived.xml`:**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<timetable station="Wolfratshausen">
  <s id="trip-S7-arr-002">
    <tl c="S" n="6763"/>
    <ar pt="2605051250" ct="2605051250" pp="1" l="S7"
        ppth="Baierbrunn|Hohenschäftlarn|Ebenhausen-Schäftlarn|Icking"/>
  </s>
</timetable>
```

#### Step 5.5 — Create `intermediate_solln_arrived.xml`

This fixture represents München-Solln's `/fchg` carrying the train with a delay (no `cs="c"`). Used to assert the drilldown walks past it when terminus said `cs="c"` but the train was still running at Solln.

- [ ] **Write `fetcher/tests/fixtures/intermediate_solln_arrived.xml`:**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<timetable station="München-Solln">
  <s id="trip-S7-mid-001">
    <tl c="S" n="6762"/>
    <ar pt="2605051220" ct="2605051225" pp="2" l="S7"
        ppth="Baierbrunn|Buchenhain|Höllriegelskreuth|Pullach|Großhesselohe Isartalbf"/>
  </s>
</timetable>
```

#### Step 5.6 — Create `intermediate_solln_cancelled.xml`

- [ ] **Write `fetcher/tests/fixtures/intermediate_solln_cancelled.xml`:**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<timetable station="München-Solln">
  <s id="trip-S7-mid-001">
    <tl c="S" n="6762"/>
    <ar pt="2605051220" pp="2" l="S7" cs="c"
        ppth="Baierbrunn|Buchenhain|Höllriegelskreuth|Pullach|Großhesselohe Isartalbf"/>
  </s>
</timetable>
```

#### Step 5.7 — Commit fixtures

```bash
cd fetcher
git add tests/fixtures/terminus_*.xml tests/fixtures/intermediate_*.xml
git commit -m "test(terminus): add /fchg fixtures for terminus + intermediate stations"
```

---

### Task 6: Terminus module — constants, dataclasses, `build_index`, `_is_cancelled`

**Files:**
- Create: `fetcher/src/s7bb_fetcher/terminus.py`
- Create: `fetcher/tests/test_terminus.py`

#### Step 6.1 — Write failing tests

- [ ] **Create `fetcher/tests/test_terminus.py` with:**

```python
from pathlib import Path

import pytest
from lxml import etree

FIXTURES = Path(__file__).parent / "fixtures"

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)


def _load(name: str) -> etree._Element:
    return etree.fromstring((FIXTURES / name).read_bytes(), parser=_PARSER)


def test_build_index_keys_by_train_number():
    from s7bb_fetcher.terminus import build_index
    idx = build_index(_load("terminus_munich_arrived.xml"))
    assert "6762" in idx
    assert idx["6762"].tag == "s"


def test_build_index_skips_entries_without_tl_n():
    """A <s> without a train number is skipped (cannot be matched)."""
    from s7bb_fetcher.terminus import build_index
    xml = etree.fromstring(
        b'<timetable><s id="x"><ar pt="2605051200"/></s></timetable>',
        parser=_PARSER,
    )
    assert build_index(xml) == {}


def test_is_cancelled_true_on_ar_cs_c():
    from s7bb_fetcher.terminus import _is_cancelled, build_index
    entry = build_index(_load("terminus_munich_cancelled.xml"))["6762"]
    assert _is_cancelled(entry) is True


def test_is_cancelled_false_on_normal_arrival():
    from s7bb_fetcher.terminus import _is_cancelled, build_index
    entry = build_index(_load("terminus_munich_arrived.xml"))["6762"]
    assert _is_cancelled(entry) is False


def test_constants_present():
    from s7bb_fetcher import terminus
    assert terminus.MUENCHEN_HBF_EVA == "8000261"
    assert terminus.WOLFRATSHAUSEN_EVA == "8006550"
    assert terminus.CUTOFF_GRACE_MINUTES == 60
    assert terminus.TRAVEL_TIME_MINUTES == {"muenchen": 35, "wolfratshausen": 20}
    # Spot-check the station→EVA table from the spec
    assert terminus.STATION_NAME_TO_EVA["München-Solln"] == "8004161"
    assert terminus.STATION_NAME_TO_EVA["Hohenschäftlarn"] == "8002955"
```

#### Step 6.2 — Run, expect failure

Run: `cd fetcher && uv run pytest tests/test_terminus.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 's7bb_fetcher.terminus'`.

#### Step 6.3 — Create `terminus.py`

- [ ] **Write `fetcher/src/s7bb_fetcher/terminus.py`:**

```python
"""Terminus arrival tracking for S7 trains departing Baierbrunn.

After each Baierbrunn fetch cycle, classify every pending train as
arrived / short_turn / cancelled / pending by polling the terminus
station's /fchg feed and matching on train_number.
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from lxml import etree

log = logging.getLogger(__name__)

MUENCHEN_HBF_EVA = "8000261"
WOLFRATSHAUSEN_EVA = "8006550"

# Per-direction average travel time Baierbrunn → terminus (minutes).
TRAVEL_TIME_MINUTES = {
    "muenchen":       35,
    "wolfratshausen": 20,
}
# Grace period beyond planned terminus arrival before declaring a missing train cancelled.
CUTOFF_GRACE_MINUTES = 60

# Resolved 2026-05-22 against DB Timetables /station/{name}. Stations along
# the two S7 directions, ordered Baierbrunn → terminus.
STATION_NAME_TO_EVA = {
    # Direction München
    "Buchenhain":                  "8071272",
    "Höllriegelskreuth":           "8002899",
    "Pullach":                     "8004899",
    "Großhesselohe Isartalbf":     "8002422",
    "München-Solln":               "8004161",
    "München Siemenswerke":        "8004137",
    "München-Mittersendling":      "8004154",
    "München Harras":              "8004130",
    "München Heimeranplatz":       "8005419",
    "München Donnersbergerbrücke": "8004128",
    "München Hbf Gl.27-36":        MUENCHEN_HBF_EVA,
    # Direction Wolfratshausen
    "Hohenschäftlarn":             "8002955",
    "Ebenhausen-Schäftlarn":       "8001621",
    "Icking":                      "8003039",
    "Wolfratshausen":              WOLFRATSHAUSEN_EVA,
}

TERMINUS_EVA_FOR_BUCKET = {
    "muenchen":       MUENCHEN_HBF_EVA,
    "wolfratshausen": WOLFRATSHAUSEN_EVA,
}


@dataclass(frozen=True)
class PendingTrain:
    train_number: str
    scheduled_time: str   # ISO UTC
    direction_bucket: str
    dp_ppth: str          # may be empty/None for legacy rows


@dataclass(frozen=True)
class TerminusUpdate:
    train_number: str
    scheduled_time: str
    terminus_status: str                    # "arrived" | "short_turn" | "cancelled"
    terminus_delay_minutes: int | None
    terminus_short_turn_station: str | None


def build_index(feed: etree._Element) -> dict[str, etree._Element]:
    """Index a /fchg response by train_number."""
    out: dict[str, etree._Element] = {}
    for s in feed.findall(".//s"):
        tl = s.find("tl")
        n = tl.get("n") if tl is not None else None
        if n and n.strip():
            out[n.strip()] = s
    return out


def _is_cancelled(entry: etree._Element) -> bool:
    """True iff this station's <ar> (or <dp> fallback) carries cs="c"."""
    ar = entry.find("ar")
    if ar is not None and ar.get("cs", "") == "c":
        return True
    dp = entry.find("dp")
    if dp is not None and dp.get("cs", "") == "c":
        return True
    return False
```

(Functions `classify`, `drilldown_short_turn`, `list_pending_trains`, and `update_terminus_for_window` come in later tasks; do not stub them here — pytest collection will fail to find them, but no test in Task 6 imports them.)

#### Step 6.4 — Run, verify pass

Run: `cd fetcher && uv run pytest tests/test_terminus.py -v`

Expected: ALL PASS (5 tests).

#### Step 6.5 — Commit

```bash
cd fetcher
git add src/s7bb_fetcher/terminus.py tests/test_terminus.py
git commit -m "feat(terminus): scaffold module with constants and index helpers"
```

---

### Task 7: Terminus module — `classify()` pure function

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/terminus.py`
- Modify: `fetcher/tests/test_terminus.py`

Per spec §State machine, `classify()` decides for one pending train, given (a) the terminus feed entry (or None), (b) `now`, and (c) a drilldown callable. Splitting the drilldown out keeps `classify()` pure and testable without the HTTP layer.

#### Step 7.1 — Write failing tests

- [ ] **Append to `fetcher/tests/test_terminus.py`:**

```python
from datetime import datetime, timedelta, UTC

from s7bb_fetcher.terminus import PendingTrain  # forward-OK after Task 6


def _pending(
    train_number="6762",
    scheduled_iso="2026-05-05T10:30:00+00:00",
    bucket="muenchen",
    dp_ppth="Buchenhain|Höllriegelskreuth|München Hbf Gl.27-36",
) -> PendingTrain:
    return PendingTrain(train_number, scheduled_iso, bucket, dp_ppth)


# scheduled_time is 10:30 UTC; cutoff = 10:30 + 35 + 60 = 12:05 UTC
_BEFORE_CUTOFF = datetime(2026, 5, 5, 11, 30, tzinfo=UTC)
_AFTER_CUTOFF  = datetime(2026, 5, 5, 13,  0, tzinfo=UTC)


def test_classify_arrived_on_time():
    from s7bb_fetcher.terminus import build_index, classify
    idx = build_index(_load("terminus_munich_arrived.xml"))
    pending = _pending()
    update = classify(pending, idx.get(pending.train_number), _BEFORE_CUTOFF,
                      drilldown=lambda *_: None)
    assert update is not None
    assert update.terminus_status == "arrived"
    assert update.terminus_delay_minutes == 0
    assert update.terminus_short_turn_station is None


def test_classify_arrived_with_delay():
    from s7bb_fetcher.terminus import build_index, classify
    idx = build_index(_load("terminus_munich_delayed.xml"))
    pending = _pending()
    update = classify(pending, idx.get(pending.train_number), _BEFORE_CUTOFF,
                      drilldown=lambda *_: None)
    assert update.terminus_status == "arrived"
    assert update.terminus_delay_minutes == 5


def test_classify_short_turn_calls_drilldown_and_uses_its_result():
    from s7bb_fetcher.terminus import build_index, classify
    idx = build_index(_load("terminus_munich_cancelled.xml"))
    calls = []

    def fake_drilldown(dp_ppth, train_number):
        calls.append((dp_ppth, train_number))
        return "München-Solln"

    update = classify(_pending(), idx.get("6762"), _BEFORE_CUTOFF,
                      drilldown=fake_drilldown)
    assert calls == [("Buchenhain|Höllriegelskreuth|München Hbf Gl.27-36", "6762")]
    assert update.terminus_status == "short_turn"
    assert update.terminus_short_turn_station == "München-Solln"
    assert update.terminus_delay_minutes is None


def test_classify_cancelled_when_drilldown_finds_no_intermediate():
    """Terminus says cs='c' but no intermediate station reports the train
    as cancelled → train vanished entirely → status='cancelled'."""
    from s7bb_fetcher.terminus import build_index, classify
    idx = build_index(_load("terminus_munich_cancelled.xml"))
    update = classify(_pending(), idx.get("6762"), _BEFORE_CUTOFF,
                      drilldown=lambda *_: None)
    assert update.terminus_status == "cancelled"
    assert update.terminus_short_turn_station is None


def test_classify_pending_when_missing_before_cutoff():
    """Train absent from terminus feed but cutoff not yet passed → return
    None (= no update; row stays 'pending' until next cycle)."""
    from s7bb_fetcher.terminus import classify
    assert classify(_pending(), None, _BEFORE_CUTOFF,
                    drilldown=lambda *_: None) is None


def test_classify_short_turn_via_drilldown_after_cutoff():
    """Missing past cutoff + drilldown finds a cancelled intermediate →
    short_turn."""
    from s7bb_fetcher.terminus import classify
    update = classify(_pending(), None, _AFTER_CUTOFF,
                      drilldown=lambda *_: "Pullach")
    assert update.terminus_status == "short_turn"
    assert update.terminus_short_turn_station == "Pullach"


def test_classify_cancelled_when_missing_past_cutoff_and_drilldown_blank():
    from s7bb_fetcher.terminus import classify
    update = classify(_pending(), None, _AFTER_CUTOFF,
                      drilldown=lambda *_: None)
    assert update.terminus_status == "cancelled"
    assert update.terminus_short_turn_station is None


def test_classify_wolfratshausen_uses_20_minute_travel_time():
    """Wolfratshausen cutoff = scheduled + 20 + 60 = +80 min. A train missing
    at scheduled + 70 min must still be 'pending', not 'cancelled'."""
    from s7bb_fetcher.terminus import classify
    pending = _pending(bucket="wolfratshausen",
                       dp_ppth="Hohenschäftlarn|Ebenhausen-Schäftlarn|Icking|Wolfratshausen")
    sched = datetime.fromisoformat(pending.scheduled_time)
    now = sched + timedelta(minutes=70)
    assert classify(pending, None, now, drilldown=lambda *_: None) is None


def test_classify_arrived_zero_delay_when_ct_missing():
    """Some on-time entries omit ct entirely. With no cs and no ct, treat
    as arrived with delay=0."""
    from s7bb_fetcher.terminus import classify
    xml = etree.fromstring(
        b'<timetable><s id="x"><tl n="6762"/><ar pt="2605051230"/></s></timetable>',
        parser=_PARSER,
    )
    entry = xml.find(".//s")
    update = classify(_pending(), entry, _BEFORE_CUTOFF, drilldown=lambda *_: None)
    assert update.terminus_status == "arrived"
    assert update.terminus_delay_minutes == 0
```

#### Step 7.2 — Run, expect failure

Run: `cd fetcher && uv run pytest tests/test_terminus.py -v`

Expected: FAIL — `classify` not defined.

#### Step 7.3 — Implement `classify`

- [ ] **Append to `fetcher/src/s7bb_fetcher/terminus.py`:**

```python
_DB_TIME_FMT = "%y%m%d%H%M"  # planning/change times: Europe/Berlin local

from zoneinfo import ZoneInfo
_DE_TZ = ZoneInfo("Europe/Berlin")


def _parse_db_time(raw: str) -> datetime:
    local = datetime.strptime(raw, _DB_TIME_FMT).replace(tzinfo=_DE_TZ)
    return local.astimezone(UTC)


def _cutoff(pending: PendingTrain) -> datetime:
    sched = datetime.fromisoformat(pending.scheduled_time)
    travel = TRAVEL_TIME_MINUTES.get(pending.direction_bucket, 35)
    return sched + timedelta(minutes=travel + CUTOFF_GRACE_MINUTES)


def _arrival_delay_minutes(entry: etree._Element) -> int:
    """Compute ct - pt in whole minutes; 0 if ct missing."""
    ar = entry.find("ar")
    if ar is None:
        return 0
    pt = ar.get("pt")
    ct = ar.get("ct")
    if not pt or not ct:
        return 0
    delta = _parse_db_time(ct) - _parse_db_time(pt)
    return int(delta.total_seconds() / 60)


def classify(
    pending: PendingTrain,
    entry: etree._Element | None,
    now: datetime,
    drilldown,
) -> TerminusUpdate | None:
    """Classify a single pending train.

    Returns a TerminusUpdate to write, or None to leave the row pending.

    `drilldown` is a callable `(dp_ppth, train_number) -> str | None` that
    returns the Baierbrunn-most station where the train is reported with
    cs="c", or None if no cancellation point is found.
    """
    # Case A: terminus feed has an entry for this train_number.
    if entry is not None:
        if _is_cancelled(entry):
            station = drilldown(pending.dp_ppth, pending.train_number)
            if station is None:
                return TerminusUpdate(
                    pending.train_number, pending.scheduled_time,
                    terminus_status="cancelled",
                    terminus_delay_minutes=None,
                    terminus_short_turn_station=None,
                )
            return TerminusUpdate(
                pending.train_number, pending.scheduled_time,
                terminus_status="short_turn",
                terminus_delay_minutes=None,
                terminus_short_turn_station=station,
            )
        # Not cancelled at terminus → arrived (possibly late).
        return TerminusUpdate(
            pending.train_number, pending.scheduled_time,
            terminus_status="arrived",
            terminus_delay_minutes=_arrival_delay_minutes(entry),
            terminus_short_turn_station=None,
        )

    # Case B: missing from terminus feed.
    if now <= _cutoff(pending):
        return None  # stay pending; next cycle may catch it

    # Case C: missing past cutoff → drilldown.
    station = drilldown(pending.dp_ppth, pending.train_number)
    if station is None:
        return TerminusUpdate(
            pending.train_number, pending.scheduled_time,
            terminus_status="cancelled",
            terminus_delay_minutes=None,
            terminus_short_turn_station=None,
        )
    return TerminusUpdate(
        pending.train_number, pending.scheduled_time,
        terminus_status="short_turn",
        terminus_delay_minutes=None,
        terminus_short_turn_station=station,
    )
```

#### Step 7.4 — Run, verify pass

Run: `cd fetcher && uv run pytest tests/test_terminus.py -v`

Expected: ALL PASS.

#### Step 7.5 — Commit

```bash
cd fetcher
git add src/s7bb_fetcher/terminus.py tests/test_terminus.py
git commit -m "feat(terminus): add classify() with arrived/short_turn/cancelled/pending logic"
```

---

### Task 8: Terminus module — `drilldown_short_turn` reverse walk

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/terminus.py`
- Modify: `fetcher/tests/test_terminus.py`

#### Step 8.1 — Write failing tests

- [ ] **Append to `fetcher/tests/test_terminus.py`:**

```python
class _FakeClient:
    """Duck-typed stand-in for api module: maps eva → /fchg fixture name."""

    def __init__(self, mapping: dict[str, str]):
        # mapping: eva → fixture filename (without .xml)
        self._mapping = mapping
        self.calls: list[str] = []

    def fetch_full_changes(self, eva: str) -> etree._Element:
        self.calls.append(eva)
        name = self._mapping.get(eva)
        if name is None:
            raise AssertionError(f"unexpected fetch for eva={eva}")
        return _load(name + ".xml")


def test_drilldown_returns_baierbrunn_most_cancelled():
    """Solln has cs='c'; stations before Solln are not in /fchg (on-time
    pass-through) → first reverse-walk None breaks the loop → return Solln."""
    from s7bb_fetcher.terminus import drilldown_short_turn
    client = _FakeClient({
        "8004161": "intermediate_solln_cancelled",  # München-Solln cancelled
        # Stations earlier in ppth (Pullach, Höllriegelskreuth, ...) return
        # empty /fchg feeds. We model that by mapping them to an empty
        # fixture; build_index of an empty <timetable/> yields {}.
        "8004899": "empty_fchg",
        "8002899": "empty_fchg",
        "8071272": "empty_fchg",
        "8002422": "empty_fchg",
    })
    ppth = "Buchenhain|Höllriegelskreuth|Pullach|Großhesselohe Isartalbf|München-Solln|München Hbf Gl.27-36"
    result = drilldown_short_turn(client, ppth, "6762")
    assert result == "München-Solln"


def test_drilldown_stops_at_first_on_time_intermediate():
    """If München-Solln is present in /fchg WITHOUT cs='c' (i.e. delayed
    but ran), the walk stops there — Pullach (earlier) is never fetched."""
    from s7bb_fetcher.terminus import drilldown_short_turn
    client = _FakeClient({
        "8004161": "intermediate_solln_arrived",  # delayed, not cancelled
    })
    ppth = "Pullach|München-Solln|München Hbf Gl.27-36"
    result = drilldown_short_turn(client, ppth, "6762")
    assert result is None
    # Pullach (8004899) must NOT be fetched
    assert "8004899" not in client.calls


def test_drilldown_unknown_station_logs_and_continues(caplog):
    """An unknown station name is skipped without aborting the walk."""
    from s7bb_fetcher.terminus import drilldown_short_turn
    client = _FakeClient({
        "8004161": "intermediate_solln_cancelled",
    })
    ppth = "Mars|München-Solln|München Hbf Gl.27-36"
    with caplog.at_level("WARNING"):
        result = drilldown_short_turn(client, ppth, "6762")
    assert result == "München-Solln"
    assert any("Mars" in r.message for r in caplog.records)


def test_drilldown_empty_ppth_returns_none():
    """Legacy rows with NULL/empty dp_ppth cannot be drilled down."""
    from s7bb_fetcher.terminus import drilldown_short_turn
    client = _FakeClient({})
    assert drilldown_short_turn(client, "", "6762") is None
    assert drilldown_short_turn(client, None, "6762") is None
    assert client.calls == []


def test_drilldown_http_error_aborts_walk_and_returns_none():
    """A transient HTTP failure mid-walk leaves the train pending (caller
    interprets None correctly)."""
    from s7bb_fetcher.terminus import drilldown_short_turn

    class _Erroring:
        def fetch_full_changes(self, eva):
            raise RuntimeError("boom")
    ppth = "München-Solln|München Hbf Gl.27-36"
    assert drilldown_short_turn(_Erroring(), ppth, "6762") is None
```

The test references `empty_fchg.xml` — create it as part of this task.

- [ ] **Create `fetcher/tests/fixtures/empty_fchg.xml`:**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<timetable/>
```

#### Step 8.2 — Run, expect failure

Run: `cd fetcher && uv run pytest tests/test_terminus.py -k drilldown -v`

Expected: FAIL — `drilldown_short_turn` not defined.

#### Step 8.3 — Implement `drilldown_short_turn`

- [ ] **Append to `fetcher/src/s7bb_fetcher/terminus.py`:**

```python
def drilldown_short_turn(client, dp_ppth: str | None, train_number: str) -> str | None:
    """Walk dp.ppth reverse from one-before-terminus toward Baierbrunn,
    looking up each station's /fchg and returning the Baierbrunn-most
    station where the train is reported with cs='c'.

    The /fchg endpoint only returns entries for stations where something
    *changed*. So `entry is None` at an intermediate means the train passed
    on time there — i.e. we walked past the cancellation point and can stop.

    Returns None if no cancellation point is reachable (train vanished
    before any station that reported a change, or HTTP failure mid-walk,
    or dp_ppth is empty/None).
    """
    if not dp_ppth:
        return None
    parts = [p for p in dp_ppth.split("|") if p]
    # parts[-1] is terminus; walk everything before it, reverse
    candidate: str | None = None
    for name in reversed(parts[:-1]):
        eva = STATION_NAME_TO_EVA.get(name)
        if eva is None:
            log.warning("terminus drilldown: unknown intermediate %s", name)
            continue
        try:
            feed = client.fetch_full_changes(eva)
        except Exception:
            log.exception("terminus drilldown: /fchg %s failed; aborting walk", eva)
            return candidate  # best-effort: return what we have so far
        entry = build_index(feed).get(train_number)
        if entry is None:
            # No change at this station → train passed → past cancellation point.
            break
        if _is_cancelled(entry):
            candidate = name  # keep walking; may find a Baierbrunn-er hit
            continue
        # Entry present but not cancelled (delay only) → train ran here → stop.
        break
    return candidate
```

#### Step 8.4 — Run, verify pass

Run: `cd fetcher && uv run pytest tests/test_terminus.py -v`

Expected: ALL PASS.

#### Step 8.5 — Commit

```bash
cd fetcher
git add src/s7bb_fetcher/terminus.py tests/test_terminus.py tests/fixtures/empty_fchg.xml
git commit -m "feat(terminus): add drilldown_short_turn reverse ppth walk"
```

---

### Task 9: Terminus module — `list_pending_trains`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/terminus.py`
- Modify: `fetcher/tests/test_terminus.py`

#### Step 9.1 — Write failing tests

- [ ] **Append to `fetcher/tests/test_terminus.py`:**

```python
from s7bb_fetcher.parser import ArrivalRecord
from s7bb_fetcher.storage import open_db, upsert_records


def _arr(**kw) -> ArrivalRecord:
    defaults = dict(
        train_id=kw.get("train_id", "t1"),
        line="S7", station="Baierbrunn", direction="München Hbf Gl.27-36",
        direction_bucket="muenchen",
        scheduled_time="2026-05-05T10:00:00+00:00",
        actual_time="2026-05-05T10:00:00+00:00", delay_minutes=0,
        cancelled=False, reason=None, train_number="6762",
        dp_ppth="Buchenhain|München Hbf Gl.27-36",
    )
    return ArrivalRecord(**{**defaults, **kw})


def test_list_pending_excludes_cancelled(tmp_path):
    from s7bb_fetcher.terminus import list_pending_trains
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [
        _arr(train_id="t1", train_number="A", cancelled=False),
        _arr(train_id="t2", train_number="B", cancelled=True,
             actual_time=None, delay_minutes=None),
    ])
    now = datetime(2026, 5, 5, 10, 5, tzinfo=UTC)
    pending = list_pending_trains(conn, now)
    nums = {p.train_number for p in pending}
    assert nums == {"A"}


def test_list_pending_excludes_terminal_states(tmp_path):
    from s7bb_fetcher.terminus import list_pending_trains
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(train_id="t1", train_number="A")])
    conn.execute("UPDATE arrivals SET terminus_status='arrived'")
    conn.commit()
    now = datetime(2026, 5, 5, 10, 5, tzinfo=UTC)
    assert list_pending_trains(conn, now) == []


def test_list_pending_excludes_null_train_number(tmp_path):
    from s7bb_fetcher.terminus import list_pending_trains
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(train_id="t1", train_number=None)])
    now = datetime(2026, 5, 5, 10, 5, tzinfo=UTC)
    assert list_pending_trains(conn, now) == []


def test_list_pending_window_scope(tmp_path):
    """Window is [now-2h, now+5min]. Older than 2h or in the future > 5min is excluded."""
    from s7bb_fetcher.terminus import list_pending_trains
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [
        _arr(train_id="old",   train_number="A", scheduled_time="2026-05-05T07:00:00+00:00"),  # 3h ago
        _arr(train_id="now",   train_number="B", scheduled_time="2026-05-05T09:30:00+00:00"),  # in window
        _arr(train_id="future",train_number="C", scheduled_time="2026-05-05T11:00:00+00:00"),  # +1h
    ])
    now = datetime(2026, 5, 5, 10, 0, tzinfo=UTC)
    pending = list_pending_trains(conn, now)
    nums = {p.train_number for p in pending}
    assert nums == {"B"}


def test_list_pending_returns_dataclass_fields(tmp_path):
    from s7bb_fetcher.terminus import list_pending_trains
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(train_id="t1", train_number="A",
                                dp_ppth="X|München Hbf Gl.27-36")])
    now = datetime(2026, 5, 5, 10, 5, tzinfo=UTC)
    [p] = list_pending_trains(conn, now)
    assert p.train_number == "A"
    assert p.direction_bucket == "muenchen"
    assert p.dp_ppth == "X|München Hbf Gl.27-36"
```

#### Step 9.2 — Run, expect failure

Run: `cd fetcher && uv run pytest tests/test_terminus.py -k list_pending -v`

Expected: FAIL — `list_pending_trains` not defined.

#### Step 9.3 — Implement `list_pending_trains`

- [ ] **Append to `fetcher/src/s7bb_fetcher/terminus.py`:**

```python
def list_pending_trains(
    conn: sqlite3.Connection, now: datetime
) -> list[PendingTrain]:
    """Return Baierbrunn rows still awaiting terminus classification.

    Window: [now - 2h, now + 5min]. Older trains are written off (next
    cycle won't classify them — terminus feed has rolled past); +5min lets
    early-departing trains that are seconds ahead of the clock still match.
    """
    lo = (now - timedelta(hours=2)).isoformat()
    hi = (now + timedelta(minutes=5)).isoformat()
    cur = conn.execute(
        """
        SELECT train_number, scheduled_time, direction_bucket, dp_ppth
          FROM arrivals
         WHERE terminus_status = 'pending'
           AND cancelled = 0
           AND train_number IS NOT NULL
           AND scheduled_time BETWEEN ? AND ?
        """,
        (lo, hi),
    )
    return [
        PendingTrain(
            train_number=row[0],
            scheduled_time=row[1],
            direction_bucket=row[2],
            dp_ppth=row[3] or "",
        )
        for row in cur.fetchall()
    ]
```

#### Step 9.4 — Run, verify pass

Run: `cd fetcher && uv run pytest tests/test_terminus.py -v`

Expected: ALL PASS.

#### Step 9.5 — Commit

```bash
cd fetcher
git add src/s7bb_fetcher/terminus.py tests/test_terminus.py
git commit -m "feat(terminus): add list_pending_trains with 2h+5min window"
```

---

### Task 10: Terminus module — `update_terminus_for_window` orchestrator and EVA-mismatch streak

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/terminus.py`
- Modify: `fetcher/tests/test_terminus.py`

#### Step 10.1 — Write failing tests

- [ ] **Append to `fetcher/tests/test_terminus.py`:**

```python
def test_update_terminus_for_window_writes_arrived(tmp_path):
    from s7bb_fetcher.terminus import update_terminus_for_window
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(
        train_id="t1", train_number="6762",
        scheduled_time="2026-05-05T10:30:00+00:00",
    )])
    client = _FakeClient({"8000261": "terminus_munich_arrived"})
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    n = update_terminus_for_window(conn, client, now=now)
    assert n == 1
    row = conn.execute(
        "SELECT terminus_status, terminus_delay_minutes FROM arrivals"
    ).fetchone()
    assert row == ("arrived", 0)


def test_update_terminus_for_window_skips_quiet_directions(tmp_path):
    """Only directions with pending trains are polled. With one Wolfratshausen-
    bound pending train, München's /fchg must not be fetched."""
    from s7bb_fetcher.terminus import update_terminus_for_window
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(
        train_id="t1", train_number="6763",
        direction="Wolfratshausen", direction_bucket="wolfratshausen",
        dp_ppth="Hohenschäftlarn|Wolfratshausen",
        scheduled_time="2026-05-05T10:30:00+00:00",
    )])
    client = _FakeClient({"8006550": "terminus_wolfratshausen_arrived"})
    # München (8000261) is NOT in the mapping; if it were fetched the
    # _FakeClient would assert. The test passes iff it isn't fetched.
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    n = update_terminus_for_window(conn, client, now=now)
    assert n == 1
    assert "8000261" not in client.calls


def test_update_terminus_for_window_logs_zero_match_streak(tmp_path, caplog):
    """3 consecutive zero-match cycles with non-empty pending list logs a WARN
    about possible EVA mismatch; the streak is persisted to terminus_health."""
    from s7bb_fetcher.terminus import update_terminus_for_window
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(
        train_id="t1", train_number="9999",  # not in fixture → zero match
        scheduled_time="2026-05-05T10:30:00+00:00",
    )])
    client = _FakeClient({"8000261": "terminus_munich_arrived"})  # has 6762, not 9999
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)

    with caplog.at_level("WARNING"):
        update_terminus_for_window(conn, client, now=now)
        update_terminus_for_window(conn, client, now=now)
        update_terminus_for_window(conn, client, now=now)

    streak = conn.execute(
        "SELECT zero_match_streak FROM terminus_health WHERE eva='8000261'"
    ).fetchone()
    assert streak[0] == 3
    assert any("0 matches against eva=8000261" in r.message for r in caplog.records)


def test_update_terminus_for_window_resets_streak_on_match(tmp_path):
    from s7bb_fetcher.terminus import update_terminus_for_window
    conn = open_db(tmp_path / "t.db")
    # First: zero-match cycle (train_number 9999 not in fixture)
    upsert_records(conn, [_arr(
        train_id="t-miss", train_number="9999",
        scheduled_time="2026-05-05T10:30:00+00:00",
    )])
    client = _FakeClient({"8000261": "terminus_munich_arrived"})
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    update_terminus_for_window(conn, client, now=now)
    # Then: matching cycle (6762 is in the fixture)
    upsert_records(conn, [_arr(
        train_id="t-hit", train_number="6762",
        scheduled_time="2026-05-05T10:35:00+00:00",
    )])
    update_terminus_for_window(conn, client, now=now)
    streak = conn.execute(
        "SELECT zero_match_streak FROM terminus_health WHERE eva='8000261'"
    ).fetchone()
    assert streak[0] == 0


def test_update_terminus_for_window_returns_zero_when_no_pending(tmp_path):
    from s7bb_fetcher.terminus import update_terminus_for_window
    conn = open_db(tmp_path / "t.db")
    client = _FakeClient({})  # nothing should be fetched
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    assert update_terminus_for_window(conn, client, now=now) == 0
    assert client.calls == []
```

#### Step 10.2 — Run, expect failure

Run: `cd fetcher && uv run pytest tests/test_terminus.py -k update_terminus_for_window -v`

Expected: FAIL — `update_terminus_for_window` not defined.

#### Step 10.3 — Implement `update_terminus_for_window`

- [ ] **Append to `fetcher/src/s7bb_fetcher/terminus.py`:**

```python
ZERO_MATCH_WARN_THRESHOLD = 3


def _record_health(
    conn: sqlite3.Connection, eva: str, *, pending_count: int, match_count: int, now: datetime
) -> None:
    """Increment/reset zero-match streak per terminus EVA."""
    if pending_count == 0:
        return  # quiet cycle isn't evidence of mismatch
    if match_count > 0:
        conn.execute(
            """
            INSERT INTO terminus_health (eva, zero_match_streak, updated_at)
            VALUES (?, 0, ?)
            ON CONFLICT(eva) DO UPDATE SET zero_match_streak=0, updated_at=excluded.updated_at
            """,
            (eva, now.isoformat()),
        )
        conn.commit()
        return
    cur = conn.execute(
        "SELECT zero_match_streak FROM terminus_health WHERE eva=?", (eva,)
    ).fetchone()
    streak = (cur[0] if cur else 0) + 1
    conn.execute(
        """
        INSERT INTO terminus_health (eva, zero_match_streak, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(eva) DO UPDATE SET
            zero_match_streak = excluded.zero_match_streak,
            updated_at = excluded.updated_at
        """,
        (eva, streak, now.isoformat()),
    )
    conn.commit()
    if streak >= ZERO_MATCH_WARN_THRESHOLD:
        log.warning(
            "terminus: 0 matches against eva=%s across %d pending trains for %d consecutive cycles "
            "— possible EVA mismatch",
            eva, pending_count, streak,
        )


def update_terminus_for_window(
    conn: sqlite3.Connection,
    client,
    now: datetime | None = None,
) -> int:
    """Orchestrator: poll terminus feeds, classify pending trains, persist.

    `client` is duck-typed: must expose `fetch_full_changes(eva) -> Element`.
    Returns count of rows actually updated.

    Caller (service.py) wraps this in try/except — a raise here must not
    abort the parent fetch cycle.
    """
    from .storage import update_terminus_fields  # local import: cycle break

    now = now or datetime.now(UTC)
    pending = list_pending_trains(conn, now)
    if not pending:
        return 0

    # Group by direction so we hit each terminus /fchg at most once.
    by_bucket: dict[str, list[PendingTrain]] = {}
    for p in pending:
        by_bucket.setdefault(p.direction_bucket, []).append(p)

    def _drilldown(dp_ppth, train_number):
        return drilldown_short_turn(client, dp_ppth, train_number)

    updates: list[dict] = []
    for bucket, group in by_bucket.items():
        eva = TERMINUS_EVA_FOR_BUCKET.get(bucket)
        if eva is None:
            continue  # 'unknown' bucket — never resolvable
        try:
            feed = client.fetch_full_changes(eva)
        except Exception:
            log.exception("terminus: /fchg %s failed; %d pending stay pending", eva, len(group))
            continue
        idx = build_index(feed)
        match_count = 0
        for p in group:
            entry = idx.get(p.train_number)
            if entry is not None:
                match_count += 1
            update = classify(p, entry, now, drilldown=_drilldown)
            if update is not None:
                updates.append({
                    "train_number": update.train_number,
                    "scheduled_time": update.scheduled_time,
                    "terminus_status": update.terminus_status,
                    "terminus_delay_minutes": update.terminus_delay_minutes,
                    "terminus_short_turn_station": update.terminus_short_turn_station,
                })
        _record_health(conn, eva, pending_count=len(group),
                       match_count=match_count, now=now)

    if not updates:
        return 0
    return update_terminus_fields(conn, updates)
```

#### Step 10.4 — Run, verify pass

Run: `cd fetcher && uv run pytest tests/test_terminus.py -v`

Expected: ALL PASS.

#### Step 10.5 — Commit

```bash
cd fetcher
git add src/s7bb_fetcher/terminus.py tests/test_terminus.py
git commit -m "feat(terminus): orchestrator with per-direction polling and EVA-mismatch alerting"
```

---

### Task 11: Service — wire terminus into `_fetch_job` with isolating try/except

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/service.py` (`_fetch_job` lines 63-75)
- Modify: `fetcher/tests/test_service.py`

#### Step 11.1 — Write failing test

- [ ] **Append to `fetcher/tests/test_service.py` (creating the file content if a test of this shape doesn't already exist):**

```python
def test_terminus_failure_does_not_abort_fetch_job(monkeypatch, tmp_path, caplog):
    """If update_terminus_for_window raises, _fetch_job must still log
    success of the Baierbrunn upsert and return cleanly."""
    from s7bb_fetcher import service
    from s7bb_fetcher.parser import ArrivalRecord

    # Stub the network calls and parser
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(
        "s7bb_fetcher.api.fetch_baierbrunn_now",
        lambda: (object(), object()),
    )
    monkeypatch.setattr(
        "s7bb_fetcher.parser.parse_timetable",
        lambda plan, changes: [ArrivalRecord(
            train_id="t1", line="S7", station="Baierbrunn",
            direction="München Hbf Gl.27-36", direction_bucket="muenchen",
            scheduled_time="2026-05-05T10:00:00+00:00",
            actual_time="2026-05-05T10:00:00+00:00",
            delay_minutes=0, cancelled=False, reason=None, train_number="6762",
            dp_ppth="X|München Hbf Gl.27-36",
        )],
    )
    # Make terminus blow up
    def _boom(*a, **kw):
        raise RuntimeError("terminus failure")
    monkeypatch.setattr("s7bb_fetcher.terminus.update_terminus_for_window", _boom)

    with caplog.at_level("ERROR"):
        service._fetch_job()  # must not raise

    # Baierbrunn row was still committed
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    rows = conn.execute("SELECT train_id FROM arrivals").fetchall()
    assert rows == [("t1",)]
    # Failure was logged
    assert any("terminus" in r.message.lower() for r in caplog.records)
```

#### Step 11.2 — Run, expect failure

Run: `cd fetcher && uv run pytest tests/test_service.py::test_terminus_failure_does_not_abort_fetch_job -v`

Expected: FAIL — `_fetch_job` does not call terminus yet, so no error is logged and the assertion on log content fails.

#### Step 11.3 — Wire into `_fetch_job`

- [ ] **Replace `_fetch_job` in `fetcher/src/s7bb_fetcher/service.py`:**

```python
def _fetch_job() -> None:
    from . import api as _api
    from .parser import parse_timetable
    from .storage import open_db, upsert_records
    from .terminus import update_terminus_for_window

    try:
        plan_xml, changes_xml = _api.fetch_baierbrunn_now()
        records = parse_timetable(plan_xml, changes_xml)
        conn = open_db(DB_PATH)
        n = upsert_records(conn, records)
        logger.info("fetch_job: %d stops, %d upserted", len(records), n)
    except Exception:
        logger.exception("fetch_job failed")
        return

    # Terminus tracking runs in its own try/except so a terminus failure
    # never invalidates the Baierbrunn data we just committed.
    try:
        updated = update_terminus_for_window(conn, _api)
        logger.info("fetch_job: terminus %d rows updated", updated)
    except Exception:
        logger.exception("fetch_job: terminus tracking failed")
```

Notes:
- The `api` module itself satisfies the `client` duck type: `fetch_full_changes(eva)` is `s7bb_fetcher.api.fetch_full_changes`. Passing the module avoids constructing a wrapper.
- The terminus call is **outside** the existing try/except so a terminus failure does not retrigger the "fetch_job failed" branch; spec §Error handling requires Baierbrunn data already committed to be preserved on terminus failure.

#### Step 11.4 — Run, verify pass

Run: `cd fetcher && uv run pytest tests/test_service.py -v`

Expected: ALL PASS.

#### Step 11.5 — Commit

```bash
cd fetcher
git add src/s7bb_fetcher/service.py tests/test_service.py
git commit -m "feat(service): invoke update_terminus_for_window in isolating try/except"
```

---

### Task 12: Exporter — flow terminus fields into `latest.json` and monthly archive

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/exporter.py` (`_query_window` lines 35-51; `export_monthly_archive` SELECT lines 182-191)
- Modify: `fetcher/tests/test_exporter.py`

#### Step 12.1 — Write failing tests

- [ ] **Append to `fetcher/tests/test_exporter.py`:**

```python
from s7bb_fetcher.exporter import export_monthly_archive


def test_latest_json_includes_terminus_fields(populated_db, tmp_path):
    # Seed one row with terminus fields set
    populated_db.execute("""
        UPDATE arrivals
           SET terminus_status='arrived',
               terminus_delay_minutes=3,
               terminus_short_turn_station=NULL
         WHERE train_id='m1'
    """)
    populated_db.commit()

    out = tmp_path / "latest.json"
    export_latest(populated_db, out)
    data = json.loads(out.read_text())
    m1 = next(a for a in data["arrivals"] if a["train_id"] == "m1")
    assert m1["terminus_status"] == "arrived"
    assert m1["terminus_delay_minutes"] == 3
    assert m1["terminus_short_turn_station"] is None
    # Untouched rows still have the keys (with null values)
    other = next(a for a in data["arrivals"] if a["train_id"] != "m1")
    for k in ("terminus_status", "terminus_delay_minutes", "terminus_short_turn_station"):
        assert k in other


def test_monthly_archive_includes_terminus_fields(populated_db, tmp_path):
    populated_db.execute(
        "UPDATE arrivals SET terminus_status='short_turn', "
        "terminus_short_turn_station='München-Solln' WHERE train_id='m1'"
    )
    populated_db.commit()
    today = datetime.now(UTC)
    out = tmp_path / f"{today.year:04d}-{today.month:02d}.json"
    export_monthly_archive(populated_db, today.year, today.month, out)
    data = json.loads(out.read_text())
    m1 = next(a for a in data["arrivals"] if a["train_id"] == "m1")
    assert m1["terminus_status"] == "short_turn"
    assert m1["terminus_short_turn_station"] == "München-Solln"
```

#### Step 12.2 — Run, expect failure

Run: `cd fetcher && uv run pytest tests/test_exporter.py -k terminus -v`

Expected: FAIL — `KeyError: 'terminus_status'`.

#### Step 12.3 — Update both SELECTs

- [ ] **In `fetcher/src/s7bb_fetcher/exporter.py`, replace the SELECT in `_query_window` (lines 36-46):**

```python
def _query_window(conn: sqlite3.Connection, days: int) -> list[dict]:
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    cur = conn.execute(
        """
        SELECT train_id, line, station, direction, direction_bucket, scheduled_time,
               actual_time, delay_minutes, cancelled, reason, train_number,
               terminus_status, terminus_delay_minutes, terminus_short_turn_station
        FROM arrivals
        WHERE scheduled_time >= ?
        ORDER BY scheduled_time, train_id
        """,
        (since,),
    )
    cols = [d[0] for d in cur.description]
    out = [dict(zip(cols, row)) for row in cur.fetchall()]
    for r in out:
        r["cancelled"] = bool(r["cancelled"])
    return out
```

- [ ] **And the SELECT in `export_monthly_archive` (lines 182-191):**

```python
    cur = conn.execute(
        """
        SELECT train_id, line, station, direction, direction_bucket, scheduled_time,
               actual_time, delay_minutes, cancelled, reason, train_number,
               terminus_status, terminus_delay_minutes, terminus_short_turn_station
        FROM arrivals
        WHERE scheduled_time >= ? AND scheduled_time < ?
        ORDER BY scheduled_time, train_id
        """,
        (start, end),
    )
```

No other code change needed: `dict(zip(cols, row))` propagates the new columns into `arrivals[]` automatically, and `json.dump` serialises `None` as `null`.

#### Step 12.4 — Run, verify pass

Run: `cd fetcher && uv run pytest tests/test_exporter.py -v`

Expected: ALL PASS.

#### Step 12.5 — Commit

```bash
cd fetcher
git add src/s7bb_fetcher/exporter.py tests/test_exporter.py
git commit -m "feat(exporter): include terminus_status/delay/short_turn in latest + archive JSON"
```

---

### Task 13: Site — extend `Arrival` TS contract with terminus fields

**Files:**
- Modify: `site/src/data.ts` (`Arrival` interface lines 3-15)
- Verify: `cd site && npm run build`

#### Step 13.1 — Add types

- [ ] **In `site/src/data.ts`, add the `TerminusStatus` type and 3 fields:**

Replace lines 1-15 of `site/src/data.ts` with:

```ts
export type DirectionBucket = "muenchen" | "wolfratshausen" | "unknown";

export type TerminusStatus = "arrived" | "short_turn" | "cancelled" | "pending";

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
  terminus_status?: TerminusStatus | null;
  terminus_delay_minutes?: number | null;
  terminus_short_turn_station?: string | null;
}
```

The fields are `?` (optional, may be absent on legacy fixtures) **and** `| null` (Phase 1 always emits the keys, but values are nullable per the spec §Data flow JSON example).

#### Step 13.2 — Type-check the site

- [ ] **Run:**

```bash
cd site && npm run build
```

Expected: build succeeds. No site code references the new fields yet (Phase 2), so existing tests do not need updates.

#### Step 13.3 — Commit

```bash
cd site
git add src/data.ts
git commit -m "feat(site): extend Arrival TS contract with terminus fields (data only)"
```

---

### Task 14: Self-test — full backend dry run against fixtures

This task does not modify code. It runs everything one more time end-to-end to catch integration regressions before changelog/release.

#### Step 14.1 — Run the full test suite

- [ ] **Run:**

```bash
cd fetcher && uv run pytest -v
```

Expected: ALL PASS, no warnings about deprecated APIs in the new code.

#### Step 14.2 — Lint

- [ ] **Run:**

```bash
cd fetcher && uv run ruff check src tests
```

Expected: no findings.

#### Step 14.3 — Site type-check + lint

- [ ] **Run:**

```bash
cd site && npm run build && npm run lint
```

Expected: both succeed.

#### Step 14.4 — Spot-check JSON shape

- [ ] **From the populated test DB context, ensure `latest.json` carries the new keys for both terminal-state and pending rows.** This is already locked by `test_latest_json_includes_terminus_fields` (Task 12), so no new test is required.

---

### Task 15: CHANGELOG entry

**Files:**
- Modify: `CHANGELOG.md`

#### Step 15.1 — Read current CHANGELOG head

- [ ] **Open `CHANGELOG.md` and locate the `## [Unreleased]` section (or the most recent `## [X.Y.Z]` header if no `[Unreleased]` exists).**

#### Step 15.2 — Append the entry

- [ ] **Under `## [Unreleased]` → `### Added`, append:**

```markdown
- Backend tracking of S7 terminus arrivals (München Hbf Gl.27-36 /
  Wolfratshausen). Each Baierbrunn departure is now classified per cycle
  as `arrived` (with delay), `short_turn` (with station), `cancelled`, or
  `pending`. Data is exposed as three new optional+nullable fields on
  every arrival in `latest.json` and the monthly archives:
  `terminus_status`, `terminus_delay_minutes`,
  `terminus_short_turn_station`. UI rendering is Phase 2 and intentionally
  not part of this release.
```

If no `## [Unreleased]` block exists, create one above the most recent versioned section. Match the existing Keep a Changelog formatting.

#### Step 15.3 — Commit

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): record terminus arrival tracking (phase 1)"
```

---

### Task 16: Plan and spec files are committed

The plan file (this document) and the spec file (`docs/superpowers/specs/2026-05-22-terminus-tracking-design.md`) must be in the same PR as the implementation. CLAUDE.md §Plan files: "Plan files written to `docs/superpowers/plans/YYYY-MM-DD-*.md` … Always commit them — bundle into the implementation PR."

- [ ] **Run:**

```bash
git status -- docs/superpowers/
```

If either file is untracked, stage and commit:

```bash
git add docs/superpowers/plans/2026-05-22-terminus-tracking.md \
        docs/superpowers/specs/2026-05-22-terminus-tracking-design.md
git commit -m "docs(spec): terminus tracking phase 1 plan"
```

---

### Task 17: Open the PR

#### Step 17.1 — Push and open

- [ ] **Run:**

```bash
git push -u origin <branch-name>
gh pr create --title "feat: terminus arrival tracking (phase 1)" --body "$(cat <<'EOF'
## Summary
- Backend-only: schema, fetcher, exporter, JSON contract for tracking whether
  each S7 train reaches its terminus on time, late, short-turned, or cancelled.
- New `terminus.py` module polls terminus `/fchg` once per direction per
  cycle, matches by `train_number`, drills down `dp.ppth` reverse on
  cancellation/missing-past-cutoff.
- No UI rendering — Phase 2 follows separately, mirroring the train_number
  rollout pattern (PR #45 → v0.6.0).

Spec: docs/superpowers/specs/2026-05-22-terminus-tracking-design.md
Plan: docs/superpowers/plans/2026-05-22-terminus-tracking.md

## Test plan
- [ ] `cd fetcher && uv run pytest` passes
- [ ] `cd fetcher && uv run ruff check src tests` clean
- [ ] `cd site && npm run build && npm run lint` clean
- [ ] After merge: VM `git pull && docker compose up -d`; verify migration
      adds 4 arrivals columns + `terminus_health` table; verify within
      ~30 min that `SELECT terminus_status, COUNT(*) FROM arrivals
      GROUP BY terminus_status` shows non-zero `arrived`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

#### Step 17.2 — Post-merge: release

Per CLAUDE.md §Post-merge release trigger, a `feat:` PR triggers a MINOR
release. After merge:

- [ ] Bump `fetcher/pyproject.toml` version to next MINOR (e.g. `0.6.0` → `0.7.0`)
- [ ] `cd fetcher && uv sync --no-dev` to refresh `uv.lock`
- [ ] Rename `[Unreleased]` to `[0.7.0] - 2026-05-22` (use actual merge date) in `CHANGELOG.md`
- [ ] `git commit -am "chore(release): 0.7.0"`
- [ ] `git tag v0.7.0 && git push origin main v0.7.0`
- [ ] `gh release create v0.7.0 --title "v0.7.0" --latest --notes-file <(awk '/^## \[0\.7\.0\]/,/^## \[/' CHANGELOG.md | sed '$d')` — verify body is non-empty before considering done (see [[feedback_release_awk]]).

---

## Verification (manual, post-deploy)

Mirrors spec §Verification. After the VM has pulled the release and the
container has restarted:

1. **Migration:** `sqlite3 /data/s7bb.db ".schema arrivals"` shows 4 new columns; `.schema terminus_health` exists.
2. **Seed:** `sqlite3 /data/s7bb.db "SELECT COUNT(*) FROM arrivals WHERE terminus_status='pending'"` > 0 after one fetch cycle; cancelled rows are `NULL`.
3. **Match:** after ~30 min, `SELECT terminus_status, COUNT(*) FROM arrivals GROUP BY terminus_status` shows non-zero `arrived`.
4. **Delay:** spot-check a row where Baierbrunn `actual_time != scheduled_time` — `terminus_delay_minutes` is set and of similar magnitude.
5. **Short-turn:** wait for organic event (rare); `terminus_status='short_turn'` with a non-NULL station drawn from that train's `dp_ppth`.
6. **Export:** `latest.json` arrivals[0] carries the 3 new keys.
7. **TS build:** site build green with the new optional fields.
8. **Logs:** `journalctl … | grep terminus` — INFO lines, no ERROR; no `0 matches against eva=… for 3 consecutive cycles` warning (would indicate EVA mismatch).
9. **Quota:** DB API rate-limit headers ≈ 2–4× previous baseline. No 429s.
