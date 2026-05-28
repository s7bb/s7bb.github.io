# Terminus pt resolve — design

Fixes a regression on top of the v0.7.2 terminus delay fix
([#54](https://github.com/s7bb/s7bb.github.io/pull/54)).
`terminus_delay_minutes` is still reported as `0` for some
`terminus_status='arrived'` rows whose scheduled terminus arrival
falls into a different `/plan` hour than the one the tracker queried.

## Context

Observed against live data on 2026-05-28:

| Train | Baierbrunn sched | Baierbrunn delay | Wolfratshausen sched | Wolfratshausen actual | Reported delay | Real delay |
|-------|------------------|------------------|----------------------|-----------------------|----------------|------------|
| 6766  | 14:40 local      | 19 min           | 14:54 local          | 15:16 local           | **0 min**      | 22 min     |

Verification:

- `/plan/8006550/260528/14` → `<tl c="S" n="6766"/>`, `<ar pt="2605281454"/>` (scheduled 14:54)
- `/fchg/8006550` → entry `id="-3055705683960046530-2605281414-16"` → `<ar ct="2605281516"/>` (actual 15:16)
- Same trip prefix as Baierbrunn row `-3055705683960046530-2605281414-12`, same train number 6766

Real delay at terminus = 22 min, not 0.

### Root cause

`fetcher/src/s7bb_fetcher/terminus.py:_hour_keys` estimates terminus
arrival as `scheduled_baierbrunn + TRAVEL_TIME_MINUTES[bucket]` and
queries `/plan` for that hour. With
`TRAVEL_TIME_MINUTES["wolfratshausen"] = 20`, train 6766 at 14:40
projects to 15:00 → tracker queries `/plan` **hour 15**. Real
scheduled terminus arrival is 14:54 → lives in `/plan` **hour 14**.
Trip prefix missing from `plan_pt` index → `planned_pt = None` →
`_arrival_delay_minutes` short-circuits to `0`.

Average travel time wolfratshausen is closer to ~14 min, not 20. Any
Baierbrunn-departure time `xx:m` where `m + offset_estimate` crosses
an hour boundary while `m + offset_real` does not (or vice versa) is
silently miscounted.

## Architecture

Eliminate the estimate. Resolve the **authoritative** scheduled
terminus arrival time at the moment the Baierbrunn row is ingested,
persist it on the row, and have the terminus tracker read it back —
no `/plan` lookup at classification time.

```
APScheduler fetch_job (every 5 min):
  1. fetch_baierbrunn_now()             (existing)
  2. parse_timetable()                  (existing)
  3. upsert_records()                   (existing)
  4. resolve_terminus_pts(new_rows)     NEW — populates terminus_scheduled_pt
  5. update_terminus_for_window():
       a. /fchg/{terminus_eva}          (existing)
       b. for rows with NULL terminus_scheduled_pt: re-attempt resolve  NEW
       c. classify(pending, fchg_entry, now)   MODIFIED — no planned_pt param
```

Hour-boundary bug is eliminated by construction: the stored pt comes
straight from the API for the trip, not from a derived hour key.

### Hour selection at resolve time

`resolve_terminus_pts` still needs to pick which `(eva, date, hour)`
combinations to query `/plan` for. Inaccuracy here only affects
**which hour bucket(s) we fetch**, not the stored value. Strategy:

```
offset = BAIERBRUNN_TO_TERMINUS_OFFSET_MIN[bucket]
estimated_pt_local = (scheduled_time_utc + offset).astimezone(_DE_TZ)
hour_keys = { (date_of(estimated_pt_local), hour_of(estimated_pt_local)) }
if estimated_pt_local.minute >= 50:
    hour_keys.add( (date, hour+1) )
if estimated_pt_local.minute <= 10:
    hour_keys.add( (date, hour-1) )
```

±1 hour safety covers any per-train deviation from the constant.
`BAIERBRUNN_TO_TERMINUS_OFFSET_MIN`:

```python
BAIERBRUNN_TO_TERMINUS_OFFSET_MIN = {
    "muenchen":       30,
    "wolfratshausen": 14,
}
```

Defined in the new `terminus_pt.py` module, independent of the
existing `TRAVEL_TIME_MINUTES` in `terminus.py` (which is kept for
the `_cutoff` legacy-fallback path on NULL pt rows). The two
constants serve different purposes and may diverge:
`BAIERBRUNN_TO_TERMINUS_OFFSET_MIN` only governs which `/plan` hour
to fetch (real pt comes back exact); `TRAVEL_TIME_MINUTES` only
governs the cutoff for legacy rows.

## Data model

New column on `arrivals`:

```sql
ALTER TABLE arrivals ADD COLUMN terminus_scheduled_pt TEXT
```

Raw DB time string `YYMMDDHHMM` (Europe/Berlin), `NULL` when
unresolved. No index — lookups are by `train_id` (already keyed).

New cache + tombstone tables:

```sql
CREATE TABLE terminus_plan_cache (
    eva          TEXT NOT NULL,   -- terminus EVA
    date         TEXT NOT NULL,   -- YYMMDD local DE
    hour         TEXT NOT NULL,   -- HH local DE
    trip_prefix  TEXT NOT NULL,
    pt           TEXT NOT NULL,   -- YYMMDDHHMM local DE
    fetched_at   TEXT NOT NULL,   -- ISO UTC
    PRIMARY KEY (eva, date, hour, trip_prefix)
);

CREATE INDEX idx_terminus_plan_cache_window
    ON terminus_plan_cache(eva, date, hour);

CREATE TABLE terminus_plan_fetch_log (
    eva         TEXT NOT NULL,
    date        TEXT NOT NULL,
    hour        TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (eva, date, hour)
);
```

`terminus_plan_fetch_log` tombstones a successful fetch even when the
plan response contains zero matching `<ar>` entries. Cache hit logic
is:

1. Does `terminus_plan_fetch_log` have a row for `(eva, date, hour)`?
   - No → hit API, populate both tables, return resolved map.
   - Yes → return `SELECT trip_prefix, pt FROM terminus_plan_cache WHERE (eva, date, hour) = …` (may be empty; legitimate).

Retention: 7-day window (same as `window_days` in exporter). Run as
part of existing maintenance step in `service.py`.

Migrations: appended to `storage.py:_apply_migrations` per existing
pattern (entries 4 = column, 5 = cache table, 6 = tombstone table).

## Module layout

**New file `fetcher/src/s7bb_fetcher/terminus_pt.py`**

```python
"""Resolve scheduled terminus arrival time (pt) for arrivals.

Single authoritative source for trip → terminus pt mapping.
Used by ingestion (populate at row insert) and by the terminus
tracker (repair NULL rows on next cycle). Cache in SQLite; on miss
hits DB Timetables /plan at terminus EVA.
"""

@dataclass(frozen=True)
class TripKey:
    train_id: str
    direction_bucket: str   # "muenchen" | "wolfratshausen"
    scheduled_time: str     # ISO UTC

def resolve_terminus_pts(
    conn: sqlite3.Connection,
    client: ApiClient,
    trips: Iterable[TripKey],
) -> dict[str, str | None]:
    """{train_id: pt | None}. pt is the raw YYMMDDHHMM string."""
```

Internal helpers (private):

```python
def _candidate_hour_keys(bucket, sched_iso) -> set[tuple[str, str]]
def _cache_lookup(conn, eva, date, hour) -> dict[str, str] | None
def _cache_populate(conn, eva, date, hour, plan_xml, now_utc) -> None
def _evas_for_bucket(bucket) -> tuple[str, ...]   # delegates to
                                                  # TERMINUS_EVA_FOR_BUCKET
```

**`service.py:fetch_job` hook** — after `storage.upsert_arrivals`:

```python
new_pending = conn.execute(
    "SELECT train_id, direction_bucket, scheduled_time FROM arrivals "
    "WHERE train_id IN (...) AND terminus_scheduled_pt IS NULL"
).fetchall()
try:
    pts = resolve_terminus_pts(conn, client,
                               (TripKey(*row) for row in new_pending))
    conn.executemany(
        "UPDATE arrivals SET terminus_scheduled_pt = ? WHERE train_id = ?",
        [(pt, tid) for tid, pt in pts.items() if pt is not None],
    )
    conn.commit()
except Exception:
    logger.exception("fetch_job: terminus_pt resolve failed")
```

Wrapped in try/except so a terminus_pt failure cannot break ingestion
(same pattern as the existing terminus update block).

**`terminus.py` changes**

Remove:
- `_build_plan_pt_index`
- `_hour_keys`
- `planned_pt` parameter on `classify` and `_arrival_delay_minutes`
- `/plan` fetch loop inside `update_terminus_for_window`

Keep (no change):
- `TRAVEL_TIME_MINUTES` — still used by `_cutoff` as legacy fallback for rows with NULL `terminus_scheduled_pt`. `terminus_pt.py` defines its own `BAIERBRUNN_TO_TERMINUS_OFFSET_MIN` for hour-key selection; the two constants are independent and may diverge over time without coupling.

Modify:
- `PendingTrain` — add `terminus_scheduled_pt: str | None`
- `_arrival_delay_minutes(entry, pt: str)` — `pt` required
- `_cutoff(pending)` — when `terminus_scheduled_pt` is set, returns `parse(pt) + CUTOFF_GRACE_MINUTES`. When NULL (legacy pre-deploy rows), falls back to the existing `sched + TRAVEL_TIME_MINUTES[bucket] + CUTOFF_GRACE_MINUTES` formula so those rows still progress.
- `update_terminus_for_window`:
    - Before classification, gather pending rows with NULL `terminus_scheduled_pt`, call `resolve_terminus_pts`, UPDATE rows that resolve.
    - Classification uses `pending.terminus_scheduled_pt` directly.

## Testing

**New file `tests/test_terminus_pt.py`**

1. `test_resolve_cache_hit_no_api` — pre-populated cache + tombstone; mock client asserts no call.
2. `test_resolve_cache_miss_hits_api` — empty; mock client returns canned `/plan` XML; cache + tombstone populated.
3. `test_resolve_tombstone_empty_legitimate` — tombstone present, cache empty → API not called; trips in that hour return `None`.
4. `test_candidate_hour_keys_normal` — Baierbrunn 14:00 wolfratshausen → only hour 14.
5. `test_candidate_hour_keys_boundary_regression` — Baierbrunn 14:40 wolfratshausen → hours 14 and 15 both queried (estimated pt 14:54 is in the ±10 min safety band of the 15:00 boundary). Hour 14 is the one that actually carries the 6766 entry; the central estimate of 15 alone is wrong, which is the bug.
6. `test_candidate_hour_keys_far_from_boundary` — Baierbrunn 14:10 wolfratshausen → only hour 14 (estimated pt 14:24; not in any safety band).
7. `test_resolve_muenchen_multi_eva` — bucket=muenchen → tries both EVAs.
8. `test_resolve_api_failure_returns_none` — client raises; train_id → None; no DB writes.
9. `test_resolve_no_trip_match_returns_none` — API returns plan; trip_prefix absent → None.

**Modify `tests/test_terminus.py`**

10. `test_arrival_delay_uses_stored_pt` — `<ar>` has ct, no pt; stored pt resolves delay.
11. `test_arrival_delay_regression_6766` — `ct=2605281516`, stored `pt=2605281454` → delay 22 (not 0).
12. `test_cutoff_uses_stored_pt` — pending with stored pt → cutoff = pt + grace.
13. `test_cutoff_legacy_null_pt_falls_back` — pt NULL → old `sched + offset` formula.
14. `test_update_repairs_null_pt` — pending row with NULL pt → update cycle resolves + populates + classifies in same call.

**Modify `tests/test_service.py`**

15. `test_fetch_job_populates_terminus_pt` — full ingest fixture → rows have terminus_scheduled_pt.
16. `test_fetch_job_terminus_pt_failure_does_not_break_ingest` — resolve raises; rows inserted with NULL pt; job succeeds.

**Modify `tests/test_storage.py`**

17. `test_migration_adds_terminus_scheduled_pt_column`
18. `test_migration_creates_cache_tables`

**Retention**

19. `test_cache_retention_drops_old_rows` — date 8 days old removed; 1 day old retained.

## Rollout

- Conventional Commits: `fix(terminus): resolve scheduled pt at ingest, fix hour-boundary delay bug`
- SemVer: PATCH → **0.9.3**
- CHANGELOG entry under `[Unreleased] → Fixed`:
  > Terminus delay incorrectly reported as 0 min when scheduled
  > terminus arrival fell into a different /plan hour than the
  > estimated one (e.g. Baierbrunn 14:40 → Wolfratshausen 14:54 across
  > the 14↔15 boundary). Scheduled terminus pt now resolved
  > authoritatively at ingest and stored per row; the terminus
  > tracker uses the stored value instead of re-querying /plan.

- Plan file: `docs/superpowers/plans/2026-05-28-terminus-pt-resolve.md` (output of writing-plans skill).
- Per CLAUDE.md "Plan files" rule + memory `feedback_plan_files.md`: spec + plan bundled into the implementation PR.
- VM rollout: `docker compose build s7bb-fetcher && docker compose up -d`
  (per memory `feedback_docker_rebuild.md` — bare `up -d` reuses cached image).
- Post-merge: cut release immediately (`fix` triggers PATCH per CLAUDE.md). Tag `v0.9.3`, `gh release create --latest`.

### Backfill (out of scope)

Historical "arrived" rows with `terminus_delay_minutes=0` whose real
delay was non-zero stay wrong. Decision: fix-forward only. Existing
pending rows auto-repair on their next terminus cycle via the
NULL-repair branch.

### Verification gate

- Unit + integration tests green.
- After VM redeploy, observe ≥ 1 hour of new rows:
    - `terminus_scheduled_pt` populated for new arrivals.
    - `terminus_delay_minutes` is non-zero for late terminus arrivals.
    - Regression case (any Baierbrunn `xx:40` wolfratshausen) no longer drops to 0 when actually late.
- Per `verification-before-completion` skill.
