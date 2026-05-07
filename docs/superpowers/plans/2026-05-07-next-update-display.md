# Next Update Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Append "Nächstes Update: HH:MM" next to existing "Stand:" footer on the today page so users see when fresh data is expected.

**Architecture:** Compute next push time client-side from `data.generated_at` by flooring to the hour and adding one hour. Cron `0 * * * *` is fixed, so JSON schema stays unchanged. Helper is exported for unit testing.

**Tech Stack:** TypeScript, Vite, Vitest (jsdom env), Chart.js (untouched).

---

## File Structure

- Modify: `site/src/pages/today.ts` — add `nextUpdate` helper, edit footer render.
- Create: `site/src/pages/today.test.ts` — vitest unit tests for `nextUpdate`.
- Modify: `CHANGELOG.md` — add entry under `[Unreleased]` › `Added`.

Helper lives next to its only consumer in `today.ts` rather than in a shared module — `data.ts`/`archive.ts` exist for cross-page concerns, this is page-local.

---

### Task 1: nextUpdate helper with TDD

**Files:**
- Modify: `site/src/pages/today.ts`
- Create: `site/src/pages/today.test.ts`

- [ ] **Step 1: Write failing tests**

Create `site/src/pages/today.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { nextUpdate } from "./today.js";

describe("nextUpdate", () => {
  it("returns next top of hour when generated_at is exactly on the hour", () => {
    expect(nextUpdate("2026-05-07T14:00:00Z").toISOString()).toBe("2026-05-07T15:00:00.000Z");
  });

  it("returns next top of hour when generated_at is mid-hour", () => {
    expect(nextUpdate("2026-05-07T14:00:30Z").toISOString()).toBe("2026-05-07T15:00:00.000Z");
  });

  it("returns next top of hour when generated_at is at end of hour", () => {
    expect(nextUpdate("2026-05-07T14:59:59Z").toISOString()).toBe("2026-05-07T15:00:00.000Z");
  });

  it("rolls over to next day at 23:xx", () => {
    expect(nextUpdate("2026-05-07T23:30:00Z").toISOString()).toBe("2026-05-08T00:00:00.000Z");
  });
});
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd site && npm test -- src/pages/today.test.ts`
Expected: FAIL with "nextUpdate is not exported" or similar.

- [ ] **Step 3: Add helper to `today.ts`**

Insert after the `formatTime` helper (currently at `today.ts:5-7`):

```ts
export function nextUpdate(generatedAt: string): Date {
  const d = new Date(generatedAt);
  d.setUTCMinutes(0, 0, 0);
  d.setUTCHours(d.getUTCHours() + 1);
  return d;
}
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd site && npm test -- src/pages/today.test.ts`
Expected: PASS, 4 tests green.

- [ ] **Step 5: Commit**

```bash
git add site/src/pages/today.ts site/src/pages/today.test.ts
git commit -m "feat(site): add nextUpdate helper for today page footer"
```

---

### Task 2: Render "Nächstes Update" in footer

**Files:**
- Modify: `site/src/pages/today.ts:69` (footer paragraph in `renderToday`)

- [ ] **Step 1: Edit footer render**

Replace the existing line:

```ts
    <p class="data-age">Stand: ${new Date(data.generated_at).toLocaleString("de-DE")}</p>
```

with:

```ts
    <p class="data-age">Stand: ${new Date(data.generated_at).toLocaleString("de-DE")} · Nächstes Update: ${formatTime(nextUpdate(data.generated_at).toISOString())}</p>
```

`formatTime` (line 5-7) already returns `HH:MM` in `de-DE` locale.

- [ ] **Step 2: Type-check + build**

Run: `cd site && npm run build`
Expected: build succeeds, no TS errors.

- [ ] **Step 3: Manual visual check in dev server**

Run: `cd site && npm run dev`
Open the printed URL, switch to the today page, scroll to the bottom.
Expected: footer reads `Stand: <date+time> · Nächstes Update: HH:MM` where `HH:MM` is the next top-of-hour after `generated_at` in local time.
Stop dev server (Ctrl+C) when verified.

- [ ] **Step 4: Commit**

```bash
git add site/src/pages/today.ts
git commit -m "feat(site): show next update time on today page footer"
```

---

### Task 3: Changelog entry

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add Added entry under [Unreleased]**

Edit `CHANGELOG.md`. Replace:

```markdown
## [Unreleased]

## [0.2.0] - 2026-05-07
```

with:

```markdown
## [Unreleased]

### Added
- Today page footer now shows the expected time of the next data refresh ("Nächstes Update: HH:MM") next to the existing "Stand" timestamp.

## [0.2.0] - 2026-05-07
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog entry for next-update display"
```

---

### Task 4: Final verification

- [ ] **Step 1: Full site test suite**

Run: `cd site && npm test`
Expected: all tests pass (today.test.ts + archive.test.ts).

- [ ] **Step 2: Lint**

Run: `cd site && npm run lint`
Expected: no errors.

- [ ] **Step 3: Build**

Run: `cd site && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Confirm git status clean**

Run: `git status`
Expected: working tree clean (the unrelated `M docker-compose.yml` and `M site/vite.config.ts` from session start may still be there — those are not part of this feature).
