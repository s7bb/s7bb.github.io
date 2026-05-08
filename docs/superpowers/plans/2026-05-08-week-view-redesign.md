# Week View Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current `Letzte 7 Tage` page (two charts, each mixing minutes and cancellation counts on one y-axis) with a compact KPI strip plus two single-unit charts grouped by metric, each showing both directions side-by-side.

**Architecture:** Pure frontend change in `site/`. New helper in `data.ts` produces a single `DayDirRow[]` array consumed by both charts. Two new chart modules expose a pure `buildXxxConfig(rows)` function (testable) and a `renderXxx(canvasId, rows)` wrapper (manual verification). KPI strip rendered as DOM by a pure helper. No fetcher / Python / `latest.json` schema change.

**Tech Stack:** TypeScript 5.4, Vite 6, Chart.js 4.4, vitest 2.1 (jsdom env), eslint 8.57.

**Spec:** `docs/superpowers/specs/2026-05-08-week-view-redesign-design.md`

**Color choice (small deviation from spec):** Spec wrote `#f59e0b` (orange) for Wolfratshausen, but `--orange` is already the "late" status color in `style.css` (semantic clash). Plan uses:
- München: `#006ab3` (matches existing `.line-badge` blue)
- Wolfratshausen: `#6c4fc4` (purple — distinct from all status colors)

Band shading hex unchanged: green `rgba(34,197,94,0.10)`, red `rgba(239,68,68,0.08)`.

---

## File Plan

| File | Action | Responsibility |
|---|---|---|
| `site/src/data.ts` | Modify | Add `DayDirRow` interface + `last7DaysByDayBothDirections(data)` |
| `site/src/data.test.ts` | Create | Unit tests for new helper |
| `site/src/charts/weekCancellationBars.ts` | Create | Pure `buildCancellationChartConfig` + `formatCancellationTooltip` + `renderWeekCancellationBars` wrapper |
| `site/src/charts/weekCancellationBars.test.ts` | Create | Unit tests for the pure helpers |
| `site/src/charts/weekDelayBars.ts` | Create | Pure `buildDelayChartConfig` + `punctualityBandPlugin` + `renderWeekDelayBars` wrapper |
| `site/src/charts/weekDelayBars.test.ts` | Create | Unit tests for the pure config builder |
| `site/src/charts/weekKpi.ts` | Create | Pure `renderWeekKpiStrip(container, agg)` DOM helper |
| `site/src/charts/weekKpi.test.ts` | Create | Unit tests for KPI rendering (jsdom) |
| `site/src/style.css` | Modify | `.kpi-strip`, `.kpi-card` styles |
| `site/src/pages/week.ts` | Modify | Restructure DOM, wire new components, drop old histogram calls |
| `site/src/charts/delayHistogram.ts` | Delete | Replaced |
| `CHANGELOG.md` | Modify | `### Changed` entry under `[Unreleased]` |

---

## Task 1: Data helper `last7DaysByDayBothDirections`

**Files:**
- Modify: `site/src/data.ts` (add at end of file)
- Create: `site/src/data.test.ts`

Existing `last7DaysByDay(data, bucket)` (`site/src/data.ts:93-116`) is preserved — `pages/stats.ts` still uses it.

- [ ] **Step 1.1: Write the failing test**

Create `site/src/data.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { last7DaysByDayBothDirections } from "./data.js";
import type { S7Data, Arrival } from "./data.js";

function arrival(overrides: Partial<Arrival>): Arrival {
  return {
    train_id: "x",
    line: "S7",
    station: "Baierbrunn",
    direction: "",
    direction_bucket: "muenchen",
    scheduled_time: "2026-05-01T08:00:00",
    actual_time: null,
    delay_minutes: 0,
    cancelled: false,
    reason: null,
    ...overrides,
  };
}

function fixture(arrivals: Arrival[]): S7Data {
  return {
    generated_at: "2026-05-08T07:00:00Z",
    station: "Baierbrunn",
    line: "S7",
    window_days: 7,
    arrivals,
    aggregates: {
      today:        { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0,
        by_direction: {
          muenchen:       { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0 },
          wolfratshausen: { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0 },
        }},
      last_7_days:  { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0,
        by_direction: {
          muenchen:       { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0 },
          wolfratshausen: { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0 },
        }},
    },
    expected_slots: { today: { muenchen: [], wolfratshausen: [] } },
  };
}

describe("last7DaysByDayBothDirections", () => {
  it("returns empty array when no arrivals", () => {
    expect(last7DaysByDayBothDirections(fixture([]))).toEqual([]);
  });

  it("groups by date and direction, computing scheduled / cancelled / avg_delay", () => {
    const data = fixture([
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", delay_minutes: 2, cancelled: false }),
      arrival({ scheduled_time: "2026-05-01T09:00:00", direction_bucket: "muenchen", delay_minutes: 4, cancelled: false }),
      arrival({ scheduled_time: "2026-05-01T10:00:00", direction_bucket: "muenchen", delay_minutes: null, cancelled: true }),
      arrival({ scheduled_time: "2026-05-01T08:30:00", direction_bucket: "wolfratshausen", delay_minutes: 1, cancelled: false }),
    ]);
    const rows = last7DaysByDayBothDirections(data);
    expect(rows).toHaveLength(1);
    expect(rows[0].date).toBe("2026-05-01");
    expect(rows[0].muenchen).toEqual({ avg_delay: 3, cancelled: 1, scheduled: 3 });
    expect(rows[0].wolfratshausen).toEqual({ avg_delay: 1, cancelled: 0, scheduled: 1 });
  });

  it("ignores arrivals with direction_bucket 'unknown'", () => {
    const data = fixture([
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "unknown", delay_minutes: 99, cancelled: false }),
    ]);
    expect(last7DaysByDayBothDirections(data)).toEqual([]);
  });

  it("yields zero sub-row when one direction is absent on a date", () => {
    const data = fixture([
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", delay_minutes: 5, cancelled: false }),
    ]);
    const rows = last7DaysByDayBothDirections(data);
    expect(rows[0].muenchen).toEqual({ avg_delay: 5, cancelled: 0, scheduled: 1 });
    expect(rows[0].wolfratshausen).toEqual({ avg_delay: 0, cancelled: 0, scheduled: 0 });
  });

  it("returns dates ascending across multiple days", () => {
    const data = fixture([
      arrival({ scheduled_time: "2026-05-03T08:00:00", direction_bucket: "muenchen", delay_minutes: 1 }),
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", delay_minutes: 2 }),
      arrival({ scheduled_time: "2026-05-02T08:00:00", direction_bucket: "muenchen", delay_minutes: 3 }),
    ]);
    const rows = last7DaysByDayBothDirections(data);
    expect(rows.map(r => r.date)).toEqual(["2026-05-01", "2026-05-02", "2026-05-03"]);
  });

  it("treats avg_delay as 0 when direction has only cancelled arrivals", () => {
    const data = fixture([
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", cancelled: true, delay_minutes: null }),
    ]);
    expect(last7DaysByDayBothDirections(data)[0].muenchen).toEqual({ avg_delay: 0, cancelled: 1, scheduled: 1 });
  });
});
```

- [ ] **Step 1.2: Run the test, verify it fails**

```bash
cd site && npm test -- data.test.ts
```

Expected: FAIL — "last7DaysByDayBothDirections is not exported from ./data.js" or similar import error.

- [ ] **Step 1.3: Implement the function**

Append to `site/src/data.ts`:

```ts
export interface DayDirStats {
  avg_delay: number;
  cancelled: number;
  scheduled: number;
}

export interface DayDirRow {
  date: string;
  muenchen: DayDirStats;
  wolfratshausen: DayDirStats;
}

export function last7DaysByDayBothDirections(data: S7Data): DayDirRow[] {
  type Bucket = "muenchen" | "wolfratshausen";
  const acc = new Map<string, Record<Bucket, { delays: number[]; cancelled: number; scheduled: number }>>();

  for (const a of data.arrivals) {
    if (a.direction_bucket !== "muenchen" && a.direction_bucket !== "wolfratshausen") continue;
    const bucket: Bucket = a.direction_bucket;
    const date = a.scheduled_time.slice(0, 10);
    if (!acc.has(date)) {
      acc.set(date, {
        muenchen:       { delays: [], cancelled: 0, scheduled: 0 },
        wolfratshausen: { delays: [], cancelled: 0, scheduled: 0 },
      });
    }
    const day = acc.get(date)!;
    day[bucket].scheduled++;
    if (a.cancelled) {
      day[bucket].cancelled++;
    } else if (a.delay_minutes !== null) {
      day[bucket].delays.push(a.delay_minutes);
    }
  }

  const toStats = (b: { delays: number[]; cancelled: number; scheduled: number }): DayDirStats => ({
    avg_delay: b.delays.length ? b.delays.reduce((s, d) => s + d, 0) / b.delays.length : 0,
    cancelled: b.cancelled,
    scheduled: b.scheduled,
  });

  return [...acc.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, { muenchen, wolfratshausen }]) => ({
      date,
      muenchen: toStats(muenchen),
      wolfratshausen: toStats(wolfratshausen),
    }));
}
```

- [ ] **Step 1.4: Run the test, verify it passes**

```bash
cd site && npm test -- data.test.ts
```

Expected: PASS, all 6 tests green.

- [ ] **Step 1.5: Lint and type-check**

```bash
cd site && npm run lint && npm run build
```

Expected: lint OK, type-check OK, build OK.

- [ ] **Step 1.6: Commit**

```bash
git add site/src/data.ts site/src/data.test.ts
git commit -m "feat(site): add last7DaysByDayBothDirections data helper"
```

---

## Task 2: Cancellation chart helpers (pure)

**Files:**
- Create: `site/src/charts/weekCancellationBars.ts`
- Create: `site/src/charts/weekCancellationBars.test.ts`

We split this chart's logic into three exports: a tooltip formatter (pure string), a config builder (pure object), and a `renderWeekCancellationBars(canvasId, rows)` wrapper that mounts to DOM. Only the pure exports get unit tests; the wrapper is verified manually because Chart.js needs canvas APIs jsdom does not implement.

- [ ] **Step 2.1: Write the failing test**

Create `site/src/charts/weekCancellationBars.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import {
  formatCancellationTooltip,
  buildCancellationChartConfig,
} from "./weekCancellationBars.js";
import type { DayDirRow } from "../data.js";

const rows: DayDirRow[] = [
  {
    date: "2026-05-01",
    muenchen:       { avg_delay: 0, cancelled: 2, scheduled: 14 },
    wolfratshausen: { avg_delay: 0, cancelled: 1, scheduled: 7  },
  },
  {
    date: "2026-05-02",
    muenchen:       { avg_delay: 0, cancelled: 0, scheduled: 14 },
    wolfratshausen: { avg_delay: 0, cancelled: 0, scheduled: 7  },
  },
];

describe("formatCancellationTooltip", () => {
  it("uses plural Ausfälle for n != 1", () => {
    expect(formatCancellationTooltip("München", 2, 14))
      .toBe("München: 2 Ausfälle (2 von 14 geplant, 14 %)");
  });
  it("uses singular Ausfall for n == 1", () => {
    expect(formatCancellationTooltip("Wolfratshausen", 1, 7))
      .toBe("Wolfratshausen: 1 Ausfall (1 von 7 geplant, 14 %)");
  });
  it("zero scheduled yields 0 %", () => {
    expect(formatCancellationTooltip("München", 0, 0))
      .toBe("München: 0 Ausfälle (0 von 0 geplant, 0 %)");
  });
});

describe("buildCancellationChartConfig", () => {
  const cfg = buildCancellationChartConfig(rows);

  it("is a bar chart with two datasets", () => {
    expect(cfg.type).toBe("bar");
    expect(cfg.data.datasets).toHaveLength(2);
    expect(cfg.data.datasets[0].label).toBe("München");
    expect(cfg.data.datasets[1].label).toBe("Wolfratshausen");
  });

  it("uses MÜ blue and WO purple", () => {
    expect(cfg.data.datasets[0].backgroundColor).toBe("#006ab3");
    expect(cfg.data.datasets[1].backgroundColor).toBe("#6c4fc4");
  });

  it("maps cancellation counts in row order", () => {
    expect(cfg.data.datasets[0].data).toEqual([2, 0]);
    expect(cfg.data.datasets[1].data).toEqual([1, 0]);
  });

  it("formats day labels in German short form", () => {
    expect(cfg.data.labels).toHaveLength(2);
    expect(cfg.data.labels?.[0]).toMatch(/\d/);
  });

  it("y-axis is integer, beginAtZero", () => {
    const y = cfg.options?.scales?.y as { beginAtZero?: boolean; ticks?: { precision?: number } };
    expect(y.beginAtZero).toBe(true);
    expect(y.ticks?.precision).toBe(0);
  });
});
```

- [ ] **Step 2.2: Run the test, verify it fails**

```bash
cd site && npm test -- weekCancellationBars.test.ts
```

Expected: FAIL — module not found.

- [ ] **Step 2.3: Implement the chart module**

Create `site/src/charts/weekCancellationBars.ts`:

```ts
import {
  Chart, BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend,
  type ChartConfiguration, type TooltipItem,
} from "chart.js";
import type { DayDirRow } from "../data.js";

Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend);

const COLOR_MUENCHEN = "#006ab3";
const COLOR_WOLFRATSHAUSEN = "#6c4fc4";

function formatDay(dateIso: string): string {
  const dt = new Date(dateIso);
  return dt.toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "numeric" });
}

export function formatCancellationTooltip(direction: string, n: number, scheduled: number): string {
  const word = n === 1 ? "Ausfall" : "Ausfälle";
  const pct = scheduled === 0 ? 0 : Math.round((n / scheduled) * 100);
  return `${direction}: ${n} ${word} (${n} von ${scheduled} geplant, ${pct} %)`;
}

export function buildCancellationChartConfig(rows: DayDirRow[]): ChartConfiguration<"bar"> {
  const labels = rows.map(r => formatDay(r.date));
  const muData = rows.map(r => r.muenchen.cancelled);
  const woData = rows.map(r => r.wolfratshausen.cancelled);
  const muScheduled = rows.map(r => r.muenchen.scheduled);
  const woScheduled = rows.map(r => r.wolfratshausen.scheduled);

  return {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "München",        data: muData, backgroundColor: COLOR_MUENCHEN },
        { label: "Wolfratshausen", data: woData, backgroundColor: COLOR_WOLFRATSHAUSEN },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { position: "top" },
        tooltip: {
          callbacks: {
            label: (item: TooltipItem<"bar">) => {
              const direction = item.dataset.label ?? "";
              const n = item.parsed.y;
              const scheduled = item.datasetIndex === 0 ? muScheduled[item.dataIndex] : woScheduled[item.dataIndex];
              return formatCancellationTooltip(direction, n, scheduled);
            },
          },
        },
      },
      scales: {
        y: { beginAtZero: true, ticks: { precision: 0 } },
      },
    },
  };
}

export function renderWeekCancellationBars(canvasId: string, rows: DayDirRow[]): void {
  const canvas = document.getElementById(canvasId) as HTMLCanvasElement | null;
  if (!canvas) return;
  Chart.getChart(canvas)?.destroy();
  new Chart(canvas, buildCancellationChartConfig(rows));
}
```

- [ ] **Step 2.4: Run the test, verify it passes**

```bash
cd site && npm test -- weekCancellationBars.test.ts
```

Expected: PASS, all 8 tests green.

- [ ] **Step 2.5: Lint and type-check**

```bash
cd site && npm run lint && npm run build
```

Expected: clean.

- [ ] **Step 2.6: Commit**

```bash
git add site/src/charts/weekCancellationBars.ts site/src/charts/weekCancellationBars.test.ts
git commit -m "feat(site): add weekCancellationBars chart"
```

---

## Task 3: Delay chart helpers (pure)

**Files:**
- Create: `site/src/charts/weekDelayBars.ts`
- Create: `site/src/charts/weekDelayBars.test.ts`

The 0–6 min green / above-6 red shading is implemented as a Chart.js plugin object. The plugin uses `chart.scales.y` to convert the y=0/y=6/y=top thresholds to pixels and fills two rects in `beforeDatasetsDraw` so bars draw over the bands.

- [ ] **Step 3.1: Write the failing test**

Create `site/src/charts/weekDelayBars.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import {
  buildDelayChartConfig,
  PUNCTUALITY_THRESHOLD_MIN,
  punctualityBandPlugin,
} from "./weekDelayBars.js";
import type { DayDirRow } from "../data.js";

const rows: DayDirRow[] = [
  {
    date: "2026-05-01",
    muenchen:       { avg_delay: 3.2, cancelled: 0, scheduled: 14 },
    wolfratshausen: { avg_delay: 4.1, cancelled: 0, scheduled: 7  },
  },
  {
    date: "2026-05-02",
    muenchen:       { avg_delay: 1.0, cancelled: 0, scheduled: 14 },
    wolfratshausen: { avg_delay: 7.5, cancelled: 0, scheduled: 7  },
  },
];

describe("buildDelayChartConfig", () => {
  const cfg = buildDelayChartConfig(rows);

  it("is a bar chart with two datasets", () => {
    expect(cfg.type).toBe("bar");
    expect(cfg.data.datasets).toHaveLength(2);
    expect(cfg.data.datasets[0].label).toBe("München");
    expect(cfg.data.datasets[1].label).toBe("Wolfratshausen");
  });

  it("uses MÜ blue and WO purple", () => {
    expect(cfg.data.datasets[0].backgroundColor).toBe("#006ab3");
    expect(cfg.data.datasets[1].backgroundColor).toBe("#6c4fc4");
  });

  it("rounds avg_delay to 1 decimal", () => {
    expect(cfg.data.datasets[0].data).toEqual([3.2, 1.0]);
    expect(cfg.data.datasets[1].data).toEqual([4.1, 7.5]);
  });

  it("y-axis begins at zero", () => {
    const y = cfg.options?.scales?.y as { beginAtZero?: boolean };
    expect(y.beginAtZero).toBe(true);
  });

  it("registers the punctuality band plugin", () => {
    expect(cfg.plugins).toBeDefined();
    expect(cfg.plugins).toContain(punctualityBandPlugin);
  });
});

describe("PUNCTUALITY_THRESHOLD_MIN", () => {
  it("is 6 (DB convention)", () => {
    expect(PUNCTUALITY_THRESHOLD_MIN).toBe(6);
  });
});

describe("punctualityBandPlugin", () => {
  it("has id 'punctualityBand'", () => {
    expect(punctualityBandPlugin.id).toBe("punctualityBand");
  });

  it("defines beforeDatasetsDraw", () => {
    expect(typeof punctualityBandPlugin.beforeDatasetsDraw).toBe("function");
  });
});
```

- [ ] **Step 3.2: Run the test, verify it fails**

```bash
cd site && npm test -- weekDelayBars.test.ts
```

Expected: FAIL — module not found.

- [ ] **Step 3.3: Implement the chart module**

Create `site/src/charts/weekDelayBars.ts`:

```ts
import {
  Chart, BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend,
  type ChartConfiguration, type Plugin, type TooltipItem,
} from "chart.js";
import type { DayDirRow } from "../data.js";

Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend);

const COLOR_MUENCHEN = "#006ab3";
const COLOR_WOLFRATSHAUSEN = "#6c4fc4";
const COLOR_BAND_GREEN = "rgba(34,197,94,0.10)";
const COLOR_BAND_RED   = "rgba(239,68,68,0.08)";

export const PUNCTUALITY_THRESHOLD_MIN = 6;

function formatDay(dateIso: string): string {
  const dt = new Date(dateIso);
  return dt.toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "numeric" });
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

export const punctualityBandPlugin: Plugin<"bar"> = {
  id: "punctualityBand",
  beforeDatasetsDraw(chart) {
    const { ctx, chartArea } = chart;
    const yScale = chart.scales.y;
    if (!yScale) return;
    const top = chartArea.top;
    const bottom = chartArea.bottom;
    const left = chartArea.left;
    const right = chartArea.right;
    const yMaxData = yScale.max;
    const thresholdY = yScale.getPixelForValue(Math.min(PUNCTUALITY_THRESHOLD_MIN, yMaxData));

    ctx.save();
    ctx.fillStyle = COLOR_BAND_GREEN;
    ctx.fillRect(left, thresholdY, right - left, bottom - thresholdY);

    if (yMaxData > PUNCTUALITY_THRESHOLD_MIN) {
      ctx.fillStyle = COLOR_BAND_RED;
      ctx.fillRect(left, top, right - left, thresholdY - top);
    }
    ctx.restore();
  },
};

export function buildDelayChartConfig(rows: DayDirRow[]): ChartConfiguration<"bar"> {
  const labels = rows.map(r => formatDay(r.date));
  const muData = rows.map(r => round1(r.muenchen.avg_delay));
  const woData = rows.map(r => round1(r.wolfratshausen.avg_delay));

  return {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "München",        data: muData, backgroundColor: COLOR_MUENCHEN },
        { label: "Wolfratshausen", data: woData, backgroundColor: COLOR_WOLFRATSHAUSEN },
      ],
    },
    plugins: [punctualityBandPlugin],
    options: {
      responsive: true,
      plugins: {
        legend: { position: "top" },
        tooltip: {
          callbacks: {
            label: (item: TooltipItem<"bar">) =>
              `${item.dataset.label}: Ø ${item.parsed.y.toFixed(1)} min`,
          },
        },
      },
      scales: {
        y: { beginAtZero: true, title: { display: true, text: "Minuten" } },
      },
    },
  };
}

export function renderWeekDelayBars(canvasId: string, rows: DayDirRow[]): void {
  const canvas = document.getElementById(canvasId) as HTMLCanvasElement | null;
  if (!canvas) return;
  Chart.getChart(canvas)?.destroy();
  new Chart(canvas, buildDelayChartConfig(rows));
}
```

- [ ] **Step 3.4: Run the test, verify it passes**

```bash
cd site && npm test -- weekDelayBars.test.ts
```

Expected: PASS, all 7 tests green.

- [ ] **Step 3.5: Lint and type-check**

```bash
cd site && npm run lint && npm run build
```

Expected: clean.

- [ ] **Step 3.6: Commit**

```bash
git add site/src/charts/weekDelayBars.ts site/src/charts/weekDelayBars.test.ts
git commit -m "feat(site): add weekDelayBars chart with punctuality band"
```

---

## Task 4: KPI strip helper

**Files:**
- Create: `site/src/charts/weekKpi.ts`
- Create: `site/src/charts/weekKpi.test.ts`

KPI strip is plain DOM injection — fully testable in jsdom. Helper accepts the `last_7_days.by_direction` aggregate object and a target container, fills it with two `.kpi-card` divs.

- [ ] **Step 4.1: Write the failing test**

Create `site/src/charts/weekKpi.test.ts`:

```ts
import { describe, it, expect, beforeEach } from "vitest";
import { renderWeekKpiStrip } from "./weekKpi.js";
import type { DirectionAggregate } from "../data.js";

function aggregate(over: Partial<DirectionAggregate> = {}): DirectionAggregate {
  return { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0, ...over };
}

let host: HTMLElement;

beforeEach(() => {
  document.body.innerHTML = `<div id="host"></div>`;
  host = document.getElementById("host")!;
});

describe("renderWeekKpiStrip", () => {
  it("renders two kpi cards", () => {
    renderWeekKpiStrip(host, {
      muenchen:       aggregate({ avg_delay_min: 3.2, cancelled: 2 }),
      wolfratshausen: aggregate({ avg_delay_min: 4.1, cancelled: 1 }),
    });
    const cards = host.querySelectorAll(".kpi-card");
    expect(cards).toHaveLength(2);
  });

  it("uses singular Ausfall for cancelled === 1", () => {
    renderWeekKpiStrip(host, {
      muenchen:       aggregate({ avg_delay_min: 3.2, cancelled: 2 }),
      wolfratshausen: aggregate({ avg_delay_min: 4.1, cancelled: 1 }),
    });
    expect(host.textContent).toContain("1 Ausfall");
    expect(host.textContent).toContain("2 Ausfälle");
  });

  it("rounds avg_delay_min to 1 decimal with German comma", () => {
    renderWeekKpiStrip(host, {
      muenchen:       aggregate({ avg_delay_min: 3.247, cancelled: 0 }),
      wolfratshausen: aggregate({ avg_delay_min: 4.0,  cancelled: 0 }),
    });
    expect(host.textContent).toContain("Ø 3,2 min");
    expect(host.textContent).toContain("Ø 4,0 min");
  });

  it("includes both direction labels", () => {
    renderWeekKpiStrip(host, {
      muenchen:       aggregate(),
      wolfratshausen: aggregate(),
    });
    expect(host.textContent).toContain("München");
    expect(host.textContent).toContain("Wolfratshausen");
  });

  it("renders em-dash placeholders when aggregate is missing", () => {
    renderWeekKpiStrip(host, undefined);
    expect(host.textContent).toContain("Ø — min");
    expect(host.textContent).toContain("— Ausfälle");
  });
});
```

- [ ] **Step 4.2: Run the test, verify it fails**

```bash
cd site && npm test -- weekKpi.test.ts
```

Expected: FAIL — module not found.

- [ ] **Step 4.3: Implement the helper**

Create `site/src/charts/weekKpi.ts`:

```ts
import type { DirectionAggregate } from "../data.js";

type KpiInput =
  | { muenchen: DirectionAggregate; wolfratshausen: DirectionAggregate }
  | undefined;

function ausfallWord(n: number): string {
  return n === 1 ? "Ausfall" : "Ausfälle";
}

function formatMin(n: number): string {
  return n.toFixed(1).replace(".", ",");
}

function cardHtml(label: string, agg: DirectionAggregate | undefined): string {
  if (!agg) {
    return `
      <div class="kpi-card">
        <div class="kpi-card__title">→ ${label}</div>
        <div class="kpi-card__stats">Ø — min · — Ausfälle</div>
      </div>
    `;
  }
  return `
    <div class="kpi-card">
      <div class="kpi-card__title">→ ${label}</div>
      <div class="kpi-card__stats">Ø ${formatMin(agg.avg_delay_min)} min · ${agg.cancelled} ${ausfallWord(agg.cancelled)}</div>
    </div>
  `;
}

export function renderWeekKpiStrip(container: HTMLElement, agg: KpiInput): void {
  container.innerHTML = `
    <div class="kpi-strip">
      ${cardHtml("München",        agg?.muenchen)}
      ${cardHtml("Wolfratshausen", agg?.wolfratshausen)}
    </div>
  `;
}
```

- [ ] **Step 4.4: Run the test, verify it passes**

```bash
cd site && npm test -- weekKpi.test.ts
```

Expected: PASS, all 5 tests green.

- [ ] **Step 4.5: Lint and type-check**

```bash
cd site && npm run lint && npm run build
```

Expected: clean.

- [ ] **Step 4.6: Commit**

```bash
git add site/src/charts/weekKpi.ts site/src/charts/weekKpi.test.ts
git commit -m "feat(site): add weekKpi strip renderer"
```

---

## Task 5: CSS for KPI strip

**Files:**
- Modify: `site/src/style.css` (append at end of file)

- [ ] **Step 5.1: Append the styles**

Add to the end of `site/src/style.css`:

```css
/* Week KPI strip */
.kpi-strip {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
  margin-bottom: 1.25rem;
}
.kpi-card {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.6rem 0.9rem;
}
.kpi-card__title { font-size: 0.85rem; font-weight: 600; color: #555; margin-bottom: 0.2rem; }
.kpi-card__stats { font-size: 0.95rem; font-variant-numeric: tabular-nums; }
@media (max-width: 480px) { .kpi-strip { grid-template-columns: 1fr; } }
```

- [ ] **Step 5.2: Verify build still works**

```bash
cd site && npm run build
```

Expected: clean build.

- [ ] **Step 5.3: Commit**

```bash
git add site/src/style.css
git commit -m "feat(site): add kpi-strip styles"
```

---

## Task 6: Wire `week.ts` to use new components

**Files:**
- Modify: `site/src/pages/week.ts` (full replacement)
- Delete: `site/src/charts/delayHistogram.ts`

Before deleting `delayHistogram.ts`, verify no other file imports it.

- [ ] **Step 6.1: Verify no remaining importers**

```bash
grep -rn "delayHistogram\|renderDelayHistogram" site/src/ | grep -v "delayHistogram.ts"
```

Expected: empty output (only `week.ts:2` and `week.ts:3` reference it, and we are about to overwrite `week.ts`).

If anything else shows up, stop and reassess.

- [ ] **Step 6.2: Replace `site/src/pages/week.ts`**

Overwrite `site/src/pages/week.ts` with:

```ts
import type { S7Data } from "../data.js";
import { last7DaysByDayBothDirections } from "../data.js";
import { renderWeekKpiStrip } from "../charts/weekKpi.js";
import { renderWeekDelayBars } from "../charts/weekDelayBars.js";
import { renderWeekCancellationBars } from "../charts/weekCancellationBars.js";
import { loadIndex } from "../archive.js";
import { renderMonthsBar } from "../charts/monthsBar.js";

export async function renderWeek(data: S7Data, container: HTMLElement): Promise<void> {
  const agg = data.aggregates.last_7_days.by_direction;
  const rows = last7DaysByDayBothDirections(data);

  container.innerHTML = `
    <h2>Letzte 7 Tage — S7 Baierbrunn</h2>
    <div id="week-kpi"></div>
    <div class="chart-container">
      <h3>Ø Verspätung (Minuten)</h3>
      <canvas id="chart-week-delay"></canvas>
    </div>
    <div class="chart-container">
      <h3>Ausfälle (Anzahl)</h3>
      <canvas id="chart-week-cancellations"></canvas>
    </div>
    <h3>Letzte 12 Monate</h3>
    <div class="chart-container">
      <canvas id="chart-week-months"></canvas>
    </div>
  `;

  renderWeekKpiStrip(document.getElementById("week-kpi")!, agg);
  renderWeekDelayBars("chart-week-delay", rows);
  renderWeekCancellationBars("chart-week-cancellations", rows);

  try {
    const idx = await loadIndex();
    renderMonthsBar("chart-week-months", idx.months.slice(-12));
  } catch {
    const el = document.getElementById("chart-week-months")?.parentElement;
    if (el) el.innerHTML = `<p class="error">Monatsübersicht nicht verfügbar</p>`;
  }
}
```

- [ ] **Step 6.3: Delete the obsolete chart file**

```bash
rm site/src/charts/delayHistogram.ts
```

- [ ] **Step 6.4: Run the full test suite**

```bash
cd site && npm test
```

Expected: all tests pass (existing + the 4 new test files).

- [ ] **Step 6.5: Lint and build**

```bash
cd site && npm run lint && npm run build
```

Expected: clean.

- [ ] **Step 6.6: Commit**

```bash
git add site/src/pages/week.ts site/src/charts/delayHistogram.ts
git commit -m "feat(site): rebuild Letzte-7-Tage view with split charts and kpi strip"
```

---

## Task 7: Manual smoke test

**Files:** none touched in this task.

- [ ] **Step 7.1: Start dev server**

```bash
cd site && npm run dev
```

Vite reports a local URL (e.g. `http://localhost:5173`).

- [ ] **Step 7.2: Open the Letzte-7-Tage page**

In a browser, navigate to the Vite URL and click the `Letzte 7 Tage` nav link.

Visually confirm:
- KPI strip shows two cards with `→ München` and `→ Wolfratshausen`, each with `Ø X,Y min · N Ausfälle`.
- Singular `Ausfall` appears only when count is exactly 1; plural `Ausfälle` otherwise.
- "Ø Verspätung (Minuten)" chart: grouped bars per day, München blue (#006ab3), Wolfratshausen purple (#6c4fc4). Green band visible up to y=6. If any bar reaches above 6, a faint red band appears above 6.
- "Ausfälle (Anzahl)" chart: grouped bars same colors. Tooltip on hover/tap shows e.g. `München: 2 Ausfälle (2 von 14 geplant, 14 %)`.
- Months chart unchanged below.

- [ ] **Step 7.3: Resize to mobile width (≤ 480 px)**

Use browser devtools responsive mode. Confirm:
- KPI cards stack vertically.
- Charts shrink responsively, x-axis labels readable (Chart.js may rotate them).

- [ ] **Step 7.4: Stop dev server**

`Ctrl+C` in the terminal running Vite.

If anything in 7.2 or 7.3 looks wrong, fix and commit before proceeding. Otherwise no commit needed for this task.

---

## Task 8: Changelog and final commit

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 8.1: Add Changed entry under `[Unreleased]`**

Edit `CHANGELOG.md`. The current header looks like:

```
## [Unreleased]

### Added
- Today page footer now shows the expected time of the next data refresh ...
- Startup preflight check in `s7bb-fetcher` ...
```

Add a new `### Changed` section under `[Unreleased]` (or append to it if already present):

```
### Changed
- Letzte-7-Tage view: Verspätung und Ausfälle in getrennte Diagramme aufgeteilt; Ø-Verspätung mit grünem Pünktlichkeitsband (0–6 min); kompakter KPI-Streifen pro Richtung; konsistente Farben für Richtung München (blau) und Wolfratshausen (lila).
```

- [ ] **Step 8.2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): note week-view redesign under Unreleased"
```

---

## Acceptance criteria (verify before declaring done)

- [ ] `cd site && npm test` — all green
- [ ] `cd site && npm run lint` — clean
- [ ] `cd site && npm run build` — clean
- [ ] Manual smoke (Task 7) passed
- [ ] `git log --oneline` shows 7 commits since the spec commit, one per Task 1–6 plus 8 (Task 7 has no commit)
- [ ] No remaining references to `delayHistogram` or `renderDelayHistogram` in `site/src/`
- [ ] `pages/stats.ts` still works (it imports `last7DaysByDay` and `avgDelayLine`, both untouched)
