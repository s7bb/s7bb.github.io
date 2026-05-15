# Production /repo Data-Repo Wiring Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the production `s7bb-fetcher` container push schedule JSON to `s7bb/s7bb-data` instead of the code repo, with a HARD preflight guard against the misconfiguration.

**Architecture:** A new one-shot `s7bb-repo-init` compose service clones `s7bb/s7bb-data` into a named volume `s7bb-repo`; `s7bb-fetcher` mounts that volume at `/repo` and `depends_on` it (`service_completed_successfully`). The image still builds from `fetcher/` (build context unchanged). A new HARD preflight check `repo_identity` aborts startup if `/repo` looks like the code repo (`fetcher/` or `site/` present) or its origin disagrees with `GITHUB_REPO_SLUG`. This eliminates the manual VM cutover and the build-context/`/repo` tension entirely.

**Tech Stack:** Docker Compose, alpine/git, Python 3.11, GitPython, pytest, uv.

---

## Background — the defect being fixed

`docker-compose.yml` `s7bb-fetcher` mounts `.:/repo`. `.` is the **code repo** clone (`s7bb/s7bb.github.io`). Run as committed on `main@a39fca9`:

- `pusher._resolve_slug` parses origin → `s7bb/s7bb.github.io`; the bot stages `latest.json` + `archive/*.json` into the code-repo working tree, commits, and `git push s7bb/s7bb.github.io HEAD:refs/heads/main`.
- The bot PAT is now `s7bb-data`-only → every hourly push fails `401/403` (`PUSH_FAILED`), commits pile up in the code-repo tree, the published site goes stale.
- Even with a manual `GITHUB_REPO_SLUG=s7bb/s7bb-data` override, `/repo` is still the full code-repo clone, so `git push s7bb-data HEAD:refs/heads/main` pushes unrelated history → rejected (or, if forced, destroys s7bb-data). The override alone does **not** fix it.
- Preflight cannot catch this: `_check_github` is SOFT, no check asserts `/repo` identity, so a misconfigured prod boots clean and fails silently every hour.

This plan removes the manual VM cutover (old plan `2026-05-15-two-repo-data-split.md` Task 12) by self-provisioning `/repo` from compose.

## File Structure

- `docker-compose.yml` — add `s7bb-repo-init` service + `s7bb-repo` volume; repoint `s7bb-fetcher` `/repo` mount from the code-repo bind to the named volume; add `depends_on`.
- `fetcher/src/s7bb_fetcher/preflight.py` — add `_check_repo_identity`, wire into `run()` between `_check_repo_ownership` and `_check_sqlite`.
- `fetcher/tests/test_preflight.py` — new tests for `_check_repo_identity`; update `test_run_returns_all_checks` and `test_run_does_not_short_circuit` for the added check.
- `README.md` — §1 (no manual data clone), §3 (init ordering + restart semantics), Development note.
- `.env.example` — `GITHUB_PAT` and `GITHUB_REPO_SLUG` comments (post-split, identity-guard aware).
- `CLAUDE.md` — VM Setup (production) steps.
- `CHANGELOG.md` — `[Unreleased] → ### Fixed` entry.

Semver: this is a **`fix`** (corrects broken production wiring shipped in 0.5.0). Per CLAUDE.md post-merge trigger, cut **PATCH 0.5.1** after merge — that is a separate procedure, not a task in this plan.

---

### Task 0: Land the plan file

**Files:**
- Create: `docs/superpowers/plans/2026-05-15-prod-data-repo-wiring.md` (this file)

- [ ] **Step 1: Commit the plan**

```bash
git add docs/superpowers/plans/2026-05-15-prod-data-repo-wiring.md
git commit -m "docs: plan for production /repo data-repo wiring fix"
```

---

### Task 1: HARD preflight `repo_identity`

**Files:**
- Modify: `fetcher/src/s7bb_fetcher/preflight.py`
- Test: `fetcher/tests/test_preflight.py`

- [ ] **Step 1: Write the failing tests**

In `fetcher/tests/test_preflight.py`, add `_check_repo_identity` to the import block:

```python
from s7bb_fetcher.preflight import (
    Check,
    PreflightFailed,
    Severity,
    _check_data_writable,
    _check_github,
    _check_repo_identity,
    _check_repo_ownership,
    _check_repo_writable,
    _check_sqlite,
)
```

Append these tests (use the existing `_init_repo` helper; it creates a repo whose only tree entry is `README.md`, so no code-repo markers):

```python
def test_repo_identity_ok_flat_repo(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_REPO_SLUG", raising=False)
    _init_repo(tmp_path)
    c = _check_repo_identity(tmp_path)
    assert c.ok is True
    assert c.name == "repo_identity"
    assert c.severity is Severity.HARD


def test_repo_identity_rejects_code_repo_fetcher(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_REPO_SLUG", raising=False)
    _init_repo(tmp_path)
    (tmp_path / "fetcher").mkdir()
    c = _check_repo_identity(tmp_path)
    assert c.ok is False
    assert c.severity is Severity.HARD
    assert "fetcher/" in c.message


def test_repo_identity_rejects_code_repo_site(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_REPO_SLUG", raising=False)
    _init_repo(tmp_path)
    (tmp_path / "site").mkdir()
    c = _check_repo_identity(tmp_path)
    assert c.ok is False
    assert "site/" in c.message


def test_repo_identity_slug_mismatch(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    repo.create_remote("origin", url="https://github.com/s7bb/s7bb.github.io.git")
    monkeypatch.setenv("GITHUB_REPO_SLUG", "s7bb/s7bb-data")
    c = _check_repo_identity(tmp_path)
    assert c.ok is False
    assert "wrong repository" in c.message
    assert "s7bb/s7bb.github.io" in c.message


def test_repo_identity_slug_match(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    repo.create_remote("origin", url="https://github.com/s7bb/s7bb-data.git")
    monkeypatch.setenv("GITHUB_REPO_SLUG", "s7bb/s7bb-data")
    c = _check_repo_identity(tmp_path)
    assert c.ok is True
```

Update the two existing `run()` tests. Replace `test_run_returns_all_checks` and `test_run_does_not_short_circuit` with:

```python
def test_run_returns_all_checks(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_REPO_SLUG", raising=False)
    _init_repo(tmp_path)
    db = tmp_path / "s7bb.db"
    with patch("s7bb_fetcher.preflight._check_github",
               return_value=Check("github", Severity.SOFT, True, "ok")):
        results = preflight.run(
            data_dir=tmp_path, repo_path=tmp_path, db_path=db,
            github_slug="o/r", github_token="t",
        )
    names = [c.name for c in results]
    assert names == [
        "data_writable", "repo_writable", "repo_ownership",
        "repo_identity", "sqlite", "github",
    ]


def test_run_does_not_short_circuit(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_REPO_SLUG", raising=False)
    bad = tmp_path / "missing"
    with patch("s7bb_fetcher.preflight._check_github",
               return_value=Check("github", Severity.SOFT, False, "n/a")):
        results = preflight.run(
            data_dir=bad, repo_path=bad, db_path=bad / "x.db",
            github_slug=None, github_token=None,
        )
    assert len(results) == 6  # every check is attempted
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd fetcher && uv run pytest tests/test_preflight.py -q`
Expected: FAIL — `ImportError: cannot import name '_check_repo_identity'` (collection error).

- [ ] **Step 3: Implement `_check_repo_identity` and wire it into `run()`**

In `fetcher/src/s7bb_fetcher/preflight.py`, add this function immediately after `_check_repo_ownership` (it calls `_resolve_slug`, defined later in the module — resolved at call time, so ordering is fine):

```python
_CODE_REPO_MARKERS = ("fetcher", "site")


def _check_repo_identity(repo_path: Path) -> Check:
    """Assert /repo is the flat s7bb-data tree, not the code repo.

    Catches the misconfiguration where the code repo is mounted at
    REPO_PATH: the bot would then commit data files into the code
    working tree and push them to the wrong remote.
    """
    name = "repo_identity"
    for marker in _CODE_REPO_MARKERS:
        if (repo_path / marker).is_dir():
            return Check(
                name,
                Severity.HARD,
                False,
                f"{repo_path} contains '{marker}/' — looks like the code "
                f"repo. REPO_PATH must point at the flat s7bb-data clone "
                f"(latest.json at the root).",
            )
    override = os.environ.get("GITHUB_REPO_SLUG", "").strip()
    if override:
        actual = _resolve_slug(repo_path)
        if actual is not None and actual != override:
            return Check(
                name,
                Severity.HARD,
                False,
                f"{repo_path} origin resolves to {actual!r} but "
                f"GITHUB_REPO_SLUG={override!r} — REPO_PATH points at the "
                f"wrong repository.",
            )
    return Check(name, Severity.HARD, True, f"{repo_path} is the data repo")
```

Then in `run()`, insert the call between `_check_repo_ownership` and `_check_sqlite`:

```python
    return [
        _check_data_writable(data_dir),
        _check_repo_writable(repo_path),
        _check_repo_ownership(repo_path),
        _check_repo_identity(repo_path),
        _check_sqlite(db_path),
        _check_github(github_slug, github_token),
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd fetcher && uv run pytest tests/test_preflight.py -q`
Expected: PASS (all preflight tests, including the 5 new + 2 updated).

- [ ] **Step 5: Lint + full suite**

Run: `cd fetcher && uv run ruff check src tests && uv run pytest -q`
Expected: ruff clean; full suite green.

- [ ] **Step 6: Commit**

```bash
git add fetcher/src/s7bb_fetcher/preflight.py fetcher/tests/test_preflight.py
git commit -m "fix(fetcher): add repo_identity HARD preflight guard

Aborts startup if REPO_PATH contains fetcher/ or site/ (code repo
mounted) or its origin disagrees with GITHUB_REPO_SLUG. Previously this
misconfiguration booted clean and failed every hourly push silently."
```

---

### Task 2: Self-provision /repo from s7bb-data in compose

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Replace the `s7bb-fetcher` service and add `s7bb-repo-init`**

In `docker-compose.yml`, replace the entire `s7bb-fetcher:` service block (currently lines 2–17, ending at `REPO_PATH: /repo`) with:

```yaml
  # One-shot: clone/refresh the flat s7bb-data repo into the s7bb-repo
  # named volume so s7bb-fetcher pushes to the data repo, never the code
  # repo. Anonymous HTTPS clone (s7bb-data is public); the push itself
  # uses GITHUB_PAT via GIT_ASKPASS. Non-shallow so pushes never hit
  # shallow-clone edge cases. On restart, reset --hard origin/main
  # discards unpushed local bot commits — they are regenerated from the
  # persistent SQLite DB on the next export.
  s7bb-repo-init:
    image: alpine/git:latest
    environment:
      DATA_REPO_URL: https://github.com/s7bb/s7bb-data.git
    entrypoint: ["sh", "-c"]
    command:
      - |
        set -e
        if [ ! -d /repo-clone/.git ]; then
          git clone --branch main --single-branch "$$DATA_REPO_URL" /repo-clone
        else
          git -C /repo-clone fetch origin main
          git -C /repo-clone reset --hard origin/main
        fi
    volumes:
      - s7bb-repo:/repo-clone

  s7bb-fetcher:
    build:
      context: fetcher
      dockerfile: Dockerfile
    restart: unless-stopped
    env_file: .env
    # Run as container UID 0. In rootless nerdctl this maps to the host
    # invoking user, so the data bind mount and s7bb-repo volume preserve
    # ownership. Setting UID=1000 here would map to a sub-UID and break
    # write access.
    user: "0:0"
    depends_on:
      s7bb-repo-init:
        condition: service_completed_successfully
    volumes:
      - ./data:/data
      - s7bb-repo:/repo
    environment:
      DATA_DIR: /data
      REPO_PATH: /repo
```

Leave `s7bb-dev`, `s7bb-data-init`, and `s7bb-site-dev` unchanged.

- [ ] **Step 2: Add the `s7bb-repo` named volume**

Replace the `volumes:` block at the end of the file:

```yaml
volumes:
  s7bb-site-node-modules:
  s7bb-data-checkout:
```

with:

```yaml
volumes:
  s7bb-site-node-modules:
  s7bb-data-checkout:
  s7bb-repo:
```

- [ ] **Step 3: Validate the compose file structurally**

Run:

```bash
python3 -c "import yaml; d=yaml.safe_load(open('docker-compose.yml')); s=d['services']; assert 's7bb-repo-init' in s, 'init missing'; assert s['s7bb-fetcher']['volumes']==['./data:/data','s7bb-repo:/repo'], s['s7bb-fetcher']['volumes']; assert s['s7bb-fetcher']['depends_on']['s7bb-repo-init']['condition']=='service_completed_successfully'; assert 's7bb-repo' in d['volumes']; assert s['s7bb-fetcher']['build']['context']=='fetcher'; print('compose OK')"
```

Expected: `compose OK`.

- [ ] **Step 4: Validate with the docker CLI if available**

Run: `docker compose config -q && echo 'docker config OK' || echo 'docker CLI absent — relying on structural check'`
Expected: `docker config OK` if docker is installed; otherwise the fallback message (acceptable — Step 3 is the gate).

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "fix: provision /repo from s7bb-data clone, not the code repo

s7bb-fetcher mounted .:/repo (the code repo), so the bot would push
data to the wrong remote / fail under the s7bb-data-scoped PAT. New
one-shot s7bb-repo-init clones s7bb/s7bb-data into the s7bb-repo named
volume; s7bb-fetcher depends_on it and mounts it at /repo. Image still
builds from fetcher/. Removes the manual VM cutover."
```

---

### Task 3: Docs — README, .env.example, CLAUDE.md

**Files:**
- Modify: `README.md`, `.env.example`, `CLAUDE.md`

- [ ] **Step 1: README §1 — drop the manual data clone**

Replace the `### 1. Clone and configure` section body (from the heading through the ```` ``` ```` block ending in `s7bb/s7bb-data` `main`.`):

```markdown
### 1. Clone and configure

Clone this code repo (it carries `docker-compose.yml` and the fetcher
image source). The data-repo working tree at `/repo` is **provisioned
automatically** — `docker compose` runs a one-shot `s7bb-repo-init`
service that clones `s7bb/s7bb-data` into the `s7bb-repo` named volume
before `s7bb-fetcher` starts. You do **not** clone the data repo by hand.

```bash
git clone <repo-url> /opt/s7bb
cd /opt/s7bb
cp .env.example .env
```

`REPO_PATH=/repo` is the auto-provisioned s7bb-data clone (named volume
`s7bb-repo`). The DB and generated JSON live under `/data` (host
bind-mount, untracked). Each hourly cycle the exporter writes
`/data/{latest.json,archive/*.json}`, the service copies them into
`/repo` (flat, at the root), commits, and pushes to `s7bb/s7bb-data`
`main`.
```

- [ ] **Step 2: README §3 — init ordering + restart semantics**

In `### 3. Run the container (VM)`, replace the **Startup sequence.** paragraph with:

```markdown
**Startup sequence.** `s7bb-repo-init` runs first (clone, or `git fetch`
+ `reset --hard origin/main`) and must exit 0 before `s7bb-fetcher`
starts. A container restart discards any local bot commits that never
pushed — they are regenerated from the persistent SQLite DB on the next
export (single writer, so the remote is authoritative). `s7bb-service`
then runs preflight checks and a startup sync against the s7bb-data
`main`: if local `latest.json` is newer than the published copy it is
pushed immediately; if remote is newer, the remote bytes overwrite the
local file. The scheduler does not start until all succeed — any error
aborts startup so an operator notices the divergence.
```

- [ ] **Step 3: README Development — distinguish prod vs dev init**

At the end of the `### Local (Docker)` subsection, after the
`git clone --depth=1 https://github.com/s7bb/s7bb-data.git ./.data-checkout`
block, append:

```markdown

Production uses a separate one-shot `s7bb-repo-init` → `s7bb-repo`
volume, mounted **read-write** by `s7bb-fetcher` (it commits and
pushes). The `dev` profile's `s7bb-data-init` → `s7bb-data-checkout` is
**read-only** for the site container.
```

- [ ] **Step 4: README §5 — post-split ruleset paths/repo**

The push ruleset now protects `s7bb/s7bb-data` and its tree is flat
(no `data/` prefix). Replace the intro sentence:

```markdown
The VM authenticates to GitHub with a **fine-grained Personal Access Token (PAT)** scoped to a single repository, layered with a server-side **push ruleset** that restricts which paths the bot is allowed to write. Even if the PAT leaks, the ruleset still rejects any change outside `data/latest.json` and `data/archive/**`.
```

with:

```markdown
The VM authenticates to GitHub with a **fine-grained Personal Access Token (PAT)** scoped to `s7bb/s7bb-data` only, layered with a server-side **push ruleset** that restricts which paths the bot is allowed to write. Even if the PAT leaks, the ruleset still rejects any change outside `latest.json` and `archive/**`.
```

Replace the §5a allow-list:

```markdown
   - **Restrict file paths** → allow-list:
     - `data/latest.json`
     - `data/archive/**`
```

with:

```markdown
   - **Restrict file paths** → allow-list:
     - `latest.json`
     - `archive/**`
```

In §5b step 5, replace `select **only this repo**` with
`select **only `s7bb/s7bb-data`**`. In §5a step 1, the ruleset is
created in the **`s7bb/s7bb-data`** repo settings, not this code repo —
prefix the step with that clarification:
`Open **`s7bb/s7bb-data`** → Settings → Rules → Rulesets → New branch ruleset.`

- [ ] **Step 4b: README `## Data` — post-split paths**

The `## Data` table still shows pre-split `data/`-prefixed paths and
"committed hourly" wording. Replace the three table rows:

```markdown
| `data/s7bb.db` | SQLite database — **VM only, never committed**. Schema: [`documentation/database-schema.md`](documentation/database-schema.md) |
| `data/latest.json` | Last 7 days of arrivals + aggregates — committed hourly |
| `data/archive/YYYY-MM.json` | Monthly dumps — committed on the 1st of each month |
```

with:

```markdown
| `/data/s7bb.db` | SQLite database — **VM only, never committed**. Schema: [`documentation/database-schema.md`](documentation/database-schema.md) |
| `/data/latest.json` | Last 7 days of arrivals + aggregates — copied to the s7bb-data root and pushed hourly |
| `/data/archive/YYYY-MM.json` | Monthly dumps — pushed to s7bb-data `archive/` on the 1st of each month |
```

- [ ] **Step 4c: README — stale Actions-trigger + service name (code-review follow-ups)**

Code review found two README inaccuracies the two-repo rewrite makes
actively wrong. `build-site.yml` triggers on `push` (`site/**`,
`.github/workflows/build-site.yml`) + `schedule: "10 * * * *"` +
`workflow_dispatch` — never `data/**`.

In the "How it works" ASCII diagram, replace the line:

```
        ▼  GitHub Actions (triggered by push to data/**)
```

with:

```
        ▼  GitHub Actions (hourly cron :10, picks up VM's :00 push)
```

Replace the sentence immediately below the diagram:

```
The fetcher runs in a Docker container on a small VM and pushes `data/latest.json` hourly. GitHub Actions rebuilds and deploys the static site on every push.
```

with:

```
The fetcher runs in a Docker container on a small VM and pushes the schedule JSON hourly to `s7bb/s7bb-data`. GitHub Actions rebuilds and deploys the static site on an hourly schedule (and on site-code changes).
```

In README §3 startup-sequence paragraph, replace `` `s7bb-service` `` (the Python entrypoint name, inconsistent with the operator-facing `s7bb-fetcher` used everywhere else in §3) so the sentence reads `the `s7bb-fetcher` container then runs preflight checks and a startup sync against the s7bb-data `main`:` (keep the rest of the sentence unchanged).

- [ ] **Step 5: .env.example — fix post-split PAT/slug comments**

Replace the `GITHUB_PAT` comment block and the `GITHUB_REPO_SLUG` block:

```
# GitHub fine-grained Personal Access Token. Required for the hourly push of
# data/latest.json. Scope: repository = this repo only, Contents = Read and
# write (Metadata = Read auto-granted), all other permissions = No access.
# Server-side push ruleset on `main` further restricts allowed paths to
# data/latest.json and data/archive/**. See README §5 for the rotation flow.
GITHUB_PAT=github_pat_REPLACE_ME

# Optional: override the owner/repo slug used for the HTTPS push URL.
# Auto-detected from `origin` remote when unset; only set this if your
# clone uses a non-standard remote URL.
# GITHUB_REPO_SLUG=owner/s7bb
```

with:

```
# GitHub fine-grained Personal Access Token. Required for the hourly push
# to the s7bb-data repo. Scope: repository = s7bb/s7bb-data only,
# Contents = Read and write (Metadata = Read auto-granted), all other
# permissions = No access. The bot PAT has no access to the code repo.
# See README §5 for the rotation flow.
GITHUB_PAT=github_pat_REPLACE_ME

# Optional: override the owner/repo slug used for the HTTPS push URL.
# Auto-detected from the s7bb-data clone's `origin` (s7bb/s7bb-data) when
# unset. If set, the `repo_identity` preflight HARD-fails on mismatch —
# leave unset unless the auto-provisioned clone uses a non-standard URL.
# GITHUB_REPO_SLUG=s7bb/s7bb-data
```

- [ ] **Step 6: CLAUDE.md — VM Setup (production)**

Replace the `## VM Setup (production)` numbered list:

```markdown
## VM Setup (production)

1. Clone repo over HTTPS.
2. Copy `.env.example` → `.env`, fill in API credentials, `GITHUB_PAT` (see README §5), UID/GID.
3. `docker compose up -d s7bb-fetcher` — APScheduler runs fetch+export+push inside container.
```

with:

```markdown
## VM Setup (production)

1. Clone **this code repo** over HTTPS. The s7bb-data working tree at
   `/repo` is auto-provisioned by the `s7bb-repo-init` compose service
   (named volume `s7bb-repo`) — do not clone it by hand.
2. Copy `.env.example` → `.env`, fill in API credentials, `GITHUB_PAT` (see README §5), UID/GID.
3. `docker compose up -d s7bb-fetcher` — `s7bb-repo-init` clones/refreshes
   `s7bb/s7bb-data` first, then APScheduler runs fetch+export+push.
```

- [ ] **Step 7: Commit**

```bash
git add README.md .env.example CLAUDE.md
git commit -m "docs: production /repo auto-provisioned from s7bb-data

README §1/§3/Development, .env.example PAT+slug comments, CLAUDE.md VM
Setup updated for the s7bb-repo-init self-provisioning model; no manual
data clone or VM cutover."
```

---

### Task 4: CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the Fixed entry under `[Unreleased]`**

Replace:

```markdown
## [Unreleased]

## [0.5.0] - 2026-05-15
```

with:

```markdown
## [Unreleased]

### Fixed

- Production `docker-compose.yml` mounted the **code repo** at `/repo`
  (`.:/repo`): the bot would have committed data into the code working
  tree and pushed to the wrong remote, or failed every hourly push
  under the `s7bb-data`-scoped PAT. A new one-shot `s7bb-repo-init`
  service clones `s7bb/s7bb-data` into a named volume `s7bb-repo` that
  `s7bb-fetcher` mounts at `/repo` (`depends_on` →
  `service_completed_successfully`). The image still builds from
  `fetcher/`; no manual VM cutover or host repoint is needed.
- New HARD preflight `repo_identity` aborts startup if `/repo` contains
  `fetcher/` or `site/` (code repo mounted), or if its origin disagrees
  with `GITHUB_REPO_SLUG`. Previously this misconfiguration booted clean
  and failed silently every hour.

## [0.5.0] - 2026-05-15
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for production data-repo wiring fix"
```

---

### Task 5: Compose-wiring regression test (added from review feedback)

**Files:**
- Create: `fetcher/tests/test_compose_wiring.py`

**Rationale:** the defect was a compose misconfiguration (`s7bb-fetcher`
mounting `.:/repo`, the code repo). The `repo_identity` preflight
(Task 1) only catches it at container startup; nothing in the test
suite fails if the compose mount regresses. This adds a dependency-free
(stdlib-only — `pyyaml` is not a project dep) tripwire that asserts the
post-split wiring invariants and would have failed on the pre-fix
`docker-compose.yml`. Test-only, non-user-facing → no CHANGELOG entry
(CLAUDE.md: pure `test` changes do not trigger a release).

**Block-scoping note:** `.:/repo` is a *legitimate* mount on the
`s7bb-site-dev` service, so the "no `.:/repo`" assertion MUST be scoped
to the `s7bb-fetcher` service block only — a file-wide check would
false-fail. Extract the `s7bb-fetcher` block as the lines from
`^  s7bb-fetcher:$` up to (not including) the next top-level-2-space
key (`^  \S` or `^volumes:`/`^\S`).

- [ ] **Step 1: Write the test**

Create `fetcher/tests/test_compose_wiring.py`:

```python
"""Regression guard: docker-compose.yml must wire s7bb-fetcher's /repo
to the auto-provisioned s7bb-data clone, never the code repo.

The original production defect mounted `.:/repo` (the code repo) on
s7bb-fetcher. The repo_identity preflight catches it only at startup;
this fails CI the moment the compose mount regresses. Stdlib-only —
pyyaml is not a project dependency.
"""

import re
from pathlib import Path

import pytest

_COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def _service_block(text: str, name: str) -> str:
    """Return the lines of one 2-space-indented compose service block."""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln == f"  {name}:":
            start = i
            break
    assert start is not None, f"service {name!r} not found in docker-compose.yml"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        ln = lines[j]
        if ln and not ln[0].isspace():          # top-level key (e.g. volumes:)
            end = j
            break
        if re.match(r"  \S", ln) and not ln.startswith("   "):  # next service
            end = j
            break
    return "\n".join(lines[start:end])


@pytest.fixture(scope="module")
def compose_text() -> str:
    assert _COMPOSE.is_file(), f"{_COMPOSE} missing"
    return _COMPOSE.read_text()


def test_fetcher_does_not_mount_the_code_repo(compose_text):
    block = _service_block(compose_text, "s7bb-fetcher")
    # The exact defect: bind-mounting the code repo working tree at /repo.
    assert not re.search(r"^\s*-\s*\.:/repo\s*$", block, re.M), (
        "s7bb-fetcher mounts '.:/repo' — that is the CODE repo. It must "
        "mount the s7bb-repo named volume (the s7bb-data clone)."
    )


def test_fetcher_mounts_s7bb_repo_volume(compose_text):
    block = _service_block(compose_text, "s7bb-fetcher")
    assert re.search(r"^\s*-\s*s7bb-repo:/repo\s*$", block, re.M), (
        "s7bb-fetcher must mount 's7bb-repo:/repo'"
    )


def test_fetcher_depends_on_repo_init_completed(compose_text):
    block = _service_block(compose_text, "s7bb-fetcher")
    assert "depends_on:" in block
    assert "s7bb-repo-init:" in block
    assert "condition: service_completed_successfully" in block


def test_repo_init_service_and_volume_declared(compose_text):
    assert "\n  s7bb-repo-init:\n" in compose_text, "s7bb-repo-init service missing"
    init = _service_block(compose_text, "s7bb-repo-init")
    assert "s7bb-data.git" in init, "init must clone the s7bb-data repo"
    assert re.search(r"^\s*-\s*s7bb-repo:/repo-clone\s*$", init, re.M), (
        "s7bb-repo-init must populate the s7bb-repo volume at /repo-clone"
    )
    # top-level named volume must be declared
    vol = compose_text.split("\nvolumes:\n", 1)
    assert len(vol) == 2 and re.search(r"^\s+s7bb-repo:\s*$", vol[1], re.M), (
        "top-level 'volumes:' must declare s7bb-repo"
    )
```

- [ ] **Step 2: Prove the guard is real (historical red)**

Confirm the test would have FAILED on the pre-fix compose (the
`a39fca9` `docker-compose.yml`, which mounted `.:/repo` and had no
`s7bb-repo-init`). Run:

```bash
cd /home/lima.guest/aiworkshop/s7bb/.claude/worktrees/prod-data-repo-wiring
git show a39fca9:docker-compose.yml > /tmp/old-compose.yml
cd fetcher && uv run python -c "
import re, importlib.util
spec = importlib.util.spec_from_file_location('t', 'tests/test_compose_wiring.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
old = open('/tmp/old-compose.yml').read()
blk = m._service_block(old, 's7bb-fetcher')
assert re.search(r'^\s*-\s*\.:/repo\s*\$', blk, re.M), 'expected old compose to mount .:/repo'
assert not re.search(r'^\s*-\s*s7bb-repo:/repo\s*\$', blk, re.M)
assert '\n  s7bb-repo-init:\n' not in old
print('historical-red confirmed: guard catches the pre-fix defect')
"
rm -f /tmp/old-compose.yml
```

Expected: `historical-red confirmed: guard catches the pre-fix defect`.

- [ ] **Step 3: Green on current + full suite + lint**

```bash
cd /home/lima.guest/aiworkshop/s7bb/.claude/worktrees/prod-data-repo-wiring/fetcher
uv run pytest tests/test_compose_wiring.py -q   # 4 passed
uv run pytest -q                                # full suite green (152)
uv run ruff check src tests                     # clean
```

- [ ] **Step 4: Commit**

```bash
git add fetcher/tests/test_compose_wiring.py
git -c user.name="Martin Zehetmayer" -c user.email="angrox@idle.at" commit -m "test: regression guard for s7bb-fetcher /repo compose wiring

Fails if s7bb-fetcher ever bind-mounts .:/repo (the code repo) again
or loses the s7bb-repo-init dependency. Scoped to the s7bb-fetcher
block so the legitimate .:/repo on s7bb-site-dev does not false-fail.
Stdlib-only (pyyaml is not a project dep)."
```

---

## Self-Review

**Spec coverage:**
- Design error #1 (code repo mounted at `/repo`) → Task 2 (self-provision `s7bb-repo` volume + `depends_on`).
- Design error #2 (no prod provisioning) → Task 2 (`s7bb-repo-init`, non-profile, runs on `up`).
- Design error #3 (preflight can't catch it) → Task 1 (`repo_identity` HARD check).
- README/compose/.env.example contradictions → Task 3.
- Changelog/semver → Task 4 + post-merge PATCH 0.5.1 note (CLAUDE.md trigger).

**Placeholder scan:** No TBD/TODO/"handle edge cases"/uncoded steps — every code/diff step shows full content.

**Type consistency:** `_check_repo_identity(repo_path: Path) -> Check`; `_resolve_slug(repo_path)` is the existing preflight helper returning `str | None`; `run()` returns the 6-name list `["data_writable","repo_writable","repo_ownership","repo_identity","sqlite","github"]` and tests assert exactly that. `s7bb-repo` is the volume name everywhere (`/repo-clone` inside init, `/repo` inside fetcher).

**Post-merge (not a task here):** cut PATCH **0.5.1** per CLAUDE.md; then update memory `project_two_repo_split.md` — manual VM cutover (old plan Task 12) is obsoleted by `s7bb-repo-init`.
