# Design: Train number inclusion (Phase 1)

- **Date:** 2026-05-19
- **Status:** Approved (brainstorming → ready for implementation plan)
- **Author:** Martin Zehetmayer (via Claude Code)
- **Release impact:** `feat` → MINOR (target `0.6.0`)

## Problem

The DB Timetables plan XML carries a public train number (Zugnummer) on
the `<tl>` element (attribute `n`, e.g. `n="6800"`). The fetcher parser
discards `<tl>` entirely. The train number is therefore absent from the
SQLite DB, from `latest.json`, and from every `archive/*.json`. We want
it captured going forward and exposed in the data artifacts.

### Investigation findings (verified)

- `<tl n>` is present on every S7 `<s>` in plan responses. Confirmed
  live: current-hour plan returns e.g. `n="6769"`, `n="6762"`.
- The stored `train_id` is the DB internal stop id
  (`<bignum>-<YYMMDDHHMM>-<stopseq>`, e.g.
  `9200032258854766354-2605051243-5`). It does **not** contain the
  Zugnummer. Train number is not derivable from existing stored data.
- The DB Timetables `/plan/{eva}/{date}/{hour}` endpoint has **no
  history**. Probed live with the production key: current hour `200`;
  yesterday, 4-days-ago, and 14-days-ago all `404` empty. Re-fetching
  past plans to backfill is impossible.

## Scope

**In scope (Phase 1, this spec):**

- Parse `<tl n>` into the record going forward.
- New nullable `train_number` column in SQLite (string).
- Field flows into `latest.json` and `archive/*.json`.
- Site TypeScript `Arrival` interface + test fixtures kept in sync
  (no UI rendering — audience is non-technical residents).

**Out of scope (recorded, not built — "Phase 2"):**

Retroactive backfill of the ~913 pre-existing rows and historical
archive JSON. Not possible from source: the API 404s on all past dates
(verified) and the number is not in the opaque `train_id`. The only
future path is a heuristic mapping
`(local departure HH:MM, direction_bucket, weekday-type) → n`, built
from accumulated forward data after Phase 1 has run ~1–2 weeks. Such
values would be inferred, not authoritative, and must be labelled as
such. Deferred follow-up, intentionally not in this spec.

## Decisions (locked during brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Scope | Phase 1 only; pre-existing rows stay `NULL` | Phase 2 blocked on data accumulation; heuristic, non-authoritative |
| UI | Data-only, no rendering | Non-technical audience; train number is operational noise |
| Type | `String`, nullable | Lossless, no numeric assumptions; matches how line/ids are handled |
| TS contract | Sync `Arrival` interface + fixtures, no render | Keeps JSON↔TypeScript contract honest; tiny diff |
| Upsert | Approach A: include in `ON CONFLICT DO UPDATE SET` | Matches existing `direction_bucket` precedent; rows re-observed in plan window self-fill |

## Design

### 1. Data flow

No new API calls, no new files, no new UI. `<tl n>` (already fetched) →
parser → `ArrivalRecord` → SQLite column → exporter SELECT →
`latest.json` + `archive/*.json` → site `Arrival` interface.

### 2. Schema + migration (`fetcher/src/s7bb_fetcher/storage.py`)

- `SCHEMA`: add `train_number TEXT` (nullable, no default), placed
  after `reason`.
- `_migrate()`: add a branch — if `train_number` not in
  `PRAGMA table_info` columns → `ALTER TABLE arrivals ADD COLUMN
  train_number TEXT`. No backfill `UPDATE` (Phase 1: existing rows stay
  `NULL`). Mirrors the existing `direction_bucket` migration structure.
- `upsert_records`: add `r.train_number` to the INSERT value tuple and
  column list; add `train_number = excluded.train_number` to the
  `ON CONFLICT(train_id, scheduled_time) DO UPDATE SET` clause
  (Approach A — a row re-observed within the plan window self-fills).

### 3. Parser (`fetcher/src/s7bb_fetcher/parser.py`)

- `ArrivalRecord`: add `train_number: str | None` (placed immediately
  after `train_id`).
- In the plan loop, extract defensively:
  - find `<tl>` child of the `<s>` stop element;
  - `train_number = tl.get("n").strip()` when `<tl>` exists and `n` is
    non-empty, else `None`;
  - a missing `<tl>` or empty `n` yields `None` and the row is **still
    emitted** (relief / extra / replacement trains may lack it).
- Pass `train_number=train_number` into the `ArrivalRecord(...)`
  constructor.

### 4. Exporter + JSON (`fetcher/src/s7bb_fetcher/exporter.py`)

- Add `train_number` to both hardcoded SELECT column lists:
  `_query_window` and `export_monthly_archive`.
- `dict(zip(cols, row))` propagates the key automatically. JSON always
  emits `"train_number"`, value `null` when absent — consistent shape,
  same convention as `reason` / `actual_time`.
- Aggregates are untouched: the train number is a per-arrival attribute
  only, never aggregated.

### 5. Site TypeScript contract (`site/src/data.ts` + fixtures)

- `Arrival` interface: add `train_number: string | null`.
- No rendering in `today.ts`, `archive-detail.ts`, `stats.ts`, or
  anywhere else.
- `site/src/data.test.ts` builds `Arrival` objects via an `arrival(overrides)`
  helper with a full default object. Add one line `train_number: null` to
  that default; per-call literals need no change (overrides are partial).
- `site/src/archive.test.ts` mocks fetched JSON; adjust only if it
  constructs typed `Arrival` literals that would fail type-check.

### 6. Tests (fetcher)

- `fetcher/tests/fixtures/plan.xml` (synthetic fixture): add
  `<tl ... n="...">` to each `<s>` (the `plan_real.xml` fixture already
  has it).
- `test_parser.py`: assert `train_number` is parsed from `<tl n>`; add a
  case where `<tl>` is missing → `train_number is None` and the row is
  still present.
- `test_storage.py`: round-trip including the column; migration on a
  pre-column DB adds the `NULL` column without error; a re-observed row
  updates `train_number` (Approach A behaviour).
- `test_exporter.py`: assert the key is present in `arrivals[]` of both
  `latest.json` and a monthly archive; `null` for rows lacking it.

### 7. Release (per CLAUDE.md post-merge trigger)

New data field = `feat` → MINOR bump. After merge to `main`:

1. Bump `fetcher/pyproject.toml` `0.5.2` → `0.6.0`.
2. `cd fetcher && uv sync --no-dev` (sync `uv.lock`).
3. `CHANGELOG.md`: rename `[Unreleased]` → `[0.6.0] - YYYY-MM-DD`, entry
   under `### Added`.
4. `chore(release): 0.6.0`, tag `v0.6.0`, push tag.
5. GitHub Release at the Releases page from the CHANGELOG section.

## Risks / notes

- Plan window is short, so most of the 913 existing rows are never
  re-observed and remain `train_number = NULL`. Expected and accepted
  (Phase 1 only).
- Defensive `None` handling required: relief/extra trains can lack
  `<tl>` or `n`. Row must still be recorded.
- Two exporter SELECT column lists are hardcoded and must both be
  updated, or the archive path silently omits the field.

## Files touched

- `fetcher/src/s7bb_fetcher/parser.py`
- `fetcher/src/s7bb_fetcher/storage.py`
- `fetcher/src/s7bb_fetcher/exporter.py`
- `fetcher/tests/fixtures/plan.xml`
- `fetcher/tests/test_parser.py`
- `fetcher/tests/test_storage.py`
- `fetcher/tests/test_exporter.py`
- `site/src/data.ts`
- `site/src/data.test.ts` (one line in the `arrival()` default builder);
  `site/src/archive.test.ts` only if typed `Arrival` literals break
- `CHANGELOG.md` (at release time)
- `fetcher/pyproject.toml`, `fetcher/uv.lock` (at release time)
