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
