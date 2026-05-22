# Terminus arrival tracking — design

## Context

Today the s7bb fetcher only knows whether an S7 train was present, on time, delayed, or cancelled **at Baierbrunn**. It cannot say whether a train that departed Baierbrunn actually reached its terminus (München Hbf Gl.27-36 or Wolfratshausen), whether it was delayed on arrival there, or whether it short-turned at an intermediate station.

This is information the residents of Baierbrunn (the site's primary audience) care about: a train that left Baierbrunn on time but never made it to Munich is a meaningfully worse outcome than one that ran to completion late. The DB Timetables API exposes the data — it just requires polling the terminus station's `/fchg` feed and matching trains by `train_number`.

Phase 1 of this feature is **backend-only**: schema, fetcher, exporter, JSON contract. Phase 2 (UI rendering) is a follow-up, mirroring the train_number rollout pattern (PR #45 → v0.6.0).

The user-visible summary per train, once Phase 2 ships, will be one of: **arrived**, **arrived +N min late**, **short-turned at station X**, **cancelled (did not reach terminus)**, or **pending** (still in flight).

## Architecture

A new module `fetcher/src/s7bb_fetcher/terminus.py` owns terminus tracking. It is called sequentially after the existing Baierbrunn upsert inside `_fetch_job()` in `service.py`, so there is no race with the row insert.

```
APScheduler _fetch_job (every 5 min):
  1. fetch_baierbrunn_now()         (existing)
  2. parse_timetable()              (existing)
  3. upsert_records()               (existing, modified to seed terminus_status='pending')
  4. update_terminus_for_window()   ← NEW
```

`update_terminus_for_window()` does:

1. Read pending Baierbrunn arrivals from DB (window: `[now-2h, now+5min]`, `terminus_status='pending'`, `cancelled=0`, `train_number IS NOT NULL`).
2. Group by `direction_bucket`. Skip groups with no pending trains.
3. For each direction in use, call `fetch_full_changes(terminus_eva)` **once** (not once per train).
4. Match each pending train against the terminus feed by `train_number`.
5. Classify per train → `TerminusUpdate` (status + delay + short_turn_station).
6. For trains with `cs="c"` at terminus, or trains missing from the terminus feed past cutoff, perform a drilldown walk along that train's own `dp.ppth` (stored on the Baierbrunn row). Drilldown returns the Baierbrunn-most station where the train is reported with `cs="c"`, or None if no cancellation is reported along the path.
7. Apply updates via `storage.update_terminus_fields()`.

All terminus work runs inside a single try/except. Failure logs and returns; the parent fetch job is unaffected. Pending rows simply retry next cycle.

### Match key

Trains are correlated across stations by `train_number` (`<tl n="...">` in DB XML, stable per train run across stations). To prevent rare cross-day collisions, the SQL UPDATE constrains by a UTC time window around the pending row's `scheduled_time` (±4 h) rather than a date-string equality:

```sql
WHERE train_number = ?
  AND scheduled_time BETWEEN ? AND ?   -- [scheduled_time - 4h, scheduled_time + 4h]
  AND terminus_status = 'pending'
  AND cancelled = 0
```

This avoids the UTC-vs-local-DE-date ambiguity that affects late-night Baierbrunn departures crossing midnight UTC. The `<s id="...">` identifier in DB XML is not used for cross-station matching because its production format is not contractually guaranteed station-stable.

### State machine

```
                          ┌─ cancelled=1 at Baierbrunn ───► terminus_status = NULL (N/A)
upsert_records writes row ┤
                          └─ cancelled=0 ────────────────► terminus_status = 'pending'

each cycle, for pending rows in window:
  match train_number in terminus_fchg
    found, no cs="c"               → 'arrived',     delay = ct - pt
    found, cs="c"                  → drilldown walks dp.ppth reverse:
        Baierbrunn-most cs="c" station   → 'short_turn', short_turn_station = X
        no cs="c" station found          → 'cancelled', short_turn = NULL
    not found, now <= cutoff       → stay 'pending'
    not found, now >  cutoff       → run drilldown:
        Baierbrunn-most cs="c" station   → 'short_turn', short_turn_station = X
        else                              → 'cancelled', short_turn = NULL
```

**Cutoff formula.** The user-approved rule is "planned terminus arrival + 60 min". The DB row only stores Baierbrunn departure (`scheduled_time`), so the formula adds a per-direction travel-time constant:

```python
TRAVEL_TIME_MINUTES = {
    "muenchen":        35,  # Baierbrunn → München Hbf Gl.27-36
    "wolfratshausen":  20,  # Baierbrunn → Wolfratshausen
}
CUTOFF_GRACE_MINUTES = 60

cutoff = scheduled_time + TRAVEL_TIME_MINUTES[direction_bucket] + CUTOFF_GRACE_MINUTES
```

Effective cutoff: scheduled_time + 95 min (München) or +80 min (Wolfratshausen). Source: official MVV timetable; stable across years. Note this approximates "planned terminus arrival + 60 min" using a per-direction travel constant rather than the exact per-train planned arrival; real travel varies by ±2 min between runs, well inside the 60 min grace. If the schedule materially changes, update these constants.

Once a row reaches `arrived` / `short_turn` / `cancelled`, it is **terminal** — subsequent cycles do not touch it (the SQL `WHERE` clause filters `terminus_status='pending'`). This avoids flapping on terminus-feed jitter and saves quota.

If a non-cancelled row is later marked `cancelled=1` by a Baierbrunn refetch, the upsert clears the terminus fields back to NULL.

### Verified EVA numbers

Resolved against the DB Timetables `/station/{name}` endpoint on 2026-05-22 and cross-checked against a live `/plan/8000781` response showing the S7 ppth:

```
Baierbrunn:                    8000781   (already in code)
München Hbf Gl.27-36:          8000261
Wolfratshausen:                8006550

Direction München, ordered Baierbrunn → terminus:
  Buchenhain                   8071272
  Höllriegelskreuth            8002899
  Pullach                      8004899
  Großhesselohe Isartalbf      8002422
  München-Solln                8004161
  München Siemenswerke         8004137
  München-Mittersendling       8004154
  München Harras               8004130
  München Heimeranplatz        8005419
  München Donnersbergerbrücke  8004128

Direction Wolfratshausen, ordered Baierbrunn → terminus:
  Hohenschäftlarn              8002955
  Ebenhausen-Schäftlarn        8001621
  Icking                       8003039
```

A live `dp.ppth` confirmed on 2026-05-22:

```
Buchenhain|Höllriegelskreuth|Pullach|Großhesselohe Isartalbf|
München-Solln|München Siemenswerke|München-Mittersendling|
München Harras|München Heimeranplatz|München Donnersbergerbrücke|
München Hbf Gl.27-36
```

**First-run sanity check** for `MUENCHEN_HBF_EVA`. The München Hbf deep S-Bahn platform sometimes appears under a separate EVA from the long-distance Hbf in DB catalogues. `update_terminus_for_window()` logs `WARN terminus: 0 matches against eva=<EVA> across <N> pending trains` if a non-empty pending list yields zero matches at a terminus EVA for 3 consecutive cycles. This flags an EVA mismatch without spurious warnings on quiet nights.

The 3-cycle counter is persisted as a row per `terminus_eva` in a new tiny `terminus_health` table (`eva TEXT PRIMARY KEY, zero_match_streak INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL`). Each call increments on a zero-match pending-non-empty cycle, resets to 0 on any match. Persistent storage means a container restart does not silently mask an EVA mismatch.

### Drilldown algorithm

Hardcoded EVA tables are brittle to MVV reroutes. Instead, walk the train's own `dp.ppth` (which the Baierbrunn record already carries) and look up each station name in a static `STATION_NAME_TO_EVA` dictionary. Unknown names log a warning and are skipped, allowing graceful degradation on new stations.

**Key DB API constraint.** `/fchg/<eva>` returns only stations where something *changed*; on-time pass-throughs do not appear. So `entry is None` at an intermediate means "train ran on time through here" (i.e. we have walked past the cancellation point), not "train never reached here". The algorithm must therefore walk reverse from terminus and find the Baierbrunn-most station where the train is reported with `cs="c"`. The first `entry is None` while walking is the stop signal.

`_is_cancelled(entry)` returns True iff the train's `<ar>` (or `<dp>` fallback) element on this station entry carries `cs="c"`.

```python
parts = dp_ppth.split("|")     # ordered Baierbrunn → terminus
# parts[-1] is terminus; cancelled there → walk parts[:-1] reverse
short_turn = None
for name in reversed(parts[:-1]):
    eva = STATION_NAME_TO_EVA.get(name)
    if eva is None:
        log.warning("unknown intermediate %s", name)
        continue
    feed = fetch_full_changes(eva)
    entry = build_index(feed).get(train_number)
    if entry is None:
        # no change at this station → train passed on time → past cancellation point
        break
    if _is_cancelled(entry):
        short_turn = name        # candidate; keep walking, may find one closer to Baierbrunn
        continue
    # entry present but not cancelled (delay only) → train passed → stop
    break
return short_turn   # None ⇒ train vanished entirely → caller labels 'cancelled'
```

Result semantics: `short_turn` names the Baierbrunn-most station where the train is reported cancelled. The train was last seen running at the next earlier station in `parts` (or at Baierbrunn itself if `short_turn` is the first station after Baierbrunn).

### Quota cost

| Scenario | API calls per 5-min cycle |
|----------|---------------------------|
| Existing baseline | 2 (Baierbrunn plan + fchg) |
| + terminus, no short-turn events | +1 per direction in use (typically +2) |
| + drilldown on short-turn event | + up to 10 intermediate fchg calls (rare) |

Terminus `/fchg` is fetched **once per direction per cycle**, shared across all pending trains in that direction.

## Components & files

### New files

- `fetcher/src/s7bb_fetcher/terminus.py`
  - Constants: `MUENCHEN_HBF_EVA`, `WOLFRATSHAUSEN_EVA`, `STATION_NAME_TO_EVA`, `TRAVEL_TIME_MINUTES`, `CUTOFF_GRACE_MINUTES = 60`
  - `@dataclass TerminusUpdate { train_number, scheduled_time, terminus_status, terminus_delay_minutes, terminus_short_turn_station }` — `scheduled_time` (UTC ISO) is the Baierbrunn row's value and is used to compute the ±4 h match window
  - `list_pending_trains(conn) -> list[PendingTrain]` — issues `SELECT train_number, scheduled_time, direction_bucket, dp_ppth FROM arrivals WHERE terminus_status='pending' AND cancelled=0 AND train_number IS NOT NULL AND scheduled_time BETWEEN ? AND ?`
  - `build_index(feed) -> dict[train_number, <s>]`
  - `classify(pending, terminus_entry, now) -> TerminusUpdate` — pure, clock-injectable
  - `drilldown_short_turn(client, dp_ppth, train_number) -> str | None`
  - `update_terminus_for_window(conn, client, now=None) -> int` — orchestrator
- `fetcher/tests/test_terminus.py`
- `fetcher/tests/fixtures/terminus_munich_arrived.xml`
- `fetcher/tests/fixtures/terminus_munich_delayed.xml`
- `fetcher/tests/fixtures/terminus_munich_cancelled.xml`
- `fetcher/tests/fixtures/terminus_wolfratshausen_arrived.xml`
- `fetcher/tests/fixtures/intermediate_solln_arrived.xml`
- `fetcher/tests/fixtures/intermediate_solln_cancelled.xml`

### Modified files

- `fetcher/src/s7bb_fetcher/storage.py`
  - Schema: add `terminus_status TEXT`, `terminus_delay_minutes INTEGER`, `terminus_short_turn_station TEXT`, `dp_ppth TEXT`
  - `_migrate()`: ALTER TABLE adds all 4 columns on existing DBs (forward-only — existing rows stay NULL, including `dp_ppth`; drilldown skips trains with NULL ppth and they classify only via terminus feed)
  - `upsert_records()`: seed `terminus_status='pending' IF cancelled=0 ELSE NULL` on INSERT; on CONFLICT, leave terminus_* untouched **except** when `excluded.cancelled=1`, in which case clear them. On conflict, `dp_ppth` uses `COALESCE(excluded.dp_ppth, dp_ppth)` — newer non-empty paths overwrite, but a NULL/empty refetch (outage / partial XML) preserves the last known good path so drilldown stays usable.
  - New `update_terminus_fields(conn, updates) -> int` — guarded UPDATE (`WHERE terminus_status='pending' AND cancelled=0`)
  - New `terminus_health` table (see "First-run sanity check" above): `(eva TEXT PRIMARY KEY, zero_match_streak INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)`. Created in `SCHEMA` and idempotently in `_migrate()` for existing DBs.
- `fetcher/src/s7bb_fetcher/parser.py`
  - `ArrivalRecord` gains `dp_ppth: str`. Parser already reads `dp.get("ppth", "")` locally (parser.py:96) but currently discards it — preserve onto the dataclass instead.
- `fetcher/src/s7bb_fetcher/service.py:_fetch_job()`
  - Append: `try: update_terminus_for_window(conn, client) except Exception: log.exception(...)`
- `fetcher/src/s7bb_fetcher/exporter.py`
  - SELECT adds the 3 columns; arrivals[] dict adds 3 keys (always present, may be JSON null)
- `site/src/data.ts`
  - Add `TerminusStatus` type and 3 optional + nullable fields on `Arrival`
- `fetcher/tests/test_storage.py`, `fetcher/tests/test_exporter.py`
  - Migration test, upsert seed test, cancellation-flip test, exporter schema test (see Testing section below)

### Unchanged

- `fetcher/src/s7bb_fetcher/api.py` — existing `fetch_full_changes(eva)` already takes an EVA parameter
- All site `pages/*` — Phase 1 is data-only, no rendering

## Data flow

```
DB Timetables API
  └─ /plan/8000781/{date}/{hour}        ──┐
  └─ /fchg/8000781                       ──┴─► parse_timetable() → ArrivalRecord[]
                                             (now includes dp_ppth)
                                             upsert_records() seeds
                                             terminus_status='pending'
                                                            │
                                                            ▼
                                             list_pending_trains(conn)
                                                            │
                              ┌─────────────────────────────┤
                              ▼                             ▼
                       (München bound)              (Wolfratshausen bound)
  └─ /fchg/8000261 once  ─────┐                  ┌──── once /fchg/8006550
                              ▼                  ▼
                         classify(pending, entry, now) → TerminusUpdate

  └─ /fchg/<intermediate> ────► drilldown_short_turn(dp_ppth) → station name | None
     (on cs="c" at terminus OR on missing-past-cutoff)

                              │
                              ▼
                      update_terminus_fields(conn, updates)
                              │
                              ▼
                       (hourly) export_latest() emits 3 new JSON fields
```

JSON schema diff in `latest.json` arrivals entry:

```json
{
  "...": "...existing fields...",
  "terminus_status": "arrived" | "short_turn" | "cancelled" | "pending" | null,
  "terminus_delay_minutes": <int> | null,
  "terminus_short_turn_station": <string> | null
}
```

`null` for `terminus_status` means: row predates this feature OR train was cancelled at Baierbrunn (not evaluated). Frontend (Phase 2) should treat both identically — no terminus info to display.

## Error handling

| Failure | Behaviour |
|---------|-----------|
| `update_terminus_for_window` raises | Caught by `_fetch_job()`; log via `log.exception`; cycle continues. Existing Baierbrunn data already committed. |
| Terminus `/fchg` HTTP 4xx/5xx | Caught inside terminus module; log; pending rows stay pending; next cycle retries. |
| Drilldown HTTP error mid-walk | Abort that train's drilldown; leave it `pending`; next cycle re-attempts. |
| Unknown station name in ppth | Log warning; skip that station; continue walking remaining stations. |
| `train_number IS NULL` on Baierbrunn row | Excluded from `list_pending_trains` query. Train never settles. Acceptable — DB API supplies `<tl n=...>` for every regular S-Bahn run. |
| Two cycles race UPDATE | SQLite WAL serialises; last-write-wins; both converge to the same terminal state. |
| DB API late-correction after row terminal | Not reverted (terminal states immutable). Rare in practice. |

## Testing

Strict TDD: write tests before implementation.

### Unit tests (`test_terminus.py`)

- `test_classify_arrived` — `<ar ct=...>` present, no cs, ct >= pt → status='arrived'
- `test_classify_arrived_with_delay` — ct − pt = 5 min → delay_minutes=5
- `test_classify_arrived_zero_delay` — ct missing, no cs → status='arrived', delay=0
- `test_classify_short_turn_triggers_drilldown` — terminus `cs="c"`; drilldown returns "München-Solln"
- `test_classify_short_turn_drilldown_no_cancelled_intermediates` — terminus `cs="c"` but no intermediate has the train in /fchg (all on-time pass-throughs) → status='cancelled', short_turn=None
- `test_classify_pending_not_in_feed_before_cutoff` — not matched, now < T+cutoff → no update issued (stays pending)
- `test_classify_missing_past_cutoff_triggers_drilldown` — not in terminus feed, now > T+cutoff; drilldown finds cs="c" at intermediate → status='short_turn'
- `test_classify_missing_past_cutoff_no_drilldown_hit` — not in terminus feed, now > T+cutoff, drilldown finds nothing → status='cancelled'
- `test_drilldown_walks_ppth_reverse_returns_baierbrunn_most_cancelled` — fixture: stations Y,X,Z toward terminus all show cs="c", station before Y absent (on-time pass) → returns Y
- `test_drilldown_stops_at_first_on_time_intermediate` — reverse walk: first None entry breaks the loop, earlier cs="c" stations are not rechecked
- `test_drilldown_unknown_station_logs_and_continues` — ppth contains unknown name → warn + skip
- `test_list_pending_excludes_baierbrunn_cancelled` — rows with `cancelled=1` never selected
- `test_list_pending_excludes_terminal_states` — rows with non-pending status excluded
- `test_list_pending_window_scope` — rows outside `[now-2h, now+5min]` excluded
- `test_match_by_train_number_and_window` — two rows with same train_number on different days; the one outside the ±4 h window is not updated
- `test_update_terminus_fields_idempotent` — second call is no-op (WHERE filter)
- `test_update_terminus_fields_guards_cancelled_flip` — row flipped to cancelled=1 not updated
- `test_terminus_failure_does_not_abort_fetch_job` — `update_terminus_for_window` raises → service.py logs and continues

### Modified `test_storage.py`

- `test_migration_adds_terminus_columns` — terminus_status / terminus_delay_minutes / terminus_short_turn_station / dp_ppth all added on legacy DB
- `test_migration_creates_terminus_health_table`
- `test_upsert_initialises_terminus_status_pending` (cancelled=0)
- `test_upsert_initialises_terminus_status_null_when_cancelled`
- `test_upsert_clears_terminus_on_cancellation_flip`
- `test_upsert_preserves_terminus_on_normal_refetch`
- `test_upsert_overwrites_dp_ppth_on_conflict`

### Modified `test_exporter.py`

- `test_latest_json_includes_terminus_fields`
- `test_monthly_archive_includes_terminus_fields`

### Test isolation

- Clock: classify() takes `now: datetime` parameter — no `freezegun` dependency added
- HTTP: pass a fake client (duck-typed) into terminus functions; tests construct one that returns fixture XML

### No live API in tests

All fixtures local. Existing fetcher tests already follow this pattern.

## Verification

End-to-end manual verification after deploy:

1. **Migration:** `docker compose up -d s7bb-fetcher` on VM → check `sqlite3 data/s7bb.db ".schema arrivals"` shows the 4 new columns (terminus_status, terminus_delay_minutes, terminus_short_turn_station, dp_ppth) and `.schema terminus_health` shows the health table.
2. **Seed:** wait one fetch cycle → `SELECT COUNT(*) FROM arrivals WHERE terminus_status='pending'` > 0; cancelled rows have `terminus_status IS NULL`.
3. **Match:** wait ~30 min for terminus polling → `SELECT terminus_status, COUNT(*) FROM arrivals GROUP BY terminus_status` shows non-zero `arrived` count.
4. **Delay:** spot-check one row where actual_time != scheduled_time at Baierbrunn → terminus_delay_minutes should also reflect München arrival delay (likely similar magnitude).
5. **Short-turn:** wait for an organic short-turn event (rare). Confirm `terminus_status='short_turn'` and `terminus_short_turn_station` is set to a station from the dp.ppth.
6. **Export:** trigger `uv run s7bb-export` → confirm `latest.json` arrivals[0] contains the 3 new keys.
7. **TS build:** `cd site && npm run build` — type-check passes with new optional fields.
8. **Log inspection:** `journalctl -u docker-s7bb-fetcher | grep terminus` → expect periodic `INFO terminus: ...` lines, no `ERROR` lines under normal operation.
9. **Quota:** rate-limit headers from DB API show usage approx 2–4× previous baseline. No 429s.

Phase 2 (UI) is out of scope here. Once Phase 1 is shipped and data is flowing for ≥1 week, brainstorm Phase 2 separately (badge in today list + archive column + daily aggregate).
