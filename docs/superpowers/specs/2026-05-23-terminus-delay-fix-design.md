# Terminus delay fix — design

Resolves issue [#51](https://github.com/s7bb/s7bb.github.io/issues/51): every
`terminus_status='arrived'` row carries `terminus_delay_minutes=0` because
the DB Timetables `/fchg` endpoint omits the `pt` (planned time) attribute
for S-Bahn arrivals. `_arrival_delay_minutes` in
`fetcher/src/s7bb_fetcher/terminus.py:136` therefore short-circuits to 0
on every late train.

## Context

Phase 1 terminus tracking (#49 / v0.7.0) and the trip-id-prefix fix
(#50 / v0.7.1) shipped a working classifier for **status**
(`arrived` / `short_turn` / `cancelled` / `pending`). The **delay** field
attached to `arrived` rows is structurally broken: against the live
`/fchg` for both terminus EVAs (Wolfratshausen `8006550`, München Hbf
Gl.27-36 `8098261`), 0/48 `<ar>` entries carry `pt`. Only `ct` (changed
time) is present. The current code yields `delta = ct - pt = ct - 0`,
which we explicitly guard against by returning `0`.

Result: the site will tell residents *"S7 erreichte Endhaltestelle
pünktlich"* even when the train ran 6 minutes late to Wolfratshausen.
Misleading enough that the public-facing terminus badge (planned Phase
2) cannot ship on top of it.

## Architecture

Fetch the planned arrival time for every pending trip from the terminus
station's `/plan/{eva}/{date}/{hour}` response and join into the
classifier alongside the existing `/fchg` poll.

The decision tree, components, and DB schema are otherwise unchanged
from the Phase 1 spec
(`docs/superpowers/specs/2026-05-22-terminus-tracking-design.md`); this
spec narrows scope to the `pt` lookup.

```
APScheduler _fetch_job (every 5 min):
  1. fetch_baierbrunn_now()              (existing)
  2. parse_timetable()                   (existing)
  3. upsert_records()                    (existing)
  4. update_terminus_for_window():
       per direction with pending trains:
         a. /fchg/{terminus_eva}          (existing)
         b. /plan/{terminus_eva}/{date}/{hour}  for each hour covered by
            pending trains' expected terminus-arrival times          NEW
         c. classify(pending, fchg_entry, plan_pt, now)              MODIFIED
```

### Plan-hour set

For each direction's pending list, compute the set of
`(YYMMDD, HH)` tuples covering the trips' planned terminus arrival
times:

```
expected_terminus_dt = scheduled_time_utc + TRAVEL_TIME_MINUTES[bucket]
                       (then convert to Europe/Berlin for date/hour)
hour_key = (expected_terminus_dt.strftime("%y%m%d"),
            expected_terminus_dt.strftime("%H"))
```

Typical 2 h pending window × 5 min cadence ⇒ ≤ 2 distinct hours per
direction per cycle (most cycles 1). The set is built once per cycle
and deduplicated before any HTTP call.

The DB Timetables `/plan/{eva}/{date}/{hour}` endpoint is documented
to return all arrivals within that local-time hour at `eva`. Times are
in Europe/Berlin (`YYMMDDHHMM`), matching the convention already used
by `parser._parse_db_time`.

### Plan-pt index

For each fetched plan XML, walk `<s>` blocks and read the **arrival**
planned time — `s/ar/@pt`. (Trains in the plan response also carry
`s/dp/@pt` for the planned departure from terminus to the next leg —
not relevant; we want the moment the train *arrives* at terminus.)

Key by `trip_prefix(s/@id)` so the join is identical to the `/fchg`
index (`build_index`).

```
plan_pt: dict[trip_prefix, str_db_time] = {}
for s in plan_xml.findall(".//s"):
    prefix = trip_prefix(s.get("id") or "")
    if not prefix:
        continue
    ar = s.find("ar")
    if ar is None:
        continue
    pt = ar.get("pt")
    if pt:
        plan_pt[prefix] = pt
```

Result is shallow `(trip_prefix → "YYMMDDHHMM")`. Caller resolves to a
UTC datetime only when computing the delta, mirroring
`_parse_db_time` in terminus.py.

### Delay computation

`_arrival_delay_minutes` gains a second argument:

```python
def _arrival_delay_minutes(entry, planned_pt: str | None) -> int:
    ar = entry.find("ar")
    if ar is None:
        return 0
    ct = ar.get("ct")
    pt = ar.get("pt") or planned_pt
    if not ct or not pt:
        return 0
    return int((_parse_db_time(ct) - _parse_db_time(pt)).total_seconds() / 60)
```

Three-tier fallback:

1. `/fchg` carries `pt` (long-distance services do). Use it. — unchanged
2. `/plan` lookup hit. Use that.                                — new
3. Neither. Return `0`. Logged at DEBUG to keep noise down.     — fallback

Tier 3 stays so a transient `/plan` outage degrades to today's
behaviour rather than crashing the cycle.

### classify() signature

```python
def classify(
    pending: PendingTrain,
    entry: etree._Element | None,
    now: datetime,
    drilldown,
    planned_pt: str | None = None,   # NEW
) -> TerminusUpdate | None:
```

Default `None` keeps the existing unit tests (which test the
on-time / cancelled / short-turn paths without delay deltas) compiling
unchanged. Two new test cases exercise the populated path.

### Orchestrator wiring

`update_terminus_for_window` per direction:

1. Build `hour_keys` set from `group` pending trains.
2. Fetch `/plan/{eva}/{date}/{hour}` for each key; on HTTP error log
   and continue with the keys already fetched. `plan_pt = {**a, **b}`.
3. Existing `/fchg` fetch + index, unchanged.
4. Per-train: `update = classify(p, entry, now, drilldown=_drilldown,
   planned_pt=plan_pt.get(trip_prefix(p.train_id)))`.

A partial-plan outage simply degrades affected trains to delay 0 (tier
3 fallback) instead of dropping the whole cycle.

### Why runtime, not at insert time

The alternative — store `planned_terminus_time` as a column on
`arrivals`, populated by the Baierbrunn parser via a per-train
`/plan/{terminus_eva}/{hour}` call — was rejected:

- Adds a schema migration and a backfill problem for legacy rows.
- Couples the Baierbrunn fetch path to terminus geography; today
  `parser.py` is station-agnostic.
- Every Baierbrunn row would force a terminus plan fetch even if it
  later cancels at Baierbrunn (never reaches terminus classification).
  Runtime variant only pays the plan cost for rows that survive into
  the pending window.

Quota cost of the runtime variant: **+1–2 plan calls per direction per
5 min cycle**. Aligned with the existing Phase 1 quota table.

## Components & files

### Modified

- `fetcher/src/s7bb_fetcher/terminus.py`
  - `_arrival_delay_minutes(entry, planned_pt)` — second arg, three-tier fallback.
  - `classify(..., planned_pt=None)` — pass-through to delay helper.
  - `_build_plan_pt_index(plan_xml) -> dict[str, str]` — new pure helper.
  - `_hour_keys(group) -> set[tuple[str, str]]` — new pure helper.
  - `update_terminus_for_window` — fetch terminus `/plan` per hour key, build merged plan_pt dict, pass into classify.

- `fetcher/tests/test_terminus.py`
  - New fixtures (below) used by added unit tests.
  - Adapt `test_classify_arrived_on_time` to pass `planned_pt` and keep the assertion (delay still 0 when ct == pt).
  - New `test_classify_arrived_with_delay_via_plan_pt`: `/fchg` entry has only `ct`; `planned_pt` argument supplied → delta computed.
  - New `test_classify_arrived_zero_when_no_pt_anywhere`: regression guard for the tier-3 fallback.
  - New `test_build_plan_pt_index` — pure XML→dict.
  - New `test_hour_keys_dedup` — covers two pending trains in the same hour producing one key.
  - New `test_update_terminus_for_window_fetches_plan_and_applies_delay` — orchestrator-level: fake client returns the new plan fixture + the existing fchg fixture; assert delay written to DB.
  - New `test_update_terminus_for_window_tolerates_plan_http_error` — fake client raises on plan; classifier still runs from /fchg; delay falls back to 0; cycle does not abort.

### New fixtures

- `fetcher/tests/fixtures/terminus_munich_delayed_no_pt.xml`
  Variant of `terminus_munich_delayed.xml` with the `pt` attribute
  stripped — matches live S-Bahn `/fchg` behaviour. Used to prove the
  delta now comes from the plan lookup.
- `fetcher/tests/fixtures/terminus_munich_plan.xml`
  Minimal `/plan` response containing the same `TRIP_PREFIX` with
  `<ar pt="...">` populated at the planned hour.

### Unchanged

- `fetcher/src/s7bb_fetcher/api.py` — `fetch_plan(eva, date, hour)` already exists.
- `fetcher/src/s7bb_fetcher/parser.py` — Baierbrunn parsing untouched.
- `fetcher/src/s7bb_fetcher/storage.py` — no schema change.
- `fetcher/src/s7bb_fetcher/exporter.py` — same JSON shape; `terminus_delay_minutes` already exported.
- `site/*` — no contract change; the integer becomes accurate, that's it.

## Data flow

```
/plan/{terminus_eva}/{date}/{hour}  ──► _build_plan_pt_index ──► {trip_prefix: pt}
                                                                       │
/fchg/{terminus_eva}  ─────────────► build_index ──► {trip_prefix: <s>}│
                                                              │        │
                                       per pending train:     ▼        ▼
                                       classify(pending, entry, now,
                                                drilldown, planned_pt) ─► TerminusUpdate
                                                                          (delay_minutes
                                                                           now correct)
```

## Error handling

| Failure                                  | Behaviour                                                                                            |
|------------------------------------------|------------------------------------------------------------------------------------------------------|
| `/plan/{eva}/{date}/{hour}` HTTP error   | Caught; log via `log.exception`; affected pending trains fall back to delay 0 (tier 3). Cycle continues. |
| Plan XML missing the train               | Tier 3 fallback. Logged at DEBUG.                                                                    |
| `/fchg` HTTP error                       | Unchanged — entire direction stays pending; next cycle retries.                                      |
| `update_terminus_for_window` raises      | Unchanged — caught by `service._fetch_job()`.                                                        |

## Historical data

Forward-only fix. Rows that were classified `arrived` with
`terminus_delay_minutes=0` between v0.7.0 deploy and this fix may
under-report a real delay. There is no recoverable source of truth
once the row has left the 2 h pending window (the `/fchg` change feed
ages out, and we did not store the trip-level plan at the time).

Two operational notes:

1. The CHANGELOG `[Unreleased]` entry for this fix must state plainly
   that historical `arrived/0` delays are not retroactively corrected.
2. After deploy, the VM operator may optionally run

   ```sql
   UPDATE arrivals
      SET terminus_status         = 'pending',
          terminus_delay_minutes  = NULL,
          terminus_short_turn_station = NULL
    WHERE terminus_status = 'arrived'
      AND terminus_delay_minutes = 0
      AND scheduled_time >= datetime('now', '-2 hours');
   ```

   to re-evaluate the freshest window with the new code path. Rows
   older than ~2 h cannot be recovered.

## Testing

Strict TDD: write failing tests first, then implement until green.

Unit tests live in `fetcher/tests/test_terminus.py`. The new fixtures
are byte-stable XML snippets following the existing fixture style
(see `terminus_munich_delayed.xml` for the template). No live API in
tests; no `freezegun`.

Acceptance covers:

- Delay computed from the **plan** `pt` when `/fchg` omits it.
- Delay still computed from the **/fchg** `pt` when present (long-distance services).
- Tier-3 fallback returns 0 when both sources lack `pt`.
- Plan HTTP failure does not abort the fetch cycle.
- `update_terminus_for_window` integration test asserts the correct
  delay lands in the `arrivals` row.

## Verification

After deploy on the VM:

1. `docker compose up -d s7bb-fetcher` — restart with new image.
2. Wait one 5-min cycle; check fetcher logs (`journalctl -u
   docker-s7bb-fetcher | grep terminus`) — expect `INFO` lines only,
   no `ERROR`, and no spike in DB API 4xx/5xx counts.
3. Wait for a pending row whose Baierbrunn `delay_minutes > 0` to
   reach `terminus_status='arrived'`. Verify
   `terminus_delay_minutes > 0` on that row (the original symptom).
4. Confirm `latest.json` published to `s7bb-data` carries the new
   non-zero delay on the freshest cycle.
5. Spot-check: pick a recent `arrived` row in the dashboard JSON where
   the Baierbrunn delay is +3 → +6 min. Terminus delay should be the
   same order of magnitude (real S7 typically loses ≤1 min between
   Baierbrunn and terminus, not enough to flip the sign).

## Release

Patch bump: **v0.7.2**. Conventional commit `fix(terminus): compute
arrival delay from /plan pt when /fchg omits it`. CHANGELOG
`[Unreleased]` → `[0.7.2]`. Issue #51 closed by the merge commit's
`Fixes #51` trailer.
