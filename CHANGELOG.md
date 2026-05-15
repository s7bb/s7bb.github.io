# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-05-15

### Added

- Schedule JSON moved to a dedicated single-writer repository
  `s7bb/s7bb-data`. The VM is its sole writer, so hourly data pushes no
  longer compete with Dependabot/PR merges on `main` for fast-forward —
  this removes the silent non-fast-forward push-rejection class that
  left the site serving stale data after `main` activity. The bot PAT
  is scoped to `s7bb/s7bb-data` only and cannot touch code.

### Changed

- Exporter SQL: `ORDER BY scheduled_time, train_id` (deterministic
  tie-break) — byte-stable hourly archive rewrites, smaller git deltas.
- Build workflow checks out both this repo and `s7bb/s7bb-data`;
  fallback rebuild cron shifted to `:10`.
- `docker-compose.yml`: new `s7bb-data-init` (profile `dev`) clones the
  data repo into a named volume; `s7bb-site-dev` mounts it read-only at
  `/repo/data`.
- This repo no longer tracks `data/`; it is gitignored locally.

## [0.4.5] - 2026-05-14

### Fixed

- Pusher now pushes pre-existing unpushed local commits even when no new
  data file changes were staged. Previously commits could accumulate
  locally for hours while logs reported success.
- `startup_sync` log message reflects whether `push_data` actually pushed.
  No more `action=push ... — pushed` when nothing was pushed.
- Hourly push failures now log at ERROR with a `PUSH_FAILED` prefix and a
  consecutive-failure counter, instead of being buried among generic
  `export_job step push failed` lines.

## [0.4.4] - 2026-05-11

### Fixed

- Parser no longer shifts `dp pt` / `dp ct` by +1 minute. The 0.4.2 shift was based on a wrong premise: DB Timetables `pt` is already the public planned departure time. Empirically (production DB, week of 2026-05-05 to 2026-05-10), raw `dp pt` matches the public S7 board, so the +1 shift made every `scheduled_time` and `actual_time` one minute too late. Reverts `_PUBLIC_OFFSET` in `parser.py` and the two parser tests that asserted the shift. The SQLite migration `scripts/migrate_shift_public_times.py` is removed — it never ran on production (`PRAGMA user_version = 0`), so historical rows are untouched and no rollback is needed. The Docker image no longer copies the `scripts/` directory.

## [0.4.3] - 2026-05-10

### Fixed

- Fetcher Docker image now ships the `scripts/` directory, so one-shot maintenance scripts (e.g. `python -m scripts.migrate_shift_public_times`) are runnable inside the container. Without this the 0.4.2 DB migration failed with `ModuleNotFoundError: No module named 'scripts'` when invoked via `docker compose run`.
- Fetcher Docker image now ships the `sqlite3` CLI alongside `git`, so ad-hoc DB inspection (e.g. `docker compose exec s7bb-fetcher sqlite3 /data/s7bb.db 'PRAGMA user_version;'`) works without falling back to a Python one-liner.
- `scripts/migrate_shift_public_times.py` now handles the post-double-write state in which the new fetcher already wrote public-time rows (`:00 / :20 / :40`) alongside the old internal-time rows (`:59 / :19 / :39`) for the same `train_id`. The naive shift collided on the `(train_id, scheduled_time)` UNIQUE index and aborted with `IntegrityError`. Migration now drops the old internal-time row whenever its shifted target already exists, leaves already-public rows untouched, and shifts lone old rows as before.

## [0.4.2] - 2026-05-10

### Fixed

- Parser now shifts DB Timetables internal departure timestamp by +1 minute so `scheduled_time` and `actual_time` reflect the public S7 board (`:00 / :20 / :40` instead of `:59 / :19 / :39`). Prior backfill of `latest.json` was being overwritten on every hourly export.
- Exporter no longer infers a 20-minute cadence grid between first/last observed train, eliminating the phantom "keine Daten" rows in the today view that appeared outside actual service hours and in operational gaps. Per-direction `missing` counter is consequently always `0`.
- One-shot `scripts/migrate_shift_public_times.py` corrects historical SQLite rows so they match the new public-time convention.

## [0.4.1] - 2026-05-10

### Fixed
- Heute view: scheduled times in the row list now display in the user's local time zone correctly. Previously the slot keys had their timezone suffix sliced off before being passed to `new Date()`, which JavaScript then interpreted as the *browser's* local time — shifting every shown time by the browser's UTC offset (e.g. an early-morning train at `00:19` Berlin appeared as `22:19` because the underlying UTC instant `2026-05-09T22:19+00:00` was re-parsed as local).

## [0.4.0] - 2026-05-10

### Added
- `s7bb-site-dev` service in `docker-compose.yml` (under the `dev` profile) runs the Vite dev server inside a container at <http://localhost:5173>. An entrypoint script copies `data/latest.json` into the container, shifts every time +1 minute (so the bundled pre-fix data file matches the new departure-time semantics), and exports `VITE_DEV_NOW` from the file's `generated_at` so the today-page filters treat the bundled data as live. Run with `docker compose --profile dev up s7bb-site-dev`.

### Changed
- Heute view now renders both directions side-by-side aligned by scheduled time. Each row shows the same time on a single line, with München on the left and Wolfratshausen on the right; gaps in one direction (e.g. an early-morning train that only runs toward Wolfratshausen) are rendered as an empty placeholder so the rest of the day stays aligned.

### Fixed
- Scheduled times now match the public S7 timetable (x:00, x:20, x:40) instead of being one minute earlier (x:19, x:39, x:59). The fetcher previously stored the planned arrival time at Baierbrunn; it now stores the planned departure time, which is what passengers see on the Bahn schedule. Delays are still computed against the same time, so values remain accurate.
- Heute view no longer shows "keine Daten" rows for non-operational hours or for stale data from a previous day. The expected-slot list is now constrained to the viewer's current Europe/Berlin date and to slots whose scheduled time has already passed.
- Today's aggregate now uses the Europe/Berlin local date, so trains running just before midnight or shortly after are bucketed into the correct day (previously the UTC date boundary mis-bucketed late-evening trains).

## [0.3.0] - 2026-05-08

### Added
- Today page footer now shows the expected time of the next data refresh ("Nächstes Update: HH:MM") next to the existing "Stand" timestamp.
- Startup preflight check in `s7bb-fetcher` validating volume permissions, git repo writability, "dubious ownership", SQLite integrity, and GitHub PAT/repo access. Hard failures abort startup; soft failures (e.g. GitHub reach) log a warning. New `s7bb-preflight` CLI runs the same checks on demand.
- Startup sync check in `s7bb-fetcher`: after preflight and before the scheduler runs, reconcile local `data/latest.json` with the copy on `origin/main`. Pushes the local file when its `generated_at` is newer (no need to wait up to an hour for the next hourly export); overwrites the local file with the remote bytes when remote is newer (handles VM rollback). Hard-fails startup on network, parse, or push errors.

### Changed
- Letzte-7-Tage view: Verspätung und Ausfälle in getrennte Diagramme aufgeteilt; Ø-Verspätung mit grünem Pünktlichkeitsband (0–6 min); kompakter KPI-Streifen pro Richtung; konsistente Farben für Richtung München (blau) und Wolfratshausen (lila).

## [0.2.0] - 2026-05-07

### Added
- Monthly archive JSON files at `data/archive/YYYY-MM.json` with full row history, daily aggregates, and per-direction breakdowns.
- `data/archive/index.json` summarising all available months.
- Site `Archiv` tab with 12-month bar chart, monthly detail view, and raw-data download.
- CLI flags `s7bb-export --archive-index` and `--refinalize`.

### Changed
- Hourly export job now writes `latest.json` plus current-month archive plus archive index, and pushes everything in one commit.
- Site nav reorganized into top-level `Live` / `Archiv` tabs.

### BREAKING CHANGE
- `pusher.push_latest` renamed to `push_data` and now stages `data/archive/*.json` in addition to `data/latest.json`.

### Security
- Replaced the SSH deploy key used for the hourly `data/latest.json` push with
  a fine-grained GitHub Personal Access Token over HTTPS. PAT scope is
  `Contents: Read and write` on a single repo; a server-side push ruleset on
  `main` further restricts allowed paths to `data/latest.json` and
  `data/archive/**`, blocks force-pushes, blocks branch deletion, and requires
  linear history. Previously the deploy key could write any file to any
  branch.
- Token is delivered to `git push` via a per-push `GIT_ASKPASS` helper script;
  it never appears in process arguments and never lands in `.git/config`.
- Bumped `vite` 5.2.11 → 6.4.2 in `site/` to close 12 Dependabot alerts
  covering `server.fs.deny` bypass / path-traversal variants
  (GHSA-4w7w-66w2-5vf9, GHSA-93m4-6634-74q7, GHSA-g4jq-h2w9-997c,
  GHSA-jqfw-vq24-v9c3, GHSA-859w-5945-r5v3, GHSA-356w-63v5-8wf4,
  GHSA-xcj6-pq6g-qj4x, GHSA-4r4m-qw57-chr8, GHSA-x574-m823-4x7w,
  GHSA-vg6x-rcgg-rjx6, GHSA-9cwx-2883-4wfx, GHSA-64vr-g452-qvp3) and one
  transitive `esbuild` dev-server CORS issue (GHSA-67mh-4wv8-2f99). The
  vulnerable code paths only run in `vite dev`; the deployed static site
  was never exposed.
- Bumped fetcher dependencies to address Dependabot alerts:
  - `lxml` 5.2.2 → 6.1.0 (GHSA-vfmq-68hx-4jfw — XXE via default `iterparse()`/`ETCompatXMLParser()` settings)
  - `requests` 2.32.3 → 2.33.1 (GHSA-9hjg-9r4m-mvj7 `.netrc` credential leak; GHSA-gc5v-m9x4-r6x2 insecure temp-file reuse in `extract_zipped_paths`)
  - `gitpython` 3.1.47 → 3.1.49
  - dev: `pytest` 8.2.2 → 9.0.3 (GHSA-6w46-j5rx-g56g — vulnerable tmpdir handling)
- Hardened DB Timetables XML parsing: `api.py` now uses an explicit
  `lxml.etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)`
  for all `fromstring` calls, defence-in-depth against malicious XML even
  though the upstream is a trusted DB API.

### Removed
- SSH deploy key push path. `SSH_DEPLOY_KEY_PATH` and `SSH_KNOWN_HOSTS_PATH`
  env vars, the host SSH-key bind mount in `docker-compose.yml`, and the
  `openssh-client` package in `fetcher/Dockerfile` are gone.

### Fixed
- Train filter previously read line from `<tl c=.. n=..>` (category + train run
  number, e.g. `S6765`) and never matched `S7`, so the parser dropped every
  arrival and the database stayed empty. Filter now reads the line attribute
  from `<ar l="S7">`, matching the real DB Timetables XML schema. Test fixture
  `plan.xml` updated to use `l="S7"` to reflect production data.

### Changed
- Direction classification simplified to two buckets matching the post-2024
  S7 timetable split (Wolfratshausen ↔ München Hbf Gl.27-36). The previous
  `MUENCHEN_TERMINI` set listed eastern-branch stations (Kreuzstraße, Aying,
  Höhenkirchen-Siegertsbrunn, Ebersberg, ...) that are no longer served by
  S7 since the line was split in 2024.

### Added
- `db-api/s7_baierbrunn_now.py` smoke script: fetches plan + full-changes for
  Baierbrunn and prints current S7 arrivals (scheduled, actual, delay,
  direction, platform, origin) to stdout. Useful for verifying API access and
  the parser's filter logic without touching the database.

### Changed
- Fetcher Docker image switched from `python:3.12-slim` + `pip install .` to
  the official `ghcr.io/astral-sh/uv` image with `uv sync`. When `uv.lock`
  is present in `fetcher/`, builds are reproducible via `uv sync --frozen`;
  without it, uv resolves at build time. Run `cd fetcher && uv lock` once
  and commit `uv.lock` to lock dependency versions for production builds.
- Added `fetcher/.dockerignore` to keep build context small and avoid
  shipping tests / virtualenvs into the image.

### Added
- Docker container for fetcher: single `s7bb-fetcher` service runs fetch and
  export+push on independent APScheduler cron schedules (`FETCH_CRON`,
  `EXPORT_CRON` env vars)
- `push-data.sh` logic migrated to Python (`pusher.py`); runs inside the
  container with SSH deploy key mounted as a volume
- `docker-compose.yml` with `s7bb-fetcher` (production) and `s7bb-dev`
  (serves `latest.json` on port 8080, activated via `--profile dev`)
- `.env.example` extended with `FETCH_CRON`, `EXPORT_CRON`,
  `SSH_DEPLOY_KEY_PATH`, git identity, and `UID`/`GID` variables
- HTML escaping for free-text fields (delay reason, direction) before they
  are rendered in the static site
- Optional `SSH_KNOWN_HOSTS_PATH` env var for pinning the GitHub host key
  inside the fetcher container

### Changed
- DB Timetables API timestamps are now correctly interpreted as
  `Europe/Berlin` local time and converted to UTC; previously stored as UTC
  directly, causing a 1–2 hour offset on every arrival
- Vite static site now respects `BASE_URL` so it deploys correctly to a
  GitHub Pages project subpath (`/s7bb/`) when `GITHUB_PAGES=1` is set
  during build
- SQLite database now opened in WAL mode with a 5-second busy timeout to
  avoid lock contention between the fetch and export jobs
- Charts are explicitly destroyed and recreated on re-render to prevent
  Chart.js memory leaks while navigating between pages
- `cancelled` is now a JSON boolean (was `0`/`1`) in `latest.json` and in
  the TypeScript `Arrival` interface
- Pinned all Python and npm dependency versions to exact pins per project
  policy (`==X.Y.Z` / no `^`)

### Security
- Fetcher git push uses `IdentitiesOnly=yes` and
  `StrictHostKeyChecking=accept-new` instead of disabling host-key
  verification; SSH key path is shell-quoted
- Fetcher commits now use the configured `GIT_AUTHOR_*` /
  `GIT_COMMITTER_*` env vars instead of falling back to whatever is in
  the container's git config

### Removed
- `fetcher/systemd/*` unit files and `fetcher/push-data.sh` (superseded by
  container-internal APScheduler and `pusher.py`)

### Fixed
- Train filter now matches only line `S7` (was accidentally accepting any
  S-Bahn line with `f="S"` due to a redundant double-check)
- `s7bb-fetch` now requests the timetable for the current Europe/Berlin
  hour rather than the current UTC hour
- Baierbrunn EVA station number corrected from `8004073` to `8000781`
  (the previous value caused the DB Timetables API to reject every
  `/plan` and `/fchg` request with HTTP 400). EVA is now sourced from the
  `S7BB_EVA` env var with the correct default; documentation and example
  env file updated to match

### Added
- Per-direction tracking: arrivals split into "Richtung München" and "Richtung Wolfratshausen" on all pages
- Heute page shows two columns (one per direction), stacking on narrow screens
- Statistik and Letzte 7 Tage pages show separate charts and aggregates per direction
- Missing-train detection: expected 20-minute schedule slots inferred from observed data; gaps shown with "keine Daten" badge
- New `direction_bucket` field (`muenchen` | `wolfratshausen` | `unknown`) on every arrival in `latest.json`
- New `aggregates.*.by_direction` block and `expected_slots.today` block in `latest.json` (backwards-compatible additions)
- Methodik page explains "keine Daten" badge
- Automatic SQLite migration adds `direction_bucket` column to existing databases on first run
- Initial project scaffold: Python fetcher, SQLite storage, Vite+TS static site
- DB Timetables API client (`api.py`) with plan and full-changes endpoints
- XML parser merging planned + actual timetable into `ArrivalRecord` dataclasses
- SQLite storage with upsert deduplication on `(train_id, scheduled_time)`
- JSON exporter producing `data/latest.json` (7-day window) and monthly archive dumps
- CLI entry points `s7bb-fetch` and `s7bb-export`
- systemd service + timer units for 5-minute fetch and hourly export
- `push-data.sh` script for committing and pushing `latest.json` from VM
- Vite + TypeScript static site with four pages: Heute, Letzte 7 Tage, Statistik, Methodik
- Chart.js charts: delay bar histogram, average delay line, on-time status pie
- GitHub Actions workflows: CI (lint + test) and gh-pages deployment
