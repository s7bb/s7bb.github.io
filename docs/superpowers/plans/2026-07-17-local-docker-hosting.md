# Local Docker Hosting (Phase 1: remote mode) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let anyone run the S7BB site locally with `docker compose up -d --build s7bb-site`, reading published data from the s7bb-data repo, with no credentials.

**Architecture:** A new multi-stage `site/Dockerfile` builds the Vite bundle and serves it with nginx. The data source is a runtime setting, not a build-time bake: the container entrypoint writes `config.json` from `S7BB_DATA_BASE_URL` at startup, and the site fetches that file at boot to learn its base URL. A new `dataBase()` helper collapses the three duplicated base-URL branches into one resolution path, falling back to today's behavior when no config exists so dev workflows are unaffected.

**Tech Stack:** TypeScript, Vite 8, Vitest 4, nginx (alpine), Node 22, Docker Compose, jq (in the site image, for JSON escaping).

**Spec:** `docs/superpowers/specs/2026-07-17-local-docker-hosting-design.md`

**Plan status:** revised after two independent reviews. Findings that were verified by
execution (not reasoning) are marked inline so you know which "Expected:" lines are
trustworthy.

## STOP: read before running any Docker command

This working copy has a real `.env` containing a **live, non-placeholder
`GITHUB_PAT`**, and today `s7bb-repo-init` / `s7bb-fetcher` carry **no compose
profile**, which means they start on a bare `docker compose up -d`.

Until Task 5 lands, running `docker compose up -d` in this repo starts the **production
fetcher**, which will push to `s7bb/s7bb-data` from your machine and break the
single-writer invariant in CLAUDE.md.

**Do not run a bare `docker compose up -d` at any point in this plan.** Always name the
service. Task 5 fixes this at the root by profiling the production services.

## Global Constraints

- **No em-dash.** Do not use "—" anywhere: UI text, docs, code comments, commit messages. Use a plain hyphen "-".
- **Exact dependency pinning.** All deps use `=X.Y.Z` exact versions. Pin Docker base images to a specific tag, never `latest`.
- **Conventional Commits.** Types: `feat`, `fix`, `docs`, `chore`, `refactor`, `perf`, `test`, `style`, `revert`. Subject imperative, lowercase, no trailing period, <=72 chars.
- **German UI, English code.** UI labels/strings in German; code, comments, and commit messages in English. The README is written in English; only quoted UI strings are German.
- **Node 22**, per `.nvmrc`.
- **No new npm dependencies.** Everything in this plan uses what is already installed.
- **Production services:** Task 5 adds `profiles: [fetcher]` to `s7bb-repo-init` and `s7bb-fetcher`. That is the only permitted change to them. Their behavior when started must stay identical, and the VM's `docker compose up -d s7bb-fetcher` must keep working. Do not touch the `dev` profile services at all.
- This is **phase 1 only**: remote mode. Do not implement `S7BB_PUSH_ENABLED`, preflight rework, or `s7bb-seed`.
- **No auto-refresh.** The site fetches once per page load; `main.ts:34-37` memoizes `liveData` and there is no timer. This is deliberate for phase 1. Do not add one, and do not claim otherwise in docs.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `site/src/config.ts` | Create | Resolve the data base URL. Pure `resolveBase()` + cached async `dataBase()`. |
| `site/src/config.test.ts` | Create | Unit tests for resolution order and fallback. |
| `site/src/data.ts` | Modify (`:54-61`) | Use `dataBase()` instead of its own branch. |
| `site/src/archive.ts` | Modify (`:39-43`) | Same. `archiveBase()` becomes async. |
| `site/src/pages/archive-detail.ts` | Modify (`:10-14`, `:92`) | Same. `archiveJsonUrl()` becomes a pure fn taking `base`. |
| `site/src/archive.test.ts` | Modify (`:29-32`) | Prime the config cache so fetch counts stay accurate. |
| `site/src/pages/archive-list.test.ts` | Modify (`:25-28`) | Prime the config cache. Without this the shared Response body is drained. |
| `site/src/pages/archive-detail.test.ts` | Modify (`:79-82`) | Same. |
| `site/nginx.conf` | Create | Serve static assets; `no-store` on config.json. |
| `site/docker-entrypoint.sh` | Create | Write config.json from env; validate; warn on missing local data; chain to nginx init. |
| `site/test-entrypoint.sh` | Create | Plain-sh tests for the entrypoint. No framework, no new deps. |
| `site/Dockerfile` | Create | Multi-stage node build -> nginx serve. |
| `site/.dockerignore` | Create | Keep `node_modules/` out of the build context. |
| `docker-compose.yml` | Modify | Add `s7bb-site`; add `profiles: [fetcher]` to the two production services. |
| `.env.example` | Modify | Add the paired config block; fix the stale README pointer (Task 0). |
| `README.md` | Modify | New "Run it locally with Docker" section; reconcile with the existing `:21-23` note. |
| `CHANGELOG.md` | Modify | Entry under `[Unreleased]`. |
| `CLAUDE.md` | Modify | Local-hosting architecture note; audience note. |
| `.github/workflows/ci.yml` | Modify | Run vitest; build the site image; run the entrypoint tests. |

---

## Task 0: Branch, and fix the stale README pointer

The `.env.example` fix is unrelated to this feature but is a known defect recorded in
the spec: PR #78 renumbered README section 5 to 4 and missed this file. Doing it first
keeps it out of the feature diff.

**Files:**
- Modify: `.env.example`

**Interfaces:**
- Consumes: nothing
- Produces: branch `feat/local-docker-hosting`

- [ ] **Step 1: Create the feature branch**

The spec and this plan are committed on `docs/local-docker-hosting-spec`. Branch the
feature from there so the spec travels with it:

```bash
git checkout docs/local-docker-hosting-spec
git checkout -b feat/local-docker-hosting
git branch --show-current
```

Expected: `feat/local-docker-hosting`

- [ ] **Step 2: Confirm the stale pointer exists**

Run: `grep -n "README §" .env.example`
Expected: one line reading `# See README §5 for the rotation flow.`

- [ ] **Step 3: Fix it**

In `.env.example`, change:

```
# See README §5 for the rotation flow.
```

to:

```
# See README §4 for the rotation flow.
```

- [ ] **Step 4: Verify the fix landed**

Run: `grep -c "README §5" .env.example`
Expected: `0`

Scope the check to this file. A repo-wide grep for "README §5" returns 9 hits in
`docs/` (this plan, the spec, and an older plan quoting the same text). Those are
historical records and must not be edited.

- [ ] **Step 5: Commit**

```bash
git add .env.example
git commit -m "docs: fix stale README section pointer in .env.example"
```

---

## Task 1: `dataBase()` config resolution

The core of the feature. A pure `resolveBase()` holds all the decision logic so tests
need no `import.meta.env` stubbing, and a thin `dataBase()` wrapper does the fetch.

**Files:**
- Create: `site/src/config.ts`
- Test: `site/src/config.test.ts`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `resolveBase(s: BaseSources): string`
  - `dataBase(): Promise<string>` - cached; returns base URL with no trailing slash
  - `_resetConfigCache(): void` - test helper
  - `_primeDataBase(base: string): void` - test helper; sets the cache without fetching
  - `interface BaseSources { configValue: unknown; viteValue: string | undefined; dev: boolean; baseUrl: string }`

**Verified:** `import.meta.env.DEV` is **true** under this repo's vitest (probed:
`DEV=true PROD=false MODE="test" BASE_URL="/"`). The tests below account for that. Do
not try to stub `DEV`; `resolveBase` covers the prod branch purely via `dev: false`.

- [ ] **Step 1: Write the failing test**

Create `site/src/config.test.ts`:

```typescript
import { describe, it, expect, beforeEach, vi } from "vitest";
import { resolveBase, dataBase, _resetConfigCache } from "./config.js";

beforeEach(() => {
  _resetConfigCache();
  vi.restoreAllMocks();
});

describe("resolveBase", () => {
  const dflt = { configValue: undefined, viteValue: undefined, dev: false, baseUrl: "/" };

  it("prefers config.json over everything", () => {
    expect(resolveBase({ ...dflt, configValue: "https://cdn.example/d", viteValue: "/vite" }))
      .toBe("https://cdn.example/d");
  });

  it("falls back to the vite var when config is absent", () => {
    expect(resolveBase({ ...dflt, viteValue: "/vite" })).toBe("/vite");
  });

  it("falls back to the built-in default in prod", () => {
    expect(resolveBase(dflt)).toBe("/data");
  });

  it("falls back to the relative path in dev", () => {
    expect(resolveBase({ ...dflt, dev: true })).toBe("../data");
  });

  it("ignores a non-string config value", () => {
    expect(resolveBase({ ...dflt, configValue: 42 })).toBe("/data");
  });

  it("ignores an empty or whitespace config value", () => {
    expect(resolveBase({ ...dflt, configValue: "   " })).toBe("/data");
  });

  it("strips a trailing slash so callers can always append /latest.json", () => {
    expect(resolveBase({ ...dflt, configValue: "https://cdn.example/d/" }))
      .toBe("https://cdn.example/d");
  });

  it("respects a non-root baseUrl", () => {
    expect(resolveBase({ ...dflt, baseUrl: "/s7bb/" })).toBe("/s7bb/data");
  });
});

// These exercise dataBase() end to end. Vitest sets import.meta.env.DEV = true, so
// every fallback here resolves to the dev path "../data".
describe("dataBase", () => {
  it("uses dataBaseUrl from config.json when present", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ dataBaseUrl: "https://cdn.example/d" }), { status: 200 }) as Response,
    );
    expect(await dataBase()).toBe("https://cdn.example/d");
  });

  it("falls back silently when config.json is missing", async () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("not found", { status: 404 }) as Response,
    );
    expect(await dataBase()).toBe("../data");
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("falls back silently when config.json is not JSON", async () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("<!doctype html><html></html>", { status: 200 }) as Response,
    );
    expect(await dataBase()).toBe("../data");
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("falls back silently when the fetch itself rejects", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("network down"));
    expect(await dataBase()).toBe("../data");
  });

  it("fetches config.json only once across calls", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ dataBaseUrl: "/data" }), { status: 200 }) as Response,
    );
    await dataBase();
    await dataBase();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd site && npx vitest run src/config.test.ts`
Expected: FAIL. Cannot find module `./config.js`.

- [ ] **Step 3: Write the implementation**

Create `site/src/config.ts`:

```typescript
// Resolves where the site reads its JSON from.
//
// The base URL is a runtime setting: the container entrypoint writes
// config.json at startup, so switching data source needs a restart, not a
// rebuild. Falls back to the build-time default when no config.json exists,
// which is the normal case for `npm run dev` and the dev compose profile.
//
// VITE_DATA_BASE_URL is a build-time escape hatch for anyone building the
// bundle outside Docker. Nothing in this repo sets it; the container uses
// config.json instead.

export interface BaseSources {
  configValue: unknown;
  viteValue: string | undefined;
  dev: boolean;
  baseUrl: string;
}

function stripTrailingSlash(u: string): string {
  return u.endsWith("/") ? u.slice(0, -1) : u;
}

function usable(v: unknown): v is string {
  return typeof v === "string" && v.trim() !== "";
}

export function resolveBase(s: BaseSources): string {
  if (usable(s.configValue)) return stripTrailingSlash(s.configValue.trim());
  if (usable(s.viteValue)) return stripTrailingSlash(s.viteValue.trim());
  return s.dev ? "../data" : stripTrailingSlash(`${s.baseUrl}data`);
}

let _baseCache: Promise<string> | null = null;

export function _resetConfigCache(): void {
  _baseCache = null;
}

// Test helper: set the base without a config.json round-trip. Tests that mock
// fetch with a single shared Response need this, otherwise dataBase() drains
// the body before the code under test can read it.
export function _primeDataBase(base: string): void {
  _baseCache = Promise.resolve(base);
}

export function dataBase(): Promise<string> {
  if (!_baseCache) {
    _baseCache = (async () => {
      let configValue: unknown;
      try {
        const resp = await fetch(`${import.meta.env.BASE_URL}config.json`);
        if (resp.ok) {
          const cfg = (await resp.json()) as { dataBaseUrl?: unknown };
          configValue = cfg?.dataBaseUrl;
        }
      } catch {
        // No config.json, or it is not JSON. Normal in dev and in a plain
        // `npm run preview`. Fall through to the build-time default; this is
        // not an error and must not be logged as one.
      }
      return resolveBase({
        configValue,
        viteValue: import.meta.env.VITE_DATA_BASE_URL as string | undefined,
        dev: import.meta.env.DEV,
        baseUrl: import.meta.env.BASE_URL,
      });
    })();
  }
  return _baseCache;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd site && npx vitest run src/config.test.ts`
Expected: **PASS, 13 tests** (8 `resolveBase` + 5 `dataBase`).

- [ ] **Step 5: Lint and type-check**

Run: `cd site && npm run lint && npx tsc --noEmit`
Expected: both exit 0.

- [ ] **Step 6: Commit**

```bash
git add site/src/config.ts site/src/config.test.ts
git commit -m "feat(site): add runtime data-source config resolution"
```

---

## Task 2: Wire the three call sites to `dataBase()`

**Files:**
- Modify: `site/src/data.ts:54-61`
- Modify: `site/src/archive.ts:39-43`, `:45-77`
- Modify: `site/src/pages/archive-detail.ts:10-14`, `:43`, `:92`
- Modify: `site/src/archive.test.ts:1-2`, `:29-32`
- Modify: `site/src/pages/archive-list.test.ts:1-3`, `:25-28`
- Modify: `site/src/pages/archive-detail.test.ts:1-3`, `:79-82`

**Interfaces:**
- Consumes: `dataBase()`, `_primeDataBase()` from Task 1
- Produces:
  - `archiveBase(): Promise<string>` (was sync)
  - `archiveJsonUrl(base: string, period: string): string` (was `(period: string)`)

**Why three test files change.** `dataBase()` adds a `config.json` fetch before the
first data fetch. Two distinct problems follow, and both were confirmed by running the
suite:

1. `archive.test.ts` asserts exact fetch counts (1, 1, 2). An extra fetch breaks them.
2. `archive-list.test.ts` and `archive-detail.test.ts` mock fetch with
   `mockResolvedValue(new Response(...))`, which returns **the same Response instance**
   every call. A Response body can only be read once, so `dataBase()` drains it and the
   code under test gets `Body is unusable: Body has already been read`.

Priming the cache fixes both: no config fetch happens, so counts and bodies are
untouched.

- [ ] **Step 1: Prime the config cache in all three affected test files**

In `site/src/archive.test.ts`, add the import after line 2:

```typescript
import { _primeDataBase } from "./config.js";
```

and change the `beforeEach` (lines 29-32) to:

```typescript
beforeEach(() => {
  _resetCache();
  _primeDataBase("../data");
  vi.restoreAllMocks();
});
```

In `site/src/pages/archive-list.test.ts`, add the import after line 3:

```typescript
import { _primeDataBase } from "../config.js";
```

and change its `beforeEach` (lines 25-28) to:

```typescript
beforeEach(() => {
  _resetCache();
  _primeDataBase("../data");
  vi.restoreAllMocks();
});
```

In `site/src/pages/archive-detail.test.ts`, add the import after line 3:

```typescript
import { _primeDataBase } from "../config.js";
```

and change the `beforeEach` inside the `describe("renderArchiveDetail hostile JSON")`
block (lines 79-82) to:

```typescript
  beforeEach(() => {
    _resetCache();
    _primeDataBase("../data");
    vi.restoreAllMocks();
  });
```

- [ ] **Step 2: Run the suite to confirm it is still green before the refactor**

Run: `cd site && npx vitest run`
Expected: **PASS, 9 files, 110 tests.** Priming is inert until Step 4 changes the
source; this step only prevents a false failure later. It is not a red-green step.

- [ ] **Step 3: Update `site/src/data.ts`**

Add the import at the top of the file:

```typescript
import { dataBase } from "./config.js";
```

Replace lines 54-61:

```typescript
export async function loadData(): Promise<S7Data> {
  const url = import.meta.env.DEV
    ? "../data/latest.json"
    : `${import.meta.env.BASE_URL}data/latest.json`;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Failed to load data: ${resp.status}`);
  return resp.json() as Promise<S7Data>;
}
```

with:

```typescript
export async function loadData(): Promise<S7Data> {
  const url = `${await dataBase()}/latest.json`;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Failed to load data: ${resp.status}`);
  return resp.json() as Promise<S7Data>;
}
```

- [ ] **Step 4: Update `site/src/archive.ts`**

Add the import at the top:

```typescript
import { dataBase } from "./config.js";
```

Replace lines 39-43:

```typescript
function archiveBase(): string {
  return import.meta.env.DEV
    ? "../data/archive"
    : `${import.meta.env.BASE_URL}data/archive`;
}
```

with:

```typescript
async function archiveBase(): Promise<string> {
  return `${await dataBase()}/archive`;
}
```

Then update its two call sites. In `loadIndex`, change:

```typescript
      const url = `${archiveBase()}/index.json`;
```

to:

```typescript
      const url = `${await archiveBase()}/index.json`;
```

In `loadMonth`, change:

```typescript
      const url = `${archiveBase()}/${period}.json`;
```

to:

```typescript
      const url = `${await archiveBase()}/${period}.json`;
```

Both are already inside `async` IIFEs, so no signature changes are needed.

- [ ] **Step 5: Update `site/src/pages/archive-detail.ts`**

Add the import at the top:

```typescript
import { dataBase } from "../config.js";
```

Replace lines 10-14:

```typescript
function archiveJsonUrl(period: string): string {
  return import.meta.env.DEV
    ? `../data/archive/${period}.json`
    : `${import.meta.env.BASE_URL}data/archive/${period}.json`;
}
```

with:

```typescript
function archiveJsonUrl(base: string, period: string): string {
  return `${base}/archive/${period}.json`;
}
```

In `renderArchiveDetail` (line 43), resolve the base once near the top of the function
body, before the template literal that uses it:

```typescript
  const base = await dataBase();
```

Then change line 92 from:

```typescript
      <a href="${archiveJsonUrl(period)}" download>Rohdaten herunterladen (JSON)</a>
```

to:

```typescript
      <a href="${escapeHtml(archiveJsonUrl(base, period))}" download>Rohdaten herunterladen (JSON)</a>
```

`escapeHtml` is already imported in this file. The base now comes from config.json
rather than a compile-time constant, so escape it before it lands in an href. `period`
is already validated against `_PERIOD_RE` by `loadMonth` before this line runs.

Note: in remote mode this link is cross-origin, and browsers ignore the `download`
attribute on cross-origin links. "Rohdaten herunterladen" will open the JSON rather
than download it. This is a known, accepted cosmetic regression - do not try to fix it
here.

- [ ] **Step 6: Run the full test suite**

Run: `cd site && npx vitest run`
Expected: **PASS, 9 files, 110 tests.** (Verified against a scratch copy with all of
Task 1 and Task 2 applied.) `archive.test.ts` fetch counts stay 1, 1, 2.

- [ ] **Step 7: Type-check, lint, build**

Run: `cd site && npm run lint && npx tsc --noEmit && npm run build`
Expected: all exit 0; `dist/` written.

- [ ] **Step 8: Commit**

```bash
git add site/src/data.ts site/src/archive.ts site/src/pages/archive-detail.ts \
        site/src/archive.test.ts site/src/pages/archive-list.test.ts \
        site/src/pages/archive-detail.test.ts
git commit -m "refactor(site): resolve data URLs through dataBase()"
```

---

## Task 3: nginx config and container entrypoint

**Files:**
- Create: `site/nginx.conf`
- Create: `site/docker-entrypoint.sh`
- Test: `site/test-entrypoint.sh`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `docker-entrypoint.sh` reads env `S7BB_DATA_BASE_URL`, writes `${WEB_ROOT:-/usr/share/nginx/html}/config.json` as compact JSON `{"dataBaseUrl":"<value>"}`
  - exits non-zero with a `FATAL:` message when `S7BB_DATA_BASE_URL` is unset or blank
  - chains to `/docker-entrypoint.sh` (the nginx image's own init) when present

- [ ] **Step 1: Write the failing test**

Create `site/test-entrypoint.sh`. Plain sh, no framework, no new dependencies:

```sh
#!/bin/sh
# Tests for docker-entrypoint.sh. Run: sh site/test-entrypoint.sh
# Requires: jq (same dependency the entrypoint itself has).
#
# Note: `set -e` is deliberately NOT enabled. Every case runs the entrypoint
# expecting it to fail sometimes, and captures $? by hand.
set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ENTRYPOINT="$SCRIPT_DIR/docker-entrypoint.sh"
FAILED=0

pass() { echo "ok   - $1"; }
fail() { echo "FAIL - $1"; FAILED=1; }

# Each case runs the entrypoint with a throwaway web root and a no-op command,
# so it writes config.json and exits instead of execing nginx.
run_case() {
  WEB_ROOT=$(mktemp -d)
  export WEB_ROOT
  S7BB_DATA_BASE_URL="$1"
  export S7BB_DATA_BASE_URL
  OUT=$(sh "$ENTRYPOINT" true 2>&1)
  RC=$?
  CONFIG="$WEB_ROOT/config.json"
}

# 1. Happy path: writes valid JSON with the URL
run_case "https://raw.githubusercontent.com/s7bb/s7bb-data/main"
if [ "$RC" -eq 0 ] && [ "$(jq -r '.dataBaseUrl' "$CONFIG")" = "https://raw.githubusercontent.com/s7bb/s7bb-data/main" ]; then
  pass "writes dataBaseUrl for a normal URL"
else
  fail "writes dataBaseUrl for a normal URL (rc=$RC out=$OUT)"
fi

# 1b. Output is compact single-line JSON, which is what the docs assert
if [ "$(wc -l < "$CONFIG")" -eq 1 ]; then
  pass "writes compact single-line JSON"
else
  fail "writes compact single-line JSON (got $(wc -l < "$CONFIG") lines)"
fi

# 2. JSON-escaping: a quote in the value must not corrupt the file
run_case 'https://evil.example/"x'
if [ "$RC" -eq 0 ] && jq -e . "$CONFIG" >/dev/null 2>&1 \
   && [ "$(jq -r '.dataBaseUrl' "$CONFIG")" = 'https://evil.example/"x' ]; then
  pass "JSON-escapes a value containing a quote"
else
  fail "JSON-escapes a value containing a quote (rc=$RC out=$OUT)"
fi

# 3. Backslash is escaped too
run_case 'https://evil.example/\x'
if [ "$RC" -eq 0 ] && jq -e . "$CONFIG" >/dev/null 2>&1; then
  pass "JSON-escapes a value containing a backslash"
else
  fail "JSON-escapes a value containing a backslash (rc=$RC out=$OUT)"
fi

# 4. Unset variable fails fast, with a FATAL message.
# Assert on the message, not just rc: a missing or broken script also exits
# non-zero, and a bare rc check would pass against it.
WEB_ROOT=$(mktemp -d); export WEB_ROOT
unset S7BB_DATA_BASE_URL
OUT=$(sh "$ENTRYPOINT" true 2>&1); RC=$?
if [ "$RC" -ne 0 ] && echo "$OUT" | grep -q "FATAL: S7BB_DATA_BASE_URL"; then
  pass "fails fast with FATAL when S7BB_DATA_BASE_URL is unset"
else
  fail "fails fast with FATAL when S7BB_DATA_BASE_URL is unset (rc=$RC out=$OUT)"
fi

# 5. Blank value fails fast, with a FATAL message
run_case "   "
if [ "$RC" -ne 0 ] && echo "$OUT" | grep -q "FATAL: S7BB_DATA_BASE_URL"; then
  pass "fails fast with FATAL when S7BB_DATA_BASE_URL is blank"
else
  fail "fails fast with FATAL when S7BB_DATA_BASE_URL is blank (rc=$RC out=$OUT)"
fi

# 6. Local mode with no data warns but still starts
run_case "/data"
if [ "$RC" -eq 0 ] && echo "$OUT" | grep -q "WARN"; then
  pass "warns when base is /data but latest.json is absent"
else
  fail "warns when base is /data but latest.json is absent (rc=$RC out=$OUT)"
fi

# 7. Local mode with data present does not warn
run_case "/data"
mkdir -p "$WEB_ROOT/data" && echo '{}' > "$WEB_ROOT/data/latest.json"
OUT=$(sh "$ENTRYPOINT" true 2>&1); RC=$?
if [ "$RC" -eq 0 ] && ! echo "$OUT" | grep -q "WARN"; then
  pass "does not warn when /data/latest.json exists"
else
  fail "does not warn when /data/latest.json exists (rc=$RC out=$OUT)"
fi

# 8. A path that merely starts with /data must not be treated as local mode
run_case "https://database.example/feed"
if [ "$RC" -eq 0 ] && ! echo "$OUT" | grep -q "WARN"; then
  pass "does not treat a lookalike URL as local mode"
else
  fail "does not treat a lookalike URL as local mode (rc=$RC out=$OUT)"
fi

exit "$FAILED"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `sh site/test-entrypoint.sh`
Expected: FAIL. Every case reports `FAIL`, non-zero exit, because
`site/docker-entrypoint.sh` does not exist yet.

- [ ] **Step 3: Write the entrypoint**

Create `site/docker-entrypoint.sh`:

```sh
#!/bin/sh
# Writes config.json from the environment, then hands off to nginx.
#
# The data source is a runtime setting so users switch it with a restart
# instead of a rebuild. Writing bad JSON here would make the site silently
# fall back to its build-time default, so validate and fail fast instead.
set -eu

WEB_ROOT="${WEB_ROOT:-/usr/share/nginx/html}"
CONFIG="$WEB_ROOT/config.json"

if [ -z "${S7BB_DATA_BASE_URL:-}" ] || [ -z "$(printf '%s' "${S7BB_DATA_BASE_URL}" | tr -d ' \t')" ]; then
  echo "FATAL: S7BB_DATA_BASE_URL is unset or blank." >&2
  echo "       Set it in .env, for example:" >&2
  echo "         S7BB_DATA_BASE_URL=https://raw.githubusercontent.com/s7bb/s7bb-data/main" >&2
  exit 1
fi

# jq, not printf: a value containing a quote or backslash would otherwise
# produce invalid JSON and the site would quietly use the wrong data source.
# -c keeps it on one line, which is what the docs and tests assert.
mkdir -p "$WEB_ROOT"
jq -nc --arg u "$S7BB_DATA_BASE_URL" '{dataBaseUrl: $u}' > "$CONFIG"

echo "config: dataBaseUrl=$S7BB_DATA_BASE_URL"

# Exact match on /data or a /data/... path. A bare /data* glob would also
# match https://database.example/... and misfire the warning.
case "$S7BB_DATA_BASE_URL" in
  /data|/data/*)
    if [ ! -r "$WEB_ROOT/data/latest.json" ]; then
      echo "WARN: S7BB_DATA_BASE_URL is '$S7BB_DATA_BASE_URL' but $WEB_ROOT/data/latest.json" >&2
      echo "WARN: is missing. The site will show 'Fehler beim Laden der Daten'." >&2
      echo "WARN: Local data comes from the fetcher. Either start it, or switch to" >&2
      echo "WARN: remote data:" >&2
      echo "WARN:   S7BB_DATA_BASE_URL=https://raw.githubusercontent.com/s7bb/s7bb-data/main" >&2
    fi
    ;;
esac

# Chain to the nginx image's own entrypoint when it is there, so its
# /docker-entrypoint.d/ init scripts still run. Absent on a host running the
# tests, in which case exec the command directly.
if [ -x /docker-entrypoint.sh ]; then
  exec /docker-entrypoint.sh "$@"
fi
exec "$@"
```

- [ ] **Step 4: Make both scripts executable and run the tests**

```bash
chmod +x site/docker-entrypoint.sh site/test-entrypoint.sh
sh site/test-entrypoint.sh
```

Expected: 9 `ok` lines, exit 0.

- [ ] **Step 5: Write the nginx config**

Create `site/nginx.conf`:

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # Routing is hash-based (#/archiv/2026-05), so every route is index.html.
    # No SPA try_files fallback is needed.

    # config.json is written at container start. If a browser caches it, a
    # `docker compose restart` after changing S7BB_DATA_BASE_URL appears to do
    # nothing, which is exactly the stale-config trap this design avoids.
    location = /config.json {
        add_header Cache-Control "no-store" always;
    }

    location / {
        try_files $uri $uri/ =404;
    }
}
```

- [ ] **Step 6: Commit**

```bash
git add site/nginx.conf site/docker-entrypoint.sh site/test-entrypoint.sh
git commit -m "feat(site): add nginx config and runtime config entrypoint"
```

---

## Task 4: Site Docker image

**Note:** Docker was not available in the environment where this plan was written, so
Steps 3-5 are the first genuinely unverified steps in it. Treat their expected output
as intent, not as measured fact, and report any deviation rather than forcing a match.

**Files:**
- Create: `site/Dockerfile`
- Create: `site/.dockerignore`

**Interfaces:**
- Consumes: `site/nginx.conf`, `site/docker-entrypoint.sh` from Task 3
- Produces: an image serving the site on port 80, configured by `S7BB_DATA_BASE_URL`

- [ ] **Step 1: Write the .dockerignore**

Create `site/.dockerignore`:

```
node_modules
dist
data
*.log
```

Without this, the build context includes a multi-hundred-MB `node_modules` and every
build is needlessly slow.

- [ ] **Step 2: Write the Dockerfile**

Create `site/Dockerfile`:

```dockerfile
# Build stage: produce the static bundle. Node version matches .nvmrc and CI.
FROM node:22-alpine AS build
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Serve stage: nginx + the built bundle.
FROM nginx:1.27-alpine
# jq is required by docker-entrypoint.sh to write config.json safely.
RUN apk add --no-cache jq
COPY --from=build /build/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
# The nginx image ships its own /docker-entrypoint.sh. Copy ours alongside it
# under a distinct name; ours chains to it so the base init still runs.
COPY docker-entrypoint.sh /docker-entrypoint-s7bb.sh
RUN chmod +x /docker-entrypoint-s7bb.sh
ENTRYPOINT ["/docker-entrypoint-s7bb.sh"]
CMD ["nginx", "-g", "daemon off;"]
```

- [ ] **Step 3: Build the image**

Run: `docker build -t s7bb-site:test site/`
Expected: build succeeds.

- [ ] **Step 4: Verify the image serves and configures correctly**

```bash
docker run --rm -d --name s7bb-site-test -p 8081:80 \
  -e S7BB_DATA_BASE_URL=https://raw.githubusercontent.com/s7bb/s7bb-data/main \
  s7bb-site:test
sleep 2
curl -s http://localhost:8081/config.json; echo
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8081/
curl -s -I http://localhost:8081/config.json | grep -i cache-control
docker logs s7bb-site-test 2>&1 | head -5
docker rm -f s7bb-site-test
```

Expected:
- `{"dataBaseUrl":"https://raw.githubusercontent.com/s7bb/s7bb-data/main"}` on one line
  (`jq -nc` is what makes it compact; without `-c` jq pretty-prints across three lines)
- `200`
- `Cache-Control: no-store`
- logs contain `config: dataBaseUrl=https://raw.githubusercontent.com/s7bb/s7bb-data/main`

- [ ] **Step 5: Verify fail-fast on missing config**

```bash
docker run --rm s7bb-site:test > /tmp/s7bb-fatal.txt 2>&1
echo "exit=$?"
head -3 /tmp/s7bb-fatal.txt
```

Expected: `exit=1` and `FATAL: S7BB_DATA_BASE_URL is unset or blank.`

Capture to a file rather than piping to `head`: `$?` after a pipe is the exit status of
`head`, not of `docker run`, so the piped form would always report success.

- [ ] **Step 6: Commit**

```bash
git add site/Dockerfile site/.dockerignore
git commit -m "feat(site): add multi-stage Docker image"
```

---

## Task 5: Compose service, production profiles, and `.env.example`

This task carries the plan's one production change. Read the whole task before running
anything.

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `site/Dockerfile` from Task 4
- Produces: service `s7bb-site` on profiles `remote` and `fetcher`, port 8080;
  `profiles: [fetcher]` on `s7bb-repo-init` and `s7bb-fetcher`

**Why the production services must be profiled.** A Compose service with no `profiles:`
key is **always** started. `s7bb-repo-init` and `s7bb-fetcher` have none, so
`docker compose up -d` starts the production fetcher today. Putting a profile on
`s7bb-site` gates the site and does nothing to the fetcher. Without this change, telling
a local user to run `up -d` starts a push-enabled fetcher on their machine: a crash loop
with placeholder credentials, or a second writer to s7bb-data with real ones.

Naming a service explicitly enables its profiles, so the VM's documented
`docker compose up -d s7bb-fetcher` keeps working, and `s7bb-repo-init` still comes
along via `depends_on` because it shares the `fetcher` profile.

- [ ] **Step 1: Profile the two production services**

In `docker-compose.yml`, add a `profiles` key to `s7bb-repo-init` (currently line 12)
so it reads:

```yaml
  s7bb-repo-init:
    image: alpine/git:latest
    profiles:
      - fetcher
    environment:
      DATA_REPO_URL: https://github.com/s7bb/s7bb-data.git
```

and to `s7bb-fetcher` (currently line 34) so it reads:

```yaml
  s7bb-fetcher:
    build:
      context: fetcher
      dockerfile: Dockerfile
    profiles:
      - fetcher
    restart: unless-stopped
    env_file: .env
```

Change nothing else in either service.

- [ ] **Step 2: Add the compose service**

In `docker-compose.yml`, add this service above `s7bb-repo-init` so the user-facing
service reads first:

```yaml
  # Static site, served by nginx. Runs in both data modes:
  #   remote  - the browser fetches JSON straight from the s7bb-data repo
  #   fetcher - the browser reads ./data, written by a local fetcher (phase 2)
  # The data source is a runtime setting (S7BB_DATA_BASE_URL), so switching it
  # needs a restart, not a rebuild.
  s7bb-site:
    build:
      context: site
      dockerfile: Dockerfile
    restart: unless-stopped
    profiles:
      - remote
      - fetcher
    ports:
      # 8080 is also used by s7bb-dev, but its profile is disjoint from these.
      - "8080:80"
    environment:
      S7BB_DATA_BASE_URL: ${S7BB_DATA_BASE_URL:-https://raw.githubusercontent.com/s7bb/s7bb-data/main}
    volumes:
      # Unused in remote mode and harmless there; phase 2 (local fetcher)
      # needs no change to this service definition.
      - ./data:/usr/share/nginx/html/data:ro
```

- [ ] **Step 3: Add the paired config block to `.env.example`**

Append to `.env.example`:

```
# --- Local hosting: where the site reads its data from ---
# These two settings must agree. The site warns at startup if they do not.
#
# remote (default): read published data from the s7bb-data repo. No
# credentials needed, full history, current on every page load.
COMPOSE_PROFILES=remote
S7BB_DATA_BASE_URL=https://raw.githubusercontent.com/s7bb/s7bb-data/main

# fetcher: run your own fetcher and serve its output from ./data. Requires
# DB_API_KEY and DB_CLIENT_ID above. Not available yet - see
# docs/superpowers/specs/2026-07-17-local-docker-hosting-design.md (phase 2).
# COMPOSE_PROFILES=fetcher
# S7BB_DATA_BASE_URL=/data
```

- [ ] **Step 4: Validate the compose file**

`s7bb-fetcher` declares `env_file: .env`, which Compose requires to exist even when the
service is not started. Create one if missing, then validate:

```bash
test -f .env || cp .env.example .env
docker compose config --quiet && echo "compose OK"
```

Expected: `compose OK`, no warnings.

Note: `cp` only when `.env` is absent. If a `.env` already exists it may hold real
credentials; never overwrite it.

- [ ] **Step 5: Verify the profile matrix**

This is the check that proves the safety fix. Run each and compare:

```bash
docker compose config --services                      # every service, profiled or not
echo "--- default (no profile) ---"
COMPOSE_PROFILES= docker compose config --services --profiles 2>/dev/null || true
echo "--- what a bare up -d would start ---"
COMPOSE_PROFILES= docker compose up --dry-run -d 2>&1 | head -20
echo "--- what up -d s7bb-site would start ---"
COMPOSE_PROFILES= docker compose up --dry-run -d s7bb-site 2>&1 | head -20
echo "--- what the VM's up -d s7bb-fetcher would start ---"
COMPOSE_PROFILES= docker compose up --dry-run -d s7bb-fetcher 2>&1 | head -20
```

Expected:
- bare `up -d` with no profile: starts **nothing** (no service is in the default set)
- `up -d s7bb-site`: starts **s7bb-site only**
- `up -d s7bb-fetcher`: starts **s7bb-fetcher and s7bb-repo-init**, exactly as the VM
  does today

If `up -d s7bb-fetcher` does not pull in `s7bb-repo-init`, stop. The VM depends on that
ordering and the profiling is wrong.

- [ ] **Step 6: Verify production services are otherwise untouched**

Run: `git diff docker-compose.yml`
Expected: the only changes to `s7bb-repo-init` and `s7bb-fetcher` are the added
`profiles:` keys. No other line of theirs changed. `s7bb-dev`, `s7bb-data-init`, and
`s7bb-site-dev` are untouched.

- [ ] **Step 7: End-to-end smoke test**

```bash
docker compose up -d --build s7bb-site
sleep 3
curl -s http://localhost:8080/config.json; echo
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/
docker compose ps --services
```

Expected:
- `{"dataBaseUrl":"https://raw.githubusercontent.com/s7bb/s7bb-data/main"}`
- `200`
- `docker compose ps --services` prints exactly `s7bb-site` and nothing else. If
  `s7bb-fetcher` or `s7bb-repo-init` appear, stop immediately and run
  `docker compose down` - the profiling in Step 1 is wrong and the fetcher may be
  pushing to s7bb-data.

- [ ] **Step 8: Verify the site actually renders data in a browser**

Open <http://localhost:8080> and confirm the today page shows S7 arrivals rather than
"Fehler beim Laden der Daten". In the browser devtools Network tab, confirm a request
to `raw.githubusercontent.com` returning 200.

This is the one check that proves the whole feature works. It needs a human. Do not
skip it, and do not substitute a passing typecheck for it.

- [ ] **Step 9: Check the ./data ownership question from the spec**

Run: `ls -ld data/ 2>/dev/null || echo "no data dir"`

The spec flags that Docker may create `./data` as a root-owned directory, which would
block the phase 2 fetcher from writing. Record what actually happened in the PR
description. Do not fix it here - phase 2 owns that.

- [ ] **Step 10: Tear down**

Run: `docker compose down`

- [ ] **Step 11: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "feat: add s7bb-site compose service for local hosting"
```

---

## Task 6: Documentation and CI

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: everything above
- Produces: nothing

- [ ] **Step 1: Run the site tests in CI**

CI does not currently run vitest at all: the `typescript` job runs only `npm run lint`
and `npm run build`, so `config.test.ts` and the three refactored test files would go
unenforced. In `.github/workflows/ci.yml`, add to the **`typescript`** job, after the
existing "Type-check + build" step:

```yaml
      - name: Test
        run: npm test
        working-directory: site
```

- [ ] **Step 2: Build the site image and test the entrypoint in CI**

In the same file, add to the **`docker`** job:

```yaml
      - name: Build site image
        run: docker build -t s7bb-site:ci site/

      - name: Test site entrypoint
        run: sh site/test-entrypoint.sh
```

`jq` is preinstalled on `ubuntu-latest`, so the entrypoint test needs no setup.

- [ ] **Step 3: Verify the CI steps work locally**

```bash
cd site && npm test && cd ..
sh site/test-entrypoint.sh
docker build -t s7bb-site:ci site/
```

Expected: 110 tests pass; 9 `ok` lines; image builds.

- [ ] **Step 4: Reconcile the existing README note**

`README.md:21-23` currently says deployment is disabled and points at `#site` for local
builds. That paragraph predates local hosting and would now compete with the new
section. Replace those three lines:

```markdown
Site deployment is currently **disabled** - the `build-site.yml` workflow is
retained but switched off, and no site is published. The site code under
`site/` still builds locally (see [Development](#site)).
```

with:

```markdown
No site is published: GitHub Pages is deleted and the `build-site.yml` workflow is
retained but switched off. Run it yourself instead, see
[Run it locally with Docker](#run-it-locally-with-docker).
```

- [ ] **Step 5: Add the README section**

In `README.md`, add immediately after the "How it works" section. The README is in
English; the German strings below are quoted UI text, per CLAUDE.md:

````markdown
## Run it locally with Docker

The public site is gone. To see the statistics, run them yourself:

```bash
cp .env.example .env
docker compose up -d --build s7bb-site
```

The site is then at <http://localhost:8080>.

The default mode is `remote`: the browser reads the published data directly from
`s7bb/s7bb-data`. No credentials are needed and the full history is there. The data is
current every time you load the page. A tab left open does not refresh on its own;
reload it.

Name the service (`s7bb-site`) rather than running a bare `docker compose up -d`. The
fetcher services are behind the `fetcher` profile, so a bare `up -d` starts nothing
unless `COMPOSE_PROFILES` is set in your `.env`.

### Changing the data source

The source is a runtime setting in `.env`, so changing it needs a restart, not a
rebuild of the image:

```bash
docker compose restart s7bb-site
```

In phase 1 the only supported value is the default:

```
S7BB_DATA_BASE_URL=https://raw.githubusercontent.com/s7bb/s7bb-data/main
```

`COMPOSE_PROFILES` and `S7BB_DATA_BASE_URL` have to agree. If they do not, the page
shows "Fehler beim Laden der Daten" and the reason is in the container log:

```bash
docker compose logs s7bb-site
```

The `fetcher` mode, running your own fetcher instead of reading s7bb-data, is not
available yet. It is described as phase 2 in
[`docs/superpowers/specs/2026-07-17-local-docker-hosting-design.md`](docs/superpowers/specs/2026-07-17-local-docker-hosting-design.md).
````

- [ ] **Step 6: Update CLAUDE.md**

In `CLAUDE.md`, add to the "Site publishing (disabled)" section:

```markdown
Local hosting replaces it: `docker compose up -d --build s7bb-site` builds `site/` and
serves it with nginx on :8080. Default mode `remote` - the browser fetches JSON straight
from `s7bb/s7bb-data`, no credentials, current on each page load (no refresh timer). The
data source is a runtime setting (`S7BB_DATA_BASE_URL`), written to `config.json` by the
site container's entrypoint and read by `site/src/config.ts`; changing it needs a
restart, not a rebuild. `s7bb-repo-init` and `s7bb-fetcher` are behind the `fetcher`
profile so a bare `up -d` cannot start the production fetcher; the VM's
`docker compose up -d s7bb-fetcher` is unaffected. Local fetcher mode is phase 2 and not
implemented. See `docs/superpowers/specs/2026-07-17-local-docker-hosting-design.md`.
```

Also amend the "Project: S7BB" audience line. It currently reads:

```markdown
Target audience: non-technical Baierbrunn residents; UI labels are German, code/comments English.
```

Change it to:

```markdown
Target audience: Baierbrunn residents; UI labels are German, code/comments English.
Note: since the public site was taken down, distribution is via local Docker, so
running S7BB now requires technical skill even though the UI stays simple and German.
```

- [ ] **Step 7: Add the CHANGELOG entry**

In `CHANGELOG.md`, under `[Unreleased]`, add an `### Added` section above the existing
`### Removed`:

```markdown
### Added

- Local Docker hosting: `docker compose up -d --build s7bb-site` builds the site and serves it at <http://localhost:8080>, reading published data straight from the s7bb-data repo with no credentials. The data source is configurable at runtime via `S7BB_DATA_BASE_URL` and takes effect on restart, without a rebuild.

### Changed

- The `s7bb-repo-init` and `s7bb-fetcher` services now sit behind the `fetcher` compose profile, so a bare `docker compose up -d` no longer starts the production fetcher. The documented `docker compose up -d s7bb-fetcher` is unaffected.
```

- [ ] **Step 8: Check the em-dash constraint across the feature diff**

```bash
git diff main...HEAD -- . ':!docs/superpowers' | grep -n "^+.*—"
```
Expected: no output.

Scope matters here. An unscoped `git diff main...HEAD | grep "—"` matches this plan's
own constraint text and its grep command, and can also match unchanged context lines
from `.env.example`. Only added lines outside `docs/superpowers/` are in scope.

- [ ] **Step 9: Full verification**

```bash
cd site && npm run lint && npx tsc --noEmit && npm run build && npm test && cd ..
sh site/test-entrypoint.sh
docker compose config --quiet && echo "compose OK"
```

Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add .github/workflows/ci.yml README.md CLAUDE.md CHANGELOG.md
git commit -m "docs: document local Docker hosting"
```

---

## Task 7: Open the PR

**Files:** none

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/local-docker-hosting
```

- [ ] **Step 2: Open the PR**

Title: `feat: local Docker hosting (phase 1, remote mode)`

The body must state:
- what shipped: remote mode, runtime config, `dataBase()` refactor
- **the production compose change**: `s7bb-repo-init` and `s7bb-fetcher` are now behind
  the `fetcher` profile, why (a bare `up -d` previously started the production fetcher),
  and the evidence from Task 5 Step 5 that `up -d s7bb-fetcher` still works
- what did not ship: fetcher mode, seeding (phase 2, link the spec)
- no auto-refresh: current per page load, by design
- the `./data` ownership finding from Task 5 Step 9
- the cross-origin `download` attribute regression from Task 2 Step 5
- confirmation that the browser smoke test (Task 5 Step 8) passed

- [ ] **Step 3: Wait for CI**

Run: `gh pr checks --watch`
Expected: python, typescript, docker all pass.

- [ ] **Step 4: Flag the VM step for the maintainer**

The compose profile change affects the VM. Note in the PR that after merge, the VM needs
`git pull` and that its `docker compose up -d s7bb-fetcher` command is unchanged. No
action beyond the pull is required. Do not run anything against the VM yourself.

---

## Task 8: Cut the release

CLAUDE.md's post-merge trigger makes this mandatory: the branch contains `feat`
commits, so merging requires a **MINOR** release. Do this immediately after merge.

**Files:**
- Modify: `fetcher/pyproject.toml`, `fetcher/uv.lock`, `CHANGELOG.md`

- [ ] **Step 1: Pull main and determine the version**

```bash
git checkout main && git pull
grep '^version' fetcher/pyproject.toml
```

Current is `0.10.0`, so the new version is `0.11.0` (MINOR: `feat`, no breaking change).
If `pyproject.toml` shows something else, recompute: MINOR bump from whatever is there.

- [ ] **Step 2: Bump the version and sync the lock**

```bash
# edit fetcher/pyproject.toml: version = "0.11.0"
cd fetcher && uv sync --no-dev && cd ..
git diff --stat fetcher/uv.lock
```

Expected: `uv.lock` shows the new version.

- [ ] **Step 3: Update the CHANGELOG**

Rename `## [Unreleased]` to `## [0.11.0] - 2026-07-17` (use the actual date), and add a
fresh empty `## [Unreleased]` above it.

- [ ] **Step 4: Commit and tag**

```bash
git add fetcher/pyproject.toml fetcher/uv.lock CHANGELOG.md
git commit -m "chore(release): 0.11.0"
git tag v0.11.0
git push && git push --tags
```

- [ ] **Step 5: Extract the release notes and VERIFY THEY ARE NOT EMPTY**

The form in CLAUDE.md silently yields an empty body. Use the dot-escaped, explicit-end
form, and check the output before publishing:

```bash
awk '/^## \[0\.11\.0\]/,/^## \[0\.10\.0\]/' CHANGELOG.md | sed '$d' > /tmp/notes.md
cat /tmp/notes.md
wc -l /tmp/notes.md
```

Expected: the 0.11.0 section body, several lines, **not empty**. If it is empty or one
line, stop and fix the awk before continuing. Publishing an empty release body is the
recorded failure mode here.

- [ ] **Step 6: Create the GitHub Release**

```bash
gh release create v0.11.0 --title "v0.11.0" --notes-file /tmp/notes.md --latest
gh release view v0.11.0
```

Expected: the release exists at
<https://github.com/s7bb/s7bb.github.io/releases> with a non-empty body matching the
CHANGELOG section.
