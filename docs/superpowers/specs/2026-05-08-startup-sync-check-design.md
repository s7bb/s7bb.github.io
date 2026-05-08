# Startup sync check — design

**Date:** 2026-05-08
**Status:** Draft
**Author:** Martin Zehetmayer (with Claude Code)

## Context

The s7bb-fetcher VM commits `data/latest.json` once an hour via `_export_job`. If the
VM crashes between an export and a successful push, or if the push fails for any
reason and the service is restarted before the next hourly tick, the local
`data/latest.json` and the copy on `origin/main` diverge. The site (deployed from
`origin/main` via GitHub Pages) keeps showing stale data for up to an hour.

Conversely, if a different runner has pushed newer data while this VM was offline
(or if the local DB was rolled back from backup), the local `latest.json` may be
older than what is on `main`.

This spec adds a startup-time reconciliation step that brings local and remote
into sync immediately, before the scheduler starts.

## Goals

- On service startup, detect drift between `data/latest.json` (local) and
  `data/latest.json` on `origin/main`.
- If local is newer, push it now — don't wait up to an hour for the next
  `_export_job` tick.
- If remote is newer, pull the remote copy into the local working tree so the
  local file matches what the deployed site shows.
- Hard-fail startup if reconciliation cannot be completed (network, parse, or
  push errors), so an operator notices instead of running with hidden drift.

## Non-goals

- Not a multi-runner coordination mechanism. The deployment is a single VM by
  design; the "remote newer" path covers VM rebuilds and clock skew, not
  active-active replication.
- Not a substitute for the hourly `_export_job` push — the next scheduled tick
  still re-exports from SQLite and pushes if the DB has produced new data.
- Does not reconcile `data/archive/*.json`. Archives are append-only monthly
  files; the existing `_export_job` push is sufficient.

## Architecture

```
service.main()
    │
    ├── preflight.run()              (existing — read-only validation)
    ├── startup_sync.startup_sync()  (NEW — mutating: push or pull)
    └── scheduler.start()            (existing)
```

`startup_sync` is a new module in `fetcher/src/s7bb_fetcher/startup_sync.py`.

```
startup_sync()
    │
    ├── _read_local_generated_at(data_path)        → datetime | None
    ├── _fetch_remote(slug, timeout)               → (raw_bytes, datetime) | (None, None)  on 404
    ├── compare timestamps with ±60 s tolerance
    └── dispatch:  push  → pusher.push_data(repo_path)
                   pull  → atomic-write raw_bytes to data_path
                   noop  → log + return
```

The slug (`owner/repo`) is resolved by `pusher._resolve_slug(repo)`, which
already exists. No new env-var plumbing.

The push leg reuses `pusher.push_data` unchanged — it stages, commits, and
pushes via the existing PAT helper.

## Public interface

```python
# startup_sync.py

@dataclass(frozen=True)
class SyncResult:
    action: Literal["push", "pull", "noop"]
    local_generated_at: datetime | None
    remote_generated_at: datetime | None
    message: str

def startup_sync(
    repo_path: Path,
    data_path: Path,
    slug: str,
    *,
    timeout: float = 10.0,
    tolerance_seconds: float = 60.0,
) -> SyncResult:
    """Reconcile local data/latest.json with origin/main before scheduler starts.

    Raises on any failure that prevents reconciliation: network error,
    unparseable JSON, push failure, write failure. Caller should treat a raise
    as a hard startup failure.
    """
```

## Decision matrix

`L` = local `generated_at`, `R` = remote `generated_at`. Δ = `L − R` in seconds.

| Local         | Remote        | Condition          | Action  | Notes                                            |
|---------------|---------------|--------------------|---------|--------------------------------------------------|
| present       | present       | `Δ > +tolerance`   | push    | Local newer; push now.                           |
| present       | present       | `Δ < −tolerance`   | pull    | Remote newer; overwrite local with remote bytes. |
| present       | present       | `\|Δ\| ≤ tolerance` | noop    | Within clock-skew band; treat as in sync.        |
| present       | absent (404)  | —                  | push    | First-ever push case.                            |
| absent        | present       | —                  | pull    | Bootstrap local from remote.                     |
| absent        | absent (404)  | —                  | noop    | Empty install; export will produce file.         |

`tolerance_seconds = 60` prevents push/pull thrash when the two files were
written within ~1 minute of each other (e.g., committer wrote remote, then
local clock skew makes them appear inverted).

## Push leg

```python
def _push(repo_path: Path) -> None:
    pushed = pusher.push_data(repo_path)
    if not pushed:
        # generated_at differs but git tree clean — content identical
        # (e.g., only timestamps differ inside the JSON, no data drift).
        # Log and treat as success; don't raise.
        logger.warning(
            "startup_sync: local generated_at is newer but git working tree "
            "matches HEAD; nothing to commit"
        )
```

Any exception from `pusher.push_data` propagates → hard fail.

## Pull leg

```python
def _pull(data_path: Path, raw_bytes: bytes) -> None:
    """Atomically replace local data_path with raw_bytes from remote."""
    data_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{data_path.name}.", suffix=".tmp", dir=data_path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw_bytes)
        os.replace(tmp, data_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
```

Pull does **not** stage/commit. The local clone is the consumer; `origin/main`
is the source of truth for what the deployed site shows. Next `_export_job`
will rewrite `latest.json` from the local SQLite DB and push that.

## Remote fetch

```python
_RAW_URL_TMPL = "https://raw.githubusercontent.com/{slug}/main/data/latest.json"

def _fetch_remote(slug: str, timeout: float) -> tuple[bytes, datetime] | tuple[None, None]:
    url = _RAW_URL_TMPL.format(slug=slug)
    resp = requests.get(url, timeout=timeout)
    if resp.status_code == 404:
        return None, None
    resp.raise_for_status()  # raises on 5xx / other 4xx
    body = resp.content
    payload = json.loads(body)            # raises JSONDecodeError on garbage
    raw = payload["generated_at"]         # raises KeyError on missing field
    ts = datetime.fromisoformat(raw)      # raises ValueError on bad ISO
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return body, ts
```

The repo is public, so no auth header is needed. If the repo were ever made
private, this call would 404 and the design would need revisiting (out of
scope).

## Local read

```python
def _read_local_generated_at(path: Path) -> datetime | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_bytes())  # raises on garbage
    raw = payload["generated_at"]            # raises on missing field
    ts = datetime.fromisoformat(raw)         # raises on bad ISO
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts
```

A missing file is a normal bootstrap state. A corrupt file is a hard fail —
something is wrong locally and the operator should investigate before the
service overwrites it.

## Service integration

`service.py`, after the existing preflight loop, before `scheduler.start()`:

```python
from . import startup_sync

slug = pusher._resolve_slug(git.Repo(str(REPO_PATH)))   # or use existing helper
result = startup_sync.startup_sync(REPO_PATH, OUT_PATH, slug)
logger.info(
    "startup_sync: action=%s local=%s remote=%s — %s",
    result.action,
    result.local_generated_at,
    result.remote_generated_at,
    result.message,
)
```

If `startup_sync` raises, the existing top-level entrypoint exits non-zero and
systemd / docker-compose marks the unit as failed — same shape as
`PreflightFailed`.

## Error matrix

| Condition                                | Behavior      |
|------------------------------------------|---------------|
| Local file missing                       | continue (`L=None`) |
| Local JSON malformed / no `generated_at` | raise         |
| Local `generated_at` not parseable ISO   | raise         |
| Remote 404                               | continue (`R=None`) |
| Remote 5xx / 4xx (non-404)               | raise         |
| Network timeout / DNS / connect error    | raise         |
| Remote JSON malformed / no `generated_at`| raise         |
| Slug unresolvable                        | raise         |
| Push fails (auth, ruleset, network)      | raise         |
| Pull write fails (disk full, perms)      | raise         |

All `raise` paths cause `service.main()` to exit non-zero — startup hard-fails.

## Testing

New file: `fetcher/tests/test_startup_sync.py`. `requests.get` is monkey-patched
via `unittest.mock.patch` (no new test dependencies).

| # | Test                                | Asserts                                         |
|---|-------------------------------------|-------------------------------------------------|
| 1 | `local_newer_pushes`                | mocked remote 200 older → `pusher.push_data` called, `action == "push"` |
| 2 | `remote_newer_pulls`                | mocked remote 200 newer → local file equals remote body, `action == "pull"` |
| 3 | `equal_within_tolerance_noop`       | Δ = 30 s → no push, no overwrite, `action == "noop"`                  |
| 4 | `equal_outside_tolerance_pushes`    | Δ = 90 s, local newer → `action == "push"`                            |
| 5 | `remote_404_pushes`                 | 404 + local present → `action == "push"`                              |
| 6 | `no_local_remote_present_pulls`     | local absent + 200 → file written with remote bytes, `action == "pull"` |
| 7 | `no_local_no_remote_noop`           | local absent + 404 → no write, `action == "noop"`                     |
| 8 | `remote_500_raises`                 | mocked 500 → raises                                                    |
| 9 | `remote_timeout_raises`             | `requests.exceptions.Timeout` → raises                                 |
| 10| `remote_malformed_json_raises`      | 200 + non-JSON body → raises                                           |
| 11| `local_malformed_raises`            | local file with garbage → raises                                       |
| 12| `push_failure_propagates`           | `pusher.push_data` raises → propagates                                 |
| 13| `pull_clean_commit_warns_no_raise`  | local newer but `push_data` returns False → action stays `"push"`, warning logged, no raise |

## Logging

- INFO at entry: `startup_sync: checking drift against origin/main…`
- INFO at exit (success): `startup_sync: action=<a> local=<ts> remote=<ts> — <message>`
- WARNING when push leg finds clean tree
- ERROR before any raise, with the relevant exception detail

## Documentation

- `CHANGELOG.md` — `[Unreleased] / Added`: "Startup sync check: reconcile local
  `data/latest.json` with `origin/main` before the scheduler starts; push if
  local is newer, pull if remote is newer."
- `README.md` — under "VM Setup" or a new "Startup behavior" subsection,
  one paragraph explaining what runs on start (preflight → startup sync →
  scheduler) and what hard-fails.
- `CLAUDE.md` — no change; existing architecture diagram still applies.

## Out of scope

- Multi-runner coordination (last-write-wins is fine for single-VM).
- Reconciliation of `data/archive/*.json` (append-only, hourly export covers
  it).
- A flag to make startup sync best-effort (soft fail) — can be added later if
  flaky networks become a problem in practice.

## Open questions

None at design time. All clarifying questions resolved in the brainstorming
session.
