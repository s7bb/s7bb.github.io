# S7BB - S7 Baierbrunn Pünktlichkeit

Tracks on-time performance of the Deutsche Bahn S7 S-Bahn line at Baierbrunn station (Munich). Shows live delays, cancellations, and weekly statistics. Published as a static site on GitHub Pages, updated hourly.

**Site:** https://s7bb.github.io

---

## How it works

```
DB Timetables API (XML)
        │
        ▼  every 5 min (APScheduler in container)
  s7bb-fetch  →  data/s7bb.db  (SQLite, stays on VM)
        │
        ▼  every hour (APScheduler in container)
  s7bb-export → data/latest.json → git push
        │
        ▼  GitHub Actions (hourly cron :10, picks up VM's :00 push)
  Vite build  →  GitHub Pages
```

The fetcher runs in a Docker container on a small VM and pushes the schedule JSON hourly to `s7bb/s7bb-data`. GitHub Actions rebuilds and deploys the static site on an hourly schedule (and on site-code changes).

---

## Deutsche Bahn API

S7BB uses the **DB Timetables API** from the DB API Marketplace.

### Register for an API key

1. Go to **[developers.deutschebahn.com](https://developers.deutschebahn.com)** and create a free account.
2. Navigate to **API Marketplace → Timetables** and subscribe to the API (free tier is sufficient).
3. After subscribing, open your application in the portal. You will find two credentials:
   - **Client ID** (`DB-Client-Id`)
   - **API Key** (`DB-Api-Key`)

Both are required. Keep them secret - never commit them to the repository.

### API details

| Property | Value |
|---|---|
| Base URL | `https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1` |
| Auth headers | `DB-Api-Key: <key>` and `DB-Client-Id: <id>` |
| Response format | XML |
| Baierbrunn EVA number | `8000781` (env: `S7BB_EVA`) |

Endpoints used:

- `GET /plan/{eva}/{YYMMDD}/{HH}` - planned timetable for a station/date/hour
- `GET /fchg/{eva}` - full set of current changes (actual vs. planned times, cancellations)

### Operational notes - construction work

The DB Timetables API does **not** always label S7 trains as `S7`. During
Munich Stammstrecke construction the S7-Süd service is operationally
linked to S7-Nord and the combined Wolfratshausen ↔ Kreuzstraße run is
exposed by the API with `l="S5"` for the Munich-direction departures.
The public timetable still markets these as "S7" but the underlying
slot uses the S5 designator. The fetcher therefore accepts both `S7`
and `S5` for Baierbrunn arrivals.

For the same reason, a Munich-direction departure from Baierbrunn may
list a terminus east of the city (e.g. `Höhenkirchen-Siegertsbrunn`,
`Aying`, `Kreuzstraße`) instead of `München Hbf Gl.27-36` - the train
really does run that whole route during the closure. The site still
groups these as "Richtung München" because München appears in the
mid-path; the displayed terminus shows the train's actual final stop.

Current and upcoming Stammstrecke closures (with their service-pattern
changes) are listed on the official S-Bahn München construction page:
**[s-bahn-muenchen.de/de/fahren/baustellen/stammstrecke](https://www.s-bahn-muenchen.de/de/fahren/baustellen/stammstrecke)**.

For programmatic access to disruption / construction messages, see the
**RIS::Disruptions** product on the DB API Marketplace
([developers.deutschebahn.com/db-api-marketplace/apis/product/ris-disruptions-transporteure](https://developers.deutschebahn.com/db-api-marketplace/apis/product/ris-disruptions-transporteure)).
S7BB does not currently ingest it.

---

## Setup

### Prerequisites

- Python 3.11+ with [uv](https://docs.astral.sh/uv/) (`pip install uv`)
- Node.js 22+
- A VM with internet access. The fetcher pushes via HTTPS using a fine-grained GitHub Personal Access Token (no SSH key required - see §5)

### 1. Clone and configure

Clone this code repo (it carries `docker-compose.yml` and the fetcher
image source). The data-repo working tree at `/repo` is **provisioned
automatically** - `docker compose` runs a one-shot `s7bb-repo-init`
service that clones `s7bb/s7bb-data` into the gitignored host directory
`./data-repo` (bind-mounted; survives `docker volume prune`) before
`s7bb-fetcher` starts. You do **not** clone the data repo by hand.

```bash
git clone <repo-url> /opt/s7bb
cd /opt/s7bb
cp .env.example .env
```

`REPO_PATH=/repo` is the auto-provisioned s7bb-data clone (host directory
`./data-repo`, bind-mounted, gitignored - survives `docker volume
prune`). The DB and generated JSON live under `/data` (host bind-mount,
untracked). Each hourly cycle the exporter writes
`/data/{latest.json,archive/*.json}`, the service copies them into
`/repo` (flat, at the root), commits, and pushes to `s7bb/s7bb-data`
`main`.

Edit `.env` and fill in your credentials:

```
DB_API_KEY=your_api_key_here
DB_CLIENT_ID=your_client_id_here
```

### 2. Install the Python fetcher

```bash
cd fetcher
uv sync
```

Test a single fetch:

```bash
export $(cat /opt/s7bb/.env | xargs)
uv run s7bb-fetch       # fetches current hour → data/s7bb.db
uv run s7bb-export      # writes data/latest.json
```

### 3. Run the container (VM)

```bash
docker compose up -d s7bb-fetcher
```

The container runs APScheduler with two cron jobs:

- `FETCH_CRON` (default `*/5 * * * *`) → fetch + upsert into SQLite
- `EXPORT_CRON` (default `0 * * * *`) → export `data/latest.json` and push to git

Both cron expressions and the GitHub PAT (`GITHUB_PAT`) are configured via `.env`.

**Startup sequence.** `s7bb-repo-init` runs first (clone, or `git fetch`
+ `reset --hard origin/main`) and must exit 0 before `s7bb-fetcher`
starts. A container restart discards any local bot commits that never
pushed - they are regenerated from the persistent SQLite DB on the next
export (single writer, so the remote is authoritative). The `s7bb-fetcher`
container then runs preflight checks and a startup sync against the s7bb-data
`main`: if local `latest.json` is newer than the published copy it is
pushed immediately; if remote is newer, the remote bytes overwrite the
local file. The scheduler does not start until all succeed - any error
aborts startup so an operator notices the divergence.

### Diagnosing startup problems

The fetcher runs a preflight check on startup. If the container exits immediately, run the same checks manually to see which one failed:

```bash
docker compose run --rm s7bb-fetcher s7bb-preflight
```

The CLI prints one line per check. `[OK]` is healthy, `[WARN]` is a soft failure (the service would still start), `[FAIL]` is a hard failure (the service aborts). Common fixes:

- `repo_ownership [FAIL]: dubious ownership` - set `GIT_SAFE_DIRECTORY=/repo` in `.env` or align host UID with the container's `UID`/`GID`.
- `data_writable [FAIL]: permission denied` - the bind-mounted `data/` directory is not writable by the container user.
- `github [WARN]: bad or expired GITHUB_PAT` - issue a new fine-grained PAT and update `.env`.

### 4. Configure GitHub Pages

1. Repo **Settings → Pages → Source → GitHub Actions**.
2. No secrets needed - the deploy workflow uses OIDC (`id-token: write`).
3. On the next data push to `s7bb/s7bb-data` (or a manual `workflow_dispatch`), GitHub Actions will build and deploy the site automatically.

The build workflow checks out **both** this repo (site code) and
`s7bb/s7bb-data` (the JSON) and assembles them into the deployed
artifact. `s7bb/s7bb-data` must stay public for the token-free checkout.
The fallback `schedule:` cron runs at `:10` so it picks up the VM's
`:00` hourly push.

### 5. GitHub credentials for push from VM

The VM authenticates to GitHub with a **fine-grained Personal Access Token (PAT)** scoped to `s7bb/s7bb-data` only, layered with a server-side **push ruleset** that restricts which paths the bot is allowed to write. Even if the PAT leaks, the ruleset still rejects any change outside `latest.json` and `archive/**`.

#### 5a. Add the push ruleset (do this first)

1. Open **`s7bb/s7bb-data`** → **Settings → Rules → Rulesets → New branch ruleset**.
2. **Name:** `protect-main-from-bot-scope-creep`. **Status:** Active. **Bypass list:** empty.
3. **Target branches:** include the default branch (`main`).
4. **Branch rules:**
   - Restrict deletions
   - Block force pushes
   - Require linear history
   - **Restrict file paths** → allow-list:
     - `latest.json`
     - `archive/**`
5. **Create.**

#### 5b. Create the fine-grained PAT

1. **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.**
2. **Token name:** `s7bb-fetcher push`.
3. **Resource owner:** the account that owns this repo.
4. **Expiration:** 1 year (the maximum). GitHub emails the owner before expiry.
5. **Repository access → Only select repositories →** select **only `s7bb/s7bb-data`**.
6. **Permissions → Repository permissions:**
   - **Contents:** Read and write
   - **Metadata:** Read-only (auto-selected, cannot be deselected)
   - All others: **No access**
7. **Generate token.** Copy it immediately - GitHub shows it only once.

#### 5c. Install the token on the VM

```bash
# In /opt/s7bb/.env
GITHUB_PAT=github_pat_xxxxxxxxxxxxxxxx
```

Restart the container to pick up the new value:

```bash
docker compose up -d s7bb-fetcher
```

The token is delivered to `git push` via a per-push `GIT_ASKPASS` helper. It never lands in `.git/config`, never appears in process arguments, and never persists past one push.

#### 5d. Annual rotation

1. Roughly 7 days before expiry, GitHub emails the PAT owner.
2. Generate a replacement PAT with identical scope (steps 5b.1–7).
3. Replace `GITHUB_PAT` in `.env` on the VM and restart: `docker compose up -d s7bb-fetcher`.
4. Wait for the next hourly push to succeed (`docker compose logs --tail 50 s7bb-fetcher`).
5. **Revoke the old PAT** in GitHub Settings.

#### 5e. Suspected leak

1. **Revoke the PAT immediately** in GitHub Settings.
2. Generate a replacement, update `.env`, restart the container.
3. Audit recent commits on `main` for unexpected paths - the push ruleset should have blocked anything off-scope; verify in the repo's commit history.

---

## Development

### Local (Docker)

Primary dev entry point:

    docker compose --profile dev up

`s7bb-data-init` clones the data repo into the gitignored host directory
`./.data-checkout` (bind-mounted) that `s7bb-site-dev` mounts read-only
at `/repo/data`. To refresh the data-repo tip without restarting the
site container:

    docker compose --profile dev run --rm s7bb-data-init

For editor inspection of the data outside Docker, the same
`./.data-checkout` directory is already on the host (the path is
gitignored), or clone it yourself:

    git clone --depth=1 https://github.com/s7bb/s7bb-data.git ./.data-checkout

Production uses a separate one-shot `s7bb-repo-init` → `./data-repo`
host directory, mounted **read-write** by `s7bb-fetcher` (it commits and
pushes). The `dev` profile's `s7bb-data-init` → `./.data-checkout` is
**read-only** for the site container.

**One-time VM migration (0.5.1 → next):** after `git pull` and
`docker compose up -d`, `s7bb-repo-init` re-clones `s7bb/s7bb-data` into
`./data-repo` (remote is authoritative, SQLite in `./data` persists - no
data risk). The orphaned old named volumes may then be removed:

    docker volume rm s7bb-repo s7bb-data-checkout

### Fetcher

```bash
cd fetcher
uv sync --group dev

export DB_API_KEY=...
export DB_CLIENT_ID=...

uv run s7bb-fetch                     # single fetch
uv run s7bb-export                    # export latest.json
uv run pytest                         # run all tests
uv run pytest tests/test_parser.py    # single file
uv run ruff check src tests           # lint
```

### Site

```bash
cd site
npm install
npm run dev        # dev server at http://localhost:5173 (reads ../data/latest.json)
npm run build      # type-check + build → dist/
npm run preview    # serve dist/ locally
npm run lint       # eslint
```

The dev server reads `../data/latest.json` directly. Run `s7bb-export` first to populate it, or create a minimal fixture file manually.

---

## Data

| Path | Description |
|---|---|
| `/data/s7bb.db` | SQLite database - **VM only, never committed**. Schema: [`documentation/database-schema.md`](documentation/database-schema.md) |
| `/data/latest.json` | Last 7 days of arrivals + aggregates - copied to the s7bb-data root and pushed hourly |
| `/data/archive/YYYY-MM.json` | Monthly dumps - pushed to s7bb-data `archive/` on the 1st of each month |

To export a monthly archive manually:

```bash
uv run s7bb-export --archive 2026-05
```

---

## Built with Claude Code

This project was designed and scaffolded using [Claude Code](https://claude.ai/code) (Anthropic's AI coding assistant). The architecture, Python fetcher, TypeScript site, GitHub Actions workflows, and all initial code were generated in a collaborative planning + implementation session.

The AI-assisted workflow:
1. **Architecture planning** - open decisions (storage format, API choice, deploy strategy, chart library) were resolved via a structured plan before any code was written.
2. **Scaffolding** - all files generated from the approved plan in a single session.
3. **Ongoing development** - Claude Code used for subsequent changes, refactoring, and documentation.

---

## License

MIT
