# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: S7BB

Tracks Deutsche Bahn S7 S-Bahn schedule at Baierbrunn station (Munich) - on-time status, delays, cancellations. Target audience: non-technical Baierbrunn residents; UI labels are German, code/comments English.

## Architecture

Two repositories:

- **`s7bb/s7bb.github.io`** (this repo) - humans + Dependabot. Code,
  site, fetcher, workflows, docs. Does **not** track `data/`.
- **`s7bb/s7bb-data`** - VM bot, sole writer. Flat tree at the root:
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
                       ↓ (push → s7bb-data/.github/workflows/dispatch-build.yml)
                       ↓ (workflow_dispatch API, DISPATCH_TOKEN, Actions:write)
                     Actions build-site.yml (event: workflow_dispatch)
                     checks out this repo + s7bb-data, assembles
                     site/dist, deploys gh-pages. No schedule cron.
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
- **Station EVA lookups: always consult [`docs/s7-station-evas.md`](docs/s7-station-evas.md) first** - canonical table of every S7 station's EVA, DS100 code, and route position. Only hit the live `/station/{name}` endpoint when a name is missing from the doc, and append the resolved row back into the doc in the same PR. Conserves DB Timetables quota and keeps spec / code / docs in sync on one source of truth.
- Fetch cadence: every 5 min (systemd timer)
- Chart library: Chart.js v4
- Site deploy is **event-driven, not scheduled**. GitHub `schedule:`
  cron is best-effort and was silently dropped under load, so it is
  removed. A `push`-triggered workflow in `s7bb/s7bb-data`
  (`dispatch-build.yml`) calls the `workflow_dispatch` API of this repo.
  Its token (`DISPATCH_TOKEN`, Actions secret in **s7bb-data**, not on
  the VM) is a fine-grained PAT scoped to `s7bb.github.io` with
  `Actions: write` only - it cannot modify code, preserving the
  "bot PAT has no access to this code repo" boundary. Renew the PAT
  before its 90-day expiry; an expired token silently stops deploys
  (visible as failed dispatch runs in the s7bb-data Actions tab).

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

1. Clone **this code repo** over HTTPS. The s7bb-data working tree at
   `/repo` is auto-provisioned by the `s7bb-repo-init` compose service
   (gitignored host bind mount `./data-repo`) - do not clone it by hand.
2. Copy `.env.example` → `.env`, fill in API credentials, `GITHUB_PAT` (see README §5), UID/GID.
3. `docker compose up -d s7bb-fetcher` - `s7bb-repo-init` clones/refreshes
   `s7bb/s7bb-data` first, then APScheduler runs fetch+export+push.

## GitHub Pages Setup

1. Repo Settings → Pages → Source: GitHub Actions.
2. No secrets needed for deployment (OIDC via `id-token: write`).
3. `DB_API_KEY` / `DB_CLIENT_ID` are never needed in CI - fetching runs only on VM.

## Key constraints

**Punctuation:** do not use "—" (em-dash) anywhere in UI text, documentation, code comments, or commit messages. Use a plain hyphen "-" instead.

**Dependency pinning:** all deps use `=X.Y.Z` exact versions. Match this style when adding deps.

**Commits, versioning, changelog:** Follow `.claude/skills/release-hygiene/SKILL.md` - enforces Conventional Commits (types: `feat`, `fix`, `docs`, `chore`, `refactor`, `perf`, `test`, `style`, `revert`), Semantic Versioning, and Keep a Changelog. Project-specific extensions below override the skill where they conflict.

**Release:** bump version in `pyproject.toml` + sync `fetcher/uv.lock` (run `uv sync --no-dev` in `fetcher/`) + rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD` in `CHANGELOG.md` + commit `chore(release): X.Y.Z` + tag `vX.Y.Z` + push tag + create GitHub Release at <https://github.com/s7bb/s7bb.github.io/releases> with `gh release create vX.Y.Z --title "vX.Y.Z" --notes-file <(awk '/^## \[X.Y.Z\]/,/^## \[/' CHANGELOG.md | sed '$d')` (or `--notes-from-tag` if the tag was annotated). For the latest release, add `--latest`. The Releases page is the canonical user-visible changelog and must stay in sync with `CHANGELOG.md`.

**Post-merge release trigger:** After a PR with semver impact (any `feat`, `fix`, or breaking change) is merged into `main`, cut a release immediately: pull `main`, run the full Release procedure above (including the GitHub Release on the Releases page). PATCH for `fix`, MINOR for `feat`, MAJOR for `feat!` / `BREAKING CHANGE`. Pure `docs`/`chore`/`refactor`/`test`/`style` PRs do not trigger a release.

**Plan files:** Plans written to `docs/superpowers/plans/YYYY-MM-DD-*.md` (output of the brainstorming / writing-plans skills) are the durable record of intent + scope behind a change. Always commit them - bundle into the implementation PR, or follow up with a `docs:` PR if the implementation PR is already open. Never leave plan files untracked, do not delete them after execution, do not gitignore the directory.

