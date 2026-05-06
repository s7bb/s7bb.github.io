# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: S7BB

Tracks Deutsche Bahn S7 S-Bahn schedule at Baierbrunn station (Munich) — on-time status, delays, cancellations. Target audience: non-technical Baierbrunn residents; UI labels are German, code/comments English.

## Architecture

```
DB Timetables API (XML) → Python fetcher → SQLite (data/s7bb.db)
                                                    ↓
                                          hourly: s7bb-export → data/latest.json → git push
                                                                                         ↓
                                                                               GitHub Actions
                                                                               Vite build → gh-pages
```

- **`fetcher/`** — Python package (`s7bb_fetcher`). Entry points: `s7bb-fetch` (5 min cron) and `s7bb-export` (hourly).
- **`site/`** — Vanilla TypeScript + Vite + Chart.js static site. Reads `data/latest.json` at runtime.
- **`data/`** — `latest.json` (7-day window, committed hourly by VM), `archive/YYYY-MM.json` (monthly dumps).
- **`.github/workflows/`** — `ci.yml` (lint+test on PR), `build-site.yml` (deploy to gh-pages on push to `data/**`).

### Key decisions (locked)
- Storage: **SQLite** (`data/s7bb.db` stays on VM, never committed)
- GitHub push: VM commits `data/latest.json` hourly via fine-grained GitHub PAT over HTTPS, server-side restricted by a `main`-branch ruleset to `data/latest.json` and `data/archive/**`; generated site deployed by Actions
- DB API: `apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1`, auth via `DB-Api-Key` header
- Baierbrunn EVA number: `8000781` (overridable via `S7BB_EVA` env var)
- Fetch cadence: every 5 min (systemd timer)
- Chart library: Chart.js v4

## Commands

### Fetcher (Python)

```bash
cd fetcher
uv sync --group dev          # install deps including dev
export DB_API_KEY=...
export DB_CLIENT_ID=...
uv run s7bb-fetch            # single fetch → data/s7bb.db
uv run s7bb-export           # write data/latest.json
uv run pytest                # run tests
uv run ruff check src tests  # lint
uv run pytest tests/test_parser.py  # single test file
```

### Site (TypeScript)

```bash
cd site
npm install
npm run dev      # Vite dev server (reads ../data/latest.json)
npm run build    # type-check + Vite build → dist/
npm run preview  # serve dist/ locally
npm run lint     # eslint
```

## Data Flow Details

- `api.py`: HTTP client for DB Timetables. `fetch_plan(eva, YYMMDD, HH)` → plan XML; `fetch_full_changes(eva)` → changes XML.
- `parser.py`: Merges plan + changes XML into `ArrivalRecord` dataclasses. DB times are in local DE time (format `YYMMDDHHMM`).
- `storage.py`: Upserts records into SQLite `arrivals` table. `ON CONFLICT(train_id, scheduled_time)` deduplicates re-fetches.
- `exporter.py`: Queries last N days, builds `latest.json` with `arrivals[]` + `aggregates.today` + `aggregates.last_7_days`.

## VM Setup (production)

1. Clone repo over HTTPS.
2. Copy `.env.example` → `.env`, fill in API credentials, `GITHUB_PAT` (see README §5), UID/GID.
3. `docker compose up -d s7bb-fetcher` — APScheduler runs fetch+export+push inside container.

## GitHub Pages Setup

1. Repo Settings → Pages → Source: GitHub Actions.
2. No secrets needed for deployment (OIDC via `id-token: write`).
3. `DB_API_KEY` / `DB_CLIENT_ID` are never needed in CI — fetching runs only on VM.

## Key constraints

**Dependency pinning:** all deps use `=X.Y.Z` exact versions. Match this style when adding deps.

**Versioning:** [Semantic Versioning](https://semver.org) — `MAJOR.MINOR.PATCH`. Breaking API/data-schema changes bump MAJOR; new features bump MINOR; bug fixes bump PATCH.

**Commit format:** [Conventional Commits](https://www.conventionalcommits.org) required. Allowed types: `feat`, `fix`, `docs`, `chore`, `refactor`, `perf`, `test`, `style`, `revert`. Breaking changes: append `!` and add `BREAKING CHANGE:` footer.

**Changelog:** [Keep a Changelog](https://keepachangelog.com) format. Every user-facing change goes in `CHANGELOG.md` under `[Unreleased]` before merging. Sections: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`. Entries describe user-visible effect, not code paths.

**Release:** bump version in `pyproject.toml` + rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD` in `CHANGELOG.md` + commit `chore(release): X.Y.Z` + tag `vX.Y.Z`.

