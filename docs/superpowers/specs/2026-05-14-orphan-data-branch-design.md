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

`site/src/data.ts` and `site/src/archive.ts` read `../data/latest.json` in dev mode. After migration, `main` no longer contains `data/`, so a fresh clone has no file there.

Two compatible options for dev:

1. The existing `s7bb-site-dev` compose service already transforms `latest.json` into an anonymous overlay. Update `site/dev-entrypoint.sh` to fetch `https://raw.githubusercontent.com/{slug}/data/latest.json` on startup when no local copy exists, writing it into the overlay. (Preferred — keeps the dev experience one-command.)
2. Developers who run the fetcher locally see `/data/latest.json` populated as before; a small symlink `site/public/data -> ../../data` can be added so Vite serves it during dev. (Fallback for offline work.)

The CLAUDE.md mention of `npm run dev` continues to work.

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
   - Update `service.py` if any path constants reference `data/` inside `/repo`.
   - Update `README.md` §VM Setup and §GitHub Pages Setup sections.
   - Update `CLAUDE.md` architecture diagram.
   - Add release note in `CHANGELOG.md` under `[Unreleased]`: `feat: decouple data pushes via orphan data branch (resolves push collisions with main)`.
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

## Open questions

- Should `archive/index.json` live on `data` (alongside the monthly files) or be generated by the Actions workflow at deploy time from the directory listing? Current code generates it in `exporter.export_archive_index`. Keeping that path means `index.json` ships on the `data` branch, which is consistent and simple. **Resolution: keep current behaviour, ship `index.json` on `data`.**
- Do we want a small "freshness" badge on the site that warns when `latest.json`'s `generated_at` is older than, say, 90 minutes? Out of scope for this design; tracked as a follow-up. The current incident would have surfaced visibly with such a badge.

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
