# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: S7BB

Tracks Deutsche Bahn S7 S-Bahn schedule at Baierbrunn station (Munich) — on-time status, delays, cancellations. Target audience: non-technical Baierbrunn residents; UI labels are German, code/comments English.

## Architecture

Two repositories:

- **`s7bb/s7bb.github.io`** (this repo) — humans + Dependabot. Code,
  site, fetcher, workflows, docs. Does **not** track `data/`.
- **`s7bb/s7bb-data`** — VM bot, sole writer. Flat tree at the root:
  `latest.json`, `archive/*.json`, `archive/index.json`. Single-writer,
  so VM pushes never collide with Dependabot/PR merges.

```
DB Timetables API (XML)
  → Python fetcher → SQLite (/data/s7bb.db, VM-only)
                       ↓
                     /data/latest.json + /data/archive/*.json   (exporter)
                       ↓ (copy)
                     /repo/latest.json + /repo/archive/*.json   (s7bb-data clone)
                       ↓ (hourly push, HEAD:refs/heads/main)
                     GitHub: s7bb/s7bb-data main updated
                       ↓
                     Actions build-site.yml checks out this repo +
                     s7bb-data, assembles site/dist, deploys gh-pages.
```

### Key decisions (locked)
- Storage: **SQLite** (`data/s7bb.db` stays on VM, never committed)
- GitHub push: VM commits a flat `latest.json` + `archive/*.json` hourly
  to **`s7bb/s7bb-data`** `main` via a fine-grained GitHub PAT scoped to
  that single repository (`Contents: read/write`). The bot PAT has no
  access to this code repo. Generated site deployed by Actions, which
  also checks out `s7bb/s7bb-data`.
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

**Commits, versioning, changelog:** Follow `.claude/skills/release-hygiene/SKILL.md` — enforces Conventional Commits (types: `feat`, `fix`, `docs`, `chore`, `refactor`, `perf`, `test`, `style`, `revert`), Semantic Versioning, and Keep a Changelog. Project-specific extensions below override the skill where they conflict.

**Release:** bump version in `pyproject.toml` + sync `fetcher/uv.lock` (run `uv sync --no-dev` in `fetcher/`) + rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD` in `CHANGELOG.md` + commit `chore(release): X.Y.Z` + tag `vX.Y.Z` + push tag + create GitHub Release at <https://github.com/s7bb/s7bb.github.io/releases> with `gh release create vX.Y.Z --title "vX.Y.Z" --notes-file <(awk '/^## \[X.Y.Z\]/,/^## \[/' CHANGELOG.md | sed '$d')` (or `--notes-from-tag` if the tag was annotated). For the latest release, add `--latest`. The Releases page is the canonical user-visible changelog and must stay in sync with `CHANGELOG.md`.

**Post-merge release trigger:** After a PR with semver impact (any `feat`, `fix`, or breaking change) is merged into `main`, cut a release immediately: pull `main`, run the full Release procedure above (including the GitHub Release on the Releases page). PATCH for `fix`, MINOR for `feat`, MAJOR for `feat!` / `BREAKING CHANGE`. Pure `docs`/`chore`/`refactor`/`test`/`style` PRs do not trigger a release.

**Plan files:** Plans written to `docs/superpowers/plans/YYYY-MM-DD-*.md` (output of the brainstorming / writing-plans skills) are the durable record of intent + scope behind a change. Always commit them — bundle into the implementation PR, or follow up with a `docs:` PR if the implementation PR is already open. Never leave plan files untracked, do not delete them after execution, do not gitignore the directory.

