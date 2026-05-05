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

### Changed
- Systemd timers superseded by container-internal APScheduler; existing units
  in `fetcher/systemd/` are retained for reference

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
