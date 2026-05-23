# München Hbf Multi-EVA Terminus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Treat any München Hbf arrival (surface Gl.27-36 EVA `8098261` OR Stammstrecke tief EVA `8098263`) as success for the `muenchen` bucket, so DB's Stammstrecke through-routing of S7-Süd stops producing false `cancelled` / `null` terminus rows.

**Architecture:** `TERMINUS_EVA_FOR_BUCKET` values become EVA tuples. `update_terminus_for_window` iterates per bucket, fetching `/fchg` and `/plan` for each EVA, merging the trip-prefix indexes by `dict.update` (last-write-wins is safe — one inbound S-Bahn run physically calls at exactly one Hbf variant). `drilldown_short_turn` truncates `dp_ppth` at the first Hbf variant before walking, so eastern Stammstrecke stations are never queried. `terminus_health` is re-keyed from `eva` → `bucket` (one-shot DROP + CREATE) so a quiet variant does not trip a permanent false warning while the other variant matches normally. Exporter field rename `eva` → `bucket` (site has no consumer — verified via `grep -r terminus_health site/` → empty).

**Tech Stack:** Python 3.12 + `lxml` + `sqlite3` + `pytest`. Single fetcher PR; no site change; one-shot SQLite migration (drop+recreate `terminus_health`, no data loss — derived metric reaccrues within 3 cycles).

---

## File Structure

- `fetcher/src/s7bb_fetcher/terminus.py` — constants (tief EVA, EVAS tuple), `STATION_NAME_TO_EVA` (add tief name), `TERMINUS_EVA_FOR_BUCKET` (scalar → tuple), `drilldown_short_turn` (Hbf cap), `update_terminus_for_window` (multi-EVA poll), `_record_health` (bucket-keyed).
- `fetcher/src/s7bb_fetcher/storage.py` — `SCHEMA` constant + `_migrate` for `terminus_health` (drop + recreate keyed by bucket).
- `fetcher/src/s7bb_fetcher/exporter.py` — `export_latest` health query / field name (`eva` → `bucket`).
- `fetcher/tests/test_terminus.py` — extend with multi-EVA fixtures, drilldown cap test, bucket-keyed health tests; update existing per-EVA assertions.
- `fetcher/tests/test_storage.py` — update `test_migration_creates_terminus_health_table` to expect bucket schema.
- `fetcher/tests/test_exporter.py` — update health-export tests to bucket field.
- `fetcher/tests/fixtures/terminus_munich_tief_arrived.xml` — new fixture, same trip-prefix as the surface fixture but with tief platform style metadata; used to assert merge correctness.
- `fetcher/tests/fixtures/empty_fchg.xml` — already exists (reused).
- `CHANGELOG.md` — new `## [0.8.3] - 2026-05-23` section under `### Fixed`.
- `fetcher/pyproject.toml` + `fetcher/uv.lock` — version bump 0.8.2 → 0.8.3.
- `docs/s7-station-evas.md` — already lists `8098263 / MHT / München Hbf (tief)` (resolved 2026-05-23, no edit needed; spot-confirm at task start).

---

## Pre-flight verification

### Task 0: Confirm spec preconditions still hold

**Files:** Read-only.

- [ ] **Step 1: Confirm tief EVA + name in canonical doc**

Run: `grep -n "8098263\|München Hbf (tief)" docs/s7-station-evas.md`
Expected: row `| 8098263 | MHT | München Hbf (tief) | ...` present. If missing, append it per CLAUDE.md "always consult [docs/s7-station-evas.md] first" rule before continuing.

- [ ] **Step 2: Confirm site has no terminus_health consumer**

Run: `grep -rn "terminus_health" site/ || echo "NO CONSUMER"`
Expected: `NO CONSUMER`. If site references the field, escalate — exporter rename becomes a MINOR (breaking) bump and the site must change in lockstep.

- [ ] **Step 3: Confirm baseline tests green before any edits**

Run: `cd fetcher && uv run pytest -q`
Expected: all green. A pre-existing failure means revert/diagnose first — do not start TDD on a red baseline.

---

## Task 1: Add tief EVA constants and station-name mapping

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/terminus.py:29-67`
- Test: `fetcher/tests/test_terminus.py` (extend `test_constants_present`)

- [ ] **Step 1: Write the failing test (extend existing constants test)**

Edit `fetcher/tests/test_terminus.py`, replace the body of `test_constants_present` (around line 64-73) with:

```python
def test_constants_present():
    from s7bb_fetcher import terminus
    assert terminus.MUENCHEN_HBF_EVA == "8098261"
    assert terminus.MUENCHEN_HBF_TIEF_EVA == "8098263"
    assert terminus.MUENCHEN_HBF_EVAS == ("8098261", "8098263")
    assert terminus.WOLFRATSHAUSEN_EVA == "8006550"
    assert terminus.CUTOFF_GRACE_MINUTES == 60
    assert terminus.TRAVEL_TIME_MINUTES == {"muenchen": 35, "wolfratshausen": 20}
    # TERMINUS_EVA_FOR_BUCKET is now uniformly a tuple of EVAs.
    assert terminus.TERMINUS_EVA_FOR_BUCKET == {
        "muenchen":       ("8098261", "8098263"),
        "wolfratshausen": ("8006550",),
    }
    # Station map covers both Hbf variants by their dp_ppth name.
    assert terminus.STATION_NAME_TO_EVA["München Hbf Gl.27-36"] == "8098261"
    assert terminus.STATION_NAME_TO_EVA["München Hbf (tief)"]   == "8098263"
    assert terminus.STATION_NAME_TO_EVA["Hohenschäftlarn"]      == "8002955"
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd fetcher && uv run pytest tests/test_terminus.py::test_constants_present -v`
Expected: FAIL with `AttributeError: module 's7bb_fetcher.terminus' has no attribute 'MUENCHEN_HBF_TIEF_EVA'` (or AssertionError on the tuple shape).

- [ ] **Step 3: Add constants and update station map**

Edit `fetcher/src/s7bb_fetcher/terminus.py`. Replace lines 29-32:

```python
# S-Bahn surface platforms 27-36 at München Hbf are a separate station
# in the Timetables API from the long-distance München Hbf (8000261).
# Tief = Stammstrecke underground S-Bahn platforms.
MUENCHEN_HBF_EVA      = "8098261"
MUENCHEN_HBF_TIEF_EVA = "8098263"
MUENCHEN_HBF_EVAS     = (MUENCHEN_HBF_EVA, MUENCHEN_HBF_TIEF_EVA)
WOLFRATSHAUSEN_EVA    = "8006550"
```

In `STATION_NAME_TO_EVA` (lines 44-62), insert a new entry directly after the `"München Hbf Gl.27-36"` line:

```python
    "München Hbf Gl.27-36":        MUENCHEN_HBF_EVA,
    "München Hbf (tief)":          MUENCHEN_HBF_TIEF_EVA,
```

Replace `TERMINUS_EVA_FOR_BUCKET` (lines 64-67) with the uniform-tuple form:

```python
TERMINUS_EVA_FOR_BUCKET: dict[str, tuple[str, ...]] = {
    "muenchen":       MUENCHEN_HBF_EVAS,
    "wolfratshausen": (WOLFRATSHAUSEN_EVA,),
}
```

- [ ] **Step 4: Run constants test, verify it passes**

Run: `cd fetcher && uv run pytest tests/test_terminus.py::test_constants_present -v`
Expected: PASS.

- [ ] **Step 5: Run full terminus + storage test files (will fail; that is expected)**

Run: `cd fetcher && uv run pytest tests/test_terminus.py tests/test_storage.py -q`
Expected: many failures referencing `TERMINUS_EVA_FOR_BUCKET[...]` being a tuple, or `eva` lookups returning nothing. **Do not fix them here** — Tasks 2-6 handle each consumer in turn.

- [ ] **Step 6: Commit (test + scalar→tuple constant change, intentionally leaves consumers red)**

```bash
git add fetcher/src/s7bb_fetcher/terminus.py fetcher/tests/test_terminus.py
git commit -m "refactor(terminus): introduce MUENCHEN_HBF_EVAS tuple + tief station-name mapping"
```

---

## Task 2: Drilldown cap at Munich Hbf variants

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/terminus.py:407-447`
- Test: `fetcher/tests/test_terminus.py` (new tests)

- [ ] **Step 1: Write the failing test (drilldown truncates at tief Hbf, never walks east)**

Append to `fetcher/tests/test_terminus.py`:

```python
def test_drilldown_truncates_at_muenchen_hbf_tief():
    """When dp_ppth runs THROUGH München Hbf (tief) on to Aying, the walk
    must cap at Hbf-tief. Solln cancelled → return Solln; cap prevents the
    walk from ever asking the (non-existent in STATION_NAME_TO_EVA) eastern
    Stammstrecke stations, eliminating `unknown intermediate` WARN spam.
    """
    from s7bb_fetcher.terminus import drilldown_short_turn
    client = _FakeClient({
        "8004161": "intermediate_solln_cancelled",  # cancelled → candidate
        "8004899": "empty_fchg",                    # Pullach passed → break
    })
    ppth = (
        "Buchenhain|Höllriegelskreuth|Pullach|München-Solln|"
        "München Hbf (tief)|München Ost|Höhenkirchen-Siegertsbrunn|Aying"
    )
    result = drilldown_short_turn(client, ppth, BAIERBRUNN_ID)
    assert result == "München-Solln"
    # Walk order after cap: reversed([Buchenhain, Höllriegelskreuth, Pullach,
    # Solln]) → Solln (cs=c, candidate), Pullach (empty → break).
    assert client.calls == ["8004161", "8004899"]


def test_drilldown_truncates_at_muenchen_hbf_surface_skips_eastern_stops(caplog):
    """Symmetric case for surface Gl.27-36 routing — same cap rule. Asserts
    NO `unknown intermediate` WARN for eastern stops (which aren't in
    STATION_NAME_TO_EVA), and only mapped western EVAs are fetched.
    """
    from s7bb_fetcher.terminus import drilldown_short_turn
    client = _FakeClient({
        "8004161": "intermediate_solln_cancelled",
        "8004899": "empty_fchg",
    })
    ppth = (
        "Höllriegelskreuth|Pullach|München-Solln|"
        "München Hbf Gl.27-36|Some Stammstrecke Stop|Aying"
    )
    with caplog.at_level("WARNING"):
        result = drilldown_short_turn(client, ppth, BAIERBRUNN_ID)
    assert result == "München-Solln"
    assert client.calls == ["8004161", "8004899"]
    for east in ("Some Stammstrecke Stop", "Aying"):
        assert not any(east in r.message for r in caplog.records), (
            f"cap regressed: drilldown logged unknown intermediate for {east}"
        )


def test_drilldown_no_hbf_in_ppth_falls_back_to_full_walk():
    """Wolfratshausen-direction paths contain no Hbf variant — must walk all
    intermediates from one-before-terminus toward Baierbrunn unchanged.
    """
    from s7bb_fetcher.terminus import drilldown_short_turn
    client = _FakeClient({
        "8002955": "empty_fchg",  # Hohenschäftlarn
        "8001621": "empty_fchg",  # Ebenhausen-Schäftlarn
        "8003039": "empty_fchg",  # Icking
    })
    ppth = "Hohenschäftlarn|Ebenhausen-Schäftlarn|Icking|Wolfratshausen"
    result = drilldown_short_turn(client, ppth, BAIERBRUNN_ID)
    assert result is None
    # All three intermediates must have been walked (each returned empty,
    # break on first empty). Order: reversed(parts[:-1]) → Icking first.
    assert client.calls[0] == "8003039"


def test_drilldown_finds_cancellation_west_of_hbf_tief():
    """A real short-turn west of Hbf must still be detected when the path
    continues east past Hbf (tief). Use München-Solln as the cancellation
    point; truncation must not hide it.
    """
    from s7bb_fetcher.terminus import drilldown_short_turn
    client = _FakeClient({
        "8004161": "intermediate_solln_cancelled",     # München-Solln cs="c"
        "8004899": "empty_fchg",                       # Pullach passed → break
    })
    ppth = (
        "Pullach|München-Solln|München Hbf (tief)|München Ost|Aying"
    )
    result = drilldown_short_turn(client, ppth, BAIERBRUNN_ID)
    assert result == "München-Solln"
    # Walk: reversed([Pullach, Solln]) → Solln (candidate), Pullach (empty → break).
    assert client.calls == ["8004161", "8004899"]
```

- [ ] **Step 2: Run new tests, verify they fail**

Run: `cd fetcher && uv run pytest tests/test_terminus.py -k 'drilldown_truncates or drilldown_finds_cancellation_west or drilldown_no_hbf' -v`
Expected: failures — current `reversed(parts[:-1])` starts at "Höhenkirchen-Siegertsbrunn" / "Aying" / "Some Stammstrecke Stop" and tries to fetch each via name lookup, which:
- For unmapped eastern names: emits `"unknown intermediate"` WARN → trips the `caplog` assertion in `test_drilldown_truncates_at_muenchen_hbf_surface_skips_eastern_stops`.
- Continues past Solln instead of capping → `client.calls` includes EVAs beyond the expected `["8004161", "8004899"]` list, or raises `AssertionError("unexpected fetch")` from `_FakeClient` on the first unmapped EVA reached.

- [ ] **Step 3: Implement the Hbf cap**

Edit `fetcher/src/s7bb_fetcher/terminus.py`. Replace the body of `drilldown_short_turn` (lines 407-447) with:

```python
def drilldown_short_turn(client, dp_ppth: str | None, train_id: str) -> str | None:
    """Walk dp.ppth reverse from one-before-terminus toward Baierbrunn,
    looking up each station's /fchg and returning the Baierbrunn-most
    station where the train is reported with cs='c'.

    For muenchen-direction trains that DB routes through the Stammstrecke
    (path continues east of München Hbf to Aying/Kreuzstraße/etc.), the
    walk truncates at the first Hbf variant encountered. Stations east of
    Hbf are irrelevant to the "can I reach Munich?" question and are not
    in STATION_NAME_TO_EVA anyway — walking them just logs noise.

    The /fchg endpoint only returns entries for stations where something
    *changed*. So `entry is None` at an intermediate means the train passed
    on time there — i.e. we walked past the cancellation point and can stop.

    Returns None if no cancellation point is reachable (train vanished
    before any station that reported a change, or HTTP failure mid-walk,
    or dp_ppth is empty/None).
    """
    if not dp_ppth:
        return None
    prefix = trip_prefix(train_id)
    if not prefix:
        return None
    parts = [p for p in dp_ppth.split("|") if p]
    # Cap at first München Hbf variant if present — a single inbound S-Bahn
    # cannot physically call at both surface and tief, so first match suffices.
    hbf_variants = {"München Hbf Gl.27-36", "München Hbf (tief)"}
    for idx, name in enumerate(parts):
        if name in hbf_variants:
            parts = parts[: idx + 1]
            break
    # parts[-1] is the (possibly truncated) terminus; walk everything before
    # it in reverse.
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
            return candidate
        entry = build_index(feed).get(prefix)
        if entry is None:
            break
        if _is_cancelled(entry):
            candidate = name
            continue
        break
    return candidate
```

- [ ] **Step 4: Run drilldown tests, verify they pass**

Run: `cd fetcher && uv run pytest tests/test_terminus.py -k drilldown -v`
Expected: all drilldown tests PASS, including the four new ones and all pre-existing ones (`test_drilldown_returns_baierbrunn_most_cancelled` etc. — Hbf cap is idempotent on paths whose terminus is already Hbf).

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/terminus.py fetcher/tests/test_terminus.py
git commit -m "fix(terminus): cap drilldown at München Hbf for Stammstrecke through-routing"
```

---

## Task 3: Storage — re-key terminus_health by bucket

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/storage.py:34-77`
- Test: `fetcher/tests/test_storage.py:191-202`

- [ ] **Step 1: Update failing test for new schema**

Edit `fetcher/tests/test_storage.py`. Replace the body of `test_migration_creates_terminus_health_table` (lines 191-202) with:

```python
def test_migration_creates_terminus_health_table(tmp_path: Path):
    db_path = tmp_path / "old.db"
    sqlite3.connect(str(db_path)).close()
    conn = open_db(db_path)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "terminus_health" in tables
    cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(terminus_health)"
    ).fetchall()}
    assert cols == {"bucket", "zero_match_streak", "updated_at"}
    pk_cols = [
        row[1] for row in conn.execute(
            "PRAGMA table_info(terminus_health)"
        ).fetchall() if row[5]  # row[5] == pk position (1+) for PK cols
    ]
    assert pk_cols == ["bucket"]


def test_migration_drops_old_eva_keyed_terminus_health(tmp_path: Path):
    """Pre-existing DB with eva-keyed terminus_health is migrated to a
    bucket-keyed one; old rows are dropped (derived metric, reaccrues fast).
    """
    db_path = tmp_path / "old.db"
    conn0 = sqlite3.connect(str(db_path))
    conn0.executescript(
        """
        CREATE TABLE terminus_health (
            eva               TEXT PRIMARY KEY,
            zero_match_streak INTEGER NOT NULL DEFAULT 0,
            updated_at        TEXT NOT NULL
        );
        INSERT INTO terminus_health (eva, zero_match_streak, updated_at)
            VALUES ('8098261', 19, '2026-05-23T19:00:00+00:00');
        """
    )
    conn0.commit()
    conn0.close()

    conn = open_db(db_path)
    cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(terminus_health)"
    ).fetchall()}
    assert cols == {"bucket", "zero_match_streak", "updated_at"}
    rows = conn.execute("SELECT * FROM terminus_health").fetchall()
    assert rows == []  # dropped + recreated; no carry-over
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd fetcher && uv run pytest tests/test_storage.py::test_migration_creates_terminus_health_table tests/test_storage.py::test_migration_drops_old_eva_keyed_terminus_health -v`
Expected: FAIL — current schema has `eva` PK, no migration drops it.

- [ ] **Step 3: Update SCHEMA + migration**

Edit `fetcher/src/s7bb_fetcher/storage.py`. The top-level `SCHEMA` constant (lines 9-31) is for the `arrivals` table only; `terminus_health` is created inside `_migrate`. **Fully replace** the entire existing `terminus_health` creation block (storage.py lines 70-76, the `conn.execute("""CREATE TABLE IF NOT EXISTS terminus_health (eva ...)""")` call and its trailing `conn.commit()` immediately after) — do NOT just prepend the DROP guard, or the eva-keyed CREATE will linger and re-create the dropped table on the very next line.

After the edit, exactly one `terminus_health` CREATE must remain in storage.py. Verify with `grep -n "CREATE TABLE.*terminus_health" fetcher/src/s7bb_fetcher/storage.py` → 1 line.

Replacement block:

```python
    # terminus_health: re-keyed from `eva` to `bucket` in v0.8.3. Old rows
    # are derived (3-cycle streak) and reaccrue within ~15 min, so a hard
    # drop on schema mismatch is the simplest correct migration.
    health_info = conn.execute("PRAGMA table_info(terminus_health)").fetchall()
    health_cols = {row[1] for row in health_info}
    if health_info and "bucket" not in health_cols:
        conn.execute("DROP TABLE terminus_health")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS terminus_health (
            bucket             TEXT PRIMARY KEY,
            zero_match_streak  INTEGER NOT NULL DEFAULT 0,
            updated_at         TEXT NOT NULL
        )
    """)
    conn.commit()
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `cd fetcher && uv run pytest tests/test_storage.py -v`
Expected: both migration tests PASS. All other storage tests still PASS (none touched terminus_health internals).

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/storage.py fetcher/tests/test_storage.py
git commit -m "fix(storage): re-key terminus_health by bucket; drop+recreate eva-keyed table"
```

---

## Task 4: Health recorder — bucket-keyed; orchestrator iterates EVA tuple

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/terminus.py:288-404`
- Test: `fetcher/tests/test_terminus.py` (rewrite the two streak tests + add multi-EVA test)

- [ ] **Step 1: Add fixture for tief-arrived trip**

Create `fetcher/tests/fixtures/terminus_munich_tief_arrived.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<timetable station="München Hbf (tief)">
  <s id="42-2605051200-22">
    <ar ct="2605051245" pt="2605051240" l="2" cs="a"/>
  </s>
</timetable>
```

Same `TRIP_PREFIX` (`42-2605051200`) the other Munich fixtures use, so a single pending train will match against either feed.

- [ ] **Step 2: Write failing tests (multi-EVA poll + bucket health)**

Edit `fetcher/tests/test_terminus.py`. Replace `test_update_terminus_for_window_logs_zero_match_streak` and `test_update_terminus_for_window_resets_streak_on_match` (lines 388-433) with:

```python
def test_update_terminus_for_window_logs_zero_match_streak(tmp_path, caplog):
    """3 consecutive zero-match cycles with non-empty pending list logs a
    WARN about possible EVA mismatch; the streak is persisted to
    terminus_health keyed by BUCKET (not EVA)."""
    from s7bb_fetcher.terminus import update_terminus_for_window
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(
        train_id="9999-2605051200-5",
        scheduled_time="2026-05-05T10:30:00+00:00",
    )])
    # Both EVAs in the muenchen tuple return a feed without our trip.
    client = _FakeClient({
        "8098261": "terminus_munich_arrived",      # trip 42-, not 9999-
        "8098263": "terminus_munich_tief_arrived", # also 42-, not 9999-
    })
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)

    with caplog.at_level("WARNING"):
        update_terminus_for_window(conn, client, now=now)
        update_terminus_for_window(conn, client, now=now)
        update_terminus_for_window(conn, client, now=now)

    streak = conn.execute(
        "SELECT zero_match_streak FROM terminus_health WHERE bucket='muenchen'"
    ).fetchone()
    assert streak[0] == 3
    assert any("muenchen" in r.message for r in caplog.records)


def test_update_terminus_for_window_resets_streak_on_match(tmp_path):
    from s7bb_fetcher.terminus import update_terminus_for_window
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(
        train_id="9999-2605051200-5",
        scheduled_time="2026-05-05T10:30:00+00:00",
    )])
    client = _FakeClient({
        "8098261": "terminus_munich_arrived",
        "8098263": "terminus_munich_tief_arrived",
    })
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    update_terminus_for_window(conn, client, now=now)
    upsert_records(conn, [_arr(
        train_id=BAIERBRUNN_ID,
        scheduled_time="2026-05-05T10:35:00+00:00",
    )])
    update_terminus_for_window(conn, client, now=now)
    streak = conn.execute(
        "SELECT zero_match_streak FROM terminus_health WHERE bucket='muenchen'"
    ).fetchone()
    assert streak[0] == 0


def test_update_terminus_for_window_matches_via_tief_eva(tmp_path):
    """Surface /fchg has no entry for the trip; tief /fchg carries it.
    Merged index must yield a classify→arrived. Asserts that the multi-EVA
    poll succeeds when DB routes through the Stammstrecke."""
    from s7bb_fetcher.terminus import update_terminus_for_window
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(
        train_id=BAIERBRUNN_ID,
        scheduled_time="2026-05-05T10:30:00+00:00",
    )])
    client = _FakeClient({
        "8098261": "empty_fchg",                    # surface: empty
        "8098263": "terminus_munich_tief_arrived",  # tief: carries the trip
    })
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    n = update_terminus_for_window(conn, client, now=now)
    assert n == 1
    row = conn.execute(
        "SELECT terminus_status FROM arrivals"
    ).fetchone()
    assert row[0] == "arrived"
    # Both EVAs polled (no early-exit when first returns no entry).
    assert set(client.calls) >= {"8098261", "8098263"}


def test_update_terminus_for_window_single_eva_outage_no_warning(tmp_path, caplog):
    """If one EVA in the tuple raises but the other matches the pending
    trip, the cycle is healthy at bucket level — no zero-match increment."""
    from s7bb_fetcher.terminus import update_terminus_for_window

    class _PartialClient(_FakeClient):
        def fetch_full_changes(self, eva):
            if eva == "8098261":
                raise RuntimeError("surface 5xx")
            return super().fetch_full_changes(eva)

    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(
        train_id=BAIERBRUNN_ID,
        scheduled_time="2026-05-05T10:30:00+00:00",
    )])
    client = _PartialClient({"8098263": "terminus_munich_tief_arrived"})
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    with caplog.at_level("WARNING"):
        update_terminus_for_window(conn, client, now=now)
    row = conn.execute(
        "SELECT zero_match_streak FROM terminus_health WHERE bucket='muenchen'"
    ).fetchone()
    assert row[0] == 0
    # The bucket matched via tief, so no zero-match WARN must fire. The
    # surface 5xx still log.exception's at ERROR level with the bucket name;
    # filter to WARNING-only to isolate the zero-match path under test.
    bucket_warns = [r for r in caplog.records
                    if r.levelname == "WARNING" and "bucket=muenchen" in r.message]
    assert bucket_warns == []
```

Also update `test_update_terminus_for_window_writes_arrived` (line 351) and `test_update_terminus_for_window_skips_quiet_directions` (line 368) to map BOTH muenchen EVAs in `_FakeClient` (otherwise the unmapped EVA raises `AssertionError`):

```python
def test_update_terminus_for_window_writes_arrived(tmp_path):
    from s7bb_fetcher.terminus import update_terminus_for_window
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(
        train_id=BAIERBRUNN_ID,
        scheduled_time="2026-05-05T10:30:00+00:00",
    )])
    client = _FakeClient({
        "8098261": "terminus_munich_arrived",
        "8098263": "empty_fchg",
    })
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    n = update_terminus_for_window(conn, client, now=now)
    assert n == 1
    row = conn.execute(
        "SELECT terminus_status, terminus_delay_minutes FROM arrivals"
    ).fetchone()
    assert row == ("arrived", 0)


def test_update_terminus_for_window_skips_quiet_directions(tmp_path):
    """Only directions with pending trains are polled. With one Wolfratshausen-
    bound pending train, NEITHER München EVA (8098261 surface, 8098263 tief)
    must be fetched — the multi-EVA poll must not iterate the muenchen tuple
    when its `by_bucket` group is empty."""
    from s7bb_fetcher.terminus import update_terminus_for_window
    conn = open_db(tmp_path / "t.db")
    upsert_records(conn, [_arr(
        train_id=BAIERBRUNN_ID,
        direction="Wolfratshausen", direction_bucket="wolfratshausen",
        dp_ppth="Hohenschäftlarn|Wolfratshausen",
        scheduled_time="2026-05-05T10:30:00+00:00",
    )])
    client = _FakeClient({"8006550": "terminus_wolfratshausen_arrived"})
    now = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
    n = update_terminus_for_window(conn, client, now=now)
    assert n == 1
    assert "8098261" not in client.calls
    assert "8098263" not in client.calls
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `cd fetcher && uv run pytest tests/test_terminus.py -k 'update_terminus_for_window' -v`
Expected: failures — `_record_health` still inserts on `eva` column (which no longer exists), and the orchestrator still treats `TERMINUS_EVA_FOR_BUCKET[bucket]` as a scalar.

- [ ] **Step 4: Rewrite `_record_health` keyed by bucket**

Edit `fetcher/src/s7bb_fetcher/terminus.py`. Replace lines 291-328 (`_record_health` function) with:

```python
def _record_health(
    conn: sqlite3.Connection, bucket: str, *,
    pending_count: int, match_count: int, now: datetime,
) -> None:
    """Increment/reset zero-match streak per direction bucket.

    Keyed by bucket (not EVA) so multi-EVA polls do not trip a false warning
    when only one variant carries traffic for a given cycle. The bucket-level
    metric matches the user-facing question: "can I reach this terminus at
    all?".
    """
    if pending_count == 0:
        return  # quiet cycle isn't evidence of mismatch
    if match_count > 0:
        conn.execute(
            """
            INSERT INTO terminus_health (bucket, zero_match_streak, updated_at)
            VALUES (?, 0, ?)
            ON CONFLICT(bucket) DO UPDATE SET
                zero_match_streak = 0,
                updated_at        = excluded.updated_at
            """,
            (bucket, now.isoformat()),
        )
        conn.commit()
        return
    cur = conn.execute(
        "SELECT zero_match_streak FROM terminus_health WHERE bucket=?", (bucket,)
    ).fetchone()
    streak = (cur[0] if cur else 0) + 1
    conn.execute(
        """
        INSERT INTO terminus_health (bucket, zero_match_streak, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(bucket) DO UPDATE SET
            zero_match_streak = excluded.zero_match_streak,
            updated_at        = excluded.updated_at
        """,
        (bucket, streak, now.isoformat()),
    )
    conn.commit()
    if streak >= ZERO_MATCH_WARN_THRESHOLD:
        log.warning(
            "terminus: 0 matches against bucket=%s across %d pending trains for %d consecutive cycles "
            "— possible EVA mismatch in TERMINUS_EVA_FOR_BUCKET[%s]",
            bucket, pending_count, streak, bucket,
        )
```

- [ ] **Step 5: Rewrite `update_terminus_for_window` to iterate the EVA tuple**

Edit `fetcher/src/s7bb_fetcher/terminus.py`. Replace the per-bucket loop body in `update_terminus_for_window` (lines 361-400) with:

```python
    updates: list[dict] = []
    for bucket, group in by_bucket.items():
        evas = TERMINUS_EVA_FOR_BUCKET.get(bucket)
        if not evas:
            continue  # 'unknown' bucket — never resolvable

        # Merge /fchg across all EVAs in the tuple. One inbound S-Bahn run
        # physically calls at exactly one variant, so last-write-wins is
        # safe; collisions (if any) carry identical ar/@ct.
        merged_idx: dict[str, etree._Element] = {}
        any_fchg_ok = False
        for eva in evas:
            try:
                feed = client.fetch_full_changes(eva)
            except Exception:
                log.exception(
                    "terminus: /fchg %s failed; trying remaining EVAs for bucket=%s",
                    eva, bucket,
                )
                continue
            any_fchg_ok = True
            merged_idx.update(build_index(feed))
        if not any_fchg_ok:
            log.warning(
                "terminus: all /fchg EVAs failed for bucket=%s; %d pending stay pending",
                bucket, len(group),
            )
            continue

        # Merge /plan across all (EVA, hour) combinations. Same idempotency
        # rationale: a given trip-prefix appears in at most one EVA's plan.
        plan_pt: dict[str, str] = {}
        for eva in evas:
            for date, hour in sorted(_hour_keys(group, bucket)):
                try:
                    plan_xml = client.fetch_plan(eva, date, hour)
                except Exception:
                    log.exception(
                        "terminus: /plan %s %s/%s failed; delays may fall back to 0",
                        eva, date, hour,
                    )
                    continue
                plan_pt.update(_build_plan_pt_index(plan_xml))

        match_count = 0
        for p in group:
            entry = merged_idx.get(trip_prefix(p.train_id))
            if entry is not None:
                match_count += 1
            update = classify(
                p, entry, now, drilldown=_drilldown,
                planned_pt=plan_pt.get(trip_prefix(p.train_id)),
            )
            if update is not None:
                updates.append({
                    "train_id": update.train_id,
                    "scheduled_time": update.scheduled_time,
                    "terminus_status": update.terminus_status,
                    "terminus_delay_minutes": update.terminus_delay_minutes,
                    "terminus_short_turn_station": update.terminus_short_turn_station,
                })
        _record_health(conn, bucket, pending_count=len(group),
                       match_count=match_count, now=now)
```

Leave the surrounding function header, the `from .storage import ...` line, and the trailing `return update_terminus_fields(...)` block unchanged.

- [ ] **Step 6: Run terminus tests, verify they pass**

Run: `cd fetcher && uv run pytest tests/test_terminus.py -v`
Expected: all PASS (including the four new multi-EVA / single-EVA-outage / bucket-streak tests).

- [ ] **Step 7: Commit**

```bash
git add fetcher/src/s7bb_fetcher/terminus.py fetcher/tests/test_terminus.py \
        fetcher/tests/fixtures/terminus_munich_tief_arrived.xml
git commit -m "fix(terminus): poll surface + tief Hbf EVAs; key health by bucket"
```

---

## Task 5: Exporter — rename `eva` field to `bucket`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/exporter.py:143-149`
- Test: `fetcher/tests/test_exporter.py:408-428`

- [ ] **Step 1: Update failing tests**

Edit `fetcher/tests/test_exporter.py`. Replace `test_terminus_health_populated_sorted_by_eva` (lines 408-428) with:

```python
def test_terminus_health_populated_sorted_by_bucket(tmp_path):
    """`terminus_health` rows emitted as
    list[{bucket, zero_match_streak, updated_at}], ordered by bucket ASC
    for stable diffs in the s7bb-data repo. v0.8.3 renamed eva → bucket
    in lockstep with the multi-EVA poll; site has no consumer yet."""
    conn = open_db(tmp_path / "test.db")
    conn.executemany(
        "INSERT INTO terminus_health (bucket, zero_match_streak, updated_at) VALUES (?,?,?)",
        [
            ("wolfratshausen", 0, "2026-05-23T07:42:11+00:00"),
            ("muenchen",       12, "2026-05-23T07:42:11+00:00"),
        ],
    )
    conn.commit()

    out = tmp_path / "latest.json"
    export_latest(conn, out)
    data = json.loads(out.read_text())

    assert data["terminus_health"] == [
        {"bucket": "muenchen",       "zero_match_streak": 12,
         "updated_at": "2026-05-23T07:42:11+00:00"},
        {"bucket": "wolfratshausen", "zero_match_streak":  0,
         "updated_at": "2026-05-23T07:42:11+00:00"},
    ]
```

`test_terminus_health_empty_table` (lines 397-405) needs no change — empty list shape is unchanged.

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd fetcher && uv run pytest tests/test_exporter.py::test_terminus_health_populated_sorted_by_bucket -v`
Expected: FAIL — exporter still queries `eva` column.

- [ ] **Step 3: Update exporter query**

Edit `fetcher/src/s7bb_fetcher/exporter.py`. Replace lines 143-149 with:

```python
    health_cur = conn.execute(
        "SELECT bucket, zero_match_streak, updated_at FROM terminus_health "
        "ORDER BY bucket"
    )
    terminus_health = [
        {"bucket": bucket, "zero_match_streak": streak, "updated_at": updated_at}
        for bucket, streak, updated_at in health_cur.fetchall()
    ]
```

- [ ] **Step 4: Run exporter tests, verify they pass**

Run: `cd fetcher && uv run pytest tests/test_exporter.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add fetcher/src/s7bb_fetcher/exporter.py fetcher/tests/test_exporter.py
git commit -m "fix(exporter): rename terminus_health.eva → bucket in latest.json"
```

---

## Task 6: Full-suite green check + lint

**Files:** None (verification only).

- [ ] **Step 1: Run full fetcher test suite**

Run: `cd fetcher && uv run pytest -q`
Expected: 0 failures across `test_terminus.py`, `test_storage.py`, `test_exporter.py`, `test_service.py`, `test_cli.py`, `test_parser.py`, `test_preflight.py`, `test_pusher.py`, `test_startup_sync.py`, `test_compose_wiring.py`. If anything in `test_service.py` (or another suite I have not examined) imports `TERMINUS_EVA_FOR_BUCKET` and expects a scalar, fix the assertion to expect the tuple form and re-run.

- [ ] **Step 2: Lint**

Run: `cd fetcher && uv run ruff check src tests`
Expected: clean. Common breakage: unused `MUENCHEN_HBF_EVA` import if a test stopped referencing it — leave the constant exported (still referenced by `MUENCHEN_HBF_EVAS` tuple and `STATION_NAME_TO_EVA`).

- [ ] **Step 3: Confirm no stray `eva` reference in exporter / orchestrator / health recorder**

Run (three independent greps — same-line `terminus_health.*eva` is too narrow on its own; a renamed param can leave behind `eva` in a function signature without touching the table on the same line):

```bash
grep -rnE "terminus_health.*eva|eva.*terminus_health" fetcher/src/
grep -n "def _record_health" fetcher/src/s7bb_fetcher/terminus.py
grep -n "eva" fetcher/src/s7bb_fetcher/exporter.py
```

Expected:
1. First grep: no output.
2. Second grep: signature contains `bucket: str`, no `eva` parameter.
3. Third grep: no match (exporter no longer references `eva` after Task 5).

Comments mentioning the historical `eva` keying are fine in CHANGELOG / docs, but live code should not reference the dropped column.

---

## Task 7: Release bookkeeping (0.8.2 → 0.8.3)

**Files:**
- Modify: `fetcher/pyproject.toml` (version line)
- Modify: `fetcher/uv.lock` (regenerated)
- Modify: `CHANGELOG.md`
- Tag: `v0.8.3` after merge

This follows `release-hygiene` skill + the CLAUDE.md release procedure. SemVer: PATCH (`fix`) per spec §Migration — the `terminus_health` field rename is exporter-internal because the site has no consumer (verified in Task 0 step 2).

- [ ] **Step 1: Bump version in pyproject.toml**

Edit `fetcher/pyproject.toml`. Find the `version = "0.8.2"` line and change to:

```toml
version = "0.8.3"
```

- [ ] **Step 2: Sync uv.lock**

Run: `cd fetcher && uv sync --no-dev`
Expected: `fetcher/uv.lock` updates the `s7bb-fetcher` package version line to `0.8.3`. No other diff.

- [ ] **Step 3: Add CHANGELOG entry**

Edit `CHANGELOG.md`. Insert directly under the title block (above `## [0.8.2]`):

```markdown
## [0.8.3] - 2026-05-23

### Fixed

- Treat München Hbf surface (`8098261`, Gl.27-36) **and** Hbf tief
  (`8098263`, Stammstrecke) as equally valid terminus arrivals for
  the `muenchen` bucket. `update_terminus_for_window` now polls a
  tuple of EVAs per bucket and merges the trip-prefix indexes, so
  Baierbrunn → Hbf trips classify correctly whether DB routes them
  through the surface platforms or continues east via the
  Stammstrecke (Höhenkirchen-Siegertsbrunn / Kreuzstraße / Aying).
- Drilldown walk truncates at the first München Hbf variant in
  `dp.ppth`; eastern Stammstrecke stations (München Ost,
  Höhenkirchen-Siegertsbrunn, Kreuzstraße, Aying, …) — none of which
  are in `STATION_NAME_TO_EVA` — no longer reach the name-lookup
  branch, eliminating spurious `unknown intermediate` WARNs per cycle.
- `terminus_health` re-keyed from `eva` to `bucket`. The exporter
  emits `bucket` instead of `eva` in `latest.json[].terminus_health`.
  The site has no consumer of this field yet, so the rename is not a
  breaking change.

### Migration notes

- One-shot SQLite migration drops and recreates `terminus_health`
  on first start under v0.8.3. Health is a derived 3-cycle streak —
  the bucket-level row reaccrues within ~15 minutes.
- Rows for `direction_bucket = "muenchen"` on **2026-05-23** are
  not backfilled: the majority ended up `terminus_status = null`,
  with a handful misclassified `cancelled` via cutoff drilldown.
  The pre-deploy `/fchg` window has closed; accept the lossy day.
  Same convention as the 2026-05-23 parser fix in 0.8.2.
  (Exact counts: verify pre-release with
  `sqlite3 data/s7bb.db "SELECT terminus_status, COUNT(*) FROM arrivals
   WHERE direction_bucket='muenchen' AND date(scheduled_time)='2026-05-23'
   GROUP BY terminus_status"` and edit the line above if the shape
   materially differs.)
```

- [ ] **Step 4: Commit release bump (do not tag yet — tag after merge per project policy)**

```bash
git add fetcher/pyproject.toml fetcher/uv.lock CHANGELOG.md
git commit -m "chore(release): 0.8.3"
```

- [ ] **Step 5: Open PR**

Run:

```bash
gh pr create --title "fix(terminus): multi-EVA poll for München Hbf (surface + tief)" \
  --body "$(cat <<'EOF'
## Summary
- Treat surface (`8098261`) and tief (`8098263`) München Hbf as one terminus for the `muenchen` bucket.
- Drilldown caps at first Hbf variant in `dp.ppth` so eastern Stammstrecke stations are no longer queried.
- `terminus_health` re-keyed by `bucket` (replaces per-EVA keying that broke under multi-EVA poll). Exporter field renamed in lockstep; site has no consumer (verified `grep -rn terminus_health site/` → empty).

## Quota impact (5-min cadence)
- `+288` `/fchg` per day (tief EVA), `+288–576` `/plan` per day. Wolfratshausen bucket unaffected.

## Test plan
- [ ] `cd fetcher && uv run pytest -q` green
- [ ] `cd fetcher && uv run ruff check src tests` clean
- [ ] After VM redeploy: `sqlite3 data/s7bb.db "SELECT * FROM terminus_health"` shows one row for `bucket='muenchen'` with `zero_match_streak = 0` within ~15 min.
- [ ] Spot-check current Aying-terminus trip: `terminus_status='arrived'` with a finite delay once it physically passes Hbf.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 6: After merge — tag, push, and GitHub Release**

(Per CLAUDE.md "Post-merge release trigger". Run only after the PR merges to `main`.)

```bash
git checkout main
git pull
git tag -a v0.8.3 -m "v0.8.3"
git push origin v0.8.3
gh release create v0.8.3 --title "v0.8.3" --latest \
  --notes-file <(awk '/^## \[0\.8\.3\]/,/^## \[/' CHANGELOG.md | sed '$d')
```

Verify the release notes body is non-empty before publishing (per `[[feedback_release_awk]]`). If empty: re-run with the dot-escaped explicit-end form above.

- [ ] **Step 7: VM redeploy**

(Per `[[feedback_docker_rebuild]]` — `up -d` alone reuses cached image; the code change ships only with `build`.)

```bash
# On the VM:
git pull
docker compose build s7bb-fetcher
docker compose up -d s7bb-fetcher
```

Then within ~15 min verify:

```bash
docker compose exec s7bb-fetcher sqlite3 /data/s7bb.db \
  "SELECT bucket, zero_match_streak, updated_at FROM terminus_health"
```

Expected: rows for `muenchen` and `wolfratshausen`, both with `zero_match_streak = 0`. The two pre-v0.8.3 EVA-keyed rows are gone (table was dropped + recreated by `_migrate`).

---

## Self-review (run before declaring complete)

- **Spec §Multi-EVA poll** → Task 1 (constants/tuple), Task 4 (orchestrator iteration + merged index). ✓
- **Spec §Drilldown cap** → Task 2 (first-Hbf truncation + fallback for wolfratshausen). ✓
- **Spec §Station map extension** → Task 1 step 3 (adds `"München Hbf (tief)"` → `8098263`). ✓
- **Spec §Travel time and cutoff** → unchanged per spec; no task needed. ✓
- **Spec §Health table re-key** → Task 3 (schema), Task 4 step 4 (recorder), Task 4 steps 2/6 (tests). ✓
- **Spec §Schema migration** → Task 3 step 3 (DROP if `bucket` missing, then CREATE IF NOT EXISTS). ✓
- **Spec §Exporter rename** → Task 5. ✓
- **Spec §Migration / rollout** → Task 7 (SemVer PATCH, CHANGELOG, VM rebuild). ✓
- **Spec §Risks 1 (wrong tief EVA)** → Task 0 step 1 confirms doc; Task 7 VM check observes `zero_match_streak`. ✓
- **Spec §Risks 4 (quota)** → noted in PR body in Task 7 step 5. ✓
- **Spec §Testing checklist** → multi-EVA fixture (Task 4 step 1+2), drilldown cap tests (Task 2 step 1), bucket-health test (Task 4 step 2), storage CREATE test (Task 3 step 1), exporter bucket-field test (Task 5 step 1), VM smoke checks (Task 7 step 7). ✓
- **Non-goals** → no backfill code; binary triad unchanged; no aggregates / UI changes. ✓
- **Placeholder scan** → no TBD / TODO / "similar to" / "add appropriate" strings in tasks. ✓
- **Type consistency** → `bucket` (str) used uniformly; `evas: tuple[str, ...]` annotation matches `MUENCHEN_HBF_EVAS` shape; `_record_health` signature uses `bucket: str` keyword positions matching call site. ✓
