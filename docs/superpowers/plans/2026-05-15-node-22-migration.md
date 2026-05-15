# Node 20 → 22 LTS Migration + Node-24 Action Runtimes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the build/dev toolchain from Node 20 to Node 22 LTS, bump GitHub Actions to their Node-24 runtime majors, and pin one source of truth for the Node version, in a single `chore(ci)` PR.

**Architecture:** Add a root `.nvmrc` (`22`) as the single source of truth; both CI workflows consume it via `node-version-file`. The dev container image and the README prerequisite move to Node 22. GitHub Actions (`checkout`, `setup-node`, `upload-pages-artifact`, `deploy-pages`) bump to majors running on the Node-24 runtime. No production Node runtime exists (static `dist/` on GitHub Pages), so the change is config-only and fully revertible.

**Tech Stack:** GitHub Actions YAML, Docker Compose, nvm/fnm, Node 22 LTS, Vite 6 / Vitest 2 / TypeScript 5 / ESLint 8 (unchanged).

**Spec:** `docs/superpowers/specs/2026-05-15-node-22-migration-design.md`

**Branch:** Already on `ci/node-22-migration` (the PR branch). Do **not** create a new branch.

**Commit policy:** The spec mandates **one commit** for the whole change (overrides the default "frequent commits" guidance). Make all edits across all tasks first; commit once in the final task. Do not commit between tasks.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `.nvmrc` | Create (repo root) | Single source of truth for Node version: `22`. Consumed by nvm/fnm locally and by `setup-node` in CI. |
| `.github/workflows/build-site.yml` | Modify | CI build/deploy: consume `.nvmrc`; bump `checkout`→v6, `setup-node`→v6, `upload-pages-artifact`→v5, `deploy-pages`→v5. |
| `.github/workflows/ci.yml` | Modify | CI lint/test/build: consume `.nvmrc`; bump `checkout`→v6, `setup-node`→v6. |
| `docker-compose.yml` | Modify | Dev image `node:20-alpine`→`node:22-alpine` (svc `s7bb-site-dev`, line 85). |
| `README.md` | Modify | Prerequisite `Node.js 20+`→`Node.js 22+` (line 63). |
| `docs/superpowers/plans/2026-05-15-node-22-migration.md` | Commit (this file) | Durable record of intent; bundled into the implementation commit per CLAUDE.md. |

`node-version-file` in `setup-node` is resolved relative to the repository root (`GITHUB_WORKSPACE`), independent of any step `working-directory`. Both workflows check this repo out at the default root path, so the value is `.nvmrc` in **both** (not `../.nvmrc`).

---

### Task 1: Ensure Node 22 locally + add `.nvmrc`

**Files:**
- Create: `.nvmrc`

- [ ] **Step 1: Check current local Node version**

Run: `node --version`
Note the output (e.g. `v20.x.x`). If already `v22.x.x`, skip Step 2.

- [ ] **Step 2: Install + activate Node 22**

With nvm:

```bash
nvm install 22
nvm use 22
```

Or with fnm:

```bash
fnm install 22
fnm use 22
```

Run: `node --version`
Expected: `v22.` prefix (e.g. `v22.x.x`).

- [ ] **Step 3: Create `.nvmrc` at repo root**

Create `.nvmrc` with exactly this content (single line, trailing newline, no `v` prefix):

```
22
```

- [ ] **Step 4: Verify nvm/fnm picks it up**

Run from repo root: `nvm use` (or `fnm use`)
Expected: resolves to a Node 22 version, e.g. `Now using node v22.x.x`.

(No commit — see Commit policy.)

---

### Task 2: Update `.github/workflows/build-site.yml`

**Files:**
- Modify: `.github/workflows/build-site.yml`

- [ ] **Step 1: Bump both `actions/checkout` to v6**

There are two occurrences (lines 27 and 30). Replace **all**:

Old (each occurrence):
```yaml
        uses: actions/checkout@v4
```
New:
```yaml
        uses: actions/checkout@v6
```

Use an Edit with `replace_all: true` on `        uses: actions/checkout@v4` → `        uses: actions/checkout@v6` (both occurrences in this file must become v6).

- [ ] **Step 2: Bump `actions/setup-node` to v6 and switch to `.nvmrc`**

Replace this block (lines 36–40):

```yaml
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: site/package-lock.json
```

with:

```yaml
      - uses: actions/setup-node@v6
        with:
          node-version-file: .nvmrc
          cache: "npm"
          cache-dependency-path: site/package-lock.json
```

- [ ] **Step 3: Bump `actions/upload-pages-artifact` to v5**

Replace (line 58):

```yaml
      - uses: actions/upload-pages-artifact@v3
```
with:
```yaml
      - uses: actions/upload-pages-artifact@v5
```

- [ ] **Step 4: Bump `actions/deploy-pages` to v5**

Replace (line 70):

```yaml
        uses: actions/deploy-pages@v4
```
with:
```yaml
        uses: actions/deploy-pages@v5
```

- [ ] **Step 5: Verify the diff**

Run: `git diff .github/workflows/build-site.yml`
Expected: exactly 5 changed lines — `checkout@v4`→`@v6` ×2, `setup-node@v4`→`@v6` ×1, `node-version: "20"`→`node-version-file: .nvmrc` ×1, `upload-pages-artifact@v3`→`@v5` ×1, `deploy-pages@v4`→`@v5` ×1. No other lines touched.

- [ ] **Step 6: Lint the YAML**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/build-site.yml')); print('build-site.yml OK')"`
Expected: `build-site.yml OK` (no traceback).

(No commit — see Commit policy.)

---

### Task 3: Update `.github/workflows/ci.yml`

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Bump all three `actions/checkout` to v6**

Three occurrences (lines 16, 37, 60). Replace **all**:

Old (each occurrence):
```yaml
      - uses: actions/checkout@v4
```
New:
```yaml
      - uses: actions/checkout@v6
```

Use an Edit with `replace_all: true` on `      - uses: actions/checkout@v4` → `      - uses: actions/checkout@v6` (all three occurrences in this file must become v6).

- [ ] **Step 2: Bump `actions/setup-node` to v6 and switch to `.nvmrc`**

Replace this block (lines 39–43):

```yaml
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: site/package-lock.json
```

with:

```yaml
      - uses: actions/setup-node@v6
        with:
          node-version-file: .nvmrc
          cache: "npm"
          cache-dependency-path: site/package-lock.json
```

- [ ] **Step 3: Verify the diff**

Run: `git diff .github/workflows/ci.yml`
Expected: exactly 4 changed lines — `checkout@v4`→`@v6` ×3, `setup-node@v4`→`@v6` ×1, `node-version: "20"`→`node-version-file: .nvmrc` ×1. (`astral-sh/setup-uv@v4`, `docker/setup-buildx-action@v3`, `docker/build-push-action@v6` MUST remain untouched — they are out of scope per the spec.)

- [ ] **Step 4: Lint the YAML**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('ci.yml OK')"`
Expected: `ci.yml OK` (no traceback).

(No commit — see Commit policy.)

---

### Task 4: Update dev image + README prerequisite

**Files:**
- Modify: `docker-compose.yml:85`
- Modify: `README.md:63`

- [ ] **Step 1: Bump the dev container image to Node 22**

In `docker-compose.yml`, under the `s7bb-site-dev:` service (line 85), replace:

```yaml
    image: node:20-alpine
```
with:
```yaml
    image: node:22-alpine
```

(There is exactly one `node:20-alpine` in the live `docker-compose.yml`.)

- [ ] **Step 2: Bump the README prerequisite**

In `README.md` (line 63, under `### Prerequisites`), replace:

```
- Node.js 20+
```
with:
```
- Node.js 22+
```

- [ ] **Step 3: Verify the diffs**

Run: `git diff docker-compose.yml README.md`
Expected: exactly 2 changed lines — `node:20-alpine`→`node:22-alpine` and `Node.js 20+`→`Node.js 22+`. Nothing else.

- [ ] **Step 4: Validate compose file syntax**

Run: `docker compose config -q && echo "compose OK"`
Expected: `compose OK` (no error). If `docker` is unavailable in the environment, instead run `python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml')); print('compose YAML OK')"` and expect `compose YAML OK`.

(No commit — see Commit policy.)

---

### Task 5: Verification gate + single commit + PR

**Files:**
- All staged changes from Tasks 1–4 + this plan file.

- [ ] **Step 1: Confirm Node 22 is active**

Run: `node --version`
Expected: `v22.` prefix. If not, `nvm use` (or `fnm use`) from repo root — `.nvmrc` now drives it.

- [ ] **Step 2: Clean install on Node 22**

Run:
```bash
cd site
npm ci
```
Expected: completes with exit 0, no `EBADENGINE` / unsupported-engine errors, `package-lock.json` unchanged afterward (`git diff --quiet site/package-lock.json` returns 0).

- [ ] **Step 3: Type-check + build**

Run (from `site/`): `npm run build`
Expected: `tsc --noEmit` passes (no type errors), `vite build` completes, `dist/` written, exit 0.

- [ ] **Step 4: Tests**

Run (from `site/`): `npm run test`
Expected: `vitest run` — all tests pass, exit 0.

- [ ] **Step 5: Lint**

Run (from `site/`): `npm run lint`
Expected: `eslint src` — no errors, exit 0. (ESLint 8.57 runs on Node 22; the eslint-9 migration is explicitly out of scope.)

- [ ] **Step 6: Final review of the full diff**

Run (from repo root): `git status --short && git diff`
Expected changes only in: `.nvmrc` (new), `.github/workflows/build-site.yml`, `.github/workflows/ci.yml`, `docker-compose.yml`, `README.md`. No `pyproject.toml`, no `CHANGELOG.md`, no `site/package-lock.json` changes (pure CI/tooling change — does not trigger the post-merge release procedure).

- [ ] **Step 7: Stage and create the single commit**

Run (from repo root):
```bash
git add .nvmrc \
        .github/workflows/build-site.yml \
        .github/workflows/ci.yml \
        docker-compose.yml \
        README.md \
        docs/superpowers/plans/2026-05-15-node-22-migration.md
git commit -m "$(cat <<'EOF'
chore(ci): migrate Node 20→22 LTS, bump actions to Node-24 runtimes

Add root .nvmrc (22) as the single source of truth; both workflows
consume it via node-version-file. Bump actions/checkout@v4→v6,
actions/setup-node@v4→v6, actions/upload-pages-artifact@v3→v5,
actions/deploy-pages@v4→v5 (Node-24 runtimes; kills the deprecation
warning and the transitive upload-artifact@v4). Dev image
node:20-alpine→node:22-alpine; README prereq Node 20+→22+.

No prod Node runtime (static dist/ on Pages); no native deps; bundle
target decoupled from Node — config-only and fully revertible.

Spec: docs/superpowers/specs/2026-05-15-node-22-migration-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```
Expected: one commit created on `ci/node-22-migration`. No `pyproject.toml`/`CHANGELOG.md` bump (spec: pure CI/tooling, no release trigger).

- [ ] **Step 8: Push and open the PR**

Run:
```bash
git push -u origin ci/node-22-migration
gh pr create --base main --head ci/node-22-migration \
  --title "chore(ci): migrate Node 20→22 LTS, bump actions to Node-24 runtimes" \
  --body "$(cat <<'EOF'
Moves the build/dev toolchain off EOL Node 20 onto active LTS Node 22,
and bumps GitHub Actions to Node-24 runtime majors (clears the
deprecation warning). Single source of truth: root `.nvmrc`.

See `docs/superpowers/specs/2026-05-15-node-22-migration-design.md` and
`docs/superpowers/plans/2026-05-15-node-22-migration.md`.

- `.nvmrc` (new): `22`
- `build-site.yml` / `ci.yml`: `node-version-file: .nvmrc`; checkout v6, setup-node v6; build-site also upload-pages-artifact v5, deploy-pages v5
- `docker-compose.yml`: dev image `node:22-alpine`
- `README.md`: prerequisite `Node.js 22+`

No prod Node runtime, no native deps, bundle target decoupled from Node
→ config-only, fully revertible. No semver bump / no release trigger.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
Expected: PR created against `main`.

- [ ] **Step 9: Confirm CI green**

Wait for both `ci.yml` jobs (python, typescript, docker) and any `build-site.yml` run to complete on the PR.
Run: `gh pr checks ci/node-22-migration`
Expected: all required checks pass. If a `build-site.yml` dispatch is feasible, trigger `workflow_dispatch` and confirm it builds + deploys green.

---

## Self-Review

**1. Spec coverage:**
- `.nvmrc` (new, `22`) → Task 1 ✅
- `build-site.yml` `node-version-file` → Task 2 Step 2 ✅
- `ci.yml` `node-version-file` → Task 3 Step 2 ✅
- `docker-compose.yml` dev image → Task 4 Step 1 ✅
- `README.md` prereq → Task 4 Step 2 ✅
- `checkout@v4`→v6 (build ×2, ci ×3) → Task 2 Step 1 / Task 3 Step 1 ✅
- `setup-node@v4`→v6 (×1 each) → Task 2 Step 2 / Task 3 Step 2 ✅
- `upload-pages-artifact@v3`→v5 → Task 2 Step 3 ✅
- `deploy-pages@v4`→v5 → Task 2 Step 4 ✅
- Out-of-scope (docker/uv actions, eslint 9, historical plan files) → explicitly not touched; Task 3 Step 3 guards the docker/uv actions ✅
- Verification gate (`npm ci`/`build`/`test`/`lint` on Node 22 + CI green) → Task 5 Steps 2–5, 9 ✅
- One commit, no semver/release → Task 5 Step 7 + Commit policy ✅
- Plan file committed (CLAUDE.md) → Task 5 Step 7 ✅

No gaps.

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". Every edit shows exact old→new content; every command has expected output.

**3. Type consistency:** N/A (no code types). Action version targets are internally consistent (`upload-pages-artifact@v5` paired with `deploy-pages@v5`; `node-version-file: .nvmrc` identical in both workflows and matches the `.nvmrc` created in Task 1). `node-version-file` value is repo-root-relative (`.nvmrc`, not `../.nvmrc`) consistently in both workflows.
