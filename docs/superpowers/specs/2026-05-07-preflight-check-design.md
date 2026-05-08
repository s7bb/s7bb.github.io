# Preflight Check Design

**Date:** 2026-05-07
**Status:** Draft — pending implementation
**Component:** `fetcher/` (Python service)

## Problem

When the `s7bb-fetcher` container starts on a fresh VM (or after a config change), several classes of misconfiguration silently degrade or break the service. They surface only when the next scheduled job runs — which can be up to an hour later for the export/push job — and the failure mode is buried in scheduler logs alongside successful fetches.

Common failure classes observed or anticipated:

1. **Bind-mount permissions.** The compose file mounts `./data` → `/data` and `.` → `/repo`. If host UID/GID and container UID don't agree (e.g., user changed `UID`/`GID` in `.env` without rebuilding, or removed the override entirely), writes silently fail or partial data is written.
2. **GitHub push misconfiguration.** A missing, expired, or wrongly-scoped `GITHUB_PAT` only surfaces when `pusher.push_data()` runs hourly. Wrong `GITHUB_REPO_SLUG` or unparseable origin URL has the same problem.
3. **Git "dubious ownership"** error. When the repo on the host is owned by a different UID than the container user, `git status` (and therefore the GitPython operations in `pusher.py`) refuses with `fatal: detected dubious ownership in repository at '/repo'`. This is reproducible and confusing to operators.
4. **SQLite database access.** The fetcher writes to `/data/s7bb.db`. If the file is corrupt (truncated container kill mid-write, manual edit), parent directory missing, or locked by another process, every fetch silently logs an exception.

We want startup-time validation that surfaces these problems immediately, with clear remediation messages, before the scheduler starts running jobs.

## Goals

- Detect misconfiguration at container start, not at first scheduled job.
- Distinguish unrecoverable misconfiguration (must block startup) from transient/external issues (warn but continue).
- Provide an operator-runnable diagnostic that does not start the scheduler.
- Keep the implementation small, testable, and dependency-light.

## Non-goals

- Auto-remediation (e.g., we do not add `safe.directory` to git config automatically — auto-fix masks the underlying mount/UID problem).
- Validating DB Timetables API credentials. The fetch job retries every 5 minutes and a transient network failure should not block startup. (Out of scope; could be added later as a soft check.)
- Replacing per-job error handling. Preflight is a startup gate, not a substitute for `_safe()` wrappers around scheduled jobs.

## Design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Failure mode | Mixed: hard-fail volumes/ownership/SQLite, soft-warn GitHub | Volume + DB problems are deploy-time misconfig and unrecoverable. GitHub reach can flap on transient network/API issues; we don't want to block fetch jobs because of a 5xx during startup. |
| GitHub check depth | API auth (`GET /repos/{slug}`) with PAT bearer | Catches bad PAT, expired token, wrong slug, missing repo access. Side-effect-free. Dry-run push would also test ruleset, but ruleset rejects only on real push, so dry-run isn't strictly stronger. |
| Volume check scope | Test write to `/data` and `/repo`, plus dubious-ownership detection on `/repo` | Pusher needs `/repo` write (stage + commit) before push. Read-only repo mount would only fail at the hourly push. |
| Code structure | New `preflight.py` module + new `s7bb-preflight` CLI entry, both calling the same `run()` | One implementation, two callers. Operators can run `docker compose run --rm s7bb-fetcher s7bb-preflight` to diagnose without starting the scheduler. |
| Auto-fix dubious ownership | No | Auto-fix hides the real problem (UID/mount mismatch). Better to fail loud with a remediation message that tells the operator to either fix mount ownership or set `GIT_SAFE_DIRECTORY=/repo`. |

## Checks

| # | Check | Severity | Mechanism |
|---|---|---|---|
| 1 | `/data` writable | hard | Create + delete temp file under `DATA_DIR`. |
| 2 | `/repo` writable, `.git` openable | hard | Create + delete temp file; `git.Repo(REPO_PATH)` succeeds. |
| 3 | Repo not flagged "dubious ownership" | hard | Run `repo.git.status()`; on `GitCommandError` matching `dubious ownership` in stderr, fail with remediation message. |
| 4 | SQLite DB accessible and valid | hard | `storage.open_db(DB_PATH)` (creates if missing) and `PRAGMA integrity_check` returning `ok`. |
| 5 | GitHub PAT + repo access | soft | `GET https://api.github.com/repos/{slug}` with `Authorization: Bearer $GITHUB_PAT` and `Accept: application/vnd.github+json`, 5s timeout, expect HTTP 200. Distinguish 401 / 403 / 404 in message. |

## Components

```
fetcher/src/s7bb_fetcher/preflight.py
├── Severity (Enum: HARD, SOFT)
├── Check (dataclass: name, severity, ok, message)
├── PreflightFailed (Exception)
├── _check_data_writable(data_dir: Path) -> Check
├── _check_repo_writable(repo_path: Path) -> Check
├── _check_repo_ownership(repo_path: Path) -> Check
├── _check_sqlite(db_path: Path) -> Check
├── _check_github(slug: str | None, token: str | None) -> Check
└── run(
      data_dir: Path,
      repo_path: Path,
      db_path: Path,
    ) -> list[Check]
```

`run()` invokes each check in order, returns the list. It does not raise. The caller decides what to do with the results (service raises `PreflightFailed`; CLI sets exit code).

`cli.py` gains a `preflight()` function wired to a new `[project.scripts]` entry `s7bb-preflight`.

`service.main()` calls `preflight.run()` before constructing the scheduler, logs each `Check` (INFO if ok, ERROR if hard-fail, WARNING if soft-fail), and raises `PreflightFailed` if any HARD check failed. The exception falls through to the process; combined with `restart: unless-stopped` in compose, this produces a visible crash loop until the operator fixes the configuration.

## Data flow

```
container start
  └─ service.main()
       ├─ preflight.run(DATA_DIR, REPO_PATH, DB_PATH)
       │    └─ [_check_data_writable, _check_repo_writable,
       │        _check_repo_ownership, _check_sqlite, _check_github]
       ├─ log each Check (INFO/WARNING/ERROR by severity + ok)
       ├─ if any HARD check failed: raise PreflightFailed → sys.exit(1)
       └─ scheduler.start()
```

CLI path:

```
$ s7bb-preflight
  └─ cli.preflight() → preflight.run(...)
       ├─ print formatted check table to stdout
       └─ exit 0 if all HARD passed (soft fails print warnings, do not affect exit code)
          exit 1 if any HARD failed
```

## Error handling

- Each `_check_*` wraps its work in `try/except Exception` and returns a `Check(ok=False, msg=...)` rather than propagating. The list returned by `run()` always reflects every check attempted.
- "Dubious ownership" detection: catch `git.exc.GitCommandError`, match `stderr` for the literal substring `dubious ownership`. Message: `"git refuses to use /repo: dubious ownership. Fix host mount ownership to match container user, or set GIT_SAFE_DIRECTORY=/repo in .env."` Other `GitCommandError`s pass the stderr through verbatim.
- GitHub failure modes:
  - PAT missing or empty → `Check(ok=False, severity=SOFT, msg="GITHUB_PAT not set; push will fail at next export")`
  - Origin URL unparseable and no `GITHUB_REPO_SLUG` → soft fail.
  - HTTP 401 → `"bad or expired GITHUB_PAT"`
  - HTTP 403 → `"GITHUB_PAT lacks contents:write or repo access"`
  - HTTP 404 → `"repo {slug} not found or PAT cannot see it"`
  - Network error / timeout → soft fail with the urllib error message.
- SQLite:
  - `sqlite3.DatabaseError` (corrupt header) → `"DB at {path} is not a valid SQLite database"`
  - `PermissionError` on parent dir → `"cannot create DB at {path}: permission denied"`
  - `PRAGMA integrity_check` returning anything other than `ok` → fail with the returned text.

## Logging

At service startup, before raising on hard failure:

```
INFO  s7bb_fetcher.preflight running 5 checks
INFO  s7bb_fetcher.preflight ✓ data_writable        /data is writable
INFO  s7bb_fetcher.preflight ✓ repo_writable        /repo is writable
INFO  s7bb_fetcher.preflight ✓ repo_ownership       git accepts /repo
ERROR s7bb_fetcher.preflight ✗ sqlite               DB at /data/s7bb.db is not a valid SQLite database
WARN  s7bb_fetcher.preflight ! github               bad or expired GITHUB_PAT
ERROR s7bb_fetcher.preflight 1 hard check failed; aborting startup
```

CLI output uses the same lines without the logger prefix.

## Testing

New file `fetcher/tests/test_preflight.py`. Each check tested in isolation with `tmp_path` and `unittest.mock` where needed:

- `test_data_writable_ok` — uses `tmp_path`.
- `test_data_writable_denied` — chmods directory to `0o500`.
- `test_repo_writable_ok` / `test_repo_writable_denied`.
- `test_repo_ownership_ok` — initialises a real local git repo in `tmp_path`.
- `test_repo_ownership_dubious` — patches `git.Repo` so `repo.git.status()` raises `GitCommandError` with stderr containing `dubious ownership`; asserts the remediation message is in the returned `Check.message`.
- `test_sqlite_ok` — fresh path, asserts file gets created and check passes.
- `test_sqlite_corrupt` — writes 16 bytes of garbage to the path, asserts hard fail with corruption message.
- `test_github_ok` / `test_github_bad_pat` / `test_github_no_access` / `test_github_404` / `test_github_network_error` — patch `urllib.request.urlopen` to return canned responses.
- `test_run_returns_all_checks_even_when_one_fails` — confirms `run()` does not short-circuit.
- `test_service_aborts_on_hard_fail` — patch `preflight.run` to return one hard failure; assert `service.main()` raises `PreflightFailed` before `scheduler.start()` is called.
- `test_service_continues_on_soft_fail` — patch with one soft failure; assert scheduler.add_job is reached.

## Files affected

- **New:** `fetcher/src/s7bb_fetcher/preflight.py`
- **New:** `fetcher/tests/test_preflight.py`
- **Modified:** `fetcher/src/s7bb_fetcher/service.py` — call `preflight.run()` at top of `main()`, raise on hard fail.
- **Modified:** `fetcher/src/s7bb_fetcher/cli.py` — add `preflight()` entry.
- **Modified:** `fetcher/pyproject.toml` — add `s7bb-preflight = "s7bb_fetcher.cli:preflight"` to `[project.scripts]`.
- **Modified:** `CHANGELOG.md` — `Added: preflight check at fetcher startup; new s7bb-preflight CLI for diagnostics.`
- **Modified:** `README.md` — short section under VM Setup documenting the new CLI command and what each check verifies.

## Out of scope (followups)

- DB Timetables API credential check (could be a future soft check).
- Auto-remediation of dubious ownership.
- Push dry-run as a strict-mode opt-in.
- Periodic re-running of preflight (e.g., once an hour) — not currently warranted; restart loop on hard failure is enough.
