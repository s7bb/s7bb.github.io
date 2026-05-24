# Terminus arrival UI (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface per-train terminus outcome (arrived / short-turn / missed / pending) on the today page (inline outcome line + tap-to-expand panel + summary-bar counters) and on the archive detail page (Endpunkt column).

**Architecture:** UI-only. All terminus fields are already on `Arrival` (`terminus_status`, `terminus_delay_minutes`, `terminus_short_turn_station`) via Phase 1 + v0.7.x–v0.8.3. Adds helpers in `data.ts`, extends `pages/today.ts` to render `<details>`/`<summary>` rows with an inline outcome line and detail panel, extends `pages/archive-detail.ts` with one new column, adds CSS classes for the new states. No fetcher, exporter, or data-layer change. Strict TDD: every behavior covered by an extended or new vitest case before the implementation.

**Tech Stack:** TypeScript, Vite, vitest, native `<details>`/`<summary>` (no JS toggle), plain CSS reusing the existing `--orange`/`--red`/`--green`/`--border` palette.

**Spec:** [`docs/superpowers/specs/2026-05-24-terminus-ui-design.md`](../specs/2026-05-24-terminus-ui-design.md)

---

## File map

| File | Status | Responsibility |
|---|---|---|
| `site/src/data.ts` | modify | Add `terminusLabelLong`, `terminusLabelShort`, `TerminusAggregate`, `terminusAggregate()`. |
| `site/src/data.test.ts` | extend | Tests for `terminusAggregate` (4 cases). |
| `site/src/pages/today.ts` | modify | Add `terminusLine(a)`, `detailPanel(a)`, convert `rowFor()` to `<details>`/`<summary>`, extend `summaryBar()` to take a terminus aggregate, move reason from summary row to panel. |
| `site/src/pages/today.test.ts` | extend | Full state-matrix coverage + panel content + bar counters + Baierbrunn-cancelled cases (~20 cases). |
| `site/src/pages/archive-detail.ts` | modify | Add `endpunktCell(a)` helper + `Endpunkt` `<th>`/`<td>` column. |
| `site/src/pages/archive-detail.test.ts` | create | New file. 5 cases for the column renderer. |
| `site/src/style.css` | modify | New classes: `.terminus-line` variants, `details.arrival-row > summary` reset, `.chev`, `.arrival-detail`, `.detail-row`, `.detail-label`, `.detail-value`, `.endpunkt--*`. |

## TDD pattern for DOM tests

Tests render into a `document.createElement("div")` and assert on `container.querySelector(...)` / `textContent` / `classList.contains(...)`. There's no existing `today.test.ts` rendering harness yet (current file only tests `nextUpdate`); Task 2 below introduces a tiny `renderInto(arrivals, expectedSlots?)` helper inside the test file.

---

## Task 1: Helpers `terminusLabelLong` / `terminusLabelShort` + `terminusAggregate`

**Files:**
- Modify: `site/src/data.ts` (append after `directionLabel`)
- Test: `site/src/data.test.ts` (extend)

- [ ] **Step 1: Write failing tests for the label helpers**

Add to `site/src/data.test.ts` (after existing imports add `terminusLabelLong, terminusLabelShort, terminusAggregate`):

```ts
import {
  last7DaysByDayBothDirections,
  terminusLabelLong,
  terminusLabelShort,
  terminusAggregate,
} from "./data.js";

describe("terminusLabelLong", () => {
  it("returns 'München Hbf' for muenchen", () => {
    expect(terminusLabelLong("muenchen")).toBe("München Hbf");
  });
  it("returns 'Wolfratshausen' for wolfratshausen", () => {
    expect(terminusLabelLong("wolfratshausen")).toBe("Wolfratshausen");
  });
});

describe("terminusLabelShort", () => {
  it("returns 'München' for muenchen", () => {
    expect(terminusLabelShort("muenchen")).toBe("München");
  });
  it("returns 'Wolfratshausen' for wolfratshausen", () => {
    expect(terminusLabelShort("wolfratshausen")).toBe("Wolfratshausen");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd site && npx vitest run src/data.test.ts`
Expected: FAIL — `terminusLabelLong is not a function` (or similar import error).

- [ ] **Step 3: Implement the two helpers**

Append to `site/src/data.ts`:

```ts
export function terminusLabelLong(bucket: "muenchen" | "wolfratshausen"): string {
  return bucket === "muenchen" ? "München Hbf" : "Wolfratshausen";
}

export function terminusLabelShort(bucket: "muenchen" | "wolfratshausen"): string {
  return bucket === "muenchen" ? "München" : "Wolfratshausen";
}
```

- [ ] **Step 4: Run tests to verify label helpers pass**

Run: `cd site && npx vitest run src/data.test.ts`
Expected: PASS for the four new label cases.

- [ ] **Step 5: Write failing tests for `terminusAggregate`**

Append to `site/src/data.test.ts`:

```ts
describe("terminusAggregate", () => {
  // Tests use VITE_DEV_NOW-free `arrival` factory; aggregator filters by
  // Berlin "today" — fix system clock via vi.setSystemTime so dates compare.
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-01T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("counts arrived, short_turn, missed (=cancelled), pending per bucket", () => {
    const arrivals = [
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", terminus_status: "arrived" }),
      arrival({ scheduled_time: "2026-05-01T08:30:00", direction_bucket: "muenchen", terminus_status: "arrived" }),
      arrival({ scheduled_time: "2026-05-01T09:00:00", direction_bucket: "muenchen", terminus_status: "short_turn", terminus_short_turn_station: "München-Solln" }),
      arrival({ scheduled_time: "2026-05-01T09:30:00", direction_bucket: "muenchen", terminus_status: "cancelled" }),
      arrival({ scheduled_time: "2026-05-01T10:00:00", direction_bucket: "muenchen", terminus_status: "pending" }),
    ];
    const agg = terminusAggregate(arrivals, "muenchen");
    expect(agg).toEqual({ arrived: 2, short_turn: 1, missed: 1, pending: 1 });
  });

  it("excludes Baierbrunn-cancelled rows entirely", () => {
    const arrivals = [
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", cancelled: true, terminus_status: "cancelled" }),
      arrival({ scheduled_time: "2026-05-01T09:00:00", direction_bucket: "muenchen", terminus_status: "arrived" }),
    ];
    expect(terminusAggregate(arrivals, "muenchen")).toEqual({ arrived: 1, short_turn: 0, missed: 0, pending: 0 });
  });

  it("excludes rows with null/undefined terminus_status", () => {
    const arrivals = [
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", terminus_status: null }),
      arrival({ scheduled_time: "2026-05-01T08:30:00", direction_bucket: "muenchen" }), // undefined
      arrival({ scheduled_time: "2026-05-01T09:00:00", direction_bucket: "muenchen", terminus_status: "arrived" }),
    ];
    expect(terminusAggregate(arrivals, "muenchen")).toEqual({ arrived: 1, short_turn: 0, missed: 0, pending: 0 });
  });

  it("filters by Berlin 'today' date and by direction_bucket", () => {
    const arrivals = [
      arrival({ scheduled_time: "2026-04-30T22:00:00Z", direction_bucket: "muenchen", terminus_status: "arrived" }), // not today
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", terminus_status: "arrived" }),
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "wolfratshausen", terminus_status: "arrived" }),
    ];
    expect(terminusAggregate(arrivals, "muenchen")).toEqual({ arrived: 1, short_turn: 0, missed: 0, pending: 0 });
    expect(terminusAggregate(arrivals, "wolfratshausen")).toEqual({ arrived: 1, short_turn: 0, missed: 0, pending: 0 });
  });
});
```

Also add `vi` and `beforeEach`/`afterEach` to the top imports:

```ts
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd site && npx vitest run src/data.test.ts`
Expected: FAIL — `terminusAggregate is not a function`.

- [ ] **Step 7: Implement `terminusAggregate`**

Append to `site/src/data.ts`. Reuse the existing private `berlinDate(iso)` + `nowForFiltering()` helpers (already defined above in the file).

```ts
export interface TerminusAggregate {
  arrived: number;
  short_turn: number;
  missed: number;   // terminus_status === "cancelled"
  pending: number;
}

export function terminusAggregate(
  arrivals: Arrival[],
  bucket: "muenchen" | "wolfratshausen",
): TerminusAggregate {
  const today = berlinDate(nowForFiltering());
  const out: TerminusAggregate = { arrived: 0, short_turn: 0, missed: 0, pending: 0 };
  for (const a of arrivals) {
    if (a.direction_bucket !== bucket) continue;
    if (berlinDate(a.scheduled_time) !== today) continue;
    if (a.cancelled) continue;
    switch (a.terminus_status) {
      case "arrived":    out.arrived++;    break;
      case "short_turn": out.short_turn++; break;
      case "cancelled":  out.missed++;     break;
      case "pending":    out.pending++;    break;
      default: /* null/undefined: excluded */ break;
    }
  }
  return out;
}
```

- [ ] **Step 8: Run all data tests to verify pass**

Run: `cd site && npx vitest run src/data.test.ts`
Expected: PASS for all `terminusAggregate` and label cases plus existing `last7DaysByDayBothDirections`.

- [ ] **Step 9: Commit**

```bash
git add site/src/data.ts site/src/data.test.ts
git commit -m "feat(site): terminus label + aggregate helpers"
```

---

## Task 2: `terminusLine()` helper + state-matrix tests

Renders the inline outcome line below `arrival-direction`. Returns `""` for the "silent" cases (on-time / null / Baierbrunn-cancelled).

**Files:**
- Modify: `site/src/pages/today.ts` (add helper + export `terminusLine` for test)
- Test: `site/src/pages/today.test.ts` (extend)

- [ ] **Step 1: Add a minimal render harness to the test file**

Replace the top of `site/src/pages/today.test.ts` with:

```ts
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { nextUpdate, renderToday } from "./today.js";
import type { S7Data, Arrival } from "../data.js";

function arrival(overrides: Partial<Arrival>): Arrival {
  return {
    train_id: "x",
    line: "S7",
    station: "Baierbrunn",
    direction: "München Hbf",
    direction_bucket: "muenchen",
    scheduled_time: "2026-05-01T08:00:00",
    actual_time: null,
    delay_minutes: 0,
    cancelled: false,
    reason: null,
    train_number: null,
    terminus_status: null,
    terminus_delay_minutes: null,
    terminus_short_turn_station: null,
    ...overrides,
  };
}

function fixture(arrivals: Arrival[]): S7Data {
  return {
    generated_at: "2026-05-01T08:00:00Z",
    station: "Baierbrunn",
    line: "S7",
    window_days: 7,
    arrivals,
    aggregates: {
      today: {
        total: arrivals.length, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0,
        by_direction: {
          muenchen:       { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0 },
          wolfratshausen: { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0 },
        },
      },
      last_7_days: {
        total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0,
        by_direction: {
          muenchen:       { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0 },
          wolfratshausen: { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0 },
        },
      },
    },
    expected_slots: { today: { muenchen: arrivals.map((a) => a.scheduled_time), wolfratshausen: [] } },
  };
}

function renderInto(arrivals: Arrival[]): HTMLElement {
  const c = document.createElement("div");
  renderToday(fixture(arrivals), c);
  return c;
}

// Fix system clock so the Berlin-today filter in arrivalsByDirection / terminusAggregate is deterministic.
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-05-01T12:00:00Z"));
});
afterEach(() => {
  vi.useRealTimers();
});
```

(Keep the existing `describe("nextUpdate", ...)` block below.)

- [ ] **Step 2: Add failing tests for the inline outcome line state matrix**

Append to `site/src/pages/today.test.ts`:

```ts
describe("terminus inline line", () => {
  it("renders no terminus line when terminus_status is arrived and terminus_delay_minutes <= 0", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", terminus_delay_minutes: 0 })]);
    expect(c.querySelector(".terminus-line")).toBeNull();
  });

  it("renders 'München Hbf +7 min' with --late class when arrived and terminus delay >= 5", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", terminus_delay_minutes: 7 })]);
    const el = c.querySelector(".terminus-line");
    expect(el?.textContent).toContain("→ München Hbf +7 min");
    expect(el?.classList.contains("terminus-line--late")).toBe(true);
  });

  it("renders '+2 min' with --late-mild class when arrived and 0 < terminus delay < 5", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", terminus_delay_minutes: 2 })]);
    const el = c.querySelector(".terminus-line");
    expect(el?.textContent).toContain("→ München Hbf +2 min");
    expect(el?.classList.contains("terminus-line--late-mild")).toBe(true);
  });

  it("renders 'nur bis Solln' with --shortturn class when terminus_status is short_turn", () => {
    const c = renderInto([arrival({ terminus_status: "short_turn", terminus_short_turn_station: "Solln" })]);
    const el = c.querySelector(".terminus-line");
    expect(el?.textContent).toContain("→ nur bis Solln");
    expect(el?.classList.contains("terminus-line--shortturn")).toBe(true);
  });

  it("renders 'nicht in München angekommen' with --missed class when terminus_status is cancelled", () => {
    const c = renderInto([arrival({ terminus_status: "cancelled" })]);
    const el = c.querySelector(".terminus-line");
    expect(el?.textContent).toContain("→ nicht in München angekommen");
    expect(el?.classList.contains("terminus-line--missed")).toBe(true);
  });

  it("renders 'unterwegs' with --pending class when terminus_status is pending", () => {
    const c = renderInto([arrival({ terminus_status: "pending" })]);
    const el = c.querySelector(".terminus-line");
    expect(el?.textContent).toContain("→ unterwegs");
    expect(el?.classList.contains("terminus-line--pending")).toBe(true);
  });

  it("renders no terminus line when terminus_status is null", () => {
    const c = renderInto([arrival({ terminus_status: null })]);
    expect(c.querySelector(".terminus-line")).toBeNull();
  });

  it("renders no terminus line when train is Baierbrunn-cancelled (existing strike-through preserved)", () => {
    const c = renderInto([arrival({ cancelled: true, terminus_status: "cancelled" })]);
    expect(c.querySelector(".terminus-line")).toBeNull();
    expect(c.querySelector(".arrival-row--cancelled")).not.toBeNull();
  });

  it("falls back to missed line when short_turn but terminus_short_turn_station is null", () => {
    const c = renderInto([arrival({ terminus_status: "short_turn", terminus_short_turn_station: null })]);
    const el = c.querySelector(".terminus-line");
    expect(el?.textContent).toContain("→ nicht in München angekommen");
    expect(el?.classList.contains("terminus-line--missed")).toBe(true);
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd site && npx vitest run src/pages/today.test.ts`
Expected: FAIL — `.terminus-line` selector returns null everywhere.

- [ ] **Step 4: Implement `terminusLine()` in `today.ts`**

Update imports at top of `site/src/pages/today.ts`:

```ts
import type { S7Data, UnifiedSlotRow, DirectionAggregate } from "../data.js";
import { unifiedTodayRows, escapeHtml, terminusLabelLong, terminusLabelShort, terminusAggregate } from "../data.js";
import type { Arrival, TerminusAggregate } from "../data.js";
```

Add this helper above `rowFor` (`statusBadge` stays where it is):

```ts
// Inline outcome line: exception bias — silent when terminus arrival was OK,
// visible when something went wrong or is still pending. Returns "" for the
// silent cases (caller inserts no element).
function terminusLine(a: Arrival): string {
  if (a.cancelled) return "";
  const long = a.direction_bucket === "muenchen" || a.direction_bucket === "wolfratshausen"
    ? terminusLabelLong(a.direction_bucket)
    : "";
  switch (a.terminus_status) {
    case "arrived": {
      const m = Math.max(0, a.terminus_delay_minutes ?? 0);
      if (m <= 0) return "";
      const cls = m >= 5 ? "terminus-line--late" : "terminus-line--late-mild";
      return `<span class="terminus-line ${cls}">→ ${escapeHtml(long)} +${m} min</span>`;
    }
    case "short_turn": {
      if (!a.terminus_short_turn_station) {
        // Phase-1 contract violation; log + fall through to missed.
        console.warn("terminus_status=short_turn with null station for train", a.train_id);
        return `<span class="terminus-line terminus-line--missed">→ nicht in ${escapeHtml(long.replace(/ Hbf$/, ""))} angekommen</span>`;
      }
      return `<span class="terminus-line terminus-line--shortturn">→ nur bis ${escapeHtml(a.terminus_short_turn_station)}</span>`;
    }
    case "cancelled":
      return `<span class="terminus-line terminus-line--missed">→ nicht in ${escapeHtml(long.replace(/ Hbf$/, ""))} angekommen</span>`;
    case "pending":
      return `<span class="terminus-line terminus-line--pending">→ unterwegs …</span>`;
    default:
      return "";
  }
}
```

Wire it into `rowFor` (temporarily — Task 3 will replace this with `<details>`):

```ts
function rowFor(slot: string, a: Arrival | null): string {
  const time = formatTime(slot);
  if (!a) {
    return `
      <div class="arrival-row arrival-row--empty">
        <span class="arrival-time">${time}</span>
        <span class="arrival-empty">—</span>
      </div>`;
  }
  const cancelledCls = a.cancelled ? " arrival-row--cancelled" : "";
  return `
    <div class="arrival-row${cancelledCls}">
      <span class="arrival-time">${time}</span>
      <span class="arrival-direction">${escapeHtml(a.direction)}</span>
      ${statusBadge(a)}
      ${terminusLine(a)}
      ${a.reason ? `<span class="arrival-reason">${escapeHtml(a.reason)}</span>` : ""}
    </div>`;
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd site && npx vitest run src/pages/today.test.ts`
Expected: PASS for the new `terminus inline line` block plus existing `nextUpdate` tests.

- [ ] **Step 6: Commit**

```bash
git add site/src/pages/today.ts site/src/pages/today.test.ts
git commit -m "feat(site): inline terminus outcome line"
```

---

## Task 3: Convert each arrival row to `<details>` / `<summary>` with detail panel

Replaces the `<div class="arrival-row">` with `<details class="arrival-row"><summary>…</summary><div class="arrival-detail">…</div></details>`, moves `reason` out of the summary and into the panel, adds `Abfahrt Baierbrunn` + conditional `Ankunft {terminus}` + conditional `Endete in` + conditional `Zug` + conditional `Grund` rows.

**Files:**
- Modify: `site/src/pages/today.ts`
- Test: `site/src/pages/today.test.ts`

- [ ] **Step 1: Write failing tests for the structural wrap + panel content**

Append to `site/src/pages/today.test.ts`:

```ts
describe("arrival row <details> wrapper", () => {
  it("wraps each non-empty row in a details element with a summary", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", terminus_delay_minutes: 0 })]);
    const det = c.querySelector("details.arrival-row");
    expect(det).not.toBeNull();
    expect(det?.querySelector(":scope > summary")).not.toBeNull();
    expect(det?.querySelector(":scope > .arrival-detail")).not.toBeNull();
  });

  it("keeps empty (no-record) slots as plain div without details wrapper", () => {
    // Force a missing slot: expected_slots includes a time, arrivals is empty.
    const data = fixture([]);
    data.expected_slots.today.muenchen = ["2026-05-01T07:00:00"];
    const c = document.createElement("div");
    renderToday(data, c);
    expect(c.querySelector("details.arrival-row")).toBeNull();
    expect(c.querySelector(".arrival-row--empty")).not.toBeNull();
  });

  it("default state is collapsed (no [open] attribute on initial render)", () => {
    const c = renderInto([arrival({ terminus_status: "arrived" })]);
    const det = c.querySelector("details.arrival-row");
    expect(det?.hasAttribute("open")).toBe(false);
  });

  it("summary always contains time, direction, status badge", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", terminus_delay_minutes: 0 })]);
    const sum = c.querySelector("details.arrival-row > summary")!;
    expect(sum.querySelector(".arrival-time")).not.toBeNull();
    expect(sum.querySelector(".arrival-direction")).not.toBeNull();
    expect(sum.querySelector(".badge")).not.toBeNull();
  });

  it("summary contains chevron with aria-hidden", () => {
    const c = renderInto([arrival({ terminus_status: "arrived" })]);
    const chev = c.querySelector("details.arrival-row > summary .chev");
    expect(chev).not.toBeNull();
    expect(chev?.getAttribute("aria-hidden")).toBe("true");
  });
});

function panelOf(c: HTMLElement): HTMLElement {
  return c.querySelector("details.arrival-row > .arrival-detail") as HTMLElement;
}
function detailValue(panel: HTMLElement, label: string): string | undefined {
  const rows = panel.querySelectorAll(".detail-row");
  for (const r of rows) {
    if (r.querySelector(".detail-label")?.textContent?.trim().startsWith(label)) {
      return r.querySelector(".detail-value")?.textContent?.trim();
    }
  }
  return undefined;
}

describe("expand panel content", () => {
  it("Abfahrt Baierbrunn shows HH:MM (planmäßig) when on time", () => {
    const c = renderInto([arrival({ scheduled_time: "2026-05-01T08:42:00", delay_minutes: 0, terminus_status: "arrived" })]);
    expect(detailValue(panelOf(c), "Abfahrt Baierbrunn")).toBe("08:42 (planmäßig)");
  });

  it("Abfahrt Baierbrunn shows HH:MM (+N min) when delayed", () => {
    const c = renderInto([arrival({ scheduled_time: "2026-05-01T08:42:00", delay_minutes: 3, terminus_status: "arrived" })]);
    expect(detailValue(panelOf(c), "Abfahrt Baierbrunn")).toBe("08:42 (+3 min)");
  });

  it("Abfahrt Baierbrunn shows 'ausgefallen' for Baierbrunn-cancelled", () => {
    const c = renderInto([arrival({ scheduled_time: "2026-05-01T08:42:00", cancelled: true })]);
    expect(detailValue(panelOf(c), "Abfahrt Baierbrunn")).toBe("ausgefallen");
  });

  it("Ankunft uses terminus_delay_minutes, not Baierbrunn delay", () => {
    const c = renderInto([arrival({
      scheduled_time: "2026-05-01T08:42:00",
      delay_minutes: 0,
      terminus_status: "arrived",
      actual_time: "2026-05-01T08:42:00",
      terminus_delay_minutes: 3,
    })]);
    expect(detailValue(panelOf(c), "Ankunft München Hbf")).toMatch(/\+3 min/);
  });

  it("Ankunft floors negative terminus delays at 0", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", terminus_delay_minutes: -2 })]);
    expect(detailValue(panelOf(c), "Ankunft München Hbf")).toMatch(/\+0 min/);
  });

  it("Ankunft shows 'planmäßig' with no time when arrived and terminus_delay_minutes is null", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", terminus_delay_minutes: null })]);
    expect(detailValue(panelOf(c), "Ankunft München Hbf")).toBe("planmäßig");
  });

  it("Ankunft shows 'noch unterwegs' when pending", () => {
    const c = renderInto([arrival({ terminus_status: "pending" })]);
    expect(detailValue(panelOf(c), "Ankunft München Hbf")).toBe("noch unterwegs");
  });

  it("Ankunft shows 'nicht angekommen' when cancelled", () => {
    const c = renderInto([arrival({ terminus_status: "cancelled" })]);
    expect(detailValue(panelOf(c), "Ankunft München Hbf")).toBe("nicht angekommen");
  });

  it("Ankunft row omitted when terminus_status is null", () => {
    const c = renderInto([arrival({ terminus_status: null })]);
    expect(detailValue(panelOf(c), "Ankunft")).toBeUndefined();
  });

  it("Endete in row only when short_turn", () => {
    const cs = renderInto([arrival({ terminus_status: "short_turn", terminus_short_turn_station: "München-Solln" })]);
    expect(detailValue(panelOf(cs), "Endete in")).toBe("München-Solln (Kurzwende)");
    const ca = renderInto([arrival({ terminus_status: "arrived" })]);
    expect(detailValue(panelOf(ca), "Endete in")).toBeUndefined();
  });

  it("Zug row only when train_number is present", () => {
    const c1 = renderInto([arrival({ terminus_status: "arrived", train_number: "6824" })]);
    expect(detailValue(panelOf(c1), "Zug")).toBe("S 6824");
    const c2 = renderInto([arrival({ terminus_status: "arrived", train_number: null })]);
    expect(detailValue(panelOf(c2), "Zug")).toBeUndefined();
  });

  it("Grund row appears in panel and is removed from summary row when reason is set", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", reason: "Signalstörung" })]);
    expect(detailValue(panelOf(c), "Grund")).toBe("Signalstörung");
    expect(c.querySelector("details.arrival-row > summary .arrival-reason")).toBeNull();
  });

  it("Baierbrunn-cancelled with reason=null shows 'Zug ausgefallen — keine Fahrt' line and no separate Grund row", () => {
    const c = renderInto([arrival({ cancelled: true, reason: null })]);
    const panel = panelOf(c);
    expect(panel.textContent).toContain("Zug ausgefallen — keine Fahrt");
    expect(detailValue(panel, "Grund")).toBeUndefined();
  });

  it("Baierbrunn-cancelled with reason shows reason in Grund row", () => {
    const c = renderInto([arrival({ cancelled: true, reason: "Streik" })]);
    expect(detailValue(panelOf(c), "Grund")).toBe("Streik");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd site && npx vitest run src/pages/today.test.ts`
Expected: FAIL — no `details.arrival-row`, no `.arrival-detail` etc.

- [ ] **Step 3: Implement panel + replace `rowFor`**

In `site/src/pages/today.ts`, add helpers above `rowFor`:

```ts
function fmtDeparture(a: Arrival): string {
  if (a.cancelled) return "ausgefallen";
  const t = formatTime(a.scheduled_time);
  const m = a.delay_minutes ?? 0;
  if (m > 0) return `${t} (+${m} min)`;
  return `${t} (planmäßig)`;
}

function fmtTerminusArrival(a: Arrival): string {
  // arrived: HH:MM (+N min) with N = floor(terminus_delay_minutes, 0), or "planmäßig" if null.
  // cancelled: "nicht angekommen". pending: "noch unterwegs".
  switch (a.terminus_status) {
    case "arrived": {
      const m = a.terminus_delay_minutes;
      if (m === null || m === undefined) return "planmäßig";
      const floored = Math.max(0, m);
      // No reliable terminus actual_time on Arrival — show delay only (matches spec example for null-actual case, generalised).
      const sched = formatTime(a.scheduled_time);
      // Compute display-only arrival time by adding scheduled departure offset — we don't have it.
      // Per spec the value examples include "07:17 (+3 min)"; spec note says when terminus_delay_minutes is null we display "planmäßig" only.
      // The Arrival type does not currently carry a terminus actual time; show "(+N min)" without computed HH:MM, prefixed by Soll-Ankunft? Spec ambiguous; we render delay only since no terminus actual exists in the data model.
      void sched;
      return floored > 0 ? `+${floored} min` : `+0 min`;
    }
    case "short_turn":
    case "cancelled":
      return "nicht angekommen";
    case "pending":
      return "noch unterwegs";
    default:
      return "";
  }
}

function detailRow(label: string, value: string): string {
  return `<div class="detail-row"><span class="detail-label">${escapeHtml(label)}:</span><span class="detail-value">${escapeHtml(value)}</span></div>`;
}

function detailPanel(a: Arrival): string {
  const rows: string[] = [];
  rows.push(detailRow("Abfahrt Baierbrunn", fmtDeparture(a)));

  if (a.cancelled) {
    if (!a.reason) {
      rows.push(`<div class="detail-row detail-row--note">Zug ausgefallen — keine Fahrt</div>`);
    }
  } else if (a.terminus_status) {
    const long = a.direction_bucket === "muenchen" || a.direction_bucket === "wolfratshausen"
      ? terminusLabelLong(a.direction_bucket)
      : "";
    rows.push(detailRow(`Ankunft ${long}`, fmtTerminusArrival(a)));
  }

  if (a.terminus_status === "short_turn" && a.terminus_short_turn_station) {
    rows.push(detailRow("Endete in", `${a.terminus_short_turn_station} (Kurzwende)`));
  }
  if (a.train_number) {
    rows.push(detailRow("Zug", `S ${a.train_number}`));
  }
  if (a.reason) {
    rows.push(detailRow("Grund", a.reason));
  }
  return `<div class="arrival-detail">${rows.join("")}</div>`;
}
```

Replace `rowFor` body with the `<details>` form:

```ts
function rowFor(slot: string, a: Arrival | null): string {
  const time = formatTime(slot);
  if (!a) {
    return `
      <div class="arrival-row arrival-row--empty">
        <span class="arrival-time">${time}</span>
        <span class="arrival-empty">—</span>
      </div>`;
  }
  const cancelledCls = a.cancelled ? " arrival-row--cancelled" : "";
  return `
    <details class="arrival-row${cancelledCls}">
      <summary>
        <span class="arrival-time">${time}</span>
        <span class="arrival-direction">${escapeHtml(a.direction)}</span>
        ${statusBadge(a)}
        ${terminusLine(a)}
        <span class="chev" aria-hidden="true"></span>
      </summary>
      ${detailPanel(a)}
    </details>`;
}
```

> Note on `fmtTerminusArrival`: the `Arrival` type today carries `actual_time` for *Baierbrunn departure*, not for terminus arrival. The spec's HH:MM example for the panel relies on a terminus actual we don't have in the data model. We render delay-only (`+N min` / `+0 min` / `planmäßig`) per the spec's null-actual rule, generalized to all cases — this matches every test case above and avoids fabricating a clock time. If Phase 2.1 later adds `terminus_actual_time`, swap `+N min` for `HH:MM (+N min)` here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd site && npx vitest run src/pages/today.test.ts`
Expected: PASS for `arrival row <details> wrapper` + `expand panel content` blocks.

- [ ] **Step 5: Commit**

```bash
git add site/src/pages/today.ts site/src/pages/today.test.ts
git commit -m "feat(site): tap-to-expand panel on each arrival row"
```

---

## Task 4: Extend `summaryBar` with terminus aggregate items

`summaryBar` currently takes `DirectionAggregate`. It now also accepts a `TerminusAggregate`, appending `✓ N bis {terminusLabelShort}`, `⚠ N Kurzwende`, `⊘ N nicht angekommen`. All three suppressed when `arrived+short_turn+missed===0`.

**Files:**
- Modify: `site/src/pages/today.ts`
- Test: `site/src/pages/today.test.ts`

- [ ] **Step 1: Write failing tests for the summary-bar extension**

Append to `site/src/pages/today.test.ts`:

```ts
describe("summary bar terminus items", () => {
  it("shows 'bis München' count when arrived > 0", () => {
    const c = renderInto([
      arrival({ direction_bucket: "muenchen", terminus_status: "arrived" }),
      arrival({ scheduled_time: "2026-05-01T08:30:00", direction_bucket: "muenchen", terminus_status: "arrived" }),
    ]);
    const bar = c.querySelectorAll(".direction-col")[0].querySelector(".summary-bar")!;
    expect(bar.textContent).toContain("2 bis München");
  });

  it("shows '⚠ N Kurzwende' when short_turn > 0", () => {
    const c = renderInto([arrival({ direction_bucket: "muenchen", terminus_status: "short_turn", terminus_short_turn_station: "Solln" })]);
    const bar = c.querySelectorAll(".direction-col")[0].querySelector(".summary-bar")!;
    expect(bar.textContent).toContain("1 Kurzwende");
  });

  it("shows '⊘ N nicht angekommen' when missed (cancelled terminus) > 0", () => {
    const c = renderInto([arrival({ direction_bucket: "muenchen", terminus_status: "cancelled" })]);
    const bar = c.querySelectorAll(".direction-col")[0].querySelector(".summary-bar")!;
    expect(bar.textContent).toContain("1 nicht angekommen");
  });

  it("suppresses all three terminus items when arrived+short_turn+missed = 0", () => {
    const c = renderInto([arrival({ direction_bucket: "muenchen", terminus_status: "pending" })]);
    const bar = c.querySelectorAll(".direction-col")[0].querySelector(".summary-bar")!;
    expect(bar.textContent).not.toContain("bis");
    expect(bar.textContent).not.toContain("Kurzwende");
    expect(bar.textContent).not.toContain("nicht angekommen");
  });

  it("uses 'Wolfratshausen' as terminus label for wolfratshausen bucket", () => {
    const c = renderInto([arrival({ direction_bucket: "wolfratshausen", terminus_status: "arrived" })]);
    // wolfratshausen is the right column.
    const bar = c.querySelectorAll(".direction-col")[1].querySelector(".summary-bar")!;
    expect(bar.textContent).toContain("1 bis Wolfratshausen");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd site && npx vitest run src/pages/today.test.ts`
Expected: FAIL — bar contains only the existing four items.

- [ ] **Step 3: Implement the bar extension**

In `site/src/pages/today.ts`, change `summaryBar` signature and body:

```ts
function summaryBar(
  agg: DirectionAggregate,
  term: TerminusAggregate,
  bucket: "muenchen" | "wolfratshausen",
): string {
  const showTerm = term.arrived + term.short_turn + term.missed > 0;
  const termItems = showTerm
    ? [
        term.arrived > 0
          ? `<span class="summary-item summary-item--ok">✓ ${term.arrived} bis ${terminusLabelShort(bucket)}</span>`
          : "",
        term.short_turn > 0
          ? `<span class="summary-item summary-item--shortturn">⚠ ${term.short_turn} Kurzwende</span>`
          : "",
        term.missed > 0
          ? `<span class="summary-item summary-item--missed">⊘ ${term.missed} nicht angekommen</span>`
          : "",
      ]
    : [];
  return [
    `<span class="summary-item summary-item--ok">✓ ${agg.on_time} pünktlich</span>`,
    `<span class="summary-item summary-item--late">⏱ ${agg.late} verspätet</span>`,
    `<span class="summary-item summary-item--cancelled">✕ ${agg.cancelled} ausgefallen</span>`,
    agg.missing > 0 ? `<span class="summary-item summary-item--missing">? ${agg.missing} keine Daten</span>` : "",
    ...termItems,
  ].filter(Boolean).join("");
}
```

In `renderToday`, compute the two per-bucket terminus aggregates and pass them in:

```ts
export function renderToday(data: S7Data, container: HTMLElement): void {
  const agg = data.aggregates.today;
  const rows = unifiedTodayRows(data);
  const termM = terminusAggregate(data.arrivals, "muenchen");
  const termW = terminusAggregate(data.arrivals, "wolfratshausen");

  container.innerHTML = `
    <h2>Heute — S7 Baierbrunn</h2>
    <div class="today-grid">
      <div class="direction-col">
        <h3>Richtung München</h3>
        <div class="summary-bar">${summaryBar(agg.by_direction.muenchen, termM, "muenchen")}</div>
      </div>
      <div class="direction-col">
        <h3>Richtung Wolfratshausen</h3>
        <div class="summary-bar">${summaryBar(agg.by_direction.wolfratshausen, termW, "wolfratshausen")}</div>
      </div>
    </div>
    ${rows.length
      ? `<div class="today-rows">${renderRows(rows)}</div>`
      : `<p>Keine Daten für heute.</p>`}
    <details class="today-combined">
      <summary>Gesamt heute: ${agg.total} Züge · Ø ${agg.avg_delay_min} min Verspätung</summary>
    </details>
    <p class="data-age">Stand: ${new Date(data.generated_at).toLocaleString("de-DE")} · Nächstes Update: ${formatTime(nextUpdate(data.generated_at).toISOString())}</p>
  `;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd site && npx vitest run src/pages/today.test.ts`
Expected: PASS for the `summary bar terminus items` block and all prior blocks.

- [ ] **Step 5: Commit**

```bash
git add site/src/pages/today.ts site/src/pages/today.test.ts
git commit -m "feat(site): terminus counters in today summary bar"
```

---

## Task 5: CSS — terminus line variants, `<details>` reset, panel, summary item classes

**Files:**
- Modify: `site/src/style.css`

No tests for pure CSS. Visual verification is in Task 8.

- [ ] **Step 1: Append new style block to `site/src/style.css`**

```css
/* Native <details> reset so the <summary> renders as a flex row identical to
   the previous .arrival-row layout (no UA disclosure triangle, custom glyph). */
details.arrival-row {
  display: block;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0;
  font-size: 0.95rem;
}
details.arrival-row > summary {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.55rem 0.85rem;
  cursor: pointer;
  list-style: none;
  flex-wrap: wrap;
}
details.arrival-row > summary::-webkit-details-marker { display: none; }
details.arrival-row .chev::before { content: "▸"; color: #888; margin-left: auto; }
details.arrival-row[open] > summary .chev::before { content: "▾"; }
@media (max-width: 700px) {
  details.arrival-row > summary { padding: 0.4rem 0.55rem; gap: 0.35rem; font-size: 0.85rem; }
}

/* Inline terminus outcome line — exception bias, color + arrow + word. */
.terminus-line {
  font-size: 0.85rem;
  white-space: nowrap;
}
.terminus-line--shortturn { color: var(--orange); }
.terminus-line--missed    { color: var(--red); }
.terminus-line--late      { color: var(--red); }
.terminus-line--late-mild { color: #444; }
.terminus-line--pending   { color: #888; font-style: italic; }

/* Expand panel: tabular per-field rows. */
.arrival-detail {
  padding: 0 0.85rem 0.6rem;
  font-size: 0.85rem;
  color: #333;
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 0.15rem 0.6rem;
}
.detail-row { display: contents; }
.detail-row--note {
  display: block;
  grid-column: 1 / -1;
  font-style: italic;
  color: #666;
}
.detail-label { font-weight: 600; color: #555; }
.detail-value { font-variant-numeric: tabular-nums; }

/* Summary-bar terminus items: reuse palette, distinct glyph colors. */
.summary-item--shortturn { color: var(--orange); font-weight: 600; }
.summary-item--missed    { color: var(--red);    font-weight: 600; }

/* Archive Endpunkt cell. */
.endpunkt--ok        { color: var(--green); }
.endpunkt--shortturn { color: var(--orange); font-weight: 600; }
.endpunkt--missed    { color: var(--red); font-weight: 600; }
@media (max-width: 420px) {
  .archive-table td.endpunkt-cell, .archive-table th.endpunkt-cell {
    font-size: 0.8rem;
  }
}
```

- [ ] **Step 2: Verify the site still builds and lints**

Run: `cd site && npm run build && npm run lint`
Expected: PASS (no TS errors, no lint errors).

- [ ] **Step 3: Commit**

```bash
git add site/src/style.css
git commit -m "feat(site): styles for terminus line, expand panel, summary items"
```

---

## Task 6: Archive detail page — Endpunkt column

**Files:**
- Modify: `site/src/pages/archive-detail.ts`
- Create: `site/src/pages/archive-detail.test.ts`

- [ ] **Step 1: Create the new test file**

Create `site/src/pages/archive-detail.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { endpunktCell } from "./archive-detail.js";
import type { Arrival } from "../data.js";

function a(overrides: Partial<Arrival>): Arrival {
  return {
    train_id: "x",
    line: "S7",
    station: "Baierbrunn",
    direction: "München Hbf",
    direction_bucket: "muenchen",
    scheduled_time: "2026-05-01T08:00:00",
    actual_time: null,
    delay_minutes: 0,
    cancelled: false,
    reason: null,
    train_number: null,
    terminus_status: null,
    terminus_delay_minutes: null,
    terminus_short_turn_station: null,
    ...overrides,
  };
}

describe("endpunktCell", () => {
  it("renders '{terminusLabelShort}' with --ok class when arrived with delay 0", () => {
    const html = endpunktCell(a({ terminus_status: "arrived", terminus_delay_minutes: 0 }));
    expect(html).toContain("München");
    expect(html).toContain("endpunkt--ok");
    expect(html).not.toContain("+");
  });

  it("renders '{terminusLabelShort} +N' with --ok class when arrived with positive delay", () => {
    const html = endpunktCell(a({ terminus_status: "arrived", terminus_delay_minutes: 4 }));
    expect(html).toContain("München +4");
    expect(html).toContain("endpunkt--ok");
  });

  it("floors negative terminus delays at 0", () => {
    const html = endpunktCell(a({ terminus_status: "arrived", terminus_delay_minutes: -3 }));
    expect(html).toContain("München");
    expect(html).not.toContain("-3");
    expect(html).not.toContain("+");
  });

  it("renders '{station} (Kurzwende)' with --shortturn class for short_turn", () => {
    const html = endpunktCell(a({ terminus_status: "short_turn", terminus_short_turn_station: "München-Solln" }));
    expect(html).toContain("München-Solln (Kurzwende)");
    expect(html).toContain("endpunkt--shortturn");
  });

  it("renders 'nicht angekommen' with --missed class for cancelled terminus", () => {
    const html = endpunktCell(a({ terminus_status: "cancelled" }));
    expect(html).toContain("nicht angekommen");
    expect(html).toContain("endpunkt--missed");
  });

  it("renders '—' for pending", () => {
    const html = endpunktCell(a({ terminus_status: "pending" }));
    expect(html).toContain("—");
  });

  it("renders '—' for null terminus_status", () => {
    const html = endpunktCell(a({ terminus_status: null }));
    expect(html).toContain("—");
  });

  it("renders '—' for Baierbrunn-cancelled (irrespective of terminus_status)", () => {
    const html = endpunktCell(a({ cancelled: true, terminus_status: "cancelled" }));
    expect(html).toContain("—");
    expect(html).not.toContain("nicht angekommen");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd site && npx vitest run src/pages/archive-detail.test.ts`
Expected: FAIL — `endpunktCell` not exported.

- [ ] **Step 3: Implement `endpunktCell` and wire the column**

Update `site/src/pages/archive-detail.ts`. Update imports:

```ts
import { loadMonth } from "../archive.js";
import { escapeHtml, terminusLabelShort } from "../data.js";
import type { Arrival } from "../data.js";
import { renderDailyByDirection } from "../charts/dailyByDirection.js";
```

Add the helper above `renderArchiveDetail` and export it:

```ts
export function endpunktCell(a: Arrival): string {
  if (a.cancelled) {
    return `<td class="endpunkt-cell">—</td>`;
  }
  const bucket = a.direction_bucket;
  if (bucket !== "muenchen" && bucket !== "wolfratshausen") {
    return `<td class="endpunkt-cell">—</td>`;
  }
  const short = terminusLabelShort(bucket);
  switch (a.terminus_status) {
    case "arrived": {
      const m = Math.max(0, a.terminus_delay_minutes ?? 0);
      const label = m > 0 ? `${short} +${m}` : short;
      return `<td class="endpunkt-cell endpunkt--ok">${escapeHtml(label)}</td>`;
    }
    case "short_turn": {
      const st = a.terminus_short_turn_station ?? "unbekannt";
      return `<td class="endpunkt-cell endpunkt--shortturn">${escapeHtml(st)} (Kurzwende)</td>`;
    }
    case "cancelled":
      return `<td class="endpunkt-cell endpunkt--missed">nicht angekommen</td>`;
    case "pending":
    default:
      return `<td class="endpunkt-cell">—</td>`;
  }
}
```

Update the table markup in `renderArchiveDetail`:

```ts
      <table class="archive-table">
        <thead>
          <tr><th>Datum</th><th>Soll</th><th>Ist</th><th>Verspätung</th><th>Richtung</th><th>Status</th><th class="endpunkt-cell">Endpunkt</th></tr>
        </thead>
        <tbody>
          ${arc.arrivals.map((a) => `
            <tr>
              <td>${a.scheduled_time.slice(0, 10)}</td>
              <td>${fmtTime(a.scheduled_time)}</td>
              <td>${a.actual_time ? fmtTime(a.actual_time) : "—"}</td>
              <td>${a.delay_minutes ?? 0} min</td>
              <td>${escapeHtml(a.direction)}</td>
              <td>${a.cancelled ? "Ausgefallen" : (a.delay_minutes && a.delay_minutes > 0 ? "Verspätet" : "Pünktlich")}</td>
              ${endpunktCell(a)}
            </tr>`).join("")}
        </tbody>
      </table>
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `cd site && npx vitest run`
Expected: PASS for `archive-detail.test.ts`, `data.test.ts`, `today.test.ts`, and pre-existing tests.

- [ ] **Step 5: Commit**

```bash
git add site/src/pages/archive-detail.ts site/src/pages/archive-detail.test.ts
git commit -m "feat(site): Endpunkt column on archive detail page"
```

---

## Task 7: Build + lint + manual smoke

- [ ] **Step 1: Full build**

Run: `cd site && npm run build`
Expected: tsc clean, Vite emits `dist/`, no errors.

- [ ] **Step 2: Lint**

Run: `cd site && npm run lint`
Expected: PASS.

- [ ] **Step 3: Manual smoke against current `data/latest.json`**

```bash
cd site && npm run dev
```

Open the printed URL. Verify:

1. Today page renders both columns; rows that previously showed `pünktlich` and have `terminus_status === "arrived"` with delay 0 show **no** outcome line.
2. Click any row → panel opens, shows Abfahrt + Ankunft + (Zug if present).
3. If `data/latest.json` contains a `short_turn` row, it shows `→ nur bis …` (orange) and the panel's `Endete in:` row.
4. Summary bar shows `✓ N bis München` when `arrived > 0`.
5. Resize browser to 375 px; summary row stays on one line, outcome line wraps below.
6. Visit `/archive/<period>` (any period present in `data/archive/`); rightmost column `Endpunkt` populated for every row.
7. Confirm no console warnings (other than the explicit `short_turn` null-station fallback, which should not fire on healthy data).

- [ ] **Step 4: Commit any cleanup**

```bash
git status
# if anything stray, address before continuing
```

(No commit if working tree clean.)

---

## Task 8: Update CHANGELOG and prep release

This is a `feat` change (new UI surfacing existing data) → MINOR bump. Per `.claude/skills/release-hygiene/SKILL.md` and `CLAUDE.md`, the release itself happens **after** PR merge (post-merge release trigger). Inside the PR we update only `CHANGELOG.md` `[Unreleased]` section.

- [ ] **Step 1: Add a CHANGELOG entry**

Edit `CHANGELOG.md`, add under `## [Unreleased]` → `### Added`:

```
- **Site:** Terminus arrival surface on today + archive pages — inline outcome line ("→ nur bis Solln", "→ +N min", "→ unterwegs …"), tap-to-expand detail panel per row, "bis München / Kurzwende / nicht angekommen" counters in the summary bar, new Endpunkt column on the monthly archive table. Surfaces `terminus_status` / `terminus_delay_minutes` / `terminus_short_turn_station` populated by Phase 1 (v0.7.0+).
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): note Phase 2 terminus UI surface"
```

- [ ] **Step 3: Push branch and open PR**

```bash
git push -u origin HEAD
gh pr create --title "feat(site): Phase 2 terminus arrival UI" --body "$(cat <<'EOF'
## Summary
- Inline outcome line on today rows when terminus state is exceptional (short-turn, missed, pending, late ≥1 min)
- Tap-to-expand panel per row with Abfahrt / Ankunft / Endete in / Zug / Grund
- Summary-bar counters: ✓ bis {terminus}, ⚠ Kurzwende, ⊘ nicht angekommen
- Endpunkt column on archive detail table

Spec: docs/superpowers/specs/2026-05-24-terminus-ui-design.md

## Test plan
- [ ] npx vitest run (all green, ~30+ new cases)
- [ ] npm run build + npm run lint clean
- [ ] Manual: today page renders, tap opens panel, mobile 375 px width OK
- [ ] Manual: archive Endpunkt column populated, mobile width acceptable

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Post-merge release** (do not run before merge)

Once merged into `main`, per CLAUDE.md "Post-merge release trigger":

1. `git checkout main && git pull`
2. Bump `pyproject.toml` MINOR (e.g. `0.8.3` → `0.9.0`)
3. `cd fetcher && uv sync --no-dev` to refresh `uv.lock`
4. Update `CHANGELOG.md`: rename `[Unreleased]` to `[0.9.0] - YYYY-MM-DD`, fill date
5. Commit: `chore(release): 0.9.0`
6. Tag: `git tag v0.9.0`
7. Push tag: `git push origin v0.9.0`
8. GitHub Release: per CLAUDE.md, use the explicit-end awk form documented in `[[feedback_release_awk]]` (verify body is non-empty before `gh release create`)
9. No VM redeploy needed (UI-only; gh-pages build runs automatically on `main` push via the existing `dispatch-build.yml` chain — but here the trigger is the `s7bb-data` repo's hourly push, so the site rebuilds within ≤1 h on its own).

> ⚠ If the latest deploy hasn't picked up the new commits within ~1 h after merge, manually trigger `build-site.yml` via `gh workflow run build-site.yml` on `s7bb/s7bb.github.io`.

---

## Self-review

**Spec coverage map:**

| Spec section | Plan task |
|---|---|
| State matrix (inline line) | Task 2 |
| State matrix (expand panel "Ankunft") | Task 3 |
| Terminus label helpers (`terminusLabelLong`/`Short`) | Task 1 |
| Inline outcome line CSS + classes | Task 5 |
| Tap-to-expand panel structure + native `<details>` | Task 3 |
| Chevron rotation, summary list-style reset | Task 5 |
| Aggregate counter (`terminusAggregate` + bar items) | Task 1 + Task 4 |
| Archive detail Endpunkt column | Task 6 |
| Data-flow (`terminusLine(a)` + `endpunktCell(a)` helpers) | Tasks 2, 6 |
| Accessibility (chevron `aria-hidden`, native semantics) | Tasks 3, 5 |
| Edge cases (null terminus, null delay, null station, pre-feature) | Tasks 2, 3, 6 |
| Testing (all listed `today.test.ts` / `data.test.ts` / `archive-detail.test.ts` cases) | Tasks 1, 2, 3, 4, 6 |
| Manual verification | Task 7 |

**Placeholder scan:** No "TBD" / "implement later" / "similar to Task N". Every code block contains complete source.

**Type consistency:** `terminusLabelLong` / `terminusLabelShort` / `TerminusAggregate` / `terminusAggregate` / `terminusLine` / `endpunktCell` / `detailPanel` / `detailRow` / `fmtDeparture` / `fmtTerminusArrival` — used identically across tasks. `summaryBar(agg, term, bucket)` signature change is introduced in Task 4 and used only there.

**Known limitation noted in plan:** `Arrival` lacks a `terminus_actual_time` field, so the panel's `Ankunft` row renders `+N min` / `planmäßig` / `noch unterwegs` / `nicht angekommen` — never `HH:MM (+N min)`. Spec's HH:MM examples (`07:17 (+3 min)`) are aspirational; would require a Phase 2.1 data-layer addition. Tests assert the realised behavior; deferred to a follow-up brainstorm.
