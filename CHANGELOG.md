# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
