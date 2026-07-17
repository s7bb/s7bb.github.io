# Local Docker hosting - design

Date: 2026-07-17
Status: approved, phase 1 of 2
Scope: this spec covers phase 1 (remote mode) only. Phase 2 (local fetcher mode) is deferred to its own spec.

## Problem

The public site at s7bb.github.io is gone: Pages is unpublished and `build-site.yml`
is disabled. Users who want S7BB data have nowhere to get it. We want them to build
and run the site locally in Docker.

Data can reach the site two ways:

1. **remote** - read the JSON published at `github.com/s7bb/s7bb-data`
2. **fetcher** - run a local fetcher instance against the DB Timetables API

Both must be configurable, in the site and in `docker-compose.yml`.

## Decisions

| Question | Answer |
|---|---|
| Audience | Each viewer runs their own container, views at `localhost`. Technical users. |
| Default mode | `remote` - zero credentials, full history, works on first `up` |
| Freshness | Current on every page load. No build-time bake, so the container never goes stale. No auto-refresh timer: a tab left open does not update until reloaded. |
| Config surface | Site reads a data-source base URL; `.env` sets it |
| Config timing | Runtime (`config.json` written at container start), not baked at build |
| Phase 1 | Remote mode only |
| Phase 2 | Local fetcher mode + history seeding |

### Audience note

CLAUDE.md states the target audience is non-technical Baierbrunn residents. That
holds for the *site UI*, which stays German and stays simple. It no longer holds for
*distribution*: `docker compose up` is a technical act, so the reachable audience is
now much smaller than the public site's. This is a known and accepted consequence of
taking the site down. CLAUDE.md should be updated to say so.

## Architecture

### remote mode (default, phase 1)

```
browser → https://raw.githubusercontent.com/s7bb/s7bb-data/main/latest.json
          (and /archive/index.json, /archive/YYYY-MM.json)
             ↑
site container (nginx) serves only the built assets + config.json
```

One container. No `/data` volume, no fetcher, no repo clone, no credentials. Data is
current on each page load because the browser fetches it live.

`main.ts:34-37` memoizes `liveData` for the page session and there is no timer
anywhere, so an open tab does not refresh on its own. That is accepted for phase 1: the
site is a thing you open, read, and close. Correcting a build-time bake was the point;
a refresh timer is not required to achieve it and is not implemented.

### fetcher mode (phase 2, designed for now, not built)

```
DB API → s7bb-fetcher (5-min cron) → SQLite → exporter → ./data/{latest.json,archive/*.json}
                                                            ↓ (bind mount, read-only)
browser → site container (nginx) → /data/latest.json
```

No git repo, no PAT, no push. Refreshes on the fetcher's existing hourly export cron.

## Verified facts

These were checked against the live system and the code, not assumed.

- **CORS allows it.** `raw.githubusercontent.com` returns `access-control-allow-origin: *`
  on `s7bb-data/main/latest.json`, so a browser at `localhost` can fetch it directly.
  `cache-control: max-age=300` (5 min) is harmless for hourly data. `content-type:
  text/plain` does not matter; `fetch().json()` ignores it.
- **URL layouts already line up.** The site wants `<base>/latest.json`,
  `<base>/archive/index.json`, `<base>/archive/<period>.json`. The s7bb-data root is
  flat: `latest.json`, `archive/*.json`, `archive/index.json`. One base URL swaps
  between local and remote with no path translation.
- **Routing is hash-based** (`main.ts:19-20`, `#/archiv/2026-05`), so nginx needs no
  SPA `try_files` fallback. Every route is one `index.html`.
- **Load failures already surface.** `main.ts:67-69` catches and renders
  `Fehler beim Laden der Daten. Bitte später nochmal versuchen.`
- **`.nvmrc` is 22**, so `node:22-alpine` matches the CI build.
- **The runtime is nerdctl, and its compose profile support is not Docker's.** The VM
  runs rootless nerdctl: `docker-compose.yml:40` sets `user: "0:0"` precisely because
  "in rootless nerdctl this maps to the host invoking user", and that ownership model
  is load-bearing across earlier specs. Measured against nerdctl 2.3.3 / compose
  v2.3.3:

  | Mechanism | nerdctl behavior |
  |---|---|
  | `--profile <name>` flag | works, filters correctly |
  | `COMPOSE_PROFILES` env var | **silently ignored**; profiled services never start |
  | naming a profiled service (`compose up svc`) | **fails**: `no such service: svc` |

  Docker enables a service's profile when you name it explicitly. nerdctl does not.
  This kills two designs outright: `COMPOSE_PROFILES=remote` in `.env` would never
  start the site, and adding `profiles: [fetcher]` to `s7bb-fetcher` would make the
  VM's `up -d s7bb-fetcher` fail with `no such service`, silently killing production on
  the next redeploy. The repo's existing idiom (`--profile dev`, README:242) is the
  flag, which is the nerdctl-compatible form.

## Components

### 1. `site/src/config.ts` (new)

Exports `dataBase(): Promise<string>`. One cached promise, following the existing
`_indexCache` idiom in `archive.ts:36`.

Resolution order:

1. fetch `${import.meta.env.BASE_URL}config.json`; if it parses and has a non-empty
   string `dataBaseUrl`, use it
2. else `import.meta.env.VITE_DATA_BASE_URL`
3. else current behavior: `import.meta.env.DEV ? "../data" : \`${import.meta.env.BASE_URL}data\``

Step 3 preserves today's behavior exactly, so `npm run dev` and the existing
`s7bb-site-dev` compose profile keep working untouched. A missing `config.json` in dev
is the normal case and MUST fall through silently - no `console.error`.

### 2. Refactor three call sites

Each currently carries its own copy of the same `DEV ? "../data" : BASE_URL+"data"`
branch:

- `site/src/data.ts:55-57`
- `site/src/archive.ts:39-43` (`archiveBase()`)
- `site/src/pages/archive-detail.ts:11-13`

All three become `await dataBase()`. All three are already inside async functions, so
the change is contained.

### 3. `site/Dockerfile` (new)

Multi-stage:

```
node:22-alpine  → npm ci → npm run build → dist/
nginx:alpine    → dist/ + docker-entrypoint.sh + nginx.conf
```

### 3b. `site/.dockerignore` (new)

Must exclude `node_modules/`, `dist/`, and `data/`. Without it the build context
includes a multi-hundred-MB `node_modules`, making every build slow for no reason.

### 4. `site/docker-entrypoint.sh` (new)

At container start, writes `/usr/share/nginx/html/config.json` from
`S7BB_DATA_BASE_URL`.

Requirements:

- **JSON-escape via `jq -n --arg`**, never `printf`. A URL containing a quote would
  otherwise produce invalid JSON, and the site would silently fall back to step 2/3 -
  the exact quiet wrong-mode failure this design exists to avoid.
- **Validate and fail fast** on unset or empty `S7BB_DATA_BASE_URL`.
- **Warn loudly** when the base is `/data` and `/usr/share/nginx/html/data/latest.json`
  is absent - the fetcher-not-running case.

### 5. `site/nginx.conf` (new)

- serve `/usr/share/nginx/html`
- `location = /config.json` → `Cache-Control: no-store`. Without this a browser caches
  the old config and `docker compose restart` appears to do nothing, reintroducing the
  stale-config trap by the back door.
- no SPA fallback needed (hash routing)

### 6. `docker-compose.yml`

Local hosting gets **its own compose file**, `compose.local.yml`, containing only the
site. `docker-compose.yml` is not touched at all.

```yaml
# compose.local.yml
services:
  s7bb-site:
    build:
      context: site
    restart: unless-stopped
    ports:
      - "8080:80"
    environment:
      S7BB_DATA_BASE_URL: ${S7BB_DATA_BASE_URL:-https://raw.githubusercontent.com/s7bb/s7bb-data/main}
    volumes:
      - ./data:/usr/share/nginx/html/data:ro
```

```bash
docker compose  -f compose.local.yml up -d --build     # Docker
nerdctl compose -f compose.local.yml up -d --build     # nerdctl
```

**Why a separate file rather than profiles.** Two things force it:

1. `s7bb-repo-init` and `s7bb-fetcher` have no `profiles:` key, and a Compose service
   without one is *always* started. So `docker compose up -d` starts the production,
   push-enabled fetcher: with a real `GITHUB_PAT` that is a second writer to s7bb-data,
   breaking the single-writer invariant; with placeholder credentials it is a
   `restart: unless-stopped` crash loop. Putting a profile on the site does not change
   that - it gates the site, not the fetcher.
2. Profiling the production services *would* fix it under Docker, but the runtime here
   is nerdctl, which ignores `COMPOSE_PROFILES` and refuses to start a profiled service
   by name (see Verified facts). It would leave the VM unable to start its fetcher.

A separate file sidesteps profile semantics entirely: the production services are not
in it, so no invocation of it can start them, under either runtime. It also needs no
`.env` - `S7BB_DATA_BASE_URL` has a built-in default - so local hosting requires zero
configuration.

| Command | Starts |
|---|---|
| `compose -f compose.local.yml up -d --build` | site only, both runtimes |
| `docker compose up -d` (production file) | unchanged, pre-existing trap, not made worse |
| `docker compose up -d s7bb-fetcher` (VM) | unchanged |

The pre-existing trap in `docker-compose.yml` is deliberately left alone: fixing it
needs the profile change that nerdctl cannot support, so it wants its own change with
VM verification.

Two further notes:

- **The `./data` mount is unconditional.** Harmless and unused in remote mode, and it
  means phase 2 needs no change to this service definition. On a fresh clone `./data`
  does not exist; the runtime creates an empty directory for the bind mount. That is
  acceptable (`/data/` is gitignored), but the plan should verify it does not produce a
  root-owned directory that later blocks the phase 2 fetcher from writing.
- **Port 8080 is also used by `s7bb-dev`** (`8080:8080`, `dev` profile). They live in
  different compose files and never start together unless someone runs both. Do not run
  the `dev` profile and local hosting at once.

Nothing in `docker-compose.yml` changes: not the production services, not the `dev`
profile services.

### 7. `.env.example`

Local hosting needs **no `.env`**: `S7BB_DATA_BASE_URL` defaults to the s7bb-data raw
URL inside `compose.local.yml`. Add only a short commented block documenting the
override, so the knob is discoverable without implying it is required:

```
# --- Local hosting (compose.local.yml) ---
# Optional. Defaults to the published s7bb-data URL; only set this to point
# the site somewhere else.
# S7BB_DATA_BASE_URL=https://raw.githubusercontent.com/s7bb/s7bb-data/main
#
# Phase 2 (own fetcher, serving ./data): S7BB_DATA_BASE_URL=/data
```

No `COMPOSE_PROFILES`. It would be inert under nerdctl and misleading under Docker, and
the separate compose file makes it unnecessary. This also removes the earlier design's
one wart: there are no longer two settings that must agree.

## Error handling

| Failure | Behavior |
|---|---|
| Base is `/data`, no fetcher running | Generic German error in UI; entrypoint logs a loud startup warning |
| Remote mode, no internet | Generic German error in UI. Honest and visible. |
| Malformed `config.json` | Falls through to step 2/3; entrypoint validates with `jq` and fails fast before writing |
| `S7BB_DATA_BASE_URL` unset/empty | Entrypoint fails fast at startup |

No in-site diagnostic UI and no new error strings. The existing generic message plus a
loud container log is proportionate for an audience that just ran `docker compose up`.

## Testing

| Layer | Test |
|---|---|
| Unit (vitest) | `dataBase()` precedence: config.json wins → VITE var → default |
| Unit (vitest) | Malformed / empty `config.json` falls through without throwing |
| Unit (vitest) | Missing `config.json` in dev is silent (no `console.error`) |
| Unit (shell) | Entrypoint JSON-escapes a URL containing a quote |
| Unit (shell) | Entrypoint fails fast on empty `S7BB_DATA_BASE_URL` |
| Smoke (manual) | `docker compose up -d` → curl `/config.json` and `/index.html`; load in browser; confirm data renders from GitHub |
| CI | Add the site image build to the existing `docker` job so the Dockerfile cannot rot |

## Out of scope

Deferred to the phase 2 spec:

- `S7BB_PUSH_ENABLED=0` in the fetcher: skip `startup_sync` (`service.py:179-183`),
  skip stage+push (`service.py:149-150`), make the `repo_writable` / `repo_ownership` /
  `repo_identity` HARD preflight checks conditional (`preflight.py:60-128`)
- `s7bb-seed` CLI to import history

### Why seeding is not a file copy (recorded for phase 2)

`_export_job` (`service.py:118-150`) regenerates `latest.json` **and the current
month's archive** from SQLite every hour. Past months are only rewritten on the 1st at
00:00. So copying s7bb-data's JSON into `./data` is quietly half-broken: seeded past
months survive and appear in the index, but `latest.json` and the current month are
clobbered within the hour and revert to sparse local data - with no error anywhere.

Seeding must therefore write **SQLite**, not JSON. This is feasible: the export SELECT
(`exporter.py:59-71`) covers 17 columns, and the archive JSON carries full `arrivals[]`.
It omits only `fetched_at`, `dp_ppth`, and the retired `reason`; none affect rendering
(`dp_ppth` is only needed at parse time to derive `direction_bucket`, which is
exported). An importer upserts via the existing `ON CONFLICT(train_id, scheduled_time)`,
synthesizing `fetched_at`, leaving `dp_ppth` NULL, un-nesting the `disruption` object
built by `_attach_disruption`, and coercing `cancelled` back to int.

Also note: without seeding, fetcher mode starts from an empty DB - `latest.json` has
only data since first start, the archive is empty until a month rolls over, and week
charts are blank for 7 days. The two modes are not data-equivalent.

## Docs to update

- README: new "Lokal mit Docker betreiben" section
- CHANGELOG: entry under `[Unreleased]`
- CLAUDE.md: architecture note for local hosting; audience note (see above)

## Known unrelated defect

`.env.example` still says "See README §5 for the rotation flow", but PR #78 renumbered
that section to §4. This is a stale pointer introduced by that PR; fix it in a separate
commit, not as part of this feature.
