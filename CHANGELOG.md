# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
