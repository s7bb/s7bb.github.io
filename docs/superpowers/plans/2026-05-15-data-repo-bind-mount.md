# data-repo Host Bind Mount + Discard-Visibility Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the production s7bb-data clone (and the dev checkout) off Docker named volumes onto gitignored host bind mounts so `docker volume prune` cannot destroy them, and log a `WARN` when `s7bb-repo-init` discards unpushed local commits.

**Architecture:** Pure compose/test/docs change — no `s7bb_fetcher` source touched. `s7bb-repo-init` clones `s7bb/s7bb-data` into the host directory `./data-repo` (was named volume `s7bb-repo`); `s7bb-fetcher` mounts `./data-repo:/repo` (read-write). The dev `s7bb-data-init` clones into `./.data-checkout`; `s7bb-site-dev` mounts it `:ro`. `/data` (SQLite + exporter JSON) remains the single authoritative persistent source, so re-cloning `./data-repo` is always safe. The deliberate `reset --hard origin/main` is unchanged; a stderr `WARN` is added only when the local clone is ahead of origin.

**Tech Stack:** docker-compose (short-form bind mounts, `$$` compose escape for shell `$`), Python `pytest` (stdlib-only compose-wiring regression guard), Markdown docs.

---

## Architecture invariant (why this is safe — keep in mind while implementing)

- `/data` (`./data` host bind mount: `s7bb.db` + exporter `latest.json` / `archive/*.json`) is the single authoritative persistent source. `s7bb-repo-init` never mounts or touches `/data`.
- `/repo` is disposable staging. `pusher.push_data()` copies `/data` → `/repo`, commits, non-force pushes `HEAD:refs/heads/main`. Every `/repo` commit is byte-reconstructable from `/data`.
- `s7bb-repo-init`'s `reset --hard origin/main` is deliberate (guarantees the next non-force push is a fast-forward). The guard added here is **visibility only** — a stderr `WARN` — never a behavioral gate.

## File Structure

- `docker-compose.yml` — modify. Mount edits + drop two top-level named volumes + reword `s7bb-repo-init` header comment + add discard-`WARN` shell guard.
- `fetcher/tests/test_compose_wiring.py` — modify. Rewrite two assertions to the bind-mount form, add a WARN-guard regression test, update docstring. Security regex test stays byte-identical.
- `.gitignore` — modify. Add `/data-repo/`.
- `README.md` — modify. Three spots: §1 clone paragraph, the `REPO_PATH=/repo` paragraph, the dev section (~229–243).
- `CLAUDE.md` — modify. "VM Setup" §1.
- `CHANGELOG.md` — modify. New `### Fixed` entry under `[Unreleased]`.

## Regex-safety note (must hold — do not change the security test)

`test_fetcher_does_not_mount_the_code_repo` uses
`^\s*-\s*["']?\.\/?:/repo(?::[a-z]+)?["']?\s*$`. It requires `.` or `./`
**immediately** followed by `:/repo`. The new mounts:

- `./data-repo:/repo` — after `.` `/` the next char is `d`, not `:` → no match.
- `./data-repo:/repo-clone`, `./.data-checkout:/repo/data:ro` — same, no match.

So the security guard keeps rejecting only the historical `.:/repo`
code-repo defect and does not false-positive on the new binds. It stays
unmodified.

---

### Task 1: Commit the plan file

**Files:**
- Create: `docs/superpowers/plans/2026-05-15-data-repo-bind-mount.md` (this file — already written)

- [ ] **Step 1: Stage and commit the plan**

```bash
cd /home/lima.guest/aiworkshop/s7bb
git add docs/superpowers/plans/2026-05-15-data-repo-bind-mount.md
git commit -m "$(cat <<'EOF'
docs: plan — data-repo host bind mount + discard-visibility guard

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: one commit, plan file tracked.

---

### Task 2: Rewrite the compose-wiring regression guard (failing tests first)

**Files:**
- Modify: `fetcher/tests/test_compose_wiring.py` (full rewrite below — docstring + two rewritten tests + one new test; security test & helpers byte-identical)
- Test: `fetcher/tests/test_compose_wiring.py` itself is the test

- [ ] **Step 1: Replace the test file with the new content**

Write `fetcher/tests/test_compose_wiring.py` with exactly:

```python
"""Regression guard: docker-compose.yml must wire s7bb-fetcher's /repo
to the auto-provisioned s7bb-data clone, never the code repo.

The original production defect mounted `.:/repo` (the code repo) on
s7bb-fetcher. The repo_identity preflight catches it only at startup;
this fails CI the moment the compose mount regresses. Stdlib-only —
pyyaml is not a project dependency.

The s7bb-data clone now lives on a gitignored host bind mount
(`./data-repo:/repo`), not the former `s7bb-repo` named volume — a host
bind mount survives `docker volume prune`. These tests assert the
bind-mount wiring and that the discard-visibility WARN guard is present
in s7bb-repo-init.

Scope: guards the *short-form* bind of the code repo at /repo
(`.`/`./` -> /repo, any mode/quoting). Long-form `type: bind` mounts
are intentionally out of scope — the project only uses short-form and
parsing long-form reliably without a YAML lib is not worth the
fragility.
"""

import re
from pathlib import Path

import pytest

# Layout assumed: <repo>/fetcher/tests/test_compose_wiring.py
_COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"

# `.`/`./` -> /repo (the defect) in short form: optional quotes, "." or
# "./", optional :ro/:rw/:z mode. Catches the historical bare form AND
# its trivially-equivalent paraphrases.
_CODE_REPO_AT_REPO = re.compile(
    r"""^\s*-\s*["']?\.\/?:/repo(?::[a-z]+)?["']?\s*$""", re.M
)


def _service_block(text: str, name: str) -> str:
    """Return the lines of one 2-space-indented compose service block.

    Terminates at the next top-level key or the next 2-space-indented
    *service key*. Comments and deeper-indented lines do NOT end the
    block — a 2-space comment must not silently truncate it.
    """
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
        if ln and not ln[0].isspace():            # top-level key (e.g. volumes:)
            end = j
            break
        if (
            re.match(r"  \S", ln)
            and not ln.startswith("   ")
            and not ln.lstrip().startswith("#")   # 2-space comment != next service
        ):
            end = j
            break
    return "\n".join(lines[start:end])


@pytest.fixture(scope="module")
def compose_text() -> str:
    assert _COMPOSE.is_file(), f"{_COMPOSE} missing"
    return _COMPOSE.read_text().replace("\r\n", "\n")  # CRLF-safe


def test_fetcher_does_not_mount_the_code_repo(compose_text):
    block = _service_block(compose_text, "s7bb-fetcher")
    # The defect and its :ro/:rw/quoted paraphrases: bind-mounting the
    # code repo working tree at /repo.
    assert not _CODE_REPO_AT_REPO.search(block), (
        "s7bb-fetcher mounts the code repo at /repo ('.:/repo'). It must "
        "mount the ./data-repo host bind mount (the s7bb-data clone)."
    )


def test_fetcher_mounts_data_repo_bind(compose_text):
    block = _service_block(compose_text, "s7bb-fetcher")
    assert re.search(r"^\s*-\s*\./data-repo:/repo\s*$", block, re.M), (
        "s7bb-fetcher must mount './data-repo:/repo' (host bind mount)"
    )


def test_fetcher_depends_on_repo_init_completed(compose_text):
    block = _service_block(compose_text, "s7bb-fetcher")
    assert "depends_on:" in block, "s7bb-fetcher must declare depends_on"
    dep = block.split("depends_on:", 1)[1]
    assert "s7bb-repo-init:" in dep and "service_completed_successfully" in dep, (
        "s7bb-fetcher must depend_on s7bb-repo-init with "
        "condition: service_completed_successfully"
    )


def test_repo_init_clones_into_data_repo_bind(compose_text):
    assert re.search(r"^  s7bb-repo-init:\s*$", compose_text, re.M), (
        "s7bb-repo-init service missing"
    )
    init = _service_block(compose_text, "s7bb-repo-init")
    assert "s7bb-data.git" in init, "init must clone the s7bb-data repo"
    assert re.search(r"^\s*-\s*\./data-repo:/repo-clone\s*$", init, re.M), (
        "s7bb-repo-init must populate './data-repo:/repo-clone'"
    )
    m = re.search(r"^volumes:\s*$", compose_text, re.M)
    assert m, "top-level 'volumes:' block missing"
    assert not re.search(r"^\s+s7bb-repo:\s*$", compose_text[m.end():], re.M), (
        "top-level 'volumes:' must NOT declare s7bb-repo — the named "
        "volume was replaced by the ./data-repo host bind mount"
    )


def test_repo_init_warns_on_discard(compose_text):
    init = _service_block(compose_text, "s7bb-repo-init")
    assert "rev-list --count origin/main..HEAD" in init, (
        "s7bb-repo-init must count commits ahead of origin/main before reset"
    )
    assert "WARN: s7bb-repo-init discarding" in init, (
        "s7bb-repo-init must log a WARN when it discards unpushed commits"
    )
    assert "reset --hard origin/main" in init, (
        "s7bb-repo-init must still reset --hard origin/main (behavior unchanged)"
    )
```

- [ ] **Step 2: Run the suite to verify the new assertions fail against the still-old compose**

Run: `cd fetcher && uv run pytest tests/test_compose_wiring.py -v`

Expected: FAIL.
- `test_fetcher_mounts_data_repo_bind` FAILS (compose still has `s7bb-repo:/repo`).
- `test_repo_init_clones_into_data_repo_bind` FAILS (compose still has `s7bb-repo:/repo-clone` and a top-level `s7bb-repo:` volume).
- `test_repo_init_warns_on_discard` FAILS (no WARN/rev-list yet).
- `test_fetcher_does_not_mount_the_code_repo` and `test_fetcher_depends_on_repo_init_completed` PASS (unchanged).

This red state confirms the tests actually exercise the change.

---

### Task 3: Rewire docker-compose.yml to host bind mounts + add the WARN guard

**Files:**
- Modify: `docker-compose.yml` (full new content below)
- Test: `fetcher/tests/test_compose_wiring.py` (from Task 2)

- [ ] **Step 1: Replace `docker-compose.yml` with exactly this content**

Write `docker-compose.yml` with:

```yaml
services:
  # One-shot: clone/refresh the flat s7bb-data repo into the ./data-repo
  # host directory (bind-mounted, gitignored) so s7bb-fetcher pushes to
  # the data repo, never the code repo. A host bind mount survives
  # `docker volume prune`, unlike the former s7bb-repo named volume.
  # Anonymous HTTPS clone (s7bb-data is public); the push itself uses
  # GITHUB_PAT via GIT_ASKPASS. Non-shallow so pushes never hit
  # shallow-clone edge cases. On restart, reset --hard origin/main
  # discards unpushed local bot commits — they are regenerated from the
  # persistent SQLite DB on the next export, and the discard is now
  # logged at WARN.
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
          ahead=$$(git -C /repo-clone rev-list --count origin/main..HEAD 2>/dev/null || echo 0)
          if [ "$$ahead" -gt 0 ]; then
            behind=$$(git -C /repo-clone rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
            echo "WARN: s7bb-repo-init discarding $$ahead unpushed local commit(s) (behind=$$behind) via 'reset --hard origin/main'; data is reconstructable from persistent /data on the next export / startup_sync push" >&2
          fi
          git -C /repo-clone reset --hard origin/main
        fi
    volumes:
      - ./data-repo:/repo-clone

  s7bb-fetcher:
    build:
      context: fetcher
      dockerfile: Dockerfile
    restart: unless-stopped
    env_file: .env
    # Run as container UID 0. In rootless nerdctl this maps to the host
    # invoking user, so the ./data and ./data-repo bind mounts preserve
    # ownership. Setting UID=1000 here would map to a sub-UID and break
    # write access.
    user: "0:0"
    depends_on:
      s7bb-repo-init:
        condition: service_completed_successfully
    volumes:
      - ./data:/data
      - ./data-repo:/repo
    environment:
      DATA_DIR: /data
      REPO_PATH: /repo

  s7bb-dev:
    image: python:3.12-slim
    command: python3 -m http.server 8080 --directory /data
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data:ro
    profiles:
      - dev

  s7bb-data-init:
    image: alpine/git:latest
    profiles: [dev]
    environment:
      DATA_REPO_URL: https://github.com/s7bb/s7bb-data.git
    entrypoint: ["sh", "-c"]
    command:
      - |
        set -e
        if [ ! -d /data-checkout/.git ]; then
          git clone --branch main --single-branch --depth=1 \
            "$$DATA_REPO_URL" /data-checkout
        else
          git -C /data-checkout fetch --depth=1 origin main
          git -C /data-checkout reset --hard FETCH_HEAD
        fi
    volumes:
      - ./.data-checkout:/data-checkout

  s7bb-site-dev:
    image: node:20-alpine
    working_dir: /repo/site
    # Entrypoint derives VITE_DEV_NOW from data/latest.json's generated_at so
    # the today page treats the bundled data as "now" (it's filtered to the
    # viewer's current Europe/Berlin date in production).
    command: ["sh", "/repo/site/dev-entrypoint.sh"]
    ports:
      - "5173:5173"
    depends_on:
      s7bb-data-init:
        condition: service_completed_successfully
    volumes:
      - .:/repo
      # Data-repo tip, read-only, at the path dev-entrypoint.sh expects.
      - ./.data-checkout:/repo/data:ro
      # Anonymous volume overlays the bind mount so the entrypoint can
      # write a transformed latest.json into /repo/site/data without
      # leaking back into the host's site/ tree. Vite serves it under
      # /data/ (which is what fetch("../data/latest.json") resolves to).
      - /repo/site/data
      - s7bb-site-node-modules:/repo/site/node_modules
    profiles:
      - dev

volumes:
  s7bb-site-node-modules:
```

Notes for the implementer (do not add to the file):
- Every shell `$` is written `$$` (compose interpolation escape) — `$$DATA_REPO_URL`, `$$ahead`, `$$behind`, `$$(git …)`. Preserve exactly.
- `s7bb-site-dev` keeps `.:/repo` (it needs the code repo for the dev site — that is intentional and out of the security test's scope, which only inspects the `s7bb-fetcher` block).
- Because `s7bb-site-dev` binds `.:/repo`, `./.data-checkout` also surfaces at `/repo/.data-checkout`; the explicit `./.data-checkout:/repo/data:ro` overlay still wins for the path Vite reads — behaviorally identical to the named-volume version.
- Top-level `volumes:` now declares only `s7bb-site-node-modules:` (`s7bb-repo:` and `s7bb-data-checkout:` removed).

- [ ] **Step 2: Run the compose-wiring suite — now green**

Run: `cd fetcher && uv run pytest tests/test_compose_wiring.py -v`

Expected: PASS — all 5 tests:
- `test_fetcher_does_not_mount_the_code_repo` PASS
- `test_fetcher_mounts_data_repo_bind` PASS
- `test_fetcher_depends_on_repo_init_completed` PASS
- `test_repo_init_clones_into_data_repo_bind` PASS
- `test_repo_init_warns_on_discard` PASS

- [ ] **Step 3: (Manual / VM only — non-blocking) compose parse sanity**

If `docker compose` is available on the host:

Run: `docker compose config >/dev/null && echo OK`
Expected: `OK` (no YAML/interpolation error; `$$` collapses to `$` in the rendered command).

If docker is not installed in this environment, skip — the pytest guard above is the authoritative automated check; the parse is re-validated on the VM at deploy time (`docker compose up -d s7bb-fetcher`).

---

### Task 4: Add `/data-repo/` to `.gitignore`

**Files:**
- Modify: `.gitignore:38-39`

- [ ] **Step 1: Add the `/data-repo/` entry next to the existing data-checkout entry**

Edit `.gitignore` — replace:

```
# Optional host-side clone of the data repo for offline inspection
/.data-checkout/
```

with:

```
# Production s7bb-data clone working tree (host bind mount; untracked
# here — s7bb-data repo is the source of truth, same as /data/)
/data-repo/

# Optional host-side clone of the data repo for offline inspection
/.data-checkout/
```

- [ ] **Step 2: Verify the pattern ignores the directory**

Run: `git check-ignore -q data-repo && echo IGNORED`
Expected: `IGNORED`

- [ ] **Step 3: Verify nothing in `./data-repo` is staged accidentally**

Run: `git status --porcelain | grep -E '^\?\? data-repo/' || echo CLEAN`
Expected: `CLEAN` (the directory, if present from a local `docker compose up`, is ignored).

---

### Task 5: CHANGELOG `[Unreleased]` entry

**Files:**
- Modify: `CHANGELOG.md:8-10`

- [ ] **Step 1: Add the Fixed entry under `[Unreleased]`**

Edit `CHANGELOG.md` — replace:

```
## [Unreleased]

## [0.5.1] - 2026-05-15
```

with:

```
## [Unreleased]

### Fixed

- Production data-repo clone moved off the `s7bb-repo` Docker named
  volume onto a gitignored host bind mount `./data-repo` (the dev
  checkout likewise → `./.data-checkout`). A named volume is destroyed
  by `docker volume prune`; a host bind mount is not. Recovery was
  already automatic (remote `s7bb/s7bb-data` is authoritative, SQLite in
  `./data` regenerates the JSON), but the clone is no longer needlessly
  exposed and is now directly inspectable on the host. `s7bb-repo-init`
  additionally logs a `WARN` when its `reset --hard origin/main`
  discards unpushed local bot commits — observability only; the
  deliberate reset is unchanged and the data is reconstructable from the
  persistent `/data` on the next export / `startup_sync` push.

## [0.5.1] - 2026-05-15
```

- [ ] **Step 2: Commit the code change (compose + tests + gitignore + changelog) as one atomic fix**

```bash
cd /home/lima.guest/aiworkshop/s7bb
git add docker-compose.yml fetcher/tests/test_compose_wiring.py .gitignore CHANGELOG.md
git commit -m "$(cat <<'EOF'
fix(compose): bind-mount data-repo, drop named volumes, log discard

Move the production s7bb-data clone (and the dev checkout) off the
s7bb-repo / s7bb-data-checkout Docker named volumes onto gitignored
host bind mounts ./data-repo and ./.data-checkout. A named volume is
wiped by `docker volume prune`; a host bind mount is not. /data
(SQLite + exporter JSON) remains the single authoritative persistent
source, so re-cloning ./data-repo is always safe.

Add a stderr WARN in s7bb-repo-init when `reset --hard origin/main`
discards unpushed local commits (ahead>0). Observability only — the
deliberate reset and the fast-forward-push guarantee are unchanged.

Rewrite the compose-wiring regression guard to assert the bind-mount
wiring and the WARN guard; the security regex test is unchanged and
still rejects only the historical `.:/repo` code-repo defect.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: one commit; `git status` clean except for unrelated pre-existing untracked files.

---

### Task 6: Update docs (README + CLAUDE.md)

**Files:**
- Modify: `README.md` (three spots)
- Modify: `CLAUDE.md:81-83`

- [ ] **Step 1: README §1 — clone paragraph**

Edit `README.md` — replace:

```
Clone this code repo (it carries `docker-compose.yml` and the fetcher
image source). The data-repo working tree at `/repo` is **provisioned
automatically** — `docker compose` runs a one-shot `s7bb-repo-init`
service that clones `s7bb/s7bb-data` into the `s7bb-repo` named volume
before `s7bb-fetcher` starts. You do **not** clone the data repo by hand.
```

with:

```
Clone this code repo (it carries `docker-compose.yml` and the fetcher
image source). The data-repo working tree at `/repo` is **provisioned
automatically** — `docker compose` runs a one-shot `s7bb-repo-init`
service that clones `s7bb/s7bb-data` into the gitignored host directory
`./data-repo` (bind-mounted; survives `docker volume prune`) before
`s7bb-fetcher` starts. You do **not** clone the data repo by hand.
```

- [ ] **Step 2: README — `REPO_PATH=/repo` paragraph**

Edit `README.md` — replace:

```
`REPO_PATH=/repo` is the auto-provisioned s7bb-data clone (named volume
`s7bb-repo`). The DB and generated JSON live under `/data` (host
bind-mount, untracked). Each hourly cycle the exporter writes
`/data/{latest.json,archive/*.json}`, the service copies them into
`/repo` (flat, at the root), commits, and pushes to `s7bb/s7bb-data`
`main`.
```

with:

```
`REPO_PATH=/repo` is the auto-provisioned s7bb-data clone (host directory
`./data-repo`, bind-mounted, gitignored — survives `docker volume
prune`). The DB and generated JSON live under `/data` (host bind-mount,
untracked). Each hourly cycle the exporter writes
`/data/{latest.json,archive/*.json}`, the service copies them into
`/repo` (flat, at the root), commits, and pushes to `s7bb/s7bb-data`
`main`.
```

- [ ] **Step 3: README — dev section (~229–243)**

Edit `README.md` — replace:

```
`s7bb-data-init` clones the data repo into a named volume that
`s7bb-site-dev` mounts read-only at `/repo/data`. To refresh the
data-repo tip without restarting the site container:

    docker compose --profile dev run --rm s7bb-data-init

For editor inspection of the data outside Docker, clone it alongside the
repo (the path is gitignored):

    git clone --depth=1 https://github.com/s7bb/s7bb-data.git ./.data-checkout

Production uses a separate one-shot `s7bb-repo-init` → `s7bb-repo`
volume, mounted **read-write** by `s7bb-fetcher` (it commits and
pushes). The `dev` profile's `s7bb-data-init` → `s7bb-data-checkout` is
**read-only** for the site container.
```

with:

```
`s7bb-data-init` clones the data repo into the gitignored host directory
`./.data-checkout` (bind-mounted) that `s7bb-site-dev` mounts read-only
at `/repo/data`. To refresh the data-repo tip without restarting the
site container:

    docker compose --profile dev run --rm s7bb-data-init

For editor inspection of the data outside Docker, the same
`./.data-checkout` directory is already on the host (the path is
gitignored), or clone it yourself:

    git clone --depth=1 https://github.com/s7bb/s7bb-data.git ./.data-checkout

Production uses a separate one-shot `s7bb-repo-init` → `./data-repo`
host directory, mounted **read-write** by `s7bb-fetcher` (it commits and
pushes). The `dev` profile's `s7bb-data-init` → `./.data-checkout` is
**read-only** for the site container.
```

- [ ] **Step 4: CLAUDE.md — VM Setup §1**

Edit `CLAUDE.md` — replace:

```
1. Clone **this code repo** over HTTPS. The s7bb-data working tree at
   `/repo` is auto-provisioned by the `s7bb-repo-init` compose service
   (named volume `s7bb-repo`) — do not clone it by hand.
```

with:

```
1. Clone **this code repo** over HTTPS. The s7bb-data working tree at
   `/repo` is auto-provisioned by the `s7bb-repo-init` compose service
   (gitignored host bind mount `./data-repo`) — do not clone it by hand.
```

- [ ] **Step 5: Add the one-time VM migration note to README**

In `README.md`, immediately **after** the dev-section block edited in Step 3 (the paragraph ending `**read-only** for the site container.`), insert a new paragraph:

```

**One-time VM migration (0.5.1 → next):** after `git pull` and
`docker compose up -d`, `s7bb-repo-init` re-clones `s7bb/s7bb-data` into
`./data-repo` (remote is authoritative, SQLite in `./data` persists — no
data risk). The orphaned old named volumes may then be removed:

    docker volume rm s7bb-repo s7bb-data-checkout
```

(Place it as its own paragraph; do not merge it into the preceding text.)

- [ ] **Step 6: Commit the docs change**

```bash
cd /home/lima.guest/aiworkshop/s7bb
git add README.md CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: data-repo on host bind mount + VM migration note

README §1 / REPO_PATH / dev section and CLAUDE.md VM Setup §1 now
describe ./data-repo and ./.data-checkout host bind mounts instead of
the s7bb-repo / s7bb-data-checkout named volumes. Adds a one-time VM
migration note (re-clone is safe; orphaned volumes removable).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Full verification

**Files:** none modified — verification only.

- [ ] **Step 1: Full fetcher test suite**

Run: `cd fetcher && uv run pytest`
Expected: PASS, no failures (no `s7bb_fetcher` source changed; only compose/test/docs).

- [ ] **Step 2: Lint**

Run: `cd fetcher && uv run ruff check src tests`
Expected: `All checks passed!` (or no output, exit 0).

- [ ] **Step 3: Confirm working tree is clean**

Run: `cd /home/lima.guest/aiworkshop/s7bb && git status --porcelain`
Expected: only unrelated pre-existing untracked entries (`.claude/worktrees/`, `tmp/`, the two other untracked plan files `2026-05-14-orphan-data-branch.md`, `2026-05-15-freshness-badge.md`). No tracked file left modified or staged. Do **not** commit or delete those unrelated untracked files — they are out of scope for this plan.

- [ ] **Step 4: (Manual / VM only — non-blocking) end-to-end sanity**

On a host with docker, after deploy:
1. `docker compose up -d s7bb-fetcher` → `./data-repo` is auto-created on the host and `s7bb-repo-init` clones `s7bb/s7bb-data` into it; `s7bb-fetcher` mounts it at `/repo`.
2. Create a synthetic unpushed commit in `./data-repo` (`git -C ./data-repo commit --allow-empty -m test`), then `docker compose up -d --force-recreate s7bb-repo-init` → its logs show `WARN: s7bb-repo-init discarding 1 unpushed local commit(s) …` and the clone is reset to `origin/main`.

Skip if docker is unavailable here; Steps 1–3 are the authoritative automated gate.

---

## Post-merge release (per CLAUDE.md — not part of plan execution)

This is a `fix` with semver impact → after the PR merges to `main`, cut a **PATCH** release (0.5.1 → 0.5.2) following the CLAUDE.md Release procedure: bump `fetcher/pyproject.toml`, `uv sync --no-dev` in `fetcher/`, rename `[Unreleased]` → `[0.5.2] - <date>` in `CHANGELOG.md`, `chore(release): 0.5.2`, tag `v0.5.2`, push tag, create the GitHub Release. The added `WARN` is folded into this same `fix`.

---

## Self-Review

**1. Spec coverage**
- Goal 1 (prod clone → `./data-repo` bind mount): Task 3 (compose `s7bb-repo-init` + `s7bb-fetcher` mounts), Task 4 (`.gitignore`). ✅
- Goal 2 (dev `s7bb-data-checkout` → `./.data-checkout`): Task 3 (`s7bb-data-init` + `s7bb-site-dev` mounts). ✅ (`/.data-checkout/` already in `.gitignore` — no change needed, confirmed.)
- Goal 3 (loud WARN on discard, no behavior change): Task 3 shell guard; `set -e`-safe via `|| echo 0`; `$$` escaping documented; reset preserved. ✅
- Goal 4 (compose guard green & meaningful): Task 2 rewrite + new `test_repo_init_warns_on_discard`; security regex test unchanged (regex-safety note proves no false-positive). ✅
- Goal 5 (docs accurate): Task 6 (README ×3 + migration note, CLAUDE.md). ✅
- Non-goals respected: no `s7bb_fetcher` source change; no `${REPO_HOST_DIR}` env var; `s7bb-site-node-modules` named volume kept; `.env.example` untouched (`REPO_PATH=/repo` still correct — not in any task). ✅
- Spec §4 detail: `test_fetcher_does_not_mount_the_code_repo` and `test_fetcher_depends_on_repo_init_completed` kept byte-identical; the other two rewritten; docstring updated; top-level `s7bb-repo` negative assertion added. ✅
- Spec §5: CHANGELOG `fix` under `[Unreleased]` (Task 5); migration note in README (Task 6 Step 5); commit type `fix(compose)` (Task 5 Step 2); post-merge PATCH noted. ✅

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". Every code/edit step shows full literal content. ✅

**3. Type/string consistency:** Test function names referenced consistently (`test_fetcher_mounts_data_repo_bind`, `test_repo_init_clones_into_data_repo_bind`, `test_repo_init_warns_on_discard`). The WARN substring asserted in Task 2 (`"WARN: s7bb-repo-init discarding"`, `"rev-list --count origin/main..HEAD"`, `"reset --hard origin/main"`) matches the exact strings written into `docker-compose.yml` in Task 3. The regex `\./data-repo:/repo` (with escaped dot) matches the literal compose mount line. ✅
