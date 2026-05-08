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
