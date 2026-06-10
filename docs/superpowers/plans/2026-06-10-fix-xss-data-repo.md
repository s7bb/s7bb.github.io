# Fix Stored XSS via s7bb-data Repo (review finding H1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the stored-XSS path where JSON from the bot-writable `s7bb/s7bb-data` repo (`archive/index.json`, `archive/YYYY-MM.json`, `latest.json`) reaches `innerHTML` unescaped or uncoerced, so a compromised bot PAT can no longer inject script into visitors' browsers.

**Architecture:** Two layers. (1) Load boundary: `loadIndex()` drops index entries whose `period` fails the existing `/^\d{4}-\d{2}$/` regex, so attacker-shaped periods never reach any renderer. (2) Render sites: every interpolation of data-repo-derived values into `innerHTML` goes through `escapeHtml` (strings) or a new `num()` coercion helper (numeric fields, which TypeScript types as `number` but which arrive from unvalidated JSON). The duplicated `germanMonth` helper is hoisted into `data.ts` and hardened to return the raw period (for the caller to escape) instead of `"undefined 2026"` on out-of-range months.

**Threat model note (do not weaken):** `latest.json` and the archive JSONs are written by the VM bot. The two-repo split exists so a stolen bot PAT means "bad data only". Any unescaped/uncoerced interpolation of these JSONs breaks that containment. Chart.js inputs (labels, datasets) render to `<canvas>` text, not HTML, and are out of scope.

**Tech Stack:** TypeScript, Vite, Vitest + jsdom (already configured: `site/vitest.config.ts`, tests colocated as `src/**/*.test.ts`). All commands below run from `site/`.

**Conventions:** No em-dash anywhere (project rule, use "-"). Conventional Commits. This plan file gets bundled into the implementation PR (CLAUDE.md plan-file rule).

## File structure

- Modify: `site/src/data.ts` - add `num()` and hardened shared `germanMonth()` next to `escapeHtml`
- Modify: `site/src/data.test.ts` - tests for both helpers
- Modify: `site/src/archive.ts` - filter invalid `period` entries in `loadIndex()`
- Modify: `site/src/archive.test.ts` - test the filter
- Modify: `site/src/pages/archive-list.ts` - escape/coerce all interpolations, delete local `germanMonth`
- Create: `site/src/pages/archive-list.test.ts` - render test with hostile index JSON
- Modify: `site/src/pages/archive-detail.ts` - escape/coerce all interpolations, delete local `germanMonth`
- Modify: `site/src/pages/archive-detail.test.ts` - render test with hostile month JSON
- Modify: `site/src/pages/today.ts` - coerce numeric aggregate fields in `summaryBar`, `statusBadge`, `fmtDeparture`, totals line
- Modify: `site/src/pages/today.test.ts` - render test with hostile aggregates
- Modify: `site/src/charts/weekKpi.ts` - coerce `avg_delay_min` / `cancelled`
- Modify: `site/src/charts/weekKpi.test.ts` - hostile-input test
- Modify: `CHANGELOG.md` - `[Unreleased]` Fixed entry

Out of scope (separate findings, do not fix here): negative-delay flooring in the archive table (M2), UTC time display (H3), day bucketing (M1). `num()` must preserve current numeric behavior exactly, including negative values.

---

### Task 1: `num()` coercion helper

**Files:**
- Modify: `site/src/data.ts` (insert after `escapeHtml`, which ends at line 63)
- Test: `site/src/data.test.ts`

- [ ] **Step 1: Write the failing tests**

Append to `site/src/data.test.ts`:

```ts
describe("num", () => {
  it("passes finite numbers through unchanged, including negatives and floats", () => {
    expect(num(5)).toBe(5);
    expect(num(-3)).toBe(-3);
    expect(num(1.2)).toBe(1.2);
    expect(num(0)).toBe(0);
  });

  it("coerces numeric strings", () => {
    expect(num("7")).toBe(7);
  });

  it("returns 0 for injection payloads, NaN, Infinity, null, undefined, objects", () => {
    expect(num('<img src=x onerror=alert(1)>')).toBe(0);
    expect(num(NaN)).toBe(0);
    expect(num(Infinity)).toBe(0);
    expect(num(null)).toBe(0);
    expect(num(undefined)).toBe(0);
    expect(num({})).toBe(0);
  });
});
```

Add `num` to the existing import from `./data.js` at the top of the file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/data.test.ts`
Expected: FAIL - `num` is not exported (TypeScript/import error).

- [ ] **Step 3: Implement `num()`**

In `site/src/data.ts`, directly after the `escapeHtml` function:

```ts
// Numeric fields in latest.json / archive JSON are typed as number but come
// from the bot-writable s7bb-data repo. Coerce before innerHTML interpolation
// so a tampered value can never carry markup.
export function num(v: unknown): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/data.test.ts`
Expected: PASS (all describe blocks).

- [ ] **Step 5: Commit**

```bash
git add site/src/data.ts site/src/data.test.ts
git commit -m "feat(site): add num() coercion helper for untrusted JSON numerics"
```

---

### Task 2: shared hardened `germanMonth()`

**Files:**
- Modify: `site/src/data.ts` (insert after `num()` from Task 1)
- Test: `site/src/data.test.ts`

Currently duplicated verbatim in `archive-list.ts:4-9` and `archive-detail.ts:6-11`; both index `months[parseInt(m, 10)]` unchecked, yielding `"undefined 2026"` for month `00`/`13`. The hardened version returns the input unchanged when it is not a valid `YYYY-MM` with month 01-12; callers must escape the result (it may be attacker-controlled passthrough).

- [ ] **Step 1: Write the failing tests**

Append to `site/src/data.test.ts` (add `germanMonth` to the `./data.js` import):

```ts
describe("germanMonth", () => {
  it("formats a valid period", () => {
    expect(germanMonth("2026-04")).toBe("April 2026");
    expect(germanMonth("2026-01")).toBe("Januar 2026");
    expect(germanMonth("2026-12")).toBe("Dezember 2026");
  });

  it("returns the input unchanged for out-of-range months", () => {
    expect(germanMonth("2026-00")).toBe("2026-00");
    expect(germanMonth("2026-13")).toBe("2026-13");
  });

  it("returns the input unchanged for non-period strings (incl. payloads)", () => {
    expect(germanMonth("<img src=x onerror=alert(1)>")).toBe("<img src=x onerror=alert(1)>");
    expect(germanMonth("2026-4")).toBe("2026-4");
    expect(germanMonth("")).toBe("");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/data.test.ts`
Expected: FAIL - `germanMonth` is not exported.

- [ ] **Step 3: Implement**

In `site/src/data.ts`, after `num()`:

```ts
// Renders "April 2026" for "2026-04". Returns the input verbatim when it is
// not a valid YYYY-MM period (month 01-12) - callers must escapeHtml the
// result, since the passthrough may be attacker-controlled.
export function germanMonth(period: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (!match) return period;
  const idx = parseInt(match[2], 10);
  const months = ["", "Januar", "Februar", "März", "April", "Mai", "Juni",
                  "Juli", "August", "September", "Oktober", "November", "Dezember"];
  if (idx < 1 || idx > 12) return period;
  return `${months[idx]} ${match[1]}`;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/data.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add site/src/data.ts site/src/data.test.ts
git commit -m "feat(site): shared germanMonth() helper, hardened against invalid periods"
```

---

### Task 3: validate `period` at the load boundary

**Files:**
- Modify: `site/src/archive.ts:45-55` (`loadIndex`)
- Test: `site/src/archive.test.ts`

`loadMonth` already rejects invalid periods via `_PERIOD_RE` (`archive.ts:58`). `loadIndex` trusts the JSON wholesale. Drop months whose `period` is not a `YYYY-MM` string so no renderer ever sees one.

- [ ] **Step 1: Write the failing test**

Append inside the existing `describe("loadIndex", ...)` block in `site/src/archive.test.ts`:

```ts
  it("drops months whose period is not a valid YYYY-MM string", async () => {
    const hostile = {
      ...indexJson,
      months: [
        ...indexJson.months,
        { ...indexJson.months[0], period: '"><img src=x onerror=alert(1)>' },
        { ...indexJson.months[0], period: 42 },
        { ...indexJson.months[0], period: "2026-4" },
      ],
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(hostile), { status: 200 }) as Response,
    );
    const idx = await loadIndex();
    expect(idx.months).toHaveLength(1);
    expect(idx.months[0].period).toBe("2026-04");
  });

  it("tolerates a missing months array", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ generated_at: "x", station: "Baierbrunn" }), { status: 200 }) as Response,
    );
    const idx = await loadIndex();
    expect(idx.months).toEqual([]);
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/archive.test.ts`
Expected: the two new tests FAIL (hostile months pass through; missing array stays undefined). Existing tests PASS.

- [ ] **Step 3: Implement the filter**

In `site/src/archive.ts`, replace the body of the `loadIndex` IIFE (lines 47-52):

```ts
    _indexCache = (async () => {
      const url = `${archiveBase()}/index.json`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`Failed to load archive index: ${resp.status}`);
      const idx = (await resp.json()) as ArchiveIndex;
      // index.json comes from the bot-writable s7bb-data repo: never let a
      // non-YYYY-MM period reach a renderer (stored-XSS containment).
      idx.months = Array.isArray(idx.months)
        ? idx.months.filter((m) => typeof m.period === "string" && _PERIOD_RE.test(m.period))
        : [];
      return idx;
    })().catch((e) => { _indexCache = null; throw e; });
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/archive.test.ts`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add site/src/archive.ts site/src/archive.test.ts
git commit -m "fix(site): drop invalid archive index periods at load boundary"
```

---

### Task 4: harden `archive-list.ts` rendering

**Files:**
- Modify: `site/src/pages/archive-list.ts`
- Create: `site/src/pages/archive-list.test.ts`

The primary XSS site (`archive-list.ts:35-38`): `m.period` into `href`, `germanMonth(m.period)` into link text, `m.total`/`m.on_time`/`m.late`/`m.cancelled` into the summary span - all unescaped inside `container.innerHTML`. Defense in depth on top of Task 3.

- [ ] **Step 1: Write the failing test**

Create `site/src/pages/archive-list.test.ts`:

```ts
import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderArchiveList } from "./archive-list.js";
import { _resetCache } from "../archive.js";

vi.mock("../charts/monthsBar.js", () => ({ renderMonthsBar: vi.fn() }));

function month(overrides: Record<string, unknown>) {
  return {
    period: "2026-04", finalized: true,
    total: 100, on_time: 90, late: 8, cancelled: 2, avg_delay_min: 1.0,
    by_direction: {
      muenchen:       { total: 50, on_time: 45, late: 4, cancelled: 1, avg_delay_min: 1.0 },
      wolfratshausen: { total: 50, on_time: 45, late: 4, cancelled: 1, avg_delay_min: 1.0 },
    },
    ...overrides,
  };
}

function mockIndex(months: unknown[]): void {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ generated_at: "x", station: "Baierbrunn", months }), { status: 200 }) as Response,
  );
}

beforeEach(() => {
  _resetCache();
  vi.restoreAllMocks();
});

describe("renderArchiveList", () => {
  it("renders a month link with German label", async () => {
    mockIndex([month({})]);
    const c = document.createElement("div");
    await renderArchiveList(c);
    const a = c.querySelector(".month-links a") as HTMLAnchorElement;
    expect(a.getAttribute("href")).toBe("#archiv/2026-04");
    expect(a.textContent).toBe("April 2026");
    expect(c.textContent).toContain("100 Züge");
  });

  it("never injects markup from tampered numeric fields", async () => {
    mockIndex([month({
      total: '<img src=x onerror="window.__pwned=1">',
      on_time: "<script>window.__pwned=1</script>",
      late: { evil: true },
      cancelled: null,
    })]);
    const c = document.createElement("div");
    await renderArchiveList(c);
    expect(c.querySelector("img")).toBeNull();
    expect(c.querySelector("script")).toBeNull();
    expect((window as { __pwned?: number }).__pwned).toBeUndefined();
    expect(c.textContent).toContain("0 Züge");
  });

  it("never renders a month whose period carries a payload (filtered at load)", async () => {
    mockIndex([month({}), month({ period: '"><img src=x onerror="window.__pwned=1">' })]);
    const c = document.createElement("div");
    await renderArchiveList(c);
    expect(c.querySelectorAll(".month-links li")).toHaveLength(1);
    expect(c.querySelector("img")).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify the hostile-numerics case fails**

Run: `npx vitest run src/pages/archive-list.test.ts`
Expected: test 1 and 3 PASS (Task 3 already filters periods), test 2 FAILS (`<img>` element present / `0 Züge` missing).

- [ ] **Step 3: Implement**

Replace `site/src/pages/archive-list.ts` in full:

```ts
import { loadIndex } from "../archive.js";
import { escapeHtml, germanMonth, num } from "../data.js";
import { renderMonthsBar } from "../charts/monthsBar.js";

export async function renderArchiveList(container: HTMLElement): Promise<void> {
  let idx;
  try {
    idx = await loadIndex();
  } catch {
    container.innerHTML = `<p class="error">Archivdaten nicht verfügbar</p>`;
    return;
  }

  const last12 = idx.months.slice(-12);

  container.innerHTML = `
    <h2>Archiv - S7 Baierbrunn</h2>
    <section class="months-overview">
      <h3>Letzte 12 Monate</h3>
      <div class="chart-container">
        <canvas id="chart-months-bar"></canvas>
      </div>
    </section>
    <section class="months-list">
      <h3>Alle Monate</h3>
      <ul class="month-links">
        ${idx.months.slice().reverse().map((m) => `
          <li>
            <a href="#archiv/${escapeHtml(m.period)}">${escapeHtml(germanMonth(m.period))}</a>
            <span class="month-summary">
              ${num(m.total)} Züge · ${num(m.on_time)} pünktlich · ${num(m.late)} verspätet · ${num(m.cancelled)} ausgefallen
              ${m.finalized ? "" : " <em>(läuft)</em>"}
            </span>
          </li>`).join("")}
      </ul>
    </section>
  `;

  renderMonthsBar("chart-months-bar", last12);
}
```

(The local `germanMonth` copy is deleted; the shared one comes from `data.js`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/pages/archive-list.test.ts`
Expected: PASS (3/3).

- [ ] **Step 5: Commit**

```bash
git add site/src/pages/archive-list.ts site/src/pages/archive-list.test.ts
git commit -m "fix(site): escape and coerce archive index fields in month list (XSS)"
```

---

### Task 5: harden `archive-detail.ts` rendering

**Files:**
- Modify: `site/src/pages/archive-detail.ts`
- Test: `site/src/pages/archive-detail.test.ts`

Unescaped sites: `germanMonth(period)` in `<h2>` (line 67), `agg.on_time`/`agg.late`/`agg.cancelled`/`agg.avg_delay_min` in the summary bar (69-72), per-row `a.scheduled_time.slice(0,10)` / `fmtTime(...)` slices (87-89) and `${a.delay_minutes ?? 0}` (90). The route already regex-validates `period`, so `germanMonth`/`archiveJsonUrl` inputs are safe; escape anyway for consistency. `arc.arrivals.length` is an array length, safe.

- [ ] **Step 1: Write the failing test**

Append to `site/src/pages/archive-detail.test.ts` (extend the vitest import with `beforeEach`/`vi`, and add imports):

```ts
import { renderArchiveDetail } from "./archive-detail.js";
import { _resetCache } from "../archive.js";

vi.mock("../charts/dailyByDirection.js", () => ({ renderDailyByDirection: vi.fn() }));

describe("renderArchiveDetail hostile JSON", () => {
  beforeEach(() => {
    _resetCache();
    vi.restoreAllMocks();
  });

  it("never injects markup from tampered aggregate or arrival fields", async () => {
    const hostile = {
      generated_at: "x", station: "Baierbrunn", line: "S7",
      period: "2026-04", finalized: true,
      arrivals: [a({
        scheduled_time: '<img src=x onerror="window.__pwned=1">T<svg>',
        actual_time: "<script>1</script>T<b>x</b>",
        delay_minutes: '<img src=x onerror="window.__pwned=1">',
      })],
      aggregates: {
        total: 1, on_time: '<img src=x onerror="window.__pwned=1">',
        late: "<script>1</script>", cancelled: 0, avg_delay_min: {},
        by_direction: {
          muenchen:       { total: 1, on_time: 1, late: 0, cancelled: 0, avg_delay_min: 0 },
          wolfratshausen: { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0 },
        },
      },
      daily: [],
      daily_by_direction: { muenchen: [], wolfratshausen: [] },
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(hostile), { status: 200 }) as Response,
    );
    const c = document.createElement("div");
    await renderArchiveDetail("2026-04", c);
    expect(c.querySelector("img")).toBeNull();
    expect(c.querySelector("script")).toBeNull();
    expect(c.querySelector("svg")).toBeNull();
    expect(c.querySelector("table b")).toBeNull();
    expect((window as { __pwned?: number }).__pwned).toBeUndefined();
    expect(c.textContent).toContain("0 pünktlich");
    expect(c.textContent).toContain("April 2026");
  });
});
```

Note: the existing fake-timer-free file has no `beforeEach`; the new block scopes its own. The existing `a()` fixture helper is reused.

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/pages/archive-detail.test.ts`
Expected: new test FAILS (img/script elements found). Existing `endpunktCell` tests PASS.

- [ ] **Step 3: Implement**

In `site/src/pages/archive-detail.ts`:

1. Replace the import block's `data.js` line and delete the local `germanMonth` (lines 6-11):

```ts
import { escapeHtml, germanMonth, num, terminusLabelShort } from "../data.js";
```

2. Harden `fmtTime` (slices of attacker strings stay strings):

```ts
function fmtTime(iso: string): string {
  return escapeHtml(String(iso).slice(11, 16));
}
```

3. In the `container.innerHTML` template, change exactly these interpolations:

```ts
    <h2>${escapeHtml(germanMonth(period))} - S7 Baierbrunn ${arc.finalized ? "" : "<em>(läuft)</em>"}</h2>
```

```ts
      <span class="summary-item summary-item--ok">✓ ${num(agg.on_time)} pünktlich</span>
      <span class="summary-item summary-item--late">⏱ ${num(agg.late)} verspätet</span>
      <span class="summary-item summary-item--cancelled">✕ ${num(agg.cancelled)} ausgefallen</span>
      <span class="summary-item">Ø ${num(agg.avg_delay_min)} min Verspätung</span>
```

```ts
              <td>${escapeHtml(String(a.scheduled_time).slice(0, 10))}</td>
              <td>${fmtTime(a.scheduled_time)}</td>
              <td>${a.actual_time ? fmtTime(a.actual_time) : "-"}</td>
              <td>${num(a.delay_minutes)} min</td>
              <td>${escapeHtml(a.direction)}</td>
              <td>${a.cancelled ? "Ausgefallen" : (num(a.delay_minutes) > 0 ? "Verspätet" : "Pünktlich")}</td>
```

(`num(a.delay_minutes)` keeps the `?? 0` semantics: `Number(null)` is 0. Negative values still display raw - that is finding M2, out of scope here.)

Also fix the error path at line 60 to use the now-escaping convention unchanged: `escapeHtml(germanMonth(period))` (it already escapes; just confirm it compiles against the shared import).

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/pages/archive-detail.test.ts`
Expected: PASS (all, including existing `endpunktCell` suite).

- [ ] **Step 5: Commit**

```bash
git add site/src/pages/archive-detail.ts site/src/pages/archive-detail.test.ts
git commit -m "fix(site): escape and coerce archive month fields in detail view (XSS)"
```

---

### Task 6: harden `today.ts` aggregate rendering

**Files:**
- Modify: `site/src/pages/today.ts`
- Test: `site/src/pages/today.test.ts`

Unguarded sites: `summaryBar` interpolates `agg.on_time`/`agg.late`/`agg.cancelled` (lines 134-136) and the totals line interpolates `agg.total`/`agg.avg_delay_min` (line 220) straight from `latest.json`. `term.*` values are computed frontend-side in `terminusAggregate` (real numbers), safe. `statusBadge`/`fmtDeparture` interpolate `a.delay_minutes` only behind a `> 0` comparison (a payload string compares NaN-false), but coerce them too so safety does not hang on comparison semantics.

- [ ] **Step 1: Write the failing test**

Append to `site/src/pages/today.test.ts` (reuses the existing `arrival`/`fixture` helpers and fake-timer `beforeEach`):

```ts
describe("hostile aggregates from latest.json", () => {
  it("never injects markup from tampered numeric fields", () => {
    const data = fixture([arrival({})]);
    const pwn = '<img src=x onerror="window.__pwned=1">';
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const agg = data.aggregates.today as any;
    agg.total = pwn;
    agg.avg_delay_min = "<script>1</script>";
    agg.by_direction.muenchen.on_time = pwn;
    agg.by_direction.muenchen.late = pwn;
    agg.by_direction.muenchen.cancelled = pwn;
    const c = document.createElement("div");
    renderToday(data, c);
    expect(c.querySelector("img")).toBeNull();
    expect(c.querySelector("script")).toBeNull();
    expect((window as { __pwned?: number }).__pwned).toBeUndefined();
    expect(c.textContent).toContain("0 pünktlich");
    expect(c.textContent).toContain("0 Züge");
  });

  it("never injects markup from a tampered per-train delay", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = renderInto([arrival({ delay_minutes: '"><img src=x onerror="window.__pwned=1">' as any })]);
    expect(c.querySelector("img")).toBeNull();
    expect((window as { __pwned?: number }).__pwned).toBeUndefined();
  });
});
```

(Note: `.eslintrc.cjs` disables `no-explicit-any`, so the disable comments are belt-and-braces; keep them only if lint complains, otherwise drop them.)

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/pages/today.test.ts`
Expected: first new test FAILS (img element in summary bar). Second may already pass via the `> 0` guard - keep it as a regression test either way. Existing tests PASS.

- [ ] **Step 3: Implement**

In `site/src/pages/today.ts`:

1. Extend the `data.js` import:

```ts
import { unifiedTodayRows, escapeHtml, num, terminusLabelLong, terminusLabelShort, terminusAggregate } from "../data.js";
```

2. `statusBadge` (lines 42-46):

```ts
function statusBadge(a: Arrival): string {
  if (a.cancelled) return `<span class="badge badge--cancelled">ausgefallen</span>`;
  const m = num(a.delay_minutes);
  if (m > 0) return `<span class="badge badge--late">+${m} min</span>`;
  return `<span class="badge badge--ok">pünktlich</span>`;
}
```

3. `fmtDeparture` (line 51): `const m = num(a.delay_minutes);` (replaces `a.delay_minutes ?? 0`).

4. `summaryBar` (lines 133-139):

```ts
  return [
    `<span class="summary-item summary-item--ok">✓ ${num(agg.on_time)} pünktlich</span>`,
    `<span class="summary-item summary-item--late">⏱ ${num(agg.late)} verspätet</span>`,
    `<span class="summary-item summary-item--cancelled">✕ ${num(agg.cancelled)} ausgefallen</span>`,
    num(agg.missing) > 0 ? `<span class="summary-item summary-item--missing">? ${num(agg.missing)} keine Daten</span>` : "",
    ...termItems,
  ].filter(Boolean).join("");
```

5. Totals line (line 220):

```ts
      <summary>Gesamt heute: ${num(agg.total)} Züge · Ø ${num(agg.avg_delay_min)} min Verspätung</summary>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/pages/today.test.ts`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add site/src/pages/today.ts site/src/pages/today.test.ts
git commit -m "fix(site): coerce latest.json numeric fields in today view (XSS)"
```

---

### Task 7: harden `weekKpi.ts`

**Files:**
- Modify: `site/src/charts/weekKpi.ts`
- Test: `site/src/charts/weekKpi.test.ts`

`cardHtml` interpolates `agg.cancelled` raw (injectable) and calls `agg.avg_delay_min.toFixed()` (a tampered string throws TypeError, killing the whole week page render).

- [ ] **Step 1: Write the failing test**

Append to `site/src/charts/weekKpi.test.ts` (match the file's existing import/render conventions when editing):

```ts
describe("hostile aggregates", () => {
  it("never injects markup and does not throw on tampered fields", () => {
    const c = document.createElement("div");
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hostile: any = {
      muenchen:       { avg_delay_min: '<img src=x onerror="window.__pwned=1">', cancelled: "<script>1</script>" },
      wolfratshausen: { avg_delay_min: 1.5, cancelled: 2 },
    };
    renderWeekKpiStrip(c, hostile);
    expect(c.querySelector("img")).toBeNull();
    expect(c.querySelector("script")).toBeNull();
    expect((window as { __pwned?: number }).__pwned).toBeUndefined();
    expect(c.textContent).toContain("Ø 0,0 min");
    expect(c.textContent).toContain("Ø 1,5 min");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/charts/weekKpi.test.ts`
Expected: new test FAILS (TypeError from `.toFixed` on a string, or injected markup).

- [ ] **Step 3: Implement**

In `site/src/charts/weekKpi.ts`:

```ts
import { num } from "../data.js";
import type { DirectionAggregate } from "../data.js";
```

and in `cardHtml`:

```ts
  const cancelled = num(agg.cancelled);
  return `
    <div class="kpi-card">
      <div class="kpi-card__title">→ ${label}</div>
      <div class="kpi-card__stats">Ø ${formatMin(num(agg.avg_delay_min))} min · ${cancelled} ${ausfallWord(cancelled)}</div>
    </div>
  `;
```

(`label` stays as-is: both call sites pass literals.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/charts/weekKpi.test.ts`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add site/src/charts/weekKpi.ts site/src/charts/weekKpi.test.ts
git commit -m "fix(site): coerce week KPI numeric fields (XSS, render crash)"
```

---

### Task 8: full verification, changelog, plan file

**Files:**
- Modify: `CHANGELOG.md`
- Add: `docs/superpowers/plans/2026-06-10-fix-xss-data-repo.md` (this file - CLAUDE.md requires plan files committed with the implementation PR)

- [ ] **Step 1: Run the full site verification suite**

```bash
cd site
npm test
npm run lint
npm run build
```

Expected: all tests PASS, lint clean, `tsc --noEmit` + Vite build succeed.

- [ ] **Step 2: Add changelog entry**

Under `## [Unreleased]` / `### Fixed` in `CHANGELOG.md` (create the subsection if absent):

```markdown
- Stored XSS via the s7bb-data repo: archive index periods are now validated at load, and all JSON-derived strings/numerics rendered into `innerHTML` are escaped or coerced (`archive-list`, `archive-detail`, `today`, week KPI strip).
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md docs/superpowers/plans/2026-06-10-fix-xss-data-repo.md
git commit -m "docs: changelog and plan for data-repo XSS fix"
```

- [ ] **Step 4: Release note for the executor**

This is a `fix` with semver impact: per CLAUDE.md, after the PR merges to `main`, cut a PATCH release (bump `fetcher/pyproject.toml` version, `uv sync --no-dev` in `fetcher/`, changelog rename, `chore(release): X.Y.Z` commit, tag, GitHub Release). Use the dot-escaped explicit-end awk form for release notes (known gotcha: the CLAUDE.md one-liner yields an empty body) and verify the notes body before declaring done.

---

## Self-review checklist (done at plan time)

- Spec coverage: H1 fix = escape `m.period`/`germanMonth` (Task 4), validate period when rendering the index (Task 3 at load boundary - stronger), coerce numerics across archive-list/archive-detail/today/weekKpi (Tasks 4-7). All elements of the finding have tasks.
- `num()` defined in Task 1, used identically in Tasks 4-7; `germanMonth(period: string): string` defined in Task 2, imported in Tasks 4-5. Signatures consistent.
- Out-of-scope findings (M2 negative floor, H3 UTC times, M1 bucketing) explicitly preserved: `num()` keeps negatives, slices unchanged.
- No placeholders: every step carries the actual code, command, and expected result.
