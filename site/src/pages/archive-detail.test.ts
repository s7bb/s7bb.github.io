import { describe, it, expect, beforeEach, vi } from "vitest";
import { endpunktCell, renderArchiveDetail } from "./archive-detail.js";
import { _resetCache } from "../archive.js";
import { _primeDataBase } from "../config.js";
import type { Arrival } from "../data.js";

vi.mock("../charts/dailyByDirection.js", () => ({ renderDailyByDirection: vi.fn() }));

function a(overrides: Partial<Arrival>): Arrival {
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

describe("endpunktCell", () => {
  it("renders '{terminusLabelShort}' with --ok class when arrived with delay 0", () => {
    const html = endpunktCell(a({ terminus_status: "arrived", terminus_delay_minutes: 0 }));
    expect(html).toContain("München");
    expect(html).toContain("endpunkt--ok");
    expect(html).not.toContain("+");
  });

  it("renders '{terminusLabelShort} +N' with --ok class when arrived with positive delay", () => {
    const html = endpunktCell(a({ terminus_status: "arrived", terminus_delay_minutes: 4 }));
    expect(html).toContain("München +4");
    expect(html).toContain("endpunkt--ok");
  });

  it("floors negative terminus delays at 0", () => {
    const html = endpunktCell(a({ terminus_status: "arrived", terminus_delay_minutes: -3 }));
    expect(html).toContain("München");
    expect(html).not.toContain("-3");
    expect(html).not.toContain("+");
  });

  it("renders '{station} (Kurzwende)' with --shortturn class for short_turn", () => {
    const html = endpunktCell(a({ terminus_status: "short_turn", terminus_short_turn_station: "München-Solln" }));
    expect(html).toContain("München-Solln (Kurzwende)");
    expect(html).toContain("endpunkt--shortturn");
  });

  it("renders 'nicht angekommen' with --missed class for cancelled terminus", () => {
    const html = endpunktCell(a({ terminus_status: "cancelled" }));
    expect(html).toContain("nicht angekommen");
    expect(html).toContain("endpunkt--missed");
  });

  it("renders '-' for pending", () => {
    const html = endpunktCell(a({ terminus_status: "pending" }));
    expect(html).toContain("-");
  });

  it("renders '-' for null terminus_status", () => {
    const html = endpunktCell(a({ terminus_status: null }));
    expect(html).toContain("-");
  });

  it("renders '-' for Baierbrunn-cancelled (irrespective of terminus_status)", () => {
    const html = endpunktCell(a({ cancelled: true, terminus_status: "cancelled" }));
    expect(html).toContain("-");
    expect(html).not.toContain("nicht angekommen");
  });
});

describe("renderArchiveDetail hostile JSON", () => {
  beforeEach(() => {
    _resetCache();
    _primeDataBase("../data");
    vi.restoreAllMocks();
  });

  it("never injects markup from tampered aggregate or arrival fields", async () => {
    const hostile = {
      generated_at: "x", station: "Baierbrunn", line: "S7",
      period: "2026-04", finalized: true,
      arrivals: [a({
        scheduled_time: '<img src=x onerror="window.__pwned=1">T<svg>',
        actual_time: "<script>1</script>T<b>x</b>",
        delay_minutes: '<img src=x onerror="window.__pwned=1">' as unknown as number,
      })],
      aggregates: {
        total: 1, on_time: '<img src=x onerror="window.__pwned=1">',
        late: "<script>1</script>", cancelled: 0, avg_delay_min: {},
        by_direction: {
          muenchen:       { total: 1, on_time: 1, late: 0, cancelled: 0, avg_delay_min: 0 },
          wolfratshausen: { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0 },
        },
      },
      daily: [],
      daily_by_direction: { muenchen: [], wolfratshausen: [] },
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(hostile), { status: 200 }) as Response,
    );
    const c = document.createElement("div");
    await renderArchiveDetail("2026-04", c);
    expect(c.querySelector("img")).toBeNull();
    expect(c.querySelector("script")).toBeNull();
    expect(c.querySelector("svg")).toBeNull();
    expect(c.querySelector("table b")).toBeNull();
    expect((window as { __pwned?: number }).__pwned).toBeUndefined();
    expect(c.textContent).toContain("0 pünktlich");
    expect(c.textContent).toContain("April 2026");
  });
});
