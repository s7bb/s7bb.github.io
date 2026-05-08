# Week View Redesign — Decoupling Delay and Cancellation Metrics

Date: 2026-05-08
Status: Draft, awaiting user review

## Problem

The current "Letzte 7 Tage" page renders two charts (one per direction). Each chart mixes two heterogeneous metrics on a single y-axis:

- Ø Verspätung in **minutes** (continuous, typical range 0–10)
- Ausfälle as a **count** (discrete, typical range 0–10)

A shared y-axis with mismatched units is misleading — readers cannot meaningfully compare bar heights, and small delay values get visually dwarfed when cancellations spike. Data-viz literature (Datawrapper, Knaflic, Flourish, FT Visual Vocabulary) and major transit dashboards (SBB, MTA, TfL, DB Konzern) all avoid this pattern.

## Goals

The redesign must serve three reader tasks equally:

1. "How bad has the past week been overall?" — fast at-a-glance summary.
2. "Is my direction reliable?" — direction comparison.
3. "Are cancellations clustering on specific days?" — outage pattern visibility.

## Non-goals

- No fetcher / Python changes.
- No `latest.json` schema change.
- No change to today, archive, monthly, or methodology pages.
- No new external dependencies (band shading via inline Chart.js plugin, not `chartjs-plugin-annotation`).

## Approach

**Group by metric.** One chart per metric, both directions inside the chart as grouped bars. Two charts replace the current two — same chart count, but each chart has one clean unit. Color encodes direction (consistent across both charts and KPI strip).

Rejected alternatives:
- *Group by direction* (two stacked panels per direction) — better for "deep dive into one direction" but worse for direction comparison, which the user weighted equally.
- *SBB-style single composite punctuality %* — folds cancellations into one KPI; loses the "how many trains vanished" signal that residents care about.
- *Dual-axis chart* — universally cautioned against in visualization literature.

## Layout

```
┌──────────────────────────────────────────────────────────┐
│  Letzte 7 Tage — S7 Baierbrunn                           │
├────────────────────────────┬─────────────────────────────┤
│ → München                  │ → Wolfratshausen            │
│ Ø 3,2 min · 2 Ausfälle     │ Ø 4,1 min · 1 Ausfall       │
├────────────────────────────┴─────────────────────────────┤
│  Ø Verspätung (Minuten)                                  │
│  [grouped bars, Mü blue / Wo orange, green band 0–6 min, │
│   red band above 6 min, 7 day labels]                    │
├──────────────────────────────────────────────────────────┤
│  Ausfälle (Anzahl)                                       │
│  [grouped bars, Mü blue / Wo orange, integer y-axis,     │
│   tooltip: "München: 2 Ausfälle (2 von 14 geplant, 14%)"]│
├──────────────────────────────────────────────────────────┤
│  Letzte 12 Monate (unchanged)                            │
└──────────────────────────────────────────────────────────┘
```

KPI cards stack vertically on narrow screens.

## Components

### KPI strip
Inline in `week.ts` markup, styled in `style.css` as `.kpi-card`. Two cards side-by-side (CSS grid, `1fr 1fr`, gap, fallback to single column under ~480 px). Content per card: direction arrow + label, then `Ø {n} min · {k} Ausfälle` with German singular/plural agreement (`1 Ausfall` / `n Ausfälle`). Values from `data.aggregates.last_7_days.by_direction.{muenchen,wolfratshausen}`.

### `weekDelayBars` (`site/src/charts/weekDelayBars.ts`, new)
- Chart.js grouped bar chart.
- Two datasets: München (`#3b82f6`), Wolfratshausen (`#f59e0b`).
- x-axis: 7 day labels, German locale, format `Mo 5.5.`.
- y-axis: minutes, `beginAtZero: true`, no upper cap.
- Background bands via inline Chart.js plugin (`beforeDraw`): `rgba(34,197,94,0.10)` from y=0 to y=6, `rgba(239,68,68,0.08)` from y=6 to chart top. Plugin reads `chart.scales.y` to convert data values to pixel coordinates; clamps to current y-range.
- Tooltip: `{Direction}: Ø {n.toFixed(1)} min`.
- Legend: top, default Chart.js styling.

### `weekCancellationBars` (`site/src/charts/weekCancellationBars.ts`, new)
- Chart.js grouped bar chart, same colors as `weekDelayBars`.
- x-axis: same 7 day labels.
- y-axis: count, integer ticks (`ticks.precision: 0`), `beginAtZero: true`.
- Tooltip callback: `{Direction}: {k} {Ausfall|Ausfälle} ({k} von {scheduled} geplant, {pct}%)`. The plural and percent are computed in a pure helper `formatCancellationTooltip(direction, k, scheduled)` exported alongside the chart for unit testing.

### `last7DaysByDayBothDirections` (`site/src/data.ts`, new)
```ts
export interface DayDirRow {
  date: string;
  muenchen:        { avg_delay: number; cancelled: number; scheduled: number };
  wolfratshausen:  { avg_delay: number; cancelled: number; scheduled: number };
}
export function last7DaysByDayBothDirections(data: S7Data): DayDirRow[];
```
Iterates `data.arrivals` once, keys on `(scheduled_time.slice(0,10), direction_bucket)`. Per `muenchen` / `wolfratshausen` bucket: increment `scheduled` always; if `cancelled` increment `cancelled`; else if `delay_minutes !== null` push to delays. Arrivals with `direction_bucket === "unknown"` are skipped entirely (same behavior as today's per-direction histogram). Emit one `DayDirRow` per date sorted ascending. If a date saw only one of the two directions, the missing direction's sub-object is `{ avg_delay: 0, cancelled: 0, scheduled: 0 }`. `avg_delay` is `0` when no non-cancelled samples; downstream chart treats this as a real 0-min day (matches current behavior).

## Data flow

```
load latest.json
  → renderKpiStrip(agg.last_7_days.by_direction)
  → const rows = last7DaysByDayBothDirections(data)
  → renderWeekDelayBars("chart-week-delay", rows)
  → renderWeekCancellationBars("chart-week-cancellations", rows)
  → loadIndex() → renderMonthsBar("chart-week-months", ...)   // unchanged
```

Both charts read the same `DayDirRow[]` array — single source of truth, no shape mismatch.

## Files touched

- `site/src/pages/week.ts` — restructure DOM, replace two histogram calls with KPI strip + two new chart calls.
- `site/src/charts/delayHistogram.ts` — **delete** (only `week.ts` imports it; verified via grep).
- `site/src/charts/weekDelayBars.ts` — **new**.
- `site/src/charts/weekCancellationBars.ts` — **new**.
- `site/src/data.ts` — add `DayDirRow` interface and `last7DaysByDayBothDirections`. **Keep** `last7DaysByDay` because `pages/stats.ts` still uses it.
- `site/src/style.css` — `.kpi-card`, `.kpi-strip` styles.
- `site/src/charts/weekDelayBars.test.ts` — **new**.
- `site/src/charts/weekCancellationBars.test.ts` — **new**.
- `site/src/data.test.ts` — extend or create with `last7DaysByDayBothDirections` tests.

`avgDelayLine.ts` and `last7DaysByDay` retained — used by `pages/stats.ts`. Stats page is out of scope for this redesign.

## Error handling

- Missing `aggregates.last_7_days.by_direction` (very old `latest.json`): KPI cards render `Ø — min · — Ausfälle`. No throw.
- Empty `arrivals[]` window: charts render 7 day labels with zero-height bars; cancellation tooltip shows `0 von 0 geplant`; band plugin clamps to actual (collapsed) y-range so the green band still appears.
- One direction missing on a date: emit zero row for that bucket.
- Months chart load fails: existing `try/catch` keeps `<p class="error">Monatsübersicht nicht verfügbar</p>`.
- Chart.js responsive sizing: `responsive: true`, default `maintainAspectRatio`. Verify on mobile during manual review.

## Testing

Unit tests (vitest, JSDOM, follow existing `today.test.ts` / `archive.test.ts` style):

- **`data.test.ts`**: `last7DaysByDayBothDirections` against a synthetic `S7Data` fixture with mixed Mü/Wo arrivals, some cancelled, some `unknown` direction, some dates with only one direction. Assertions: 7 dates ascending; `scheduled` counts match raw arrivals; cancelled excluded from `avg_delay`; `avg_delay === 0` when no non-cancelled samples; `unknown` ignored; missing-direction rows are zero.
- **`weekDelayBars.test.ts`**: render into JSDOM canvas; assert Chart instance has 2 datasets, expected day labels, expected colors, `beginAtZero: true`. No pixel diff.
- **`weekCancellationBars.test.ts`**: same shape. Plus: `formatCancellationTooltip("München", 2, 14)` → `"München: 2 Ausfälle (2 von 14 geplant, 14%)"` and singular case `formatCancellationTooltip("Wolfratshausen", 1, 7)` → `"Wolfratshausen: 1 Ausfall (1 von 7 geplant, 14%)"` and zero-scheduled case → `"… (0 von 0 geplant, 0%)"`.

Manual checks (called out, not automated):

- `npm run dev`, view at desktop + mobile viewport.
- Plural agreement (Ausfall / Ausfälle).
- Green band visible when all bars < 6; red region appears only when any bar ≥ 6.
- KPI cards stack on narrow screens.

## Out of scope

- Replacing Ø-min with DB-style "% pünktlich (<6 min)" KPI — separate decision, not bundled.
- Schwere-Verspätung (≥6 min) breakdown as third metric.
- Today/archive/monthly view changes.
- Color-blind palette tuning beyond the chosen blue/orange.

## CHANGELOG entry (preview)

`### Changed` — Letzte-7-Tage view: Verspätung und Ausfälle in getrennte Diagramme aufgeteilt; Ø-Verspätung mit grünem Pünktlichkeitsband (0–6 min); kompakter KPI-Streifen pro Richtung; konsistente Farben für Richtung München / Wolfratshausen.
