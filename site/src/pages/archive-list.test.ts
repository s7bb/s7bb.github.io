import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderArchiveList } from "./archive-list.js";
import { _resetCache } from "../archive.js";
import { _primeDataBase } from "../config.js";

vi.mock("../charts/monthsBar.js", () => ({ renderMonthsBar: vi.fn() }));

function month(overrides: Record<string, unknown>) {
  return {
    period: "2026-04", finalized: true,
    total: 100, on_time: 90, late: 8, cancelled: 2, avg_delay_min: 1.0,
    by_direction: {
      muenchen:       { total: 50, on_time: 45, late: 4, cancelled: 1, avg_delay_min: 1.0 },
      wolfratshausen: { total: 50, on_time: 45, late: 4, cancelled: 1, avg_delay_min: 1.0 },
    },
    ...overrides,
  };
}

function mockIndex(months: unknown[]): void {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ generated_at: "x", station: "Baierbrunn", months }), { status: 200 }) as Response,
  );
}

beforeEach(() => {
  _resetCache();
  _primeDataBase("../data");
  vi.restoreAllMocks();
});

describe("renderArchiveList", () => {
  it("renders a month link with German label", async () => {
    mockIndex([month({})]);
    const c = document.createElement("div");
    await renderArchiveList(c);
    const a = c.querySelector(".month-links a") as HTMLAnchorElement;
    expect(a.getAttribute("href")).toBe("#archiv/2026-04");
    expect(a.textContent).toBe("April 2026");
    expect(c.textContent).toContain("100 Züge");
  });

  it("never injects markup from tampered numeric fields", async () => {
    mockIndex([month({
      total: '<img src=x onerror="window.__pwned=1">',
      on_time: "<script>window.__pwned=1</script>",
      late: { evil: true },
      cancelled: null,
    })]);
    const c = document.createElement("div");
    await renderArchiveList(c);
    expect(c.querySelector("img")).toBeNull();
    expect(c.querySelector("script")).toBeNull();
    expect((window as { __pwned?: number }).__pwned).toBeUndefined();
    expect(c.textContent).toContain("0 Züge");
  });

  it("never renders a month whose period carries a payload (filtered at load)", async () => {
    mockIndex([month({}), month({ period: '"><img src=x onerror="window.__pwned=1">' })]);
    const c = document.createElement("div");
    await renderArchiveList(c);
    expect(c.querySelectorAll(".month-links li")).toHaveLength(1);
    expect(c.querySelector("img")).toBeNull();
  });
});
