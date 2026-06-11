import { describe, it, expect, vi } from "vitest";
import type { S7Data, Arrival } from "../data.js";

// Stub the chart modules so renderStats doesn't touch a canvas under jsdom.
vi.mock("../charts/statusPie.js", () => ({ renderStatusPie: vi.fn() }));
vi.mock("../charts/avgDelayLine.js", () => ({ renderAvgDelayLine: vi.fn() }));

import { renderStats } from "./stats.js";

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
    disruption: null,
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
    expected_slots: { today: { muenchen: [], wolfratshausen: [] } },
  };
}

describe("hostile aggregates from latest.json", () => {
  it("never injects markup from tampered numeric fields", () => {
    const data = fixture([arrival({})]);
    const pwn = '<img src=x onerror="window.__pwned=1">';

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const last7 = data.aggregates.last_7_days as any;
    last7.by_direction.muenchen.total = pwn;
    last7.by_direction.muenchen.avg_delay_min = "<script>window.__pwned=1</script>";
    last7.by_direction.muenchen.missing = pwn;
    last7.total = pwn;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (data as any).window_days = pwn;

    const c = document.createElement("div");
    renderStats(data, c);

    expect(c.querySelector("img")).toBeNull();
    expect(c.querySelector("script")).toBeNull();
    expect((window as { __pwned?: number }).__pwned).toBeUndefined();
    // Tampered numerics coerce to 0 via num().
    expect(c.textContent).toContain("0 Züge");
  });
});

describe("top disruption reasons", () => {
  it("lists top disruption reasons by cause_text falling back to category", () => {
    const data = fixture([
      arrival({ disruption: { category: "Störung", cause_code: 34, cause_text: "Verspätung eines vorausfahrenden Zuges", window: null } }),
      arrival({ disruption: { category: "Störung", cause_code: 34, cause_text: "Verspätung eines vorausfahrenden Zuges", window: null } }),
      arrival({ disruption: { category: "Bauarbeiten", cause_code: null, cause_text: null, window: null } }),
    ]);
    const c = document.createElement("div");
    renderStats(data, c);
    const box = c.querySelector(".reasons-box");
    expect(box?.textContent).toContain("Verspätung eines vorausfahrenden Zuges");
    expect(box?.textContent).toContain("(2×)");
    expect(box?.textContent).toContain("Bauarbeiten");
  });
});
