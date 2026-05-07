# S7BB — S7 Baierbrunn Pünktlichkeit

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
        ▼  GitHub Actions (triggered by push to data/**)
  Vite build  →  GitHub Pages
```

The fetcher runs in a Docker container on a small VM and pushes `data/latest.json` hourly. GitHub Actions rebuilds and deploys the static site on every push.

---

## Deutsche Bahn API

S7BB uses the **DB Timetables API** from the DB API Marketplace.

### Register for an API key

1. Go to **[developers.deutschebahn.com](https://developers.deutschebahn.com)** and create a free account.
2. Navigate to **API Marketplace → Timetables** and subscribe to the API (free tier is sufficient).
3. After subscribing, open your application in the portal. You will find two credentials:
   - **Client ID** (`DB-Client-Id`)
   - **API Key** (`DB-Api-Key`)

Both are required. Keep them secret — never commit them to the repository.

### API details

| Property | Value |
|---|---|
| Base URL | `https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1` |
| Auth headers | `DB-Api-Key: <key>` and `DB-Client-Id: <id>` |
| Response format | XML |
| Baierbrunn EVA number | `8000781` (env: `S7BB_EVA`) |

Endpoints used:

- `GET /plan/{eva}/{YYMMDD}/{HH}` — planned timetable for a station/date/hour
- `GET /fchg/{eva}` — full set of current changes (actual vs. planned times, cancellations)

---

## Setup

### Prerequisites

- Python 3.11+ with [uv](https://docs.astral.sh/uv/) (`pip install uv`)
- Node.js 20+
- A VM with internet access. The fetcher pushes via HTTPS using a fine-grained GitHub Personal Access Token (no SSH key required — see §5)

### 1. Clone and configure

```bash
git clone <repo-url> /opt/s7bb
cd /opt/s7bb
cp .env.example .env
```

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

### Diagnosing startup problems

The fetcher runs a preflight check on startup. If the container exits immediately, run the same checks manually to see which one failed:

```bash
docker compose run --rm s7bb-fetcher s7bb-preflight
```

The CLI prints one line per check. `[OK]` is healthy, `[WARN]` is a soft failure (the service would still start), `[FAIL]` is a hard failure (the service aborts). Common fixes:

- `repo_ownership [FAIL]: dubious ownership` — set `GIT_SAFE_DIRECTORY=/repo` in `.env` or align host UID with the container's `UID`/`GID`.
- `data_writable [FAIL]: permission denied` — the bind-mounted `data/` directory is not writable by the container user.
- `github [WARN]: bad or expired GITHUB_PAT` — issue a new fine-grained PAT and update `.env`.

### 4. Configure GitHub Pages

1. Repo **Settings → Pages → Source → GitHub Actions**.
2. No secrets needed — the deploy workflow uses OIDC (`id-token: write`).
3. On the first push of `data/latest.json` from the VM, GitHub Actions will build and deploy the site automatically.

### 5. GitHub credentials for push from VM

The VM authenticates to GitHub with a **fine-grained Personal Access Token (PAT)** scoped to a single repository, layered with a server-side **push ruleset** that restricts which paths the bot is allowed to write. Even if the PAT leaks, the ruleset still rejects any change outside `data/latest.json` and `data/archive/**`.

#### 5a. Add the push ruleset (do this first)

1. Repo **Settings → Rules → Rulesets → New branch ruleset**.
2. **Name:** `protect-main-from-bot-scope-creep`. **Status:** Active. **Bypass list:** empty.
3. **Target branches:** include the default branch (`main`).
4. **Branch rules:**
   - Restrict deletions
   - Block force pushes
   - Require linear history
   - **Restrict file paths** → allow-list:
     - `data/latest.json`
     - `data/archive/**`
5. **Create.**

#### 5b. Create the fine-grained PAT

1. **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.**
2. **Token name:** `s7bb-fetcher push`.
3. **Resource owner:** the account that owns this repo.
4. **Expiration:** 1 year (the maximum). GitHub emails the owner before expiry.
5. **Repository access → Only select repositories →** select **only this repo**.
6. **Permissions → Repository permissions:**
   - **Contents:** Read and write
   - **Metadata:** Read-only (auto-selected, cannot be deselected)
   - All others: **No access**
7. **Generate token.** Copy it immediately — GitHub shows it only once.

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
3. Audit recent commits on `main` for unexpected paths — the push ruleset should have blocked anything off-scope; verify in the repo's commit history.

---

## Development

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
| `data/s7bb.db` | SQLite database — **VM only, never committed**. Schema: [`documentation/database-schema.md`](documentation/database-schema.md) |
| `data/latest.json` | Last 7 days of arrivals + aggregates — committed hourly |
| `data/archive/YYYY-MM.json` | Monthly dumps — committed on the 1st of each month |

To export a monthly archive manually:

```bash
uv run s7bb-export --archive 2026-05
```

---

## Built with Claude Code

This project was designed and scaffolded using [Claude Code](https://claude.ai/code) (Anthropic's AI coding assistant). The architecture, Python fetcher, TypeScript site, GitHub Actions workflows, and all initial code were generated in a collaborative planning + implementation session.

The AI-assisted workflow:
1. **Architecture planning** — open decisions (storage format, API choice, deploy strategy, chart library) were resolved via a structured plan before any code was written.
2. **Scaffolding** — all files generated from the approved plan in a single session.
3. **Ongoing development** — Claude Code used for subsequent changes, refactoring, and documentation.

---

## License

MIT
