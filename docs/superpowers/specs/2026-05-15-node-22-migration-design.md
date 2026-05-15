# Node 20 → 22 LTS migration + Node-24 action runtimes — Design

**Date:** 2026-05-15
**Status:** Approved (brainstorming)
**Type:** `chore(ci)` — no semver bump, no release trigger

## Problem

1. GitHub Actions emits a deprecation warning: `actions/checkout@v4`,
   `actions/setup-node@v4`, and the transitive `actions/upload-artifact@v4`
   run on the Node 20 action runtime. GitHub forces Node 24 on 2026-06-02
   and removes Node 20 from runners on 2026-09-16.
2. The site build/dev toolchain targets Node 20. Node 20 reached
   end-of-life on 2026-04-30 (already past as of 2026-05-15). Active LTS
   is Node 22 ("Jod"), supported into 2027.
3. No dev/CI Node-version parity guard exists (no `.nvmrc`, no `engines`),
   so versions can silently drift.

## Goal

Move the build/dev toolchain from Node 20 to Node 22 LTS, bump GitHub
Actions to their Node-24 runtime majors, and pin one source of truth for
the Node version. Single `chore(ci)` PR.

## Scope

### Node 20 → 22

| Change | File | Detail |
|---|---|---|
| Add `.nvmrc` | `.nvmrc` (new, repo root) | Content: `22`. Single source of truth. nvm/fnm auto-switch locally. |
| CI Node | `.github/workflows/build-site.yml` | `actions/setup-node` step: replace `node-version: "20"` with `node-version-file: .nvmrc`. |
| CI Node | `.github/workflows/ci.yml` | Same: `node-version-file: .nvmrc`. |
| Dev image | `docker-compose.yml` (line ~85, `s7bb-site-dev`) | `image: node:20-alpine` → `image: node:22-alpine`. |
| Doc prereq | `README.md` (line ~63) | `Node.js 20+` → `Node.js 22+`. |

### Action runtime bumps (Node-24, same workflow files)

| Action | From | To |
|---|---|---|
| `actions/checkout` | `@v4` | `@v6` |
| `actions/setup-node` | `@v4` | `@v6` |
| `actions/upload-pages-artifact` | `@v3` | `@v5` (kills transitive `upload-artifact@v4`) |
| `actions/deploy-pages` | `@v4` | `@v5` (pair with upload v5) |

Occurrences:
- `build-site.yml`: `checkout@v4` ×2, `setup-node@v4` ×1,
  `upload-pages-artifact@v3` ×1, `deploy-pages@v4` ×1.
- `ci.yml`: `checkout@v4` ×3, `setup-node@v4` ×1.

Docker/uv actions (`astral-sh/setup-uv@v4`, `docker/setup-buildx-action@v3`,
`docker/build-push-action@v6`) are NOT in the deprecation warning and are
out of scope for this PR.

## Compatibility analysis

No production Node runtime: the site ships a static `dist/` to GitHub
Pages. Node runs only at build time (Actions) and local dev.

Dependency floors vs Node 22:

| Dep | Version | Node 22 |
|---|---|---|
| vite | 6.4.2 | ✅ supports 18/20/22+ |
| vitest | 2.1.9 | ✅ Node 18+ |
| typescript | 5.4.5 | ✅ engine-agnostic |
| eslint | 8.57.0 | ✅ runs (>=16); EOL debt, see below |
| jsdom | 25.0.1 | ✅ Node 18+ |
| chart.js | 4.4.3 | ✅ browser lib, build-time only |

`package-lock.json` floor is only `node >=18`, no upper bound. No native
addons / node-gyp anywhere → no rebuild risk. Vite bundle target is
browsers (set in `site/vite.config.ts`), decoupled from the Node runtime
→ emitted bundle is byte-identical. npm 10 ships on both `node:20-alpine`
and `node:22-alpine` → `npm ci` behavior and `lockfileVersion` unchanged.

## Risk & rollback

- Regression risk: minimal (no prod Node, no native deps, bundle target
  decoupled from Node version).
- Security gain: real — moves off EOL Node 20 onto active LTS Node 22.
- Rollback: revert the single commit. No state or data migration; fully
  reversible.

## Verification (gate before merge)

Local, on Node 22:

```bash
cd site
npm ci
npm run build
npm run test
npm run lint
```

Then: CI green on the PR (both `ci.yml` jobs and a `build-site.yml`
dispatch/preview if feasible).

## Out of scope (YAGNI)

- **ESLint 8.57 EOL** (eslint 9 flat-config migration). Pre-existing
  technical debt, not blocked by or related to the Node bump. Separate PR.
- **Historical plan files** under `docs/superpowers/plans/*.md` that
  contain `node-version: "20"`. These are the durable record of past
  intent and must not be edited.
- Docker/uv GitHub Actions bumps (not in the deprecation warning).

## Commit / release

- One commit: `chore(ci): migrate Node 20→22 LTS, bump actions to Node-24 runtimes`.
- No `pyproject.toml` / `CHANGELOG.md` version bump. Pure CI/tooling change
  — does not trigger the post-merge release procedure.
