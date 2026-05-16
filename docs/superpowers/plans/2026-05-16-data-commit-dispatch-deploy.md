# Data-Commit-Triggered Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the site within seconds of every data commit instead of relying on GitHub's unreliable `schedule:` cron, without giving the VM any new access to the code repo.

**Architecture:** GitHub has no native cross-repo push trigger. The VM keeps pushing data to `s7bb/s7bb-data` with its existing single-repo PAT (unchanged). A new tiny workflow **inside s7bb-data** runs `on: push` and calls the GitHub **`workflow_dispatch` REST API** to trigger `build-site.yml` in `s7bb/s7bb.github.io`. The cross-repo token is a fine-grained PAT scoped to `s7bb.github.io` with **`Actions: write` only** (cannot modify code), stored as an Actions secret in s7bb-data — never on the VM. The `schedule:` cron is removed entirely; `workflow_dispatch` (manual + API) and the existing `push` trigger remain.

**Tech Stack:** GitHub Actions YAML, GitHub REST API (`/actions/workflows/{file}/dispatches`), `gh` CLI (preinstalled on `ubuntu-latest`), fine-grained PAT.

---

## Why `workflow_dispatch` API, not `repository_dispatch`

| Mechanism | API endpoint | Fine-grained PAT permission required | Can mutate code repo? |
|---|---|---|---|
| `repository_dispatch` | `POST /repos/{o}/{r}/dispatches` | **`Contents: write`** | **Yes** (write to repo contents) |
| `workflow_dispatch` | `POST /repos/{o}/{r}/actions/workflows/{file}/dispatches` | **`Actions: write`** | No (trigger/cancel workflows only) |

The locked CLAUDE.md decision is "the bot PAT has no access to this code repo." `repository_dispatch` would need `Contents: write` on `s7bb.github.io` — a token that can rewrite code. `workflow_dispatch` needs only `Actions: write` — least privilege, cannot touch code. **This plan uses `workflow_dispatch`.** `build-site.yml` already declares `workflow_dispatch:`, so no new trigger type is added there.

## Trust boundary outcome

- VM PAT: **unchanged** (still `s7bb-data` only, `Contents: read/write`). Locked decision preserved verbatim — the VM gains nothing.
- New cross-repo token: lives **only** as an Actions secret in s7bb-data repo settings. Scope: `s7bb/s7bb.github.io`, `Actions: write` (+ implicit `Metadata: read`). Blast radius if leaked: trigger/cancel workflows on the code repo — cannot read or write code, cannot read other repos.

## Accepted residual risk (schedule removed)

User explicitly chose to drop the `schedule:` safety net. Consequence: if the s7bb-data dispatch job fails (expired token, GitHub API 5xx, runner outage), **that hour's deploy is skipped and only recovers on the next data commit** (~hourly — VM pushes hourly, confirmed from run history). Mitigations included in this plan instead of a cron fallback:
1. The dispatch step retries 3× with backoff on transient API failure.
2. A failed dispatch job is visible in the s7bb-data Actions tab (push-triggered runs are reliable, unlike `schedule:`).
3. Manual `workflow_dispatch` remains as the human escape hatch.
Re-adding a low-contention catch-up cron later is a one-line change if the residual risk proves unacceptable.

## File Structure

**Repo `s7bb/s7bb.github.io` (this repo):**
- Modify: `.github/workflows/build-site.yml` — remove the `schedule:` block (lines 9–10). No other change; `workflow_dispatch:` and `push:` stay.
- Modify: `CLAUDE.md` — architecture diagram + locked-decisions note (deploy is event-driven; dispatch token location).
- Modify: `CHANGELOG.md` — `[Unreleased]` entry.
- This plan file (already created): `docs/superpowers/plans/2026-05-16-data-commit-dispatch-deploy.md`.

**Repo `s7bb/s7bb-data` (separate repo — NOT in this worktree):**
- Create: `.github/workflows/dispatch-build.yml` — `on: push` → `workflow_dispatch` API call into `s7bb.github.io`.

**Manual (no file — operator action, documented in Task 3):**
- Fine-grained PAT + `DISPATCH_TOKEN` Actions secret in s7bb-data repo settings.

---

### Task 1: Remove the `schedule:` cron from build-site.yml

**Files:**
- Modify: `.github/workflows/build-site.yml:9-10`

- [ ] **Step 1: Confirm current trigger block**

Run: `sed -n '3,12p' .github/workflows/build-site.yml`
Expected output:
```
on:
  push:
    branches: [main]
    paths:
      - "site/**"
      - ".github/workflows/build-site.yml"
  schedule:
    - cron: "10 * * * *"  # after the VM's :00 hourly data push
  workflow_dispatch:
```

- [ ] **Step 2: Delete the two `schedule:` lines**

Edit `.github/workflows/build-site.yml`, remove exactly:
```yaml
  schedule:
    - cron: "10 * * * *"  # after the VM's :00 hourly data push
```
Resulting `on:` block must be:
```yaml
on:
  push:
    branches: [main]
    paths:
      - "site/**"
      - ".github/workflows/build-site.yml"
  workflow_dispatch:
```

- [ ] **Step 3: Validate YAML still parses**

Run: `python3 -c "import yaml,sys; d=yaml.safe_load(open('.github/workflows/build-site.yml')); print(sorted(d['true'].keys()) if 'true' in d else sorted(d['on'].keys()))"`
Expected: `['push', 'workflow_dispatch']`
(YAML 1.1 may parse the key `on` as boolean `True`; the command handles both. The point: `schedule` is gone, `push` + `workflow_dispatch` remain.)

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/build-site.yml
git commit -m "ci(pages): drop unreliable schedule cron; deploy via workflow_dispatch"
```

---

### Task 2: Add the dispatch workflow in the s7bb-data repo

**Files:**
- Create (in **s7bb-data** repo): `.github/workflows/dispatch-build.yml`

> Execution note: this task edits a different repository. If running inline, clone it first:
> `git clone https://github.com/s7bb/s7bb-data.git /tmp/s7bb-data && cd /tmp/s7bb-data`
> Commit + push there with a token that has `Contents: write` on s7bb-data (the operator's own credentials, **not** the bot PAT and **not** `DISPATCH_TOKEN`).

- [ ] **Step 1: Create `.github/workflows/dispatch-build.yml`**

Full file content (no placeholders):
```yaml
name: Dispatch site build

# A data commit landed on s7bb-data main. GitHub has no cross-repo push
# trigger, so this workflow calls the workflow_dispatch API of
# s7bb/s7bb.github.io to deploy the site immediately. Replaces the
# unreliable schedule cron that GitHub silently dropped under load.

on:
  push:
    branches: [main]
    paths-ignore:
      - ".github/**"   # don't self-trigger on edits to this workflow
  workflow_dispatch: {}  # manual re-trigger

permissions: {}          # no GITHUB_TOKEN scopes needed; we use DISPATCH_TOKEN

concurrency:
  group: dispatch-build
  cancel-in-progress: true

jobs:
  dispatch:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger build-site.yml in s7bb.github.io
        env:
          GH_TOKEN: ${{ secrets.DISPATCH_TOKEN }}
        run: |
          set -euo pipefail
          for attempt in 1 2 3; do
            if gh workflow run build-site.yml \
                 --repo s7bb/s7bb.github.io \
                 --ref main; then
              echo "dispatch ok (attempt $attempt)"
              exit 0
            fi
            echo "dispatch attempt $attempt failed; retrying in $((attempt*10))s" >&2
            sleep $((attempt*10))
          done
          echo "::error::failed to dispatch build-site.yml after 3 attempts" >&2
          exit 1
```

- [ ] **Step 2: Lint the workflow YAML**

Run (in the s7bb-data checkout): `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/dispatch-build.yml')); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit + push (in s7bb-data, operator credentials)**

```bash
git add .github/workflows/dispatch-build.yml
git commit -m "ci: dispatch s7bb.github.io build on data commit"
git push origin main
```

> ⚠️ This first push has `paths-ignore: .github/**`, so it will **not** self-trigger a dispatch. Good — the workflow only fires on real data commits (`latest.json`, `archive/*.json`).

---

### Task 3: Provision the cross-repo dispatch token (operator action)

**Files:** none — GitHub UI / `gh` operator action. Document the exact steps in the PR description and in CLAUDE.md (Task 4).

- [ ] **Step 1: Create a fine-grained PAT**

GitHub → Settings → Developer settings → Fine-grained tokens → Generate new token:
- **Resource owner:** `s7bb`
- **Repository access:** Only select repositories → **`s7bb/s7bb.github.io`** (this code repo, and only this one)
- **Repository permissions:** **Actions → Read and write**. Leave everything else "No access". (`Metadata: Read-only` is auto-selected and required — that is expected and harmless.)
- **Expiration:** 90 days (calendar-renewed; note in CLAUDE.md).

Verify it grants exactly `actions:write` + `metadata:read` and nothing for `contents`.

- [ ] **Step 2: Store it as an Actions secret in s7bb-data**

```bash
gh secret set DISPATCH_TOKEN --repo s7bb/s7bb-data --body '<paste-fine-grained-PAT>'
```
Verify:
```bash
gh secret list --repo s7bb/s7bb-data
```
Expected: a row `DISPATCH_TOKEN` is listed.

- [ ] **Step 3: Confirm the token cannot touch code (negative check)**

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer <fine-grained-PAT>" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/s7bb/s7bb.github.io/contents/README.md
```
Expected: `404` or `403` (no `contents` permission). A `200` means the token is over-scoped — regenerate with Actions-only.

- [ ] **Step 4: Confirm the token CAN dispatch (positive check)**

```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST \
  -H "Authorization: Bearer <fine-grained-PAT>" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/s7bb/s7bb.github.io/actions/workflows/build-site.yml/dispatches \
  -d '{"ref":"main"}'
```
Expected: `204` (dispatch accepted — a `build-site.yml` run with event `workflow_dispatch` should appear in this repo's Actions tab within ~10s).

---

### Task 4: Update CLAUDE.md and CHANGELOG.md

**Files:**
- Modify: `CLAUDE.md` (architecture diagram + locked decisions)
- Modify: `CHANGELOG.md` (`[Unreleased]`)

- [ ] **Step 1: Update the architecture diagram in CLAUDE.md**

Replace the last block of the architecture fenced diagram:
```
                     GitHub: s7bb/s7bb-data main updated
                       ↓
                     Actions build-site.yml checks out this repo +
                     s7bb-data, assembles site/dist, deploys gh-pages.
```
with:
```
                     GitHub: s7bb/s7bb-data main updated
                       ↓ (push → s7bb-data/.github/workflows/dispatch-build.yml)
                       ↓ (workflow_dispatch API, DISPATCH_TOKEN, Actions:write)
                     Actions build-site.yml (event: workflow_dispatch)
                     checks out this repo + s7bb-data, assembles
                     site/dist, deploys gh-pages. No schedule cron.
```

- [ ] **Step 2: Add a locked-decision bullet under "### Key decisions (locked)"**

Append this bullet:
```
- Site deploy is **event-driven, not scheduled**. GitHub `schedule:`
  cron is best-effort and was silently dropped under load, so it is
  removed. A `push`-triggered workflow in `s7bb/s7bb-data`
  (`dispatch-build.yml`) calls the `workflow_dispatch` API of this repo.
  Its token (`DISPATCH_TOKEN`, Actions secret in **s7bb-data**, not on
  the VM) is a fine-grained PAT scoped to `s7bb.github.io` with
  `Actions: write` only — it cannot modify code, preserving the
  "bot PAT has no access to this code repo" boundary. Renew the PAT
  before its 90-day expiry; an expired token silently stops deploys
  (visible as failed dispatch runs in the s7bb-data Actions tab).
```

- [ ] **Step 3: Add a CHANGELOG entry under `[Unreleased]`**

Insert under `## [Unreleased]`:
```markdown
## [Unreleased]

### Changed

- Site deploy is now triggered by each data commit (a `push`-triggered
  dispatch workflow in `s7bb/s7bb-data` calls this repo's
  `workflow_dispatch` API) instead of an hourly `schedule:` cron, which
  GitHub silently dropped under load (multi-hour gaps observed). The
  cross-repo dispatch token is `Actions: write`-only and lives in
  s7bb-data secrets, not on the VM — the VM's data-repo PAT is unchanged.
```

- [ ] **Step 4: Commit docs**

```bash
git add CLAUDE.md CHANGELOG.md docs/superpowers/plans/2026-05-16-data-commit-dispatch-deploy.md
git commit -m "docs: event-driven deploy via s7bb-data dispatch (no schedule cron)"
```

> Release note: this is `ci:` + `docs:` only — no `feat`/`fix`. Per CLAUDE.md "Post-merge release trigger", **no version bump / release** is required.

---

### Task 5: End-to-end verification

**Files:** none — live verification after Tasks 1–4 are merged and the token is set.

- [ ] **Step 1: Trigger a real data-path commit on s7bb-data**

Make a no-op-but-real change to a data-path file so `paths-ignore` does not skip it (operator credentials, in an s7bb-data checkout):
```bash
cd /tmp/s7bb-data
git pull
# touch the file's mtime via a trivial re-write that the next VM push will overwrite anyway:
python3 -c "import json,io; p='latest.json'; d=json.load(open(p)); json.dump(d, open(p,'w'), separators=(',',':'))"
git commit -am "chore: verify dispatch pipeline" || echo "no diff — instead push an empty-ish archive touch"
git push origin main
```

- [ ] **Step 2: Confirm the dispatch workflow ran in s7bb-data**

Run: `gh run list --repo s7bb/s7bb-data --workflow dispatch-build.yml --limit 1 --json status,conclusion,event,createdAt`
Expected: one run, `event:"push"`, `conclusion:"success"` within ~1 min of the push.

- [ ] **Step 3: Confirm build-site.yml fired in this repo with the right event**

Run: `gh run list --repo s7bb/s7bb.github.io --workflow build-site.yml --limit 1 --json event,status,conclusion,createdAt`
Expected: one run with `event:"workflow_dispatch"`, started within ~30s of Step 2, `conclusion` ultimately `success`.

- [ ] **Step 4: Confirm no scheduled runs can occur anymore**

Run: `gh workflow view build-site.yml --repo s7bb/s7bb.github.io --yaml | grep -c schedule || true`
Expected: `0` (no `schedule` key remains on the deployed workflow).

- [ ] **Step 5: Confirm the site actually redeployed**

Run: `curl -sI https://s7bb.github.io/ | head -1` and check the deployed `latest.json`:
`curl -s https://s7bb.github.io/data/latest.json | python3 -c "import sys,json; print(json.load(sys.stdin).get('generated_at') or list(json.load.__doc__ and {}))" 2>/dev/null || curl -sI https://s7bb.github.io/data/latest.json | grep -i last-modified`
Expected: HTTP `200`; `last-modified` / data timestamp newer than before Step 1.

---

## Self-Review

**1. Spec coverage:**
- "Deploy on data change" → Tasks 1+2 (push→dispatch→build). ✅
- "VM-triggered conceptually, but via s7bb-data CI (Option B)" → Task 2. ✅
- "Preserve locked VM↔code-repo boundary" → Task 3 (`Actions: write`-only token in s7bb-data, VM PAT untouched); negative check Step 3. ✅
- "Drop schedule entirely" → Task 1. ✅
- "Plan only, document both repos + token setup" → this document; Tasks 2 & 3 fully specify the s7bb-data half. ✅
- CLAUDE.md mandate: plan file committed → Task 4 Step 4. ✅
- CLAUDE.md mandate: docs/changelog updated → Task 4. ✅

**2. Placeholder scan:** No "TBD/TODO/handle edge cases". All YAML and commands are complete. `<paste-fine-grained-PAT>` / `<fine-grained-PAT>` are intentional operator-supplied secrets, not code placeholders.

**3. Type/name consistency:** Secret name `DISPATCH_TOKEN` consistent across Task 2 (`secrets.DISPATCH_TOKEN`), Task 3 (`gh secret set DISPATCH_TOKEN`), Task 4 (CLAUDE.md). Workflow filename `build-site.yml` and `dispatch-build.yml` consistent across all tasks. Trigger mechanism is `workflow_dispatch` everywhere (never `repository_dispatch`).

## Risks & Open Items

- **Token expiry (highest):** fine-grained PATs max 1 year; 90-day chosen. Expiry → silent deploy stop. Mitigated by visible failed dispatch runs + CLAUDE.md renewal note. Consider a GitHub App installation token (no expiry) as a future hardening.
- **No schedule fallback:** accepted by user. One lost dispatch = up to ~1h stale site. Re-adding `schedule: - cron: "37 * * * *"` (off-peak minute) is the documented escape if unacceptable.
- **s7bb-data is single-writer by the VM:** adding a `.github/workflows/` file there is a human commit on `main` and does not conflict with the bot (bot only writes `latest.json`/`archive/*`). The `paths-ignore: .github/**` prevents workflow edits from triggering dispatches.
- **Cross-repo dependency:** Task 2/3/5 require operator access to s7bb-data; cannot be completed from this repo's worktree alone.
