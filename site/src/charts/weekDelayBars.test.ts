import { describe, it, expect } from "vitest";
import type { Chart } from "chart.js";
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

describe("punctualityBandPlugin > beforeDatasetsDraw", () => {
  type Call = { type: string; args: unknown[] };

  function stubCtx(): { ctx: CanvasRenderingContext2D; calls: Call[] } {
    const calls: Call[] = [];
    let currentFill = "";
    const ctx = {
      save: () => calls.push({ type: "save", args: [] }),
      restore: () => calls.push({ type: "restore", args: [] }),
      fillRect: (...args: number[]) =>
        calls.push({ type: "fillRect", args: [...args, currentFill] }),
      set fillStyle(v: string) {
        currentFill = v;
        calls.push({ type: "fillStyle", args: [v] });
      },
      get fillStyle() {
        return currentFill;
      },
    };
    return { ctx: ctx as unknown as CanvasRenderingContext2D, calls };
  }

  function stubChart(yMax: number): { chart: unknown; calls: Call[] } {
    const { ctx, calls } = stubCtx();
    const chart = {
      ctx,
      chartArea: { left: 0, right: 100, top: 0, bottom: 200 },
      scales: {
        y: {
          max: yMax,
          getPixelForValue: (v: number) => 200 - (v / yMax) * 200,
        },
      },
    };
    return { chart, calls };
  }

  function invoke(yMax: number): Call[] {
    const { chart, calls } = stubChart(yMax);
    punctualityBandPlugin.beforeDatasetsDraw!(
      chart as unknown as Chart<"bar">,
      { mode: "default", cancelable: true } as unknown as Parameters<
        NonNullable<typeof punctualityBandPlugin.beforeDatasetsDraw>
      >[1],
      {} as unknown as Parameters<
        NonNullable<typeof punctualityBandPlugin.beforeDatasetsDraw>
      >[2],
    );
    return calls;
  }

  it("draws only a green rect when yScale.max is below threshold (yMax=3)", () => {
    const calls = invoke(3);

    const fillRects = calls.filter(c => c.type === "fillRect");
    expect(fillRects).toHaveLength(1);

    const fillStyles = calls.filter(c => c.type === "fillStyle");
    expect(fillStyles).toHaveLength(1);
    expect(fillStyles[0].args).toEqual(["rgba(34,197,94,0.10)"]);

    // Green rect should cover full plot area (thresholdY=0, bottom=200).
    expect(fillRects[0].args).toEqual([0, 0, 100, 200, "rgba(34,197,94,0.10)"]);
  });

  it("draws green and red rects when yScale.max is above threshold (yMax=10)", () => {
    const calls = invoke(10);

    const fillRects = calls.filter(c => c.type === "fillRect");
    expect(fillRects).toHaveLength(2);

    const fillStyles = calls.filter(c => c.type === "fillStyle");
    expect(fillStyles).toHaveLength(2);
    expect(fillStyles[0].args).toEqual(["rgba(34,197,94,0.10)"]);
    expect(fillStyles[1].args).toEqual(["rgba(239,68,68,0.08)"]);

    // thresholdY = 200 - (6/10)*200 = 80
    // Green: from thresholdY (80) down to bottom (200), height 120
    expect(fillRects[0].args).toEqual([0, 80, 100, 120, "rgba(34,197,94,0.10)"]);
    // Red: from top (0) down to thresholdY (80), height 80
    expect(fillRects[1].args).toEqual([0, 0, 100, 80, "rgba(239,68,68,0.08)"]);
  });

  it("draws only green at the boundary (yMax === threshold), uses strict >", () => {
    const calls = invoke(PUNCTUALITY_THRESHOLD_MIN);

    const fillRects = calls.filter(c => c.type === "fillRect");
    expect(fillRects).toHaveLength(1);

    const fillStyles = calls.filter(c => c.type === "fillStyle");
    expect(fillStyles).toHaveLength(1);
    expect(fillStyles[0].args).toEqual(["rgba(34,197,94,0.10)"]);
    // No red color was ever set.
    expect(
      fillStyles.some(c => c.args[0] === "rgba(239,68,68,0.08)"),
    ).toBe(false);
  });
});
