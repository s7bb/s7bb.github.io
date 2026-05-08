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
