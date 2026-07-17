# Local Docker Hosting (Phase 1: remote mode) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let anyone run the S7BB site locally with `docker compose up -d`, reading published data from the s7bb-data repo, with no credentials.

**Architecture:** A new multi-stage `site/Dockerfile` builds the Vite bundle and serves it with nginx. The data source is a runtime setting, not a build-time bake: the container entrypoint writes `config.json` from `S7BB_DATA_BASE_URL` at startup, and the site fetches that file at boot to learn its base URL. A new `dataBase()` helper collapses the three duplicated base-URL branches into one resolution path, falling back to today's behavior when no config exists so dev workflows are unaffected.

**Tech Stack:** TypeScript, Vite 8, Vitest 4, nginx (alpine), Node 22, Docker Compose, jq (in the site image, for JSON escaping).

**Spec:** `docs/superpowers/specs/2026-07-17-local-docker-hosting-design.md`

## Global Constraints

- **No em-dash.** Do not use "—" anywhere: UI text, docs, code comments, commit messages. Use a plain hyphen "-".
- **Exact dependency pinning.** All deps use `=X.Y.Z` exact versions. Pin Docker base images to a specific tag, never `latest`.
- **Conventional Commits.** Types: `feat`, `fix`, `docs`, `chore`, `refactor`, `perf`, `test`, `style`, `revert`. Subject imperative, lowercase, no trailing period, <=72 chars.
- **German UI, English code.** UI labels/strings in German; code, comments, and commit messages in English.
- **Node 22**, per `.nvmrc`.
- **No new npm dependencies.** Everything in this plan uses what is already installed.
- **Do not touch production services.** `s7bb-repo-init`, `s7bb-fetcher`, and the `dev` profile in `docker-compose.yml` must keep working exactly as they do. The VM runs `docker compose up -d s7bb-fetcher` and depends on current behavior.
- This is **phase 1 only**: remote mode. Do not implement `S7BB_PUSH_ENABLED`, preflight rework, or `s7bb-seed`.

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
| `site/nginx.conf` | Create | Serve static assets; `no-store` on config.json. |
| `site/docker-entrypoint.sh` | Create | Write config.json from env; validate; warn on missing local data. |
| `site/test-entrypoint.sh` | Create | Plain-sh tests for the entrypoint. No framework, no new deps. |
| `site/Dockerfile` | Create | Multi-stage node build -> nginx serve. |
| `site/.dockerignore` | Create | Keep `node_modules/` out of the build context. |
| `docker-compose.yml` | Modify | Add the `s7bb-site` service under profiles `remote` and `fetcher`. |
| `.env.example` | Modify | Add the paired config block; fix the stale README pointer (Task 0). |
| `README.md` | Modify | New "Lokal mit Docker betreiben" section. |
| `CHANGELOG.md` | Modify | Entry under `[Unreleased]`. |
| `CLAUDE.md` | Modify | Local-hosting architecture note; audience note. |
| `.github/workflows/ci.yml` | Modify | Build the site image so the Dockerfile cannot rot. |

---

## Task 0: Fix the stale README pointer in `.env.example`

Unrelated to this feature, but a known defect recorded in the spec. PR #78 renumbered
README section 5 to 4 and missed this file. Do it first so it does not pollute the
feature diff.

**Files:**
- Modify: `.env.example`

**Interfaces:**
- Consumes: nothing
- Produces: nothing

- [ ] **Step 1: Confirm the stale pointer exists**

Run: `grep -n "README §" .env.example`
Expected: one line reading `# See README §5 for the rotation flow.`

- [ ] **Step 2: Fix it**

In `.env.example`, change:

```
# See README §5 for the rotation flow.
```

to:

```
# See README §4 for the rotation flow.
```

- [ ] **Step 3: Verify no stale pointers remain repo-wide**

Run: `grep -rn "README §5" . --exclude-dir=.git --exclude-dir=node_modules`
Expected: no output.

- [ ] **Step 4: Commit**

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
    expect(await dataBase()).toBe("/data");
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("falls back silently when config.json is not JSON", async () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("<!doctype html><html></html>", { status: 200 }) as Response,
    );
    expect(await dataBase()).toBe("/data");
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("falls back silently when the fetch itself rejects", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("network down"));
    expect(await dataBase()).toBe("/data");
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

// Test helper: set the base without a config.json round-trip, so tests that
// count fetch calls stay accurate.
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
Expected: PASS, 14 tests.

Note: the `dataBase` fallback tests assert `/data` because vitest runs with
`import.meta.env.DEV` true by default. If they instead resolve `../data`, that
confirms DEV is true in this environment: change those three expectations to
`"../data"`. Do not stub DEV - `resolveBase` already covers both branches purely.

- [ ] **Step 5: Lint**

Run: `cd site && npm run lint`
Expected: no errors.

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
- Modify: `site/src/archive.test.ts:1`, `:29-32`

**Interfaces:**
- Consumes: `dataBase()`, `_primeDataBase()` from Task 1
- Produces:
  - `archiveBase(): Promise<string>` (was sync)
  - `archiveJsonUrl(base: string, period: string): string` (was `(period: string)`)

- [ ] **Step 1: Prime the config cache in the existing archive tests**

`dataBase()` adds a `config.json` fetch, which would make the existing
`toHaveBeenCalledTimes(1)` assertions in `archive.test.ts` see 2 calls. Priming the
cache skips that fetch and keeps the assertions meaningful.

In `site/src/archive.test.ts`, change line 1-2 imports to add the helper:

```typescript
import { describe, it, expect, beforeEach, vi } from "vitest";
import { loadIndex, loadMonth, _resetCache } from "./archive.js";
import { _primeDataBase } from "./config.js";
```

and change the `beforeEach` block (currently lines 29-32) to:

```typescript
beforeEach(() => {
  _resetCache();
  _primeDataBase("../data");
  vi.restoreAllMocks();
});
```

- [ ] **Step 2: Run the archive tests to verify they still fail correctly**

Run: `cd site && npx vitest run src/archive.test.ts`
Expected: FAIL. `_primeDataBase` resolves, but `archive.ts` does not use it yet, so this
should still pass on the old code path. If it PASSES, that is fine and expected: this
step only prevents a false failure in Step 4.

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
Expected: PASS, all files. `archive.test.ts` fetch counts unchanged (1, 1, 2).

- [ ] **Step 7: Type-check, lint, build**

Run: `cd site && npm run lint && npm run build`
Expected: no errors; `dist/` written.

- [ ] **Step 8: Verify dev behavior is unchanged**

Run: `cd site && npx vitest run src/config.test.ts -t "dev"`
Expected: PASS. `resolveBase` with `dev: true` still yields `../data`, so
`npm run dev` and the `s7bb-site-dev` profile keep resolving `../data/latest.json`
exactly as before.

- [ ] **Step 9: Commit**

```bash
git add site/src/data.ts site/src/archive.ts site/src/pages/archive-detail.ts site/src/archive.test.ts
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
  - `docker-entrypoint.sh` reads env `S7BB_DATA_BASE_URL`, writes `${WEB_ROOT:-/usr/share/nginx/html}/config.json` as `{"dataBaseUrl":"<value>"}`
  - exits non-zero when `S7BB_DATA_BASE_URL` is unset or blank

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

# 4. Unset variable fails fast
WEB_ROOT=$(mktemp -d); export WEB_ROOT
unset S7BB_DATA_BASE_URL
OUT=$(sh "$ENTRYPOINT" true 2>&1); RC=$?
if [ "$RC" -ne 0 ]; then
  pass "fails fast when S7BB_DATA_BASE_URL is unset"
else
  fail "fails fast when S7BB_DATA_BASE_URL is unset (rc=$RC)"
fi

# 5. Blank value fails fast
run_case "   "
if [ "$RC" -ne 0 ]; then
  pass "fails fast when S7BB_DATA_BASE_URL is blank"
else
  fail "fails fast when S7BB_DATA_BASE_URL is blank (rc=$RC)"
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

exit "$FAILED"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `sh site/test-entrypoint.sh`
Expected: FAIL. `sh: site/docker-entrypoint.sh: No such file or directory`, non-zero exit.

- [ ] **Step 3: Write the entrypoint**

Create `site/docker-entrypoint.sh`:

```sh
#!/bin/sh
# Writes config.json from the environment, then execs the given command.
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
mkdir -p "$WEB_ROOT"
jq -n --arg u "$S7BB_DATA_BASE_URL" '{dataBaseUrl: $u}' > "$CONFIG"

echo "config: dataBaseUrl=$S7BB_DATA_BASE_URL"

case "$S7BB_DATA_BASE_URL" in
  /data*)
    if [ ! -r "$WEB_ROOT/data/latest.json" ]; then
      echo "WARN: S7BB_DATA_BASE_URL is '$S7BB_DATA_BASE_URL' but $WEB_ROOT/data/latest.json" >&2
      echo "WARN: is missing. The site will show 'Fehler beim Laden der Daten'." >&2
      echo "WARN: Local data comes from the fetcher. Either start it, or switch to" >&2
      echo "WARN: remote data:" >&2
      echo "WARN:   S7BB_DATA_BASE_URL=https://raw.githubusercontent.com/s7bb/s7bb-data/main" >&2
    fi
    ;;
esac

exec "$@"
```

- [ ] **Step 4: Make it executable and run the tests**

```bash
chmod +x site/docker-entrypoint.sh site/test-entrypoint.sh
sh site/test-entrypoint.sh
```

Expected: 7 `ok` lines, exit 0.

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
COPY docker-entrypoint.sh /docker-entrypoint-s7bb.sh
RUN chmod +x /docker-entrypoint-s7bb.sh
ENTRYPOINT ["/docker-entrypoint-s7bb.sh"]
CMD ["nginx", "-g", "daemon off;"]
```

Note on the entrypoint path: the `nginx` image already ships its own
`/docker-entrypoint.sh`. Writing to that path would clobber it, so the file is copied
to `/docker-entrypoint-s7bb.sh` instead.

- [ ] **Step 3: Build the image**

Run: `docker build -t s7bb-site:test site/`
Expected: build succeeds.

- [ ] **Step 4: Verify the image serves and configures correctly**

```bash
docker run --rm -d --name s7bb-site-test -p 8081:80 \
  -e S7BB_DATA_BASE_URL=https://raw.githubusercontent.com/s7bb/s7bb-data/main \
  s7bb-site:test
sleep 2
curl -s http://localhost:8081/config.json
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8081/
curl -s -I http://localhost:8081/config.json | grep -i cache-control
docker rm -f s7bb-site-test
```

Expected:
- `{"dataBaseUrl":"https://raw.githubusercontent.com/s7bb/s7bb-data/main"}`
- `200`
- `Cache-Control: no-store`

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

## Task 5: Compose service and `.env.example`

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `site/Dockerfile` from Task 4
- Produces: service `s7bb-site` on profiles `remote` and `fetcher`, port 8080

- [ ] **Step 1: Add the compose service**

In `docker-compose.yml`, add this service. Put it above `s7bb-repo-init` so the
user-facing service reads first. Do not modify any existing service.

```yaml
  # Static site, served by nginx. Runs in both data modes:
  #   remote  - the browser fetches JSON straight from the s7bb-data repo
  #   fetcher - the browser reads ./data, written by a local fetcher (phase 2)
  # The data source is a runtime setting (S7BB_DATA_BASE_URL), so switching it
  # needs a restart, not a rebuild.
  #
  # This service carries a profile deliberately: s7bb-repo-init and
  # s7bb-fetcher have none, so a bare `docker compose up -d` would otherwise
  # start the production push-enabled fetcher on a local machine.
  s7bb-site:
    build:
      context: site
      dockerfile: Dockerfile
    restart: unless-stopped
    profiles:
      - remote
      - fetcher
    ports:
      - "8080:80"
    environment:
      S7BB_DATA_BASE_URL: ${S7BB_DATA_BASE_URL:-https://raw.githubusercontent.com/s7bb/s7bb-data/main}
    volumes:
      # Unused in remote mode and harmless there; phase 2 (local fetcher)
      # needs no change to this service definition.
      - ./data:/usr/share/nginx/html/data:ro
```

- [ ] **Step 2: Add the paired config block to `.env.example`**

Append to `.env.example`:

```
# --- Local hosting: where the site reads its data from ---
# These two settings must agree. The site warns at startup if they do not.
#
# remote (default): read published data from the s7bb-data repo. No
# credentials needed, full history, always current.
COMPOSE_PROFILES=remote
S7BB_DATA_BASE_URL=https://raw.githubusercontent.com/s7bb/s7bb-data/main

# fetcher: run your own fetcher and serve its output from ./data. Requires
# DB_API_KEY and DB_CLIENT_ID above. Not available yet - see
# docs/superpowers/specs/2026-07-17-local-docker-hosting-design.md (phase 2).
# COMPOSE_PROFILES=fetcher
# S7BB_DATA_BASE_URL=/data
```

- [ ] **Step 3: Validate the compose file**

Run: `docker compose config --quiet && echo "compose OK"`
Expected: `compose OK`, no warnings.

- [ ] **Step 4: Verify production services are untouched**

Run: `git diff docker-compose.yml`
Expected: additions only. No lines removed or changed in `s7bb-repo-init`,
`s7bb-fetcher`, `s7bb-dev`, `s7bb-data-init`, or `s7bb-site-dev`.

- [ ] **Step 5: End-to-end smoke test**

```bash
cp -n .env.example .env 2>/dev/null || true
docker compose up -d --build
sleep 3
curl -s http://localhost:8080/config.json
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/
docker compose ps
```

Expected:
- `{"dataBaseUrl":"https://raw.githubusercontent.com/s7bb/s7bb-data/main"}`
- `200`
- **Only `s7bb-site` running.** If `s7bb-fetcher` or `s7bb-repo-init` also started, the
  profile is wrong - stop and fix before continuing.

- [ ] **Step 6: Verify the site actually renders data in a browser**

Open <http://localhost:8080> and confirm the today page shows S7 arrivals rather than
"Fehler beim Laden der Daten". Check the browser devtools Network tab: there should be
a request to `raw.githubusercontent.com` returning 200.

This is the one check that proves the whole feature works. Do not skip it.

- [ ] **Step 7: Check the ./data ownership question from the spec**

Run: `ls -la data/ 2>/dev/null || echo "no data dir"`

The spec flags that Docker may create `./data` as a root-owned directory, which would
block the phase 2 fetcher from writing. Record what actually happened in the PR
description. Do not fix it here - phase 2 owns that.

- [ ] **Step 8: Tear down**

Run: `docker compose down`

- [ ] **Step 9: Commit**

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

- [ ] **Step 1: Add the site image build to CI**

In `.github/workflows/ci.yml`, inside the existing `docker` job, add a step that builds
the site image so the Dockerfile cannot rot:

```yaml
      - name: Build site image
        run: docker build -t s7bb-site:ci site/
```

Add a step running the entrypoint tests to the same job:

```yaml
      - name: Test site entrypoint
        run: sh site/test-entrypoint.sh
```

Note: the entrypoint test needs `jq`, which is preinstalled on `ubuntu-latest`.

- [ ] **Step 2: Verify the CI steps work locally**

```bash
docker build -t s7bb-site:ci site/ && sh site/test-entrypoint.sh
```

Expected: build succeeds; 7 `ok` lines.

- [ ] **Step 3: Add the README section**

In `README.md`, add after the "How it works" section:

````markdown
## Lokal mit Docker betreiben

Der öffentliche Auftritt ist abgeschaltet. Wer die Auswertung sehen will, betreibt sie
lokal:

```bash
cp .env.example .env
docker compose up -d --build
```

Danach ist die Seite unter <http://localhost:8080> erreichbar.

Voreingestellt ist der Modus `remote`: der Browser liest die veröffentlichten Daten
direkt aus `s7bb/s7bb-data`. Es werden keine Zugangsdaten benötigt, die vollständige
Historie ist vorhanden, und die Daten bleiben aktuell, solange der Container läuft.

### Datenquelle umstellen

Die Quelle ist eine Laufzeit-Einstellung. Ein Wechsel braucht keinen Neubau:

```bash
# .env
S7BB_DATA_BASE_URL=https://raw.githubusercontent.com/s7bb/s7bb-data/main
```

```bash
docker compose restart s7bb-site
```

`COMPOSE_PROFILES` und `S7BB_DATA_BASE_URL` müssen zusammenpassen. Passen sie nicht
zusammen, zeigt die Seite "Fehler beim Laden der Daten"; der Grund steht im
Container-Log:

```bash
docker compose logs s7bb-site
```

Der Modus `fetcher` (eigene Fetcher-Instanz statt s7bb-data) ist noch nicht verfügbar.
Er ist in
[`docs/superpowers/specs/2026-07-17-local-docker-hosting-design.md`](docs/superpowers/specs/2026-07-17-local-docker-hosting-design.md)
als Phase 2 beschrieben.
````

- [ ] **Step 4: Update CLAUDE.md**

In `CLAUDE.md`, add to the "Site publishing (disabled)" section:

```markdown
Local hosting replaces it: `docker compose up -d --build` builds `site/` and serves it
with nginx on :8080. Default mode `remote` - the browser fetches JSON straight from
`s7bb/s7bb-data`, no credentials. The data source is a runtime setting
(`S7BB_DATA_BASE_URL`), written to `config.json` by the site container's entrypoint and
read by `site/src/config.ts`; changing it needs a restart, not a rebuild. Local fetcher
mode is phase 2 and not implemented. See
`docs/superpowers/specs/2026-07-17-local-docker-hosting-design.md`.
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

- [ ] **Step 5: Add the CHANGELOG entry**

In `CHANGELOG.md`, under `[Unreleased]`, add an `### Added` section above the existing
`### Removed`:

```markdown
### Added

- Local Docker hosting: `docker compose up -d --build` builds the site and serves it at <http://localhost:8080>, reading published data straight from the s7bb-data repo with no credentials. The data source is configurable at runtime via `S7BB_DATA_BASE_URL` and takes effect on restart, without a rebuild.
```

- [ ] **Step 6: Check the em-dash constraint across the whole diff**

Run: `git diff main...HEAD | grep -n "—"`
Expected: no output. If any line matches, replace the em-dash with a plain hyphen.

- [ ] **Step 7: Full verification**

```bash
cd site && npm run lint && npm run build && npx vitest run && cd ..
sh site/test-entrypoint.sh
docker compose config --quiet && echo "compose OK"
```

Expected: all pass.

- [ ] **Step 8: Commit**

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
- what did not: fetcher mode, seeding (phase 2, with a link to the spec)
- the `./data` ownership finding from Task 5 Step 7
- the cross-origin `download` attribute regression from Task 2 Step 5
- confirmation that the browser smoke test (Task 5 Step 6) passed

- [ ] **Step 3: Wait for CI**

Run: `gh pr checks --watch`
Expected: python, typescript, docker all pass.

---

## Release note

This branch contains a `feat`, so per CLAUDE.md it triggers a **MINOR** release once
merged: bump `fetcher/pyproject.toml`, sync `fetcher/uv.lock`, rename `[Unreleased]` in
`CHANGELOG.md`, tag, push, and create the GitHub Release. Follow
`.claude/skills/release-hygiene/SKILL.md`. Use the dot-escaped explicit-end awk form for
the release notes and verify the body is non-empty before publishing.
