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
| Upsert | Approach A, **fill-only**: `train_number = COALESCE(excluded.train_number, train_number)` in `ON CONFLICT DO UPDATE SET` | Re-observed rows self-fill a `NULL`; immutable attribute is never regressed to `NULL` by a later `<tl n>`-less observation (bare `= excluded.` would silently lose a captured value) |

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
  column list; add
  `train_number = COALESCE(excluded.train_number, train_number)` to the
  `ON CONFLICT(train_id, scheduled_time) DO UPDATE SET` clause
  (Approach A, **fill-only** variant — a re-observed row fills a `NULL`,
  but a later observation lacking `<tl n>` must **never** overwrite a
  previously captured value with `NULL`). `train_number` is **assumed**
  immutable for a given `(train_id, scheduled_time)` (the id encodes a
  specific trip instance; its Zugnummer is stable). A bare
  `= excluded.train_number` (the `reason` precedent) would silently and
  irreversibly regress a good value to `NULL` if the relief/extra-train
  edge — flagged in §Risks — recurs on re-observation. `COALESCE`
  satisfies the self-fill rationale and removes that data-loss vector.
  Note `COALESCE` enforces only the NULL-guard, **not** the immutability
  assumption: a re-observation carrying a *different non-NULL* `n` for
  the same key would still overwrite. That path is not expected under
  the assumption above; if it ever occurs it is a data-quality signal,
  not silent loss.

### 3. Parser (`fetcher/src/s7bb_fetcher/parser.py`)

- `ArrivalRecord`: add `train_number: str | None = None` as the
  **last** field (after `reason`), **with the `= None` default**.
  - Placement is load-bearing, not cosmetic. Python dataclass rule: a
    field without a default cannot follow a field with one. Every other
    field (`train_id` … `reason`) has no default, so a defaulted
    `train_number` placed mid-class (e.g. "after `train_id`") makes the
    module raise `TypeError` **at import** → fetcher cannot start → zero
    records written for the whole outage = data loss. Hence: last field.
  - The `= None` default is required for backward compatibility. All
    `ArrivalRecord` construction is keyword-based and none of the
    existing sites pass `train_number`
    (`fetcher/tests/test_cli.py:_seed_db`,
    `fetcher/tests/test_storage.py:_record`,
    `fetcher/tests/test_exporter.py:_make_arrival`). Without the default
    they would all raise `TypeError: missing argument 'train_number'`.
    The default keeps every existing construction site working
    unchanged — notably `test_cli.py`, which is otherwise out of scope.
- In the plan loop, extract defensively. Do **not** chain
  `.get("n").strip()` (a present `<tl>` lacking `n`, or an absent
  `<tl>`, would `AttributeError` and abort `parse_timetable` for the
  whole fetch cycle → no records that cycle). Use the guarded form:

  ```python
  tl = stop.find("tl")
  n = tl.get("n") if tl is not None else None
  train_number = n.strip() if n and n.strip() else None
  ```

  A missing `<tl>` or empty/whitespace `n` yields `None` and the row is
  **still emitted** (relief / extra / replacement trains may lack it).
- Placement is constrained: extract **after** the early-`continue` skip
  guards (`dp is None` / non-S7 / no `pt`, `parser.py:77-87`) and
  **before** the `records.append(ArrivalRecord(...))` (`parser.py:130`).
  Before the skips is functionally harmless but wastes a `find` on
  dropped stops; after the append is impossible (record already built).
  Pass `train_number=train_number` into the `ArrivalRecord(...)`
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

- `Arrival` interface: add `train_number?: string | null` (optional,
  not required). Finalized past `archive/*.json` already in `s7bb-data`
  permanently lack the key — a non-optional `string | null` would
  mis-model them as always-present (runtime value is `undefined`, not
  `null`). The optional `?` keeps the JSON↔TS contract honest across
  pre-0.6.0 archives. No consumer reads the field today, so impact is
  nil now; the `?` is correctness for future readers.
- No rendering in `today.ts`, `archive-detail.ts`, `stats.ts`, or
  anywhere else.
- `site/src/data.test.ts` builds `Arrival` objects via an
  `arrival(overrides: Partial<Arrival>)` helper with a full default
  object. Because `train_number?` is **optional**, the helper and all
  per-call partial literals already type-check unchanged — no edit is
  strictly required. Optionally add `train_number: null` to the default
  object for explicitness; cosmetic, no behavioural or compile effect.
- `site/src/archive.test.ts` mocks fetched JSON; adjust only if it
  constructs typed `Arrival` literals that would fail type-check.

### 6. Tests (fetcher)

- `fetcher/tests/fixtures/plan.xml` (synthetic fixture): every `<s>`
  **already** carries `<tl f="S" t="p" o="800725" c="S" n="676x"/>`
  (lines 4, 9, 14…), as does `plan_real.xml`. No `<tl n>` needs adding
  for the happy path — it is already exercised by the existing fixture.
  The fixture work is the **inverse**: add one extra S7 `<s>` that
  **lacks** `<tl>` (or has an empty/whitespace `n`) so the
  missing-`<tl>` → `train_number is None` branch has a fixture to assert
  against.
- `test_parser.py`: assert `train_number` is parsed from `<tl n>` for a
  normal stop; assert the new no-`<tl>` stop yields `train_number is
  None` **and is still emitted** (total row count unchanged).
- `test_storage.py`: round-trip including the column; migration on a
  pre-column DB adds the `NULL` column without error. Assert fill-only
  upsert: (a) a re-observed row with `<tl n>` fills a previously `NULL`
  `train_number`; (b) a re-observed row **lacking** `train_number`
  (value `None`) does **not** overwrite an already-stored value with
  `NULL` (the `COALESCE` data-loss guard).
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
  `<tl>` or `n`. Row must still be recorded. Use the guarded extraction
  in §3 — a chained `tl.get("n").strip()` `AttributeError`s and aborts
  the whole fetch cycle (loses all records that cycle).
- Dataclass field must be **last** and **`= None`-defaulted** (§3):
  mid-class placement → import-time `TypeError` → fetcher down; no
  default → every existing kwargs construction (incl. `test_cli.py`)
  breaks.
- Upsert is fill-only `COALESCE` (§2): bare `= excluded.train_number`
  would silently, irreversibly regress a captured number to `NULL` on a
  re-observation missing `<tl n>`.
- TS `Arrival.train_number` is optional `?` (§5): finalized pre-0.6.0
  archives permanently lack the key.
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
