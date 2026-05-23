# Spec: Export `terminus_health` into `latest.json`

**Issue:** [#52](https://github.com/s7bb/s7bb.github.io/issues/52)
**Date:** 2026-05-23
**Status:** Drafted

## Problem

The `terminus_health` table tracks `zero_match_streak` per terminus EVA. It
is written by `_record_health()` in `fetcher/src/s7bb_fetcher/terminus.py`
and surfaced the v0.7.0 production bug (fixed via PR #50 / v0.7.1). It is
currently invisible outside the VM — diagnosing a recurrence requires
SSH + `sqlite3 data/s7bb.db "SELECT * FROM terminus_health"`.

This means the next instance of the same bug class (EVA mismatch, schema
drift, `/fchg` shape change) is silent from outside the VM.

## Goal

Expose the `terminus_health` table in `data/latest.json` so any external
observer can read it via:

```bash
curl https://raw.githubusercontent.com/s7bb/s7bb-data/main/latest.json \
  | jq .terminus_health
```

## Non-goals

- UI rendering of health values on the site.
- Alerting / paging on streak thresholds.
- Surfacing health in monthly archives (`archive/YYYY-MM.json`).
- Backfilling missing rows for EVAs that have never been recorded.

## Design

### Source of truth

```sql
CREATE TABLE terminus_health (
    eva                TEXT PRIMARY KEY,
    zero_match_streak  INTEGER NOT NULL DEFAULT 0,
    updated_at         TEXT NOT NULL
);
```

(See `fetcher/src/s7bb_fetcher/storage.py:70-76`.)

### JSON shape

Add a top-level `terminus_health` key to the payload emitted by
`export_latest()` in `fetcher/src/s7bb_fetcher/exporter.py`:

```json
{
  "generated_at": "...",
  "station": "Baierbrunn",
  "line": "S7",
  "...": "...",
  "terminus_health": [
    {"eva": "8000261", "zero_match_streak": 0,  "updated_at": "2026-05-23T07:42:11+00:00"},
    {"eva": "8004158", "zero_match_streak": 12, "updated_at": "2026-05-23T07:42:11+00:00"}
  ]
}
```

Rules:

- Array of objects, one per row, ordered by `eva` ASC (stable diffs).
- Always present. Empty array `[]` when table is empty (fresh DB, pre-first
  fetch). Consumers must not have to distinguish missing-key vs. empty.
- Keys match column names exactly: `eva`, `zero_match_streak`, `updated_at`.
- `updated_at` is emitted as-is (already an ISO-8601 string in DB).

### Implementation site

Single function: `export_latest()` in
`fetcher/src/s7bb_fetcher/exporter.py:138-155`. Add the query + payload
key before the `_atomic_write_json()` call.

### Why `export_latest` only (not monthly archives)

`terminus_health` is point-in-time operational state, not historical
arrivals data. Repeating today's `zero_match_streak` snapshot in every
monthly archive would be misleading. Monthly archives stay arrivals-only.

## Acceptance

- `curl .../latest.json | jq '.terminus_health | type'` → `"array"`.
- Each entry has exactly the three keys `eva`, `zero_match_streak`,
  `updated_at`.
- Rows sorted by `eva` ascending.
- Empty table → key present, value `[]`.
- Unit test in `fetcher/tests/test_exporter.py` covers both populated and
  empty cases.

## Risk

- `latest.json` is ~public; `terminus_health` contains only an EVA
  number (already public reference data) and an integer streak. No PII,
  no auth-relevant data, no schedule perturbation. Safe to publish.
- Payload size delta is trivial (< 200 bytes for the realistic 2-EVA
  case).

## Release impact

- Semver: this is a `feat:` (new exported field), so MINOR bump on
  merge per CLAUDE.md "Post-merge release trigger".
- No site change; no migration; no operator action required beyond
  normal VM redeploy.
