# Terminus arrival tracking — production bug fix (post-0.7.0)

**Status:** ready to ship. Follow-up to `2026-05-22-terminus-tracking.md`
(Phase 1 implementation, merged as #49 / released as 0.7.0).

**Goal:** Make the terminus classifier produce real `arrived` /
`short_turn` rows. Phase 1 shipped working tests but the live behaviour
collapsed to "everything is `pending` or `cancelled`" because two
assumptions baked into the spec do not hold against the live Timetables
API for S-Bahn services.

## Symptom (observed 2026-05-22, ~7.75 h after 0.7.0 deploy)

VM SQLite + remote `s7bb-data/latest.json` agree:

- 38 rows with `terminus_status='cancelled'`, none of which have
  `cancelled=1` at Baierbrunn — i.e. the trains did depart.
- 7 rows with `terminus_status='pending'` (recent cycles, still
  inside the cutoff window).
- 0 rows with `terminus_status='arrived'` or `'short_turn'`.
- `terminus_health.zero_match_streak = 93` for **both** terminus
  EVAs (`8000261` München, `8006550` Wolfratshausen). 93 cycles × 5 min
  ≈ 7.75 h, matching the full uptime since deploy. Every cycle missed
  every train.

## Root causes (both verified against live API on 2026-05-22)

### 1. `/fchg` for S-Bahn drops the `<tl>` element — `train_number` is not a viable join key

`build_index()` in `fetcher/src/s7bb_fetcher/terminus.py` indexes the
terminus and intermediate `/fchg` responses by `tl/@n`. Live evidence:

- `GET /fchg/8006550` (Wolfratshausen): 106 `<s>` blocks, **0** have a
  `<tl>` child. Every block carries `<ar>` with `l="S7"` but no train
  number.
- `GET /fchg/8098261` (Munich Hbf Gl.27-36): 158 `<s>` blocks, only 4
  have `<tl>` — all of those 4 are long-distance (`ICE`, `ECE`, `RB`).
  Of the 45 S-Bahn blocks (`l` in `{S5, S6, S7}`), none carry `<tl>`.

The stable cross-station identifier is the `s/@id` attribute. Format:
`<trip>-<YYMMDDHHMM>-<stop_seq>`. Stop sequence varies per station
(Baierbrunn `-5`, München `-16`, Wolfratshausen `-34` for the same
trip); the prefix is constant. Example: pending row
`2802800525858653677-2605222147-30` is matched by the prefix
`2802800525858653677-2605222147` against the Wolfratshausen `/fchg`
entry `2802800525858653677-2605222147-34`. Confirmed for both
directions.

The same defect afflicts `drilldown_short_turn` — intermediate-station
feeds also omit `<tl>` for S-Bahn.

### 2. `MUENCHEN_HBF_EVA = "8000261"` is the wrong station

`8000261` is the regional München Hbf (long-distance platforms). The
S7 terminus name in `dp_ppth` is "München Hbf Gl.27-36" — the surface
S-Bahn platforms, modeled as a *separate* station in the API.

`GET /station/München%20Hbf%20Gl.27-36` returns:
```
<station meta="270002|8000261|8098262|8098263"
         name="München Hbf Gl.27-36" eva="8098261" ds100="MH  N" .../>
```

The correct EVA is **`8098261`**. `8000261` appears in the `meta`
sibling list, which is what the spec author confused with the primary
EVA. `8006550` for Wolfratshausen is correct.

## Fix scope

`fetcher/src/s7bb_fetcher/`:

- `terminus.py`
  - Add `trip_prefix(sid)` helper: `rpartition("-")` returning the head
    (empty string if no separator — caller must skip).
  - `build_index()` keyed on `trip_prefix(s/@id)` instead of `tl/@n`.
  - `PendingTrain` carries `train_id` (Baierbrunn `s/@id`) instead of
    `train_number`. `train_number` is still populated in the DB by the
    Baierbrunn parser path; it is just not used for terminus matching.
  - `TerminusUpdate` carries `train_id` instead of `train_number`.
  - `classify()` passes `pending.train_id` to drilldown.
  - `drilldown_short_turn()` parameter renamed `train_id`; matches by
    trip-prefix.
  - `list_pending_trains()` selects `train_id`; drops the
    `train_number IS NOT NULL` filter (it was a proxy for "has join
    key"; now redundant given `train_id` is NOT NULL by schema).
  - `update_terminus_for_window()` builds `updates[].train_id`.
  - `MUENCHEN_HBF_EVA = "8098261"` (and the
    `STATION_NAME_TO_EVA["München Hbf Gl.27-36"]` entry follows the
    constant, so no second edit needed).
- `storage.py`
  - `update_terminus_fields()` matches `WHERE train_id = ? AND
    scheduled_time = ?` — the row's unique key. Drops the ±4 h window
    (irrelevant once we key on the unique pair).
  - Trim unused `timedelta` import.

`fetcher/tests/`:

- `tests/fixtures/terminus_*.xml`, `tests/fixtures/intermediate_*.xml`
  — regenerated to match the live S-Bahn `/fchg` shape (no `<tl>`;
  `s/@id` realistic `<int>-<YYMMDDHHMM>-<stop_seq>`).
- `tests/test_terminus.py` — keyed lookups switched from train_number
  to the shared `TRIP_PREFIX` constant. New `test_trip_prefix_*` and
  `test_drilldown_unusable_train_id_returns_none` cover the new helper.
- `tests/test_storage.py` — the four `update_terminus_fields_*` tests
  updated to the new `(train_id, scheduled_time)` contract. The "±4 h
  window" test becomes "only matches exact `scheduled_time`".

`CHANGELOG.md`: add a `## [Unreleased]` section with `### Fixed` notes
+ the backfill SQL. Version bump (0.7.1) deferred to the post-merge
release step per `CLAUDE.md`'s post-merge release trigger.

## Backfill / operator runbook

Between 0.7.0 deploy and this fix, ~38 rows were stamped
`terminus_status='cancelled'` even though the underlying train ran
normally to its terminus. The `/fchg` window has rolled past those
trains, so reconstructing the true status from the API is impossible.

Operator steps before bringing the fetcher back up with this fix:

1. `docker compose down s7bb-fetcher` (already done — DB was copied
   to `debug/`).
2. On the VM, against `data/s7bb.db`:
   ```sql
   UPDATE arrivals
      SET terminus_status              = NULL,
          terminus_delay_minutes       = NULL,
          terminus_short_turn_station  = NULL
    WHERE cancelled         = 0
      AND terminus_status   = 'cancelled';
   ```
   Bogus 'cancelled' rows revert to NULL (matches the design's
   "no information" state for legacy rows).
3. `DELETE FROM terminus_health;` — clear the streak counters; the
   first cycle on the new EVA + new key will repopulate them honestly.
4. `docker compose up -d s7bb-fetcher`. Watch
   `docker logs s7bb-fetcher | grep terminus` for the first few
   cycles — `match_count > 0` and the
   `0 matches against eva=8098261 …` warning must NOT appear.
5. Next hourly export pushes the cleaned `latest.json` to
   `s7bb/s7bb-data`.

## Tests added / changed

| Test | Purpose |
|---|---|
| `test_trip_prefix_strips_last_segment` | Handles negative leading ints + edge cases (empty, single token). |
| `test_build_index_keys_by_trip_prefix` | The index uses the new join key. |
| `test_build_index_skips_entries_without_usable_id` | Empty / single-segment ids are ignored, not blown up on. |
| `test_constants_present` | `MUENCHEN_HBF_EVA == "8098261"` (regression guard). |
| `test_drilldown_unusable_train_id_returns_none` | Defensive: zero fetches when prefix cannot be derived. |
| `test_update_terminus_for_window_*` | All updated to `8098261` + `train_id` plumbing. |
| `test_update_terminus_fields_only_matches_exact_scheduled_time` | Replaces the ±4 h window test. |

## Out of scope (Phase 2 still applies)

UI rendering, archive backfill of train_number for pre-Phase-1 rows,
broader DB Timetables resilience work. The fetcher emits the new
columns and the exporter already carries them in `latest.json` /
`archive/*.json` — no contract change.
