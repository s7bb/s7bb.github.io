# Design: Orphan `data` branch to decouple VM data pushes from `main`

**Status:** Draft
**Date:** 2026-05-14
**Author:** Martin Zehetmayer

## Problem

The VM running the `s7bb-fetcher` container commits `data/latest.json` and `data/archive/*.json` to `main` once per hour and pushes via PAT over HTTPS. The push uses `HEAD:refs/heads/main` and performs no `git fetch` or rebase first (`fetcher/src/s7bb_fetcher/pusher.py`).

When anything else lands on `main` between two VM pushes — most often a Dependabot merge — the VM's local `main` is no longer an ancestor of `origin/main` and the next push is rejected as non-fast-forward. The exception is silently caught by `_safe("push", ...)` in `service.py`, so the scheduler keeps running but pushes never succeed again until a human resets the VM clone.

Observed instance verified against GitHub on 2026-05-14:

| Time (UTC)             | Commit  | Event                                |
| ---------------------- | ------- | ------------------------------------ |
| 2026-05-13T14:00:00Z   | 15eed86 | last hourly data commit              |
| 2026-05-13T14:51:31Z   | f7a4e96 | Dependabot merge: urllib3            |
| 2026-05-13T14:53:49Z   | 1f9f083 | Dependabot merge: gitpython          |
| 2026-05-13T15:00:00Z…  | —       | hourly data pushes missing for >24h  |

`raw.githubusercontent.com/s7bb/s7bb.github.io/main/data/latest.json` still reports `generated_at = 2026-05-13T14:00:00Z`. The site shows "Lade Daten…" because the bundled data is too stale to render.

The root cause is structural: a high-frequency machine writer (hourly bot push of data files) and a low-frequency human/bot writer (PRs, Dependabot, docs) share a single branch with fast-forward push semantics. Sharing the *branch* — not the repository — is the bug.

## Goal

Eliminate the push collision class without splitting the repository. Data writes from the VM must never compete with `main` for fast-forward, and code/PR activity on `main` must never invalidate the VM's working tree.

Non-goals: changing fetch cadence, chart library, monthly archive format; splitting into a separate repository (option C in the brainstorming); replacing the PAT-over-HTTPS push mechanism.

## Approach: orphan `data` branch

Introduce a new branch `data` with no shared history with `main`. The branch contains only `latest.json` and `archive/`. The VM is the sole writer. `main` continues to hold code, site, fetcher, workflows, docs, and Dependabot/PR activity, but no longer contains `data/`.

```
main (humans + Dependabot)            data (VM only — orphan, no shared history)
─────────────────────────             ─────────────────────────────────────────
 fetcher/  site/  docs/  ...           latest.json
 .github/workflows/                    archive/2026-01.json
 (no data/)                            archive/2026-02.json
                                       archive/index.json
```

The GitHub Pages build workflow checks out both refs and assembles them into the deployed artifact.

## Components

### 1. Repository layout

`main` after migration:

- `fetcher/`, `site/`, `docs/`, `.github/`, `README.md`, `CHANGELOG.md`, `docker-compose.yml`, `CLAUDE.md`, `LICENSE` — unchanged.
- `data/` is removed from the tracked tree.
- `.gitignore` on `main` adds `/data/` so local working copies that still produce `data/` (developers running the fetcher locally) do not accidentally re-commit them.

`data` branch:

- Orphan (`git checkout --orphan data`), starts empty.
- Tracks `latest.json`, `archive/*.json`, `archive/index.json` at the **root** of the branch (not under a `data/` prefix), so the published path on GitHub Pages stays `…/data/latest.json` via the workflow copy step and does not require renaming any client code.
  - Rationale: a flat layout makes the branch self-describing — every tracked file is a data file. The workflow handles path mapping into the site bundle.

### 2. VM checkout

The container clones only the `data` branch as a shallow single-branch checkout:

```
git clone --branch data --single-branch --depth=1 \
    https://github.com/s7bb/s7bb.github.io.git /repo
```

`REPO_PATH=/repo` continues to be the fetcher's git working tree. The container never sees `main` and therefore cannot be invalidated by Dependabot or any other `main` activity. The local SQLite DB and generated JSON live under `/data` (bind-mount of `./data` on the host, untracked by git), exactly as today.

The exporter (`fetcher/src/s7bb_fetcher/exporter.py`) writes its outputs into `/data` (unchanged). A new small step copies (or hardlinks) the produced JSON files from `/data` into `/repo` at the root, so the existing `pusher.push_data` logic can stage them. Alternative considered: change the exporter to write directly into `/repo`. Rejected because it conflates "produce data" with "stage data for git" — keeping `/data` as the authoritative working store and `/repo` as the git staging area preserves the separation that exists today between `DATA_DIR` and `REPO_PATH`.

### 3. Pusher changes (`fetcher/src/s7bb_fetcher/pusher.py`)

Single-line constant change:

```python
_PUSH_REFSPEC = "HEAD:refs/heads/data"   # was refs/heads/main
```

The file-staging logic changes only in that the relative paths inside the `data` branch are flat (`latest.json`, `archive/*.json`) rather than prefixed with `data/`. The function signature, commit-author handling, ASKPASS helper, and `_resolve_slug` logic are unchanged.

A defensive `git fetch origin data && git merge --ff-only origin/data` is added before the commit step. It is a no-op in the steady state (nobody else writes to `data`) but turns a silent overwrite into an explicit error if a second writer ever appears.

### 4. Startup sync (`fetcher/src/s7bb_fetcher/startup_sync.py`)

The raw-URL reconciliation logic is unchanged in spirit but updates its source URL:

```
https://raw.githubusercontent.com/{slug}/data/latest.json   # was main/data/latest.json
```

The function still compares `generated_at` and decides push / pull / noop. Pull writes into `/data/latest.json` (unchanged). Push delegates to `pusher.push_data` (unchanged).

### 5. GitHub Actions workflow (`.github/workflows/build-site.yml`)

Trigger expansion:

```yaml
on:
  push:
    branches: [main, data]
    paths-ignore: []     # path filter removed; branch filter is sufficient
  schedule:
    - cron: "0 * * * *"
  workflow_dispatch:
```

Build job checks out both refs:

```yaml
- uses: actions/checkout@v4
  with: { ref: main }
- uses: actions/checkout@v4
  with:
    ref: data
    path: data-branch
- name: Stage data into site dist
  run: |
    mkdir -p site/dist/data/archive
    cp data-branch/latest.json        site/dist/data/latest.json    || true
    cp data-branch/archive/*.json     site/dist/data/archive/       2>/dev/null || true
```

The remaining steps (`npm ci`, `npm run build`, `upload-pages-artifact`, `deploy-pages`) are unchanged. Concurrency group `pages` already prevents overlapping deploys.

### 6. Branch protection / rulesets

- `main`: remove the existing path-restricted ruleset that allowed bot-PAT pushes to `data/**`. `main` becomes a normal protected branch (PR-only, status checks, no direct pushes from bots).
- `data`: new ruleset — only the s7bb-bot PAT identity may push; force-push denied; deletions denied. No path restriction is needed because the branch only contains data files by construction.

### 7. PAT scope

The fine-grained PAT used by the VM is re-scoped to `Contents: read/write` on this single repository, restricted by ruleset to the `data` branch. The existing token is rotated as part of the cutover.

### 8. Local development

`site/src/data.ts` and `site/src/archive.ts` read `../data/latest.json` in dev mode. After migration, `main` no longer contains `data/`, so a fresh clone has no file there. `site/dev-entrypoint.sh` also reads `/repo/data/latest.json`, applies a +1 min time shift, and writes the result to a `/repo/site/data/` anonymous overlay that Vite serves.

The dev experience materializes the `data` branch into a known location inside the dev container so both reads work unchanged.

#### Approach: init container clones `data` branch into a named volume

A new `s7bb-data-init` compose service (one-shot, profile `dev`) clones the `data` branch shallowly into a named volume. The existing `s7bb-site-dev` service depends on it and mounts the same volume at `/repo/data`.

```yaml
services:
  s7bb-data-init:
    image: alpine/git:latest
    profiles: [dev]
    environment:
      DATA_BRANCH_URL: https://github.com/s7bb/s7bb.github.io.git
    entrypoint: ["sh", "-c"]
    command:
      - |
        set -e
        if [ ! -d /data-checkout/.git ]; then
          git clone --branch data --single-branch --depth=1 \
            "$$DATA_BRANCH_URL" /data-checkout
        else
          git -C /data-checkout fetch --depth=1 origin data
          git -C /data-checkout reset --hard FETCH_HEAD
        fi
    volumes:
      - s7bb-data-checkout:/data-checkout

  s7bb-site-dev:
    # ... existing fields ...
    depends_on:
      s7bb-data-init:
        condition: service_completed_successfully
    volumes:
      - .:/repo
      - s7bb-data-checkout:/repo/data:ro          # NEW: data branch tip mounted read-only
      - /repo/site/data                           # existing anonymous overlay (transform output)
      - s7bb-site-node-modules:/repo/site/node_modules

volumes:
  s7bb-site-node-modules:
  s7bb-data-checkout:                              # NEW
```

Branch layout is flat, so the volume root contains `latest.json` and `archive/`. Mounting the volume at `/repo/data` makes the existing entrypoint path `/repo/data/latest.json` resolve without script changes. Vite's `server.fs.allow` may need to be widened to include `..` (verify in `vite.config.ts`; expand if missing).

#### Refresh

To pick up a newer `data` tip, re-run only the init service:

```
docker compose --profile dev run --rm s7bb-data-init
```

The site container keeps the same volume mounted and sees the updated files immediately. Document the command in `site/README.md`.

#### Alternative (offline / inspection): host `git worktree`

For developers who want the data branch files on the host (e.g., to read in their editor):

```
git worktree add ./.data-checkout data
```

Then point the compose volume at the worktree by bind-mounting `./.data-checkout:/repo/data:ro` instead of using the named volume. `.gitignore` excludes `/.data-checkout/`. Refresh via `git -C .data-checkout pull --ff-only`.

#### Fallback for offline development

If both options fail (no network on first run, no prior checkout), the dev-entrypoint already logs `dev-entrypoint: $SRC not readable; skipping data prep` and the site renders its error path. Acceptable — dev mode without data was never offline-friendly.

The CLAUDE.md mention of `npm run dev` and the README §Local development section need a one-line update pointing to `docker compose --profile dev up` as the primary entry point.

## Data flow (after migration)

```
DB Timetables API → s7bb-fetch     → /data/s7bb.db          (host bind-mount, untracked)
                                  ↓
                  s7bb-export    → /data/latest.json
                                  → /data/archive/*.json
                                  ↓ (copy)
                  pusher         → /repo/latest.json           (data branch working tree)
                                  → /repo/archive/*.json
                                  → git commit + push HEAD:refs/heads/data
                                                                        ↓
                                                              GitHub: data branch updated
                                                                        ↓
                                                              Actions: build-site.yml
                                                              checks out main + data,
                                                              assembles site/dist,
                                                              deploys to gh-pages
```

## Failure modes

| Failure                                            | Behaviour                                                                                       |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Dependabot / human merge on `main`                 | `data` ref unchanged. VM push unaffected.                                                       |
| VM clone corrupted                                 | Container restart re-clones single-branch `data` shallow checkout. < 1 MB transferred.          |
| Concurrent push to `data` from another source      | `git merge --ff-only origin/data` in pusher fails loudly. Logged. Next cycle retries.            |
| Hourly build-site run during VM push               | `concurrency: pages` already serialises the deploy. Trigger on `data` push enqueues a rebuild.   |
| Site code change on `main`                         | `build-site.yml` triggers on `main` push, rebuilds, redeploys, picks up latest `data` ref.       |
| `data` branch accidentally deleted                 | Ruleset denies deletion. If forced, archive history is preserved in `data/archive/*.json` files on the most recent gh-pages artifact and in any local VM clone. |

## Testing

1. **Unit**: `pusher.push_data` push refspec asserted as `HEAD:refs/heads/data`. Mock `repo.git.push` and verify args. Existing tests under `fetcher/tests/` adapted.
2. **Integration (local)**: spin up a throwaway GitHub repo (or local bare repo) with `main` and orphan `data`, run the container against it, simulate a Dependabot-equivalent commit on `main` between two VM cycles, assert next cycle pushes successfully to `data`.
3. **CI**: extend `ci.yml` lint/test job to cover the updated pusher.
4. **Manual verification (post-deploy)**: trigger `workflow_dispatch` of `build-site.yml`, confirm `s7bb.github.io/data/latest.json` reflects the latest `data` branch tip.

## Migration plan (single PR + one-time setup)

1. **PR on `main`**:
   - Remove `data/` from tracked tree (`git rm -r data/`).
   - Add `/data/` to `.gitignore`.
   - Update `build-site.yml` (two-ref checkout).
   - Update `pusher.py` (refspec + flat paths) and `startup_sync.py` (raw URL).
   - Update `exporter.py` SQL queries in `export_latest` and `export_monthly_archive` to `ORDER BY scheduled_time, train_id` for stable row ordering (improves git delta compression on hourly archive rewrites).
   - Update `service.py` if any path constants reference `data/` inside `/repo`.
   - Add `site/src/freshness.ts` (state computation + thresholds), corresponding `freshness.test.ts`, CSS rules in `site/src/style.css`, and wire badge into `today.ts`, `week.ts`, `stats.ts`, and archive list page.
   - Add `s7bb-data-init` service to `docker-compose.yml` and the `s7bb-data-checkout` named volume; wire `s7bb-site-dev` to depend on it and mount `/repo/data:ro`. Add `/.data-checkout/` to `.gitignore` for the host-worktree alternative. Verify `site/vite.config.ts` `server.fs.allow` permits `..`.
   - Update `README.md` §VM Setup and §GitHub Pages Setup sections.
   - Update `CLAUDE.md` architecture diagram.
   - Add release notes in `CHANGELOG.md` under `[Unreleased]`:
     - `feat: decouple data pushes via orphan data branch (resolves push collisions with main)`
     - `feat(site): freshness badge (frisch/verzögert/veraltet) on data-driven pages`
2. **One-time setup on GitHub** (manual, by maintainer):
   - Create orphan `data` branch from current `data/` directory contents (flat layout). Push.
   - Add `data` ruleset.
   - Rotate PAT; restrict to `data` branch.
3. **VM cutover**:
   - Stop container.
   - Re-clone `/repo` as single-branch `data` checkout.
   - Update `.env` (`GITHUB_PAT` to rotated value).
   - Start container.
4. **Verify**: watch first hourly cycle push to `data`; watch `build-site.yml` trigger and deploy; confirm site shows fresh `generated_at`.
5. **Cut release** per CLAUDE.md release procedure (MINOR bump for the `feat:`).

## Archive placement and retention

All archive content lives on the `data` branch alongside `latest.json`. The branch root layout is:

```
data branch root:
  latest.json                  ← hot, rewritten hourly
  archive/2026-05.json         ← hot until 2026-06-01, then immutable
  archive/2026-04.json         ← cold (finalized)
  archive/2026-03.json         ← cold
  …
  archive/index.json           ← hot, rewritten hourly, small
```

### Alternatives rejected

| Option                                                       | Reason rejected                                                                |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------ |
| Split `latest.json` and `archive/` across two branches       | 2× pusher logic, 2× rulesets, atomic publish lost                              |
| Archive as GitHub Releases assets (one release per month)    | Not raw-URL friendly, API quota, fetcher needs `gh` auth, site code rewrite    |
| Archive in separate `s7bb-data-archive` repo                 | New admin surface, second PAT, second ruleset, premature decouple              |

### Storage growth

The current-month archive (`archive/YYYY-MM.json`) is rewritten in full every hour (~720 rewrites/month). Finalized monthly files are written once and never touched again.

- Typical finalized month: ~500 KB – 2 MB JSON.
- Hourly rewrites of the current-month file delta-compress well in the git pack because the file is JSON with stable line-oriented formatting (`indent=2`, deterministic key order, deterministic row order — see "JSON determinism" below).
- Ten-year projection at this scale: well under GitHub's 1 GB soft repo quota.

No automatic history pruning is needed. A manual escape hatch is documented as a runbook (below) and only used if the `data` branch ever approaches the quota.

### JSON determinism

`exporter.py` already produces near-deterministic output: SQL `ORDER BY scheduled_time`, sorted aggregate keys, fixed dict insertion order, `json.dump(..., indent=2, ensure_ascii=False)`. One stability gap: ties on `scheduled_time` are not broken, so two arrivals at the same minute could swap order between exports. Fix as part of this migration:

- `export_latest` and `export_monthly_archive` SQL: `ORDER BY scheduled_time, train_id`.

`generated_at` necessarily changes every export. It is a single line near the top of each file; git delta compression handles it trivially. Left as-is.

### Runbook: re-orphan `data` branch (escape hatch)

Trigger condition: `git count-objects -v --human-readable` on the `data` branch reports a pack size approaching the repository quota (≥500 MB), or GitHub surfaces a quota warning.

Procedure (manual, by maintainer; not automated):

1. Stop the VM container so no concurrent push races the rebase.
2. Locally: `git checkout --orphan data-v2 origin/data`, `git commit -m "chore(data): re-orphan to drop history"`, `git push origin data-v2`.
3. Update ruleset: protect `data-v2` with the same rules as `data`; remove `data` ruleset.
4. Delete `data` (`gh api -X DELETE …/git/refs/heads/data`). Rename `data-v2` → `data`.
5. On VM: re-clone `/repo` single-branch shallow on the new `data` ref.
6. Restart the container.

Site is unaffected: gh-pages workflow trigger is on branch name, not on commit history. The site keeps serving the previous deploy artifact until the next workflow run.

## Freshness badge

A visual indicator on the site that surfaces stale data immediately. The 2026-05-13 incident left the site silently serving 24-hour-old data with no warning beyond a static "Stand:" timestamp that the user had to read and compare to wall-clock time. A coloured badge makes the staleness obvious at a glance.

### Computation

Client-side only. `freshnessState(generatedAt: string, now: Date): "frisch" | "verzoegert" | "veraltet"` in a new `site/src/freshness.ts`:

| State        | Age window         | Reason for threshold                                                       |
| ------------ | ------------------ | -------------------------------------------------------------------------- |
| `frisch`     | `< 75 min`         | Healthy steady state: hourly export + ≤15 min CI/deploy + small clock skew |
| `verzoegert` | `75 min – 180 min` | One missed hourly cycle, may self-recover                                  |
| `veraltet`   | `> 180 min`        | Three missed cycles — clear push/CI/fetcher failure                        |

Thresholds exported as named constants so tests assert against them rather than literals.

### Display

Extend the existing `.data-age` line on the today page (`site/src/pages/today.ts`) and add the same component to `stats.ts`, `week.ts`, and the archive list page. Component renders:

```html
<span class="freshness freshness--frisch">●&nbsp;aktuell</span>
<span class="freshness freshness--verzoegert">●&nbsp;verzögert</span>
<span class="freshness freshness--veraltet">●&nbsp;veraltet — Daten nicht aktuell</span>
```

Colours (high-contrast, accessibility-safe):
- `frisch` → green (`#16a34a`)
- `verzoegert` → amber (`#d97706`)
- `veraltet` → red (`#dc2626`)

Badge is prepended to the existing "Stand: …" line so the timestamp still appears beside it.

### Live transition

Recompute state every 60 s with `setInterval` so a page left open transitions `frisch → verzoegert → veraltet` without reload. Cleared on route change. Small DOM update only (swap class + label); no refetch.

### Error path

The existing fetch-error branch in `main.ts` (`<p class="error">Fehler beim Laden der Daten…</p>`) handles network failure / 404. The freshness badge is rendered only when `latest.json` was successfully loaded — it complements, not replaces, the error path.

### Tests

New `site/src/freshness.test.ts` covers:
- exact boundaries (74, 75, 179, 180 min)
- timezone-independent (always UTC arithmetic on `generated_at`)
- handles trailing `+00:00` vs `Z` ISO suffixes

### Scope note

The badge is added as part of this migration even though it is conceptually independent of the orphan-branch change. Bundling makes sense because:

1. Both changes are responses to the same incident.
2. Both ship in the same release.
3. The site code is touched once for both (the existing `.data-age` line is the natural anchor).

Pure CSS additions and one new module — risk is low.

## Open questions

(none)

## Trade-offs

**Pros**

- Push collisions structurally impossible: `data` ref has exactly one writer.
- VM clone is tiny and ephemeral; no need to fetch unrelated history.
- `git log` on `main` becomes readable again — no hourly noise interleaved with real changes.
- Dependabot can run freely. PR review workflow on `main` is unchanged.
- No new repository, no new secrets store, no new admin surface beyond one extra branch.

**Cons**

- `build-site.yml` does two checkouts instead of one. Marginal CI runtime cost.
- Developers who used to read `data/latest.json` from a `main` checkout now need either the dev-entrypoint fetch or a local symlink.
- Two refs to keep mental model for; new contributor needs one short paragraph in README to understand why.
- Archive listing on the GitHub web UI splits across two branches (code on `main`, data on `data`). Acceptable — the site is the user-facing surface.
