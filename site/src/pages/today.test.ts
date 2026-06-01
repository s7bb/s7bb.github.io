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

// terminusLine renders as a second .badge inside the button summary, after the
// departure badge. Helper picks the trailing one out of the two-badge row.
function terminusBadge(c: HTMLElement): HTMLElement | null {
  const badges = c.querySelectorAll("button.arrival-row .badge");
  return badges.length >= 2 ? (badges[badges.length - 1] as HTMLElement) : null;
}

describe("terminus inline badge", () => {
  it("renders green 'pünktlich' badge when arrived and terminus_delay_minutes <= 0", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", terminus_delay_minutes: 0 })]);
    const el = terminusBadge(c);
    expect(el?.textContent?.trim()).toBe("pünktlich");
    expect(el?.classList.contains("badge--ok")).toBe(true);
  });

  it("renders '+7 min' badge with badge--late when arrived and terminus delay > 0", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", terminus_delay_minutes: 7 })]);
    const el = terminusBadge(c);
    expect(el?.textContent?.trim()).toBe("+7 min");
    expect(el?.classList.contains("badge--late")).toBe(true);
  });

  it("renders '+2 min' badge with badge--late when arrived and terminus delay between 1 and 5", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", terminus_delay_minutes: 2 })]);
    const el = terminusBadge(c);
    expect(el?.textContent?.trim()).toBe("+2 min");
    expect(el?.classList.contains("badge--late")).toBe(true);
  });

  it("floors negative terminus delays to 'pünktlich'", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", terminus_delay_minutes: -3 })]);
    const el = terminusBadge(c);
    expect(el?.textContent?.trim()).toBe("pünktlich");
    expect(el?.classList.contains("badge--ok")).toBe(true);
  });

  it("renders 'Kurzwende' badge with badge--late when terminus_status is short_turn", () => {
    const c = renderInto([arrival({ terminus_status: "short_turn", terminus_short_turn_station: "Solln" })]);
    const el = terminusBadge(c);
    expect(el?.textContent?.trim()).toBe("Kurzwende");
    expect(el?.classList.contains("badge--late")).toBe(true);
  });

  it("renders 'ausgefallen' badge with badge--cancelled when terminus_status is cancelled", () => {
    const c = renderInto([arrival({ terminus_status: "cancelled" })]);
    const el = terminusBadge(c);
    expect(el?.textContent?.trim()).toBe("ausgefallen");
    expect(el?.classList.contains("badge--cancelled")).toBe(true);
  });

  it("renders 'unterwegs' badge with badge--missing when terminus_status is pending", () => {
    const c = renderInto([arrival({ terminus_status: "pending" })]);
    const el = terminusBadge(c);
    expect(el?.textContent?.trim()).toBe("unterwegs");
    expect(el?.classList.contains("badge--missing")).toBe(true);
  });

  it("renders no terminus badge when terminus_status is null", () => {
    const c = renderInto([arrival({ terminus_status: null })]);
    expect(terminusBadge(c)).toBeNull();
  });

  it("renders no terminus badge when train is Baierbrunn-cancelled (departure badge already says ausgefallen)", () => {
    const c = renderInto([arrival({ cancelled: true, terminus_status: "cancelled" })]);
    expect(terminusBadge(c)).toBeNull();
    expect(c.querySelector("button.arrival-row.arrival-row--cancelled")).not.toBeNull();
  });

  it("falls back to 'ausgefallen' badge when short_turn but terminus_short_turn_station is null", () => {
    const c = renderInto([arrival({ terminus_status: "short_turn", terminus_short_turn_station: null })]);
    const el = terminusBadge(c);
    expect(el?.textContent?.trim()).toBe("ausgefallen");
    expect(el?.classList.contains("badge--cancelled")).toBe(true);
  });
});

describe("arrival row button + detail panel", () => {
  it("renders each non-empty row as a button with a linked detail panel via aria-controls", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", terminus_delay_minutes: 0 })]);
    const btn = c.querySelector("button.arrival-row") as HTMLButtonElement | null;
    expect(btn).not.toBeNull();
    const id = btn?.getAttribute("aria-controls");
    expect(id).toBeTruthy();
    const panel = c.querySelector(`#${id}`);
    expect(panel).not.toBeNull();
    expect(panel?.classList.contains("arrival-detail")).toBe(true);
  });

  it("keeps empty (no-record) slots as plain div without button wrapper", () => {
    // Force a missing slot: expected_slots includes a time, arrivals is empty.
    const data = fixture([]);
    data.expected_slots.today.muenchen = ["2026-05-01T07:00:00"];
    const c = document.createElement("div");
    renderToday(data, c);
    expect(c.querySelector("button.arrival-row")).toBeNull();
    expect(c.querySelector(".arrival-row--empty")).not.toBeNull();
  });

  it("default state is collapsed (aria-expanded=false, panel hidden)", () => {
    const c = renderInto([arrival({ terminus_status: "arrived" })]);
    const btn = c.querySelector("button.arrival-row") as HTMLButtonElement;
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    const panel = c.querySelector(`#${btn.getAttribute("aria-controls")}`) as HTMLElement;
    expect(panel.hasAttribute("hidden")).toBe(true);
  });

  it("button summary contains time, direction, status badge", () => {
    const c = renderInto([arrival({ terminus_status: "arrived", terminus_delay_minutes: 0 })]);
    const btn = c.querySelector("button.arrival-row")!;
    expect(btn.querySelector(".arrival-time")).not.toBeNull();
    expect(btn.querySelector(".arrival-direction")).not.toBeNull();
    expect(btn.querySelector(".badge")).not.toBeNull();
  });

  it("button summary contains chevron with aria-hidden", () => {
    const c = renderInto([arrival({ terminus_status: "arrived" })]);
    const chev = c.querySelector("button.arrival-row .chev");
    expect(chev).not.toBeNull();
    expect(chev?.getAttribute("aria-hidden")).toBe("true");
  });

  it("detail panel sits inside .slot-pair as a sibling spanning both columns", () => {
    const c = renderInto([arrival({ terminus_status: "arrived" })]);
    const pair = c.querySelector(".slot-pair")!;
    const btn = pair.querySelector("button.arrival-row") as HTMLButtonElement;
    const panel = pair.querySelector(".arrival-detail") as HTMLElement;
    expect(btn.parentElement).toBe(pair);
    expect(panel.parentElement).toBe(pair);
    expect(panel.id).toBe(btn.getAttribute("aria-controls"));
  });

  it("click on button toggles aria-expanded and panel hidden", () => {
    const c = renderInto([arrival({ terminus_status: "arrived" })]);
    document.body.appendChild(c);
    const btn = c.querySelector("button.arrival-row") as HTMLButtonElement;
    const panel = c.querySelector(`#${btn.getAttribute("aria-controls")}`) as HTMLElement;
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    expect(panel.hidden).toBe(true);
    btn.click();
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    expect(panel.hidden).toBe(false);
    btn.click();
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    expect(panel.hidden).toBe(true);
    c.remove();
  });
});

function panelOf(c: HTMLElement): HTMLElement {
  const btn = c.querySelector("button.arrival-row") as HTMLButtonElement;
  return c.querySelector(`#${btn.getAttribute("aria-controls")}`) as HTMLElement;
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
    expect(c.querySelector("button.arrival-row .arrival-reason")).toBeNull();
  });

  it("Baierbrunn-cancelled with reason=null shows 'Zug ausgefallen - keine Fahrt' line and no separate Grund row", () => {
    const c = renderInto([arrival({ cancelled: true, reason: null })]);
    const panel = panelOf(c);
    expect(panel.textContent).toContain("Zug ausgefallen - keine Fahrt");
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
