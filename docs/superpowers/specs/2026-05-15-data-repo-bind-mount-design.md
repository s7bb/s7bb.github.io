# Design: data-repo clone on a host bind mount + discard-visibility guard

Date: 2026-05-15
Status: Approved (brainstorming) — pending spec review

## Problem

The s7bb-data working tree consumed by the production fetcher lives in a
Docker **named volume** (`s7bb-repo`), populated by the one-shot
`s7bb-repo-init` service and mounted read-write at `/repo` by
`s7bb-fetcher`. The dev site-preview path uses a second named volume
(`s7bb-data-checkout`).

Named volumes are wiped by `docker volume prune` and by routine teardown
flows. An operator running `docker volume prune` on the VM would silently
destroy the data-repo clone (and the dev checkout). Recovery is automatic
(remote `s7bb/s7bb-data` is authoritative, SQLite in `/data` regenerates
the JSON), but the exposure is unnecessary: a host bind mount cannot be
touched by `docker volume prune`.

Secondary concern raised during brainstorming: `s7bb-repo-init` runs
`git reset --hard origin/main` on every restart, silently discarding any
unpushed local commits in the `/repo` clone. We want visibility into
that, without changing the (deliberate) reset behavior.

## Goals

1. Move the production data-repo clone off the `s7bb-repo` named volume
   onto a gitignored host bind mount `./data-repo`, so it survives
   `docker volume prune` and is directly inspectable on the host.
2. Apply the same treatment to the dev `s7bb-data-checkout` volume →
   bind mount `./.data-checkout` (full symmetry, requested).
3. Add a loud `WARN` to `s7bb-repo-init` when its `reset --hard`
   discards unpushed local commits — observability only, no behavior
   change.
4. Keep the compose-wiring regression guard green and meaningful.
5. Keep docs (README, CLAUDE.md) accurate.

## Non-goals

- No change to the freshness/reconcile logic in `s7bb_fetcher`
  (`startup_sync`, `pusher`). It already compares the authoritative
  persistent `/data` against remote and pushes when local is newer.
- No env-configurable host path (`${REPO_HOST_DIR:-…}`). YAGNI — no
  operator-disk-placement requirement.
- No conversion of the `s7bb-site-node-modules` named volume (it is not
  data; prune of it is harmless and self-healing via `npm install`).

## Architecture invariant (the safety reasoning, made explicit)

This invariant is the reason the design is safe and must be recorded:

- **`/data` is the single authoritative, persistent source.** SQLite
  (`/data/s7bb.db`) plus the exporter outputs (`/data/latest.json`,
  `/data/archive/*.json`) live on the `./data` host bind mount.
  `s7bb-repo-init` does **not** mount `/data` and never touches it.
- **`/repo` is disposable staging.** `pusher.push_data()` copies
  `/data` → `/repo`, commits, and pushes `HEAD:refs/heads/main`
  **non-force**. Every `/repo` commit is byte-reconstructable from
  `/data`.
- **`s7bb-repo-init`'s `reset --hard origin/main` is deliberate**: it
  guarantees `/repo` HEAD == remote `main`, so the subsequent non-force
  push is always a fast-forward and cannot be rejected. After reset,
  `startup_sync` reads persistent `/data`; if newer than remote it
  re-derives the commit and pushes. The "newer data" therefore lives in
  `/data` and is preserved + pushed **regardless of the reset**.

Consequence: a freshness check *inside* `s7bb-repo-init` would compare
the stale `/repo` staging copy, not the authoritative `/data`, and would
duplicate `startup_sync` semantics on the wrong artifact. Hence the
guard is **visibility only** (WARN), not a behavioral gate.

## Design

### 1. `docker-compose.yml`

Mount edits (short-form binds, mirroring the existing `./data` pattern):

| Service | Was | Becomes |
|---|---|---|
| `s7bb-repo-init` | `s7bb-repo:/repo-clone` | `./data-repo:/repo-clone` |
| `s7bb-fetcher` | `s7bb-repo:/repo` | `./data-repo:/repo` |
| `s7bb-data-init` (dev) | `s7bb-data-checkout:/data-checkout` | `./.data-checkout:/data-checkout` |
| `s7bb-site-dev` (dev) | `s7bb-data-checkout:/repo/data:ro` | `./.data-checkout:/repo/data:ro` |

Top-level `volumes:` drops `s7bb-repo:` and `s7bb-data-checkout:`;
keeps `s7bb-site-node-modules:`.

Header comment (lines ~2–8) reworded: "host directory, bind-mounted"
instead of "named volume"; keep the existing note that `reset --hard`
discards unpushed local bot commits, and add that this is now logged.

Ownership: unchanged model. Same rootless-nerdctl `root → host invoking
user` mapping that `./data` already relies on (compose lines ~32–36).
Docker/nerdctl auto-creates the missing host dirs on first `up`.

Behavioral note for `s7bb-site-dev`: it already binds `.:/repo`, so
`./.data-checkout` also surfaces at `/repo/.data-checkout`; the explicit
`./.data-checkout:/repo/data:ro` overlay still wins for the path Vite
reads. Behaviorally identical to the named-volume version.

### 2. `s7bb-repo-init` discard-visibility guard

Existing-clone branch only (a fresh `git clone` has nothing to
discard). After the fetch, before `reset --hard`:

```sh
set -e
if [ ! -d /repo-clone/.git ]; then
  git clone --branch main --single-branch "$DATA_REPO_URL" /repo-clone
else
  git -C /repo-clone fetch origin main
  ahead=$(git -C /repo-clone rev-list --count origin/main..HEAD 2>/dev/null || echo 0)
  if [ "$ahead" -gt 0 ]; then
    behind=$(git -C /repo-clone rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
    echo "WARN: s7bb-repo-init discarding $ahead unpushed local commit(s) (behind=$behind) via 'reset --hard origin/main'; data is reconstructable from persistent /data on the next export / startup_sync push" >&2
  fi
  git -C /repo-clone reset --hard origin/main
fi
```

- **YAML escaping**: the snippet above is shell-level. In
  `docker-compose.yml` every `$` that must reach the shell is written
  `$$` (compose variable-interpolation escape) — matching the existing
  `$$DATA_REPO_URL`. So `$ahead` → `$$ahead`, `$(… )` → `$$(… )`,
  `"$DATA_REPO_URL"` → `"$$DATA_REPO_URL"`. The implementation plan must
  preserve this.
- `set -e`-safe: `|| echo 0` guards the rev-list counts so a missing
  ref cannot abort the script.
- No behavior change: still `git fetch` + `reset --hard origin/main`.
  Only a stderr `WARN` is added when `ahead > 0`.
- Fast-forward-push guarantee preserved.

Dev `s7bb-data-init` is **excluded** from the guard: its checkout is
consumed read-only by `s7bb-site-dev` (`:ro`), nothing ever writes
commits there, so it can never be ahead of origin. (It keeps its
existing `reset --hard FETCH_HEAD` behavior.)

### 3. `.gitignore`

Add `/data-repo/` (the s7bb-data clone working tree — same rationale as
the existing `/data/` entry: untracked here, s7bb-data repo is the
source of truth). `/.data-checkout/` is already present — no change.

### 4. `fetcher/tests/test_compose_wiring.py`

- **Keep unchanged**: `test_fetcher_does_not_mount_the_code_repo`
  (the security-critical invariant — the `.`/`./` → `/repo` regex).
  Verified: `./data-repo:/repo` does **not** match that regex
  (`\.\/?:` requires `.`/`./` immediately followed by `:`; `./data-repo:`
  has `data-repo` between), so the guard still rejects only the
  historical code-repo defect and does not false-positive on the new
  mount.
- **Keep unchanged**: `test_fetcher_depends_on_repo_init_completed`.
- **Rewrite** `test_fetcher_mounts_s7bb_repo_volume` →
  assert `s7bb-fetcher` mounts `./data-repo:/repo` (short-form bind).
- **Rewrite** `test_repo_init_service_and_volume_declared` →
  assert `s7bb-repo-init` clones the `s7bb-data.git` repo and populates
  `./data-repo:/repo-clone`; **drop** the top-level `volumes: s7bb-repo`
  assertion (the named volume no longer exists). Optionally assert the
  top-level `volumes:` block does **not** declare `s7bb-repo`
  (regression: ensures the volume was actually removed).
- Update the module docstring (it currently references the named
  volume and `s7bb-repo:/repo`).

### 5. Docs + migration

- `README.md`: §1 ("clones … into the `s7bb-repo` named volume"), the
  `REPO_PATH=/repo` paragraph, and the dev section (~229–241,
  "clones the data repo into a named volume", "separate one-shot
  `s7bb-repo-init` → `s7bb-repo` volume") → reword to "host directory
  `./data-repo` / `./.data-checkout` (bind-mounted, gitignored)".
- `CLAUDE.md`: "VM Setup" §1 ("auto-provisioned by the `s7bb-repo-init`
  compose service (named volume `s7bb-repo`)") → same reword.
- One-time VM migration note (README): after `git pull` +
  `docker compose up -d`, `s7bb-repo-init` re-clones into `./data-repo`
  (remote authoritative, SQLite in `./data` persists — no data risk);
  the old named volumes are orphaned and may be removed with
  `docker volume rm s7bb-repo s7bb-data-checkout`.
- `.env.example`: **unchanged** — `REPO_PATH=/repo` is
  container-internal and still correct.
- `CHANGELOG.md` `[Unreleased]`: classify as `fix(compose)` — prevents
  data-repo-clone loss on `docker volume prune` (operational defect).
  Carries a PATCH post-merge release per the CLAUDE.md post-merge rule;
  final commit type/scope confirmed during planning. The added `WARN`
  is internal observability, folded into the same `fix`.

## Testing

- `cd fetcher && uv run pytest tests/test_compose_wiring.py` — green
  with rewritten assertions; the security regex test stays green
  unmodified.
- `cd fetcher && uv run pytest` — full suite green (no source change in
  `s7bb_fetcher`; only compose/test/docs change).
- `cd fetcher && uv run ruff check src tests`.
- Manual sanity: `docker compose config` parses; `docker compose up -d
  s7bb-fetcher` creates `./data-repo` on the host, clones s7bb-data into
  it, fetcher mounts it at `/repo`. Restart with a synthetic unpushed
  commit in `./data-repo` → `s7bb-repo-init` logs the `WARN` and resets.

## Risks / edge cases

- **Rootful Docker ownership**: bind-mounted dirs auto-created by the
  daemon are root-owned; `s7bb-fetcher` runs `user: "0:0"` so it still
  writes. Identical tradeoff to the existing `./data` mount — no
  regression, documented by the existing compose comment.
- **First `up` after migration**: `./data-repo` does not exist; compose
  auto-creates it, `s7bb-repo-init` clones into it. Old `s7bb-repo`
  volume becomes orphaned (harmless; optional cleanup documented).
- **`WARN` noise**: only emitted when `ahead > 0` (a genuinely unpushed
  local commit at restart), which is the exact event we want surfaced.
```
