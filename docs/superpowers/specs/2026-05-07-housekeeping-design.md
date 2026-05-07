# Housekeeping & Archive Design

**Date:** 2026-05-07
**Status:** Draft — pending review

## Goal

Add long-term data preservation and historical browsing to S7BB. Current state: `data/latest.json` carries a rolling 7-day window; older arrivals live only in the VM-local SQLite DB. There is no scheduled archive, no on-site history view, and the pusher commits only `latest.json`.

Target: keep raw rows forever (for audit/download) and surface historical aggregates on the website (for non-technical Baierbrunn residents).

## Decisions

| # | Topic | Decision |
|---|---|---|
| 1 | Archive purpose | Both raw preservation **and** site-facing stats |
| 2 | File granularity | Monthly flat files, `data/archive/YYYY-MM.json` |
| 3 | Write cadence | Rolling rewrite of current month every hour; finalize previous month on day 1 of next month |
| 4 | `latest.json` window | Unchanged: 7-day rolling. Overlaps with the current and (early in a month) previous-month archive — duplication is intentional, archive is the long-term source, `latest.json` keeps the live view fast. |
| 5 | Archive content | Full rows + monthly aggregates + daily aggregates + by-direction daily |
| 6 | Discovery | `data/archive/index.json` lists available months with summary stats |
| 7 | Site UX | Combined: 12-month strip on main page (from index) + dedicated `Archiv` tab for monthly detail |
| 8 | Push policy | Single hourly commit covering `data/latest.json` + `data/archive/**` |
| 9 | DB retention | Keep forever on VM, no prune |

## Architecture

```
DB Timetables API
       │
       ▼  every 5 min
  s7bb-fetch  →  data/s7bb.db        (VM only, kept forever)
       │
       ▼  every hour
  s7bb-export
       ├─→  data/latest.json              (rolling 7 days)
       ├─→  data/archive/YYYY-MM.json     (current month, rolling rewrite)
       └─→  data/archive/index.json       (month list + per-month summary)
       │
       ▼  push (single commit, all changed files)
  origin/main  →  GitHub Actions  →  gh-pages
       │
       ▼
  site reads:
    - data/latest.json          (always)
    - data/archive/index.json   (on load → 12-month strip)
    - data/archive/YYYY-MM.json (lazy, on Archiv tab navigation)
```

## Components

### `fetcher/src/s7bb_fetcher/exporter.py`

- `export_latest(conn, out_path, window_days=7)` — unchanged.
- `export_monthly_archive(conn, year, month, out_path)` — extend to add `aggregates.by_direction`, `daily[]`, `daily_by_direction[]`, `finalized` flag.
- New `export_archive_index(conn, archive_dir, index_path)` — scans archive dir, builds index JSON with per-month summary including `by_direction`. Includes finalized months and current (un-finalized) month.

### `fetcher/src/s7bb_fetcher/service.py`

`_export_job` (hourly) sequence:

All time comparisons use UTC (`datetime.now(UTC)`) to match the rest of the codebase.

1. `export_latest()` → `data/latest.json`.
2. `export_monthly_archive(now.year, now.month)` → `data/archive/YYYY-MM.json` with `finalized=false`. This rewrites the current month every hour, capturing late corrections from the DB API.
3. If `now.day == 1` AND `now.hour == 0` (UTC): additionally call `export_monthly_archive(prev_year, prev_month)` with `finalized=true` to freeze the just-completed month. This is the **only** path that writes the previous month — at hour 1 onward, `now.month` is already the new month, so step 2 targets the new file and the finalized previous-month archive is left untouched.
4. `export_archive_index()` → `data/archive/index.json`.
5. `push_data()` — single commit if any diff.

Each step wrapped in try/except — failures logged, subsequent steps still run.

### `fetcher/src/s7bb_fetcher/pusher.py`

- Rename `push_latest` → `push_data(repo_path)`.
- Stages `data/latest.json` and all `data/archive/*.json`.
- Single commit `chore: update data {ts}`. Skip if no diff.
- GitHub branch ruleset already permits `data/latest.json` and `data/archive/**`.

### `fetcher/src/s7bb_fetcher/cli.py`

- `s7bb-export --archive YYYY-MM` — unchanged (manual archive build).
- New `s7bb-export --archive-index` — regenerate `index.json` only.
- New `--refinalize` flag for `--archive YYYY-MM` to overwrite a frozen archive when late corrections require it.

### `site/`

- New `site/src/archive.ts` — fetch helpers `loadIndex()`, `loadMonth(yyyymm)`. Cache responses for session.
- Main page: append "12-Monats-Übersicht" section after week stats. Stacked bar chart from `index.json` (one bar per month: on_time/late/cancelled). Click → navigate to `#/archiv/YYYY-MM`.
- New view `site/src/archive-detail.ts`: renders month detail — daily on-time line chart with two series (muenchen, wolfratshausen), arrival table, raw JSON download link.
- Hash router (`#/`, `#/archiv`, `#/archiv/YYYY-MM`).
- Top nav: small tabs `Live` / `Archiv`.

## Data Flow & Schemas

### `data/archive/YYYY-MM.json`

```json
{
  "generated_at": "2026-05-07T07:00:00+00:00",
  "station": "Baierbrunn",
  "line": "S7",
  "period": "2026-05",
  "finalized": false,
  "arrivals": [ /* full ArrivalRecord rows for that month */ ],
  "aggregates": {
    "total": 1234,
    "on_time": 1100,
    "late": 120,
    "cancelled": 14,
    "avg_delay_min": 1.2,
    "by_direction": {
      "muenchen":       { "total": 617, "on_time": 550, "late": 60, "cancelled": 7, "avg_delay_min": 1.3 },
      "wolfratshausen": { "total": 617, "on_time": 550, "late": 60, "cancelled": 7, "avg_delay_min": 1.1 }
    }
  },
  "daily": [
    { "date": "2026-05-01", "total": 84, "on_time": 78, "late": 5, "cancelled": 1, "avg_delay_min": 0.8 }
  ],
  "daily_by_direction": {
    "muenchen":       [ { "date": "2026-05-01", "total": 42, "on_time": 39, "late": 3, "cancelled": 0, "avg_delay_min": 0.9 } ],
    "wolfratshausen": [ { "date": "2026-05-01", "total": 42, "on_time": 39, "late": 2, "cancelled": 1, "avg_delay_min": 0.7 } ]
  }
}
```

`finalized=true` is set when the file is written for a fully completed month (day 1 of the following month, hour 0). Once finalized, the archive is not rewritten by the hourly job — only by an explicit `--refinalize`.

### `data/archive/index.json`

```json
{
  "generated_at": "2026-05-07T07:00:00+00:00",
  "station": "Baierbrunn",
  "months": [
    {
      "period": "2026-05",
      "finalized": false,
      "total": 1234, "on_time": 1100, "late": 120, "cancelled": 14, "avg_delay_min": 1.2,
      "by_direction": {
        "muenchen":       { "total": 617, "on_time": 550, "late": 60, "cancelled": 7, "avg_delay_min": 1.3 },
        "wolfratshausen": { "total": 617, "on_time": 550, "late": 60, "cancelled": 7, "avg_delay_min": 1.1 }
      }
    }
  ]
}
```

Months listed in chronological order. Index includes finalized months and the current (rolling) month. Months absent from disk are absent from the index — the site renders gaps gracefully.

## Error Handling

- **Independent steps:** every stage in `_export_job` is wrapped in try/except. A failure in archive build does not block `latest.json` push.
- **Atomic writes:** archive and index files written to a temp path then `os.replace`'d to avoid half-written files on crash.
- **Push failure:** existing behavior — exception propagates, APScheduler retries next hour. DB on VM remains the source of truth.
- **Late corrections past finalization:** DB-API may emit changes for arrivals more than a month old. These land in the SQLite DB but not in finalized archives. Manual recovery via `s7bb-export --archive YYYY-MM --refinalize`.
- **Missing months (VM down):** index simply skips missing months; site charts render the gap.
- **Index regen failure:** non-fatal, retried hourly.
- **Site fetch errors:** display "Archivdaten nicht verfügbar" and fall back to live (`latest.json`-only) view.

## Testing

### Fetcher (`pytest`)

- `test_exporter.py`:
  - `test_monthly_archive_includes_daily_aggregates`
  - `test_monthly_archive_includes_by_direction`
  - `test_archive_index_summarizes_all_months`
  - `test_finalized_flag_set_on_month_boundary`
  - `test_atomic_write_replaces_existing_archive`
- `test_pusher.py`:
  - `test_push_data_stages_archive_files`
  - `test_push_data_skips_when_no_diff`
  - `test_push_data_single_commit_for_combined_changes`
- `test_service.py`:
  - `test_export_job_runs_all_archive_steps`
  - `test_export_job_finalizes_prev_month_on_day_one`
  - `test_export_job_continues_after_archive_failure`

Use `freezegun` for date-dependent tests.

### Site

- `archive.test.ts` — index parsing and month-load helpers.
- Manual smoke test against fixture archive files via `npm run dev`.

## Out of Scope

- DB pruning / retention policy on VM (decision: keep forever).
- Yearly archive rollups.
- Server-side archive query API (gh-pages is static; site fetches files directly).
- Long-term data integrity verification (checksums) — relies on git history.

## Open Questions

None at design freeze. Implementation plan to be created via the `writing-plans` skill once this spec is approved.
