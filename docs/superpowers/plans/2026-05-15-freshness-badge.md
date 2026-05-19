# Freshness Badge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface stale schedule data to non-technical visitors with a coloured "aktuell / verzögert / veraltet" pill next to the existing "Stand:" timestamp on every data-driven page, recomputed every 60 s so a long-open tab transitions states without a reload.

**Architecture:** A pure `site/src/freshness.ts` module computes a `frisch`/`verzoegert`/`veraltet` state from `generated_at` vs. now, renders a badge, and exposes a self-updating ticker. CSS gives each state a colour. The four data pages (`today`, `week`, `stats`, `archive-list`) render the badge into their `.data-age` line and mount the ticker.

**Tech Stack:** TypeScript + Vite + Vitest.

**Note:** Independent of the two-repository data split (`docs/superpowers/plans/2026-05-15-two-repo-data-split.md`). Either may be implemented first. Thresholds: `frisch` < 75 min, `verzoegert` < 180 min, else `veraltet` (75 min = one hourly cycle + ~15 min slack).

---

## File structure

**Created (site):**
- `site/src/freshness.ts` — `FreshnessState`, `freshnessState()`, `renderFreshnessBadge()`, `mountFreshnessTicker()`, exported threshold constants.
- `site/src/freshness.test.ts` — boundary + timezone tests.

**Modified (site):**
- `site/src/style.css` — `.freshness` + three state modifier rules.
- `site/src/pages/today.ts` — badge in the `.data-age` line + ticker.
- `site/src/pages/week.ts` — append a `.data-age` line with badge + ticker.
- `site/src/pages/stats.ts` — prepend badge to the existing `.data-age` line + ticker.
- `site/src/pages/archive-list.ts` — append `.data-age` line using `idx.generated_at` + ticker.

**Modified (docs):**
- `CHANGELOG.md` — `[Unreleased]` entry.

---

## Task 1: Freshness module + tests

**Files:**
- Create: `site/src/freshness.ts`
- Create: `site/src/freshness.test.ts`

- [ ] **Step 1: Write failing tests.** Create `site/src/freshness.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import {
  freshnessState,
  FRESHNESS_FRISCH_MAX_MIN,
  FRESHNESS_VERZOEGERT_MAX_MIN,
} from "./freshness.js";

const now = new Date("2026-05-14T12:00:00Z");
const minutesAgo = (n: number) =>
  new Date(now.getTime() - n * 60_000).toISOString();

describe("freshnessState", () => {
  it("returns 'frisch' at 0 min", () => {
    expect(freshnessState(minutesAgo(0), now)).toBe("frisch");
  });

  it("returns 'frisch' at 74 min (just under threshold)", () => {
    expect(freshnessState(minutesAgo(74), now)).toBe("frisch");
  });

  it("returns 'verzoegert' at exactly 75 min", () => {
    expect(freshnessState(minutesAgo(75), now)).toBe("verzoegert");
  });

  it("returns 'verzoegert' at 179 min", () => {
    expect(freshnessState(minutesAgo(179), now)).toBe("verzoegert");
  });

  it("returns 'veraltet' at exactly 180 min", () => {
    expect(freshnessState(minutesAgo(180), now)).toBe("veraltet");
  });

  it("returns 'veraltet' at 24h", () => {
    expect(freshnessState(minutesAgo(60 * 24), now)).toBe("veraltet");
  });

  it("handles ISO suffix '+00:00' identically to 'Z'", () => {
    const plus = "2026-05-14T11:00:00+00:00";
    const z = "2026-05-14T11:00:00Z";
    expect(freshnessState(plus, now)).toBe(freshnessState(z, now));
  });

  it("is timezone-independent (input has +02:00 offset)", () => {
    // 2026-05-14T13:00:00+02:00 === 2026-05-14T11:00:00Z (60 min ago) → frisch
    expect(freshnessState("2026-05-14T13:00:00+02:00", now)).toBe("frisch");
  });

  it("exports thresholds as constants", () => {
    expect(FRESHNESS_FRISCH_MAX_MIN).toBe(75);
    expect(FRESHNESS_VERZOEGERT_MAX_MIN).toBe(180);
  });
});
```

- [ ] **Step 2: Run, verify failure.**

Run: `cd site && npx vitest run src/freshness.test.ts`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement** `site/src/freshness.ts`:

```typescript
export type FreshnessState = "frisch" | "verzoegert" | "veraltet";

export const FRESHNESS_FRISCH_MAX_MIN = 75;
export const FRESHNESS_VERZOEGERT_MAX_MIN = 180;

const LABELS: Record<FreshnessState, string> = {
  frisch: "aktuell",
  verzoegert: "verzögert",
  veraltet: "veraltet — Daten nicht aktuell",
};

export function freshnessState(
  generatedAt: string,
  now: Date = new Date(),
): FreshnessState {
  const ageMin = (now.getTime() - new Date(generatedAt).getTime()) / 60_000;
  if (ageMin < FRESHNESS_FRISCH_MAX_MIN) return "frisch";
  if (ageMin < FRESHNESS_VERZOEGERT_MAX_MIN) return "verzoegert";
  return "veraltet";
}

export function renderFreshnessBadge(state: FreshnessState): string {
  return `<span class="freshness freshness--${state}">●&nbsp;${LABELS[state]}</span>`;
}

/**
 * Re-evaluate state every 60 s and update the badge element in place.
 * Returns a teardown function that clears the interval.
 */
export function mountFreshnessTicker(
  el: HTMLElement,
  generatedAt: string,
): () => void {
  const update = () => {
    const s = freshnessState(generatedAt, new Date());
    el.className = `freshness freshness--${s}`;
    el.textContent = `● ${LABELS[s]}`;
  };
  update();
  const id = window.setInterval(update, 60_000);
  return () => window.clearInterval(id);
}
```

- [ ] **Step 4: Run, verify pass.**

Run: `cd site && npx vitest run src/freshness.test.ts`
Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
git add site/src/freshness.ts site/src/freshness.test.ts
git commit -m "feat(site): freshness state computation and badge renderer

Pure module — pages wire the badge in subsequent commits."
```

---

## Task 2: Freshness CSS

**Files:**
- Modify: `site/src/style.css`

- [ ] **Step 1: Confirm no class collision.**

Run: `cd site && grep -n '\.freshness' src/style.css || echo "no collision"`
Expected: `no collision`.

- [ ] **Step 2: Append** to `site/src/style.css`:

```css
/* Freshness badge */
.freshness {
  display: inline-block;
  font-weight: 600;
  font-size: 0.85rem;
  padding: 0.05rem 0.5rem;
  border-radius: 999px;
  border: 1px solid currentColor;
  margin-right: 0.5rem;
}
.freshness--frisch     { color: #16a34a; }
.freshness--verzoegert { color: #d97706; }
.freshness--veraltet   { color: #dc2626; }
```

- [ ] **Step 3: Commit.**

```bash
git add site/src/style.css
git commit -m "feat(site): freshness badge styles"
```

---

## Task 3: Wire badge into `today.ts`

**Files:**
- Modify: `site/src/pages/today.ts`

- [ ] **Step 1: Inspect the current `.data-age` line.**

Run: `cd site && grep -n 'data-age\|^import\|innerHTML' src/pages/today.ts`
Confirm there is a single `<p class="data-age">…</p>` inside a template literal assigned to `container.innerHTML`, and note the exact existing text so only the badge is prepended.

- [ ] **Step 2: Add the import** at the top of `site/src/pages/today.ts`:

```typescript
import { freshnessState, renderFreshnessBadge, mountFreshnessTicker } from "../freshness.js";
```

- [ ] **Step 3: Prepend the badge** to the existing `.data-age` line. Replace the existing `<p class="data-age">…</p>` with the same text, with the badge prepended:

```typescript
    <p class="data-age">
      ${renderFreshnessBadge(freshnessState(data.generated_at))}
      Stand: ${new Date(data.generated_at).toLocaleString("de-DE")} · Nächstes Update: ${formatTime(nextUpdate(data.generated_at).toISOString())}
    </p>
```

Keep whatever the original line's exact trailing content was (e.g. the "Nächstes Update" expression) — only prepend the `renderFreshnessBadge(...)` call. After `container.innerHTML = …;` (outside the template literal), add:

```typescript
  const badge = container.querySelector<HTMLElement>(".data-age .freshness");
  if (badge) mountFreshnessTicker(badge, data.generated_at);
```

- [ ] **Step 4: Build.**

Run: `cd site && npm run build`
Expected: type-check + Vite build pass.

- [ ] **Step 5: Commit.**

```bash
git add site/src/pages/today.ts
git commit -m "feat(site): freshness badge on Heute page"
```

---

## Task 4: Wire badge into `week.ts`, `stats.ts`, `archive-list.ts`

**Files:**
- Modify: `site/src/pages/week.ts`
- Modify: `site/src/pages/stats.ts`
- Modify: `site/src/pages/archive-list.ts`

- [ ] **Step 1: Inspect the three pages.**

Run: `cd site && grep -n 'data-age\|generated_at\|innerHTML\|renderMonthsBar\|loadIndex' src/pages/week.ts src/pages/stats.ts src/pages/archive-list.ts src/archive.ts`
Note: whether each already has a `.data-age` line, the timestamp field used (`data.generated_at` vs `idx.generated_at`), and the last DOM-mount call after `container.innerHTML` (so the `mountFreshnessTicker` call can follow it).

- [ ] **Step 2: `week.ts`.** Add the import:

```typescript
import { freshnessState, renderFreshnessBadge, mountFreshnessTicker } from "../freshness.js";
```

Append, before the closing backtick of the `container.innerHTML` template (after the week chart container's closing `</div>`):

```typescript
    <p class="data-age">
      ${renderFreshnessBadge(freshnessState(data.generated_at))}
      Stand: ${new Date(data.generated_at).toLocaleString("de-DE")}
    </p>
```

After the last DOM-mount call in `renderWeek` (e.g. `renderMonthsBar(...)`):

```typescript
  const badge = container.querySelector<HTMLElement>(".data-age .freshness");
  if (badge) mountFreshnessTicker(badge, data.generated_at);
```

- [ ] **Step 3: `stats.ts`.** Add the import:

```typescript
import { freshnessState, renderFreshnessBadge, mountFreshnessTicker } from "../freshness.js";
```

Prepend the badge to the existing `.data-age` line, keeping its original text:

```typescript
    <p class="data-age">
      ${renderFreshnessBadge(freshnessState(data.generated_at))}
      Zeitraum: letzte ${data.window_days} Tage · ${agg.total} Züge erfasst · Stand: ${new Date(data.generated_at).toLocaleString("de-DE")}
    </p>
```

(If the original line's wording differs, keep it verbatim and only prepend the `renderFreshnessBadge(...)` call.) After the last mount call in `renderStats`:

```typescript
  const badge = container.querySelector<HTMLElement>(".data-age .freshness");
  if (badge) mountFreshnessTicker(badge, data.generated_at);
```

- [ ] **Step 4: `archive-list.ts`.** Confirm the index type exposes `generated_at`:

Run: `cd site && grep -n 'generated_at' src/archive.ts`
If `loadIndex()`'s return type lacks `generated_at: string`, widen it in `site/src/archive.ts`.

Add the import:

```typescript
import { freshnessState, renderFreshnessBadge, mountFreshnessTicker } from "../freshness.js";
```

Append inside the months-list `<section>` (before its closing `</section>`):

```typescript
      <p class="data-age">
        ${renderFreshnessBadge(freshnessState(idx.generated_at))}
        Stand: ${new Date(idx.generated_at).toLocaleString("de-DE")}
      </p>
```

After the last mount call:

```typescript
  const badge = container.querySelector<HTMLElement>(".data-age .freshness");
  if (badge) mountFreshnessTicker(badge, idx.generated_at);
```

- [ ] **Step 5: Build + lint.**

Run: `cd site && npm run build && npm run lint`
Expected: pass.

- [ ] **Step 6: Commit.**

```bash
git add site/src/pages/week.ts site/src/pages/stats.ts site/src/pages/archive-list.ts site/src/archive.ts
git commit -m "feat(site): freshness badge on Woche, Statistik, Archiv pages"
```

(Drop `site/src/archive.ts` from the `git add` if Step 4 needed no change there.)

---

## Task 5: Documentation + release

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update `CHANGELOG.md`.** Under `## [Unreleased]` → `### Added`:

```markdown
- Freshness badge on the Heute, Woche, Statistik and Archiv pages: a
  coloured "aktuell / verzögert / veraltet" pill next to the "Stand:"
  timestamp, recomputed every 60 s so a long-open tab changes state
  without a reload. Thresholds: aktuell < 75 min, verzögert < 180 min.
```

- [ ] **Step 2: Commit.**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog entry for the freshness badge"
```

- [ ] **Step 3: Open the PR** titled `feat: data freshness badge`. Body links this plan. CI: only `ci.yml` runs.

- [ ] **Step 4: Cut release per CLAUDE.md** (this is `feat:` → MINOR). Determine the next version from `fetcher/pyproject.toml` at merge time (`0.4.5` → `0.5.0`; if the two-repo split already released `0.5.0`, use `0.6.0`). Follow the full Release procedure in `CLAUDE.md` (bump `pyproject.toml`, `uv sync --no-dev`, rename `[Unreleased]`, commit `chore(release): X.Y.Z`, tag, push, `gh release create`).

---

## Self-review (run by the plan author)

**Coverage:** module + tests (Task 1), CSS (Task 2), all four data pages wired with badge + 60 s ticker (Tasks 3-4), changelog + release (Task 5).

**Type / contract consistency:** `freshnessState`, `renderFreshnessBadge`, `mountFreshnessTicker`, `FreshnessState`, `FRESHNESS_FRISCH_MAX_MIN`, `FRESHNESS_VERZOEGERT_MAX_MIN` — identical names in `freshness.ts`, `freshness.test.ts`, and all four page wirings. `freshnessState(generatedAt: string, now?: Date)` and `mountFreshnessTicker(el: HTMLElement, generatedAt: string)` signatures used consistently. Badge selector `.data-age .freshness` matches the `renderFreshnessBadge` output class on every page.

**Placeholder scan:** none — every step has actual code or an exact command. Page-specific `.data-age` wording is inspected in each task's Step 1 and preserved verbatim, with only the badge prepended.
