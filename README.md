# S7BB — S7 Baierbrunn Pünktlichkeit

Tracks on-time performance of the Deutsche Bahn S7 S-Bahn line at Baierbrunn station (Munich). Shows live delays, cancellations, and weekly statistics. Published as a static site on GitHub Pages, updated hourly.

**Live site:** *(add your GitHub Pages URL here)*

---

## How it works

```
DB Timetables API (XML)
        │
        ▼  every 5 min (systemd timer on VM)
  s7bb-fetch  →  data/s7bb.db  (SQLite, stays on VM)
        │
        ▼  every hour (systemd timer on VM)
  s7bb-export  →  data/latest.json  →  git push
        │
        ▼  GitHub Actions (triggered by push to data/**)
  Vite build  →  GitHub Pages
```

The fetcher runs on a small VM and pushes `data/latest.json` hourly. GitHub Actions rebuilds and deploys the static site on every push.

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
| Baierbrunn EVA number | `8004073` |

Endpoints used:

- `GET /plan/{eva}/{YYMMDD}/{HH}` — planned timetable for a station/date/hour
- `GET /fchg/{eva}` — full set of current changes (actual vs. planned times, cancellations)

---

## Setup

### Prerequisites

- Python 3.11+ with [uv](https://docs.astral.sh/uv/) (`pip install uv`)
- Node.js 20+
- A VM with internet access and `git` configured with a deploy key that can push to this repo

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

### 3. Configure systemd timers (VM)

```bash
# Copy units
sudo cp fetcher/systemd/s7bb-fetch.service  /etc/systemd/system/
sudo cp fetcher/systemd/s7bb-fetch.timer    /etc/systemd/system/
sudo cp fetcher/systemd/s7bb-export.service /etc/systemd/system/
sudo cp fetcher/systemd/s7bb-export.timer   /etc/systemd/system/

# Install push script
sudo cp fetcher/push-data.sh /opt/s7bb/push-data.sh
sudo chmod +x /opt/s7bb/push-data.sh

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable --now s7bb-fetch.timer s7bb-export.timer
```

The fetch timer fires every 5 minutes. The export timer fires hourly and calls `push-data.sh` to commit and push `data/latest.json`.

### 4. Configure GitHub Pages

1. Repo **Settings → Pages → Source → GitHub Actions**.
2. No secrets needed — the deploy workflow uses OIDC (`id-token: write`).
3. On the first push of `data/latest.json` from the VM, GitHub Actions will build and deploy the site automatically.

### 5. Deploy key for git push from VM

1. Generate a key pair on the VM: `ssh-keygen -t ed25519 -f ~/.ssh/s7bb_deploy`
2. Add the **public key** to the repo: **Settings → Deploy keys → Add → Allow write access**.
3. Configure SSH on the VM:

```
# ~/.ssh/config
Host github.com
  IdentityFile ~/.ssh/s7bb_deploy
```

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
| `data/s7bb.db` | SQLite database — **VM only, never committed** |
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
