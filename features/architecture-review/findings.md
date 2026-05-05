# Architecture Review — Open Findings

Source: full code + architecture review run on commit `28e6817..a376c46` plus follow-up sweeps.
Closed items are intentionally omitted (see `git log` and `CHANGELOG.md` for what shipped).

Each finding has the same shape so this file can be parsed by future tooling:

```
### <stable-id> — <one-line title>
- **Severity:** critical | high | medium | low
- **Area:** fetcher | site | infra | docs | tests | arch
- **Location:** <path:line> or N/A
- **Problem:** <what is wrong / risk>
- **Suggested fix:** <minimal change that closes it>
- **Status:** open
```

---

## Medium

### MED-001 — `cli.py` derives data path from `__file__`
- **Severity:** medium
- **Area:** fetcher
- **Location:** `fetcher/src/s7bb_fetcher/cli.py:8-10`
- **Problem:** `Path(__file__).parent.parent.parent.parent / "data"` breaks when the package is installed (e.g. inside the Docker image, in a venv) because `__file__` no longer sits at `<repo>/fetcher/src/s7bb_fetcher/`. Today only `--db` / `--out` flags rescue it.
- **Suggested fix:** Read `DATA_DIR` env var (already used in `service.py:18`); default to `Path.cwd() / "data"`. Drop the `__file__` arithmetic.
- **Status:** open

### MED-002 — APScheduler `misfire_grace_time=None` skips missed jobs
- **Severity:** medium
- **Area:** fetcher
- **Location:** `fetcher/src/s7bb_fetcher/service.py:62,68`
- **Problem:** A long-running job (slow API, git push hang) causes following jobs to be silently dropped instead of catching up.
- **Suggested fix:** `misfire_grace_time=300` for fetch, `misfire_grace_time=1800` for export. Add `coalesce=True` so multiple missed runs collapse into one.
- **Status:** open

### MED-003 — Bare `except Exception` in scheduler jobs has no failure budget
- **Severity:** medium
- **Area:** fetcher
- **Location:** `fetcher/src/s7bb_fetcher/service.py:35,49`
- **Problem:** Every failure is logged and swallowed. A persistent outage (expired API key, broken DB) silently produces no data; the container never exits, so `restart: unless-stopped` cannot recover.
- **Suggested fix:** Track consecutive failures per job. After N (e.g. 6 in a row for fetch) `sys.exit(1)` so Docker restarts the container. Optionally surface to a `/healthz` file the dev profile can serve.
- **Status:** open

### MED-004 — Monthly archive promised by README, not wired into scheduler
- **Severity:** medium
- **Area:** fetcher
- **Location:** `fetcher/src/s7bb_fetcher/service.py` (missing job), `fetcher/src/s7bb_fetcher/exporter.py:135 export_monthly_archive`
- **Problem:** `README.md` and `CLAUDE.md` describe `data/archive/YYYY-MM.json` written on the 1st of each month. Implementation only exists as a CLI flag (`s7bb-export --archive`); no scheduled job calls it, so archives are never produced in production.
- **Suggested fix:** Add a third APScheduler job (`CronTrigger(day=1, hour=2, minute=15)`) that calls `export_monthly_archive` for the previous month, then triggers `pusher.push_latest` for `data/archive/*.json`.
- **Status:** open

### MED-005 — `arrivalsByDirection` builds two redundant `.map`s
- **Severity:** medium
- **Area:** site
- **Location:** `site/src/data.ts:59-80`
- **Problem:** First `.map` constructs `{slot, record}` from `recordByTime` / `observedTimes`; the trailing `.map` rebuilds the same object via `recordByTime.get(row.slot) ?? null`. The first map is dead code and `observedTimes` is unused.
- **Suggested fix:** Collapse to one pass: `[...allSlots].sort().map(slot => ({ slot, record: recordByTime.get(slot) ?? null }))`. Drop `observedTimes`.
- **Status:** open

### MED-006 — `_migrate` runs on every `open_db`, no `PRAGMA user_version` gate
- **Severity:** medium
- **Area:** fetcher
- **Location:** `fetcher/src/s7bb_fetcher/storage.py:29-48`
- **Problem:** `_migrate` reads `PRAGMA table_info` on every connection. Cheap today but does not scale once more migrations land — and if a future migration is destructive, lack of versioning makes it hard to know whether it has already been applied.
- **Suggested fix:** Use `PRAGMA user_version`. Each migration bumps the version inside a transaction; `_migrate` becomes a `match user_version` ladder.
- **Status:** open

### MED-007 — `pusher.push_latest` leaves `latest.json` staged on partial failure
- **Severity:** medium
- **Area:** fetcher
- **Location:** `fetcher/src/s7bb_fetcher/pusher.py:28-46`
- **Problem:** If the process is killed between `repo.index.add(...)` and `repo.index.commit(...)`, the file stays staged. Next run's `repo.index.diff("HEAD")` no-ops because the index already matches HEAD's intent, so the change is never committed.
- **Suggested fix:** At function entry, `repo.index.reset()` (or `git reset HEAD -- data/latest.json`) before staging. Wrap stage+commit+push in a try/finally that resets the index on exception.
- **Status:** open

---

## Low

### LOW-001 — Direction fallback uses arrival path origin
- **Severity:** low
- **Area:** fetcher
- **Location:** `fetcher/src/s7bb_fetcher/parser.py:105-109`
- **Problem:** When `dp` is missing, code reads `ar.ppth[0]` — that is the *origin*, not the terminus. Sets `direction` to a misleading station name.
- **Suggested fix:** Leave `direction = "unbekannt"` when `dp` missing; rely on `direction_bucket = "unknown"` already returned by `classify_direction("")`.
- **Status:** open

### LOW-002 — `_expected_slots` anchor math is unreadable
- **Severity:** low
- **Area:** fetcher
- **Location:** `fetcher/src/s7bb_fetcher/exporter.py:53-71`
- **Problem:** `(first.minute // 20) * 20 + anchor_offset`, then `if start_minute > first.minute: start_minute -= 20`, then `% 60` and conditional `+= timedelta(hours=1)` — works, but cannot be read.
- **Suggested fix:** Rewrite: walk back from `first` in 20-minute steps until `t.minute % 20 == anchor_offset`, then walk forward to `last`.
- **Status:** open

### LOW-003 — Nav links lack `aria-current`
- **Severity:** low
- **Area:** site
- **Location:** `site/index.html:15-19`, `site/src/main.ts:30`
- **Problem:** Active page is communicated only via the `.active` CSS class. Screen readers cannot announce which nav item is current.
- **Suggested fix:** When toggling `.active` in `main.ts`, also set `aria-current="page"` on the active anchor and remove it from the others.
- **Status:** open

### LOW-004 — `statusBadge` emoji has no accessible label
- **Severity:** low
- **Area:** site
- **Location:** `site/src/pages/today.ts:9-13`
- **Problem:** Emoji glyphs (`✓`, `⏱`, `✕`) are read inconsistently by screen readers; the accompanying German text ("ausgefallen" / "+N min" / "pünktlich") already conveys the state, so the emoji is purely decorative.
- **Suggested fix:** Wrap glyph in `<span aria-hidden="true">`; rely on the existing text node for the label.
- **Status:** open

### LOW-005 — `today.ts` keeps an unused local `agg`
- **Severity:** low
- **Area:** site
- **Location:** `site/src/pages/today.ts:58`
- **Problem:** `agg` is read once in the footer template; the per-direction aggregates already come from `data.aggregates.today.by_direction`. The local can be inlined.
- **Suggested fix:** Inline `data.aggregates.today.total` and `.avg_delay_min` into the template; drop the local.
- **Status:** open

### LOW-006 — Dockerfile does not pin the `git` apt package
- **Severity:** low
- **Area:** infra
- **Location:** `fetcher/Dockerfile:4`
- **Problem:** `apt-get install -y git` floats with the base image. A future Debian point release that pulls a new `git` major could change CLI behavior (GitPython shells out to `git`).
- **Suggested fix:** Pin: `git=1:2.* ` or the explicit Debian version present in the chosen base. Document that the base image bumps drive `git` updates.
- **Status:** open

### LOW-007 — `CHANGELOG.md` `[Unreleased]` has duplicate `### Added` blocks
- **Severity:** low
- **Area:** docs
- **Location:** `CHANGELOG.md` (under `[Unreleased]`)
- **Problem:** Two `### Added` sections accumulated across recent merges. Keep a Changelog spec wants one section per type.
- **Suggested fix:** Merge into a single `### Added` block when cutting the next release.
- **Status:** open

### LOW-008 — `docker-compose.yml` lacks healthcheck and log rotation
- **Severity:** low
- **Area:** infra
- **Location:** `docker-compose.yml`
- **Problem:** Container has no healthcheck, so `docker compose ps` cannot tell whether the scheduler is alive vs. wedged. No `logging.options.max-size` either, so logs grow unbounded on a small VM.
- **Suggested fix:** Add a healthcheck that touches a heartbeat file from each scheduler tick and `test` reads it; add `logging: driver: json-file, options: { max-size: 10m, max-file: 3 }`.
- **Status:** open

### LOW-009 — `docker-compose.yml` mounts entire repo into `/repo`
- **Severity:** low
- **Area:** infra
- **Location:** `docker-compose.yml:13`
- **Problem:** Pusher only needs `.git/` and `data/`; mounting the whole repo widens the blast radius of a container compromise.
- **Suggested fix:** Replace `- .:/repo` with `- ./.git:/repo/.git` + `- ./data:/repo/data` (or restructure so pusher operates on a thin checkout).
- **Status:** open

### LOW-010 — `api.py` raises bare `KeyError` when `DB_API_KEY` is unset
- **Severity:** low
- **Area:** fetcher
- **Location:** `fetcher/src/s7bb_fetcher/api.py:14`
- **Problem:** `os.environ["DB_API_KEY"]` produces `KeyError: 'DB_API_KEY'` deep in a stack trace; first-time operators have to guess the cause.
- **Suggested fix:** At process start (`cli.fetch`, `service._fetch_job`), check both env vars and raise a `SystemExit` with a clear message before any HTTP call.
- **Status:** open

### LOW-011 — Logs are unstructured
- **Severity:** low
- **Area:** fetcher
- **Location:** `fetcher/src/s7bb_fetcher/service.py:12-15`
- **Problem:** Plain text format makes it hard to grep specific fields out of `docker compose logs`.
- **Suggested fix:** Switch `logging.basicConfig` to a JSON formatter (e.g. `python-json-logger`). Drop into `pyproject.toml` and the Dockerfile's runtime deps.
- **Status:** open

### LOW-012 — CI does not lint YAML / shell
- **Severity:** low
- **Area:** infra
- **Location:** `.github/workflows/ci.yml`
- **Problem:** Workflow files and any future shell scripts are unchecked. A typo in `ci.yml` only surfaces when CI fails for unrelated reasons.
- **Suggested fix:** Add an `actionlint` step (and `shellcheck` if shell scripts return).
- **Status:** open

### LOW-013 — `build-site.yml` runs an hourly cron rebuild even though the VM pushes hourly
- **Severity:** low
- **Area:** infra
- **Location:** `.github/workflows/build-site.yml:10-11`
- **Problem:** Two triggers fire at the same cadence: `push` to `data/**` from the VM and the workflow's own `schedule: cron: "0 * * * *"`. The cron run rebuilds with the same artifacts, doubling CI minutes.
- **Suggested fix:** Drop the `schedule` block; rely on the push trigger plus `workflow_dispatch` for manual rebuilds.
- **Status:** open

---

## Bigger architectural items

### ARCH-001 — Replace git-push deploy with hosted JSON
- **Severity:** medium (architecture)
- **Area:** arch
- **Location:** `fetcher/src/s7bb_fetcher/pusher.py`, `.github/workflows/build-site.yml`
- **Problem:** Hourly git commits inflate history, require a deploy key on the VM, and couple data updates to a CI rebuild.
- **Suggested fix:** Have the VM publish `latest.json` to a static origin (Cloudflare R2, GitHub release asset, or the VM itself behind nginx). Site fetches cross-origin. CI only rebuilds on actual code changes.
- **Status:** open

### ARCH-002 — Dedup key is too narrow
- **Severity:** low (architecture)
- **Area:** fetcher
- **Location:** `fetcher/src/s7bb_fetcher/storage.py:24`
- **Problem:** `(train_id, scheduled_time)` collides if DB renumbers a train or two trains share the same scheduled minute at the same EVA.
- **Suggested fix:** Extend the unique index to `(eva_no, train_id, scheduled_time, direction_bucket)` and add the `eva_no` column (currently only the constant `BAIERBRUNN_EVA` is used).
- **Status:** open

### ARCH-003 — No catch-up / backfill
- **Severity:** medium (architecture)
- **Area:** fetcher
- **Location:** `fetcher/src/s7bb_fetcher/api.py:48 fetch_baierbrunn_now`, `service.py:24 _fetch_job`
- **Problem:** Fetcher only requests the *current* hour. If the VM is down for 30 minutes, that window is permanently missing.
- **Suggested fix:** Track the most recent fully-fetched hour in SQLite. On each tick, fetch every missing hour up to "now" (capped at e.g. last 24 h to bound API load).
- **Status:** open

### ARCH-004 — Test coverage gaps
- **Severity:** medium (architecture)
- **Area:** tests
- **Location:** `fetcher/tests/`
- **Problem:** No tests for: timezone regression (the just-fixed critical bug), `pusher.push_latest`, `service.main` (scheduler wiring + retry), full XML round-trip from `api.fetch_*`. A regression on the timezone fix would not surface until production.
- **Suggested fix:** Add `test_parser_timezone.py` asserting that a `2605051200` (DE local noon CEST) parses to `2026-05-05T10:00:00+00:00`. Add a `pusher` test using a tmp git repo. Add a `service` test that monkeypatches `_fetch_job` and asserts the failure counter from MED-003.
- **Status:** open

### ARCH-005 — One-pass slot merge in `arrivalsByDirection`
- **Severity:** low (architecture)
- **Area:** site
- **Location:** `site/src/data.ts:59-80`
- **Problem:** Implementation builds 4 sets/maps for what is conceptually a sorted merge. Slow for nothing on small data, hard to extend to a third direction.
- **Suggested fix:** Sort once, walk both arrays (expected slots + observed) with two pointers, emit `{slot, record}` per step. Also closes MED-005.
- **Status:** open

---

## Dependabot queue (snapshot)

These are not findings from the original review but live in the same backlog:

- PR #3 — `chore(deps): Bump esbuild and vite in /site` (security; vite stays 5.x)
- PR #4 — `chore(deps-dev): Bump vite from 5.2.11 to 6.4.2` (major; needs vite-config and Node-version review)

GitHub remote reports the default branch carries multiple Dependabot vulns (last seen: 1 high, 14 moderate, 2 low). Triage at https://github.com/angrox/s7bb/security/dependabot.
