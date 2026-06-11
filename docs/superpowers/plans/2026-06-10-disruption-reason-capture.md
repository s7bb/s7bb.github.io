# Disruption Reason Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture the real disruption reason (HIM category + window + delay-cause code) for every disrupted S7 train at Baierbrunn, store it richly in `latest.json`, and render a compact tap-to-expand badge in the web UI.

**Architecture:** `/fchg` XML `<m>` elements -> parser extracts a `Disruption` sub-object (category + cause_code + window) -> storage persists 4 sticky `COALESCE` columns -> exporter assembles a nested `disruption` JSON object (decoding the cause code to German text) -> UI renders a reduced badge with progressive disclosure. The JSON is the canonical rich source of truth; the UI is a thin projection. The legacy always-`NULL` `reason` field is retired from export but left inert in the schema.

**Tech Stack:** Python 3 + lxml (fetcher), SQLite, TypeScript + Vite (site), pytest + vitest.

---

## Background the implementer needs

**Source spec:** `docs/superpowers/specs/2026-06-10-disruption-reason-capture-design.md`. Read it once before starting; it has the live `/fchg` XML sample and the error-handling matrix this plan implements.

**The two `<m>` element levels (do not confuse them):**

```xml
<s id="..." eva="8004154">
  <m id="r2635205" t="h" from="2606100619" to="2606100830" cat="Störung" pr="1"/>  <!-- trip-level, direct child of <s> -->
  <ar cpth="" ct="2606100735" cs="c" l="S7">
    <m id="r59585930" t="d" c="34"/>   <!-- stop-level delay-cause, child of <ar>/<dp> -->
    <m id="r59586864" t="f" c="0"/>    <!-- noise, ignored -->
  </ar>
</s>
```

- `t="h"` is a **direct child of `<s>`** -> carries `cat` (category) + `from`/`to` (window).
- `t="d"` is a **child of `<ar>`/`<dp>`** -> carries numeric cause `c` code.
- `t="f"` and any `c="0"` -> noise, ignore.

**Key file paths (verified):**
- Parser: `fetcher/src/s7bb_fetcher/parser.py`
- Storage: `fetcher/src/s7bb_fetcher/storage.py`
- Exporter: `fetcher/src/s7bb_fetcher/exporter.py`
- New decode module: `fetcher/src/s7bb_fetcher/cause_codes.py`
- Site types/helpers: `site/src/data.ts` (has `escapeHtml`)
- Today render: `site/src/pages/today.ts`
- Stats render: `site/src/pages/stats.ts`

**Test commands:**
- Python: `cd fetcher && uv run pytest tests/test_parser.py -v` (or the specific test path)
- Python lint: `cd fetcher && uv run ruff check src tests`
- Site: `cd site && npm run test` (vitest) and `npm run build` (type-check)

**Conventions:** deps pinned `=X.Y.Z`; no em-dashes anywhere; UI text German, code/comments English; Conventional Commits.

---

## File Structure

**Create:**
- `fetcher/src/s7bb_fetcher/cause_codes.py` - delay-cause code -> German text decode table + `decode_cause()`.
- `fetcher/tests/test_cause_codes.py` - decode table tests.

**Modify:**
- `fetcher/src/s7bb_fetcher/parser.py` - add `Disruption` dataclass + `extract_disruption()`; stop setting `reason`.
- `fetcher/src/s7bb_fetcher/storage.py` - 4 new sticky columns + migration + upsert wiring.
- `fetcher/src/s7bb_fetcher/exporter.py` - select new columns, assemble nested `disruption`, drop `reason`.
- `fetcher/tests/test_parser.py` - disruption extraction tests + fixtures.
- `fetcher/tests/test_exporter.py` - nested object + decode + `reason` absent tests.
- `fetcher/tests/test_storage.py` - sticky `COALESCE` persistence test.
- `site/src/data.ts` - `Disruption` interface, add `disruption` to `Arrival`, remove `reason`.
- `site/src/pages/today.ts` - disruption badge + expand detail; drop `reason`.
- `site/src/pages/stats.ts` - top-reasons box from `disruption`.
- `site/src/data.test.ts`, `site/src/pages/today.test.ts`, `site/src/pages/stats.test.ts`, `site/src/pages/archive-detail.test.ts` - update fixtures/assertions.

---

## Task 1: Parser - `Disruption` dataclass + `extract_disruption()`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/parser.py`
- Test: `fetcher/tests/test_parser.py`

- [ ] **Step 1: Write failing tests**

Append to `fetcher/tests/test_parser.py`:

```python
from s7bb_fetcher.parser import Disruption, extract_disruption


def _s(xml: str) -> etree._Element:
    return etree.fromstring(xml)


def test_extract_trip_level_him_category_and_window():
    s = _s(
        '<s id="x">'
        '<m id="r1" t="h" from="2606100619" to="2606100830" cat="Störung" pr="1"/>'
        '<ar ct="2606100735" cs="c" l="S7"/>'
        '</s>'
    )
    d = extract_disruption(s)
    assert d.category == "Störung"
    # 2606100619 Europe/Berlin (CEST, +02:00) -> 04:19 UTC
    assert d.window_from == "2026-06-10T04:19:00+00:00"
    assert d.window_to == "2026-06-10T06:30:00+00:00"


def test_extract_stop_level_cause_code():
    s = _s(
        '<s id="x"><ar l="S7">'
        '<m id="r2" t="d" c="34"/>'
        '<m id="r3" t="f" c="0"/>'
        '</ar></s>'
    )
    d = extract_disruption(s)
    assert d.cause_code == 34
    assert d.category is None


def test_extract_ignores_f_and_zero_codes():
    s = _s('<s id="x"><dp l="S7"><m t="f" c="0"/><m t="d" c="0"/></dp></s>')
    assert extract_disruption(s) is None


def test_extract_ar_wins_over_dp_for_cause_code():
    s = _s(
        '<s id="x">'
        '<ar l="S7"><m t="d" c="34"/></ar>'
        '<dp l="S7"><m t="d" c="44"/></dp>'
        '</s>'
    )
    assert extract_disruption(s).cause_code == 34


def test_extract_none_when_no_messages():
    s = _s('<s id="x"><ar l="S7"/><dp l="S7"/></s>')
    assert extract_disruption(s) is None


def test_extract_malformed_window_bound_becomes_none():
    s = _s('<s id="x"><m t="h" from="garbage" to="2606100830" cat="Störung"/></s>')
    d = extract_disruption(s)
    assert d.category == "Störung"
    assert d.window_from is None
    assert d.window_to == "2026-06-10T06:30:00+00:00"
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd fetcher && uv run pytest tests/test_parser.py -k extract -v`
Expected: FAIL with `ImportError: cannot import name 'Disruption'`.

- [ ] **Step 3: Add `Disruption` dataclass**

In `fetcher/src/s7bb_fetcher/parser.py`, after the `ArrivalRecord` dataclass (after line 30), add:

```python
@dataclass
class Disruption:
    category: str | None = None       # HIM category, e.g. "Störung"
    cause_code: int | None = None     # DB delay-cause code, e.g. 34
    window_from: str | None = None    # ISO8601 UTC
    window_to: str | None = None      # ISO8601 UTC
```

- [ ] **Step 4: Add `extract_disruption()` helper**

Add after `classify_direction` (after line 69):

```python
def _safe_db_time(raw: str | None) -> str | None:
    """Parse a DB YYMMDDHHMM bound to ISO UTC, or None if absent/malformed."""
    if not raw:
        return None
    try:
        return _iso(_parse_db_time(raw))
    except ValueError:
        return None


def extract_disruption(change_stop: etree._Element) -> Disruption | None:
    """Build a Disruption from an <s> change element, or None if no usable
    message exists. Category + window come from the trip-level <m t="h">
    (direct child of <s>); cause_code from the first non-zero stop-level
    <m t="d"> on <ar> then <dp> (fixed scan order for determinism)."""
    category: str | None = None
    window_from: str | None = None
    window_to: str | None = None

    him = change_stop.find("m[@t='h']")
    if him is not None:
        category = him.get("cat")
        window_from = _safe_db_time(him.get("from"))
        window_to = _safe_db_time(him.get("to"))

    cause_code: int | None = None
    for parent_tag in ("ar", "dp"):           # ar first, then dp (deterministic)
        parent = change_stop.find(parent_tag)
        if parent is None:
            continue
        for m in parent.findall("m[@t='d']"):
            raw = m.get("c")
            if raw and raw != "0":
                try:
                    cause_code = int(raw)
                except ValueError:
                    continue
                break
        if cause_code is not None:
            break

    if category is None and cause_code is None:
        return None
    return Disruption(
        category=category,
        cause_code=cause_code,
        window_from=window_from,
        window_to=window_to,
    )
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `cd fetcher && uv run pytest tests/test_parser.py -k extract -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add fetcher/src/s7bb_fetcher/parser.py fetcher/tests/test_parser.py
git commit -m "feat(parser): extract disruption category, window, cause code from /fchg"
```

---

## Task 2: Parser - wire `disruption` into `ArrivalRecord`, retire `reason`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/parser.py`
- Test: `fetcher/tests/test_parser.py`

- [ ] **Step 1: Write failing tests**

Append to `fetcher/tests/test_parser.py`:

```python
def test_parse_sets_disruption_on_disrupted_row(tmp_path):
    # Reuse existing fixtures: build a changes XML carrying an HIM + cause code
    # for an existing plan trip id.
    plan = _load("plan.xml")
    sid = "trip-S7-001-2605051200"
    changes = _s(
        f'<timetable><s id="{sid}">'
        '<m t="h" from="2605051150" to="2605051300" cat="Störung"/>'
        '<ar l="S7"><m t="d" c="34"/></ar>'
        '<dp l="S7" ct="2605051207"/>'
        '</s></timetable>'
    )
    records = parse_timetable(plan, changes)
    r = next(r for r in records if r.train_id == sid)
    assert r.disruption is not None
    assert r.disruption.category == "Störung"
    assert r.disruption.cause_code == 34
    assert r.reason is None  # legacy field retired, always None


def test_parse_disruption_none_for_on_time():
    records = parse_timetable(_load("plan.xml"), _load("changes_empty.xml"))
    on_time = next(r for r in records if r.train_id == "trip-S7-002-2605051230")
    assert on_time.disruption is None
    assert on_time.reason is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd fetcher && uv run pytest tests/test_parser.py -k "disruption_on_disrupted or disruption_none_for" -v`
Expected: FAIL with `AttributeError: 'ArrivalRecord' object has no attribute 'disruption'`.

- [ ] **Step 3: Add `disruption` field to `ArrivalRecord`**

In `parser.py`, in the `ArrivalRecord` dataclass add after the `dp_ppth` field (line 30):

```python
    disruption: "Disruption | None" = None
```

(Keep the existing `reason: str | None` field unchanged - it stays for the storage write path but is always `None`.)

- [ ] **Step 4: Replace reason extraction with disruption extraction**

In `parse_timetable`, replace lines 137-140:

```python
            if cdp is not None:
                reason = cdp.get("m") or cdp.get("msc")
            if reason is None and car is not None:
                reason = car.get("m") or car.get("msc")
```

with:

```python
            disruption = extract_disruption(change_stop)
```

Then declare `disruption` alongside the other defaults. Change line 123 from:

```python
        reason: str | None = None
```

to:

```python
        reason: str | None = None
        disruption: Disruption | None = None
```

And in the `records.append(ArrivalRecord(...))` call (lines 150-163), the `reason=reason` line stays (now always `None`), and add after `dp_ppth=dp_ppth,`:

```python
            disruption=disruption,
```

- [ ] **Step 5: Run full parser suite, verify pass**

Run: `cd fetcher && uv run pytest tests/test_parser.py -v`
Expected: PASS (all existing + new). `reason` is now always `None`; confirm no existing test asserted a non-null `reason` (none do - they only pass `reason=None`).

- [ ] **Step 6: Commit**

```bash
git add fetcher/src/s7bb_fetcher/parser.py fetcher/tests/test_parser.py
git commit -m "feat(parser): populate ArrivalRecord.disruption, retire reason to None"
```

---

## Task 3: Storage - sticky disruption columns

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/storage.py`
- Test: `fetcher/tests/test_storage.py`

- [ ] **Step 1: Write failing test**

Append to `fetcher/tests/test_storage.py`:

```python
from s7bb_fetcher.parser import Disruption


def _arr(train_id, scheduled, **kw):
    defaults = dict(
        line="S7", station="Baierbrunn", direction="Wolfratshausen",
        direction_bucket="wolfratshausen", actual_time=scheduled,
        delay_minutes=0, cancelled=False, reason=None,
    )
    return ArrivalRecord(train_id=train_id, scheduled_time=scheduled, **{**defaults, **kw})


def test_disruption_columns_persist_and_are_sticky(tmp_path):
    conn = open_db(tmp_path / "t.db")
    # First upsert: full disruption captured.
    upsert_records(conn, [_arr(
        "d1", "2026-06-10T08:00:00+00:00",
        disruption=Disruption(category="Störung", cause_code=34,
                              window_from="2026-06-10T04:19:00+00:00",
                              window_to="2026-06-10T06:30:00+00:00"),
    )])
    # Refetch after window rolled off: disruption is None -> must NOT wipe.
    upsert_records(conn, [_arr("d1", "2026-06-10T08:00:00+00:00", disruption=None)])
    row = conn.execute(
        "SELECT disruption_category, disruption_cause_code, "
        "disruption_window_from, disruption_window_to FROM arrivals "
        "WHERE train_id='d1'"
    ).fetchone()
    assert row == ("Störung", 34, "2026-06-10T04:19:00+00:00", "2026-06-10T06:30:00+00:00")


def test_disruption_cause_code_refines_on_non_null(tmp_path):
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr("d2", "2026-06-10T08:00:00+00:00", disruption=None)])
    upsert_records(conn, [_arr(
        "d2", "2026-06-10T08:00:00+00:00",
        disruption=Disruption(cause_code=44),
    )])
    code = conn.execute(
        "SELECT disruption_cause_code FROM arrivals WHERE train_id='d2'"
    ).fetchone()[0]
    assert code == 44
```

Ensure `from s7bb_fetcher.parser import ArrivalRecord` is present at the top of `test_storage.py` (add if missing).

- [ ] **Step 2: Run test, verify it fails**

Run: `cd fetcher && uv run pytest tests/test_storage.py -k disruption -v`
Expected: FAIL with `sqlite3.OperationalError: no such column: disruption_category`.

- [ ] **Step 3: Add columns to `SCHEMA`**

In `storage.py`, in the `CREATE TABLE` (after `dp_ppth TEXT` on line 27), add:

```python
    disruption_category          TEXT,
    disruption_cause_code        INTEGER,
    disruption_window_from       TEXT,
    disruption_window_to         TEXT
```

(Add a trailing comma to the previous `dp_ppth TEXT` line.)

- [ ] **Step 4: Add forward migration ALTERs**

In `_migrate`, extend the `for col, ddl in (...)` tuple (lines 54-63) with four more entries before the closing `):`:

```python
        ("disruption_category",
         "ALTER TABLE arrivals ADD COLUMN disruption_category TEXT"),
        ("disruption_cause_code",
         "ALTER TABLE arrivals ADD COLUMN disruption_cause_code INTEGER"),
        ("disruption_window_from",
         "ALTER TABLE arrivals ADD COLUMN disruption_window_from TEXT"),
        ("disruption_window_to",
         "ALTER TABLE arrivals ADD COLUMN disruption_window_to TEXT"),
```

- [ ] **Step 5: Wire columns through the upsert**

In `upsert_records`, change the row tuple builder (lines 102-111) to unpack disruption fields. Replace the comprehension with:

```python
    def _d(r: ArrivalRecord):
        d = r.disruption
        return (d.category, d.cause_code, d.window_from, d.window_to) if d else (None, None, None, None)

    rows = [
        (
            r.train_id, r.line, r.station, r.direction, r.direction_bucket,
            r.scheduled_time, r.actual_time, r.delay_minutes,
            1 if r.cancelled else 0, r.reason, r.train_number, now,
            None if r.cancelled else "pending",  # initial terminus_status
            r.dp_ppth or None,
            *_d(r),
        )
        for r in records
    ]
```

Update the `INSERT` column list (line 114-117) to append the four columns and four placeholders. Replace the INSERT/VALUES head:

```python
        INSERT INTO arrivals
            (train_id, line, station, direction, direction_bucket, scheduled_time,
             actual_time, delay_minutes, cancelled, reason, train_number, fetched_at,
             terminus_status, dp_ppth,
             disruption_category, disruption_cause_code,
             disruption_window_from, disruption_window_to)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

In the `ON CONFLICT ... DO UPDATE SET` block, add four sticky `COALESCE` lines after the `terminus_short_turn_station = ...` line (after line 135). Add a comma to the prior line:

```python
            terminus_short_turn_station  = CASE WHEN excluded.cancelled = 1
                                               THEN NULL ELSE terminus_short_turn_station END,
            disruption_category    = COALESCE(excluded.disruption_category, disruption_category),
            disruption_cause_code  = COALESCE(excluded.disruption_cause_code, disruption_cause_code),
            disruption_window_from = COALESCE(excluded.disruption_window_from, disruption_window_from),
            disruption_window_to   = COALESCE(excluded.disruption_window_to, disruption_window_to)
```

- [ ] **Step 6: Run storage suite, verify pass**

Run: `cd fetcher && uv run pytest tests/test_storage.py -v`
Expected: PASS (existing + 2 new).

- [ ] **Step 7: Commit**

```bash
git add fetcher/src/s7bb_fetcher/storage.py fetcher/tests/test_storage.py
git commit -m "feat(storage): add sticky disruption columns with COALESCE upsert"
```

---

## Task 4: `cause_codes.py` decode module

**Files:**
- Create: `fetcher/src/s7bb_fetcher/cause_codes.py`
- Test: `fetcher/tests/test_cause_codes.py`

- [ ] **Step 1: Write failing test**

Create `fetcher/tests/test_cause_codes.py`:

```python
from s7bb_fetcher.cause_codes import decode_cause


def test_known_code_decodes():
    assert decode_cause(34) == "Verspätung eines vorausfahrenden Zuges"


def test_unknown_code_returns_none():
    assert decode_cause(99999) is None


def test_none_returns_none():
    assert decode_cause(None) is None
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd fetcher && uv run pytest tests/test_cause_codes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 's7bb_fetcher.cause_codes'`.

- [ ] **Step 3: Create the module (confirmed codes only)**

Create `fetcher/src/s7bb_fetcher/cause_codes.py`:

```python
"""Decode DB Timetables delay-cause (Verspätungsursachen) codes to German text.

Lives in code (not the DB) so extending this table re-decodes all historical
rows at export time. Unknown code -> None; the raw cause_code is still emitted
by the exporter, so no information is lost.

Only codes whose meaning is confirmed against the DB Verspätungsursachen
reference are listed. Omit (number-fallback) rather than guess (see spec).
"""

CAUSE_CODES: dict[int, str] = {
    34: "Verspätung eines vorausfahrenden Zuges",
    # Codes 43, 44, 48 observed in production but not yet confirmed - see Step 4.
}


def decode_cause(code: int | None) -> str | None:
    if code is None:
        return None
    return CAUSE_CODES.get(code)
```

- [ ] **Step 4: Resolve observed codes 43, 44, 48 against the DB reference**

This is a research action, not a placeholder. Look up codes 43, 44, 48 in the DB Timetables Verspätungsursachen list:
- Check `docs/` for any existing cause-code reference first.
- Otherwise consult the DB API Marketplace Timetables docs (the published Verspätungsursachen / delay-cause catalogue).

For each code you can **confirm**, add a `CODE: "exact German text",` line to `CAUSE_CODES`. For any code you **cannot** confirm, leave it out (it falls back to the raw number in the UI). Do not guess strings.

- [ ] **Step 5: Run test, verify pass**

Run: `cd fetcher && uv run pytest tests/test_cause_codes.py -v && uv run ruff check src tests`
Expected: PASS (3 tests), lint clean.

- [ ] **Step 6: Commit**

```bash
git add fetcher/src/s7bb_fetcher/cause_codes.py fetcher/tests/test_cause_codes.py
git commit -m "feat(fetcher): add cause-code decode table"
```

---

## Task 5: Exporter - assemble nested `disruption`, drop `reason`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/exporter.py`
- Test: `fetcher/tests/test_exporter.py`

- [ ] **Step 1: Write failing tests**

Append to `fetcher/tests/test_exporter.py`:

```python
from s7bb_fetcher.parser import Disruption


def test_disruption_object_assembled(populated_db, tmp_path):
    upsert_records(populated_db, [_make_arrival(
        "dx", _de_today_iso(9, 0), "muenchen",
        disruption=Disruption(category="Störung", cause_code=34,
                              window_from="2026-06-10T04:19:00+00:00",
                              window_to="2026-06-10T06:30:00+00:00"),
    )])
    out = tmp_path / "latest.json"
    export_latest(populated_db, out)
    data = json.loads(out.read_text())
    row = next(a for a in data["arrivals"] if a["train_id"] == "dx")
    assert row["disruption"] == {
        "category": "Störung",
        "cause_code": 34,
        "cause_text": "Verspätung eines vorausfahrenden Zuges",
        "window": {"from": "2026-06-10T04:19:00+00:00", "to": "2026-06-10T06:30:00+00:00"},
    }
    assert "reason" not in row


def test_disruption_null_when_clean(populated_db, tmp_path):
    out = tmp_path / "latest.json"
    export_latest(populated_db, out)
    data = json.loads(out.read_text())
    row = next(a for a in data["arrivals"] if a["train_id"] == "m1")
    assert row["disruption"] is None
    assert "reason" not in row


def test_disruption_unknown_code_keeps_number_drops_text(populated_db, tmp_path):
    upsert_records(populated_db, [_make_arrival(
        "dz", _de_today_iso(9, 20), "muenchen",
        disruption=Disruption(cause_code=99999),
    )])
    out = tmp_path / "latest.json"
    export_latest(populated_db, out)
    data = json.loads(out.read_text())
    row = next(a for a in data["arrivals"] if a["train_id"] == "dz")
    assert row["disruption"]["cause_code"] == 99999
    assert row["disruption"]["cause_text"] is None
    assert row["disruption"]["category"] is None
    assert row["disruption"]["window"] is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd fetcher && uv run pytest tests/test_exporter.py -k disruption -v`
Expected: FAIL - `reason` still present / `disruption` key missing.

- [ ] **Step 3: Add a shared row-assembly helper**

In `exporter.py`, add the import at the top (after line 9):

```python
from .cause_codes import decode_cause
```

Add a helper after `_atomic_write_json` (after line 32):

```python
def _attach_disruption(r: dict) -> None:
    """Replace the four disruption_* columns + legacy reason with a nested
    `disruption` object (or None). Mutates r in place."""
    cat = r.pop("disruption_category", None)
    code = r.pop("disruption_cause_code", None)
    wfrom = r.pop("disruption_window_from", None)
    wto = r.pop("disruption_window_to", None)
    r.pop("reason", None)
    if cat is None and code is None:
        r["disruption"] = None
        return
    window = None if (wfrom is None and wto is None) else {"from": wfrom, "to": wto}
    r["disruption"] = {
        "category": cat,
        "cause_code": code,
        "cause_text": decode_cause(code),
        "window": window,
    }
```

- [ ] **Step 4: Update `_query_window` SELECT + assembly**

In `_query_window`, change the SELECT column list (lines 39-41) - replace `reason` with the four columns:

```python
        SELECT train_id, line, station, direction, direction_bucket, scheduled_time,
               actual_time, delay_minutes, cancelled, train_number,
               terminus_status, terminus_delay_minutes, terminus_short_turn_station,
               disruption_category, disruption_cause_code,
               disruption_window_from, disruption_window_to
```

Then in the post-loop (lines 50-52), add the disruption attach:

```python
    for r in out:
        r["cancelled"] = bool(r["cancelled"])
        _attach_disruption(r)
    return out
```

- [ ] **Step 5: Update `export_monthly_archive` SELECT + assembly**

In `export_monthly_archive`, change the SELECT (lines 194-196) the same way (drop `reason`, add the four columns), and update the row post-loop (lines 205-206):

```python
    for r in rows:
        r["cancelled"] = bool(r["cancelled"])
        _attach_disruption(r)
```

- [ ] **Step 6: Run exporter suite, verify pass**

Run: `cd fetcher && uv run pytest tests/test_exporter.py -v && uv run ruff check src tests`
Expected: PASS (existing + 3 new), lint clean.

- [ ] **Step 7: Run the full fetcher suite**

Run: `cd fetcher && uv run pytest`
Expected: PASS (all). This confirms `test_cli.py`, `test_service.py`, `test_terminus.py` still pass with the retired `reason`.

- [ ] **Step 8: Commit**

```bash
git add fetcher/src/s7bb_fetcher/exporter.py fetcher/tests/test_exporter.py
git commit -m "feat(exporter): emit nested disruption object, drop legacy reason"
```

---

## Task 6: Site types - `Disruption` interface

**Files:**
- Modify: `site/src/data.ts`
- Test: `site/src/data.test.ts`

- [ ] **Step 1: Update the fixture in `data.test.ts`**

In `site/src/data.test.ts` line 23, remove the `reason: null,` line from the arrival fixture and add `disruption: null,` in its place. (This keeps the fixture valid against the new `Arrival` type.)

- [ ] **Step 2: Run test, verify it fails to type-check**

Run: `cd site && npm run build`
Expected: FAIL - `'reason' does not exist in type 'Arrival'` once Step 3 lands, or `'disruption'` unknown now. (Order is fine; the build will be green after Step 3.)

- [ ] **Step 3: Add `Disruption` interface, update `Arrival`**

In `site/src/data.ts`, after the `TerminusStatus` type (line 3) add:

```typescript
export interface Disruption {
  category: string | null;
  cause_code: number | null;
  cause_text: string | null;
  window: { from: string | null; to: string | null } | null;
}
```

In the `Arrival` interface, replace line 15 (`reason: string | null;`) with:

```typescript
  disruption?: Disruption | null;
```

- [ ] **Step 4: Run build, verify pass (data.ts compiles)**

Run: `cd site && npm run build`
Expected: type errors only in `today.ts`/`stats.ts` (still reference `reason`) - those are fixed in Tasks 7-8. `data.ts` and `data.test.ts` themselves clean.

- [ ] **Step 5: Commit**

```bash
git add site/src/data.ts site/src/data.test.ts
git commit -m "feat(site): add Disruption type, replace reason on Arrival"
```

---

## Task 7: Today page - disruption badge + expand

**Files:**
- Modify: `site/src/pages/today.ts`
- Test: `site/src/pages/today.test.ts`

- [ ] **Step 1: Write/replace failing tests**

In `site/src/pages/today.test.ts`:
- Update the base `arrival()` fixture (line ~16): remove `reason: null` and add `disruption: null`.
- Replace the three `reason`-based tests (lines ~314-330) with:

```typescript
  it("disruption badge appears in summary row and detail when disruption is set", () => {
    const c = renderInto([arrival({
      terminus_status: "arrived",
      disruption: { category: "Störung", cause_code: 34,
                    cause_text: "Verspätung eines vorausfahrenden Zuges",
                    window: { from: "2026-06-10T04:19:00+00:00", to: "2026-06-10T06:30:00+00:00" } },
    })]);
    expect(c.querySelector(".badge--disruption")?.textContent).toContain("Störung");
    expect(c.querySelector(".arrival-detail")?.textContent).toContain("Verspätung eines vorausfahrenden Zuges");
    // window rendered HH:MM-HH:MM in Europe/Berlin (06:19-08:30)
    expect(c.querySelector(".arrival-detail")?.textContent).toContain("06:19-08:30");
  });

  it("no disruption badge when disruption is null", () => {
    const c = renderInto([arrival({ disruption: null })]);
    expect(c.querySelector(".badge--disruption")).toBeNull();
  });

  it("escapes XSS payload in category and cause_text", () => {
    const c = renderInto([arrival({
      disruption: { category: "<img src=x onerror=alert(1)>", cause_code: null,
                    cause_text: "<script>alert(2)</script>", window: null },
    })]);
    expect(c.querySelector("img")).toBeNull();
    expect(c.querySelector("script")).toBeNull();
    expect(c.innerHTML).toContain("&lt;img");
  });

  it("category-only disruption shows badge, no cause line", () => {
    const c = renderInto([arrival({
      disruption: { category: "Störung", cause_code: null, cause_text: null, window: null },
    })]);
    expect(c.querySelector(".badge--disruption")?.textContent).toContain("Störung");
  });
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd site && npm run test -- today`
Expected: FAIL - `.badge--disruption` not found; `reason` references gone.

- [ ] **Step 3: Add a disruption badge helper**

In `site/src/pages/today.ts`, add after `terminusLine` (after line 40):

```typescript
// Compact disruption badge. Bot-written values -> escape before innerHTML.
function disruptionBadge(a: Arrival): string {
  const d = a.disruption;
  if (!d || !d.category) return "";
  return `<span class="badge badge--disruption">⚠ ${escapeHtml(d.category)}</span>`;
}

function fmtWindowBerlin(window: { from: string | null; to: string | null } | null): string {
  if (!window) return "";
  const hm = (iso: string | null) =>
    iso ? new Date(iso).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin" }) : "";
  const from = hm(window.from);
  const to = hm(window.to);
  if (!from && !to) return "";
  return `${from}-${to}`;
}
```

- [ ] **Step 4: Render the badge in the summary row**

In `rowFor` (lines 160-166), add the disruption badge slot after the terminus badge slot (after line 164):

```typescript
    `<span class="badge-slot badge-slot--disruption">${disruptionBadge(a)}</span>` +
```

- [ ] **Step 5: Replace `reason` detail rows with disruption detail**

In `detailRowsInner` (lines 88-113), replace the `reason` blocks. Remove lines 92-95 (`if (a.cancelled) { if (!a.reason) {...} }`) - keep a cancelled note that no longer depends on reason:

```python
# (TypeScript) replace the cancelled block:
```
```typescript
  if (a.cancelled && !a.disruption?.category) {
    rows.push(`<div class="detail-row detail-row--note">Zug ausgefallen - keine Fahrt</div>`);
  } else if (!a.cancelled && a.terminus_status) {
    const long = a.direction_bucket === "muenchen" || a.direction_bucket === "wolfratshausen"
      ? terminusLabelLong(a.direction_bucket)
      : "";
    rows.push(detailRow(`Ankunft ${long}`, fmtTerminusArrival(a)));
  }
```

Then replace the trailing `reason` block (lines 109-111):

```typescript
  if (a.disruption?.category || a.disruption?.cause_text) {
    const d = a.disruption;
    if (d.category) rows.push(detailRow("Grund", d.category));
    if (d.cause_text) rows.push(detailRow("Ursache", d.cause_text));
    const win = fmtWindowBerlin(d.window);
    if (win) rows.push(detailRow("Zeitraum", win));
  }
```

(`detailRow` already runs `escapeHtml` on label and value - line 85 - so `category`/`cause_text`/`win` are safe.)

- [ ] **Step 6: Run tests + build, verify pass**

Run: `cd site && npm run test -- today && npm run build`
Expected: PASS (today tests), build clean for today.ts.

- [ ] **Step 7: Commit**

```bash
git add site/src/pages/today.ts site/src/pages/today.test.ts
git commit -m "feat(site): render disruption badge with tap-to-expand detail"
```

---

## Task 8: Stats page - top reasons from disruption

**Files:**
- Modify: `site/src/pages/stats.ts`
- Test: `site/src/pages/stats.test.ts`

- [ ] **Step 1: Update the fixture + add a test**

In `site/src/pages/stats.test.ts`:
- Update the arrival fixture (line ~21): remove `reason: null`, add `disruption: null`.
- Add:

```typescript
  it("lists top disruption reasons by cause_text falling back to category", () => {
    const data = makeData([
      arrival({ disruption: { category: "Störung", cause_code: 34, cause_text: "Verspätung eines vorausfahrenden Zuges", window: null } }),
      arrival({ disruption: { category: "Störung", cause_code: 34, cause_text: "Verspätung eines vorausfahrenden Zuges", window: null } }),
      arrival({ disruption: { category: "Bauarbeiten", cause_code: null, cause_text: null, window: null } }),
    ]);
    const c = document.createElement("div");
    renderStats(data, c);
    const box = c.querySelector(".reasons-box");
    expect(box?.textContent).toContain("Verspätung eines vorausfahrenden Zuges");
    expect(box?.textContent).toContain("(2×)");
    expect(box?.textContent).toContain("Bauarbeiten");
  });
```

(Match the file's existing `makeData`/`arrival` helper names; reuse whatever the test file already defines.)

- [ ] **Step 2: Run test, verify it fails**

Run: `cd site && npm run test -- stats`
Expected: FAIL - reasons box empty (old code read `a.reason`, always null).

- [ ] **Step 3: Switch the reasons aggregation to disruption**

In `site/src/pages/stats.ts`, replace the `topReasons` block (lines 29-35):

```typescript
  const topReasons = (() => {
    const counts = new Map<string, number>();
    for (const a of data.arrivals) {
      const label = a.disruption?.cause_text ?? a.disruption?.category;
      if (label) counts.set(label, (counts.get(label) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
  })();
```

(The render at line 46 already `escapeHtml`s each label - leave it.)

- [ ] **Step 4: Run tests + build, verify pass**

Run: `cd site && npm run test -- stats && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add site/src/pages/stats.ts site/src/pages/stats.test.ts
git commit -m "feat(site): surface top disruption reasons in stats"
```

---

## Task 9: Sweep remaining `reason` fixtures + full verification

**Files:**
- Modify: `site/src/pages/archive-detail.test.ts` (and any other site test with `reason:`)

- [ ] **Step 1: Find remaining `reason` references in site**

Run: `cd site && grep -rn "reason" src --include=*.ts`
Expected: only `archive-detail.test.ts:19` (and possibly others). For each test fixture, replace `reason: null,` with `disruption: null,`.

- [ ] **Step 2: Full site verification**

Run: `cd site && npm run test && npm run build && npm run lint`
Expected: PASS - all vitest suites green, type-check clean, eslint clean.

- [ ] **Step 3: Full fetcher verification**

Run: `cd fetcher && uv run pytest && uv run ruff check src tests`
Expected: PASS - all pytest green, lint clean.

- [ ] **Step 4: Confirm no stray `reason` in source (not tests)**

Run: `cd /home/lima.guest/aiworkshop/s7bb && grep -rn "reason" site/src fetcher/src --include=*.ts --include=*.py | grep -v "\.test\.ts"`
Expected: only `storage.py` (legacy column, intentional) and `parser.py` (the inert `reason` field/argument). No exporter or UI references.

- [ ] **Step 5: Commit**

```bash
git add site/src/pages/archive-detail.test.ts
git commit -m "test(site): drop legacy reason from remaining fixtures"
```

---

## Task 10: Styling for the disruption badge

**Files:**
- Modify: `site/src/style.css`

- [ ] **Step 1: Add badge styles**

In `site/src/style.css`, find the existing `.badge` / `.badge--late` rules and add a sibling. Match the existing badge palette (reuse the warning/orange tone used by `summary-item--shortturn`):

```css
.badge--disruption {
  background: var(--c-warn-bg, #5a3a00);
  color: var(--c-warn-fg, #ffd27a);
}
.badge-slot--disruption { /* same layout as the other badge slots */ }
```

(Inspect the actual variable names / colours already in `style.css` and match them - do not invent a new palette. If the file uses literal hex rather than CSS vars, follow that.)

- [ ] **Step 2: Visual check**

Run: `cd site && npm run dev`, open the today page against a `latest.json` containing a disrupted arrival, confirm the `⚠ Störung` badge renders and tapping the row reveals Grund/Ursache/Zeitraum. (Use `VITE_DEV_NOW` if the local data is dated.)

- [ ] **Step 3: Commit**

```bash
git add site/src/style.css
git commit -m "style(site): disruption badge palette"
```

---

## Task 11: Changelog + release

**Files:**
- Modify: `CHANGELOG.md`, `fetcher/pyproject.toml`, `fetcher/uv.lock`

- [ ] **Step 1: Invoke release-hygiene skill**

This is a `feat` (new user-visible data + UI) -> MINOR bump per CLAUDE.md. Follow `.claude/skills/release-hygiene/SKILL.md` and the Release procedure in CLAUDE.md. Current version is 0.9.3 -> bump to **0.10.0**.

- [ ] **Step 2: Update CHANGELOG**

Add under `[Unreleased]` (then rename to `[0.10.0] - <today>`):

```markdown
### Added
- Disruption reason capture: S7BB now records the DB disruption category, delay-cause code, and disruption window for cancelled/delayed/short-turned trains, exposed as a nested `disruption` object in `latest.json` and rendered as a tap-to-expand badge in the today and stats views.

### Removed
- Legacy always-null `reason` key dropped from exported arrival JSON (replaced by `disruption`).
```

- [ ] **Step 3: Bump version + sync lock**

```bash
# edit fetcher/pyproject.toml version = "0.10.0"
cd fetcher && uv sync --no-dev
```

- [ ] **Step 4: Commit, tag, push, GitHub Release**

Follow the exact Release procedure in CLAUDE.md (commit `chore(release): 0.10.0`, tag `v0.10.0`, push, `gh release create`). Note the **VM redeploy with `--build`** required after merge (new `cause_codes.py` module + migration); record it in the release notes / memory.

---

## Post-merge / rollout notes

- **VM migration:** the four `disruption_*` columns are added by the idempotent `ALTER TABLE` loop on next VM start. Existing rows get `NULL` disruption (historical reasons unrecoverable - `/fchg` window has rolled past).
- **VM redeploy requires `--build`** (new module + schema): `docker compose build s7bb-fetcher && docker compose up -d`.
- **Consumer impact:** `reason` key disappears from `latest.json`; `disruption` appears. `reason` was always `null`, so no consumer depended on it.
- **Out of scope (per spec):** origin-cut short-turn detection (Gap #2), terminus classification of cancelled rows, fetching free-text HIM message bodies.
