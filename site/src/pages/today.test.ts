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

describe("arrival row <details> wrapper", () => {
  it("wraps each non-empty row in a details element with a summary", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", terminus_delay_minutes: 0 })]);
    const det = c.querySelector("details.arrival-row");
    expect(det).not.toBeNull();
    expect(det?.querySelector(":scope > summary")).not.toBeNull();
    expect(det?.querySelector(":scope > .arrival-detail")).not.toBeNull();
  });

  it("keeps empty (no-record) slots as plain div without details wrapper", () => {
    // Force a missing slot: expected_slots includes a time, arrivals is empty.
    const data = fixture([]);
    data.expected_slots.today.muenchen = ["2026-05-01T07:00:00"];
    const c = document.createElement("div");
    renderToday(data, c);
    expect(c.querySelector("details.arrival-row")).toBeNull();
    expect(c.querySelector(".arrival-row--empty")).not.toBeNull();
  });

  it("default state is collapsed (no [open] attribute on initial render)", () => {
    const c = renderInto([arrival({ terminus_status: "arrived" })]);
    const det = c.querySelector("details.arrival-row");
    expect(det?.hasAttribute("open")).toBe(false);
  });

  it("summary always contains time, direction, status badge", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", terminus_delay_minutes: 0 })]);
    const sum = c.querySelector("details.arrival-row > summary")!;
    expect(sum.querySelector(".arrival-time")).not.toBeNull();
    expect(sum.querySelector(".arrival-direction")).not.toBeNull();
    expect(sum.querySelector(".badge")).not.toBeNull();
  });

  it("summary contains chevron with aria-hidden", () => {
    const c = renderInto([arrival({ terminus_status: "arrived" })]);
    const chev = c.querySelector("details.arrival-row > summary .chev");
    expect(chev).not.toBeNull();
    expect(chev?.getAttribute("aria-hidden")).toBe("true");
  });
});

function panelOf(c: HTMLElement): HTMLElement {
  return c.querySelector("details.arrival-row > .arrival-detail") as HTMLElement;
}

function detailValue(panel: HTMLElement, label: string): string | undefined {
  const rows = panel.querySelectorAll(".detail-row");
  for (const r of rows) {
    if (r.querySelector(".detail-label")?.textContent?.trim().startsWith(label)) {
      return r.querySelector(".detail-value")?.textContent?.trim();
    }
  }
  return undefined;
}

describe("expand panel content", () => {
  it("Abfahrt Baierbrunn shows HH:MM (planmäßig) when on time", () => {
    const c = renderInto([arrival({ scheduled_time: "2026-05-01T08:42:00", delay_minutes: 0, terminus_status: "arrived" })]);
    expect(detailValue(panelOf(c), "Abfahrt Baierbrunn")).toBe("08:42 (planmäßig)");
  });

  it("Abfahrt Baierbrunn shows HH:MM (+N min) when delayed", () => {
    const c = renderInto([arrival({ scheduled_time: "2026-05-01T08:42:00", delay_minutes: 3, terminus_status: "arrived" })]);
    expect(detailValue(panelOf(c), "Abfahrt Baierbrunn")).toBe("08:42 (+3 min)");
  });

  it("Abfahrt Baierbrunn shows 'ausgefallen' for Baierbrunn-cancelled", () => {
    const c = renderInto([arrival({ scheduled_time: "2026-05-01T08:42:00", cancelled: true })]);
    expect(detailValue(panelOf(c), "Abfahrt Baierbrunn")).toBe("ausgefallen");
  });

  it("Ankunft uses terminus_delay_minutes, not Baierbrunn delay", () => {
    const c = renderInto([arrival({
      scheduled_time: "2026-05-01T08:42:00",
      delay_minutes: 0,
      terminus_status: "arrived",
      actual_time: "2026-05-01T08:42:00",
      terminus_delay_minutes: 3,
    })]);
    expect(detailValue(panelOf(c), "Ankunft München Hbf")).toMatch(/\+3 min/);
  });

  it("Ankunft floors negative terminus delays at 0", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", terminus_delay_minutes: -2 })]);
    expect(detailValue(panelOf(c), "Ankunft München Hbf")).toMatch(/\+0 min/);
  });

  it("Ankunft shows 'planmäßig' with no time when arrived and terminus_delay_minutes is null", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", terminus_delay_minutes: null })]);
    expect(detailValue(panelOf(c), "Ankunft München Hbf")).toBe("planmäßig");
  });

  it("Ankunft shows 'noch unterwegs' when pending", () => {
    const c = renderInto([arrival({ terminus_status: "pending" })]);
    expect(detailValue(panelOf(c), "Ankunft München Hbf")).toBe("noch unterwegs");
  });

  it("Ankunft shows 'nicht angekommen' when cancelled", () => {
    const c = renderInto([arrival({ terminus_status: "cancelled" })]);
    expect(detailValue(panelOf(c), "Ankunft München Hbf")).toBe("nicht angekommen");
  });

  it("Ankunft row omitted when terminus_status is null", () => {
    const c = renderInto([arrival({ terminus_status: null })]);
    expect(detailValue(panelOf(c), "Ankunft")).toBeUndefined();
  });

  it("Endete in row only when short_turn", () => {
    const cs = renderInto([arrival({ terminus_status: "short_turn", terminus_short_turn_station: "München-Solln" })]);
    expect(detailValue(panelOf(cs), "Endete in")).toBe("München-Solln (Kurzwende)");
    const ca = renderInto([arrival({ terminus_status: "arrived" })]);
    expect(detailValue(panelOf(ca), "Endete in")).toBeUndefined();
  });

  it("Zug row only when train_number is present", () => {
    const c1 = renderInto([arrival({ terminus_status: "arrived", train_number: "6824" })]);
    expect(detailValue(panelOf(c1), "Zug")).toBe("S 6824");
    const c2 = renderInto([arrival({ terminus_status: "arrived", train_number: null })]);
    expect(detailValue(panelOf(c2), "Zug")).toBeUndefined();
  });

  it("Grund row appears in panel and is removed from summary row when reason is set", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", reason: "Signalstörung" })]);
    expect(detailValue(panelOf(c), "Grund")).toBe("Signalstörung");
    expect(c.querySelector("details.arrival-row > summary .arrival-reason")).toBeNull();
  });

  it("Baierbrunn-cancelled with reason=null shows 'Zug ausgefallen — keine Fahrt' line and no separate Grund row", () => {
    const c = renderInto([arrival({ cancelled: true, reason: null })]);
    const panel = panelOf(c);
    expect(panel.textContent).toContain("Zug ausgefallen — keine Fahrt");
    expect(detailValue(panel, "Grund")).toBeUndefined();
  });

  it("Baierbrunn-cancelled with reason shows reason in Grund row", () => {
    const c = renderInto([arrival({ cancelled: true, reason: "Streik" })]);
    expect(detailValue(panelOf(c), "Grund")).toBe("Streik");
  });
});

describe("summary bar terminus items", () => {
  it("shows 'bis München' count when arrived > 0", () => {
    const c = renderInto([
      arrival({ direction_bucket: "muenchen", terminus_status: "arrived" }),
      arrival({ scheduled_time: "2026-05-01T08:30:00", direction_bucket: "muenchen", terminus_status: "arrived" }),
    ]);
    const bar = c.querySelectorAll(".direction-col")[0].querySelector(".summary-bar")!;
    expect(bar.textContent).toContain("2 bis München");
  });

  it("shows '⚠ N Kurzwende' when short_turn > 0", () => {
    const c = renderInto([arrival({ direction_bucket: "muenchen", terminus_status: "short_turn", terminus_short_turn_station: "Solln" })]);
    const bar = c.querySelectorAll(".direction-col")[0].querySelector(".summary-bar")!;
    expect(bar.textContent).toContain("1 Kurzwende");
  });

  it("shows '⊘ N nicht angekommen' when missed (cancelled terminus) > 0", () => {
    const c = renderInto([arrival({ direction_bucket: "muenchen", terminus_status: "cancelled" })]);
    const bar = c.querySelectorAll(".direction-col")[0].querySelector(".summary-bar")!;
    expect(bar.textContent).toContain("1 nicht angekommen");
  });

  it("suppresses all three terminus items when arrived+short_turn+missed = 0", () => {
    const c = renderInto([arrival({ direction_bucket: "muenchen", terminus_status: "pending" })]);
    const bar = c.querySelectorAll(".direction-col")[0].querySelector(".summary-bar")!;
    expect(bar.textContent).not.toContain("bis");
    expect(bar.textContent).not.toContain("Kurzwende");
    expect(bar.textContent).not.toContain("nicht angekommen");
  });

  it("uses 'Wolfratshausen' as terminus label for wolfratshausen bucket", () => {
    const c = renderInto([arrival({ direction_bucket: "wolfratshausen", terminus_status: "arrived" })]);
    // wolfratshausen is the right column.
    const bar = c.querySelectorAll(".direction-col")[1].querySelector(".summary-bar")!;
    expect(bar.textContent).toContain("1 bis Wolfratshausen");
  });
});
