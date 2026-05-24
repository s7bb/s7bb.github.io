# Terminus arrival UI (Phase 2) — design

## Context

Phase 1 ([`2026-05-22-terminus-tracking-design.md`](2026-05-22-terminus-tracking-design.md), shipped v0.7.0+, hardened through v0.8.3) records per-train terminus outcomes in the JSON feed. The fields `terminus_status`, `terminus_delay_minutes`, and `terminus_short_turn_station` are populated and validated, but no part of the UI consumes them yet.

This spec defines the user-facing surface for those fields. The target audience is non-technical Baierbrunn residents; the question they want answered is:

> *Did my train actually reach München (or Wolfratshausen)?*

Today's surface only tells them whether a train **departed** Baierbrunn on time. A train that left punctual but later short-turned at München-Solln currently shows as a clean `pünktlich` row — a false positive from the resident's perspective.

## Design principles

1. **Don't double-encode.** Departure badge (`pünktlich` / `+N min` / `ausgefallen`) already exists; terminus surface only adds information that the departure badge cannot infer.
2. **Exception bias.** Arrived-on-time = silent surface. Short-turn / didn't-arrive / pending = visible signal.
3. **Color + symbol + text.** No color-only encoding. Arrow `→` + German phrase carries meaning even in monochrome.
4. **Progressive disclosure.** Surface stays compact; tap a row to reveal full per-train detail.
5. **Mobile-first.** Existing layout already drops to `0.85rem` and stacks directions on narrow screens; new elements must fit that envelope.
6. **Aggregate, not only per-row.** A counter answering "wie viele Züge sind heute bis München gekommen?" gives the resident a quick at-a-glance answer.

## Architecture

UI-only; no data layer change. All terminus fields are already on the `Arrival` type in `site/src/data.ts`. Files touched:

- `site/src/pages/today.ts` — row markup, inline outcome line, expand panel, summary aggregate
- `site/src/pages/archive-detail.ts` — new `Endpunkt` table column
- `site/src/data.ts` — new helper `terminusAggregate()`
- `site/src/style.css` — new classes for outcome line, detail panel, terminus aggregate items
- `site/src/pages/today.test.ts` — extended cases
- `site/src/pages/archive-detail.test.ts` — new file

No new dependencies. No fetcher / exporter changes.

## State matrix

For each `Arrival`, the rendered surface is determined by combining departure state and `terminus_status`:

| Departure | terminus_status | Inline outcome line below row | Expand panel "Ankunft" |
|---|---|---|---|
| pünktlich / +N | `arrived`, delay ≤ 0 | *(none)* | `planmäßig` |
| pünktlich / +N | `arrived`, +M min | *(none)* | `+M min` |
| pünktlich / +N | `short_turn` | `→ nur bis {station}` (orange) | `nicht angekommen` + `Endete in: {station}` |
| pünktlich / +N | `cancelled` | `→ nicht in München angekommen` (red) | `nicht angekommen` |
| pünktlich / +N | `pending` | `→ unterwegs …` (grey, italic) | `noch unterwegs` |
| pünktlich / +N | `null` | *(none)* | row keeps existing rendering, no Ankunft line |
| ausgefallen at Baierbrunn | (any) | *(none — existing strike-through unchanged)* | `Zug ausgefallen — keine Fahrt` |

Terminus name is derived from `direction_bucket` via two helpers in `data.ts`:

- `terminusLabelLong(bucket)` for today-page surface + panel:
  - `muenchen` → `"München Hbf"`
  - `wolfratshausen` → `"Wolfratshausen"`
- `terminusLabelShort(bucket)` for archive-table cell + summary-bar aggregate (dense contexts):
  - `muenchen` → `"München"`
  - `wolfratshausen` → `"Wolfratshausen"`
- `unknown` → row hidden from today page already (existing behavior); no special case needed

Rule of thumb: the **inline line** exists to make exceptions visible at a glance; the **expand panel** exists to confirm or detail every row on demand.

## Inline outcome line

New element rendered after `arrival-direction` when the state matrix calls for it:

```html
<span class="terminus-line terminus-line--shortturn">→ nur bis Solln</span>
```

Variants and CSS:

| Variant | Class | Color (reuses palette) |
|---|---|---|
| Short-turn | `terminus-line--shortturn` | `var(--orange)` |
| Didn't arrive | `terminus-line--missed` | `var(--red)` |
| Pending | `terminus-line--pending` | `#888`, `font-style: italic` |

The line wraps to a new row on narrow screens via `flex-wrap: wrap` on `.arrival-row` (existing).

## Tap-to-expand panel

Each `arrival-row` becomes:

```html
<details class="arrival-row">
  <summary>
    <span class="arrival-time">06:42</span>
    <span class="arrival-direction">München Hbf</span>
    <!-- statusBadge -->
    <!-- terminus-line if applicable -->
    <span class="chev" aria-hidden="true">▸</span>
  </summary>
  <div class="arrival-detail">
    <div class="detail-row"><span class="detail-label">Abfahrt Baierbrunn:</span><span class="detail-value">06:42 (planmäßig)</span></div>
    <div class="detail-row"><span class="detail-label">Ankunft München Hbf:</span><span class="detail-value">07:17 (+3 min)</span></div>
    <div class="detail-row"><span class="detail-label">Endete in:</span><span class="detail-value">München-Solln (Kurzwende)</span></div>
    <div class="detail-row"><span class="detail-label">Zug:</span><span class="detail-value">S 6824</span></div>
    <div class="detail-row"><span class="detail-label">Grund:</span><span class="detail-value">Signalstörung</span></div>
  </div>
</details>
```

Panel rules:

- **Abfahrt Baierbrunn** — always present. Value: `HH:MM (planmäßig)`, `HH:MM (+N min)`, or `ausgefallen`.
- **Ankunft {terminus}** — present unless Baierbrunn-cancelled or `terminus_status` is `null`. Terminus label uses `terminusLabelLong(direction_bucket)`. Time + delay refer to **terminus arrival** (computed from `terminus_delay_minutes`, floored at 0), not Baierbrunn departure — the two delays may differ (train caught up, or lost more time downstream). When `terminus_delay_minutes === null` and status is `arrived`: show `planmäßig` only (no time, since DB feed gave no actual arrival time).
- **Endete in** — only when `terminus_status === "short_turn"`. Value: `{terminus_short_turn_station} (Kurzwende)`.
- **Zug** — only when `train_number` non-null. Value: `S {train_number}`.
- **Grund** — only when `reason` non-null. Existing inline `arrival-reason` element is removed from the summary row and shown here instead.

Empty/no-data slots (`record === null` in `UnifiedSlotRow`) keep their current rendering with no `<details>` wrapper.

Chevron rotation via:

```css
details.arrival-row[open] > summary .chev::before { content: "▾"; }
.chev::before { content: "▸"; }
```

Default state: collapsed. No JS state; native `<details>` toggle.

## Aggregate counter

`summaryBar()` in `today.ts` extended. Two new items appear when applicable:

```
✓ 18 pünktlich · ⏱ 2 verspätet · ✕ 1 ausgefallen · ✓ 19 bis München · ⚠ 1 Kurzwende
```

Computation: new helper `terminusAggregate(arrivals, bucket)` in `data.ts`:

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
): TerminusAggregate;
```

Filter: `arrivals` of today (Berlin date), matching `direction_bucket === bucket`. Counts each `terminus_status` value once. Baierbrunn-cancelled and `null` rows excluded from all four counts.

Surface rules:

- `bis {terminusLabelShort(bucket)}` item rendered when `arrived > 0`: `bis München` or `bis Wolfratshausen`.
- `⚠ N Kurzwende` rendered when `short_turn > 0`.
- `✗ N nicht angekommen` rendered when `missed > 0`.
- All three items suppressed when `arrived + short_turn + missed === 0` (legacy-data day or empty day) to keep the bar clean.
- `pending` is not surfaced in the aggregate (visible only inside per-row panel via "noch unterwegs"); avoids a live-changing number on a static hourly snapshot.

## Archive detail page

`archive-table` gains one column at the right edge:

```
| Datum | Soll | Ist | Verspätung | Richtung | Status | Endpunkt |
```

`Endpunkt` cell per row:

| `terminus_status` | Cell content | Class |
|---|---|---|
| `arrived` (delay 0) | `{terminusLabelShort}` | `endpunkt--ok` |
| `arrived` (+N) | `{terminusLabelShort} +N` (terminus delay, floored at 0) | `endpunkt--ok` |
| `short_turn` | `{station} (Kurzwende)` | `endpunkt--shortturn` |
| `cancelled` | `nicht angekommen` | `endpunkt--missed` |
| `pending` | `—` | (none) |
| `null` | `—` | (none) |
| Baierbrunn-cancelled | `—` | (none) |

No tap-to-expand on archive (table format already dense). Power users hit the JSON download link already on the page.

## Data flow

```
latest.json (already populated by exporter)
   │
   ▼
loadData() → S7Data → unifiedTodayRows() → renderToday()
                                                │
                       ┌────────────────────────┼────────────────────────┐
                       ▼                        ▼                        ▼
              statusBadge(a)         terminusLine(a) (new)     terminusAggregate(...) (new)
              [existing]             returns string|""         feeds summaryBar() extension
                                                │
                                                ▼
                                       <details>/<summary>/panel
                                       built per row
```

```
archive/{period}.json
   │
   ▼
loadMonth() → renderArchiveDetail()
                       │
                       ▼
              new column cell per row via endpunktCell(a) (new helper)
```

## Accessibility

- Native `<details>`/`<summary>` exposes `aria-expanded` automatically; screen readers announce open/closed state.
- Chevron marked `aria-hidden="true"` (decoration; state is conveyed by native semantics).
- Color is never the sole carrier of meaning — every state has an arrow + word ("nur bis", "nicht", "unterwegs") or unicode glyph (`✓`, `⚠`, `✗`).
- Tap target ≥ 44 px height on summary via existing `.arrival-row` padding (verify on iPhone SE viewport).
- Reduced motion: chevron rotation is a content swap (`::before`), not a CSS transition.

## Error handling / edge cases

| Case | Behavior |
|---|---|
| Pre-feature row (`terminus_status === undefined` or `null`) | No outcome line; panel shows only Abfahrt + Zug + Grund (no Ankunft line). |
| `terminus_delay_minutes` negative (arrived early) | Display as `+0 min` (floor at 0) per [[project_terminus_delay_fix]]. |
| `terminus_delay_minutes === null` with status `arrived` | Display `planmäßig` in panel. |
| `terminus_short_turn_station === null` with status `short_turn` | Fall back to "→ nicht in München angekommen" (treat as `cancelled`-equivalent) and log a console warning. Should never happen per Phase 1 contract. |
| Multiple short-turn intermediates in raw data | Already collapsed to Baierbrunn-most cancelled station by Phase 1 drilldown; UI shows that one name. |
| Slot with no train data (`record === null`) | Keep existing `arrival-row--empty` rendering, no `<details>`. |
| Reason text very long | Inside panel: wraps naturally; no truncation. (Surface row no longer carries reason, so no marquee risk.) |
| Aggregate sums diverge from per-row counts (e.g. pending mid-day) | Acceptable: aggregate counts only terminal statuses; pending shown only in row panel. |

## Testing

Strict TDD. All new behavior tested before implementation. Tests use the existing in-process render pattern (`renderToday(data, container)` with synthetic `S7Data`).

### `site/src/pages/today.test.ts` (extended)

- `renders no terminus line when terminus_status is arrived`
- `renders "nur bis Solln" with --shortturn class when terminus_status is short_turn`
- `renders "nicht in München angekommen" with --missed class when terminus_status is cancelled`
- `renders "unterwegs" with --pending class when terminus_status is pending`
- `renders no terminus line when terminus_status is null`
- `wraps each row in a details element with summary`
- `expand panel shows Ankunft München Hbf with terminus_delay_minutes (not Baierbrunn delay) when arrived`
- `expand panel shows "planmäßig" with no time when arrived but terminus_delay_minutes is null`
- `expand panel shows "noch unterwegs" when pending`
- `expand panel shows "Endete in: {station}" only when short_turn`
- `expand panel omits Ankunft line when terminus_status is null`
- `expand panel includes train number when present`
- `reason moves from summary row to expand panel`
- `summary bar shows "bis München" count of arrived terminus`
- `summary bar shows "Kurzwende" count when short_turn > 0`
- `summary bar suppresses terminus items when all zero`
- `Baierbrunn-cancelled row keeps existing line-through and shows "Zug ausgefallen" in panel`

### `site/src/data.test.ts` (extended)

- `terminusAggregate counts arrived, short_turn, missed, pending per bucket`
- `terminusAggregate excludes Baierbrunn-cancelled rows`
- `terminusAggregate excludes null terminus_status rows`
- `terminusAggregate filters by Berlin "today" date`

### `site/src/pages/archive-detail.test.ts` (new)

- `renders Endpunkt header column`
- `renders "{terminus} +N" for arrived with delay`
- `renders "{station} (Kurzwende)" for short_turn`
- `renders "nicht angekommen" for cancelled terminus`
- `renders "—" for pending and null`

## Verification (manual, after deploy)

1. **Today page, good day:** rows render without terminus lines, summary bar shows "bis München" count. Tap any row → panel shows planned + actual Hbf time.
2. **Today page, short-turn event:** affected row shows orange `→ nur bis {station}` line. Tap → "Endete in:" appears in panel. Summary bar shows `⚠ 1 Kurzwende`.
3. **Today page, pending row** (mid-trip): grey italic `→ unterwegs …`. Panel shows `noch unterwegs`.
4. **Today page, cancelled at Baierbrunn:** existing line-through preserved; panel shows `Zug ausgefallen — keine Fahrt`; no Ankunft line.
5. **Archive page:** Endpunkt column populated for every row from Phase-1 era onward; pre-Phase-1 historic rows show `—`.
6. **Mobile** (iPhone SE, 375 px wide): summary row stays one line at all times; outcome line wraps to its own line when present; tap target ≥ 44 px.
7. **Lighthouse accessibility:** no regression vs current score.
8. **`npm run build` + `npm run lint`** clean.

## Out of scope

- Live polling / push updates (still hourly reload via static deploy).
- Per-train history / "where does this train usually short-turn" view.
- Visualizations of short-turn frequency (chart) — separate brainstorm.
- Notifications (email / push / RSS) for short-turn events.
- i18n beyond German.
- Editing terminus data manually.

## Cross-references

- Phase 1: [`2026-05-22-terminus-tracking-design.md`](2026-05-22-terminus-tracking-design.md)
- Delay-floor fix: [`2026-05-23-terminus-delay-fix-design.md`](2026-05-23-terminus-delay-fix-design.md)
- Multi-EVA München Hbf: [`2026-05-23-muenchen-hbf-multi-eva-design.md`](2026-05-23-muenchen-hbf-multi-eva-design.md)
- Health export: [`2026-05-23-terminus-health-export.md`](2026-05-23-terminus-health-export.md)
